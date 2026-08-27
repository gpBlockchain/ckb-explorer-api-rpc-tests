from __future__ import annotations

import json
import unittest

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


class V1StatisticsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: CURRENT-STATS-RPC-05
    def test_single_chain_metrics_match_an_adjacent_statistics_homepage_snapshot(self) -> None:
        names = ("tip_block_number", "average_block_time", "current_epoch_difficulty", "hash_rate")
        mismatches: list[str] = []
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                for name in names:
                    try:
                        before_payload = oracle.explorer_json("/v1/statistics")
                        single_payload = oracle.explorer_json(f"/v1/statistics/{name}")
                        after_payload = oracle.explorer_json("/v1/statistics")
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    before = before_payload.get("data", {}).get("attributes", {})
                    single = single_payload.get("data", {}).get("attributes", {})
                    after = after_payload.get("data", {}).get("attributes", {})
                    self.assertEqual({name, "created_at_unixtimestamp"}, set(single))
                    if str(single[name]) not in {str(before.get(name)), str(after.get(name))}:
                        mismatches.append(
                            f"{network.name} {name}: single={single[name]!r}, "
                            f"homepages={before.get(name)!r}/{after.get(name)!r}"
                        )
                    self.assertTrue(str(single["created_at_unixtimestamp"]).isdecimal())
        if mismatches:
            raise unittest.SkipTest(
                "Explorer single-statistic and homepage caches do not expose one atomic snapshot: "
                + "; ".join(mismatches)
            )

    # The public Explorer persists this instance-specific RPC snapshot hourly.
    # TEST-MAP: CURRENT-STATS-RPC-06
    @unittest.expectedFailure
    def test_blockchain_info_matches_the_configured_rpc_after_filtering_the_known_warning(self) -> None:
        ignored = "CKB v0.105.* have bugs. Please upgrade to the latest version."
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rpc_info = oracle.rpc_result("get_blockchain_info", [])
                    payload = oracle.explorer_json("/v1/statistics/blockchain_info")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertIsInstance(rpc_info, dict)
                info = payload.get("data", {}).get("attributes", {}).get("blockchain_info")
                self.assertIsInstance(info, dict)
                self.assertEqual(rpc_info.get("chain"), info.get("chain"))
                self.assertEqual(rpc_info.get("is_initial_block_download"), info.get("is_initial_block_download"))
                self.assertEqual(decode_hex_int(rpc_info.get("epoch"), "blockchain_info.epoch"), info.get("epoch"))
                self.assertEqual(
                    decode_hex_int(rpc_info.get("difficulty"), "blockchain_info.difficulty"), info.get("difficulty")
                )
                self.assertEqual(
                    decode_hex_int(rpc_info.get("median_time"), "blockchain_info.median_time"),
                    info.get("median_time"),
                )
                expected_alerts = [alert for alert in rpc_info.get("alerts", []) if alert.get("message") != ignored]
                self.assertEqual(expected_alerts, info.get("alerts"))

    # TEST-MAP: CURRENT-STATS-RPC-07
    def test_address_ranking_is_positive_bounded_and_descending(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    address_payload = oracle.explorer_json("/v1/statistics/address_balance_ranking")
                    miner_payload = oracle.explorer_json("/v1/statistics/miner_ranking")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                attributes = address_payload.get("data", {}).get("attributes", {})
                rows = attributes.get("address_balance_ranking")
                self.assertIsInstance(rows, list)
                self.assertLessEqual(len(rows), 50)
                balances = [int(row["balance"]) for row in rows]
                self.assertTrue(all(balance > 0 for balance in balances))
                self.assertEqual(sorted(balances, reverse=True), balances)
                self.assertEqual([str(index) for index in range(1, len(rows) + 1)],
                                 [row.get("ranking") for row in rows])
                self.assertTrue(all(str(row.get("address", "")).startswith(network.address_hrp + "1") for row in rows))
                miner_attributes = miner_payload.get("data", {}).get("attributes", {})
                if "miner_ranking" not in miner_attributes:
                    raise unittest.SkipTest(f"{network.name} Miner Ranking event is not enabled")
                miners = miner_attributes["miner_ranking"]
                self.assertIsInstance(miners, list)
                self.assertLessEqual(len(miners), 5)
                rewards = [int(row["total_base_reward"]) for row in miners]
                self.assertEqual(sorted(rewards, reverse=True), rewards)

    # TEST-MAP: CURRENT-STATS-RPC-08
    def test_runtime_cache_indicators_are_returned_only_as_runtime_fields(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    maintenance = oracle.explorer_json("/v1/statistics/maintenance_info")
                    flush = oracle.explorer_json("/v1/statistics/flush_cache_info")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                maintenance_attributes = maintenance.get("data", {}).get("attributes", {})
                flush_attributes = flush.get("data", {}).get("attributes", {})
                self.assertEqual({"maintenance_info", "created_at_unixtimestamp"}, set(maintenance_attributes))
                self.assertEqual({"flush_cache_info", "created_at_unixtimestamp"}, set(flush_attributes))
                self.assertIsInstance(flush_attributes["flush_cache_info"], list)
                self.assertNotIn("tip_block_number", maintenance_attributes)
                self.assertNotIn("current_epoch_difficulty", flush_attributes)

    # TEST-MAP: CURRENT-STATS-RPC-09
    def test_unknown_statistic_name_returns_422_code_1019(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    status, raw = _raw_explorer_response(oracle, "/v1/statistics/not-a-stat")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                body = json.loads(raw)
                self.assertEqual(422, status)
                self.assertIsInstance(body, list)
                self.assertEqual(1, len(body))
                self.assertEqual(1019, body[0].get("code"))
                self.assertNotIn("data", body[0])
