from __future__ import annotations

import unittest
from collections.abc import Callable
from typing import Any, Mapping, TypeVar

from ckb_rpc_correctness.ckb import (
    block_cycles,
    compact_to_difficulty,
    decode_epoch,
    decode_hex_int,
    derive_miner_address,
    derive_miner_message,
    miner_reward,
    pending_base_reward,
    serialized_block_size_without_uncle_proposals,
    total_cell_consumed,
    total_output_capacity,
)
from ckb_rpc_correctness.oracle import BlockSample, NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


T = TypeVar("T")


class V1BlocksShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.oracles = tuple(NetworkOracle(network, cls.settings) for network in cls.settings.networks)

    def _available(self, operation: Callable[[], T]) -> T:
        try:
            return operation()
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error

    def _sample(self, oracle: NetworkOracle, operation: Callable[[], BlockSample]) -> BlockSample:
        sample = self._available(operation)
        self._available(lambda: oracle.ensure_stable(sample))
        return sample

    def _header(self, sample: BlockSample) -> Mapping[str, Any]:
        header = sample.rpc_block.get("header")
        self.assertIsInstance(header, dict, f"{sample.network} height {sample.height} RPC header is invalid")
        return header  # type: ignore[return-value]

    def _assert_decimal_field(self, sample: BlockSample, field: str, expected: int) -> None:
        actual = int(sample.attributes[field])
        self.assertEqual(
            expected,
            actual,
            f"{sample.network} height {sample.height} {field} mismatch: api={actual}, expected={expected}",
        )

    # TEST-MAP: BLOCK-DETAIL-RPC-01
    def test_height_and_hash_queries_resolve_the_same_canonical_block(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, lambda: oracle.detail_sample("confirmed"))
                header = self._header(sample)
                rpc_hash = header.get("hash")
                self.assertIsInstance(rpc_hash, str)
                by_hash = self._available(lambda: oracle.detail_attributes(rpc_hash))
                rpc_by_hash = self._available(lambda: oracle.block_by_hash(rpc_hash))
                self.assertEqual(sample.attributes, by_hash)
                self.assertEqual(sample.height, int(sample.attributes["number"]))
                self.assertEqual(rpc_hash, sample.attributes.get("block_hash"))
                self.assertEqual(rpc_hash, rpc_by_hash.get("header", {}).get("hash"))

    # TEST-MAP: BLOCK-DETAIL-RPC-02
    def test_direct_header_fields_match_rpc(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, lambda: oracle.detail_sample("confirmed"))
                header = self._header(sample)
                for field in ("timestamp", "version", "nonce"):
                    self._assert_decimal_field(sample, field, decode_hex_int(header.get(field), f"header.{field}"))
                self.assertEqual(header.get("transactions_root"), sample.attributes.get("transactions_root"))

    # TEST-MAP: BLOCK-DETAIL-RPC-03
    def test_epoch_fields_match_compact_epoch_decoding(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, lambda: oracle.detail_sample("confirmed"))
                epoch = decode_epoch(self._header(sample))
                for field, expected in (
                    ("epoch", epoch.number),
                    ("block_index_in_epoch", epoch.index),
                    ("length", epoch.length),
                    ("start_number", epoch.start_number),
                ):
                    self._assert_decimal_field(sample, field, expected)

    # TEST-MAP: BLOCK-DETAIL-RPC-04
    def test_difficulty_matches_compact_target_derivation(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, lambda: oracle.detail_sample("confirmed"))
                expected = compact_to_difficulty(self._header(sample).get("compact_target"))
                self._assert_decimal_field(sample, "difficulty", expected)

    # TEST-MAP: BLOCK-DETAIL-RPC-05
    def test_transactions_count_includes_cellbase_and_matches_rpc(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, lambda: oracle.detail_sample("transaction"))
                transactions = sample.rpc_block.get("transactions")
                self.assertIsInstance(transactions, list)
                self.assertGreater(len(transactions), 1)
                self._assert_decimal_field(sample, "transactions_count", len(transactions))

    # TEST-MAP: BLOCK-DETAIL-RPC-06
    def test_proposals_count_matches_rpc(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, oracle.proposal_sample)
                proposals = sample.rpc_block.get("proposals")
                self.assertIsInstance(proposals, list)
                self.assertGreater(len(proposals), 0)
                self._assert_decimal_field(sample, "proposals_count", len(proposals))

    # TEST-MAP: BLOCK-DETAIL-RPC-07
    def test_uncle_count_hashes_order_and_empty_representation_match_rpc(self) -> None:
        for oracle in self.oracles:
            for present in (False, True):
                with self.subTest(network=oracle.network.name, uncle_present=present):
                    sample = self._sample(oracle, lambda present=present: oracle.uncle_sample(present=present))
                    uncles = sample.rpc_block.get("uncles")
                    self.assertIsInstance(uncles, list)
                    hashes = [uncle.get("header", {}).get("hash") for uncle in uncles]
                    self._assert_decimal_field(sample, "uncles_count", len(uncles))
                    if present:
                        self.assertGreater(len(uncles), 0)
                        self.assertEqual(hashes, sample.attributes.get("uncle_block_hashes"))
                    else:
                        self.assertEqual([], uncles)
                        self.assertIsNone(sample.attributes.get("uncle_block_hashes"))

    # TEST-MAP: BLOCK-DETAIL-RPC-08
    def test_miner_address_and_message_match_cellbase_witness(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, lambda: oracle.detail_sample("miner"))
                self.assertEqual(
                    derive_miner_address(sample.rpc_block, oracle.network.address_hrp),
                    sample.attributes.get("miner_hash"),
                )
                self.assertEqual(derive_miner_message(sample.rpc_block), sample.attributes.get("miner_message"))

    # TEST-MAP: BLOCK-DETAIL-RPC-09
    def test_total_cell_capacity_matches_all_rpc_outputs(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, lambda: oracle.output_sample(typed_or_data=False))
                self._assert_decimal_field(sample, "total_cell_capacity", total_output_capacity(sample.rpc_block))

    # TEST-MAP: BLOCK-DETAIL-RPC-10
    def test_cell_consumed_matches_minimum_occupied_capacity(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, lambda: oracle.output_sample(typed_or_data=True))
                self._assert_decimal_field(sample, "cell_consumed", total_cell_consumed(sample.rpc_block))

    # TEST-MAP: BLOCK-DETAIL-RPC-11
    def test_total_transaction_fee_matches_nonzero_rpc_economic_state(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample, state = self._available(oracle.fee_sample)
                self._available(lambda: oracle.ensure_stable(sample))
                expected = decode_hex_int(state.get("txs_fee"), "economic_state.txs_fee")
                self.assertGreater(expected, 0)
                self._assert_decimal_field(sample, "total_transaction_fee", expected)

    # TEST-MAP: BLOCK-DETAIL-RPC-12
    def test_mature_reward_components_and_statuses_match_rpc(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample, state = self._available(oracle.detail_reward_sample)
                self._available(lambda: oracle.ensure_stable(sample))
                expected = miner_reward(state)
                self.assertEqual("issued", sample.attributes.get("reward_status"))
                self.assertEqual("calculated", sample.attributes.get("received_tx_fee_status"))
                self._assert_decimal_field(sample, "reward", expected.reward)
                self._assert_decimal_field(sample, "received_tx_fee", expected.received_tx_fee)
                self._assert_decimal_field(sample, "miner_reward", expected.total)

    # TEST-MAP: BLOCK-DETAIL-RPC-13
    def test_pending_reward_and_statuses_match_base_reward_rules(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, oracle.pending_sample)
                depth = self._available(oracle.rpc_tip_height) - sample.height
                self.assertLessEqual(depth, self.settings.proposal_window)
                epoch = decode_epoch(self._header(sample))
                expected = pending_base_reward(sample.height, epoch)
                self.assertEqual("pending", sample.attributes.get("reward_status"))
                self.assertEqual("pending", sample.attributes.get("received_tx_fee_status"))
                self._assert_decimal_field(sample, "received_tx_fee", 0)
                self._assert_decimal_field(sample, "reward", expected)
                self._assert_decimal_field(sample, "miner_reward", expected)

    # TEST-MAP: BLOCK-DETAIL-RPC-14
    def test_genesis_reward_fields_follow_special_rules(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                attributes = self._available(lambda: oracle.detail_attributes(0))
                self.assertEqual("issued", attributes.get("reward_status"))
                self.assertEqual("pending", attributes.get("received_tx_fee_status"))
                for field in ("reward", "received_tx_fee", "miner_reward"):
                    self.assertEqual(0, int(attributes[field]))

    # TEST-MAP: BLOCK-DETAIL-RPC-15
    def test_serialized_block_size_matches_rpc_body(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, lambda: oracle.detail_sample("transaction"))
                expected = serialized_block_size_without_uncle_proposals(sample.rpc_block)
                self.assertGreater(expected, 0)
                self.assertEqual(expected, sample.attributes.get("size"))

    # TEST-MAP: BLOCK-DETAIL-RPC-16
    def test_cycles_match_sum_of_non_cellbase_rpc_cycles(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, lambda: oracle.detail_sample("transaction"))
                result = self._available(lambda: oracle.block_with_cycles(sample.height))
                cycles = result.get("cycles")
                self.assertIsInstance(cycles, list)
                self.assertGreater(len(cycles), 0)
                self.assertEqual(block_cycles(result), sample.attributes.get("cycles"))

    # TEST-MAP: BLOCK-DETAIL-RPC-17
    def test_completed_epoch_size_and_cycles_extrema_match_rpc_scan(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                extrema = self._available(oracle.completed_epoch_extrema)
                self.assertEqual(extrema.largest_block, extrema.attributes.get("largest_block_in_epoch"))
                self.assertEqual(extrema.max_cycles, extrema.attributes.get("max_cycles_in_epoch"))

    # TEST-MAP: BLOCK-DETAIL-RPC-18
    def test_incomplete_epoch_extrema_remain_null(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, oracle.pending_sample)
                epoch = decode_epoch(self._header(sample))
                if epoch.index + 1 >= epoch.length:
                    raise unittest.SkipTest(f"{oracle.network.name} tip Epoch completed during observation")
                self.assertIsNone(sample.attributes.get("largest_block_in_epoch"))
                self.assertIsNone(sample.attributes.get("max_cycles_in_epoch"))

    # TEST-MAP: BLOCK-DETAIL-RPC-19
    def test_global_extrema_are_constant_and_dominate_verified_epoch_values(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                current = self._sample(oracle, oracle.pending_sample)
                genesis = self._available(lambda: oracle.detail_attributes(0))
                completed = self._available(oracle.completed_epoch_extrema)
                statistics = self._available(oracle.epoch_statistics)
                expected_largest = max(
                    int(item["largest_block"]["size"])
                    for item in statistics
                    if isinstance(item.get("largest_block"), dict) and item["largest_block"].get("size") is not None
                )
                for attributes in (current.attributes, genesis, completed.attributes):
                    self.assertEqual(expected_largest, attributes.get("largest_block"))
                    self.assertEqual(current.attributes.get("max_cycles"), attributes.get("max_cycles"))
                self.assertGreaterEqual(expected_largest, completed.largest_block)
                if completed.max_cycles is not None:
                    self.assertGreaterEqual(int(current.attributes["max_cycles"]), completed.max_cycles)


if __name__ == "__main__":
    unittest.main()
