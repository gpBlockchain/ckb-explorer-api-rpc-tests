from __future__ import annotations

import unittest
from collections import defaultdict

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.fiber import test_v2_fiber_graph_nodes_index as node_support


class V2FiberGraphNodesAddressesRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: FIBER-GRAPH-RPC-02
    def test_active_node_addresses_and_deduplicated_open_connections_match_graph_channels(self) -> None:
        helper = node_support.V2FiberGraphNodesIndexRpcCorrectnessTests()
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    nodes = helper._all_nodes(oracle)
                    active = {row["node_id"]: row for row in nodes if row["deleted_at_timestamp"] is None}
                    addresses = oracle.explorer_json("/v2/fiber/graph_nodes/addresses")["data"]
                    channels = oracle.explorer_json(
                        "/v2/fiber/graph_channels", {"page": 1, "page_size": 100}
                    )["data"]["fiber_graph_channels"]
                    if not active:
                        raise OracleUnavailable(f"{network.name} has no active Fiber Graph Node fixture")
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(set(active), {row["node_id"] for row in addresses})
                expected_connections: dict[str, set[str]] = defaultdict(set)
                for channel in channels:
                    if channel["closed_transaction_info"]:
                        continue
                    expected_connections[channel["node1"]].add(channel["node2"])
                    expected_connections[channel["node2"]].add(channel["node1"])
                saw_isolated = False
                saw_multi_channel = False
                counts: dict[tuple[str, str], int] = defaultdict(int)
                for channel in channels:
                    if not channel["closed_transaction_info"]:
                        counts[tuple(sorted((channel["node1"], channel["node2"])))] += 1
                for row in addresses:
                    node_id = row["node_id"]
                    self.assertEqual(active[node_id]["addresses"], row["addresses"])
                    self.assertEqual(expected_connections[node_id], set(row["connections"]))
                    self.assertEqual(len(row["connections"]), len(set(row["connections"])))
                    saw_isolated |= not row["connections"]
                    saw_multi_channel |= any(
                        node_id in pair and count > 1 for pair, count in counts.items()
                    )
                self.assertTrue(saw_isolated)
                self.assertTrue(saw_multi_channel)


if __name__ == "__main__":
    unittest.main()
