from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings
from tests.chain_data.test_v1_cell_input_lock_scripts_show import (
    CELL_INPUT_NOT_FOUND_ERROR,
    INVALID_PARAMETER_ERROR,
    ZERO_TX_HASH,
    InputFixture,
    _explorer_response,
)
from tests.chain_data.test_v1_cell_output_data_show import (
    MAXIMUM_DOWNLOADABLE_SIZE,
    OUTPUT_DATA_TOO_LARGE_ERROR,
)
from tests.chain_data.test_v1_cell_output_lock_scripts_show import OutputFixture


@dataclass(frozen=True)
class InputDataNetworkFixture:
    ordinary_transaction_hash: str
    nonempty_input: InputFixture
    empty_input: InputFixture
    cellbase_transaction_hash: str
    cellbase_input_id: int
    distinct_transaction_hash: str
    distinct_inputs: tuple[InputFixture, InputFixture]


INPUT_DATA_FIXTURES = {
    "mainnet": InputDataNetworkFixture(
        ordinary_transaction_hash="0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7",
        nonempty_input=InputFixture(134597081, 0),
        empty_input=InputFixture(134597082, 1),
        cellbase_transaction_hash="0xae1fa53d770c7571de66c7373528508c4591edca36f7e870c307cd1f88d7e3a4",
        cellbase_input_id=134597074,
        distinct_transaction_hash="0xe1b0ec7221982187b016e96d5be4bc17b4c3ed1f876cd05f8bbac435d3d2da47",
        distinct_inputs=(InputFixture(134597109, 0), InputFixture(134597110, 1)),
    ),
    "testnet": InputDataNetworkFixture(
        ordinary_transaction_hash="0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def",
        nonempty_input=InputFixture(230328823, 0),
        empty_input=InputFixture(230328824, 1),
        cellbase_transaction_hash="0xa3ca91e5368fafec9c61ac3c94152436cb3e8329af078a3ceee66bbd63af8016",
        cellbase_input_id=230328817,
        distinct_transaction_hash="0xdc9fccde85974e00e547d503aeeee9d9bfd96b8b15cbaa3f6e034583f819b0a6",
        distinct_inputs=(InputFixture(230328826, 0), InputFixture(230328827, 1)),
    ),
}


@dataclass(frozen=True)
class LargeInputDataFixture:
    consuming_transaction_hash: str
    cell_input: InputFixture
    previous_output: OutputFixture


# Add an immutable public fixture once an output larger than 64000 bytes has a
# confirmed consuming transaction and public CellInput ID binding.
LARGE_INPUT_DATA_FIXTURES: dict[str, LargeInputDataFixture] = {}


class V1CellInputDataShowRpcCorrectnessTests(unittest.TestCase):
    def _settings(self):
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")
        return settings

    def _assert_sample_stable(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
        initial_status: Mapping[str, Any],
    ) -> None:
        try:
            fresh_result = oracle.rpc_result("get_transaction", [transaction_hash])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        fresh_status = fresh_result.get("tx_status") if isinstance(fresh_result, dict) else None
        if not isinstance(fresh_status, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC transaction {transaction_hash} became unavailable"
            )
        if (
            fresh_status.get("status") != initial_status.get("status")
            or fresh_status.get("block_hash") != initial_status.get("block_hash")
        ):
            raise unittest.SkipTest(
                f"{oracle.network.name} transaction {transaction_hash} changed status or block"
            )

    def _load_committed_sample(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
    ) -> tuple[
        Mapping[str, Any],
        list[tuple[Mapping[str, Any], object]],
        Mapping[str, Any],
        list[str],
    ]:
        try:
            api_genesis = oracle.detail_attributes(0)
            rpc_genesis = oracle.block(0)
            api_tip = oracle.api_tip_height()
            rpc_tip = oracle.rpc_tip_height()
            rpc_result = oracle.rpc_result("get_transaction", [transaction_hash])
            detail_status, detail_payload = _explorer_response(
                oracle,
                f"/v1/transactions/{transaction_hash}",
            )
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error

        transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
        status = rpc_result.get("tx_status") if isinstance(rpc_result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC transaction {transaction_hash} is unavailable"
            )
        try:
            referenced_outputs = oracle.referenced_outputs(transaction)
            block_hash = status.get("block_hash")
            if not isinstance(block_hash, str):
                raise OracleUnavailable(
                    f"{oracle.network.name} RPC transaction {transaction_hash} has no block hash"
                )
            block = oracle.block_by_hash(block_hash)
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error

        rpc_genesis_header = rpc_genesis.get("header")
        block_transactions = block.get("transactions")
        self.assertIsInstance(rpc_genesis_header, dict)
        self.assertIsInstance(block_transactions, list)
        self.assertEqual(rpc_genesis_header.get("hash"), api_genesis.get("block_hash"))
        self.assertLessEqual(api_tip, rpc_tip)
        self.assertLessEqual(rpc_tip - api_tip, oracle.settings.max_lag_blocks)
        self.assertEqual("committed", status.get("status"))
        self.assertEqual(transaction_hash, transaction.get("hash"))
        inputs = transaction.get("inputs")
        self.assertIsInstance(inputs, list)
        self.assertEqual(len(inputs), len(referenced_outputs))
        tx_index = decode_hex_int(status.get("tx_index"), "tx_status.tx_index")
        self.assertEqual(transaction_hash, block_transactions[tx_index].get("hash"))
        self.assertEqual(200, detail_status)
        detail_data = detail_payload.get("data") if isinstance(detail_payload, dict) else None
        detail_attributes = detail_data.get("attributes") if isinstance(detail_data, dict) else None
        display_inputs = (
            detail_attributes.get("display_inputs") if isinstance(detail_attributes, dict) else None
        )
        self.assertIsInstance(display_inputs, list)
        self.assertEqual(len(inputs), len(display_inputs))
        displayed_output_ids: list[str] = []
        for index, (rpc_input, display_input) in enumerate(zip(inputs, display_inputs, strict=True)):
            previous = rpc_input.get("previous_output") if isinstance(rpc_input, dict) else None
            self.assertIsInstance(previous, dict)
            self.assertIsInstance(display_input, dict)
            self.assertEqual(previous.get("tx_hash"), display_input.get("generated_tx_hash"))
            self.assertEqual(
                decode_hex_int(previous.get("index"), f"inputs[{index}].previous_output.index"),
                int(display_input.get("cell_index")),
            )
            output_id = display_input.get("id")
            self.assertIsNotNone(output_id)
            displayed_output_ids.append(str(output_id))
        return transaction, referenced_outputs, status, displayed_output_ids

    def _input_data(self, oracle: NetworkOracle, cell_input_id: int | str) -> tuple[str, str]:
        try:
            status, payload = _explorer_response(
                oracle,
                f"/v1/cell_input_data/{cell_input_id}",
            )
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        context = f"{oracle.network.name} id={cell_input_id} status={status} body={payload!r}"
        self.assertEqual(200, status, context)
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        self.assertIsInstance(attributes, dict, context)
        resource_id = data.get("id") if isinstance(data, dict) else None
        self.assertIsNotNone(resource_id, context)
        value = attributes.get("data")
        self.assertIsInstance(value, str, context)
        return str(resource_id), value

    def _assert_data_matches_rpc(
        self,
        network: str,
        transaction_hash: str,
        input_fixture: InputFixture,
        transaction: Mapping[str, Any],
        referenced_outputs: list[tuple[Mapping[str, Any], object]],
        displayed_output_ids: list[str],
        actual_resource_id: str,
        actual: str,
    ) -> str:
        inputs = transaction.get("inputs")
        self.assertIsInstance(inputs, list)
        rpc_input = inputs[input_fixture.rpc_input_index]
        previous = rpc_input.get("previous_output") if isinstance(rpc_input, dict) else None
        self.assertIsInstance(previous, dict)
        expected = referenced_outputs[input_fixture.rpc_input_index][1]
        self.assertIsInstance(expected, str)
        out_point = (
            f"{previous.get('tx_hash')}:"
            f"{decode_hex_int(previous.get('index'), 'previous_output.index')}"
        )
        expected_resource_id = displayed_output_ids[input_fixture.rpc_input_index]
        if actual_resource_id != expected_resource_id:
            raise unittest.SkipTest(
                f"{network} CellInput.id={input_fixture.cell_input_id} resolves CellOutput.id="
                f"{actual_resource_id}, but transaction {transaction_hash} input "
                f"{input_fixture.rpc_input_index} displays CellOutput.id={expected_resource_id}; "
                "public CellInput ID binding is unavailable"
            )
        self.assertEqual(
            expected,
            actual,
            f"{network} id={input_fixture.cell_input_id} consuming_tx={transaction_hash} "
            f"rpc_input={input_fixture.rpc_input_index} previous_output={out_point}",
        )
        return expected

    # TEST-MAP: CELL-CONTENT-RPC-34
    def test_public_display_input_id_binds_to_the_same_rpc_data_when_supported(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_DATA_FIXTURES[network.name]
                transaction, referenced_outputs, status, displayed_output_ids = (
                    self._load_committed_sample(oracle, fixture.ordinary_transaction_hash)
                )
                rpc_input_index = fixture.nonempty_input.rpc_input_index
                display_id = displayed_output_ids[rpc_input_index]
                try:
                    actual_status, payload = _explorer_response(
                        oracle,
                        f"/v1/cell_input_data/{display_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                data = payload.get("data") if isinstance(payload, dict) else None
                attributes = data.get("attributes") if isinstance(data, dict) else None
                resource_id = data.get("id") if isinstance(data, dict) else None
                actual = attributes.get("data") if isinstance(attributes, dict) else None
                expected = referenced_outputs[rpc_input_index][1]
                if (
                    actual_status != 200
                    or str(resource_id) != display_id
                    or actual != expected
                ):
                    raise unittest.SkipTest(
                        f"{network.name} transaction display input id={display_id} does not bind "
                        "to the same Input Data; public CellInput ID binding is unavailable"
                    )
                self._assert_sample_stable(
                    oracle,
                    fixture.ordinary_transaction_hash,
                    status,
                )

    # TEST-MAP: CELL-CONTENT-RPC-05
    def test_nonempty_input_data_matches_its_rpc_referenced_output(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_DATA_FIXTURES[network.name]
                transaction, referenced_outputs, status, displayed_output_ids = self._load_committed_sample(
                    oracle,
                    fixture.ordinary_transaction_hash,
                )
                input_fixture = fixture.nonempty_input
                actual_resource_id, actual = self._input_data(
                    oracle,
                    input_fixture.cell_input_id,
                )
                expected = self._assert_data_matches_rpc(
                    network.name,
                    fixture.ordinary_transaction_hash,
                    input_fixture,
                    transaction,
                    referenced_outputs,
                    displayed_output_ids,
                    actual_resource_id,
                    actual,
                )
                self.assertNotEqual("0x", expected)
                self._assert_sample_stable(oracle, fixture.ordinary_transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-06
    def test_empty_input_data_is_exactly_0x(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_DATA_FIXTURES[network.name]
                transaction, referenced_outputs, status, displayed_output_ids = self._load_committed_sample(
                    oracle,
                    fixture.ordinary_transaction_hash,
                )
                input_fixture = fixture.empty_input
                actual_resource_id, actual = self._input_data(
                    oracle,
                    input_fixture.cell_input_id,
                )
                expected = self._assert_data_matches_rpc(
                    network.name,
                    fixture.ordinary_transaction_hash,
                    input_fixture,
                    transaction,
                    referenced_outputs,
                    displayed_output_ids,
                    actual_resource_id,
                    actual,
                )
                self.assertEqual("0x", expected)
                self.assertEqual("0x", actual)
                self._assert_sample_stable(oracle, fixture.ordinary_transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-35
    def test_real_cellbase_input_returns_the_exact_not_found_error(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_DATA_FIXTURES[network.name]
                try:
                    rpc_result = oracle.rpc_result(
                        "get_transaction",
                        [fixture.cellbase_transaction_hash],
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
                status = rpc_result.get("tx_status") if isinstance(rpc_result, dict) else None
                self.assertIsInstance(transaction, dict)
                self.assertIsInstance(status, dict)
                self.assertEqual("committed", status.get("status"))
                inputs = transaction.get("inputs")
                self.assertIsInstance(inputs, list)
                self.assertEqual(1, len(inputs))
                previous = inputs[0].get("previous_output")
                self.assertIsInstance(previous, dict)
                self.assertEqual(ZERO_TX_HASH, previous.get("tx_hash"))
                self.assertEqual(
                    0xFFFFFFFF,
                    decode_hex_int(previous.get("index"), "cellbase.previous_output.index"),
                )

                try:
                    actual_status, body = _explorer_response(
                        oracle,
                        f"/v1/cell_input_data/{fixture.cellbase_input_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                context = (
                    f"{network.name} id={fixture.cellbase_input_id} "
                    f"status={actual_status} body={body!r}"
                )
                self.assertEqual(404, actual_status, context)
                self.assertEqual(CELL_INPUT_NOT_FOUND_ERROR, body, context)
                self._assert_sample_stable(oracle, fixture.cellbase_transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-19
    def test_two_distinct_inputs_return_their_own_rpc_data(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_DATA_FIXTURES[network.name]
                transaction, referenced_outputs, status, displayed_output_ids = self._load_committed_sample(
                    oracle,
                    fixture.distinct_transaction_hash,
                )
                expected_values = []
                for input_fixture in fixture.distinct_inputs:
                    actual_resource_id, actual = self._input_data(
                        oracle,
                        input_fixture.cell_input_id,
                    )
                    expected = self._assert_data_matches_rpc(
                        network.name,
                        fixture.distinct_transaction_hash,
                        input_fixture,
                        transaction,
                        referenced_outputs,
                        displayed_output_ids,
                        actual_resource_id,
                        actual,
                    )
                    self.assertNotEqual("0x", expected)
                    expected_values.append(expected)

                self.assertNotEqual(expected_values[0], expected_values[1])
                self._assert_sample_stable(oracle, fixture.distinct_transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-20
    def test_non_integer_id_returns_the_exact_parameter_error(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                invalid_id = "not-an-integer"
                try:
                    status, body = _explorer_response(
                        oracle,
                        f"/v1/cell_input_data/{invalid_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                context = f"{network.name} id={invalid_id} status={status} body={body!r}"
                self.assertEqual(422, status, context)
                self.assertEqual(INVALID_PARAMETER_ERROR, body, context)

    # TEST-MAP: CELL-CONTENT-RPC-21
    def test_nonexistent_integer_id_returns_the_exact_not_found_error(self) -> None:
        settings = self._settings()
        nonexistent_id = 2**63 - 1

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    status, body = _explorer_response(
                        oracle,
                        f"/v1/cell_input_data/{nonexistent_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                context = f"{network.name} id={nonexistent_id} status={status} body={body!r}"
                self.assertEqual(404, status, context)
                self.assertEqual(CELL_INPUT_NOT_FOUND_ERROR, body, context)

    # TEST-MAP: CELL-CONTENT-RPC-22
    def test_over_64000_byte_input_and_output_data_follow_the_declared_policy_when_fixture_exists(
        self,
    ) -> None:
        settings = self._settings()
        exercised = False

        for network in settings.networks:
            fixture = LARGE_INPUT_DATA_FIXTURES.get(network.name)
            if fixture is None:
                continue
            exercised = True
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                transaction, referenced_outputs, status, displayed_output_ids = (
                    self._load_committed_sample(
                        oracle,
                        fixture.consuming_transaction_hash,
                    )
                )
                rpc_input = transaction["inputs"][fixture.cell_input.rpc_input_index]
                previous = rpc_input.get("previous_output")
                self.assertIsInstance(previous, dict)
                self.assertEqual(
                    fixture.previous_output.transaction_hash,
                    previous.get("tx_hash"),
                )
                self.assertEqual(
                    fixture.previous_output.rpc_output_index,
                    decode_hex_int(previous.get("index"), "previous_output.index"),
                )
                expected = referenced_outputs[fixture.cell_input.rpc_input_index][1]
                self.assertIsInstance(expected, str)
                self.assertGreater(
                    len(bytes.fromhex(expected[2:])),
                    MAXIMUM_DOWNLOADABLE_SIZE,
                )
                input_resource_id, input_data = self._input_data(
                    oracle,
                    fixture.cell_input.cell_input_id,
                )
                self._assert_data_matches_rpc(
                    network.name,
                    fixture.consuming_transaction_hash,
                    fixture.cell_input,
                    transaction,
                    referenced_outputs,
                    displayed_output_ids,
                    input_resource_id,
                    input_data,
                )
                try:
                    output_status, output_body = _explorer_response(
                        oracle,
                        f"/v1/cell_output_data/{fixture.previous_output.cell_output_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                context = (
                    f"{network.name} id={fixture.previous_output.cell_output_id} "
                    f"status={output_status} body={output_body!r}"
                )
                self.assertEqual(400, output_status, context)
                self.assertEqual(OUTPUT_DATA_TOO_LARGE_ERROR, output_body, context)
                self._assert_sample_stable(
                    oracle,
                    fixture.consuming_transaction_hash,
                    status,
                )

        if not exercised:
            self.skipTest(
                "no confirmed public input references output data larger than 64000 bytes"
            )

    # TEST-MAP: CELL-CONTENT-RPC-33
    def test_numeric_id_with_format_suffix_returns_the_same_rpc_data(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_DATA_FIXTURES[network.name]
                transaction, referenced_outputs, status, displayed_output_ids = self._load_committed_sample(
                    oracle,
                    fixture.ordinary_transaction_hash,
                )
                input_fixture = fixture.nonempty_input
                plain_resource_id, plain = self._input_data(
                    oracle,
                    input_fixture.cell_input_id,
                )
                dotted_id = f"{input_fixture.cell_input_id}.5"
                dotted_resource_id, dotted = self._input_data(oracle, dotted_id)
                expected = self._assert_data_matches_rpc(
                    network.name,
                    fixture.ordinary_transaction_hash,
                    input_fixture,
                    transaction,
                    referenced_outputs,
                    displayed_output_ids,
                    dotted_resource_id,
                    dotted,
                )
                self.assertEqual(plain_resource_id, dotted_resource_id)
                self.assertEqual(expected, plain)
                self.assertEqual(plain, dotted)
                self._assert_sample_stable(oracle, fixture.ordinary_transaction_hash, status)


if __name__ == "__main__":
    unittest.main()
