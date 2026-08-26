from __future__ import annotations

import json
import unittest

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


class V1NetsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: DISCOVERY-RPC-09
    def test_each_selector_matches_the_complete_local_node_snapshot(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    complete_payload = oracle.explorer_json("/v1/nets/local_node_info")
                    selected_payloads = {
                        name: oracle.explorer_json(f"/v1/nets/{name}")
                        for name in ("addresses", "node_id", "version")
                    }
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                complete_attributes = complete_payload.get("data", {}).get("attributes", {})
                self.assertEqual({"local_node_info"}, set(complete_attributes))
                complete = complete_attributes["local_node_info"]
                self.assertIsInstance(complete, dict)
                self.assertTrue({"addresses", "node_id", "version"}.issubset(complete))
                for name, payload in selected_payloads.items():
                    attributes = payload.get("data", {}).get("attributes", {})
                    self.assertEqual({name}, set(attributes))
                    self.assertEqual(complete[name], attributes[name])

    # TEST-MAP: DISCOVERY-RPC-10
    def test_unknown_selector_returns_422_code_1020_without_cached_fields(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    status, raw = _raw_explorer_response(oracle, "/v1/nets/not-a-net")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                body = json.loads(raw)
                self.assertEqual(422, status)
                self.assertIsInstance(body, list)
                self.assertEqual(1, len(body))
                self.assertEqual(1020, body[0].get("code"))
                self.assertFalse({"addresses", "node_id", "version", "local_node_info"} & set(body[0]))

    # TEST-MAP: DISCOVERY-RPC-11
    def test_repeated_selectors_share_one_four_hour_cache_snapshot(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    first = oracle.explorer_json("/v1/nets/local_node_info")
                    node_id = oracle.explorer_json("/v1/nets/node_id")
                    version = oracle.explorer_json("/v1/nets/version")
                    addresses = oracle.explorer_json("/v1/nets/addresses")
                    second = oracle.explorer_json("/v1/nets/local_node_info")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                first_info = first.get("data", {}).get("attributes", {}).get("local_node_info")
                second_info = second.get("data", {}).get("attributes", {}).get("local_node_info")
                self.assertIsInstance(first_info, dict)
                self.assertEqual(first_info, second_info)
                self.assertEqual(first_info["node_id"], node_id.get("data", {}).get("attributes", {}).get("node_id"))
                self.assertEqual(first_info["version"], version.get("data", {}).get("attributes", {}).get("version"))
                self.assertEqual(first_info["addresses"], addresses.get("data", {}).get("attributes", {}).get("addresses"))
                raise unittest.SkipTest(
                    f"{network.name} public endpoint does not expose cache expiry control for the four-hour refresh branch"
                )
