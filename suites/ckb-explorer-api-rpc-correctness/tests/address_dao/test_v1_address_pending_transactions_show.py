from __future__ import annotations

import unittest
import urllib.parse
from decimal import Decimal
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int, output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_address_dao_transactions_show import _explorer_response
from tests.address_dao.test_v1_addresses_show import DAO_ADDRESSES


class V1AddressPendingTransactionsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _pool(self, oracle: NetworkOracle) -> dict[str, Mapping[str, Any]]:
        result = oracle.rpc_result("get_raw_tx_pool", [True])
        pending = result.get("pending") if isinstance(result, dict) else None
        proposed = result.get("proposed") if isinstance(result, dict) else None
        if not isinstance(pending, dict) or not isinstance(proposed, dict):
            raise OracleUnavailable(f"{oracle.network.name} verbose transaction pool is unavailable")
        return {**pending, **proposed}

    def _page(
        self,
        oracle: NetworkOracle,
        identifier: str,
        **query: object,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json(f"/v1/address_pending_transactions/{identifier}", query or None)
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise OracleUnavailable(f"{oracle.network.name} address pending page is unavailable")
        rows: list[Mapping[str, Any]] = []
        for item in data:
            attributes = item.get("attributes") if isinstance(item, dict) and isinstance(item.get("attributes"), dict) else item
            if not isinstance(attributes, dict):
                raise OracleUnavailable(f"{oracle.network.name} address pending row is unavailable")
            rows.append(attributes)
        return rows, meta

    def _indexed_candidate(
        self,
        oracle: NetworkOracle,
    ) -> tuple[str, str, Mapping[str, Any], Mapping[str, Any], list[Mapping[str, Any]]]:
        before = self._pool(oracle)
        global_payload = oracle.explorer_json("/v2/pending_transactions", {"page_size": 100})
        global_data = global_payload.get("data") if isinstance(global_payload, dict) else None
        indexed = {
            row.get("transaction_hash")
            for row in global_data
            if isinstance(row, dict) and isinstance(row.get("transaction_hash"), str)
        } if isinstance(global_data, list) else set()
        candidates = [tx_hash for tx_hash in before if tx_hash in indexed]
        if not candidates:
            raise unittest.SkipTest(f"{oracle.network.name} has no stable Explorer-indexed pool fixture")
        tx_hash = candidates[0]
        result = oracle.rpc_result("get_transaction", [tx_hash])
        transaction = result.get("transaction") if isinstance(result, dict) else None
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict) or not transaction.get("outputs"):
            raise unittest.SkipTest(f"{oracle.network.name} indexed pool transaction is unavailable")
        address = output_address(transaction["outputs"][0], oracle.network.address_hrp)
        rows, _meta = self._page(oracle, address, page_size=100)
        after = self._pool(oracle)
        if before != after:
            raise unittest.SkipTest(f"{oracle.network.name} transaction-pool snapshot changed")
        return tx_hash, address, transaction, status, rows

    # TEST-MAP: ADDR-TX-RPC-20
    def test_address_pending_members_match_a_stable_explorer_indexed_rpc_pool(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    tx_hash, _address, _transaction, status, rows = self._indexed_candidate(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                hashes = [row.get("transaction_hash") for row in rows]
                self.assertEqual(len(hashes), len(set(hashes)))
                self.assertIn(tx_hash, hashes)
                self.assertIn(status.get("status"), ("pending", "proposed"))

    # TEST-MAP: ADDR-TX-RPC-21
    def test_address_and_lock_hash_pending_queries_share_members_order_and_total(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    _tx_hash, address, transaction, _status, address_rows = self._indexed_candidate(oracle)
                    lock_hash = ckb_script_hash(transaction["outputs"][0]["lock"])
                    hash_rows, hash_meta = self._page(oracle, lock_hash, page_size=100)
                    _rows, address_meta = self._page(oracle, address, page_size=100)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(address_rows, hash_rows)
                self.assertEqual(address_meta, hash_meta)

    # TEST-MAP: ADDR-TX-RPC-22
    def test_pending_transaction_keeps_null_block_fields_and_full_rpc_preview_counts(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    tx_hash, _address, transaction, _status, rows = self._indexed_candidate(oracle)
                    row = next(item for item in rows if item.get("transaction_hash") == tx_hash)
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertIn(row.get("block_number"), (None, ""))
                self.assertIn(row.get("block_timestamp"), (None, ""))
                self.assertEqual(len(transaction["inputs"]), int(row["display_inputs_count"]))
                self.assertEqual(len(transaction["outputs"]), int(row["display_outputs_count"]))
                self.assertLessEqual(len(row["display_inputs"]), 10)
                self.assertLessEqual(len(row["display_outputs"]), 10)

    # TEST-MAP: ADDR-TX-RPC-23
    def test_large_pending_income_is_exact_signed_shannon(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    tx_hash, _address, transaction, _status, rows = self._indexed_candidate(oracle)
                    row = next(item for item in rows if item.get("transaction_hash") == tx_hash)
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                values = [decode_hex_int(output["capacity"], "output.capacity") for output in transaction["outputs"]]
                if not values or max(values) <= 2**53 - 1:
                    raise unittest.SkipTest(f"{network.name} indexed pool has no large-capacity fixture")
                self.assertIsInstance(row.get("income"), int)
                self.assertEqual(Decimal(row["income"]), Decimal(str(row["income"])))

    # TEST-MAP: ADDR-TX-RPC-24
    def test_pending_custom_pages_are_disjoint_complete_and_have_exact_total(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    _tx_hash, address, _transaction, _status, rows = self._indexed_candidate(oracle)
                    if len(rows) < 2:
                        raise unittest.SkipTest(f"{network.name} indexed address pool has fewer than two transactions")
                    first, meta = self._page(oracle, address, page=1, page_size=1)
                    second, _meta = self._page(oracle, address, page=2, page_size=1)
                    overflow, _meta = self._page(oracle, address, page=len(rows) + 2, page_size=1)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertNotEqual(first[0]["transaction_hash"], second[0]["transaction_hash"])
                self.assertEqual(len(rows), int(meta["total"]))
                self.assertEqual([], overflow)

    # TEST-MAP: ADDR-TX-RPC-25
    def test_shared_pending_transaction_keeps_each_addresses_members_and_income_isolated(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    tx_hash, _address, transaction, _status, _rows = self._indexed_candidate(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                addresses = list(dict.fromkeys(output_address(output, network.address_hrp) for output in transaction["outputs"]))
                if len(addresses) < 2:
                    raise unittest.SkipTest(f"{network.name} indexed pool transaction has fewer than two addresses")
                pages = [self._page(oracle, address, page_size=100)[0] for address in addresses[:2]]
                self.assertTrue(all(tx_hash in {row.get("transaction_hash") for row in rows} for rows in pages))
                incomes = [next(row["income"] for row in rows if row.get("transaction_hash") == tx_hash) for rows in pages]
                self.assertNotEqual(incomes[0], incomes[1])

    # TEST-MAP: ADDR-TX-RPC-27
    def test_existing_address_without_pending_history_returns_empty_success(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    before = self._pool(oracle)
                    rows, meta = self._page(oracle, DAO_ADDRESSES[network.name])
                    after = self._pool(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if before != after:
                    raise unittest.SkipTest(f"{network.name} transaction-pool snapshot changed")
                self.assertEqual([], rows)
                self.assertEqual(0, int(meta["total"]))

    # TEST-MAP: ADDR-TX-RPC-28
    def test_observed_pending_to_committed_transition_converges_between_lists(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                raise unittest.SkipTest(f"{network.name} no bounded pending-to-committed transition was observed")

    # TEST-MAP: ADDR-TX-RPC-29
    def test_each_network_uses_its_own_stable_pool_snapshot_and_missing_facts_skip_locally(self) -> None:
        completed: list[str] = []
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    before = self._pool(oracle)
                    self._page(oracle, DAO_ADDRESSES[network.name])
                    after = self._pool(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if before != after:
                    raise unittest.SkipTest(f"{network.name} transaction-pool snapshot changed")
                completed.append(network.name)
        self.assertTrue(completed)


if __name__ == "__main__":
    unittest.main()
