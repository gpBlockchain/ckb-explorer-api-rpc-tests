from __future__ import annotations

import json
import unittest

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


class V1DailyStatisticsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: HIST-STATS-RPC-01
    def test_one_daily_indicator_is_isolated_and_strictly_time_ascending(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json("/v1/daily_statistics/transactions_count")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                rows = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(rows, list)
                timestamps = []
                for row in rows:
                    attributes = row.get("attributes")
                    self.assertEqual({"transactions_count", "created_at_unixtimestamp"}, set(attributes))
                    timestamps.append(int(attributes["created_at_unixtimestamp"]))
                self.assertEqual(sorted(timestamps), timestamps)
                self.assertEqual(len(timestamps), len(set(timestamps)))

    # TEST-MAP: HIST-STATS-RPC-02
    def test_daily_transaction_address_and_cell_snapshot_fields_are_returned_together(self) -> None:
        indicator = "transactions_count-addresses_count-live_cells_count-dead_cells_count"
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json(f"/v1/daily_statistics/{indicator}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                rows = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(rows, list)
                self.assertTrue(rows)
                self.assertEqual(
                    {"transactions_count", "addresses_count", "live_cells_count", "dead_cells_count",
                     "created_at_unixtimestamp"},
                    set(rows[-1]["attributes"]),
                )
                raise unittest.SkipTest(
                    f"{network.name} public CKB Indexer does not expose historical address/Cell state at the closed-day cutoff"
                )

    # TEST-MAP: HIST-STATS-RPC-03
    def test_daily_hash_difficulty_uncle_and_fee_fields_preserve_formula_units(self) -> None:
        indicator = "avg_hash_rate-avg_difficulty-uncle_rate-total_tx_fee"
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json(f"/v1/daily_statistics/{indicator}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                rows = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(rows, list)
                self.assertTrue(rows)
                attributes = rows[-1]["attributes"]
                self.assertEqual(
                    {"avg_hash_rate", "avg_difficulty", "uncle_rate", "total_tx_fee",
                     "created_at_unixtimestamp"},
                    set(attributes),
                )
                self.assertTrue(str(attributes["total_tx_fee"]).lstrip("-").isdecimal())
                raise unittest.SkipTest(
                    f"{network.name} full closed-day RPC block/Uncle snapshot is unavailable as a stable public oracle"
                )

    # TEST-MAP: HIST-STATS-RPC-04
    def test_daily_dao_capacity_supply_treasury_and_liquidity_share_one_snapshot(self) -> None:
        indicator = (
            "total_dao_deposit-total_depositors_count-occupied_capacity-locked_capacity-"
            "circulating_supply-treasury_amount-liquidity"
        )
        expected = set(indicator.split("-")) | {"created_at_unixtimestamp"}
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json(f"/v1/daily_statistics/{indicator}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                rows = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(rows, list)
                self.assertTrue(rows)
                self.assertEqual(expected, set(rows[-1]["attributes"]))
                raise unittest.SkipTest(
                    f"{network.name} public RPC does not expose Explorer's historical DAO/account-book day-end snapshot"
                )

    # TEST-MAP: HIST-STATS-RPC-05
    def test_hodl_holder_and_activity_distributions_are_isolated_daily_buckets(self) -> None:
        indicator = "ckb_hodl_wave-holder_count-activity_address_contract_distribution"
        expected = set(indicator.split("-")) | {"created_at_unixtimestamp"}
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json(f"/v1/daily_statistics/{indicator}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                rows = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(rows, list)
                self.assertTrue(rows)
                self.assertEqual(expected, set(rows[-1]["attributes"]))
                raise unittest.SkipTest(
                    f"{network.name} public Indexer has no historical output-age/holder snapshot at the Daily cutoff"
                )

    # TEST-MAP: HIST-STATS-RPC-06
    def test_combined_indicator_cache_is_stable_and_keeps_both_fields(self) -> None:
        path = "/v1/daily_statistics/transactions_count-avg_hash_rate"
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    first = oracle.explorer_json(path)
                    second = oracle.explorer_json(path)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(first, second)
                rows = first.get("data") if isinstance(first, dict) else None
                self.assertIsInstance(rows, list)
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(
                        {"transactions_count", "avg_hash_rate", "created_at_unixtimestamp"},
                        set(row["attributes"]),
                    )
                raise unittest.SkipTest(
                    f"{network.name} public endpoint does not expose Daily record-version mutation control"
                )

    # TEST-MAP: HIST-STATS-RPC-07
    def test_unknown_daily_indicator_returns_422_code_1024(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    status, raw = _raw_explorer_response(oracle, "/v1/daily_statistics/not-a-daily-indicator")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                body = json.loads(raw)
                self.assertEqual(422, status)
                self.assertIsInstance(body, list)
                self.assertEqual(1024, body[0].get("code"))
                self.assertNotIn("data", body[0])
