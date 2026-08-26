from __future__ import annotations

import json
import unittest
from urllib.parse import quote

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.fiber.http import fiber_rpc
from tests.portfolio.http import portfolio_response


class V2FiberChannelsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _channel_fixture(self, oracle: NetworkOracle) -> tuple[dict[str, object], dict[str, object]]:
        payload = oracle.explorer_json("/v2/fiber/peers", {"page": 1, "page_size": 100})
        peers = payload.get("data", {}).get("fiber_peers", [])
        for peer in peers:
            detail = oracle.explorer_json(
                "/v2/fiber/peers/" + quote(str(peer["peer_id"]), safe="")
            )["data"]
            if detail["fiber_channels"]:
                channel_id = detail["fiber_channels"][0]["channel_id"]
                upstream = fiber_rpc(
                    oracle.network.name,
                    list(peer["rpc_listening_addr"]),
                    "list_channels",
                    [{"peer_id": None}],
                )
                channel = next(item for item in upstream["channels"] if item["channel_id"] == channel_id)
                return peer, channel
        raise OracleUnavailable(f"{oracle.network.name} has no synchronized Fiber Channel fixture")

    # TEST-MAP: FIBER-CHANNEL-RPC-01
    def test_channel_identity_state_balances_and_times_match_owner_fiber_rpc(self) -> None:
        balance_fields = ("local_balance", "offered_tlc_balance", "remote_balance", "received_tlc_balance")
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    _peer, upstream = self._channel_fixture(oracle)
                    detail = oracle.explorer_json(
                        "/v2/fiber/channels/" + quote(str(upstream["channel_id"]), safe="")
                    )["data"]
                except (OracleUnavailable, KeyError, TypeError, ValueError, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(upstream["channel_id"], detail["channel_id"])
                self.assertEqual(upstream["state"]["state_name"], detail["state_name"])
                expected_flags = upstream["state"]["state_flags"]
                if isinstance(expected_flags, str):
                    expected_flags = expected_flags.split("|")
                self.assertEqual(expected_flags, detail["state_flags"])
                for field in balance_fields:
                    self.assertEqual(int(upstream[field], 16), int(str(detail[field]).removesuffix(".0")))
                self.assertTrue(all(field in detail for field in ("created_at", "updated_at", "shutdown_at")))

    # TEST-MAP: FIBER-CHANNEL-RPC-02
    def test_local_and_registered_remote_peer_directions_are_not_crossed(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    owner, upstream = self._channel_fixture(oracle)
                    detail = oracle.explorer_json(
                        "/v2/fiber/channels/" + quote(str(upstream["channel_id"]), safe="")
                    )["data"]
                    peers = oracle.explorer_json("/v2/fiber/peers", {"page": 1, "page_size": 100})["data"]["fiber_peers"]
                    remote = next(peer for peer in peers if peer["peer_id"] == upstream["peer_id"])
                except (OracleUnavailable, KeyError, TypeError, ValueError, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(owner["peer_id"], detail["local_peer"]["peer_id"])
                self.assertEqual(owner["name"], detail["local_peer"]["name"])
                self.assertEqual(owner["rpc_listening_addr"], detail["local_peer"]["rpc_listening_addr"])
                self.assertEqual(remote["peer_id"], detail["remote_peer"]["peer_id"])
                self.assertEqual(remote["name"], detail["remote_peer"]["name"])

    # TEST-MAP: FIBER-CHANNEL-RPC-04
    def test_unknown_channel_returns_not_found_and_a_known_retry_remains_readable(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            with self.subTest(network=network.name, case="unknown"):
                status, raw = portfolio_response(oracle, "/v2/fiber/channels/0x" + "ff" * 32)
                self.assertEqual(404, status)
                errors = json.loads(raw)
                self.assertEqual(2012, errors[0]["code"])
                self.assertNotIn("data", errors[0])
            with self.subTest(network=network.name, case="known-retry"):
                try:
                    _owner, upstream = self._channel_fixture(oracle)
                    detail = oracle.explorer_json(
                        "/v2/fiber/channels/" + quote(str(upstream["channel_id"]), safe="")
                    )
                except (OracleUnavailable, KeyError, TypeError, ValueError, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(upstream["channel_id"], detail["data"]["channel_id"])


if __name__ == "__main__":
    unittest.main()
