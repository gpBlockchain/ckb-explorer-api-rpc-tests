from __future__ import annotations

import json
import unittest
from collections import defaultdict
from typing import Any, Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


class V1UdtsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _page(
        self,
        oracle: NetworkOracle,
        **query: object,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json("/v1/udts", query or None)
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise OracleUnavailable(f"{oracle.network.name} sUDT catalog page is unavailable")
        rows: list[Mapping[str, Any]] = []
        for item in data:
            attributes = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(attributes, dict):
                raise OracleUnavailable(f"{oracle.network.name} sUDT catalog row is unavailable")
            rows.append({"id": str(item["id"]), **attributes})
        return rows, meta

    # TEST-MAP: UDT-CATALOG-RPC-04
    def test_complete_catalog_contains_only_sudt_and_includes_both_publication_states(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    first, meta = self._page(oracle, page=1, page_size=100)
                    total = int(meta["total"])
                    rows = list(first)
                    for page in range(2, (total + 99) // 100 + 1):
                        current, current_meta = self._page(oracle, page=page, page_size=100)
                        self.assertEqual(total, int(current_meta["total"]))
                        rows.extend(current)
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(total, len(rows))
                self.assertEqual(total, len({row["id"] for row in rows}))
                self.assertTrue(all(row.get("udt_type") == "sudt" for row in rows))
                self.assertEqual({False, True}, {row.get("published") for row in rows})

    # TEST-MAP: UDT-CATALOG-RPC-05
    @unittest.expectedFailure  # Public servers accept page_size above the reviewed 100-record ceiling.
    def test_default_adjacent_and_oversized_pages_follow_the_reviewed_limits(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    default, default_meta = self._page(oracle)
                    first, first_meta = self._page(oracle, page=1, page_size=20)
                    second, second_meta = self._page(oracle, page=2, page_size=20)
                    combined, combined_meta = self._page(oracle, page=1, page_size=40)
                    oversized, oversized_meta = self._page(oracle, page=1, page_size=1000)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(min(25, int(default_meta["total"])), len(default))
                self.assertEqual(25, int(default_meta["page_size"]))
                self.assertEqual(first + second, combined[: len(first) + len(second)])
                self.assertEqual(first_meta["total"], second_meta["total"])
                self.assertEqual(first_meta["total"], combined_meta["total"])
                self.assertEqual(20, int(first_meta["page_size"]))
                self.assertEqual(20, int(second_meta["page_size"]))
                self.assertEqual(40, int(combined_meta["page_size"]))
                self.assertLessEqual(len(oversized), 100)
                self.assertLessEqual(int(oversized_meta["page_size"]), 100)

    # TEST-MAP: UDT-CATALOG-RPC-06
    def test_invalid_page_and_page_size_values_return_complete_parameter_errors(self) -> None:
        cases = (
            ({"page": 0}, {1007}),
            ({"page": -1}, {1007}),
            ({"page": "1.5"}, {1007}),
            ({"page": "not-a-number"}, {1007}),
            ({"page_size": 0}, {1008}),
            ({"page_size": -1}, {1008}),
            ({"page_size": "1.5"}, {1008}),
            ({"page_size": "not-a-number"}, {1008}),
            ({"page": "bad", "page_size": "bad"}, {1007, 1008}),
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                for query, expected_codes in cases:
                    path = "/v1/udts?" + urlencode(query)
                    try:
                        status, raw = _raw_explorer_response(oracle, path)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    if status == 403:
                        raise unittest.SkipTest(f"{network.name} edge rejected invalid pagination observation")
                    self.assertEqual(400, status)
                    payload = json.loads(raw)
                    self.assertIsInstance(payload, list)
                    self.assertEqual(expected_codes, {int(error["code"]) for error in payload})
                    self.assertFalse(any("data" in error for error in payload))

    # TEST-MAP: UDT-CATALOG-RPC-07
    def test_public_sort_fields_directions_and_ties_are_stable(self) -> None:
        cases = (
            (None, "id", "desc"),
            ("transactions", "h24_ckb_transactions_count", "asc"),
            ("transactions.asc", "h24_ckb_transactions_count", "asc"),
            ("transactions.desc", "h24_ckb_transactions_count", "desc"),
            ("transactions.invalid", "h24_ckb_transactions_count", "asc"),
            ("created_time.asc", "created_at", "asc"),
            ("created_time.desc", "created_at", "desc"),
            ("addresses_count.asc", "addresses_count", "asc"),
            ("addresses_count.desc", "addresses_count", "desc"),
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                for sort, field, direction in cases:
                    query: dict[str, object] = {"page_size": 100}
                    if sort is not None:
                        query["sort"] = sort
                    try:
                        rows, _meta = self._page(oracle, **query)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    if field == "id":
                        values = [int(row["id"]) for row in rows]
                    else:
                        try:
                            values = [int(str(row[field])) for row in rows]
                        except (KeyError, TypeError, ValueError) as error:
                            raise unittest.SkipTest(
                                f"{network.name} {field} sort values are unavailable"
                            ) from error
                    expected_values = sorted(values, reverse=direction == "desc")
                    self.assertEqual(expected_values, values)
                    tied: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
                    for value, row in zip(values, rows, strict=True):
                        tied[value].append(row)
                    for group in tied.values():
                        if len(group) < 2 or field == "id":
                            continue
                        names_and_ids = [
                            (
                                "".join(
                                    char
                                    for char in str(row.get("full_name")).casefold()
                                    if char.isalnum()
                                )
                                if row.get("full_name") is not None
                                else "\U0010ffff",
                                int(row["id"]),
                            )
                            for row in group
                        ]
                        self.assertEqual(sorted(names_and_ids), names_and_ids)


if __name__ == "__main__":
    unittest.main()
