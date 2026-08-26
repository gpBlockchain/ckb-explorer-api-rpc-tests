from __future__ import annotations

import unittest
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import decode_hex_int, output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


ORDINARY_FIXTURES = {
    "mainnet": "0xab14b3580046c61056699d2aff8ae707b56d6cb79c19c8ad6af18cb8a2d45cf0",
    "testnet": "0xa7f2644682002f9a9a7dfcef7ed749c16a6f4ea92a2aac21b7f6e2f900253501",
}
MIXED_FIXTURES = {
    "mainnet": "0x2afff0376860381cab26f9ffdcce08f6eca0ce66d0e02643150e5960577a5f48",
    "testnet": "0x3c57557ef883e1c2388678e6a284f1e221d9b4a7dfdd341729da147254ec5712",
}


class V2TransactionsDetailsRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _load(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
    ) -> tuple[
        Mapping[str, Any],
        list[tuple[Mapping[str, Any], object]],
        Mapping[str, Any],
        list[Mapping[str, Any]],
    ]:
        try:
            api_genesis = oracle.detail_attributes(0)
            rpc_genesis = oracle.block(0)
            api_tip = oracle.api_tip_height()
            rpc_tip = oracle.rpc_tip_height()
            result = oracle.rpc_result("get_transaction", [transaction_hash])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        transaction = result.get("transaction") if isinstance(result, dict) else None
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC transaction {transaction_hash} is unavailable"
            )
        try:
            referenced_outputs = oracle.referenced_outputs(transaction)
            payload = oracle.explorer_json(f"/v2/transactions/{transaction_hash}/details")
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        rpc_header = rpc_genesis.get("header")
        data = payload.get("data") if isinstance(payload, dict) else None
        self.assertIsInstance(rpc_header, dict)
        self.assertEqual(rpc_header.get("hash"), api_genesis.get("block_hash"))
        self.assertLessEqual(api_tip, rpc_tip)
        self.assertLessEqual(rpc_tip - api_tip, self.settings.max_lag_blocks)
        self.assertEqual("committed", status.get("status"))
        self.assertEqual(transaction_hash, transaction.get("hash"))
        self.assertIsInstance(data, list)
        self.assertTrue(all(isinstance(row, dict) for row in data))
        return transaction, referenced_outputs, status, data

    def _integer(self, value: object, field: str) -> int:
        try:
            decimal = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            self.fail(f"{field} is not a decimal number: {value!r}; {error}")
        self.assertTrue(decimal.is_finite(), f"{field} must be finite")
        self.assertEqual(decimal, decimal.to_integral_value(), f"{field} must be an integer")
        return int(decimal)

    def _actual(self, data: list[Mapping[str, Any]]) -> dict[str, int]:
        actual: dict[str, int] = {}
        for index, row in enumerate(data):
            address = row.get("address")
            transfers = row.get("transfers")
            self.assertIsInstance(address, str, f"data[{index}].address")
            self.assertNotIn(address, actual, f"duplicate address {address}")
            self.assertIsInstance(transfers, list, f"data[{index}].transfers")
            self.assertEqual(1, len(transfers), f"data[{index}].transfers")
            transfer = transfers[0]
            self.assertIsInstance(transfer, dict)
            self.assertEqual("CKB", transfer.get("asset"))
            self.assertEqual("CKB", transfer.get("token_name"))
            self.assertEqual("CKB", transfer.get("entity_type"))
            self.assertEqual("simple_transfer", transfer.get("transfer_type"))
            actual[str(address)] = self._integer(
                transfer.get("capacity"), f"data[{index}].capacity"
            )
        return actual

    def _assert_stable(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
        initial_status: Mapping[str, Any],
    ) -> None:
        try:
            fresh = oracle.rpc_result("get_transaction", [transaction_hash])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        status = fresh.get("tx_status") if isinstance(fresh, dict) else None
        if not isinstance(status, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC transaction {transaction_hash} became unavailable"
            )
        if (
            status.get("status") != initial_status.get("status")
            or status.get("block_hash") != initial_status.get("block_hash")
        ):
            raise unittest.SkipTest(
                f"{oracle.network.name} transaction {transaction_hash} changed status or block"
            )

    # TEST-MAP: V2-TX-RPC-04
    def test_repeated_ordinary_address_capacity_changes_match_rpc(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                transaction_hash = ORDINARY_FIXTURES[network.name]
                transaction, references, status, data = self._load(oracle, transaction_hash)
                try:
                    display_inputs = oracle.explorer_json(
                        f"/v2/ckb_transactions/{transaction_hash}/display_inputs"
                    ).get("data")
                    display_outputs = oracle.explorer_json(
                        f"/v2/ckb_transactions/{transaction_hash}/display_outputs"
                    ).get("data")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertIsInstance(display_inputs, list)
                self.assertIsInstance(display_outputs, list)
                self.assertTrue(all(row.get("cell_type") == "normal" for row in display_inputs))
                self.assertTrue(all(row.get("cell_type") == "normal" for row in display_outputs))

                expected: defaultdict[str, int] = defaultdict(int)
                counts: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
                for output, _output_data in references:
                    address = output_address(output, network.address_hrp)
                    expected[address] -= decode_hex_int(output.get("capacity"), "input.capacity")
                    counts[address][0] += 1
                outputs = transaction.get("outputs")
                self.assertIsInstance(outputs, list)
                for output in outputs:
                    self.assertIsInstance(output, dict)
                    address = output_address(output, network.address_hrp)
                    expected[address] += decode_hex_int(output.get("capacity"), "output.capacity")
                    counts[address][1] += 1
                self.assertTrue(
                    any(input_count > 1 and output_count > 1 for input_count, output_count in counts.values())
                )
                self.assertNotIn(0, expected.values())
                self.assertEqual(dict(expected), self._actual(data))
                self._assert_stable(oracle, transaction_hash, status)

    # TEST-MAP: V2-TX-RPC-05
    def test_mixed_special_cells_are_excluded_from_ordinary_ckb_changes(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                transaction_hash = MIXED_FIXTURES[network.name]
                transaction, references, status, data = self._load(oracle, transaction_hash)
                try:
                    input_payload = oracle.explorer_json(
                        f"/v2/ckb_transactions/{transaction_hash}/display_inputs"
                    )
                    output_payload = oracle.explorer_json(
                        f"/v2/ckb_transactions/{transaction_hash}/display_outputs"
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                display_inputs = input_payload.get("data") if isinstance(input_payload, dict) else None
                display_outputs = output_payload.get("data") if isinstance(output_payload, dict) else None
                outputs = transaction.get("outputs")
                self.assertIsInstance(display_inputs, list)
                self.assertIsInstance(display_outputs, list)
                self.assertIsInstance(outputs, list)
                self.assertEqual(len(references), len(display_inputs))
                self.assertEqual(len(outputs), len(display_outputs))

                expected: defaultdict[str, int] = defaultdict(int)
                normal_addresses: set[str] = set()
                special_addresses: set[str] = set()
                for index, ((output, _output_data), display) in enumerate(
                    zip(references, display_inputs, strict=True)
                ):
                    self.assertIsInstance(display, dict)
                    previous_output = transaction["inputs"][index].get("previous_output")
                    self.assertIsInstance(previous_output, dict)
                    address = output_address(output, network.address_hrp)
                    self.assertEqual(previous_output.get("tx_hash"), display.get("generated_tx_hash"))
                    self.assertEqual(
                        decode_hex_int(previous_output.get("index"), "previous_output.index"),
                        int(display.get("cell_index")),
                    )
                    self.assertEqual(address, display.get("address_hash"))
                    self.assertEqual(
                        decode_hex_int(output.get("capacity"), "input.capacity"),
                        self._integer(display.get("capacity"), "display_input.capacity"),
                    )
                    if display.get("cell_type") == "normal":
                        normal_addresses.add(address)
                        expected[address] -= decode_hex_int(output.get("capacity"), "input.capacity")
                    else:
                        special_addresses.add(address)

                for index, (output, display) in enumerate(
                    zip(outputs, display_outputs, strict=True)
                ):
                    self.assertIsInstance(output, dict)
                    self.assertIsInstance(display, dict)
                    address = output_address(output, network.address_hrp)
                    self.assertEqual(transaction_hash, display.get("generated_tx_hash"))
                    self.assertEqual(index, int(display.get("cell_index")))
                    self.assertEqual(address, display.get("address_hash"))
                    self.assertEqual(
                        decode_hex_int(output.get("capacity"), "output.capacity"),
                        self._integer(display.get("capacity"), "display_output.capacity"),
                    )
                    if display.get("cell_type") == "normal":
                        normal_addresses.add(address)
                        expected[address] += decode_hex_int(output.get("capacity"), "output.capacity")
                    else:
                        special_addresses.add(address)

                self.assertTrue(normal_addresses & special_addresses)
                self.assertTrue(special_addresses - normal_addresses)
                self.assertNotIn(0, expected.values())
                self.assertEqual(dict(expected), self._actual(data))
                self._assert_stable(oracle, transaction_hash, status)


if __name__ == "__main__":
    unittest.main()
