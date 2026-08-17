from __future__ import annotations

import csv
import io
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import decode_hex_int, derive_miner_address, mature_block_reward
from ckb_rpc_correctness.http import HttpClientError
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings


CSV_HEADER = ["Blockno", "Transactions", "UnixTimestamp", "Reward(CKB)", "Miner", "date(UTC)"]


class V1BlocksDownloadCsvRpcCorrectnessTests(unittest.TestCase):
    # TEST-MAP: BLOCKS-CSV-RPC-01
    def test_header_and_every_row_have_the_six_documented_columns(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                url = network.explorer_api_url + "/v1/blocks/download_csv?" + urlencode(
                    {"start_number": 100, "end_number": 100}
                )
                try:
                    raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
                except HttpClientError as error:
                    raise unittest.SkipTest(f"{network.name} Explorer unavailable: {error}") from error

                table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))

                self.assertGreater(len(table), 1, f"{network.name} CSV must contain a header and data")
                self.assertEqual(CSV_HEADER, table[0])
                self.assertTrue(all(len(row) == len(CSV_HEADER) for row in table[1:]))

    # TEST-MAP: BLOCKS-CSV-RPC-02
    def test_height_filters_are_inclusive_complete_and_descending(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    rpc_blocks = [oracle.block(height) for height in range(100, 105)]
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                expected_heights = sorted(
                    (decode_hex_int(block["header"]["number"], "header.number") for block in rpc_blocks),
                    reverse=True,
                )
                url = network.explorer_api_url + "/v1/blocks/download_csv?" + urlencode(
                    {"start_number": 100, "end_number": 104}
                )

                try:
                    raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
                except HttpClientError as error:
                    raise unittest.SkipTest(f"{network.name} Explorer unavailable: {error}") from error
                table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
                actual_heights = [int(row[0]) for row in table[1:]]

                self.assertEqual([104, 103, 102, 101, 100], expected_heights)
                self.assertEqual(expected_heights, actual_heights)
                self.assertEqual(len(actual_heights), len(set(actual_heights)))

    # TEST-MAP: BLOCKS-CSV-RPC-03
    def test_timestamp_filters_are_inclusive_complete_and_descending(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    rpc_blocks = {height: oracle.block(height) for height in range(99, 106)}
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                timestamps = {
                    height: decode_hex_int(block["header"]["timestamp"], "header.timestamp")
                    for height, block in rpc_blocks.items()
                }
                start_date = timestamps[102]
                end_date = timestamps[104]
                expected_heights = sorted(
                    (height for height, timestamp in timestamps.items() if start_date <= timestamp <= end_date),
                    reverse=True,
                )
                url = network.explorer_api_url + "/v1/blocks/download_csv?" + urlencode(
                    {"start_date": start_date, "end_date": end_date}
                )

                try:
                    raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
                except HttpClientError as error:
                    raise unittest.SkipTest(f"{network.name} Explorer unavailable: {error}") from error
                table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
                actual_heights = [int(row[0]) for row in table[1:]]

                self.assertLess(timestamps[101], start_date)
                self.assertGreater(timestamps[105], end_date)
                self.assertIn(102, expected_heights)
                self.assertIn(104, expected_heights)
                self.assertEqual(expected_heights, actual_heights)

    # TEST-MAP: BLOCKS-CSV-RPC-04
    def test_height_and_timestamp_filters_return_their_intersection(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    rpc_blocks = {height: oracle.block(height) for height in range(100, 105)}
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                timestamps = {
                    height: decode_hex_int(block["header"]["timestamp"], "header.timestamp")
                    for height, block in rpc_blocks.items()
                }
                start_date = timestamps[102]
                end_date = timestamps[104]
                expected_heights = sorted(
                    (
                        height
                        for height, timestamp in timestamps.items()
                        if 100 <= height <= 103 and start_date <= timestamp <= end_date
                    ),
                    reverse=True,
                )
                url = network.explorer_api_url + "/v1/blocks/download_csv?" + urlencode(
                    {
                        "start_number": 100,
                        "end_number": 103,
                        "start_date": start_date,
                        "end_date": end_date,
                    }
                )

                try:
                    raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
                except HttpClientError as error:
                    raise unittest.SkipTest(f"{network.name} Explorer unavailable: {error}") from error
                table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
                actual_heights = [int(row[0]) for row in table[1:]]

                self.assertEqual([103, 102], expected_heights)
                self.assertEqual(expected_heights, actual_heights)

    # TEST-MAP: BLOCKS-CSV-RPC-05
    def test_empty_filter_intersection_returns_only_the_header(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    height_100 = oracle.block(100)
                    height_101 = oracle.block(101)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                timestamp_100 = decode_hex_int(height_100["header"]["timestamp"], "header.timestamp")
                timestamp_101 = decode_hex_int(height_101["header"]["timestamp"], "header.timestamp")
                self.assertNotEqual(timestamp_100, timestamp_101)
                url = network.explorer_api_url + "/v1/blocks/download_csv?" + urlencode(
                    {
                        "start_number": 100,
                        "end_number": 100,
                        "start_date": timestamp_101,
                        "end_date": timestamp_101,
                    }
                )

                try:
                    raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
                except HttpClientError as error:
                    raise unittest.SkipTest(f"{network.name} Explorer unavailable: {error}") from error
                table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))

                self.assertEqual([CSV_HEADER], table)

    # TEST-MAP: BLOCKS-CSV-RPC-06
    def test_default_and_large_ranges_keep_the_latest_five_hundred_blocks(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    before = oracle.explorer_json(
                        "/v1/blocks", {"page": 1, "page_size": 1, "sort": "number.desc"}
                    )
                    oracle.block(100)
                    oracle.block(700)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                before_data = before.get("data") if isinstance(before, dict) else None
                self.assertIsInstance(before_data, list)
                self.assertTrue(before_data)
                before_tip = int(before_data[0]["attributes"]["number"])

                default_url = network.explorer_api_url + "/v1/blocks/download_csv"
                range_url = network.explorer_api_url + "/v1/blocks/download_csv?" + urlencode(
                    {"start_number": 100, "end_number": 700}
                )
                try:
                    default_raw = oracle.client.request_bytes(default_url, headers=V1_HEADERS)
                    range_raw = oracle.client.request_bytes(range_url, headers=V1_HEADERS)
                    after = oracle.explorer_json(
                        "/v1/blocks", {"page": 1, "page_size": 1, "sort": "number.desc"}
                    )
                except (HttpClientError, OracleUnavailable) as error:
                    raise unittest.SkipTest(f"{network.name} oracle unavailable: {error}") from error
                default_table = list(csv.reader(io.StringIO(default_raw.decode("utf-8-sig"))))
                range_table = list(csv.reader(io.StringIO(range_raw.decode("utf-8-sig"))))
                default_heights = [int(row[0]) for row in default_table[1:]]
                range_heights = [int(row[0]) for row in range_table[1:]]
                after_data = after.get("data") if isinstance(after, dict) else None
                self.assertIsInstance(after_data, list)
                self.assertTrue(after_data)
                after_tip = int(after_data[0]["attributes"]["number"])

                with self.subTest(request="default"):
                    self.assertEqual(500, len(default_heights))
                    self.assertGreaterEqual(
                        default_heights[0],
                        before_tip,
                        (
                            f"{network.name} default CSV starts at {default_heights[0]}, "
                            f"before-request tip was {before_tip}"
                        ),
                    )
                    self.assertLessEqual(default_heights[0], after_tip)
                    self.assertEqual(
                        list(range(default_heights[0], default_heights[0] - 500, -1)),
                        default_heights,
                    )
                with self.subTest(request="height-100-700"):
                    self.assertEqual(500, len(range_heights))
                    self.assertEqual(700, range_heights[0])
                    self.assertEqual(201, range_heights[-1])
                    self.assertEqual(list(range(700, 200, -1)), range_heights)

    # TEST-MAP: BLOCKS-CSV-RPC-07
    def test_number_transaction_count_timestamp_and_utc_date_match_rpc(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")
        fixture_heights = {"mainnet": 20_183_437, "testnet": 22_112_360}

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                height = fixture_heights[network.name]
                try:
                    rpc_block = oracle.block(height)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                header = rpc_block.get("header")
                transactions = rpc_block.get("transactions")
                self.assertIsInstance(header, dict)
                self.assertIsInstance(transactions, list)
                self.assertGreater(len(transactions), 1, "fixture must contain Cellbase and a normal transaction")
                expected_number = decode_hex_int(header.get("number"), "header.number")
                expected_timestamp = decode_hex_int(header.get("timestamp"), "header.timestamp")
                expected_date = datetime.fromtimestamp(expected_timestamp // 1000, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                url = network.explorer_api_url + "/v1/blocks/download_csv?" + urlencode(
                    {"start_number": height, "end_number": height}
                )

                try:
                    raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
                except HttpClientError as error:
                    raise unittest.SkipTest(f"{network.name} Explorer unavailable: {error}") from error
                table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))

                self.assertEqual(2, len(table))
                self.assertEqual(expected_number, int(table[1][0]))
                self.assertEqual(len(transactions), int(table[1][1]))
                self.assertEqual(expected_timestamp, int(table[1][2]))
                self.assertEqual(expected_date, table[1][5])

    # TEST-MAP: BLOCKS-CSV-RPC-08
    def test_mature_reward_converts_exactly_from_shannon_to_ckb(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    rpc_block = oracle.block(100)
                    header = rpc_block.get("header")
                    block_hash = header.get("hash") if isinstance(header, dict) else None
                    if not isinstance(block_hash, str):
                        raise OracleUnavailable(f"{network.name} RPC height 100 has no block hash")
                    expected_shannon = mature_block_reward(oracle.economic_state(block_hash))
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(f"{network.name} reward oracle unavailable: {error}") from error
                self.assertGreater(expected_shannon, 0)
                url = network.explorer_api_url + "/v1/blocks/download_csv?" + urlencode(
                    {"start_number": 100, "end_number": 100}
                )

                try:
                    raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
                except HttpClientError as error:
                    raise unittest.SkipTest(f"{network.name} Explorer unavailable: {error}") from error
                table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
                self.assertEqual(2, len(table))
                actual_shannon = Decimal(table[1][3]) * Decimal(100_000_000)

                self.assertEqual(Decimal(expected_shannon), actual_shannon)

    # TEST-MAP: BLOCKS-CSV-RPC-09
    def test_miner_address_matches_the_cellbase_witness(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    rpc_block = oracle.block(100)
                    expected_miner = derive_miner_address(rpc_block, network.address_hrp)
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(f"{network.name} miner oracle unavailable: {error}") from error
                url = network.explorer_api_url + "/v1/blocks/download_csv?" + urlencode(
                    {"start_number": 100, "end_number": 100}
                )

                try:
                    raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
                except HttpClientError as error:
                    raise unittest.SkipTest(f"{network.name} Explorer unavailable: {error}") from error
                table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))

                self.assertEqual(2, len(table))
                self.assertEqual(expected_miner, table[1][4])


if __name__ == "__main__":
    unittest.main()
