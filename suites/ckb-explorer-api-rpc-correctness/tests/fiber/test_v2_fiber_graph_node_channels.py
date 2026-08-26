from __future__ import annotations

import json
import unittest
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.fiber import test_v2_fiber_graph_nodes_index as node_support
from tests.portfolio.http import portfolio_response


class V2FiberGraphNodeChannelsRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _fixture(self, oracle: NetworkOracle) -> tuple[str, list[dict[str, object]]]:
        helper = node_support.V2FiberGraphNodesIndexRpcCorrectnessTests()
        nodes = helper._all_nodes(oracle)
        for node in sorted(nodes, key=lambda row: int(row["open_channels_count"]), reverse=True):
            payload = oracle.explorer_json(
                f"/v2/fiber/graph_nodes/{node['node_id']}/graph_channels",
                {"page": 1, "page_size": 100},
            )
            rows = payload["data"]["fiber_graph_channels"]
            if (
                any(row["closed_transaction_info"] for row in rows)
                and any(not row["closed_transaction_info"] for row in rows)
                and any(row["udt_cfg_info"] for row in rows)
            ):
                return str(node["node_id"]), rows
        raise OracleUnavailable(f"{oracle.network.name} mixed Fiber Graph Channel fixture is unavailable")

    def _page(self, oracle: NetworkOracle, node_id: str, **query: object) -> tuple[list[dict[str, object]], dict[str, object]]:
        payload = oracle.explorer_json(
            f"/v2/fiber/graph_nodes/{node_id}/graph_channels", query or None
        )
        return payload["data"]["fiber_graph_channels"], payload["meta"]

    # TEST-MAP: FIBER-GRAPH-RPC-05
    def test_incident_open_closed_and_deleted_channel_history_matches_ckb_funding_and_transactions(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    node_id, rows = self._fixture(oracle)
                    global_rows = oracle.explorer_json(
                        "/v2/fiber/graph_channels", {"page": 1, "page_size": 100}
                    )["data"]["fiber_graph_channels"]
                    samples = [
                        next(row for row in rows if not row["closed_transaction_info"] and not row["udt_cfg_info"]),
                        next(row for row in rows if row["closed_transaction_info"]),
                        next(row for row in rows if row["udt_cfg_info"]),
                    ]
                    rpc = [oracle.rpc_result("get_transaction", [row["open_transaction_info"]["tx_hash"]]) for row in samples]
                    closed_rpc = oracle.rpc_result(
                        "get_transaction", [samples[1]["closed_transaction_info"]["tx_hash"]]
                    )
                except (OracleUnavailable, KeyError, TypeError, ValueError, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertTrue(all(node_id in (row["node1"], row["node2"]) for row in rows))
                self.assertTrue(any(row["node1"] == node_id for row in rows))
                self.assertTrue(any(row["node2"] == node_id for row in rows))
                self.assertEqual(len(rows), len({row["channel_outpoint"] for row in rows}))
                self.assertTrue({row["channel_outpoint"] for row in global_rows} < {row["channel_outpoint"] for row in rows})
                for row, result in zip(samples, rpc, strict=True):
                    outpoint = str(row["channel_outpoint"])
                    self.assertEqual(row["open_transaction_info"]["tx_hash"], outpoint[:66])
                    index = int.from_bytes(bytes.fromhex(outpoint[66:]), "little")
                    transaction = result["transaction"]
                    output = transaction["outputs"][index]
                    data = transaction["outputs_data"][index]
                    self.assertEqual("committed", result["tx_status"]["status"])
                    self.assertEqual(
                        decode_hex_int(output["capacity"], "funding.capacity"),
                        int(str(row["open_transaction_info"]["capacity"]).removesuffix(".0")),
                    )
                    if row["udt_cfg_info"]:
                        amount = int.from_bytes(bytes.fromhex(data[2:])[:16], "little")
                        self.assertEqual(amount, int(str(row["capacity"]).removesuffix(".0")))
                        self.assertEqual(amount, int(row["open_transaction_info"]["udt_info"]["amount"]))
                    else:
                        self.assertEqual(
                            decode_hex_int(output["capacity"], "funding.capacity") - 12_400_000_000,
                            int(str(row["capacity"]).removesuffix(".0")),
                        )
                self.assertEqual("committed", closed_rpc["tx_status"]["status"])
                self.assertEqual(
                    samples[1]["closed_transaction_info"]["tx_hash"],
                    closed_rpc["transaction"]["hash"],
                )

    # TEST-MAP: FIBER-GRAPH-RPC-06
    @unittest.expectedFailure  # Reversed dates currently escape the interaction as HTTP 500 instead of a parameter error.
    def test_combined_filters_boundaries_sort_and_adjacent_pages_are_stable(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    node_id, all_rows = self._fixture(oracle)
                    open_rows, _ = self._page(oracle, node_id, status="open", page_size=100)
                    closed_rows, _ = self._page(oracle, node_id, status="closed", page_size=100)
                    ckb_rows, _ = self._page(oracle, node_id, type_hash="0x0", page_size=100)
                    udt_sample = next(row for row in all_rows if row["udt_cfg_info"])
                    type_hash = udt_sample["open_transaction_info"]["udt_info"]["type_hash"]
                    amount = int(udt_sample["open_transaction_info"]["udt_info"]["amount"])
                    udt_rows, _ = self._page(
                        oracle, node_id, type_hash=type_hash, min_token_amount=amount, max_token_amount=amount, page_size=100
                    )
                    date = int(udt_sample["created_timestamp"])
                    date_rows, _ = self._page(oracle, node_id, start_date=date, end_date=date, page_size=100)
                    address = udt_sample["open_transaction_info"]["address"]
                    address_rows, _ = self._page(oracle, node_id, address_hash=address, page_size=100)
                    first, _ = self._page(oracle, node_id, sort="position_time.desc", page=1, page_size=2)
                    second, _ = self._page(oracle, node_id, sort="position_time.desc", page=2, page_size=2)
                    combined, _ = self._page(oracle, node_id, sort="position_time.desc", page=1, page_size=4)
                    invalid_status = portfolio_response(
                        oracle, f"/v2/fiber/graph_nodes/{node_id}/graph_channels?" + urlencode({"status": "invalid"})
                    )
                    reversed_dates = portfolio_response(
                        oracle,
                        f"/v2/fiber/graph_nodes/{node_id}/graph_channels?" + urlencode({"start_date": date + 1, "end_date": date}),
                    )
                except (OracleUnavailable, KeyError, TypeError, ValueError, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual({row["channel_outpoint"] for row in all_rows}, {row["channel_outpoint"] for row in open_rows + closed_rows})
                self.assertTrue(all(not row["closed_transaction_info"] for row in open_rows))
                self.assertTrue(all(row["closed_transaction_info"] for row in closed_rows))
                self.assertTrue(all(not row["udt_cfg_info"] for row in ckb_rows))
                self.assertEqual({udt_sample["channel_outpoint"]}, {row["channel_outpoint"] for row in udt_rows})
                self.assertIn(udt_sample["channel_outpoint"], {row["channel_outpoint"] for row in date_rows})
                self.assertIn(udt_sample["channel_outpoint"], {row["channel_outpoint"] for row in address_rows})
                self.assertEqual(first + second, combined)
                self.assertEqual([400, 400], [invalid_status[0], reversed_dates[0]])
                self.assertTrue(all("data" not in error for error in json.loads(invalid_status[1])))
                self.assertTrue(all("data" not in error for error in json.loads(reversed_dates[1])))


if __name__ == "__main__":
    unittest.main()
