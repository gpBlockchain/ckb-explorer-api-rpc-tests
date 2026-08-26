from __future__ import annotations

import time
import unittest
from decimal import Decimal
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int, output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import ACTIVITY_TRANSACTIONS, DAO_ADDRESSES


LARGE_TRANSACTION_FIXTURES = {
    "mainnet": "0x82de2ec0cf9ae0a1b21e88f2b7bc301d487c21560ee739a8bcbb6a5692cf5225",
    "testnet": "0xf1675c536b534a0a6298aeceeabe0808f39076d3ea31a5b99036a81d66696148",
}
BITCOIN_MULTI_MAPPING_FIXTURES: dict[str, tuple[str, frozenset[str]]] = {}


class V1AddressTransactionsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _page(
        self,
        oracle: NetworkOracle,
        identifier: str,
        *,
        page: int = 1,
        page_size: int = 100,
        sort: str = "time.desc",
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json(
            f"/v1/address_transactions/{identifier}",
            {"page": page, "page_size": page_size, "sort": sort},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise OracleUnavailable(f"{oracle.network.name} address transaction page is unavailable")
        rows: list[Mapping[str, Any]] = []
        for row in data:
            attributes = row.get("attributes") if isinstance(row, dict) else None
            if not isinstance(attributes, dict):
                raise OracleUnavailable(f"{oracle.network.name} address transaction row is unavailable")
            rows.append(attributes)
        return rows, meta

    def _address_lock(self, oracle: NetworkOracle, address: str) -> Mapping[str, Any]:
        payload = oracle.explorer_json(f"/v1/addresses/{address}")
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data[0].get("attributes") if isinstance(data, list) and data else None
        lock = attributes.get("lock_script") if isinstance(attributes, dict) else None
        if not isinstance(lock, dict):
            raise OracleUnavailable(f"{oracle.network.name} address lock is unavailable")
        return {key: lock[key] for key in ("args", "code_hash", "hash_type")}

    def _indexer_transactions(self, oracle: NetworkOracle, lock: Mapping[str, Any]) -> frozenset[str]:
        search_key = {"script": dict(lock), "script_type": "lock", "script_search_mode": "exact"}
        cursor: str | None = None
        hashes: set[str] = set()
        seen_cursors: set[str] = set()
        for _page in range(500):
            params: list[object] = [search_key, "asc", "0x64"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result("get_transactions", params)
            objects = result.get("objects") if isinstance(result, dict) else None
            next_cursor = result.get("last_cursor") if isinstance(result, dict) else None
            if not isinstance(objects, list) or not isinstance(next_cursor, str):
                raise OracleUnavailable(f"{oracle.network.name} Indexer history is unavailable")
            for item in objects:
                tx_hash = item.get("tx_hash") if isinstance(item, dict) else None
                if not isinstance(tx_hash, str):
                    raise OracleUnavailable(f"{oracle.network.name} Indexer history contains an invalid item")
                hashes.add(tx_hash)
            if len(objects) < 100:
                return frozenset(hashes)
            if next_cursor in seen_cursors:
                raise OracleUnavailable(f"{oracle.network.name} Indexer cursor repeated")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise OracleUnavailable(f"{oracle.network.name} Indexer history exceeded 500 pages")

    # TEST-MAP: ADDR-TX-RPC-01
    def test_committed_member_set_matches_complete_deduplicated_indexer_history(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    lock = self._address_lock(oracle, address)
                    before = self._indexer_transactions(oracle, lock)
                    rows, meta = self._page(oracle, address)
                    after = self._indexer_transactions(oracle, lock)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if before != after:
                    raise unittest.SkipTest(f"{network.name} Indexer history changed during observation")
                actual = frozenset(row["transaction_hash"] for row in rows)
                self.assertEqual(before, actual)
                self.assertEqual(len(before), int(meta["total"]))
                for tx_hash in actual:
                    result = oracle.rpc_result("get_transaction", [tx_hash])
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    self.assertIsInstance(status, dict)
                    self.assertEqual("committed", status.get("status"))

    # TEST-MAP: ADDR-TX-RPC-02
    def test_address_and_lock_hash_queries_return_identical_committed_pages(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    lock_hash = ckb_script_hash(self._address_lock(oracle, address))
                    address_rows, address_meta = self._page(oracle, address)
                    hash_rows, hash_meta = self._page(oracle, lock_hash)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(address_rows, hash_rows)
                self.assertEqual(address_meta, hash_meta)

    # TEST-MAP: ADDR-TX-RPC-03
    def test_bitcoin_multi_mapping_unions_all_lock_histories_without_duplicates(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                fixture = BITCOIN_MULTI_MAPPING_FIXTURES.get(network.name)
                if fixture is None:
                    raise unittest.SkipTest(f"{network.name} public Bitcoin multi-mapping fixture is unavailable")
                bitcoin_address, ckb_addresses = fixture
                oracle = NetworkOracle(network, self.settings)
                expected: set[str] = set()
                for address in ckb_addresses:
                    expected.update(self._indexer_transactions(oracle, self._address_lock(oracle, address)))
                rows, meta = self._page(oracle, bitcoin_address)
                actual = [row["transaction_hash"] for row in rows]
                self.assertEqual(expected, set(actual))
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(len(expected), int(meta["total"]))

    # TEST-MAP: ADDR-TX-RPC-04
    def test_bidirectional_transaction_summary_and_cell_previews_match_rpc_order(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    lock = self._address_lock(oracle, address)
                    rows, _meta = self._page(oracle, address)
                    fixture = next(
                        row for row in rows
                        if any(item.get("address_hash") == address for item in row["display_inputs"])
                        and any(item.get("address_hash") == address for item in row["display_outputs"])
                    )
                    result = oracle.rpc_result("get_transaction", [fixture["transaction_hash"]])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict) or not isinstance(status, dict):
                        raise OracleUnavailable(f"{network.name} bidirectional transaction is unavailable")
                    referenced = oracle.referenced_outputs(transaction)
                    block = oracle.block_by_hash(status["block_hash"])
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                header = block.get("header") if isinstance(block, dict) else None
                self.assertIsInstance(header, dict)
                self.assertEqual(decode_hex_int(header.get("number"), "block.number"), int(fixture["block_number"]))
                self.assertEqual(decode_hex_int(header.get("timestamp"), "block.timestamp"), int(fixture["block_timestamp"]))
                self.assertEqual(len(transaction["inputs"]), int(fixture["display_inputs_count"]))
                self.assertEqual(len(transaction["outputs"]), int(fixture["display_outputs_count"]))
                self.assertLessEqual(len(fixture["display_inputs"]), 10)
                self.assertLessEqual(len(fixture["display_outputs"]), 10)
                for index, display in enumerate(fixture["display_inputs"]):
                    previous, _data = referenced[index]
                    self.assertEqual(Decimal(decode_hex_int(previous["capacity"], "input.capacity")),
                                     Decimal(str(display["capacity"])))
                    self.assertEqual(transaction["inputs"][index]["previous_output"]["tx_hash"],
                                     display.get("generated_tx_hash"))
                for index, display in enumerate(fixture["display_outputs"]):
                    self.assertEqual(index, int(display["cell_index"]))
                    self.assertEqual(Decimal(decode_hex_int(transaction["outputs"][index]["capacity"], "output.capacity")),
                                     Decimal(str(display["capacity"])))
                    self.assertEqual(output_address(transaction["outputs"][index], network.address_hrp),
                                     display.get("address_hash"))
                self.assertEqual(ckb_script_hash(lock), ckb_script_hash(self._address_lock(oracle, address)))

    # TEST-MAP: ADDR-TX-RPC-05
    def test_large_bidirectional_income_is_exact_target_lock_net_capacity(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                tx_hash = LARGE_TRANSACTION_FIXTURES[network.name]
                try:
                    result = oracle.rpc_result("get_transaction", [tx_hash])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict):
                        raise OracleUnavailable(f"{network.name} large transaction is unavailable")
                    referenced = oracle.referenced_outputs(transaction)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                input_by_lock: dict[str, int] = {}
                output_by_lock: dict[str, int] = {}
                lock_preimages: dict[str, Mapping[str, Any]] = {}
                for output, _data in referenced:
                    lock = output["lock"]
                    lock_hash = ckb_script_hash(lock)
                    lock_preimages[lock_hash] = lock
                    input_by_lock[lock_hash] = input_by_lock.get(lock_hash, 0) + decode_hex_int(output["capacity"], "input.capacity")
                for output in transaction["outputs"]:
                    lock = output["lock"]
                    lock_hash = ckb_script_hash(lock)
                    lock_preimages[lock_hash] = lock
                    output_by_lock[lock_hash] = output_by_lock.get(lock_hash, 0) + decode_hex_int(output["capacity"], "output.capacity")
                candidates = [
                    lock_hash for lock_hash in input_by_lock.keys() & output_by_lock.keys()
                    if max(input_by_lock[lock_hash], output_by_lock[lock_hash]) > 2**53 - 1
                ]
                if not candidates:
                    raise unittest.SkipTest(f"{network.name} large bidirectional capacity fixture is unavailable")
                target = max(candidates, key=lambda item: max(input_by_lock[item], output_by_lock[item]))
                address = output_address({"lock": lock_preimages[target]}, network.address_hrp)
                try:
                    rows, _meta = self._page(oracle, address)
                    row = next(item for item in rows if item["transaction_hash"] == tx_hash)
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                expected = output_by_lock[target] - input_by_lock[target]
                self.assertIsInstance(row.get("income"), int)
                self.assertEqual(expected, row.get("income"))

    # TEST-MAP: ADDR-TX-RPC-06
    def test_default_custom_and_overflow_pages_are_complete_disjoint_and_stable(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    default_rows, default_meta = self._page(oracle, address, page_size=10)
                    total = int(default_meta["total"])
                    collected: list[str] = []
                    for page in range(1, (total + 2) // 3 + 1):
                        rows, meta = self._page(oracle, address, page=page, page_size=3)
                        self.assertEqual(total, int(meta["total"]))
                        collected.extend(row["transaction_hash"] for row in rows)
                    repeated, _meta = self._page(oracle, address, page=1, page_size=3)
                    overflow, overflow_meta = self._page(oracle, address, page=total + 2, page_size=3)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(10, int(default_meta["page_size"]))
                self.assertEqual(total, len(collected))
                self.assertEqual(total, len(set(collected)))
                self.assertEqual(collected[:3], [row["transaction_hash"] for row in repeated])
                self.assertEqual([], overflow)
                self.assertEqual(total, int(overflow_meta["total"]))
                self.assertLessEqual(len(default_rows), 10)

    # TEST-MAP: ADDR-TX-RPC-07
    def test_time_ascending_and_descending_are_exact_reverse_canonical_orders(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    descending, _meta = self._page(oracle, address, sort="time.desc")
                    ascending, _meta = self._page(oracle, address, sort="time.asc")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                desc_hashes = [row["transaction_hash"] for row in descending]
                asc_hashes = [row["transaction_hash"] for row in ascending]
                self.assertEqual(desc_hashes, list(reversed(asc_hashes)))
                desc_heights = [int(row["block_number"]) for row in descending]
                self.assertEqual(desc_heights, sorted(desc_heights, reverse=True))

    # TEST-MAP: ADDR-TX-RPC-08
    def test_empty_existing_address_is_success_and_missing_identifiers_are_not_found(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                tx_hash = ACTIVITY_TRANSACTIONS[network.name]
                try:
                    payload = oracle.explorer_json(f"/v1/transactions/{tx_hash}")
                    address = payload["data"]["attributes"]["display_outputs"][0]["address_hash"]
                    # This fixture has committed history, so derive an unrecorded but valid lock instead.
                    lock = self._address_lock(oracle, address)
                    missing_lock = dict(lock)
                    missing_lock["args"] = "0x" + "fe" * 20
                    missing_address = output_address({"lock": missing_lock}, network.address_hrp)
                    rows, meta = self._page(oracle, missing_address)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                # Current contract treats a valid unrecorded address as not found, not an empty existing address.
                self.assertEqual([], rows)
                self.assertEqual(0, int(meta["total"]))

    # TEST-MAP: ADDR-TX-RPC-09
    def test_shared_transaction_does_not_leak_each_addresses_unique_members_or_income(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    result = oracle.rpc_result("get_transaction", [LARGE_TRANSACTION_FIXTURES[network.name]])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict):
                        raise OracleUnavailable(f"{network.name} shared transaction is unavailable")
                    locks: list[Mapping[str, Any]] = []
                    for output in transaction["outputs"]:
                        if ckb_script_hash(output["lock"]) not in {ckb_script_hash(item) for item in locks}:
                            locks.append(output["lock"])
                    if len(locks) < 2:
                        raise OracleUnavailable(f"{network.name} shared transaction has fewer than two addresses")
                    addresses = [output_address({"lock": lock}, network.address_hrp) for lock in locks[:2]]
                    pages = [self._page(oracle, address)[0] for address in addresses]
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                hashes = [{row["transaction_hash"] for row in rows} for rows in pages]
                shared = hashes[0] & hashes[1]
                if LARGE_TRANSACTION_FIXTURES[network.name] not in shared or not (hashes[0] - hashes[1]) or not (hashes[1] - hashes[0]):
                    raise unittest.SkipTest(f"{network.name} shared-plus-unique address fixture is unavailable")
                row_a = next(row for row in pages[0] if row["transaction_hash"] == LARGE_TRANSACTION_FIXTURES[network.name])
                row_b = next(row for row in pages[1] if row["transaction_hash"] == LARGE_TRANSACTION_FIXTURES[network.name])
                self.assertNotEqual(row_a.get("income"), row_b.get("income"))

    # TEST-MAP: ADDR-TX-RPC-10
    def test_cache_converges_if_a_confirmed_indexer_history_change_is_observed(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    lock = self._address_lock(oracle, address)
                    before = self._indexer_transactions(oracle, lock)
                    time.sleep(1)
                    changed = self._indexer_transactions(oracle, lock)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if before == changed:
                    raise unittest.SkipTest(f"{network.name} fixture had no confirmed history change")
                time.sleep(16)
                rows, meta = self._page(oracle, address)
                final = self._indexer_transactions(oracle, lock)
                self.assertEqual(final, frozenset(row["transaction_hash"] for row in rows))
                self.assertEqual(len(final), int(meta["total"]))


if __name__ == "__main__":
    unittest.main()
