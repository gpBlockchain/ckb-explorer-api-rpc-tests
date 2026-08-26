from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.token_udt.test_v1_udts_download_csv import SMALL_UDTS
from tests.token_udt.test_v1_xudts_snapshot import SNAPSHOT_XUDTS


ALLOWED_TYPES = {"sudt", "xudt", "xudt_compatible", "ssri"}


class V1FungibleTokensIndexRpcCorrectnessTests(unittest.TestCase):
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
            payload = oracle.explorer_json("/v1/fungible_tokens", query or None)
            data = payload.get("data") if isinstance(payload, dict) else None
            meta = payload.get("meta") if isinstance(payload, dict) else None
            if not isinstance(data, list) or not isinstance(meta, dict):
                raise OracleUnavailable(f"{oracle.network.name} fungible-token page is unavailable")
            rows: list[Mapping[str, Any]] = []
            for item in data:
                attributes = item.get("attributes") if isinstance(item, dict) else None
                if not isinstance(attributes, dict):
                    raise OracleUnavailable(f"{oracle.network.name} fungible-token row is unavailable")
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
            raise OracleUnavailable(f"{oracle.network.name} fungible-token total is unavailable") from error
        rows = list(first)
        for page in range(2, (total + 99) // 100 + 1):
            params["page"] = page
            current, current_meta = self._page(oracle, **params)
            if int(current_meta.get("total", -1)) != total:
                raise OracleUnavailable(f"{oracle.network.name} fungible-token catalog changed during pagination")
            rows.extend(current)
        if len(rows) != total:
            raise OracleUnavailable(f"{oracle.network.name} fungible-token pagination omitted rows")
        return rows

    def _compatible_hash(self, oracle: NetworkOracle) -> str:
        payload = oracle.explorer_json(
            "/v1/xudts", {"type": "xudt_compatible", "page": 1, "page_size": 100}
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise OracleUnavailable(f"{oracle.network.name} xUDT-compatible catalog is unavailable")
        for row in data:
            attributes = row.get("attributes") if isinstance(row, dict) else None
            if (
                isinstance(attributes, dict)
                and attributes.get("published") is True
                and attributes.get("udt_type") == "xudt_compatible"
                and isinstance(attributes.get("type_hash"), str)
            ):
                return attributes["type_hash"]
        raise OracleUnavailable(f"{oracle.network.name} published xUDT-compatible fixture is unavailable")

    # TEST-MAP: XUDT-FT-RPC-09
    def test_catalog_contains_only_published_four_type_members_and_known_members_of_each_available_type(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            present_types: set[str] = set()
            with self.subTest(network=network.name, membership="four-type-scope"):
                try:
                    rows = self._all(oracle)
                    compatible_hash = self._compatible_hash(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertGreater(len(rows), 0)
                self.assertEqual(len(rows), len({row["type_hash"] for row in rows}))
                self.assertTrue(all(row.get("published") is True for row in rows))
                self.assertTrue(all(row.get("udt_type") in ALLOWED_TYPES for row in rows))
                hashes = {row["type_hash"] for row in rows}
                self.assertIn(SMALL_UDTS[network.name][0], hashes)
                self.assertIn(SNAPSHOT_XUDTS[network.name], hashes)
                self.assertIn(compatible_hash, hashes)
                present_types = {str(row.get("udt_type")) for row in rows}
                self.assertTrue({"sudt", "xudt", "xudt_compatible"}.issubset(present_types))
            with self.subTest(network=network.name, membership="ssri"):
                if "ssri" not in present_types:
                    raise unittest.SkipTest(f"{network.name} published SSRI fungible-token fixture is unavailable")

    # TEST-MAP: XUDT-FT-RPC-10
    def test_tag_intersection_union_meta_and_unique_members_match_full_catalog(self) -> None:
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
                    raise unittest.SkipTest(f"{network.name} fungible-token tag fixture is unavailable: {error}") from error
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
                self.assertEqual(len(intersection), len({row["type_hash"] for row in intersection}))
                self.assertEqual(len(union), len({row["type_hash"] for row in union}))
                self.assertTrue(all(row.get("udt_type") in {"xudt", "xudt_compatible"} for row in intersection + union))


if __name__ == "__main__":
    unittest.main()
