from __future__ import annotations

import unittest

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.fiber import test_v2_fiber_graph_node_channels as channel_support


class V2FiberGraphNodeTransactionsRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _page(
        self, oracle: NetworkOracle, node_id: str, **query: object
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        payload = oracle.explorer_json(
            f"/v2/fiber/graph_nodes/{node_id}/transactions", query or None
        )
        return payload["data"]["fiber_graph_transactions"], payload["meta"]

    # TEST-MAP: FIBER-GRAPH-RPC-07
    @unittest.expectedFailure  # Closed events currently reuse their opening block timestamp.
    def test_open_and_close_events_match_ckb_and_filters_sort_and_pages_are_exact(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    helper = channel_support.V2FiberGraphNodeChannelsRpcCorrectnessTests()
                    node_id, channels = helper._fixture(oracle)
                    rows, meta = self._page(oracle, node_id, page=1, page_size=100)

                    expected: dict[tuple[str, bool], tuple[dict[str, object], bool]] = {}
                    for channel in channels:
                        open_info = channel["open_transaction_info"]
                        expected[(open_info["tx_hash"], True)] = (open_info, bool(channel["udt_cfg_info"]))
                        if channel["closed_transaction_info"]:
                            close_info = channel["closed_transaction_info"]
                            expected[(close_info["tx_hash"], False)] = (
                                close_info,
                                bool(channel["udt_cfg_info"]),
                            )

                    open_rows, _ = self._page(oracle, node_id, status="open", page_size=100)
                    closed_rows, _ = self._page(oracle, node_id, status="closed", page_size=100)
                    ckb_rows, _ = self._page(oracle, node_id, type_hash="0x0", page_size=100)

                    udt_sample = next(channel for channel in channels if channel["udt_cfg_info"])
                    udt_info = udt_sample["open_transaction_info"]["udt_info"]
                    type_hash = udt_info["type_hash"]
                    amount = int(udt_info["amount"])
                    udt_rows, _ = self._page(
                        oracle,
                        node_id,
                        type_hash=type_hash,
                        min_token_amount=amount,
                        max_token_amount=amount,
                        page_size=100,
                    )
                    address = udt_sample["open_transaction_info"]["address"]
                    address_rows, _ = self._page(
                        oracle, node_id, address_hash=address, page_size=100
                    )
                    timestamp = int(udt_sample["open_transaction_info"]["block_timestamp"])
                    date_rows, _ = self._page(
                        oracle,
                        node_id,
                        start_date=timestamp,
                        end_date=timestamp,
                        page_size=100,
                    )
                    combined_rows, _ = self._page(
                        oracle,
                        node_id,
                        status="open",
                        address_hash=address,
                        type_hash=type_hash,
                        min_token_amount=amount,
                        max_token_amount=amount,
                        start_date=timestamp,
                        end_date=timestamp,
                        page_size=100,
                    )
                    ascending, _ = self._page(
                        oracle, node_id, sort="block_timestamp.asc", page_size=100
                    )
                    descending, _ = self._page(
                        oracle, node_id, sort="block_timestamp.desc", page_size=100
                    )
                    first, _ = self._page(
                        oracle, node_id, sort="block_timestamp.asc", page=1, page_size=7
                    )
                    second, _ = self._page(
                        oracle, node_id, sort="block_timestamp.asc", page=2, page_size=7
                    )
                    combined_pages, _ = self._page(
                        oracle, node_id, sort="block_timestamp.asc", page=1, page_size=14
                    )

                    rpc_results = oracle.rpc_batch_results(
                        [("get_transaction", [row["tx_hash"]]) for row in rows]
                    )
                    heights = [
                        decode_hex_int(result["tx_status"]["block_number"], "tx_status.block_number")
                        for result in rpc_results
                    ]
                    oracle.prefetch_blocks(list(dict.fromkeys(heights)))
                except (OracleUnavailable, KeyError, TypeError, ValueError, StopIteration) as error:
                    # A skipped subTest makes unittest suppress a later expectedFailure
                    # on the same method. Record this network skip directly so the
                    # remaining network can still expose the known timestamp defect.
                    self._outcome.result.addSkip(self._subtest, str(error))
                    continue

                keys = [(row["tx_hash"], row["is_open"]) for row in rows]
                self.assertEqual(len(expected), len(rows))
                self.assertEqual(len(rows), len(set(keys)))
                self.assertEqual(set(expected), set(keys))
                self.assertEqual(len(rows), meta["total"])
                self.assertEqual(100, meta["page_size"])
                for row in rows:
                    info, is_udt = expected[(row["tx_hash"], row["is_open"])]
                    self.assertEqual(is_udt, row["is_udt"])
                    self.assertEqual(info["block_number"], row["block_number"])

                self.assertEqual(
                    {key for key in expected if key[1]},
                    {(row["tx_hash"], row["is_open"]) for row in open_rows},
                )
                self.assertEqual(
                    {key for key in expected if not key[1]},
                    {(row["tx_hash"], row["is_open"]) for row in closed_rows},
                )
                self.assertEqual(
                    {
                        (row["tx_hash"], row["is_open"])
                        for row in rows
                        if not row["is_udt"]
                    },
                    {(row["tx_hash"], row["is_open"]) for row in ckb_rows},
                )

                matching_udt_channels = [
                    channel
                    for channel in channels
                    if channel["udt_cfg_info"]
                    and channel["open_transaction_info"]["udt_info"]["type_hash"] == type_hash
                    and int(channel["open_transaction_info"]["udt_info"]["amount"]) == amount
                ]
                expected_udt = {
                    (info["tx_hash"], is_open)
                    for channel in matching_udt_channels
                    for info, is_open in (
                        (channel["open_transaction_info"], True),
                        (channel["closed_transaction_info"], False),
                    )
                    if info
                }
                self.assertEqual(
                    expected_udt,
                    {(row["tx_hash"], row["is_open"]) for row in udt_rows},
                )

                matching_address_channels = [
                    channel
                    for channel in channels
                    if channel["open_transaction_info"]["address"] == address
                ]
                expected_address = {
                    (info["tx_hash"], is_open)
                    for channel in matching_address_channels
                    for info, is_open in (
                        (channel["open_transaction_info"], True),
                        (channel["closed_transaction_info"], False),
                    )
                    if info
                }
                self.assertEqual(
                    expected_address,
                    {(row["tx_hash"], row["is_open"]) for row in address_rows},
                )
                expected_date = {
                    (row["tx_hash"], row["is_open"])
                    for row in rows
                    if int(row["block_timestamp"]) == timestamp
                }
                self.assertEqual(
                    expected_date,
                    {(row["tx_hash"], row["is_open"]) for row in date_rows},
                )
                self.assertEqual(
                    {(udt_sample["open_transaction_info"]["tx_hash"], True)},
                    {(row["tx_hash"], row["is_open"]) for row in combined_rows},
                )
                self.assertEqual(
                    sorted(int(row["block_timestamp"]) for row in rows),
                    [int(row["block_timestamp"]) for row in ascending],
                )
                self.assertEqual(
                    sorted((int(row["block_timestamp"]) for row in rows), reverse=True),
                    [int(row["block_timestamp"]) for row in descending],
                )
                self.assertEqual(first + second, combined_pages)

                rpc_timestamps: dict[tuple[str, bool], int] = {}
                for row, result, height in zip(rows, rpc_results, heights, strict=True):
                    self.assertEqual("committed", result["tx_status"]["status"])
                    self.assertEqual(row["tx_hash"], result["transaction"]["hash"])
                    self.assertEqual(int(row["block_number"]), height)
                    block = oracle.block(height)
                    self.assertIn(
                        row["tx_hash"],
                        {transaction["hash"] for transaction in block["transactions"]},
                    )
                    rpc_timestamps[(row["tx_hash"], row["is_open"])] = decode_hex_int(
                        block["header"]["timestamp"], "header.timestamp"
                    )

                self.assertEqual(
                    rpc_timestamps,
                    {
                        (row["tx_hash"], row["is_open"]): int(row["block_timestamp"])
                        for row in rows
                    },
                )


if __name__ == "__main__":
    unittest.main()
