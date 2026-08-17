from __future__ import annotations

import unittest
from decimal import Decimal

from ckb_rpc_correctness.ckb import decode_hex_int, output_address, output_occupied_capacity
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


STRUCTURE_FIXTURES = {
    "mainnet": "0xba86729380f7e033d722e8fc197159db4dbd4ad6e05e28e297be8230e12a0af7",
    "testnet": "0x926de250e2771d0dc9bb49d6a9f27877d3ca7c46d473017a92cce5eed111cac6",
}
CELL_FIXTURES = {
    "mainnet": "0xab14b3580046c61056699d2aff8ae707b56d6cb79c19c8ad6af18cb8a2d45cf0",
    "testnet": "0xa7f2644682002f9a9a7dfcef7ed749c16a6f4ea92a2aac21b7f6e2f900253501",
}
WIDE_FIXTURES = {
    "mainnet": "0x4a72d274cd96f060a5184f4cf781f7c8999542843fdd9347fb8443fb58387efc",
    "testnet": "0x01ee3b9299136f07b659d5e7a9804b4d11d5b47d985abd749f5b353e4528cccf",
}
CELLBASE_FIXTURES = {
    "mainnet": "0x309bd4333114ec1394bd8226f4d54e318decfa6a168b94d188b1ed136c8eb5e1",
    "testnet": "0xe90b5763d3b53779a55ceac54c33fa6dc9113c0570de3a8ef696c9ad58db41b8",
}


class V1TransactionsShowRpcCorrectnessTests(unittest.TestCase):
    # TEST-MAP: TX-DETAIL-RPC-01
    def test_normal_transaction_identity_status_version_and_block_fields_match_rpc(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                tx_hash = CELL_FIXTURES[network.name]
                try:
                    api_genesis = oracle.detail_attributes(0)
                    rpc_genesis = oracle.block(0)
                    api_tip = oracle.api_tip_height()
                    rpc_tip = oracle.rpc_tip_height()
                    rpc_result = oracle.rpc_result("get_transaction", [tx_hash])
                    payload = oracle.explorer_json(f"/v1/transactions/{tx_hash}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                attributes = data.get("attributes") if isinstance(data, dict) else None
                transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
                status = rpc_result.get("tx_status") if isinstance(rpc_result, dict) else None
                self.assertIsInstance(attributes, dict)
                self.assertIsInstance(transaction, dict)
                self.assertIsInstance(status, dict)
                block_hash = status.get("block_hash")
                self.assertIsInstance(block_hash, str)
                try:
                    rpc_block = oracle.block_by_hash(block_hash)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                header = rpc_block.get("header")
                self.assertIsInstance(header, dict)
                genesis_header = rpc_genesis.get("header")
                self.assertIsInstance(genesis_header, dict)

                self.assertEqual(genesis_header.get("hash"), api_genesis.get("block_hash"))
                self.assertLessEqual(api_tip, rpc_tip)
                self.assertLessEqual(rpc_tip - api_tip, settings.max_lag_blocks)
                self.assertEqual(tx_hash, transaction.get("hash"))
                self.assertEqual(tx_hash, attributes.get("transaction_hash"))
                self.assertEqual("committed", status.get("status"))
                self.assertEqual("committed", attributes.get("tx_status"))
                self.assertIs(attributes.get("is_cellbase"), False)
                self.assertGreater(decode_hex_int(status.get("tx_index"), "tx_status.tx_index"), 0)
                self.assertEqual(block_hash, header.get("hash"))
                self.assertEqual(
                    decode_hex_int(status.get("block_number"), "tx_status.block_number"),
                    int(attributes["block_number"]),
                )
                self.assertEqual(
                    decode_hex_int(header.get("number"), "header.number"),
                    int(attributes["block_number"]),
                )
                self.assertEqual(
                    decode_hex_int(header.get("timestamp"), "header.timestamp"),
                    int(attributes["block_timestamp"]),
                )
                self.assertEqual(
                    decode_hex_int(transaction.get("version"), "transaction.version"),
                    int(attributes["version"]),
                )

    # TEST-MAP: TX-DETAIL-RPC-02
    def test_witnesses_header_dependencies_and_cell_dependencies_match_rpc_order(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                tx_hash = STRUCTURE_FIXTURES[network.name]
                try:
                    rpc_result = oracle.rpc_result("get_transaction", [tx_hash])
                    payload = oracle.explorer_json(f"/v1/transactions/{tx_hash}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                attributes = data.get("attributes") if isinstance(data, dict) else None
                transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
                status = rpc_result.get("tx_status") if isinstance(rpc_result, dict) else None
                self.assertIsInstance(attributes, dict)
                self.assertIsInstance(transaction, dict)
                self.assertIsInstance(status, dict)
                witnesses = transaction.get("witnesses")
                header_deps = transaction.get("header_deps")
                cell_deps = transaction.get("cell_deps")
                api_cell_deps = attributes.get("cell_deps")
                self.assertIsInstance(witnesses, list)
                self.assertIsInstance(header_deps, list)
                self.assertIsInstance(cell_deps, list)
                self.assertIsInstance(api_cell_deps, list)

                self.assertEqual("committed", status.get("status"))
                self.assertTrue(witnesses)
                self.assertTrue(header_deps)
                self.assertTrue(cell_deps)
                self.assertEqual(witnesses, attributes.get("witnesses"))
                self.assertEqual(header_deps, attributes.get("header_deps"))
                self.assertEqual(len(cell_deps), len(api_cell_deps))
                for index, (rpc_dep, api_dep) in enumerate(zip(cell_deps, api_cell_deps, strict=True)):
                    rpc_out_point = rpc_dep.get("out_point") if isinstance(rpc_dep, dict) else None
                    api_out_point = api_dep.get("out_point") if isinstance(api_dep, dict) else None
                    self.assertIsInstance(rpc_out_point, dict)
                    self.assertIsInstance(api_out_point, dict)
                    self.assertEqual(rpc_dep.get("dep_type"), api_dep.get("dep_type"))
                    self.assertEqual(rpc_out_point.get("tx_hash"), api_out_point.get("tx_hash"))
                    self.assertEqual(
                        decode_hex_int(rpc_out_point.get("index"), f"cell_deps[{index}].out_point.index"),
                        int(api_out_point["index"]),
                    )

    # TEST-MAP: TX-DETAIL-RPC-03
    def test_all_normal_inputs_match_referenced_rpc_outputs_in_order(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                tx_hash = CELL_FIXTURES[network.name]
                try:
                    rpc_result = oracle.rpc_result("get_transaction", [tx_hash])
                    transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
                    if not isinstance(transaction, dict):
                        raise OracleUnavailable(f"{network.name} RPC transaction {tx_hash} is unavailable")
                    referenced_outputs = oracle.referenced_outputs(transaction)
                    payload = oracle.explorer_json(f"/v1/transactions/{tx_hash}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                attributes = data.get("attributes") if isinstance(data, dict) else None
                inputs = transaction.get("inputs")
                self.assertIsInstance(attributes, dict)
                self.assertIsInstance(inputs, list)
                display_inputs = attributes.get("display_inputs")
                self.assertIsInstance(display_inputs, list)
                self.assertGreater(len(inputs), 1)
                self.assertTrue(any(output.get("type") is None for output, _data in referenced_outputs))
                self.assertTrue(any(output.get("type") is not None for output, _data in referenced_outputs))

                self.assertEqual(len(inputs), len(referenced_outputs))
                self.assertEqual(len(inputs), len(display_inputs))
                for index, (rpc_input, referenced, display) in enumerate(
                    zip(inputs, referenced_outputs, display_inputs, strict=True)
                ):
                    previous_output, output_data = referenced
                    previous = rpc_input.get("previous_output") if isinstance(rpc_input, dict) else None
                    since = display.get("since") if isinstance(display, dict) else None
                    self.assertIsInstance(previous, dict)
                    self.assertIsInstance(since, dict)
                    self.assertIs(display.get("from_cellbase"), False)
                    self.assertEqual(previous.get("tx_hash"), display.get("generated_tx_hash"))
                    self.assertEqual(
                        decode_hex_int(previous.get("index"), f"inputs[{index}].previous_output.index"),
                        int(display["cell_index"]),
                    )
                    self.assertEqual(
                        decode_hex_int(rpc_input.get("since"), f"inputs[{index}].since"),
                        decode_hex_int(since.get("raw"), f"display_inputs[{index}].since.raw"),
                    )
                    self.assertEqual(
                        Decimal(decode_hex_int(previous_output.get("capacity"), "previous_output.capacity")),
                        Decimal(str(display["capacity"])),
                    )
                    self.assertEqual(
                        output_occupied_capacity(previous_output, output_data),
                        int(Decimal(str(display["occupied_capacity"]))),
                    )
                    self.assertEqual(
                        output_address(previous_output, network.address_hrp),
                        display.get("address_hash"),
                    )
                    if previous_output.get("type") is None:
                        self.assertEqual("", display.get("type_script"))
                    else:
                        self.assertEqual(previous_output.get("type"), display.get("type_script"))

    # TEST-MAP: TX-DETAIL-RPC-04
    def test_all_normal_outputs_match_rpc_outputs_in_index_order(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                tx_hash = CELL_FIXTURES[network.name]
                try:
                    rpc_result = oracle.rpc_result("get_transaction", [tx_hash])
                    payload = oracle.explorer_json(f"/v1/transactions/{tx_hash}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                attributes = data.get("attributes") if isinstance(data, dict) else None
                transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
                self.assertIsInstance(attributes, dict)
                self.assertIsInstance(transaction, dict)
                outputs = transaction.get("outputs")
                outputs_data = transaction.get("outputs_data")
                display_outputs = attributes.get("display_outputs")
                self.assertIsInstance(outputs, list)
                self.assertIsInstance(outputs_data, list)
                self.assertIsInstance(display_outputs, list)
                self.assertGreater(len(outputs), 1)
                self.assertTrue(any(output.get("type") is None for output in outputs))
                self.assertTrue(any(output.get("type") is not None for output in outputs))

                self.assertEqual(len(outputs), len(outputs_data))
                self.assertEqual(len(outputs), len(display_outputs))
                for index, (output, output_data, display) in enumerate(
                    zip(outputs, outputs_data, display_outputs, strict=True)
                ):
                    self.assertEqual(tx_hash, display.get("generated_tx_hash"))
                    self.assertEqual(index, int(display["cell_index"]))
                    self.assertEqual(
                        Decimal(decode_hex_int(output.get("capacity"), f"outputs[{index}].capacity")),
                        Decimal(str(display["capacity"])),
                    )
                    self.assertEqual(
                        output_occupied_capacity(output, output_data),
                        int(Decimal(str(display["occupied_capacity"]))),
                    )
                    self.assertEqual(output_address(output, network.address_hrp), display.get("address_hash"))
                    if output.get("type") is None:
                        self.assertEqual("", display.get("type_script"))
                    else:
                        self.assertEqual(output.get("type"), display.get("type_script"))

    # TEST-MAP: TX-DETAIL-RPC-05
    def test_default_detail_does_not_truncate_transactions_wider_than_ten_cells(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                tx_hash = WIDE_FIXTURES[network.name]
                try:
                    rpc_result = oracle.rpc_result("get_transaction", [tx_hash])
                    payload = oracle.explorer_json(f"/v1/transactions/{tx_hash}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                attributes = data.get("attributes") if isinstance(data, dict) else None
                transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
                self.assertIsInstance(attributes, dict)
                self.assertIsInstance(transaction, dict)
                inputs = transaction.get("inputs")
                outputs = transaction.get("outputs")
                display_inputs = attributes.get("display_inputs")
                display_outputs = attributes.get("display_outputs")
                self.assertIsInstance(inputs, list)
                self.assertIsInstance(outputs, list)
                self.assertIsInstance(display_inputs, list)
                self.assertIsInstance(display_outputs, list)
                self.assertTrue(len(inputs) > 10 or len(outputs) > 10)

                self.assertEqual(len(inputs), len(display_inputs))
                self.assertEqual(len(outputs), len(display_outputs))
                if len(inputs) > 10:
                    previous = inputs[-1].get("previous_output")
                    self.assertIsInstance(previous, dict)
                    self.assertEqual(previous.get("tx_hash"), display_inputs[-1].get("generated_tx_hash"))
                    self.assertEqual(
                        decode_hex_int(previous.get("index"), "inputs[-1].previous_output.index"),
                        int(display_inputs[-1]["cell_index"]),
                    )
                if len(outputs) > 10:
                    self.assertEqual(tx_hash, display_outputs[-1].get("generated_tx_hash"))
                    self.assertEqual(len(outputs) - 1, int(display_outputs[-1]["cell_index"]))

    # TEST-MAP: TX-DETAIL-RPC-06
    def test_display_cells_false_only_suppresses_the_two_cell_arrays(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                tx_hash = CELL_FIXTURES[network.name]
                try:
                    default_payload = oracle.explorer_json(f"/v1/transactions/{tx_hash}")
                    true_payload = oracle.explorer_json(
                        f"/v1/transactions/{tx_hash}", {"display_cells": "true"}
                    )
                    false_payload = oracle.explorer_json(
                        f"/v1/transactions/{tx_hash}", {"display_cells": "false"}
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                default_data = default_payload.get("data") if isinstance(default_payload, dict) else None
                true_data = true_payload.get("data") if isinstance(true_payload, dict) else None
                false_data = false_payload.get("data") if isinstance(false_payload, dict) else None
                default_attributes = default_data.get("attributes") if isinstance(default_data, dict) else None
                true_attributes = true_data.get("attributes") if isinstance(true_data, dict) else None
                false_attributes = false_data.get("attributes") if isinstance(false_data, dict) else None
                self.assertIsInstance(default_attributes, dict)
                self.assertIsInstance(true_attributes, dict)
                self.assertIsInstance(false_attributes, dict)

                self.assertTrue(default_attributes.get("display_inputs"))
                self.assertTrue(default_attributes.get("display_outputs"))
                self.assertEqual(default_attributes.get("display_inputs"), true_attributes.get("display_inputs"))
                self.assertEqual(default_attributes.get("display_outputs"), true_attributes.get("display_outputs"))
                self.assertEqual([], false_attributes.get("display_inputs"))
                self.assertEqual([], false_attributes.get("display_outputs"))
                for field in (
                    "transaction_hash",
                    "tx_status",
                    "is_cellbase",
                    "witnesses",
                    "cell_deps",
                    "header_deps",
                    "block_number",
                    "version",
                    "block_timestamp",
                    "transaction_fee",
                    "bytes",
                    "cycles",
                ):
                    self.assertEqual(default_attributes.get(field), true_attributes.get(field), field)
                    self.assertEqual(default_attributes.get(field), false_attributes.get(field), field)

    # TEST-MAP: TX-DETAIL-RPC-07
    def test_transaction_fee_is_exact_input_capacity_minus_output_capacity(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                tx_hash = CELL_FIXTURES[network.name]
                try:
                    rpc_result = oracle.rpc_result("get_transaction", [tx_hash])
                    transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
                    if not isinstance(transaction, dict):
                        raise OracleUnavailable(f"{network.name} RPC transaction {tx_hash} is unavailable")
                    referenced_outputs = oracle.referenced_outputs(transaction)
                    payload = oracle.explorer_json(f"/v1/transactions/{tx_hash}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                attributes = data.get("attributes") if isinstance(data, dict) else None
                outputs = transaction.get("outputs")
                self.assertIsInstance(attributes, dict)
                self.assertIsInstance(outputs, list)
                inputs = transaction.get("inputs")
                self.assertIsInstance(inputs, list)
                self.assertEqual(len(inputs), len(referenced_outputs))
                expected_fee = sum(
                    decode_hex_int(output.get("capacity"), f"inputs[{index}].capacity")
                    for index, (output, _data) in enumerate(referenced_outputs)
                ) - sum(
                    decode_hex_int(output.get("capacity"), f"outputs[{index}].capacity")
                    for index, output in enumerate(outputs)
                )

                self.assertGreater(expected_fee, 0)
                self.assertEqual(expected_fee, int(attributes["transaction_fee"]))

    # TEST-MAP: TX-DETAIL-RPC-08
    def test_bytes_match_raw_rpc_serialized_transaction_size_with_length_prefix(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            for kind, tx_hash in (
                ("normal", CELL_FIXTURES[network.name]),
                ("cellbase", CELLBASE_FIXTURES[network.name]),
            ):
                with self.subTest(network=network.name, kind=kind):
                    oracle = NetworkOracle(network, settings)
                    try:
                        rpc_result = oracle.rpc_result("get_transaction", [tx_hash, "0x0"])
                        payload = oracle.explorer_json(f"/v1/transactions/{tx_hash}")
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error

                    data = payload.get("data") if isinstance(payload, dict) else None
                    attributes = data.get("attributes") if isinstance(data, dict) else None
                    raw_transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
                    self.assertIsInstance(attributes, dict)
                    self.assertIsInstance(raw_transaction, str)
                    self.assertTrue(raw_transaction.startswith("0x"))
                    self.assertEqual(0, (len(raw_transaction) - 2) % 2)
                    expected_bytes = (len(raw_transaction) - 2) // 2 + 4

                    self.assertGreater(expected_bytes, 4)
                    self.assertEqual(expected_bytes, int(attributes["bytes"]))

    # TEST-MAP: TX-DETAIL-RPC-09
    def test_cycles_match_rpc_for_nonzero_cycle_normal_transaction(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                tx_hash = CELL_FIXTURES[network.name]
                try:
                    rpc_result = oracle.rpc_result("get_transaction", [tx_hash])
                    payload = oracle.explorer_json(f"/v1/transactions/{tx_hash}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                attributes = data.get("attributes") if isinstance(data, dict) else None
                status = rpc_result.get("tx_status") if isinstance(rpc_result, dict) else None
                self.assertIsInstance(attributes, dict)
                self.assertIsInstance(status, dict)
                expected_cycles = decode_hex_int(rpc_result.get("cycles"), "get_transaction.cycles")

                self.assertEqual("committed", status.get("status"))
                self.assertGreater(expected_cycles, 0)
                self.assertEqual(expected_cycles, int(attributes["cycles"]))

    # TEST-MAP: TX-DETAIL-RPC-10
    def test_cellbase_uses_special_identity_fee_cycles_input_and_target_height(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                tx_hash = CELLBASE_FIXTURES[network.name]
                try:
                    rpc_result = oracle.rpc_result("get_transaction", [tx_hash])
                    payload = oracle.explorer_json(f"/v1/transactions/{tx_hash}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                attributes = data.get("attributes") if isinstance(data, dict) else None
                transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
                status = rpc_result.get("tx_status") if isinstance(rpc_result, dict) else None
                self.assertIsInstance(attributes, dict)
                self.assertIsInstance(transaction, dict)
                self.assertIsInstance(status, dict)
                block_hash = status.get("block_hash")
                self.assertIsInstance(block_hash, str)
                try:
                    rpc_block = oracle.block_by_hash(block_hash)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                block_transactions = rpc_block.get("transactions")
                outputs = transaction.get("outputs")
                display_inputs = attributes.get("display_inputs")
                display_outputs = attributes.get("display_outputs")
                self.assertIsInstance(block_transactions, list)
                self.assertIsInstance(outputs, list)
                self.assertIsInstance(display_inputs, list)
                self.assertIsInstance(display_outputs, list)
                block_number = decode_hex_int(status.get("block_number"), "tx_status.block_number")

                self.assertGreater(block_number, settings.proposal_window + 1)
                self.assertEqual(tx_hash, transaction.get("hash"))
                self.assertEqual(tx_hash, block_transactions[0].get("hash"))
                self.assertEqual(0, decode_hex_int(status.get("tx_index"), "tx_status.tx_index"))
                self.assertEqual("committed", status.get("status"))
                self.assertEqual(tx_hash, attributes.get("transaction_hash"))
                self.assertEqual("committed", attributes.get("tx_status"))
                self.assertIs(attributes.get("is_cellbase"), True)
                self.assertEqual(0, int(attributes["transaction_fee"]))
                self.assertIsNone(rpc_result.get("cycles"))
                self.assertIsNone(attributes.get("cycles"))
                self.assertEqual(1, len(display_inputs))
                self.assertIs(display_inputs[0].get("from_cellbase"), True)
                self.assertEqual(tx_hash, display_inputs[0].get("generated_tx_hash"))
                self.assertEqual(
                    block_number - settings.proposal_window - 1,
                    int(display_inputs[0]["target_block_number"]),
                )
                self.assertEqual(len(outputs), len(display_outputs))
                for index, display in enumerate(display_outputs):
                    self.assertEqual(tx_hash, display.get("generated_tx_hash"))
                    self.assertEqual(index, int(display["cell_index"]))


if __name__ == "__main__":
    unittest.main()
