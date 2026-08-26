from __future__ import annotations

import unittest

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


class V1ExternalStatsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: DISCOVERY-RPC-01
    def test_tip_block_number_is_the_current_explorer_indexed_height(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    before = oracle.api_tip_height()
                    status, raw = _raw_explorer_response(oracle, "/v1/external/stats/tip_block_number")
                    after = NetworkOracle(network, self.settings).api_tip_height()
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if after < before:
                    raise unittest.SkipTest(f"{network.name} Explorer tip moved backwards during observation")
                body = raw.decode("ascii")
                self.assertEqual(200, status)
                self.assertTrue(body.isdecimal())
                self.assertGreaterEqual(int(body), before)
                self.assertLessEqual(int(body), after)

    # TEST-MAP: DISCOVERY-RPC-02
    def test_unknown_stat_identifier_has_no_statistic_or_tip_fallback(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    status, raw = _raw_explorer_response(oracle, "/v1/external/stats/not-a-stat")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(204, status)
                self.assertEqual(b"", raw)
