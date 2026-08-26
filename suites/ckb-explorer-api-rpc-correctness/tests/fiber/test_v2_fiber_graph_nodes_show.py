from __future__ import annotations

import json
import unittest
from urllib.parse import quote

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.fiber import test_v2_fiber_graph_nodes_index as node_support
from tests.portfolio.http import portfolio_response


class V2FiberGraphNodesShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: FIBER-GRAPH-RPC-03
    def test_active_and_deleted_node_details_preserve_identity_and_only_active_open_aggregates(self) -> None:
        helper = node_support.V2FiberGraphNodesIndexRpcCorrectnessTests()
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = helper._all_nodes(oracle)
                    active = next(row for row in rows if int(row["open_channels_count"]) > 0)
                    deleted = next(row for row in rows if row["deleted_at_timestamp"] is not None)
                    active_detail = oracle.explorer_json(
                        "/v2/fiber/graph_nodes/" + quote(str(active["node_id"]), safe="")
                    )["data"]
                    deleted_detail = oracle.explorer_json(
                        "/v2/fiber/graph_nodes/" + quote(str(deleted["node_id"]), safe="")
                    )["data"]
                    channels = oracle.explorer_json(
                        "/v2/fiber/graph_channels", {"page": 1, "page_size": 100}
                    )["data"]["fiber_graph_channels"]
                except (OracleUnavailable, KeyError, TypeError, ValueError, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                for listed, detail in ((active, active_detail), (deleted, deleted_detail)):
                    for field in (
                        "node_name", "node_id", "addresses", "peer_id", "timestamp", "chain_hash",
                        "auto_accept_min_ckb_funding_amount", "udt_cfg_infos", "deleted_at_timestamp",
                    ):
                        self.assertEqual(listed[field], detail[field])
                incident = [
                    channel
                    for channel in channels
                    if active["node_id"] in (channel["node1"], channel["node2"])
                    and not channel["closed_transaction_info"]
                ]
                expected_connections = {
                    channel["node2"] if channel["node1"] == active["node_id"] else channel["node1"]
                    for channel in incident
                }
                self.assertEqual(expected_connections, set(active_detail["connected_node_ids"]))
                self.assertEqual(
                    sum(int(str(channel["capacity"]).removesuffix(".0")) for channel in incident),
                    int(str(active_detail["total_capacity"]).removesuffix(".0")),
                )
                self.assertEqual([], deleted_detail["connected_node_ids"])
                self.assertEqual(0, int(str(deleted_detail["total_capacity"]).removesuffix(".0")))

    # TEST-MAP: FIBER-GRAPH-RPC-04
    def test_unknown_node_and_both_child_routes_return_not_found_then_known_detail_recovers(self) -> None:
        missing = "ff" * 33
        helper = node_support.V2FiberGraphNodesIndexRpcCorrectnessTests()
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            with self.subTest(network=network.name, case="unknown-three-routes"):
                responses = [
                    portfolio_response(oracle, f"/v2/fiber/graph_nodes/{missing}{suffix}")
                    for suffix in ("", "/graph_channels", "/transactions")
                ]
                for status, raw in responses:
                    self.assertEqual(404, status)
                    errors = json.loads(raw)
                    self.assertEqual(2013, errors[0]["code"])
                    self.assertNotIn("data", errors[0])
            with self.subTest(network=network.name, case="known-retry"):
                try:
                    rows = helper._all_nodes(oracle)
                    if not rows:
                        raise OracleUnavailable(f"{network.name} has no Fiber Graph Node retry fixture")
                    node_id = str(rows[0]["node_id"])
                    detail = oracle.explorer_json(
                        "/v2/fiber/graph_nodes/" + quote(node_id, safe="")
                    )
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(node_id, detail["data"]["node_id"])


if __name__ == "__main__":
    unittest.main()
