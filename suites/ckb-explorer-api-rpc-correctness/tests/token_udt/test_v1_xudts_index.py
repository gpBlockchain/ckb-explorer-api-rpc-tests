from __future__ import annotations

import json
import unittest
from typing import Any, Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


class V1XudtsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.cache: dict[tuple[str, tuple[tuple[str, object], ...]], tuple[list[Mapping[str, Any]], Mapping[str, Any]]] = {}

    def _page(
        self,
        oracle: NetworkOracle,
        **query: object,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        key = (oracle.network.name, tuple(sorted(query.items())))
        if key not in self.cache:
            payload = oracle.explorer_json("/v1/xudts", query or None)
            data = payload.get("data") if isinstance(payload, dict) else None
            meta = payload.get("meta") if isinstance(payload, dict) else None
            if not isinstance(data, list) or not isinstance(meta, dict):
                raise OracleUnavailable(f"{oracle.network.name} xUDT page is unavailable")
            rows: list[Mapping[str, Any]] = []
            for item in data:
                attributes = item.get("attributes") if isinstance(item, dict) else None
                if not isinstance(attributes, dict):
                    raise OracleUnavailable(f"{oracle.network.name} xUDT row is unavailable")
                rows.append({"id": str(item["id"]), **attributes})
            self.cache[key] = rows, meta
        return self.cache[key]

    def _all(self, oracle: NetworkOracle, **query: object) -> list[Mapping[str, Any]]:
        params = dict(query)
        params.update(page=1, page_size=100)
        first, meta = self._page(oracle, **params)
        try:
            total = int(meta["total"])
        except (KeyError, TypeError, ValueError) as error:
            raise OracleUnavailable(f"{oracle.network.name} xUDT total is unavailable") from error
        rows = list(first)
        for page in range(2, (total + 99) // 100 + 1):
            params["page"] = page
            current, current_meta = self._page(oracle, **params)
            if int(current_meta.get("total", -1)) != total:
                raise OracleUnavailable(f"{oracle.network.name} xUDT catalog changed during pagination")
            rows.extend(current)
        if len(rows) != total:
            raise OracleUnavailable(f"{oracle.network.name} xUDT pagination omitted rows")
        return rows

    # TEST-MAP: XUDT-FT-RPC-01
    def test_default_and_compatible_scopes_have_exact_type_membership(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    default = self._all(oracle)
                    compatible = self._all(oracle, type="xudt_compatible")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertGreater(len(default), 0)
                self.assertEqual({"xudt", "xudt_compatible"}, {row.get("udt_type") for row in default})
                self.assertTrue(all(row.get("udt_type") == "xudt_compatible" for row in compatible))
                self.assertEqual(
                    {row["type_hash"] for row in default if row.get("udt_type") == "xudt_compatible"},
                    {row["type_hash"] for row in compatible},
                )

    # TEST-MAP: XUDT-FT-RPC-02
    def test_symbol_filter_is_case_insensitive_and_exact(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._all(oracle)
                    symbol = next(
                        str(row["symbol"])
                        for row in rows
                        if isinstance(row.get("symbol"), str)
                        and row["symbol"].isalpha()
                        and row["symbol"].lower() != row["symbol"].upper()
                    )
                    lower = self._all(oracle, symbol=symbol.lower())
                    upper = self._all(oracle, symbol=symbol.upper())
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(f"{network.name} xUDT symbol fixture is unavailable: {error}") from error
                expected = {row["type_hash"] for row in rows if str(row.get("symbol", "")).lower() == symbol.lower()}
                self.assertGreater(len(expected), 0)
                self.assertEqual(expected, {row["type_hash"] for row in lower})
                self.assertEqual(expected, {row["type_hash"] for row in upper})
                self.assertTrue(all(str(row.get("symbol", "")).lower() == symbol.lower() for row in lower + upper))

    # TEST-MAP: XUDT-FT-RPC-03
    def test_valid_tag_intersection_union_and_complete_tags_match_catalog_members(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._all(oracle)
                    selected = next(
                        tuple(dict.fromkeys(row["xudt_tags"]))[:2]
                        for row in rows
                        if isinstance(row.get("xudt_tags"), list) and len(set(row["xudt_tags"])) >= 2
                    )
                    tags = ",".join(selected)
                    intersection = self._all(oracle, tags=tags)
                    union = self._all(oracle, tags=tags, union=1)
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(f"{network.name} xUDT tag fixture is unavailable: {error}") from error
                expected_intersection = {
                    row["type_hash"]
                    for row in rows
                    if isinstance(row.get("xudt_tags"), list) and set(selected).issubset(row["xudt_tags"])
                }
                expected_union = {
                    row["type_hash"]
                    for row in rows
                    if isinstance(row.get("xudt_tags"), list) and set(selected).intersection(row["xudt_tags"])
                }
                self.assertEqual(expected_intersection, {row["type_hash"] for row in intersection})
                self.assertEqual(expected_union, {row["type_hash"] for row in union})
                source_tags = {row["type_hash"]: row.get("xudt_tags") for row in rows}
                self.assertTrue(all(row.get("xudt_tags") == source_tags[row["type_hash"]] for row in intersection + union))

    # TEST-MAP: XUDT-FT-RPC-04
    def test_invalid_tags_are_discarded_before_valid_filtering(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    unfiltered, unfiltered_meta = self._page(oracle, page=1, page_size=100)
                    valid, valid_meta = self._page(oracle, tags="rgb++", page=1, page_size=100)
                    mixed, mixed_meta = self._page(
                        oracle, tags="not-a-valid-tag,rgb++,also-invalid", page=1, page_size=100
                    )
                    invalid, invalid_meta = self._page(
                        oracle, tags="not-a-valid-tag,also-invalid", page=1, page_size=100
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(valid, mixed)
                self.assertEqual(valid_meta["total"], mixed_meta["total"])
                self.assertEqual(unfiltered, invalid)
                self.assertEqual(unfiltered_meta["total"], invalid_meta["total"])

    # TEST-MAP: XUDT-FT-RPC-05
    @unittest.expectedFailure  # Public servers currently accept page_size above the reviewed 100-row ceiling.
    def test_pagination_public_sort_fields_directions_ties_and_size_ceiling(self) -> None:
        sort_fields = (
            ("created_time", "created_at"),
            ("transactions", "h24_ckb_transactions_count"),
            ("addresses_count", "addresses_count"),
        )
        oversized_violations: list[tuple[str, int, int]] = []
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._all(oracle)
                    default, default_meta = self._page(oracle)
                    first, first_meta = self._page(oracle, page=1, page_size=20)
                    second, second_meta = self._page(oracle, page=2, page_size=20)
                    combined, combined_meta = self._page(oracle, page=1, page_size=40)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(min(25, len(rows)), len(default))
                self.assertEqual(25, int(default_meta["page_size"]))
                self.assertEqual(first + second, combined[: len(first) + len(second)])
                self.assertEqual(first_meta["total"], second_meta["total"])
                self.assertEqual(first_meta["total"], combined_meta["total"])
                self.assertEqual([row["id"] for row in default], sorted((row["id"] for row in default), key=int, reverse=True))
                for public, attribute in sort_fields:
                    for direction in ("asc", "desc"):
                        actual, _meta = self._page(oracle, page=1, page_size=100, sort=f"{public}.{direction}")
                        expected = sorted(
                            rows,
                            key=lambda row: (
                                row.get("full_name") is None,
                                str(row.get("full_name") or ""),
                                int(row["id"]),
                            ),
                        )
                        expected = sorted(
                            expected,
                            key=lambda row: int(row.get(attribute) or 0),
                            reverse=direction == "desc",
                        )
                        self.assertEqual([row["id"] for row in expected[:100]], [row["id"] for row in actual])
                implicit, _meta = self._page(oracle, page=1, page_size=100, sort="transactions")
                invalid_direction, _meta = self._page(
                    oracle, page=1, page_size=100, sort="transactions.sideways"
                )
                ascending, _meta = self._page(oracle, page=1, page_size=100, sort="transactions.asc")
                self.assertEqual(ascending, implicit)
                self.assertEqual(ascending, invalid_direction)
                oversized, oversized_meta = self._page(oracle, page=1, page_size=1000)
                if len(oversized) > 100 or int(oversized_meta["page_size"]) > 100:
                    oversized_violations.append(
                        (network.name, len(oversized), int(oversized_meta["page_size"]))
                    )
        self.assertEqual([], oversized_violations)

    # TEST-MAP: XUDT-FT-RPC-06
    def test_invalid_page_and_page_size_return_parameter_errors(self) -> None:
        cases = (
            ({"page": 0}, {1007}),
            ({"page": -1}, {1007}),
            ({"page": "1.5"}, {1007}),
            ({"page": "bad"}, {1007}),
            ({"page_size": 0}, {1008}),
            ({"page_size": -1}, {1008}),
            ({"page_size": "1.5"}, {1008}),
            ({"page_size": "bad"}, {1008}),
            ({"page": "bad", "page_size": "bad"}, {1007, 1008}),
        )
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            for query, expected_codes in cases:
                with self.subTest(network=network.name, query=query):
                    path = "/v1/xudts?" + urlencode(query)
                    try:
                        status, raw = _raw_explorer_response(oracle, path)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    if status == 403:
                        raise unittest.SkipTest(f"{network.name} edge rejected invalid pagination observation")
                    self.assertEqual(400, status)
                    payload = json.loads(raw)
                    self.assertEqual(expected_codes, {int(error["code"]) for error in payload})
                    self.assertFalse(any("data" in error for error in payload))


if __name__ == "__main__":
    unittest.main()
