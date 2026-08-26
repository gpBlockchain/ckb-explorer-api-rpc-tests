from __future__ import annotations

import unittest

from ckb_rpc_correctness.ckb import decode_epoch, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V2BlocksByEpochRpcCorrectnessTests(unittest.TestCase):
    # TEST-MAP: V2-BLOCK-BY-EPOCH-RPC-01
    def test_historical_epoch_first_middle_and_last_blocks_match_rpc(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    api_genesis = oracle.detail_attributes(0)
                    rpc_genesis = oracle.block(0)
                    api_tip = oracle.api_tip_height()
                    rpc_tip = oracle.rpc_tip_height()
                    api_tip_block = oracle.block(api_tip)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                genesis_header = rpc_genesis.get("header")
                api_tip_header = api_tip_block.get("header")
                self.assertIsInstance(genesis_header, dict)
                self.assertIsInstance(api_tip_header, dict)
                self.assertEqual(genesis_header.get("hash"), api_genesis.get("block_hash"))
                self.assertLessEqual(api_tip, rpc_tip)
                self.assertLessEqual(rpc_tip - api_tip, settings.max_lag_blocks)

                target_epoch = max(0, decode_epoch(api_tip_header).number - 2)
                try:
                    epoch = oracle.rpc_result("get_epoch_by_number", [hex(target_epoch)])
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if not isinstance(epoch, dict):
                    raise unittest.SkipTest(
                        f"{network.name} RPC Epoch {target_epoch} is unavailable"
                    )
                start_number = decode_hex_int(epoch.get("start_number"), "epoch.start_number")
                length = decode_hex_int(epoch.get("length"), "epoch.length")
                self.assertEqual(target_epoch, decode_hex_int(epoch.get("number"), "epoch.number"))
                self.assertGreater(length, 2)
                indexes = (0, length // 2, length - 1)
                self.assertEqual(3, len(set(indexes)))

                for epoch_index in indexes:
                    with self.subTest(network=network.name, epoch_index=epoch_index):
                        height = start_number + epoch_index
                        try:
                            rpc_block = oracle.block(height)
                            payload = oracle.explorer_json(
                                "/v2/blocks/by_epoch",
                                {
                                    "epoch_number": target_epoch,
                                    "epoch_index": epoch_index,
                                },
                            )
                        except OracleUnavailable as error:
                            raise unittest.SkipTest(str(error)) from error
                        data = payload.get("data") if isinstance(payload, dict) else None
                        attributes = data.get("attributes") if isinstance(data, dict) else None
                        header = rpc_block.get("header")
                        proposals = rpc_block.get("proposals")
                        uncles = rpc_block.get("uncles")
                        transactions = rpc_block.get("transactions")
                        self.assertIsInstance(data, dict)
                        self.assertEqual("block", data.get("type"))
                        self.assertIsInstance(attributes, dict)
                        self.assertIsInstance(header, dict)
                        self.assertIsInstance(proposals, list)
                        self.assertIsInstance(uncles, list)
                        self.assertIsInstance(transactions, list)
                        rpc_epoch = decode_epoch(header)
                        self.assertEqual(target_epoch, rpc_epoch.number)
                        self.assertEqual(start_number, rpc_epoch.start_number)
                        self.assertEqual(length, rpc_epoch.length)
                        self.assertEqual(epoch_index, rpc_epoch.index)

                        self.assertEqual(header.get("hash"), attributes.get("block_hash"))
                        self.assertEqual(height, int(attributes.get("number")))
                        self.assertEqual(target_epoch, int(attributes.get("epoch")))
                        self.assertEqual(start_number, int(attributes.get("start_number")))
                        self.assertEqual(length, int(attributes.get("length")))
                        self.assertEqual(epoch_index, int(attributes.get("block_index_in_epoch")))
                        self.assertEqual(
                            decode_hex_int(header.get("timestamp"), "header.timestamp"),
                            int(attributes.get("timestamp")),
                        )
                        self.assertEqual(
                            header.get("transactions_root"), attributes.get("transactions_root")
                        )
                        self.assertEqual(
                            decode_hex_int(header.get("version"), "header.version"),
                            int(attributes.get("version")),
                        )
                        self.assertEqual(
                            decode_hex_int(header.get("nonce"), "header.nonce"),
                            int(attributes.get("nonce")),
                        )
                        self.assertEqual(len(uncles), int(attributes.get("uncles_count")))
                        self.assertEqual(len(proposals), int(attributes.get("proposals_count")))
                        self.assertEqual(
                            len(transactions), int(attributes.get("transactions_count"))
                        )
                        try:
                            fresh = oracle.block(height)
                        except OracleUnavailable as error:
                            raise unittest.SkipTest(str(error)) from error
                        fresh_header = fresh.get("header")
                        if not isinstance(fresh_header, dict):
                            raise unittest.SkipTest(
                                f"{network.name} RPC block {height} became unavailable"
                            )
                        if fresh_header.get("hash") != header.get("hash"):
                            raise unittest.SkipTest(
                                f"{network.name} RPC block {height} changed during observation"
                            )


if __name__ == "__main__":
    unittest.main()
