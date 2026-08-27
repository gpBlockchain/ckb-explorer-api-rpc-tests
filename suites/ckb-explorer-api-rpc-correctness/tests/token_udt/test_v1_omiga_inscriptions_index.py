from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V1OmigaInscriptionsIndexRpcCorrectnessTests(unittest.TestCase):
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
            payload = oracle.explorer_json("/v1/omiga_inscriptions", query or None)
            data = payload.get("data") if isinstance(payload, dict) else None
            meta = payload.get("meta") if isinstance(payload, dict) else None
            if not isinstance(data, list) or not isinstance(meta, dict):
                raise OracleUnavailable(f"{oracle.network.name} Omiga inscription page is unavailable")
            rows: list[Mapping[str, Any]] = []
            for item in data:
                attributes = item.get("attributes") if isinstance(item, dict) else None
                if not isinstance(attributes, dict):
                    raise OracleUnavailable(f"{oracle.network.name} Omiga inscription row is unavailable")
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
            raise OracleUnavailable(f"{oracle.network.name} Omiga inscription total is unavailable") from error
        rows = list(first)
        for page in range(2, (total + 99) // 100 + 1):
            params["page"] = page
            current, current_meta = self._page(oracle, **params)
            if int(current_meta.get("total", -1)) != total:
                raise OracleUnavailable(f"{oracle.network.name} Omiga catalog changed during pagination")
            rows.extend(current)
        if len(rows) != total:
            raise OracleUnavailable(f"{oracle.network.name} Omiga pagination omitted rows")
        return rows

    # TEST-MAP: OMIGA-RPC-01
    def test_current_members_keep_minting_and_rebase_descendants_but_exclude_closed_predecessors(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._all(oracle)
                    descendant = next(
                        row
                        for row in rows
                        if row.get("mint_status") == "rebase_start" and isinstance(row.get("pre_udt_hash"), str)
                    )
                    predecessor_payload = oracle.explorer_json(
                        f"/v1/omiga_inscriptions/{descendant['pre_udt_hash']}"
                    )
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(f"{network.name} Omiga rebase fixture is unavailable: {error}") from error
                predecessor_data = (
                    predecessor_payload.get("data") if isinstance(predecessor_payload, dict) else None
                )
                predecessor = (
                    predecessor_data.get("attributes") if isinstance(predecessor_data, dict) else None
                )
                if not isinstance(predecessor, dict):
                    raise unittest.SkipTest(f"{network.name} closed Omiga predecessor is unavailable")
                self.assertGreater(len(rows), 0)
                self.assertEqual(len(rows), len({row["type_hash"] for row in rows}))
                self.assertTrue(all(row.get("udt_type") == "omiga_inscription" for row in rows))
                self.assertIn("minting", {row["mint_status"] for row in rows})
                self.assertIn("rebase_start", {row["mint_status"] for row in rows})
                self.assertEqual("closed", predecessor.get("mint_status"))
                self.assertEqual(descendant["pre_udt_hash"], predecessor.get("type_hash"))
                self.assertNotIn(predecessor["type_hash"], {row["type_hash"] for row in rows})
                referenced_predecessors = {
                    row["pre_udt_hash"]
                    for row in rows
                    if isinstance(row.get("pre_udt_hash"), str)
                }
                self.assertTrue(
                    all(
                        row.get("mint_status") != "closed"
                        or row.get("type_hash") not in referenced_predecessors
                        for row in rows
                    )
                )

    # TEST-MAP: OMIGA-RPC-02
    def test_empty_current_catalog_has_empty_data_and_zero_meta(self) -> None:
        observed_empty_catalog = False
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, meta = self._page(oracle, page=1, page_size=100)
                    total = int(meta["total"])
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                if total != 0:
                    continue
                observed_empty_catalog = True
                self.assertEqual([], rows)
                self.assertEqual(0, int(meta["total"]))
                self.assertEqual(0, int(meta["total_pages"]))
        if not observed_empty_catalog:
            self.skipTest("public networks have no empty Omiga catalog fixture")

    # TEST-MAP: OMIGA-RPC-03
    def test_default_explicit_pages_and_confirmed_sort_fields_follow_current_member_order(self) -> None:
        numeric_sort_fields = (
            ("created_time", "created_at"),
            ("transactions", "h24_ckb_transactions_count"),
        )
        status_rank = {"minting": 0, "closed": 1, "rebase_start": 2}
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._all(oracle)
                    default, default_meta = self._page(oracle)
                    first, first_meta = self._page(oracle, page=1, page_size=20)
                    second, second_meta = self._page(oracle, page=2, page_size=20)
                    combined, combined_meta = self._page(oracle, page=1, page_size=40)
                    self.assertEqual(min(25, len(rows)), len(default))
                    self.assertEqual(25, int(default_meta["page_size"]))
                    self.assertEqual(first + second, combined[: len(first) + len(second)])
                    self.assertEqual(first_meta["total"], second_meta["total"])
                    self.assertEqual(first_meta["total"], combined_meta["total"])
                    self.assertEqual(
                        [row["id"] for row in default],
                        sorted((row["id"] for row in default), key=int, reverse=True),
                    )
                    base_ids = {row["id"] for row in rows}
                    for public, attribute in numeric_sort_fields:
                        for direction in ("asc", "desc"):
                            actual = self._all(oracle, sort=f"{public}.{direction}")
                            if {row["id"] for row in actual} != base_ids:
                                raise unittest.SkipTest(
                                    f"{network.name} Omiga catalog changed while checking sort order"
                                )
                            values = [int(row.get(attribute) or 0) for row in actual]
                            self.assertEqual(
                                values,
                                sorted(values, reverse=direction == "desc"),
                            )
                    for direction in ("asc", "desc"):
                        actual, _meta = self._page(
                            oracle, page=1, page_size=100, sort=f"mint_status.{direction}"
                        )
                        ranks = [status_rank[str(row["mint_status"])] for row in actual]
                        self.assertEqual(ranks, sorted(ranks, reverse=direction == "desc"))
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error


if __name__ == "__main__":
    unittest.main()
