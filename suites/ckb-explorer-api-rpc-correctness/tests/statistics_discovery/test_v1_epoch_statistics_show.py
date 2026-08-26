from __future__ import annotations

import json
import unittest
from decimal import Decimal, ROUND_DOWN

from ckb_rpc_correctness.ckb import compact_to_difficulty, decode_epoch, decode_hex_int, serialized_block_size_without_uncle_proposals
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


class V1EpochStatisticsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: HIST-STATS-RPC-09
    def test_latest_completed_epoch_metrics_match_every_rpc_block_and_uncle(self) -> None:
        indicator = "difficulty-uncle_rate-hash_rate-epoch_time-epoch_length"
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json(f"/v1/epoch_statistics/{indicator}", {"limit": 1})
                    rows = payload.get("data") if isinstance(payload, dict) else None
                    if not isinstance(rows, list) or len(rows) != 1:
                        raise OracleUnavailable(f"{network.name} latest Epoch statistic is unavailable")
                    attributes = rows[0].get("attributes")
                    if not isinstance(attributes, dict):
                        raise OracleUnavailable(f"{network.name} latest Epoch attributes are unavailable")
                    epoch_number = int(attributes["epoch_number"])
                    epoch = oracle.rpc_result("get_epoch_by_number", [hex(epoch_number)])
                    if not isinstance(epoch, dict):
                        raise OracleUnavailable(f"{network.name} RPC Epoch metadata is unavailable")
                    start = decode_hex_int(epoch.get("start_number"), "epoch.start_number")
                    length = decode_hex_int(epoch.get("length"), "epoch.length")
                    heights = list(range(start, start + length))
                    oracle.prefetch_blocks(heights)
                    blocks = [oracle.block(height) for height in heights]
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                headers = [block.get("header") for block in blocks]
                self.assertTrue(all(isinstance(header, dict) for header in headers))
                self.assertTrue(all(decode_epoch(header).number == epoch_number for header in headers))
                difficulty = compact_to_difficulty(headers[0]["compact_target"])
                first_timestamp = decode_hex_int(headers[0]["timestamp"], "header.timestamp")
                last_timestamp = decode_hex_int(headers[-1]["timestamp"], "header.timestamp")
                epoch_time = last_timestamp - first_timestamp
                uncles_count = sum(len(block.get("uncles", [])) for block in blocks)
                uncle_rate = (Decimal(uncles_count) / Decimal(length)).quantize(
                    Decimal("0.00001"), rounding=ROUND_DOWN
                )
                self.assertEqual(difficulty, int(attributes["difficulty"]))
                self.assertEqual(length, int(attributes["epoch_length"]))
                self.assertEqual(epoch_time, int(attributes["epoch_time"]))
                self.assertEqual(difficulty * length // epoch_time, int(attributes["hash_rate"]))
                self.assertEqual(uncle_rate, Decimal(attributes["uncle_rate"]))

    # TEST-MAP: HIST-STATS-RPC-10
    def test_limit_selects_the_latest_epochs_then_returns_them_ascending(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    one = oracle.explorer_json("/v1/epoch_statistics/difficulty", {"limit": 1})
                    three = oracle.explorer_json("/v1/epoch_statistics/difficulty", {"limit": 3})
                    all_rows = oracle.explorer_json("/v1/epoch_statistics/difficulty")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                one_data = one.get("data") if isinstance(one, dict) else None
                three_data = three.get("data") if isinstance(three, dict) else None
                full_data = all_rows.get("data") if isinstance(all_rows, dict) else None
                self.assertIsInstance(one_data, list)
                self.assertIsInstance(three_data, list)
                self.assertIsInstance(full_data, list)
                self.assertEqual(1, len(one_data))
                self.assertEqual(3, len(three_data))
                self.assertEqual([row["id"] for row in full_data[-3:]], [row["id"] for row in three_data])
                self.assertEqual(three_data[-1]["id"], one_data[0]["id"])
                epochs = [int(row["attributes"]["epoch_number"]) for row in three_data]
                self.assertEqual(sorted(epochs), epochs)

    # TEST-MAP: HIST-STATS-RPC-11
    def test_common_largest_block_transaction_and_time_fields_are_real_epoch_members(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json("/v1/epoch_statistics/epoch_length", {"limit": 3})
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                rows = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(rows, list)
                for row in rows:
                    attributes = row["attributes"]
                    epoch_number = int(attributes["epoch_number"])
                    largest_block = attributes["largest_block"]
                    largest_tx = attributes["largest_tx"]
                    try:
                        rpc_block = oracle.block(int(largest_block["number"]))
                        tx_result = oracle.rpc_result("get_transaction", [largest_tx["tx_hash"], "0x0"])
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    header = rpc_block.get("header")
                    self.assertIsInstance(header, dict)
                    self.assertEqual(epoch_number, decode_epoch(header).number)
                    self.assertEqual(int(largest_block["size"]), serialized_block_size_without_uncle_proposals(rpc_block))
                    raw_tx = tx_result.get("transaction") if isinstance(tx_result, dict) else None
                    status = tx_result.get("tx_status") if isinstance(tx_result, dict) else None
                    self.assertIsInstance(raw_tx, str)
                    self.assertEqual(int(largest_tx["bytes"]), (len(raw_tx) - 2) // 2 + 4)
                    self.assertIsInstance(status, dict)
                    tx_block = oracle.block_by_hash(status["block_hash"])
                    self.assertEqual(epoch_number, decode_epoch(tx_block["header"]).number)
                    self.assertTrue(str(attributes["created_at_unixtimestamp"]).isdecimal())

    # TEST-MAP: HIST-STATS-RPC-16
    def test_unknown_epoch_indicator_returns_422_code_1024(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    status, raw = _raw_explorer_response(oracle, "/v1/epoch_statistics/not-an-epoch")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                body = json.loads(raw)
                self.assertEqual(422, status)
                self.assertIsInstance(body, list)
                self.assertEqual(1024, body[0].get("code"))
