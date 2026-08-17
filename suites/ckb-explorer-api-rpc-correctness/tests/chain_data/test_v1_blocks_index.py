from __future__ import annotations

import json
import unittest

from ckb_rpc_correctness.ckb import (
    calculate_live_cell_changes,
    decode_hex_int,
    derive_miner_address,
    mature_block_reward,
)
from ckb_rpc_correctness.oracle import BlockSample, NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V1BlocksIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.oracles = tuple(NetworkOracle(network, cls.settings) for network in cls.settings.networks)

    @staticmethod
    def _skip_unavailable(error: OracleUnavailable) -> None:
        raise unittest.SkipTest(str(error))

    def _sample(self, oracle: NetworkOracle, kind: str = "confirmed") -> BlockSample:
        try:
            sample = {
                "confirmed": oracle.confirmed_sample,
                "transaction": oracle.transaction_sample,
                "live-change": oracle.live_change_sample,
                "miner": oracle.miner_sample,
            }[kind]()
            oracle.ensure_stable(sample)
            return sample
        except OracleUnavailable as error:
            self._skip_unavailable(error)
            raise AssertionError("unreachable")

    # TEST-MAP: BLOCKS-RPC-01
    def test_network_genesis_identity(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    api_hash = oracle.detail_attributes(0).get("block_hash")
                    rpc_header = oracle.block(0).get("header")
                    rpc_hash = rpc_header.get("hash") if isinstance(rpc_header, dict) else None
                except OracleUnavailable as error:
                    self._skip_unavailable(error)
                self.assertEqual(
                    rpc_hash,
                    api_hash,
                    f"{oracle.network.name} genesis mismatch: api={api_hash!r}, rpc={rpc_hash!r}",
                )

    # TEST-MAP: BLOCKS-RPC-02
    def test_tip_lag_is_at_most_five_blocks(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    api_tip = oracle.api_tip_height()
                    rpc_tip = oracle.rpc_tip_height()
                except OracleUnavailable as error:
                    self._skip_unavailable(error)
                lag = rpc_tip - api_tip
                print(
                    json.dumps(
                        {"event": "tip_lag", "network": oracle.network.name, "api_tip": api_tip, "rpc_tip": rpc_tip, "lag": lag},
                        sort_keys=True,
                    ),
                    flush=True,
                )
                if lag < 0:
                    continue
                self.assertLessEqual(
                    lag,
                    self.settings.max_lag_blocks,
                    f"{oracle.network.name} Explorer lags RPC by {lag} blocks; maximum is {self.settings.max_lag_blocks}",
                )

    # TEST-MAP: BLOCKS-RPC-03
    def test_block_number_matches_rpc_header(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle)
                header = sample.rpc_block.get("header")
                raw = header.get("number") if isinstance(header, dict) else None
                expected = decode_hex_int(raw, "header.number")
                actual = int(sample.attributes["number"])
                self.assertEqual(expected, sample.height)
                self.assertEqual(
                    expected,
                    actual,
                    f"{sample.network} height {sample.height} number mismatch: api={actual}, rpc_raw={raw!r}, expected={expected}",
                )

    # TEST-MAP: BLOCKS-RPC-04
    def test_block_timestamp_matches_rpc_header(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle)
                header = sample.rpc_block.get("header")
                raw = header.get("timestamp") if isinstance(header, dict) else None
                expected = decode_hex_int(raw, "header.timestamp")
                actual = int(sample.attributes["timestamp"])
                self.assertEqual(
                    expected,
                    actual,
                    f"{sample.network} height {sample.height} timestamp mismatch: api={actual}, rpc_raw={raw!r}, expected={expected}",
                )

    # TEST-MAP: BLOCKS-RPC-05
    def test_block_hash_matches_rpc_canonical_block(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle)
                detail_hash = oracle.detail_attributes(sample.height).get("block_hash")
                header = sample.rpc_block.get("header")
                rpc_hash = header.get("hash") if isinstance(header, dict) else None
                self.assertEqual(
                    rpc_hash,
                    detail_hash,
                    f"{sample.network} height {sample.height} hash mismatch: api={detail_hash!r}, rpc={rpc_hash!r}",
                )

    # TEST-MAP: BLOCKS-RPC-06
    def test_transactions_count_matches_rpc_block(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, "transaction")
                transactions = sample.rpc_block.get("transactions")
                self.assertIsInstance(transactions, list)
                expected = len(transactions)
                actual = int(sample.attributes["transactions_count"])
                self.assertGreater(expected, 1, "fixture must contain Cellbase and a normal transaction")
                self.assertEqual(
                    expected,
                    actual,
                    f"{sample.network} height {sample.height} transactions_count mismatch: api={actual}, rpc={expected}",
                )

    # TEST-MAP: BLOCKS-RPC-07
    def test_live_cell_changes_matches_rpc_derivation(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, "live-change")
                expected = calculate_live_cell_changes(sample.rpc_block)
                actual = int(sample.attributes["live_cell_changes"])
                self.assertNotEqual(1, expected, "fixture must exercise non-trivial input/output changes")
                self.assertEqual(
                    expected,
                    actual,
                    f"{sample.network} height {sample.height} live_cell_changes mismatch: api={actual}, rpc_derived={expected}",
                )

    # TEST-MAP: BLOCKS-RPC-08
    def test_miner_hash_matches_cellbase_witness_address(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                sample = self._sample(oracle, "miner")
                expected = derive_miner_address(sample.rpc_block, oracle.network.address_hrp)
                actual = sample.attributes.get("miner_hash")
                self.assertEqual(
                    expected,
                    actual,
                    f"{sample.network} height {sample.height} miner_hash mismatch: api={actual!r}, rpc_derived={expected!r}",
                )

    # TEST-MAP: BLOCKS-RPC-09
    def test_mature_reward_matches_rpc_economic_state(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    sample, economic_state = oracle.reward_sample()
                    oracle.ensure_stable(sample)
                except OracleUnavailable as error:
                    self._skip_unavailable(error)
                expected = mature_block_reward(economic_state)
                actual = int(sample.attributes["reward"])
                self.assertEqual(
                    expected,
                    actual,
                    f"{sample.network} height {sample.height} reward mismatch: api={actual}, rpc_derived={expected}",
                )

    # TEST-MAP: BLOCKS-RPC-10
    def test_genesis_reward_remains_zero(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    actual = int(oracle.detail_attributes(0)["reward"])
                except OracleUnavailable as error:
                    self._skip_unavailable(error)
                self.assertEqual(0, actual, f"{oracle.network.name} genesis reward must remain zero, got {actual}")


if __name__ == "__main__":
    unittest.main()
