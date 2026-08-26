from __future__ import annotations

import csv
import io
import unittest
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.http import HttpClientError
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import DAO_ADDRESSES
from tests.address_dao.test_v1_dao_contract_transactions_show import DEPOSIT_TRANSACTIONS


CSV_HEADER = ["Address", "Capacity"]
DAO_CODE_HASH = "0x82d76d1b75fe2fd9a27dfbaa65a039221a380d76c926f378d3f81cf3e7e13f2e"


class V1DaoDepositorsDownloadCsvRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.cache: dict[tuple[str, tuple[tuple[str, object], ...]], list[list[str]]] = {}

    def _csv(self, oracle: NetworkOracle, **query: object) -> list[list[str]]:
        key = (oracle.network.name, tuple(sorted(query.items())))
        if key not in self.cache:
            url = oracle.network.explorer_api_url + "/v1/dao_depositors/download_csv"
            if query:
                url += "?" + urlencode(query)
            try:
                raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
            except HttpClientError as error:
                raise OracleUnavailable(f"{oracle.network.name} DAO depositor CSV unavailable: {error}") from error
            self.cache[key] = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        return self.cache[key]

    def _address_lock(self, oracle: NetworkOracle, address: str) -> Mapping[str, Any]:
        payload = oracle.explorer_json(f"/v1/addresses/{address}")
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data[0].get("attributes") if isinstance(data, list) and data else None
        lock = attributes.get("lock_script") if isinstance(attributes, dict) else None
        if not isinstance(lock, dict):
            raise OracleUnavailable(f"{oracle.network.name} DAO address lock is unavailable")
        return {key: lock[key] for key in ("args", "code_hash", "hash_type")}

    def _live_principal(self, oracle: NetworkOracle, address: str) -> int:
        search_key = {
            "script": dict(self._address_lock(oracle, address)),
            "script_type": "lock",
            "script_search_mode": "exact",
        }
        cursor: str | None = None
        total = 0
        for _page in range(100):
            params: list[object] = [search_key, "asc", "0x64"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result("get_cells", params)
            objects = result.get("objects") if isinstance(result, dict) else None
            next_cursor = result.get("last_cursor") if isinstance(result, dict) else None
            if not isinstance(objects, list) or not isinstance(next_cursor, str):
                raise OracleUnavailable(f"{oracle.network.name} Indexer cells are unavailable")
            for item in objects:
                output = item.get("output") if isinstance(item, dict) else None
                type_script = output.get("type") if isinstance(output, dict) else None
                if not isinstance(type_script, dict) or type_script.get("code_hash") != DAO_CODE_HASH:
                    continue
                data = item.get("output_data")
                if data == "0x" + "00" * 8:
                    total += decode_hex_int(output.get("capacity"), "deposit.capacity")
                    continue
                out_point = item.get("out_point")
                tx_hash = out_point.get("tx_hash") if isinstance(out_point, dict) else None
                index = decode_hex_int(out_point.get("index"), "withdrawing.index") if isinstance(out_point, dict) else -1
                if not isinstance(tx_hash, str):
                    raise OracleUnavailable(f"{oracle.network.name} withdrawing out-point is unavailable")
                result_tx = oracle.rpc_result("get_transaction", [tx_hash])
                transaction = result_tx.get("transaction") if isinstance(result_tx, dict) else None
                if not isinstance(transaction, dict):
                    raise OracleUnavailable(f"{oracle.network.name} withdrawing transaction is unavailable")
                referenced = oracle.referenced_outputs(transaction)
                if index >= len(referenced):
                    raise OracleUnavailable(f"{oracle.network.name} withdrawing input correspondence is unavailable")
                total += decode_hex_int(referenced[index][0].get("capacity"), "deposit principal")
            if len(objects) < 100:
                return total
            cursor = next_cursor
        raise OracleUnavailable(f"{oracle.network.name} address cells exceeded 100 pages")

    def _live_deposit_anchor(self, oracle: NetworkOracle, address: str) -> tuple[int, int]:
        search_key = {
            "script": dict(self._address_lock(oracle, address)),
            "script_type": "lock",
            "script_search_mode": "exact",
        }
        result = oracle.rpc_result("get_cells", [search_key, "asc", "0x64"])
        objects = result.get("objects") if isinstance(result, dict) else None
        if not isinstance(objects, list):
            raise OracleUnavailable(f"{oracle.network.name} live deposit anchor is unavailable")
        for item in objects:
            output = item.get("output") if isinstance(item, dict) else None
            type_script = output.get("type") if isinstance(output, dict) else None
            if (
                isinstance(type_script, dict)
                and type_script.get("code_hash") == DAO_CODE_HASH
                and item.get("output_data") == "0x" + "00" * 8
            ):
                height = decode_hex_int(item.get("block_number"), "deposit.block_number")
                block = oracle.block(height)
                header = block.get("header") if isinstance(block, dict) else None
                if not isinstance(header, dict):
                    raise OracleUnavailable(f"{oracle.network.name} live deposit block is unavailable")
                return height, decode_hex_int(header.get("timestamp"), "deposit.timestamp")
        raise OracleUnavailable(f"{oracle.network.name} address has no live deposit anchor")

    # TEST-MAP: DAO-STATE-RPC-12
    def test_header_and_selected_address_capacity_match_live_deposit_and_withdrawing_principal(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    expected = self._live_principal(oracle, address)
                    table = self._csv(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(CSV_HEADER, table[0])
                self.assertEqual(len(table) - 1, len({row[0] for row in table[1:]}))
                row = next((item for item in table[1:] if item[0] == address), None)
                self.assertIsNotNone(row)
                self.assertEqual(Decimal(expected), Decimal(row[1]) * 100_000_000)

    # TEST-MAP: DAO-STATE-RPC-13
    def test_timestamp_boundaries_are_inclusive_for_known_live_deposit_event(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    _height, timestamp = self._live_deposit_anchor(oracle, DAO_ADDRESSES[network.name])
                    table = self._csv(oracle, start_date=timestamp, end_date=timestamp)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(CSV_HEADER, table[0])
                self.assertTrue(table[1:])
                self.assertIn(DAO_ADDRESSES[network.name], {row[0] for row in table[1:]})

    # TEST-MAP: DAO-STATE-RPC-14
    def test_height_boundaries_are_inclusive_and_override_conflicting_dates(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    height, _timestamp = self._live_deposit_anchor(oracle, DAO_ADDRESSES[network.name])
                    table = self._csv(
                        oracle,
                        start_number=height,
                        end_number=height,
                        start_date=2**63,
                        end_date=0,
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(CSV_HEADER, table[0])
                self.assertIn(DAO_ADDRESSES[network.name], {row[0] for row in table[1:]})

    # TEST-MAP: DAO-STATE-RPC-15
    def test_empty_genesis_height_window_returns_only_the_fixed_header(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    table = self._csv(oracle, start_number=1, end_number=1)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual([CSV_HEADER], table)


if __name__ == "__main__":
    unittest.main()
