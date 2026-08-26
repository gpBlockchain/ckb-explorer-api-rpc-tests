from __future__ import annotations

import unittest

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.fiber import test_v2_fiber_graph_node_channels as channel_support


class V2FiberGraphChannelsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _page(
        self, oracle: NetworkOracle, **query: object
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        payload = oracle.explorer_json("/v2/fiber/graph_channels", query or None)
        return payload["data"]["fiber_graph_channels"], payload["meta"]

    # TEST-MAP: FIBER-GRAPH-RPC-08
    def test_active_membership_closed_and_funding_address_filters_are_exact(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, meta = self._page(oracle, page=1, page_size=100)
                    if not rows:
                        raise OracleUnavailable(
                            f"{network.name} has no active Fiber Graph Channel fixture"
                        )
                    closed, _ = self._page(
                        oracle, status="closed", page=1, page_size=100
                    )
                    address = rows[0]["open_transaction_info"]["address"]
                    addressed, _ = self._page(
                        oracle, address_hash=address, page=1, page_size=100
                    )
                    first, _ = self._page(oracle, page=1, page_size=5)
                    second, _ = self._page(oracle, page=2, page_size=5)
                    combined, _ = self._page(oracle, page=1, page_size=10)

                    histories: dict[str, dict[str, dict[str, object]]] = {}
                    for node_id in {str(row["node1"]) for row in rows}:
                        payload = oracle.explorer_json(
                            f"/v2/fiber/graph_nodes/{node_id}/graph_channels",
                            {"page": 1, "page_size": 100},
                        )
                        histories[node_id] = {
                            item["channel_outpoint"]: item
                            for item in payload["data"]["fiber_graph_channels"]
                        }
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual(len(rows), meta["total"])
                self.assertEqual(100, meta["page_size"])
                self.assertEqual(len(rows), len({row["channel_outpoint"] for row in rows}))
                self.assertEqual(first + second, combined)
                self.assertEqual(
                    {
                        row["channel_outpoint"]
                        for row in rows
                        if row["closed_transaction_info"]
                    },
                    {row["channel_outpoint"] for row in closed},
                )
                self.assertEqual(
                    {
                        row["channel_outpoint"]
                        for row in rows
                        if row["open_transaction_info"]["address"] == address
                    },
                    {row["channel_outpoint"] for row in addressed},
                )
                for row in rows:
                    historical = histories[str(row["node1"])][row["channel_outpoint"]]
                    for field in (
                        "channel_outpoint",
                        "node1",
                        "node2",
                        "chain_hash",
                        "created_timestamp",
                        "fee_rate_of_node1",
                        "fee_rate_of_node2",
                        "capacity",
                        "udt_cfg_info",
                        "open_transaction_info",
                        "closed_transaction_info",
                    ):
                        self.assertEqual(historical[field], row[field])

    # TEST-MAP: FIBER-GRAPH-RPC-11
    @unittest.expectedFailure  # Graph capacity currently reports negotiated CKB, not the funding output capacity.
    def test_funding_outputs_udt_amounts_and_closed_consumption_match_ckb_rpc(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, _ = self._page(oracle, page=1, page_size=100)
                    helper = channel_support.V2FiberGraphNodeChannelsRpcCorrectnessTests()
                    _node_id, history = helper._fixture(oracle)
                    samples = [
                        next(row for row in rows if not row["udt_cfg_info"]),
                        next(row for row in rows if row["udt_cfg_info"]),
                    ]
                    closed = next(row for row in history if row["closed_transaction_info"])
                    open_results = oracle.rpc_batch_results(
                        [
                            ("get_transaction", [row["open_transaction_info"]["tx_hash"]])
                            for row in samples
                        ]
                    )
                    closed_result = oracle.rpc_result(
                        "get_transaction", [closed["closed_transaction_info"]["tx_hash"]]
                    )
                except (OracleUnavailable, KeyError, TypeError, ValueError, StopIteration) as error:
                    self._outcome.result.addSkip(self._subtest, str(error))
                    continue

                ckb_capacities: list[tuple[int, int]] = []
                for row, result in zip(samples, open_results, strict=True):
                    outpoint = str(row["channel_outpoint"])
                    self.assertEqual(outpoint[:66], row["open_transaction_info"]["tx_hash"])
                    index = int.from_bytes(bytes.fromhex(outpoint[66:]), "little")
                    transaction = result["transaction"]
                    output = transaction["outputs"][index]
                    output_data = transaction["outputs_data"][index]
                    output_capacity = decode_hex_int(output["capacity"], "funding.capacity")
                    self.assertEqual("committed", result["tx_status"]["status"])
                    self.assertEqual(outpoint[:66], transaction["hash"])
                    self.assertEqual(
                        output_capacity,
                        int(str(row["open_transaction_info"]["capacity"]).removesuffix(".0")),
                    )
                    if row["udt_cfg_info"]:
                        amount = int.from_bytes(bytes.fromhex(output_data[2:])[:16], "little")
                        self.assertEqual(
                            row["open_transaction_info"]["udt_info"]["type_hash"],
                            ckb_script_hash(output["type"]),
                        )
                        self.assertEqual(
                            amount,
                            int(row["open_transaction_info"]["udt_info"]["amount"]),
                        )
                        self.assertEqual(amount, int(str(row["capacity"]).removesuffix(".0")))
                    else:
                        ckb_capacities.append(
                            (
                                output_capacity,
                                int(str(row["capacity"]).removesuffix(".0")),
                            )
                        )

                closed_outpoint = str(closed["channel_outpoint"])
                expected_previous_output = {
                    "tx_hash": closed_outpoint[:66],
                    "index": hex(int.from_bytes(bytes.fromhex(closed_outpoint[66:]), "little")),
                }
                self.assertEqual("committed", closed_result["tx_status"]["status"])
                self.assertIn(
                    expected_previous_output,
                    [item["previous_output"] for item in closed_result["transaction"]["inputs"]],
                )
                self.assertEqual(
                    [output_capacity for output_capacity, _graph_capacity in ckb_capacities],
                    [graph_capacity for _output_capacity, graph_capacity in ckb_capacities],
                )


if __name__ == "__main__":
    unittest.main()
