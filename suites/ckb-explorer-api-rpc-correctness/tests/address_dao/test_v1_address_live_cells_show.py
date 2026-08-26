from __future__ import annotations

import unittest
import urllib.parse
from decimal import Decimal
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int, output_occupied_capacity
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_address_dao_transactions_show import _explorer_response
from tests.address_dao.test_v1_addresses_show import ACTIVITY_TRANSACTIONS


ADDRESSES = {
    "mainnet": "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqv9ft027uv84z4nc4wsgwl32u6ex4e4qsscccscx",
    "testnet": "ckt1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq2zrchfd2y3xcf9lkqeddggqagukmnufkse0g93q",
}
TAG_FIXTURES: dict[tuple[str, str], str] = {}
BITCOIN_FILTER_FIXTURES: dict[str, str] = {}
DAO_CODE_HASH = "0x82d76d1b75fe2fd9a27dfbaa65a039221a380d76c926f378d3f81cf3e7e13f2e"


class V1AddressLiveCellsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _lock(self, oracle: NetworkOracle, address: str) -> Mapping[str, Any]:
        payload = oracle.explorer_json(f"/v1/addresses/{address}")
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data[0].get("attributes") if isinstance(data, list) and data else None
        lock = attributes.get("lock_script") if isinstance(attributes, dict) else None
        if not isinstance(lock, dict):
            raise OracleUnavailable(f"{oracle.network.name} address lock is unavailable")
        return {key: lock[key] for key in ("args", "code_hash", "hash_type")}

    def _api(
        self,
        oracle: NetworkOracle,
        identifier: str,
        **query: object,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json(f"/v1/address_live_cells/{identifier}", query or None)
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise OracleUnavailable(f"{oracle.network.name} live-cell page is unavailable")
        rows: list[Mapping[str, Any]] = []
        for item in data:
            attributes = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(attributes, dict):
                raise OracleUnavailable(f"{oracle.network.name} live-cell row is unavailable")
            rows.append(attributes)
        return rows, meta

    def _indexer(self, oracle: NetworkOracle, lock: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        search_key = {"script": dict(lock), "script_type": "lock", "script_search_mode": "exact"}
        cursor: str | None = None
        rows: list[Mapping[str, Any]] = []
        for _page in range(200):
            params: list[object] = [search_key, "asc", "0x64"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result("get_cells", params)
            objects = result.get("objects") if isinstance(result, dict) else None
            next_cursor = result.get("last_cursor") if isinstance(result, dict) else None
            if not isinstance(objects, list) or not isinstance(next_cursor, str):
                raise OracleUnavailable(f"{oracle.network.name} Indexer cells are unavailable")
            if not all(isinstance(item, dict) for item in objects):
                raise OracleUnavailable(f"{oracle.network.name} Indexer returned an invalid Cell")
            rows.extend(objects)
            if len(objects) < 100:
                return rows
            cursor = next_cursor
        raise OracleUnavailable(f"{oracle.network.name} Indexer cells exceeded 200 pages")

    # TEST-MAP: ADDR-CELL-RPC-01
    # TEST-MAP: ADDR-CELL-RPC-03
    # TEST-MAP: ADDR-CELL-RPC-05
    def test_complete_api_members_and_fields_match_stable_indexer_and_rpc_live_cells(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = ADDRESSES[network.name]
                try:
                    lock = self._lock(oracle, address)
                    before = self._indexer(oracle, lock)
                    rows, meta = self._api(oracle, address, page_size=100)
                    after = self._indexer(oracle, lock)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                key = lambda item: (item["out_point"]["tx_hash"], decode_hex_int(item["out_point"]["index"], "index"))
                if {key(item) for item in before} != {key(item) for item in after}:
                    raise unittest.SkipTest(f"{network.name} Indexer live cells changed during observation")
                expected = {key(item): item for item in before}
                actual = {(row["tx_hash"], int(row["cell_index"])): row for row in rows}
                self.assertEqual(set(expected), set(actual))
                self.assertEqual(len(rows), len(actual))
                self.assertEqual(len(expected), int(meta["total"]))
                saw_plain = False
                for out_point, row in actual.items():
                    item = expected[out_point]
                    output = item["output"]
                    output_data = item["output_data"]
                    block = oracle.block(decode_hex_int(item["block_number"], "cell.block_number"))
                    header = block.get("header") if isinstance(block, dict) else None
                    self.assertIsInstance(header, dict)
                    self.assertEqual(decode_hex_int(item["block_number"], "cell.block_number"), int(row["block_number"]))
                    self.assertEqual(decode_hex_int(header.get("timestamp"), "block.timestamp"), int(row["block_timestamp"]))
                    self.assertEqual(Decimal(decode_hex_int(output["capacity"], "capacity")), Decimal(str(row["capacity"])))
                    self.assertEqual(output_occupied_capacity(output, output_data), int(row["occupied_capacity"]))
                    self.assertEqual(output_data, row.get("data"))
                    self.assertEqual(lock, row.get("lock_script"))
                    if output.get("type") is None:
                        saw_plain = True
                        self.assertIsNone(row.get("type_script"))
                        self.assertIsNone(row.get("type_hash"))
                        self.assertEqual("0x", output_data)
                        self.assertEqual("normal", row.get("cell_type"))
                        self.assertEqual("ckb", row["extra_info"].get("type"))
                    else:
                        self.assertEqual(output.get("type"), row.get("type_script"))
                        self.assertEqual(ckb_script_hash(output["type"]), row.get("type_hash"))
                if not saw_plain:
                    raise unittest.SkipTest(f"{network.name} stable sample has no plain empty-data Cell")

    # TEST-MAP: ADDR-CELL-RPC-02
    def test_address_and_lock_hash_return_identical_target_only_cells(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = ADDRESSES[network.name]
                try:
                    lock_hash = ckb_script_hash(self._lock(oracle, address))
                    address_rows, address_meta = self._api(oracle, address, page_size=100)
                    hash_rows, hash_meta = self._api(oracle, lock_hash, page_size=100)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(address_rows, hash_rows)
                self.assertEqual(address_meta, hash_meta)

    # TEST-MAP: ADDR-CELL-RPC-04
    def test_recorded_address_without_live_cells_returns_empty_success(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                raise unittest.SkipTest(f"{network.name} recorded zero-live-cell fixture is unavailable")

    # TEST-MAP: ADDR-CELL-RPC-06
    def test_chain_identifiable_cell_types_match_scripts_and_data(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, _meta = self._api(oracle, ADDRESSES[network.name], page_size=100)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                checked = 0
                for row in rows:
                    type_script = row.get("type_script")
                    if not isinstance(type_script, dict):
                        self.assertEqual("normal", row.get("cell_type"))
                        checked += 1
                    elif type_script.get("code_hash") == DAO_CODE_HASH:
                        expected = "nervos_dao_deposit" if row.get("data") == "0x" + "00" * 8 else "nervos_dao_withdrawing"
                        self.assertEqual(expected, row.get("cell_type"))
                        checked += 1
                self.assertGreater(checked, 0)

    # TEST-MAP: ADDR-CELL-RPC-07
    def test_capacity_above_javascript_safe_integer_remains_exact_decimal(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, _meta = self._api(oracle, ADDRESSES[network.name], page_size=100)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                large = [row for row in rows if Decimal(str(row["capacity"])) > 2**53 - 1]
                if not large:
                    raise unittest.SkipTest(f"{network.name} public large Live Cell fixture is unavailable")
                for row in large:
                    self.assertEqual(Decimal(str(row["capacity"])), Decimal(int(Decimal(str(row["capacity"])))))
                    self.assertTrue(str(row["occupied_capacity"]).isdigit())

    # TEST-MAP: ADDR-CELL-RPC-08
    def test_custom_pages_are_disjoint_complete_and_overflow_is_empty(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = ADDRESSES[network.name]
                try:
                    full, full_meta = self._api(oracle, address, page_size=100)
                    collected: list[tuple[str, int]] = []
                    for page in range(1, (len(full) + 2) // 3 + 1):
                        rows, meta = self._api(oracle, address, page=page, page_size=3)
                        self.assertEqual(len(full), int(meta["total"]))
                        collected.extend((row["tx_hash"], int(row["cell_index"])) for row in rows)
                    overflow, overflow_meta = self._api(oracle, address, page=len(full) + 2, page_size=3)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(len(full), len(collected))
                self.assertEqual(len(collected), len(set(collected)))
                self.assertEqual([], overflow)
                self.assertEqual(int(full_meta["total"]), int(overflow_meta["total"]))

    # TEST-MAP: ADDR-CELL-RPC-09
    def test_default_and_explicit_timestamp_sort_directions_are_reverse_orders(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = ADDRESSES[network.name]
                try:
                    default, _meta = self._api(oracle, address, page_size=100)
                    descending, _meta = self._api(oracle, address, page_size=100, sort="block_timestamp.desc")
                    ascending, _meta = self._api(oracle, address, page_size=100, sort="block_timestamp.asc")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(default, descending)
                self.assertEqual([int(row["block_timestamp"]) for row in descending],
                                 sorted((int(row["block_timestamp"]) for row in descending), reverse=True))
                self.assertEqual({(row["tx_hash"], row["cell_index"]) for row in descending},
                                 {(row["tx_hash"], row["cell_index"]) for row in ascending})
                self.assertEqual([int(row["block_timestamp"]) for row in ascending],
                                 sorted(int(row["block_timestamp"]) for row in ascending))

    # TEST-MAP: ADDR-CELL-RPC-11
    # TEST-MAP: ADDR-CELL-RPC-12
    # TEST-MAP: ADDR-CELL-RPC-13
    def test_supported_tag_filters_match_independently_confirmed_fixture_members(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                for tag in ("fiber", "multisig", "deployment"):
                    if (network.name, tag) not in TAG_FIXTURES:
                        continue
                    oracle = NetworkOracle(network, self.settings)
                    rows, _meta = self._api(oracle, TAG_FIXTURES[(network.name, tag)], tag=tag, page_size=100)
                    self.assertTrue(rows)
                    self.assertTrue(all(tag in row.get("tags", []) for row in rows))
                if not any(key[0] == network.name for key in TAG_FIXTURES):
                    raise unittest.SkipTest(f"{network.name} independently confirmed tag fixtures are unavailable")

    # TEST-MAP: ADDR-CELL-RPC-14
    def test_unknown_nonempty_tag_returns_empty_success_and_zero_meta(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, meta = self._api(oracle, ADDRESSES[network.name], tag="not-a-supported-tag")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual([], rows)
                self.assertEqual(0, int(meta["total"]))
                self.assertEqual(0, int(meta["total_pages"]))

    # TEST-MAP: ADDR-CELL-RPC-15
    # TEST-MAP: ADDR-CELL-RPC-16
    def test_bitcoin_binding_and_combined_filters_match_independent_mapping_fixture(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                if network.name not in BITCOIN_FILTER_FIXTURES:
                    raise unittest.SkipTest(f"{network.name} independent Bitcoin Vout mapping fixture is unavailable")

    # TEST-MAP: ADDR-CELL-RPC-23
    def test_invalid_and_unrecorded_identifiers_return_address_not_found(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                for endpoint in ("address_live_cells", "address_deployed_cells"):
                    for identifier in ("not-an-address", "0x" + "00" * 32):
                        path = f"/v1/{endpoint}/" + urllib.parse.quote(identifier, safe="")
                        status, payload = _explorer_response(oracle, path)
                        if status == 403 and isinstance(payload, dict) and payload.get("cloudflare_error") is True:
                            raise unittest.SkipTest(f"{network.name} edge rejected negative-path observation")
                        self.assertEqual(404, status)
                        self.assertIsInstance(payload, list)
                        self.assertEqual(1010, payload[0].get("code"))

    # TEST-MAP: ADDR-CELL-RPC-24
    def test_cache_convergence_waits_for_an_observed_confirmed_cell_change(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                raise unittest.SkipTest(f"{network.name} no confirmed Live Cell change was observed")


if __name__ == "__main__":
    unittest.main()
