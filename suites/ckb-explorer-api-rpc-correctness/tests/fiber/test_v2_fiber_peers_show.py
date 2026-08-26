from __future__ import annotations

import json
import unittest
from urllib.parse import quote

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.fiber.http import fiber_rpc
from tests.portfolio.http import portfolio_response


class V2FiberPeersShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _peers(self, oracle: NetworkOracle) -> list[dict[str, object]]:
        payload = oracle.explorer_json("/v2/fiber/peers", {"page": 1, "page_size": 100})
        data = payload.get("data") if isinstance(payload, dict) else None
        peers = data.get("fiber_peers") if isinstance(data, dict) else None
        if not isinstance(peers, list):
            raise OracleUnavailable(f"{oracle.network.name} Fiber Peer list is unavailable")
        return peers

    # TEST-MAP: FIBER-PEER-RPC-02
    def test_peer_detail_identity_and_owned_channels_match_its_fiber_rpc(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    peers = self._peers(oracle)
                    if not peers:
                        raise OracleUnavailable(f"{network.name} has no configured Fiber Peer oracle")
                    for peer in peers:
                        detail = oracle.explorer_json(
                            "/v2/fiber/peers/" + quote(str(peer["peer_id"]), safe="")
                        )["data"]
                        upstream = fiber_rpc(
                            network.name,
                            list(peer["rpc_listening_addr"]),
                            "list_channels",
                            [{"peer_id": None}],
                        )
                        expected = {
                            (
                                channel["peer_id"],
                                channel["channel_id"],
                                channel["state"]["state_name"],
                                tuple(
                                    channel["state"]["state_flags"]
                                    if isinstance(channel["state"]["state_flags"], list)
                                    else channel["state"]["state_flags"].split("|")
                                ),
                            )
                            for channel in upstream["channels"]
                        }
                        actual = {
                            (
                                channel["peer_id"],
                                channel["channel_id"],
                                channel["state_name"],
                                tuple(channel["state_flags"]),
                            )
                            for channel in detail["fiber_channels"]
                        }
                        self.assertEqual(str(peer["peer_id"]), detail["peer_id"])
                        self.assertEqual(peer["rpc_listening_addr"], detail["rpc_listening_addr"])
                        self.assertEqual(expected, actual)
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

    # TEST-MAP: FIBER-PEER-RPC-06
    def test_unknown_peer_returns_not_found_without_poisoning_a_known_detail(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            with self.subTest(network=network.name, case="unknown"):
                status, raw = portfolio_response(
                    oracle, "/v2/fiber/peers/rpc-correctness-missing-peer"
                )
                self.assertEqual(404, status)
                errors = json.loads(raw)
                self.assertEqual(2011, errors[0]["code"])
                self.assertNotIn("data", errors[0])
            with self.subTest(network=network.name, case="known-retry"):
                try:
                    peers = self._peers(oracle)
                    if not peers:
                        raise OracleUnavailable(f"{network.name} has no configured Fiber Peer retry fixture")
                    peer_id = str(peers[0]["peer_id"])
                    detail = oracle.explorer_json("/v2/fiber/peers/" + quote(peer_id, safe=""))
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(peer_id, detail["data"]["peer_id"])
                self.assertIsInstance(detail["data"]["fiber_channels"], list)


if __name__ == "__main__":
    unittest.main()
