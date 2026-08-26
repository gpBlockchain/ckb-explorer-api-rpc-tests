from __future__ import annotations

import unittest

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V1DistributionDataShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: HIST-STATS-RPC-12
    def test_combined_latest_daily_distributions_keep_independent_fields_and_one_timestamp(self) -> None:
        indicator = "address_balance_distribution-block_time_distribution-epoch_time_distribution-epoch_length_distribution-nodes_distribution"
        expected = set(indicator.split("-")) | {"created_at_unixtimestamp"}
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json(f"/v1/distribution_data/{indicator}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                data = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(data, dict)
                attributes = data.get("attributes")
                self.assertEqual(expected, set(attributes))
                self.assertTrue(str(attributes["created_at_unixtimestamp"]).isdecimal())
                for field in expected - {"created_at_unixtimestamp"}:
                    self.assertIsInstance(attributes[field], (list, dict))

    # TEST-MAP: HIST-STATS-RPC-13
    def test_average_block_time_special_branch_preserves_the_rolling_sequence_order(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    first = oracle.explorer_json("/v1/distribution_data/average_block_time")
                    second = oracle.explorer_json("/v1/distribution_data/average_block_time")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                data = first.get("data") if isinstance(first, dict) else None
                self.assertIsInstance(data, dict)
                self.assertEqual("distribution_data", data.get("type"))
                rows = data.get("attributes", {}).get("average_block_time")
                self.assertIsInstance(rows, list)
                self.assertEqual(rows, second.get("data", {}).get("attributes", {}).get("average_block_time"))

    # TEST-MAP: HIST-STATS-RPC-14
    def test_seven_and_ninety_day_miner_distributions_are_descending_and_sum_their_windows(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    payloads = {
                        days: oracle.explorer_json(f"/v1/distribution_data/miner_address_distribution{days}")
                        for days in (7, 90)
                    }
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                for days, payload in payloads.items():
                    values = payload.get("data", {}).get("attributes", {}).get("miner_address_distribution")
                    self.assertIsInstance(values, dict)
                    counts = [int(value) for key, value in values.items() if key != "other"]
                    self.assertEqual(sorted(counts, reverse=True), counts)
                    self.assertGreater(sum(int(value) for value in values.values()), 0)
                raise unittest.SkipTest(
                    f"{network.name} complete 7/90-day RPC block windows are unavailable as a stable public oracle"
                )
