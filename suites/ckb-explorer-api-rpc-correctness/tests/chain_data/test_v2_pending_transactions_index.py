from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V2PendingTransactionsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.checked_networks: set[str] = set()

    def _assert_network_pair(self, oracle: NetworkOracle) -> None:
        if oracle.network.name in self.checked_networks:
            return
        try:
            api_genesis = oracle.detail_attributes(0)
            rpc_genesis = oracle.block(0)
            api_tip = oracle.api_tip_height()
            rpc_tip = oracle.rpc_tip_height()
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        rpc_header = rpc_genesis.get("header")
        self.assertIsInstance(rpc_header, dict)
        self.assertEqual(rpc_header.get("hash"), api_genesis.get("block_hash"))
        self.assertLessEqual(api_tip, rpc_tip)
        self.assertLessEqual(rpc_tip - api_tip, self.settings.max_lag_blocks)
        self.checked_networks.add(oracle.network.name)

    def _pool(
        self,
        oracle: NetworkOracle,
    ) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
        try:
            result = oracle.rpc_result("get_raw_tx_pool", [True])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        pending = result.get("pending") if isinstance(result, dict) else None
        proposed = result.get("proposed") if isinstance(result, dict) else None
        if not isinstance(pending, dict) or not isinstance(proposed, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC verbose transaction-pool result is unavailable"
            )
        if not all(isinstance(value, dict) for value in pending.values()):
            raise unittest.SkipTest(f"{oracle.network.name} RPC pending metadata is unavailable")
        if not all(isinstance(value, dict) for value in proposed.values()):
            raise unittest.SkipTest(f"{oracle.network.name} RPC proposed metadata is unavailable")
        return pending, proposed

    def _observe(
        self,
        oracle: NetworkOracle,
        queries: tuple[Mapping[str, object] | None, ...],
    ) -> tuple[
        tuple[tuple[list[Mapping[str, Any]], Mapping[str, Any]], ...],
        dict[str, Mapping[str, Any]],
        dict[str, Mapping[str, Any]],
    ]:
        self._assert_network_pair(oracle)
        before_pending, before_proposed = self._pool(oracle)
        observations: list[tuple[list[Mapping[str, Any]], Mapping[str, Any]]] = []
        try:
            for query in queries:
                payload = oracle.explorer_json("/v2/pending_transactions", query)
                data = payload.get("data") if isinstance(payload, dict) else None
                meta = payload.get("meta") if isinstance(payload, dict) else None
                self.assertIsInstance(data, list)
                self.assertIsInstance(meta, dict)
                self.assertTrue(all(isinstance(row, dict) for row in data))
                observations.append((data, meta))
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        after_pending, after_proposed = self._pool(oracle)
        if before_pending != after_pending or before_proposed != after_proposed:
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC pending/proposed transaction-pool snapshot changed"
            )
        return tuple(observations), before_pending, before_proposed

    def _created_milliseconds(self, value: object) -> int:
        self.assertIsInstance(value, str)
        try:
            created = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            self.fail(f"created_at is not ISO-8601: {value!r}; {error}")
        self.assertIsNotNone(created.tzinfo)
        utc = created.astimezone(timezone.utc)
        delta = utc - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000

    # TEST-MAP: PENDING-RPC-01
    def test_returned_members_and_fees_match_stable_rpc_pool(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                observations, pending, proposed = self._observe(oracle, (None,))
                data, _meta = observations[0]
                pool = pending | proposed
                hashes = [str(row.get("transaction_hash")) for row in data]
                self.assertEqual(len(hashes), len(set(hashes)))
                foreign = sorted(set(hashes) - set(pool))
                if foreign:
                    raise unittest.SkipTest(
                        f"{network.name} Explorer and RPC transaction pools are not from the same source: "
                        f"{foreign[:3]}"
                    )
                for row in data:
                    transaction_hash = str(row.get("transaction_hash"))
                    self.assertEqual(
                        decode_hex_int(pool[transaction_hash].get("fee"), "pool.fee"),
                        int(row.get("transaction_fee")),
                    )

    # TEST-MAP: PENDING-RPC-02
    def test_returned_item_projection_timestamp_and_fee_match_rpc(self) -> None:
        expected_keys = {
            "transaction_hash",
            "capacity_involved",
            "transaction_fee",
            "created_at",
            "create_timestamp",
        }
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                observations, pending, proposed = self._observe(oracle, (None,))
                data, _meta = observations[0]
                if not data:
                    raise unittest.SkipTest(f"{network.name} pending list has no observable item")
                pool = pending | proposed
                for row in data:
                    self.assertEqual(expected_keys, set(row))
                    transaction_hash = str(row.get("transaction_hash"))
                    if transaction_hash not in pool:
                        raise unittest.SkipTest(
                            f"{network.name} Explorer and RPC transaction pools are not from the same source"
                        )
                    self.assertEqual(
                        decode_hex_int(pool[transaction_hash].get("fee"), "pool.fee"),
                        int(row.get("transaction_fee")),
                    )
                    self.assertEqual(
                        self._created_milliseconds(row.get("created_at")),
                        int(row.get("create_timestamp")),
                    )

    # TEST-MAP: PENDING-RPC-05
    def test_time_sort_directions_match_created_at(self) -> None:
        queries = (
            {"sort": "time", "page_size": 100},
            {"sort": "time.asc", "page_size": 100},
            {"sort": "time.desc", "page_size": 100},
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                observations, _pending, _proposed = self._observe(oracle, queries)
                rows = [item[0] for item in observations]
                hash_sets = [{row.get("transaction_hash") for row in data} for data in rows]
                if len(hash_sets[0]) < 2 or any(value != hash_sets[0] for value in hash_sets[1:]):
                    raise unittest.SkipTest(f"{network.name} stable pending time-sort sample is unavailable")
                times = [
                    [self._created_milliseconds(row.get("created_at")) for row in data]
                    for data in rows
                ]
                if len(set(times[0])) < 2:
                    raise unittest.SkipTest(f"{network.name} pending sample has no distinct created_at values")
                self.assertEqual(rows[0], rows[1])
                self.assertEqual(sorted(times[0]), times[0])
                self.assertEqual(sorted(times[2], reverse=True), times[2])

    # TEST-MAP: PENDING-RPC-06
    def test_fee_sort_directions_match_rpc_verified_fees(self) -> None:
        queries = (
            {"sort": "fee", "page_size": 100},
            {"sort": "fee.asc", "page_size": 100},
            {"sort": "fee.desc", "page_size": 100},
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                observations, pending, proposed = self._observe(oracle, queries)
                rows = [item[0] for item in observations]
                hash_sets = [{str(row.get("transaction_hash")) for row in data} for data in rows]
                if len(hash_sets[0]) < 2 or any(value != hash_sets[0] for value in hash_sets[1:]):
                    raise unittest.SkipTest(f"{network.name} stable pending fee-sort sample is unavailable")
                pool = pending | proposed
                if not hash_sets[0].issubset(pool):
                    raise unittest.SkipTest(
                        f"{network.name} Explorer and RPC transaction pools are not from the same source"
                    )
                fees = [
                    [decode_hex_int(pool[str(row.get("transaction_hash"))].get("fee"), "pool.fee") for row in data]
                    for data in rows
                ]
                if len(set(fees[0])) < 2:
                    raise unittest.SkipTest(f"{network.name} pending sample has no distinct fees")
                self.assertEqual(rows[0], rows[1])
                self.assertEqual(sorted(fees[0]), fees[0])
                self.assertEqual(sorted(fees[2], reverse=True), fees[2])
                for data, expected_fees in zip(rows, fees, strict=True):
                    self.assertEqual(
                        expected_fees,
                        [int(row.get("transaction_fee")) for row in data],
                    )

    # TEST-MAP: PENDING-RPC-08
    def test_invalid_and_case_insensitive_sort_forms_use_bounded_ordering(self) -> None:
        queries = (
            {"sort": "time.abcd", "page_size": 100},
            {"sort": "time.asc", "page_size": 100},
            {"sort": "time.ASC", "page_size": 100},
            {"sort": "time.desc", "page_size": 100},
            {"sort": "time.DESC", "page_size": 100},
            {"sort": "unknown", "page_size": 100},
            {"sort": "unknown.asc", "page_size": 100},
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                observations, _pending, _proposed = self._observe(oracle, queries)
                rows = [item[0] for item in observations]
                if len(rows[0]) < 2:
                    raise unittest.SkipTest(f"{network.name} pending sort sample is unavailable")
                hash_sets = [{row.get("transaction_hash") for row in data} for data in rows]
                if any(value != hash_sets[0] for value in hash_sets[1:]):
                    raise unittest.SkipTest(f"{network.name} pending sort observation changed")
                self.assertEqual(rows[0], rows[1])
                self.assertEqual(rows[1], rows[2])
                self.assertEqual(rows[3], rows[4])
                self.assertEqual(rows[5], rows[6])

    # TEST-MAP: PENDING-RPC-13
    def test_each_network_uses_an_independent_stable_rpc_snapshot(self) -> None:
        completed_networks: list[str] = []
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                observations, _pending, _proposed = self._observe(oracle, (None,))
                data, meta = observations[0]
                self.assertIsInstance(data, list)
                self.assertIsInstance(meta, dict)
                completed_networks.append(network.name)
        self.assertTrue(completed_networks)


if __name__ == "__main__":
    unittest.main()
