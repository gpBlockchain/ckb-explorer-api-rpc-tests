from __future__ import annotations

import unittest

from ckb_rpc_correctness.ckb import (
    DEFAULT_EPOCH_REWARD,
    HALVING_EPOCH,
    LockScript,
    block_cycles,
    calculate_live_cell_changes,
    compact_to_difficulty,
    ckb2021_address,
    decode_epoch,
    decode_hex_int,
    parse_cellbase_message,
    parse_cellbase_lock,
    pending_base_reward,
    serialized_block_size_without_uncle_proposals,
    total_cell_consumed,
    total_output_capacity,
)


CELLBASE_WITNESS = (
    "0x5d0000000c0000005500000049000000100000003000000031000000"
    "9bd7e06f3ecf4be0f2fcd2188b23f1b9fcc88e5d4b65a8637b17723bbda3cce8"
    "011400000036c329ed630d6ce750712a477543672adab57f4c0400000012345678"
)


class CkbDerivationTests(unittest.TestCase):
    def test_decode_hex_int_preserves_large_values(self) -> None:
        self.assertEqual(2**80 + 123, decode_hex_int(hex(2**80 + 123), "value"))

    def test_parse_cellbase_lock_and_generate_ckb2021_address(self) -> None:
        lock = parse_cellbase_lock(CELLBASE_WITNESS)
        self.assertEqual("0x9bd7e06f3ecf4be0f2fcd2188b23f1b9fcc88e5d4b65a8637b17723bbda3cce8", lock.code_hash)
        self.assertEqual("type", lock.hash_type)
        self.assertEqual("0x36c329ed630d6ce750712a477543672adab57f4c", lock.args)
        self.assertEqual(
            "ckt1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqfkcv576ccddnn4quf2ga65xee2m26h7nq4sds0r",
            ckb2021_address(lock, "ckt"),
        )
        self.assertEqual("0x12345678", parse_cellbase_message(CELLBASE_WITNESS))

    def test_ckb2021_mainnet_prefix_uses_same_script_payload(self) -> None:
        lock = LockScript(
            "0x9bd7e06f3ecf4be0f2fcd2188b23f1b9fcc88e5d4b65a8637b17723bbda3cce8",
            "type",
            "0x36c329ed630d6ce750712a477543672adab57f4c",
        )
        self.assertTrue(ckb2021_address(lock, "ckb").startswith("ckb1"))

    def test_live_cell_changes_counts_cellbase_as_one(self) -> None:
        block = {
            "transactions": [
                {"inputs": [{}], "outputs": [{}]},
                {"inputs": [{}, {}], "outputs": [{}, {}, {}]},
                {"inputs": [{}], "outputs": []},
            ]
        }
        self.assertEqual(1, calculate_live_cell_changes(block))

    def test_epoch_difficulty_and_pending_reward_use_integer_derivations(self) -> None:
        packed_epoch = (1800 << 40) | (7 << 24) | 14759
        epoch = decode_epoch({"number": hex(20_000_000), "epoch": hex(packed_epoch)})
        self.assertEqual((14759, 7, 1800, 19_999_993), (epoch.number, epoch.index, epoch.length, epoch.start_number))

        compact = 0x1D00FFFF
        target = 0x00FFFF << (8 * (0x1D - 3))
        self.assertEqual(2**256 // target, compact_to_difficulty(hex(compact)))

        expected_epoch_reward = DEFAULT_EPOCH_REWARD >> (epoch.number // HALVING_EPOCH)
        base, remainder = divmod(expected_epoch_reward, epoch.length)
        expected = base + int(epoch.start_number <= 20_000_000 < epoch.start_number + remainder)
        self.assertEqual(expected, pending_base_reward(20_000_000, epoch))

    def test_capacity_consumed_size_and_cycles_derivations(self) -> None:
        lock = {
            "code_hash": "0x" + "11" * 32,
            "hash_type": "type",
            "args": "0x" + "22" * 20,
        }
        type_script = {
            "code_hash": "0x" + "33" * 32,
            "hash_type": "type",
            "args": "0x" + "44" * 32,
        }
        transaction = {
            "version": "0x0",
            "cell_deps": [],
            "header_deps": [],
            "inputs": [{"since": "0x0", "previous_output": {"tx_hash": "0x" + "00" * 32, "index": "0xffffffff"}}],
            "outputs": [
                {"capacity": "0x64", "lock": lock, "type": None},
                {"capacity": "0xc8", "lock": lock, "type": type_script},
            ],
            "outputs_data": ["0x", "0x01020304"],
            "witnesses": [CELLBASE_WITNESS],
        }
        block = {
            "header": {},
            "uncles": [],
            "transactions": [transaction],
            "proposals": [],
            "extension": None,
        }
        self.assertEqual(300, total_output_capacity(block))
        self.assertEqual((61 + 130) * 100_000_000, total_cell_consumed(block))

        script_capacity = 53 + 20
        first_output_capacity = 24 + script_capacity
        second_output_capacity = 24 + script_capacity + (53 + 32)
        outputs_capacity = 4 + 2 * 4 + first_output_capacity + second_output_capacity
        outputs_data_capacity = 4 + 2 * 4 + (4 + 0) + (4 + 4)
        raw_transaction_capacity = 28 + 4 + 4 + 4 + (4 + 44) + outputs_capacity + outputs_data_capacity
        witnesses_capacity = 4 + 4 + 4 + len(bytes.fromhex(CELLBASE_WITNESS[2:]))
        transaction_capacity = 12 + raw_transaction_capacity + witnesses_capacity
        expected_block_capacity = 24 + 208 + 4 + (4 + 4 + transaction_capacity) + 4 + 4
        self.assertEqual(expected_block_capacity, serialized_block_size_without_uncle_proposals(block))
        self.assertEqual(0x600, block_cycles({"cycles": ["0x100", "0x200", "0x300"]}))


if __name__ == "__main__":
    unittest.main()
