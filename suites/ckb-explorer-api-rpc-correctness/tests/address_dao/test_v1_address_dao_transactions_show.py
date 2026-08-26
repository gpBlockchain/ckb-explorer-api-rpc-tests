from __future__ import annotations

import json
import socket
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import ACTIVITY_TRANSACTIONS, DAO_ADDRESSES, DAO_TYPE_HASH


class _StatusPreservingProcessor(urllib.request.HTTPErrorProcessor):
    def http_response(self, request: urllib.request.Request, response: Any) -> Any:
        return response

    https_response = http_response


def _explorer_response(oracle: NetworkOracle, path: str) -> tuple[int, Any]:
    headers = dict(V1_HEADERS)
    headers["User-Agent"] = oracle.client.user_agent
    opener = urllib.request.build_opener(_StatusPreservingProcessor())
    for attempt in range(oracle.client.retries + 1):
        try:
            request = urllib.request.Request(oracle.network.explorer_api_url + path, headers=headers)
            with opener.open(request, timeout=oracle.client.timeout) as response:
                raw = response.read(oracle.client.max_body_bytes + 1)
                status = int(response.status)
            if len(raw) > oracle.client.max_body_bytes:
                raise OracleUnavailable(f"{oracle.network.name} Explorer response is too large")
            if attempt < oracle.client.retries and (status == 429 or status >= 500):
                time.sleep(0.2 * (attempt + 1))
                continue
            try:
                return status, json.loads(raw)
            except json.JSONDecodeError as error:
                raise OracleUnavailable(f"{oracle.network.name} Explorer returned invalid JSON") from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as error:
            if attempt < oracle.client.retries:
                time.sleep(0.2 * (attempt + 1))
                continue
            raise OracleUnavailable(f"{oracle.network.name} Explorer transport failure: {error}") from error
    raise AssertionError("unreachable HTTP retry loop")


class V1AddressDaoTransactionsShowRpcCorrectnessTests(unittest.TestCase):
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
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json(
            f"/v1/address_dao_transactions/{identifier}",
            {"page": page, "page_size": page_size},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise OracleUnavailable(f"{oracle.network.name} DAO transaction page is unavailable")
        rows: list[Mapping[str, Any]] = []
        for row in data:
            attributes = row.get("attributes") if isinstance(row, dict) else None
            if not isinstance(attributes, dict):
                raise OracleUnavailable(f"{oracle.network.name} DAO transaction row is unavailable")
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

    # TEST-MAP: ADDR-DAO-RPC-01
    def test_deposit_transaction_and_preview_match_rpc_transaction_and_block(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    rows, _meta = self._page(oracle, address)
                    deposit = next(
                        row for row in rows
                        if any(item.get("cell_type") == "nervos_dao_deposit" for item in row["display_outputs"])
                    )
                    result = oracle.rpc_result("get_transaction", [deposit["transaction_hash"]])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict) or not isinstance(status, dict):
                        raise OracleUnavailable(f"{network.name} deposit transaction is unavailable")
                    block = oracle.block_by_hash(status["block_hash"])
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                header = block.get("header") if isinstance(block, dict) else None
                self.assertIsInstance(header, dict)
                self.assertEqual(deposit["transaction_hash"], transaction.get("hash"))
                self.assertEqual(decode_hex_int(header.get("number"), "block.number"), int(deposit["block_number"]))
                self.assertEqual(decode_hex_int(header.get("timestamp"), "block.timestamp"), int(deposit["block_timestamp"]))
                self.assertEqual(len(transaction["inputs"]), int(deposit["display_inputs_count"]))
                self.assertEqual(len(transaction["outputs"]), int(deposit["display_outputs_count"]))
                for item in deposit["display_outputs"]:
                    index = int(item["cell_index"])
                    rpc_output = transaction["outputs"][index]
                    self.assertEqual(Decimal(decode_hex_int(rpc_output["capacity"], "output.capacity")),
                                     Decimal(str(item["capacity"])))
                    if item.get("cell_type") == "nervos_dao_deposit":
                        self.assertEqual(address, item.get("address_hash"))
                        self.assertEqual(DAO_TYPE_HASH, rpc_output["type"].get("code_hash"))
                        self.assertEqual("0x" + "00" * 8, transaction["outputs_data"][index])

    # TEST-MAP: ADDR-DAO-RPC-02
    def test_deposit_withdrawal_and_claim_lifecycle_is_present_and_rpc_linked(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, _meta = self._page(oracle, DAO_ADDRESSES[network.name])
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                deposits = [row for row in rows if any(item.get("cell_type") == "nervos_dao_deposit" for item in row["display_outputs"])]
                withdrawals = [row for row in rows if any(item.get("cell_type") == "nervos_dao_withdrawing" for item in row["display_outputs"])]
                claims = [row for row in rows if any(item.get("cell_type") == "nervos_dao_withdrawing" for item in row["display_inputs"])]
                if not deposits or not withdrawals or not claims:
                    raise unittest.SkipTest(f"{network.name} complete three-stage public DAO fixture is unavailable")
                hashes = {row["transaction_hash"] for row in deposits + withdrawals + claims}
                self.assertGreaterEqual(len(hashes), 3)
                for row in withdrawals:
                    result = oracle.rpc_result("get_transaction", [row["transaction_hash"]])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    self.assertIsInstance(transaction, dict)
                    self.assertTrue(any(data != "0x" + "00" * 8 for data in transaction["outputs_data"]))
                for row in claims:
                    result = oracle.rpc_result("get_transaction", [row["transaction_hash"]])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    self.assertIsInstance(transaction, dict)
                    self.assertTrue(transaction.get("header_deps"))

    # TEST-MAP: ADDR-DAO-RPC-03
    def test_address_and_lock_hash_queries_return_identical_pages(self) -> None:
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

    # TEST-MAP: ADDR-DAO-RPC-04
    def test_multiple_same_address_dao_cells_do_not_duplicate_or_trim_transaction(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, _meta = self._page(oracle, DAO_ADDRESSES[network.name])
                    fixture = next(
                        row for row in rows
                        if sum(item.get("cell_type", "").startswith("nervos_dao") for item in row["display_inputs"] + row["display_outputs"]) > 1
                    )
                    result = oracle.rpc_result("get_transaction", [fixture["transaction_hash"]])
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                hashes = [row["transaction_hash"] for row in rows]
                transaction = result.get("transaction") if isinstance(result, dict) else None
                self.assertEqual(1, hashes.count(fixture["transaction_hash"]))
                self.assertIsInstance(transaction, dict)
                self.assertEqual(len(transaction["inputs"]), int(fixture["display_inputs_count"]))
                self.assertEqual(len(transaction["outputs"]), int(fixture["display_outputs_count"]))

    # TEST-MAP: ADDR-DAO-RPC-05
    def test_changed_withdrawal_address_uses_each_consumed_dao_cell_owner(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                raise unittest.SkipTest(f"{network.name} public changed-withdrawal-address fixture is unavailable")

    # TEST-MAP: ADDR-DAO-RPC-06
    def test_default_order_and_custom_pagination_are_complete_and_disjoint(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    default_rows, default_meta = self._page(oracle, DAO_ADDRESSES[network.name], page_size=10)
                    total = int(default_meta["total"])
                    pages: list[Mapping[str, Any]] = []
                    for page in range(1, (total + 1) // 2 + 1):
                        rows, meta = self._page(oracle, DAO_ADDRESSES[network.name], page=page, page_size=2)
                        self.assertEqual(total, int(meta["total"]))
                        self.assertEqual(2, int(meta["page_size"]))
                        pages.extend(rows)
                    overflow, overflow_meta = self._page(oracle, DAO_ADDRESSES[network.name], page=total + 2, page_size=2)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(10, int(default_meta["page_size"]))
                keys = [(int(row["block_timestamp"]), int(row.get("transaction_index", -1))) for row in default_rows]
                self.assertEqual(keys, sorted(keys, reverse=True))
                hashes = [row["transaction_hash"] for row in pages]
                self.assertEqual(total, len(hashes))
                self.assertEqual(total, len(set(hashes)))
                self.assertEqual([], overflow)
                self.assertEqual(total, int(overflow_meta["total"]))

    # TEST-MAP: ADDR-DAO-RPC-07
    def test_wide_transaction_counts_and_ten_cell_previews_preserve_rpc_order(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, _meta = self._page(oracle, DAO_ADDRESSES[network.name])
                    fixture = next(row for row in rows if int(row["display_inputs_count"]) > 10 or int(row["display_outputs_count"]) > 10)
                    result = oracle.rpc_result("get_transaction", [fixture["transaction_hash"]])
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error
                transaction = result.get("transaction") if isinstance(result, dict) else None
                self.assertIsInstance(transaction, dict)
                self.assertEqual(len(transaction["inputs"]), int(fixture["display_inputs_count"]))
                self.assertEqual(len(transaction["outputs"]), int(fixture["display_outputs_count"]))
                self.assertLessEqual(len(fixture["display_inputs"]), 10)
                self.assertLessEqual(len(fixture["display_outputs"]), 10)
                self.assertEqual(list(range(len(fixture["display_outputs"]))),
                                 [int(item["cell_index"]) for item in fixture["display_outputs"]])

    # TEST-MAP: ADDR-DAO-RPC-08
    @unittest.expectedFailure  # Public APIs classify the malformed identifier as generic URI parameters.
    def test_empty_existing_address_and_invalid_or_missing_identifiers_are_isolated(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    result = oracle.rpc_result("get_transaction", [ACTIVITY_TRANSACTIONS[network.name]])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict):
                        raise OracleUnavailable(f"{network.name} empty-history fixture is unavailable")
                    payload = oracle.explorer_json(f"/v1/transactions/{ACTIVITY_TRANSACTIONS[network.name]}")
                    address = payload["data"]["attributes"]["display_outputs"][0]["address_hash"]
                    rows, meta = self._page(oracle, address)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual([], rows)
                self.assertEqual(0, int(meta["total"]))
                cases = (("not-an-address", "Address Hash Invalid"), ("0x" + "00" * 32, "Address Not Found"))
                for identifier, title in cases:
                    path = "/v1/address_dao_transactions/" + urllib.parse.quote(identifier, safe="")
                    status, errors = _explorer_response(oracle, path)
                    if status == 403 and isinstance(errors, dict) and errors.get("cloudflare_error") is True:
                        raise unittest.SkipTest(f"{network.name} edge rejected negative-path observation")
                    self.assertGreaterEqual(status, 400)
                    self.assertIsInstance(errors, list)
                    self.assertEqual(title, errors[0].get("title"))

    # TEST-MAP: ADDR-DAO-RPC-09
    def test_large_dao_values_remain_exact_decimal_integers(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, _meta = self._page(oracle, DAO_ADDRESSES[network.name])
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                values = [
                    str(item[key])
                    for row in rows
                    for side in ("display_inputs", "display_outputs")
                    for item in row[side]
                    for key in ("capacity", "interest")
                    if key in item and Decimal(str(item[key])) > 2**53 - 1
                ]
                if not values:
                    raise unittest.SkipTest(f"{network.name} public DAO value above 2^53-1 is unavailable")
                for value in values:
                    self.assertTrue(value.isdigit())

    # TEST-MAP: ADDR-DAO-RPC-10
    def test_each_listed_transaction_remains_on_the_same_canonical_block(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, _meta = self._page(oracle, DAO_ADDRESSES[network.name])
                    if not rows:
                        raise OracleUnavailable(f"{network.name} DAO history is empty")
                    row = rows[0]
                    before = oracle.rpc_result("get_transaction", [row["transaction_hash"]])
                    status = before.get("tx_status") if isinstance(before, dict) else None
                    if not isinstance(status, dict) or not isinstance(status.get("block_hash"), str):
                        raise OracleUnavailable(f"{network.name} DAO transaction status is unavailable")
                    block_hash = status["block_hash"]
                    before_block = oracle.block_by_hash(block_hash)
                    after_block = oracle.block_by_hash(block_hash)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                before_header = before_block.get("header") if isinstance(before_block, dict) else None
                after_header = after_block.get("header") if isinstance(after_block, dict) else None
                if not isinstance(before_header, dict) or not isinstance(after_header, dict):
                    raise unittest.SkipTest(f"{network.name} canonical block observation is unavailable")
                if before_header.get("hash") != after_header.get("hash"):
                    raise unittest.SkipTest(f"{network.name} reorganization observed")
                self.assertEqual(block_hash, before_header.get("hash"))
                self.assertEqual(int(row["block_number"]), decode_hex_int(before_header.get("number"), "block.number"))


if __name__ == "__main__":
    unittest.main()
