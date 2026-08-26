from __future__ import annotations

import json
import unittest

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


class V1StatisticInfoChartsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # Both public instances currently return HTTP 500 before emitting chart resources.
    # TEST-MAP: CURRENT-STATS-RPC-10
    @unittest.expectedFailure
    def test_difficulty_and_uncle_rate_charts_are_ordered_epoch_rpc_samples(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                status, raw = _raw_explorer_response(oracle, "/v1/statistic_info_charts")
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            self.assertEqual(200, status)
            attributes = json.loads(raw).get("data", {}).get("attributes", {})
            difficulty = attributes.get("difficulty")
            uncle_rate = attributes.get("uncle_rate")
            self.assertIsInstance(difficulty, list)
            self.assertIsInstance(uncle_rate, list)
            self.assertEqual(sorted(row["epoch_number"] for row in uncle_rate),
                             [row["epoch_number"] for row in uncle_rate])
            self.assertTrue(all(0 <= float(row["uncle_rate"]) for row in uncle_rate))
            first_per_epoch = {}
            for row in difficulty:
                first_per_epoch.setdefault(row["epoch_number"], row["block_number"])
                self.assertGreater(int(row["difficulty"]), 0)
            self.assertEqual(sorted(first_per_epoch), list(first_per_epoch))

    # Both public instances currently return HTTP 500 before resolving the keyed Hash Rate cache.
    # TEST-MAP: CURRENT-STATS-RPC-11
    @unittest.expectedFailure
    def test_hash_rate_chart_is_a_unique_cache_sequence_or_empty_on_cache_miss(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                status, raw = _raw_explorer_response(oracle, "/v1/statistic_info_charts")
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            self.assertEqual(200, status)
            rows = json.loads(raw).get("data", {}).get("attributes", {}).get("hash_rate")
            self.assertIsInstance(rows, list)
            identities = [(row.get("block_number"), str(row.get("hash_rate"))) for row in rows]
            self.assertEqual(len(identities), len(set(identities)))
            self.assertEqual(sorted(row["block_number"] for row in rows), [row["block_number"] for row in rows])
