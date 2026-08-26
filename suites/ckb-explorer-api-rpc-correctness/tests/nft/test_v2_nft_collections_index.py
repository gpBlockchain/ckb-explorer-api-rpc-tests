from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V2NftCollectionsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _page(
        self, oracle: NetworkOracle, query: Mapping[str, object] | None = None
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json("/v2/nft/collections", query)
        data = payload.get("data") if isinstance(payload, dict) else None
        pagination = payload.get("pagination") if isinstance(payload, dict) else None
        if (
            not isinstance(data, list)
            or any(not isinstance(row, dict) for row in data)
            or not isinstance(pagination, dict)
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT collection page is unavailable"
            )
        return data, pagination

    # TEST-MAP: NFT-COLL-RPC-06
    @unittest.expectedFailure
    def test_standard_filters_are_exact_and_partition_unfiltered_total(self) -> None:
        standards = ("m_nft", "nrc721", "spore", "cota")
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    _all_rows, all_pagination = self._page(oracle)
                    filtered = {
                        standard: self._page(oracle, {"type": standard})
                        for standard in standards
                    }
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                filtered_total = 0
                for standard, (rows, pagination) in filtered.items():
                    self.assertGreater(pagination["count"], 0)
                    self.assertTrue(all(row["standard"] == standard for row in rows))
                    filtered_total += int(pagination["count"])
                self.assertEqual(int(all_pagination["count"]), filtered_total)

    # TEST-MAP: NFT-COLL-RPC-07
    def test_tag_intersection_and_union_membership_follow_returned_tags(self) -> None:
        requested = {"layer-1-asset", "supply-limited"}
        tag_query = ",".join(sorted(requested))
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    intersection, intersection_pagination = self._page(
                        oracle, {"tags": tag_query}
                    )
                    union, union_pagination = self._page(
                        oracle, {"tags": tag_query, "union": "true"}
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                for row in intersection:
                    self.assertTrue(requested.issubset(set(row["tags"])))
                for row in union:
                    self.assertTrue(requested.intersection(row["tags"]))
                self.assertLessEqual(
                    int(intersection_pagination["count"]),
                    int(union_pagination["count"]),
                )
                self.assertGreater(int(union_pagination["count"]), 0)

    # TEST-MAP: NFT-COLL-RPC-09
    @unittest.expectedFailure
    def test_reviewed_sort_aliases_use_primary_value_and_timestamp_desc_tiebreaker(self) -> None:
        sort_fields = {
            "transactions": "h24_ckb_transactions_count",
            "holder": "holders_count",
            "minted": "items_count",
            "timestamp": "timestamp",
        }
        for network in self.settings.networks:
            for alias, field in sort_fields.items():
                for direction in ("asc", "desc"):
                    with self.subTest(
                        network=network.name, alias=alias, direction=direction
                    ):
                        oracle = NetworkOracle(network, self.settings)
                        try:
                            rows, _pagination = self._page(
                                oracle, {"sort": f"{alias}.{direction}"}
                            )
                        except OracleUnavailable as error:
                            raise unittest.SkipTest(str(error)) from error
                        self.assertGreater(len(rows), 1)
                        def sql_key(row: Mapping[str, Any]) -> tuple[object, ...]:
                            value = row[field]
                            timestamp = row["timestamp"]
                            if direction == "asc":
                                primary = (value is None, 0 if value is None else int(value))
                            else:
                                primary = (
                                    value is not None,
                                    0 if value is None else -int(value),
                                )
                            timestamp_desc = (
                                timestamp is not None,
                                0 if timestamp is None else -int(timestamp),
                            )
                            return primary + timestamp_desc

                        self.assertEqual(sorted(rows, key=sql_key), rows)

    # TEST-MAP: NFT-COLL-RPC-10
    def test_default_and_invalid_sort_fallbacks_are_stable(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    default_rows, _ = self._page(oracle)
                    repeated_rows, _ = self._page(oracle)
                    unknown_rows, _ = self._page(oracle, {"sort": "unknown.desc"})
                    invalid_rows, _ = self._page(oracle, {"sort": "id.sideways"})
                    missing_rows, _ = self._page(oracle, {"sort": "id"})
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                default_ids = [int(row["id"]) for row in default_rows]
                self.assertEqual(sorted(default_ids, reverse=True), default_ids)
                self.assertEqual(default_rows, repeated_rows)
                self.assertEqual(default_rows, unknown_rows)
                invalid_ids = [int(row["id"]) for row in invalid_rows]
                missing_ids = [int(row["id"]) for row in missing_rows]
                self.assertEqual(sorted(invalid_ids), invalid_ids)
                self.assertEqual(invalid_ids, missing_ids)

    # TEST-MAP: NFT-COLL-RPC-11
    @unittest.expectedFailure
    def test_adjacent_and_overflow_pages_match_pagination_metadata(self) -> None:
        overflow_metadata_errors: list[str] = []
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    first, first_pagination = self._page(oracle, {"page": 1})
                    second, second_pagination = self._page(oracle, {"page": 2})
                    overflow_page = int(first_pagination["pages"]) + 1
                    overflow, overflow_pagination = self._page(
                        oracle, {"page": overflow_page}
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                first_ids = [int(row["id"]) for row in first]
                second_ids = [int(row["id"]) for row in second]
                self.assertEqual(len(first), int(first_pagination["in"]))
                self.assertEqual(len(second), int(second_pagination["in"]))
                self.assertEqual(1, int(first_pagination["page"]))
                self.assertEqual(2, int(second_pagination["page"]))
                self.assertEqual(first_pagination["count"], second_pagination["count"])
                self.assertEqual(first_pagination["pages"], second_pagination["pages"])
                self.assertTrue(set(first_ids).isdisjoint(second_ids))
                self.assertEqual(
                    sorted(first_ids + second_ids, reverse=True), first_ids + second_ids
                )
                self.assertEqual([], overflow)
                self.assertEqual(overflow_page, int(overflow_pagination["page"]))
                if overflow_pagination["in"] != 0:
                    overflow_metadata_errors.append(
                        f"{network.name}: pagination.in={overflow_pagination['in']!r}"
                    )
                self.assertEqual(first_pagination["count"], overflow_pagination["count"])
        self.assertEqual([], overflow_metadata_errors)


if __name__ == "__main__":
    unittest.main()
