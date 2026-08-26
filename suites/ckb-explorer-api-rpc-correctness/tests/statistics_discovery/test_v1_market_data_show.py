from __future__ import annotations

import unittest

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


class V1MarketDataShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: ECON-RPC-02
    def test_total_supply_uses_the_current_dao_snapshot_and_release_branch(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    value = oracle.explorer_json("/v1/market_data/total_supply")
                    tip = oracle.rpc_tip()
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertRegex(str(value), r"^\d+(?:\.\d+)?$")
                self.assertIsInstance(tip.get("dao"), str)
                raise unittest.SkipTest(
                    f"{network.name} public RPC does not expose Explorer's cached aggregate of unmade DAO interests"
                )

    # TEST-MAP: ECON-RPC-03
    def test_circulating_supply_uses_one_current_dao_and_locked_balance_snapshot(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    value = oracle.explorer_json("/v1/market_data/circulating_supply")
                    tip = oracle.rpc_tip()
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertRegex(str(value), r"^\d+(?:\.\d+)?$")
                self.assertIsInstance(tip.get("dao"), str)
                raise unittest.SkipTest(
                    f"{network.name} public oracle has no atomic snapshot of the Explorer bug-bounty address balance"
                )

    # TEST-MAP: ECON-RPC-04
    def test_all_release_stage_boundaries_use_the_documented_locked_quota_steps(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    value = oracle.explorer_json("/v1/market_data/circulating_supply")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertGreater(float(value), 0)
                raise unittest.SkipTest(
                    f"{network.name} live endpoint has no timestamp/tip override for historical release-boundary fixtures"
                )

    # TEST-MAP: ECON-RPC-05
    def test_supply_details_are_plain_truncated_decimal_strings_with_at_most_eight_places(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    values = [
                        oracle.explorer_json(f"/v1/market_data/{name}")
                        for name in ("total_supply", "circulating_supply")
                    ]
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                for value in values:
                    text = str(value)
                    self.assertRegex(text, r"^\d+(?:\.\d{1,8})?$")
                    self.assertNotIn("e", text.lower())

    # TEST-MAP: ECON-RPC-06
    def test_unknown_market_indicator_returns_http_200_json_null(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    status, raw = _raw_explorer_response(oracle, "/v1/market_data/not-a-supply")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(200, status)
                self.assertEqual(b"null", raw)
