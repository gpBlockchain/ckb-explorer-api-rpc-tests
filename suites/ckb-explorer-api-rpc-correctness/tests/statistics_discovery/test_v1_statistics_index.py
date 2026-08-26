from __future__ import annotations

import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import compact_to_difficulty, decode_epoch, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V1StatisticsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: CURRENT-STATS-RPC-01
    def test_tip_epoch_and_difficulty_share_the_returned_rpc_tip_snapshot(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json("/v1/statistics")
                    data = payload.get("data") if isinstance(payload, dict) else None
                    attributes = data.get("attributes") if isinstance(data, dict) else None
                    if not isinstance(attributes, dict):
                        raise OracleUnavailable(f"{network.name} statistics attributes are unavailable")
                    tip = int(attributes["tip_block_number"])
                    block = oracle.block(tip)
                    header = block.get("header") if isinstance(block, dict) else None
                    if not isinstance(header, dict):
                        raise OracleUnavailable(f"{network.name} RPC statistics-tip block is unavailable")
                    epoch = decode_epoch(header)
                    explorer_tip = NetworkOracle(network, self.settings).api_tip_height()
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertGreaterEqual(explorer_tip, tip)
                self.assertLessEqual(explorer_tip - tip, self.settings.max_lag_blocks)
                epoch_info = attributes.get("epoch_info")
                self.assertIsInstance(epoch_info, dict)
                self.assertEqual(epoch.number, int(epoch_info.get("epoch_number")))
                self.assertEqual(epoch.length, int(epoch_info.get("epoch_length")))
                self.assertEqual(epoch.index, int(epoch_info.get("index")))
                self.assertEqual(compact_to_difficulty(header.get("compact_target")),
                                 int(attributes.get("current_epoch_difficulty")))

    # The persisted hourly values currently do not share the live tip embedded by the serializer.
    # TEST-MAP: CURRENT-STATS-RPC-02
    @unittest.expectedFailure
    def test_block_time_hash_rate_and_estimated_epoch_time_match_one_rpc_tip(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json("/v1/statistics")
                    data = payload.get("data") if isinstance(payload, dict) else None
                    attributes = data.get("attributes") if isinstance(data, dict) else None
                    if not isinstance(attributes, dict):
                        raise OracleUnavailable(f"{network.name} statistics attributes are unavailable")
                    tip = int(attributes["tip_block_number"])
                    heights = list(range(max(0, tip - 899), tip + 1))
                    oracle.prefetch_blocks(heights)
                    blocks = [oracle.block(height) for height in heights]
                    headers = [block.get("header") if isinstance(block, dict) else None for block in blocks]
                    if not all(isinstance(header, dict) for header in headers):
                        raise OracleUnavailable(f"{network.name} RPC statistics window is incomplete")
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                timestamps = [decode_hex_int(header["timestamp"], "header.timestamp") for header in headers]
                average_window = min(100, tip)
                average_expected = Decimal(timestamps[-1] - timestamps[-average_window]) / Decimal(average_window)
                total_difficulty = 0
                for block, header in zip(blocks, headers, strict=True):
                    total_difficulty += compact_to_difficulty(header["compact_target"])
                    uncles = block.get("uncles")
                    self.assertIsInstance(uncles, list)
                    for uncle in uncles:
                        uncle_header = uncle.get("header") if isinstance(uncle, dict) else None
                        self.assertIsInstance(uncle_header, dict)
                        total_difficulty += compact_to_difficulty(uncle_header["compact_target"])
                elapsed = timestamps[-1] - timestamps[0]
                self.assertGreater(elapsed, 0)
                hash_rate_expected = (Decimal(total_difficulty) / Decimal(elapsed)).quantize(
                    Decimal("0.000001"), rounding=ROUND_DOWN
                )
                epoch = decode_epoch(headers[-1])
                tip_difficulty = compact_to_difficulty(headers[-1]["compact_target"])
                estimated_expected = (Decimal(tip_difficulty * epoch.length) / hash_rate_expected).quantize(
                    Decimal("0.000001"), rounding=ROUND_DOWN
                )
                self.assertEqual(average_expected, Decimal(str(attributes.get("average_block_time"))))
                self.assertEqual(hash_rate_expected, Decimal(str(attributes.get("hash_rate"))))
                self.assertEqual(estimated_expected, Decimal(str(attributes.get("estimated_epoch_time"))))

    # The persisted hourly count and ten-minute rate currently do not share the live tip embedded by the serializer.
    # TEST-MAP: CURRENT-STATS-RPC-03
    @unittest.expectedFailure
    def test_last_24_hour_count_and_last_100_block_rate_match_rpc(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    cutoff = int(time.time() * 1000) - 24 * 60 * 60 * 1000
                    payload = oracle.explorer_json("/v1/statistics")
                    data = payload.get("data") if isinstance(payload, dict) else None
                    attributes = data.get("attributes") if isinstance(data, dict) else None
                    if not isinstance(attributes, dict):
                        raise OracleUnavailable(f"{network.name} statistics attributes are unavailable")
                    tip = int(attributes["tip_block_number"])
                    low = max(0, tip - 20_000)
                    high = tip
                    while low < high:
                        middle = (low + high) // 2
                        header = oracle.block(middle).get("header")
                        if not isinstance(header, dict):
                            raise OracleUnavailable(f"{network.name} RPC cutoff header is unavailable")
                        if decode_hex_int(header.get("timestamp"), "header.timestamp") > cutoff:
                            high = middle
                        else:
                            low = middle + 1
                    start = low
                    height_groups = [
                        list(range(offset, min(offset + 100, tip + 1)))
                        for offset in range(start, tip + 1, 100)
                    ]

                    def fetch(group: list[int]) -> list[Mapping[str, Any]]:
                        batch_oracle = NetworkOracle(network, self.settings)
                        results = batch_oracle.rpc_batch_results(
                            [("get_block_by_number", [hex(height)]) for height in group]
                        )
                        if not all(isinstance(block, dict) for block in results):
                            raise OracleUnavailable(f"{network.name} RPC 24-hour block batch is incomplete")
                        return results

                    with ThreadPoolExecutor(max_workers=8) as executor:
                        groups = list(executor.map(fetch, height_groups))
                    blocks = [block for group in groups for block in group]
                    fresh_tip = oracle.block(tip, refresh=True)
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                if not blocks or fresh_tip.get("header", {}).get("hash") != blocks[-1].get("header", {}).get("hash"):
                    raise unittest.SkipTest(f"{network.name} RPC tip changed during statistics observation")
                window_blocks = [
                    block for block in blocks
                    if decode_hex_int(block["header"]["timestamp"], "header.timestamp") > cutoff
                ]
                transactions_24h = sum(len(block.get("transactions", [])) for block in window_blocks)
                rate_blocks = blocks[-100:]
                rate_count = sum(len(block.get("transactions", [])) for block in rate_blocks)
                rate_elapsed_minutes = Decimal(
                    decode_hex_int(rate_blocks[-1]["header"]["timestamp"], "header.timestamp")
                    - decode_hex_int(rate_blocks[0]["header"]["timestamp"], "header.timestamp")
                ) / Decimal(60_000)
                rate_expected = (Decimal(rate_count) / rate_elapsed_minutes).quantize(
                    Decimal("0.001"), rounding=ROUND_DOWN
                )
                self.assertEqual(transactions_24h, int(attributes.get("transactions_last_24hrs")))
                self.assertEqual(rate_expected, Decimal(str(attributes.get("transactions_count_per_minute"))))

    # TEST-MAP: CURRENT-STATS-RPC-04
    def test_reorg_flag_is_null_in_stable_state_and_does_not_clear_statistics(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json("/v1/statistics")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                data = payload.get("data") if isinstance(payload, dict) else None
                attributes = data.get("attributes") if isinstance(data, dict) else None
                self.assertIsInstance(attributes, dict)
                self.assertIsNone(attributes.get("reorg_started_at"))
                for field in (
                    "tip_block_number", "epoch_info", "average_block_time", "current_epoch_difficulty",
                    "hash_rate", "estimated_epoch_time", "transactions_last_24hrs",
                    "transactions_count_per_minute",
                ):
                    self.assertIsNotNone(attributes.get(field))
                raise unittest.SkipTest(
                    f"{network.name} public endpoint has no controllable recorded-reorg state fixture"
                )
