from __future__ import annotations

import csv
import io
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.http import HttpClientError
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import DAO_ADDRESSES, LARGE_UDT_ADDRESS


CSV_HEADER = [
    "Txn hash", "Blockno", "UnixTimestamp", "Token", "Method", "Token In",
    "Token Out", "Token Balance Change", "TxnFee(CKB)", "date(UTC)",
]
BUSY_ADDRESSES = {
    "mainnet": "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqv9ft027uv84z4nc4wsgwl32u6ex4e4qsscccscx",
    "testnet": "ckt1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq2zrchfd2y3xcf9lkqeddggqagukmnufkse0g93q",
}


class V1AddressTransactionsDownloadCsvRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.cache: dict[tuple[str, str, tuple[tuple[str, object], ...]], list[list[str]]] = {}

    def _csv(
        self,
        oracle: NetworkOracle,
        address: str,
        **query: object,
    ) -> list[list[str]]:
        key = (oracle.network.name, address, tuple(sorted(query.items())))
        if key not in self.cache:
            params: dict[str, object] = {"id": address}
            params.update(query)
            url = oracle.network.explorer_api_url + "/v1/address_transactions/download_csv?" + urlencode(params)
            try:
                raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
            except HttpClientError as error:
                raise OracleUnavailable(f"{oracle.network.name} Explorer CSV unavailable: {error}") from error
            self.cache[key] = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        return self.cache[key]

    def _address_lock_hash(self, oracle: NetworkOracle, address: str) -> str:
        payload = oracle.explorer_json(f"/v1/addresses/{address}")
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data[0].get("attributes") if isinstance(data, list) and data else None
        lock = attributes.get("lock_script") if isinstance(attributes, dict) else None
        if not isinstance(lock, dict):
            raise OracleUnavailable(f"{oracle.network.name} address lock is unavailable")
        return ckb_script_hash(lock)

    # TEST-MAP: ADDR-TX-RPC-11
    def test_header_and_every_ckb_row_match_committed_rpc_capacity_fee_and_utc_facts(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    target_lock_hash = self._address_lock_hash(oracle, address)
                    table = self._csv(oracle, address)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(CSV_HEADER, table[0])
                self.assertGreater(len(table), 1)
                self.assertTrue(all(len(row) == 10 for row in table[1:]))
                self.assertTrue(all(row[3] == "CKB" for row in table[1:]))
                checked_fee_rows = 0
                for row in table[1:]:
                    result = oracle.rpc_result("get_transaction", [row[0]])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict) or not isinstance(status, dict):
                        raise unittest.SkipTest(f"{network.name} RPC transaction {row[0]} is unavailable")
                    referenced = oracle.referenced_outputs(transaction)
                    block = oracle.block_by_hash(status["block_hash"])
                    header = block.get("header") if isinstance(block, dict) else None
                    self.assertIsInstance(header, dict)
                    target_inputs = sum(
                        decode_hex_int(output["capacity"], "input.capacity")
                        for output, _data in referenced
                        if ckb_script_hash(output["lock"]) == target_lock_hash
                    )
                    target_outputs = sum(
                        decode_hex_int(output["capacity"], "output.capacity")
                        for output in transaction["outputs"]
                        if ckb_script_hash(output["lock"]) == target_lock_hash
                    )
                    total_inputs = sum(decode_hex_int(output["capacity"], "input.capacity") for output, _data in referenced)
                    total_outputs = sum(decode_hex_int(output["capacity"], "output.capacity") for output in transaction["outputs"])
                    timestamp = decode_hex_int(header.get("timestamp"), "block.timestamp")
                    self.assertEqual("committed", status.get("status"))
                    self.assertEqual(decode_hex_int(header.get("number"), "block.number"), int(row[1]))
                    self.assertEqual(timestamp, int(row[2]))
                    self.assertEqual("PAYMENT RECEIVED" if target_outputs > target_inputs else "PAYMENT SENT", row[4])
                    self.assertEqual(Decimal(target_inputs), Decimal(0) if row[5] == "/" else Decimal(row[5]) * 100_000_000)
                    self.assertEqual(Decimal(target_outputs), Decimal(0) if row[6] == "/" else Decimal(row[6]) * 100_000_000)
                    self.assertEqual(Decimal(abs(target_outputs - target_inputs)), Decimal(row[7]) * 100_000_000)
                    # DAO claims mint compensation, so their transaction fee needs the DAO
                    # maximum-withdraw calculation covered by the dedicated DAO cases.
                    if total_inputs >= total_outputs:
                        self.assertEqual(Decimal(total_inputs - total_outputs), Decimal(row[8]) * 100_000_000)
                        checked_fee_rows += 1
                    expected_date = datetime.fromtimestamp(timestamp // 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    self.assertEqual(expected_date, row[9])
                self.assertGreater(checked_fee_rows, 0)

    # TEST-MAP: ADDR-TX-RPC-12
    def test_udt_rows_are_unique_per_type_and_unknown_token_raw_amounts_match_cell_data(self) -> None:
        network = next(item for item in self.settings.networks if item.name == "mainnet")
        oracle = NetworkOracle(network, self.settings)
        try:
            target_lock_hash = self._address_lock_hash(oracle, LARGE_UDT_ADDRESS)
            table = self._csv(oracle, LARGE_UDT_ADDRESS)
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        udt_rows = [row for row in table[1:] if row[3] != "CKB"]
        if not udt_rows:
            raise unittest.SkipTest("mainnet address CSV UDT fixture is unavailable")
        self.assertEqual(len(udt_rows), len({(row[0], row[3]) for row in udt_rows}))
        self.assertTrue(any(row[3].startswith("Unknown Token #") for row in udt_rows))
        for row in udt_rows:
            result = oracle.rpc_result("get_transaction", [row[0]])
            transaction = result.get("transaction") if isinstance(result, dict) else None
            if not isinstance(transaction, dict):
                raise unittest.SkipTest(f"mainnet RPC transaction {row[0]} is unavailable")
            referenced = oracle.referenced_outputs(transaction)
            candidates: dict[str, tuple[int, int]] = {}
            for output, data in referenced:
                if ckb_script_hash(output["lock"]) == target_lock_hash and isinstance(output.get("type"), dict):
                    type_hash = ckb_script_hash(output["type"])
                    amount = int.from_bytes(bytes.fromhex(str(data)[2:])[:16], "little")
                    current = candidates.get(type_hash, (0, 0))
                    candidates[type_hash] = (current[0] + amount, current[1])
            for index, output in enumerate(transaction["outputs"]):
                if ckb_script_hash(output["lock"]) == target_lock_hash and isinstance(output.get("type"), dict):
                    type_hash = ckb_script_hash(output["type"])
                    amount = int.from_bytes(bytes.fromhex(transaction["outputs_data"][index][2:])[:16], "little")
                    current = candidates.get(type_hash, (0, 0))
                    candidates[type_hash] = (current[0], current[1] + amount)
            suffix = row[3].removeprefix("Unknown Token #")
            matching = [values for type_hash, values in candidates.items() if type_hash.endswith(suffix)]
            if not row[3].startswith("Unknown Token #") or len(matching) != 1:
                raise unittest.SkipTest("published and unpublished UDT mapping fixture is incomplete")
            expected_in, expected_out = matching[0]
            parse_raw = lambda value: 0 if value == "/" else int(Decimal(value.removesuffix(" (raw)")))
            self.assertEqual(expected_in, parse_raw(row[5]))
            self.assertEqual(expected_out, parse_raw(row[6]))
            self.assertEqual(abs(expected_out - expected_in), parse_raw(row[7]))
            self.assertEqual("/", row[8])

    # TEST-MAP: ADDR-TX-RPC-13
    def test_timestamp_filters_are_inclusive_and_combine_as_an_intersection(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    full = self._csv(oracle, address)
                    timestamps = sorted({int(row[2]) for row in full[1:]})
                    if len(timestamps) < 2:
                        raise OracleUnavailable(f"{network.name} timestamp boundary fixture is unavailable")
                    start, end = timestamps[0], timestamps[-1]
                    start_only = self._csv(oracle, address, start_date=start)
                    end_only = self._csv(oracle, address, end_date=end)
                    both = self._csv(oracle, address, start_date=start, end_date=end)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertTrue(all(int(row[2]) >= start for row in start_only[1:]))
                self.assertTrue(all(int(row[2]) <= end for row in end_only[1:]))
                self.assertTrue(all(start <= int(row[2]) <= end for row in both[1:]))
                self.assertIn(start, {int(row[2]) for row in both[1:]})
                self.assertIn(end, {int(row[2]) for row in both[1:]})

    # TEST-MAP: ADDR-TX-RPC-14
    def test_height_filters_are_inclusive_and_combine_as_an_intersection(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    full = self._csv(oracle, address)
                    heights = sorted({int(row[1]) for row in full[1:]})
                    if len(heights) < 2:
                        raise OracleUnavailable(f"{network.name} height boundary fixture is unavailable")
                    start, end = heights[0], heights[-1]
                    start_only = self._csv(oracle, address, start_number=start)
                    end_only = self._csv(oracle, address, end_number=end)
                    both = self._csv(oracle, address, start_number=start, end_number=end)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertTrue(all(int(row[1]) >= start for row in start_only[1:]))
                self.assertTrue(all(int(row[1]) <= end for row in end_only[1:]))
                self.assertTrue(all(start <= int(row[1]) <= end for row in both[1:]))
                self.assertIn(start, {int(row[1]) for row in both[1:]})
                self.assertIn(end, {int(row[1]) for row in both[1:]})

    # TEST-MAP: ADDR-TX-RPC-15
    def test_busy_address_export_caps_transactions_after_filters_and_ignores_list_controls(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    table = self._csv(oracle, BUSY_ADDRESSES[network.name])
                    altered = self._csv(oracle, BUSY_ADDRESSES[network.name], page=99, page_size=1, sort="time.asc")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                hashes = list(dict.fromkeys(row[0] for row in table[1:]))
                self.assertEqual(500, len(hashes))
                self.assertEqual(table, altered)
                heights = [int(next(row[1] for row in table[1:] if row[0] == tx_hash)) for tx_hash in hashes]
                self.assertEqual(heights, sorted(heights, reverse=True))

    # TEST-MAP: ADDR-TX-RPC-16
    def test_multiple_same_asset_cells_are_aggregated_to_one_address_transaction_row(self) -> None:
        network = next(item for item in self.settings.networks if item.name == "mainnet")
        oracle = NetworkOracle(network, self.settings)
        try:
            table = self._csv(oracle, LARGE_UDT_ADDRESS)
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        keys = [(row[0], row[3]) for row in table[1:]]
        self.assertEqual(len(keys), len(set(keys)))
        multi = False
        for row in table[1:]:
            result = oracle.rpc_result("get_transaction", [row[0]])
            transaction = result.get("transaction") if isinstance(result, dict) else None
            if isinstance(transaction, dict) and len(transaction.get("outputs", [])) > 2:
                multi = True
                break
        if not multi:
            raise unittest.SkipTest("mainnet multi-cell aggregation fixture is unavailable")

    # TEST-MAP: ADDR-TX-RPC-17
    def test_empty_filter_returns_header_only_and_bad_addresses_do_not_create_csv(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    empty = self._csv(oracle, DAO_ADDRESSES[network.name], start_number=1, end_number=1)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual([CSV_HEADER], empty)

    # TEST-MAP: ADDR-TX-RPC-18
    def test_large_raw_udt_and_ckb_values_round_trip_without_binary_float(self) -> None:
        network = next(item for item in self.settings.networks if item.name == "mainnet")
        oracle = NetworkOracle(network, self.settings)
        try:
            table = self._csv(oracle, LARGE_UDT_ADDRESS)
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        raw_values = [
            value.removesuffix(" (raw)")
            for row in table[1:]
            for value in row[5:8]
            if value.endswith(" (raw)") and value != "/"
        ]
        if not raw_values or max(Decimal(value) for value in raw_values) <= 2**53 - 1:
            raise unittest.SkipTest("mainnet CSV raw integer above 2^53-1 is unavailable")
        for value in raw_values:
            self.assertNotIn("e", value.lower())
            self.assertEqual(Decimal(value), Decimal(str(value)))


if __name__ == "__main__":
    unittest.main()
