from __future__ import annotations

import unittest

from ckb_rpc_correctness.ckb import (
    LockScript,
    calculate_live_cell_changes,
    ckb2021_address,
    decode_hex_int,
    parse_cellbase_lock,
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


if __name__ == "__main__":
    unittest.main()
