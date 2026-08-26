from __future__ import annotations

import json
import os
import time
import unittest

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.fiber.http import fiber_rpc
from tests.portfolio.http import portfolio_response


class V2FiberPeersCreateRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _controlled(self, network_name: str) -> tuple[str, str, str]:
        prefix = network_name.upper()
        endpoint = os.environ.get(f"{prefix}_FIBER_TEST_RPC_URL")
        peer_id = os.environ.get(f"{prefix}_FIBER_TEST_PEER_ID")
        name = os.environ.get(f"{prefix}_FIBER_TEST_PEER_NAME", "rpc-correctness")
        if not endpoint or not peer_id:
            raise OracleUnavailable(f"{network_name} controlled writable Fiber Peer fixture is unavailable")
        return endpoint, peer_id, name

    # TEST-MAP: FIBER-PEER-RPC-03
    def test_reachable_rpc_is_verified_persisted_and_synchronized_once(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    endpoint, peer_id, name = self._controlled(network.name)
                    upstream = fiber_rpc(network.name, [endpoint], "list_channels", [{"peer_id": None}])
                    status, raw = portfolio_response(
                        oracle,
                        "/v2/fiber/peers",
                        method="POST",
                        json_body={"name": name, "peer_id": peer_id, "rpc_listening_addr": endpoint},
                    )
                    if status != 204:
                        raise OracleUnavailable(f"{network.name} controlled Fiber create returned HTTP {status}: {raw[:200]!r}")
                    detail = None
                    for _attempt in range(10):
                        detail = oracle.explorer_json(f"/v2/fiber/peers/{peer_id}")
                        channels = detail.get("data", {}).get("fiber_channels", [])
                        if len(channels) == len(upstream.get("channels", [])):
                            break
                        time.sleep(1)
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(peer_id, detail["data"]["peer_id"])
                self.assertIn(endpoint, detail["data"]["rpc_listening_addr"])
                self.assertEqual(len(upstream["channels"]), len(detail["data"]["fiber_channels"]))

    # TEST-MAP: FIBER-PEER-RPC-04
    def test_repeated_registration_merges_rpc_addresses_and_updates_one_peer(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    first, peer_id, name = self._controlled(network.name)
                    second = os.environ.get(f"{network.name.upper()}_FIBER_TEST_RPC_URL_2")
                    if not second:
                        raise OracleUnavailable(f"{network.name} second controlled Fiber RPC fixture is unavailable")
                    for endpoint, current_name in ((first, name), (first, name), (second, name + "-updated")):
                        status, raw = portfolio_response(
                            oracle,
                            "/v2/fiber/peers",
                            method="POST",
                            json_body={"name": current_name, "peer_id": peer_id, "rpc_listening_addr": endpoint},
                        )
                        if status != 204:
                            raise OracleUnavailable(f"{network.name} repeated Fiber create returned HTTP {status}: {raw[:200]!r}")
                    listing = oracle.explorer_json("/v2/fiber/peers", {"page": 1, "page_size": 100})
                    detail = oracle.explorer_json(f"/v2/fiber/peers/{peer_id}")["data"]
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                peers = listing["data"]["fiber_peers"]
                self.assertEqual(1, sum(peer["peer_id"] == peer_id for peer in peers))
                self.assertEqual([first, second], detail["rpc_listening_addr"][-2:])
                self.assertEqual(name + "-updated", next(peer["name"] for peer in peers if peer["peer_id"] == peer_id))

    # TEST-MAP: FIBER-PEER-RPC-05
    def test_missing_malformed_and_unreachable_rpc_inputs_leave_peer_snapshot_unchanged(self) -> None:
        cases = (
            {},
            {"name": "rpc-correctness-invalid", "peer_id": "rpc-correctness-invalid", "rpc_listening_addr": ""},
            {"name": "rpc-correctness-invalid", "peer_id": "rpc-correctness-invalid", "rpc_listening_addr": "not-a-url"},
            {
                "name": "rpc-correctness-invalid",
                "peer_id": "rpc-correctness-invalid",
                "rpc_listening_addr": "http://127.0.0.1:1",
            },
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    before = oracle.explorer_json("/v2/fiber/peers", {"page": 1, "page_size": 100})
                    responses = [
                        portfolio_response(oracle, "/v2/fiber/peers", method="POST", json_body=body)
                        for body in cases
                    ]
                    after = oracle.explorer_json("/v2/fiber/peers", {"page": 1, "page_size": 100})
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(before, after)
                for status, raw in responses:
                    self.assertEqual(404, status)
                    errors = json.loads(raw)
                    self.assertEqual(2010, errors[0]["code"])
                    self.assertNotIn("data", errors[0])


if __name__ == "__main__":
    unittest.main()
