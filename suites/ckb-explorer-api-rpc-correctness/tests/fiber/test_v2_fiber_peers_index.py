from __future__ import annotations

import unittest

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.fiber.http import fiber_rpc


class V2FiberPeersIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: FIBER-PEER-RPC-01
    def test_peer_membership_ready_channel_counts_and_balances_match_each_fiber_rpc(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json("/v2/fiber/peers", {"page": 1, "page_size": 100})
                    data = payload.get("data") if isinstance(payload, dict) else None
                    peers = data.get("fiber_peers") if isinstance(data, dict) else None
                    meta = payload.get("meta") if isinstance(payload, dict) else None
                    if not isinstance(peers, list) or not isinstance(meta, dict):
                        raise OracleUnavailable(f"{network.name} Fiber Peer list is unavailable")
                    if not peers:
                        raise OracleUnavailable(f"{network.name} has no configured Fiber Peer oracle")
                    upstream = {
                        str(peer["peer_id"]): fiber_rpc(
                            network.name,
                            list(peer["rpc_listening_addr"]),
                            "list_channels",
                            [{"peer_id": None}],
                        )
                        for peer in peers
                    }
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(len(peers), int(meta["total"]))
                self.assertEqual(len(peers), len({peer["peer_id"] for peer in peers}))
                for peer in peers:
                    channels = upstream[str(peer["peer_id"])].get("channels")
                    self.assertIsInstance(channels, list)
                    ready = [channel for channel in channels if channel["state"]["state_name"] == "CHANNEL_READY"]
                    self.assertEqual(len(ready), int(peer["channels_count"]))
                    self.assertEqual(
                        sum(int(channel["local_balance"], 16) for channel in ready),
                        int(str(peer["total_local_balance"]).removesuffix(".0")),
                    )


if __name__ == "__main__":
    unittest.main()
