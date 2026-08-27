from __future__ import annotations

import unittest

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V1MarketDataIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: ECON-RPC-01
    def test_homepage_and_detail_endpoints_return_decimal_supply_snapshots(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                homepage = oracle.explorer_json("/v1/market_data")
                total = oracle.explorer_json("/v1/market_data/total_supply")
                circulating = oracle.explorer_json("/v1/market_data/circulating_supply")
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            self.assertIsInstance(homepage, dict)
            self.assertEqual({"total_supply", "circulating_supply"}, set(homepage))
            for value in [*homepage.values(), total, circulating]:
                self.assertIsInstance(value, str)
                self.assertNotIn("e", value.lower())
                self.assertRegex(value, r"^-?\d+(?:\.\d+)?$")
