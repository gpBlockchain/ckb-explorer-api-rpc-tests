from __future__ import annotations

import json
import unittest
from typing import Any, Mapping
from urllib.parse import quote, urlencode

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int, output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response
from tests.token_udt.test_v1_udt_transactions_show import UDT_FIXTURES


ADDRESS_UDT_FIXTURES = {
    **UDT_FIXTURES,
    "testnet": "0x0637334b6867044f27951542c3eae615ed0af860502faebc3788680c09967c4d",
}


class V1AddressUdtTransactionsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.fixture_cache: dict[
            str,
            tuple[str, list[Mapping[str, Any]], dict[str, Mapping[str, Any]]],
        ] = {}

    def _page(
        self,
        oracle: NetworkOracle,
        address: str,
        **query: object,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json(
            "/v1/address_udt_transactions/" + quote(address, safe=""), query or None
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise OracleUnavailable(f"{oracle.network.name} address UDT page is unavailable")
        rows: list[Mapping[str, Any]] = []
        for item in data:
            attributes = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(attributes, dict):
                raise OracleUnavailable(f"{oracle.network.name} address UDT row is unavailable")
            rows.append(attributes)
        return rows, meta

    def _fixture(
        self,
        oracle: NetworkOracle,
    ) -> tuple[str, list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
        name = oracle.network.name
        if name in self.fixture_cache:
            return self.fixture_cache[name]
        type_hash = ADDRESS_UDT_FIXTURES[name]
        payload = oracle.explorer_json(
            f"/v1/udt_transactions/{type_hash}", {"page": 1, "page_size": 100}
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            raise OracleUnavailable(f"{name} global UDT fixture is unavailable")
        rows: list[Mapping[str, Any]] = []
        hashes: list[str] = []
        for item in data:
            attributes = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(attributes, dict) or not isinstance(attributes.get("transaction_hash"), str):
                raise OracleUnavailable(f"{name} global UDT row is unavailable")
            rows.append(attributes)
            hashes.append(attributes["transaction_hash"])
        results = oracle.rpc_batch_results([("get_transaction", [tx_hash]) for tx_hash in hashes])
        transactions: dict[str, Mapping[str, Any]] = {}
        address_sets: list[set[str]] = []
        for tx_hash, result in zip(hashes, results, strict=True):
            transaction = result.get("transaction") if isinstance(result, dict) else None
            status = result.get("tx_status") if isinstance(result, dict) else None
            if not isinstance(transaction, dict) or not isinstance(status, dict):
                raise OracleUnavailable(f"{name} RPC transaction {tx_hash} is unavailable")
            if status.get("status") != "committed":
                raise OracleUnavailable(f"{name} RPC transaction {tx_hash} is not committed")
            outputs = transaction.get("outputs")
            if not isinstance(outputs, list) or any(not isinstance(output, dict) for output in outputs):
                raise OracleUnavailable(f"{name} RPC outputs for {tx_hash} are unavailable")
            addresses = {output_address(output, oracle.network.address_hrp) for output in outputs}
            addresses.update(
                output_address(output, oracle.network.address_hrp)
                for output, _data in oracle.referenced_outputs(transaction)
            )
            address_sets.append(addresses)
            transactions[tx_hash] = transaction
        common = set.intersection(*address_sets)
        if not common:
            raise OracleUnavailable(f"{name} has no address participating in every fixture transaction")
        address = sorted(common)[0]
        self.fixture_cache[name] = address, rows, transactions
        return self.fixture_cache[name]

    # TEST-MAP: UDT-TX-RPC-10
    def test_default_adjacent_and_oversized_pages_use_the_confirmed_address_udt_intersection_order(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                type_hash = ADDRESS_UDT_FIXTURES[network.name]
                try:
                    address, global_rows, _transactions = self._fixture(oracle)
                    default, default_meta = self._page(oracle, address, type_hash=type_hash)
                    first, first_meta = self._page(
                        oracle, address, type_hash=type_hash, page=1, page_size=1
                    )
                    second, second_meta = self._page(
                        oracle, address, type_hash=type_hash, page=2, page_size=1
                    )
                    combined, combined_meta = self._page(
                        oracle, address, type_hash=type_hash, page=1, page_size=2
                    )
                    oversized, oversized_meta = self._page(
                        oracle, address, type_hash=type_hash, page=1, page_size=101
                    )
                    hashes = [str(row["transaction_hash"]) for row in default]
                    rpc_results = oracle.rpc_batch_results(
                        [("get_transaction", [tx_hash]) for tx_hash in hashes]
                    )
                    order: list[tuple[int, int]] = []
                    for tx_hash, result in zip(hashes, rpc_results, strict=True):
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        block_hash = status.get("block_hash") if isinstance(status, dict) else None
                        if not isinstance(status, dict) or not isinstance(block_hash, str):
                            raise OracleUnavailable(f"{network.name} RPC status for {tx_hash} is unavailable")
                        block = oracle.block_by_hash(block_hash)
                        header = block.get("header") if isinstance(block, dict) else None
                        if not isinstance(header, dict):
                            raise OracleUnavailable(f"{network.name} RPC block for {tx_hash} is unavailable")
                        order.append(
                            (
                                decode_hex_int(header.get("timestamp"), "address_udt.timestamp"),
                                decode_hex_int(status.get("tx_index"), "address_udt.tx_index"),
                            )
                        )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                expected_hashes = [str(row["transaction_hash"]) for row in global_rows]
                self.assertEqual(expected_hashes, hashes)
                self.assertEqual(10, int(default_meta["page_size"]))
                self.assertEqual(first + second, combined[:2])
                self.assertEqual(first_meta["total"], second_meta["total"])
                self.assertEqual(first_meta["total"], combined_meta["total"])
                self.assertEqual(len(expected_hashes), int(default_meta["total"]))
                self.assertLessEqual(int(oversized_meta["page_size"]), 100)
                self.assertLessEqual(len(oversized), int(oversized_meta["page_size"]))
                self.assertEqual(order, sorted(order, reverse=True))

    # TEST-MAP: UDT-TX-RPC-11
    @unittest.expectedFailure
    def test_previews_match_global_rows_type_script_and_address_income_matches_rpc_capacity_change(self) -> None:
        income_mismatches: list[tuple[str, str, int, object]] = []
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            type_hash = ADDRESS_UDT_FIXTURES[network.name]
            try:
                address, global_rows, transactions = self._fixture(oracle)
                address_rows, _meta = self._page(
                    oracle, address, type_hash=type_hash, page=1, page_size=100
                )
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            global_by_hash = {str(row["transaction_hash"]): row for row in global_rows}
            self.assertEqual(set(global_by_hash), {str(row["transaction_hash"]) for row in address_rows})
            for row in address_rows:
                tx_hash = str(row["transaction_hash"])
                transaction = transactions[tx_hash]
                outputs = transaction.get("outputs")
                if not isinstance(outputs, list):
                    raise unittest.SkipTest(f"{network.name} RPC outputs for {tx_hash} are unavailable")
                referenced = oracle.referenced_outputs(transaction)
                self.assertEqual(
                    {key: value for key, value in global_by_hash[tx_hash].items() if key != "income"},
                    {key: value for key, value in row.items() if key != "income"},
                )
                scripts = [
                    output.get("type")
                    for output in outputs + [item[0] for item in referenced]
                    if isinstance(output, dict) and isinstance(output.get("type"), dict)
                ]
                self.assertIn(type_hash, {ckb_script_hash(script) for script in scripts})
                input_capacity = sum(
                    decode_hex_int(output.get("capacity"), "address_udt.input_capacity")
                    for output, _data in referenced
                    if output_address(output, network.address_hrp) == address
                )
                output_capacity = sum(
                    decode_hex_int(output.get("capacity"), "address_udt.output_capacity")
                    for output in outputs
                    if output_address(output, network.address_hrp) == address
                )
                expected_income = output_capacity - input_capacity
                if row.get("income") != expected_income:
                    income_mismatches.append(
                        (network.name, tx_hash, expected_income, row.get("income"))
                    )
        self.assertEqual([], income_mismatches)

    # TEST-MAP: UDT-TX-RPC-12
    def test_address_type_hash_existence_publication_and_pagination_errors_follow_validation_order(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                address, _rows, _transactions = self._fixture(oracle)
                catalog = oracle.explorer_json("/v1/udts", {"page": 1, "page_size": 100})
                data = catalog.get("data") if isinstance(catalog, dict) else None
                if not isinstance(data, list):
                    raise OracleUnavailable(f"{network.name} UDT catalog is unavailable")
                unpublished = next(
                    (
                        row["attributes"].get("type_hash")
                        for row in data
                        if isinstance(row, dict)
                        and isinstance(row.get("attributes"), dict)
                        and row["attributes"].get("published") is False
                    ),
                    None,
                )
                fake_address = output_address(
                    {
                        "lock": {
                            "code_hash": "0x" + "11" * 32,
                            "hash_type": "type",
                            "args": "0x" + "22" * 20,
                        }
                    },
                    network.address_hrp,
                )
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            if not isinstance(unpublished, str):
                raise unittest.SkipTest(f"{network.name} unpublished UDT fixture is unavailable")
            encoded_address = quote(address, safe="")
            type_hash = ADDRESS_UDT_FIXTURES[network.name]
            cases = (
                ("invalid-address", "/v1/address_udt_transactions/bad?" + urlencode({"type_hash": type_hash}), 422, {1009}),
                ("missing-type", "/v1/address_udt_transactions/" + encoded_address, 422, {1025}),
                ("invalid-type", "/v1/address_udt_transactions/" + encoded_address + "?type_hash=bad", 422, {1025}),
                (
                    "missing-address",
                    "/v1/address_udt_transactions/" + quote(fake_address, safe="") + "?" + urlencode({"type_hash": type_hash}),
                    404,
                    {1010},
                ),
                (
                    "missing-udt",
                    "/v1/address_udt_transactions/" + encoded_address + "?" + urlencode({"type_hash": "0x" + "ff" * 32}),
                    404,
                    {1026},
                ),
                (
                    "unpublished-udt",
                    "/v1/address_udt_transactions/" + encoded_address + "?" + urlencode({"type_hash": unpublished}),
                    404,
                    {1026},
                ),
                (
                    "invalid-page-and-size",
                    "/v1/address_udt_transactions/" + encoded_address + "?" + urlencode({"type_hash": type_hash, "page": 0, "page_size": "x"}),
                    400,
                    {1007, 1008},
                ),
            )
            for label, path, expected_status, expected_codes in cases:
                with self.subTest(network=network.name, error=label):
                    try:
                        status, raw = _raw_explorer_response(oracle, path)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(expected_status, status)
                    payload = json.loads(raw)
                    self.assertIsInstance(payload, list)
                    self.assertEqual(expected_codes, {int(error["code"]) for error in payload})
                    self.assertFalse(any("data" in error for error in payload))


if __name__ == "__main__":
    unittest.main()
