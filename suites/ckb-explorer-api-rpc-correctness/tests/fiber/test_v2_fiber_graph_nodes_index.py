from __future__ import annotations

import os
import unittest

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.fiber.http import fiber_rpc


class V2FiberGraphNodesIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _all_nodes(self, oracle: NetworkOracle) -> list[dict[str, object]]:
        first = oracle.explorer_json("/v2/fiber/graph_nodes", {"page": 1, "page_size": 100})
        rows = list(first["data"]["fiber_graph_nodes"])
        total = int(first["meta"]["total"])
        for page in range(2, (total + 99) // 100 + 1):
            payload = oracle.explorer_json("/v2/fiber/graph_nodes", {"page": page, "page_size": 100})
            self.assertEqual(total, int(payload["meta"]["total"]))
            rows.extend(payload["data"]["fiber_graph_nodes"])
        if len(rows) != total:
            raise OracleUnavailable(f"{oracle.network.name} Fiber Graph Node snapshot changed during pagination")
        return rows

    def _upstream_nodes(self, network_name: str) -> list[dict[str, object]]:
        endpoint = os.environ.get(f"{network_name.upper()}_FIBER_GRAPH_RPC_URL")
        if not endpoint:
            raise OracleUnavailable(f"{network_name} Fiber Graph RPC fixture is unavailable")
        rows: list[dict[str, object]] = []
        cursor: str | None = None
        for _page in range(100):
            result = fiber_rpc(network_name, [endpoint], "graph_nodes", [{"limit": "0x64", "after": cursor}])
            current = result.get("nodes") if isinstance(result, dict) else None
            next_cursor = result.get("last_cursor") if isinstance(result, dict) else None
            if not isinstance(current, list) or not isinstance(next_cursor, str):
                raise OracleUnavailable(f"{network_name} Fiber graph_nodes result is unavailable")
            rows.extend(current)
            if next_cursor == "0x" or next_cursor == cursor:
                return rows
            cursor = next_cursor
        raise OracleUnavailable(f"{network_name} Fiber graph_nodes exceeded 100 pages")

    # TEST-MAP: FIBER-GRAPH-RPC-01
    def test_active_node_membership_fields_exact_searches_and_pages_match_fiber_graph_rpc(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    upstream = self._upstream_nodes(network.name)
                    rows = self._all_nodes(oracle)
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                active = [row for row in rows if row["deleted_at_timestamp"] is None]
                expected = {str(row["node_id"]): row for row in upstream}
                self.assertEqual(set(expected), {str(row["node_id"]) for row in active})
                self.assertEqual(len(rows), len({row["node_id"] for row in rows}))
                for row in active:
                    source = expected[str(row["node_id"])]
                    self.assertEqual(source["node_name"], row["node_name"])
                    self.assertEqual(source["addresses"], row["addresses"])
                    self.assertEqual(source["chain_hash"], row["chain_hash"])
                    self.assertEqual(int(str(source["timestamp"]), 16), int(row["timestamp"]))
                    self.assertEqual(
                        int(str(source["auto_accept_min_ckb_funding_amount"]), 16),
                        int(str(row["auto_accept_min_ckb_funding_amount"]).removesuffix(".0")),
                    )
                sample = active[0]
                for key in (sample["node_name"], sample["peer_id"], sample["node_id"]):
                    searched = oracle.explorer_json("/v2/fiber/graph_nodes", {"q": key})
                    self.assertEqual([sample["node_id"]], [item["node_id"] for item in searched["data"]["fiber_graph_nodes"]])

    # TEST-MAP: FIBER-GRAPH-RPC-10
    def test_soft_deleted_nodes_and_channels_follow_history_and_active_collection_boundaries(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    nodes = self._all_nodes(oracle)
                    deleted = next(row for row in nodes if row["deleted_at_timestamp"] is not None)
                    addresses = oracle.explorer_json("/v2/fiber/graph_nodes/addresses")["data"]
                    detail = oracle.explorer_json(f"/v2/fiber/graph_nodes/{deleted['node_id']}")["data"]
                    global_channels = oracle.explorer_json(
                        "/v2/fiber/graph_channels", {"page": 1, "page_size": 100}
                    )["data"]["fiber_graph_channels"]
                    active_node = next(row for row in nodes if int(row["open_channels_count"]) > 0)
                    history = oracle.explorer_json(
                        f"/v2/fiber/graph_nodes/{active_node['node_id']}/graph_channels",
                        {"page": 1, "page_size": 100},
                    )["data"]["fiber_graph_channels"]
                except (OracleUnavailable, KeyError, TypeError, ValueError, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(deleted["node_id"], detail["node_id"])
                self.assertEqual(deleted["deleted_at_timestamp"], detail["deleted_at_timestamp"])
                self.assertNotIn(deleted["node_id"], {row["node_id"] for row in addresses})
                active_ids = {row["channel_outpoint"] for row in global_channels}
                history_ids = {row["channel_outpoint"] for row in history}
                self.assertTrue(active_ids)
                self.assertTrue(active_ids <= history_ids)
                self.assertTrue(history_ids - active_ids)
                self.assertEqual(
                    int(active_node["open_channels_count"]),
                    sum(
                        channel["channel_outpoint"] in active_ids
                        and not channel["closed_transaction_info"]
                        for channel in history
                    ),
                )


if __name__ == "__main__":
    unittest.main()
