from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings
from tests.chain_data.test_v1_cell_input_lock_scripts_show import (
    CELL_INPUT_NOT_FOUND_ERROR,
    INVALID_PARAMETER_ERROR,
    ZERO_TX_HASH,
    InputFixture,
    _explorer_response,
)


# Input Type Script fixtures and cases.
@dataclass(frozen=True)
class InputTypeNetworkFixture:
    ordinary_transaction_hash: str
    typed_input: InputFixture
    untyped_input: InputFixture
    cellbase_transaction_hash: str
    cellbase_input_id: int
    distinct_transaction_hash: str
    distinct_inputs: tuple[InputFixture, InputFixture]


INPUT_TYPE_FIXTURES = {
    "mainnet": InputTypeNetworkFixture(
        ordinary_transaction_hash="0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7",
        typed_input=InputFixture(134597081, 0),
        untyped_input=InputFixture(134597082, 1),
        cellbase_transaction_hash="0xae1fa53d770c7571de66c7373528508c4591edca36f7e870c307cd1f88d7e3a4",
        cellbase_input_id=134597074,
        distinct_transaction_hash="0xe1b0ec7221982187b016e96d5be4bc17b4c3ed1f876cd05f8bbac435d3d2da47",
        distinct_inputs=(InputFixture(134597109, 0), InputFixture(134597110, 1)),
    ),
    "testnet": InputTypeNetworkFixture(
        ordinary_transaction_hash="0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def",
        typed_input=InputFixture(230328823, 0),
        untyped_input=InputFixture(230328824, 1),
        cellbase_transaction_hash="0xa3ca91e5368fafec9c61ac3c94152436cb3e8329af078a3ceee66bbd63af8016",
        cellbase_input_id=230328817,
        distinct_transaction_hash="0xdc9fccde85974e00e547d503aeeee9d9bfd96b8b15cbaa3f6e034583f819b0a6",
        distinct_inputs=(InputFixture(230328826, 0), InputFixture(230328827, 1)),
    ),
}


class V1CellInputTypeScriptsShowRpcCorrectnessTests(unittest.TestCase):
    def _settings(self):
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")
        return settings

    def _load_committed_sample(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
    ) -> tuple[Mapping[str, Any], list[tuple[Mapping[str, Any], object]], Mapping[str, Any]]:
        try:
            api_genesis = oracle.detail_attributes(0)
            rpc_genesis = oracle.block(0)
            api_tip = oracle.api_tip_height()
            rpc_tip = oracle.rpc_tip_height()
            rpc_result = oracle.rpc_result("get_transaction", [transaction_hash])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error

        transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
        status = rpc_result.get("tx_status") if isinstance(rpc_result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise unittest.SkipTest(f"{oracle.network.name} RPC transaction {transaction_hash} is unavailable")
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
        self.assertEqual(len(transaction.get("inputs", [])), len(referenced_outputs))
        tx_index = decode_hex_int(status.get("tx_index"), "tx_status.tx_index")
        self.assertEqual(transaction_hash, block_transactions[tx_index].get("hash"))
        return transaction, referenced_outputs, status

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

    def _type_attributes(self, oracle: NetworkOracle, cell_input_id: int | str) -> Mapping[str, Any]:
        try:
            status, payload = _explorer_response(
                oracle,
                f"/v1/cell_input_type_scripts/{cell_input_id}",
            )
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        context = f"{oracle.network.name} id={cell_input_id} status={status} body={payload!r}"
        self.assertEqual(200, status, context)
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        self.assertIsInstance(attributes, dict, context)
        return attributes

    def _assert_type_matches_rpc(
        self,
        network: str,
        transaction_hash: str,
        input_fixture: InputFixture,
        transaction: Mapping[str, Any],
        referenced_outputs: list[tuple[Mapping[str, Any], object]],
        actual: Mapping[str, Any],
    ) -> tuple[str, str, str, str]:
        inputs = transaction.get("inputs")
        self.assertIsInstance(inputs, list)
        rpc_input = inputs[input_fixture.rpc_input_index]
        previous = rpc_input.get("previous_output") if isinstance(rpc_input, dict) else None
        self.assertIsInstance(previous, dict)
        expected_output = referenced_outputs[input_fixture.rpc_input_index][0]
        expected_type = expected_output.get("type")
        self.assertIsInstance(expected_type, dict)
        out_point = (
            f"{previous.get('tx_hash')}:"
            f"{decode_hex_int(previous.get('index'), 'previous_output.index')}"
        )

        for field in ("code_hash", "hash_type", "args"):
            message = (
                f"{network} id={input_fixture.cell_input_id} consuming_tx={transaction_hash} "
                f"rpc_input={input_fixture.rpc_input_index} previous_output={out_point} "
                f"field=data.attributes.{field} api={actual.get(field)!r} rpc={expected_type.get(field)!r}"
            )
            self.assertEqual(expected_type.get(field), actual.get(field), message)
        expected_hash = ckb_script_hash(expected_type)
        self.assertEqual(
            expected_hash,
            actual.get("script_hash"),
            f"{network} id={input_fixture.cell_input_id} previous_output={out_point} field=script_hash",
        )
        return tuple(
            str(value)
            for value in (
                expected_type["code_hash"],
                expected_type["hash_type"],
                expected_type["args"],
                expected_hash,
            )
        )

    def _display_input_id(
        self,
        oracle: NetworkOracle,
        transaction: Mapping[str, Any],
        transaction_hash: str,
        rpc_input_index: int,
    ) -> int:
        try:
            status, payload = _explorer_response(
                oracle,
                f"/v1/transactions/{transaction_hash}",
            )
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        context = f"{oracle.network.name} tx={transaction_hash} status={status} body={payload!r}"
        self.assertEqual(200, status, context)
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        display_inputs = (
            attributes.get("display_inputs") if isinstance(attributes, dict) else None
        )
        inputs = transaction.get("inputs")
        self.assertIsInstance(display_inputs, list, context)
        self.assertIsInstance(inputs, list, context)
        self.assertLess(rpc_input_index, len(display_inputs), context)
        display_input = display_inputs[rpc_input_index]
        rpc_input = inputs[rpc_input_index]
        self.assertIsInstance(display_input, dict, context)
        self.assertIsInstance(rpc_input, dict, context)
        previous = rpc_input.get("previous_output")
        self.assertIsInstance(previous, dict, context)
        self.assertEqual(previous.get("tx_hash"), display_input.get("generated_tx_hash"), context)
        self.assertEqual(
            decode_hex_int(previous.get("index"), "previous_output.index"),
            int(display_input.get("cell_index")),
            context,
        )
        display_id = display_input.get("id")
        self.assertIsNotNone(display_id, context)
        return int(display_id)

    # TEST-MAP: CELL-CONTENT-RPC-01
    def test_public_display_input_id_binds_to_the_same_rpc_type_when_supported(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_TYPE_FIXTURES[network.name]
                transaction, referenced_outputs, status = self._load_committed_sample(
                    oracle,
                    fixture.ordinary_transaction_hash,
                )
                display_id = self._display_input_id(
                    oracle,
                    transaction,
                    fixture.ordinary_transaction_hash,
                    fixture.typed_input.rpc_input_index,
                )
                try:
                    actual_status, payload = _explorer_response(
                        oracle,
                        f"/v1/cell_input_type_scripts/{display_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                data = payload.get("data") if isinstance(payload, dict) else None
                actual = data.get("attributes") if isinstance(data, dict) else None
                expected_output = referenced_outputs[fixture.typed_input.rpc_input_index][0]
                expected_type = expected_output.get("type")
                expected_hash = (
                    ckb_script_hash(expected_type) if isinstance(expected_type, dict) else None
                )
                fields_match = (
                    isinstance(actual, dict)
                    and isinstance(expected_type, dict)
                    and all(
                        actual.get(field) == expected_type.get(field)
                        for field in ("code_hash", "hash_type", "args")
                    )
                    and actual.get("script_hash") == expected_hash
                )
                if actual_status != 200 or not fields_match:
                    raise unittest.SkipTest(
                        f"{network.name} transaction display input id={display_id} does not bind "
                        "to the same Input Type Script; public CellInput ID binding is unavailable"
                    )
                self._assert_sample_stable(
                    oracle,
                    fixture.ordinary_transaction_hash,
                    status,
                )

    # TEST-MAP: CELL-CONTENT-RPC-03
    def test_typed_input_matches_rpc_type_script_and_computed_script_hash(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_TYPE_FIXTURES[network.name]
                transaction, referenced_outputs, status = self._load_committed_sample(
                    oracle,
                    fixture.ordinary_transaction_hash,
                )
                actual = self._type_attributes(oracle, fixture.typed_input.cell_input_id)

                self._assert_type_matches_rpc(
                    network.name,
                    fixture.ordinary_transaction_hash,
                    fixture.typed_input,
                    transaction,
                    referenced_outputs,
                    actual,
                )
                self._assert_sample_stable(oracle, fixture.ordinary_transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-04
    def test_untyped_input_returns_json_api_null(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_TYPE_FIXTURES[network.name]
                _transaction, referenced_outputs, status = self._load_committed_sample(
                    oracle,
                    fixture.ordinary_transaction_hash,
                )
                expected_output = referenced_outputs[fixture.untyped_input.rpc_input_index][0]
                self.assertIsNone(expected_output.get("type"))
                try:
                    actual_status, body = _explorer_response(
                        oracle,
                        f"/v1/cell_input_type_scripts/{fixture.untyped_input.cell_input_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                context = (
                    f"{network.name} id={fixture.untyped_input.cell_input_id} "
                    f"status={actual_status} body={body!r}"
                )
                self.assertEqual(200, actual_status, context)
                self.assertEqual({"data": None}, body, context)
                self._assert_sample_stable(oracle, fixture.ordinary_transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-07
    def test_real_cellbase_input_returns_the_exact_not_found_error(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_TYPE_FIXTURES[network.name]
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
                        f"/v1/cell_input_type_scripts/{fixture.cellbase_input_id}",
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

    # TEST-MAP: CELL-CONTENT-RPC-16
    def test_two_distinct_typed_inputs_return_their_own_rpc_type_scripts(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_TYPE_FIXTURES[network.name]
                transaction, referenced_outputs, status = self._load_committed_sample(
                    oracle,
                    fixture.distinct_transaction_hash,
                )
                expected_types = []
                for input_fixture in fixture.distinct_inputs:
                    actual = self._type_attributes(oracle, input_fixture.cell_input_id)
                    expected_types.append(
                        self._assert_type_matches_rpc(
                            network.name,
                            fixture.distinct_transaction_hash,
                            input_fixture,
                            transaction,
                            referenced_outputs,
                            actual,
                        )
                    )

                self.assertNotEqual(expected_types[0], expected_types[1])
                self._assert_sample_stable(oracle, fixture.distinct_transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-17
    def test_non_integer_id_returns_the_exact_parameter_error(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                invalid_id = "not-an-integer"
                try:
                    status, body = _explorer_response(
                        oracle,
                        f"/v1/cell_input_type_scripts/{invalid_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                context = f"{network.name} id={invalid_id} status={status} body={body!r}"
                self.assertEqual(422, status, context)
                self.assertEqual(INVALID_PARAMETER_ERROR, body, context)

    # TEST-MAP: CELL-CONTENT-RPC-18
    def test_nonexistent_integer_id_returns_the_exact_not_found_error(self) -> None:
        settings = self._settings()
        nonexistent_id = 2**63 - 1

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    status, body = _explorer_response(
                        oracle,
                        f"/v1/cell_input_type_scripts/{nonexistent_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                context = f"{network.name} id={nonexistent_id} status={status} body={body!r}"
                self.assertEqual(404, status, context)
                self.assertEqual(CELL_INPUT_NOT_FOUND_ERROR, body, context)

    # TEST-MAP: CELL-CONTENT-RPC-32
    def test_numeric_id_with_format_suffix_returns_the_same_rpc_type_script(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_TYPE_FIXTURES[network.name]
                transaction, referenced_outputs, status = self._load_committed_sample(
                    oracle,
                    fixture.ordinary_transaction_hash,
                )
                plain = self._type_attributes(oracle, fixture.typed_input.cell_input_id)
                dotted_id = f"{fixture.typed_input.cell_input_id}.5"
                dotted = self._type_attributes(oracle, dotted_id)

                self._assert_type_matches_rpc(
                    network.name,
                    fixture.ordinary_transaction_hash,
                    fixture.typed_input,
                    transaction,
                    referenced_outputs,
                    dotted,
                )
                for field in ("code_hash", "hash_type", "args", "script_hash"):
                    self.assertEqual(
                        plain.get(field),
                        dotted.get(field),
                        f"{network.name} id={dotted_id} field=data.attributes.{field}",
                    )
                self._assert_sample_stable(oracle, fixture.ordinary_transaction_hash, status)



if __name__ == "__main__":
    unittest.main()
