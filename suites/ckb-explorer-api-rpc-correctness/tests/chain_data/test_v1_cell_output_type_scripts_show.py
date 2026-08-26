from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings
from tests.chain_data.test_v1_cell_input_lock_scripts_show import _explorer_response
from tests.chain_data.test_v1_cell_output_lock_scripts_show import (
    CELL_OUTPUT_NOT_FOUND_ERROR,
    INVALID_PARAMETER_ERROR,
    OutputFixture,
)


@dataclass(frozen=True)
class OutputTypeNetworkFixture:
    typed: OutputFixture
    untyped: OutputFixture
    dead_typed: OutputFixture
    dead_consuming_transaction_hash: str


OUTPUT_TYPE_FIXTURES = {
    "mainnet": OutputTypeNetworkFixture(
        typed=OutputFixture(
            transaction_hash="0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7",
            cell_output_id=132446500,
            rpc_output_index=0,
        ),
        untyped=OutputFixture(
            transaction_hash="0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7",
            cell_output_id=132446501,
            rpc_output_index=1,
        ),
        dead_typed=OutputFixture(
            transaction_hash="0x9cdda31eb12bc63d0acbf833dc955ef1440feef8b054076518d62d0fa328c8c6",
            cell_output_id=132446485,
            rpc_output_index=0,
        ),
        dead_consuming_transaction_hash=(
            "0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7"
        ),
    ),
    "testnet": OutputTypeNetworkFixture(
        typed=OutputFixture(
            transaction_hash="0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def",
            cell_output_id=207995367,
            rpc_output_index=0,
        ),
        untyped=OutputFixture(
            transaction_hash="0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def",
            cell_output_id=207995368,
            rpc_output_index=1,
        ),
        dead_typed=OutputFixture(
            transaction_hash="0x3fda77f50756a1db12282d6a08eec6a9da16f09e53795b28e248a11764fcb102",
            cell_output_id=207995362,
            rpc_output_index=0,
        ),
        dead_consuming_transaction_hash=(
            "0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def"
        ),
    ),
}


class V1CellOutputTypeScriptsShowRpcCorrectnessTests(unittest.TestCase):
    def _settings(self):
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")
        return settings

    def _load_output_sample(
        self,
        oracle: NetworkOracle,
        fixture: OutputFixture,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
        try:
            api_genesis = oracle.detail_attributes(0)
            rpc_genesis = oracle.block(0)
            api_tip = oracle.api_tip_height()
            rpc_tip = oracle.rpc_tip_height()
            rpc_result = oracle.rpc_result("get_transaction", [fixture.transaction_hash])
            detail_status, detail_payload = _explorer_response(
                oracle,
                f"/v1/transactions/{fixture.transaction_hash}",
            )
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error

        transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
        status = rpc_result.get("tx_status") if isinstance(rpc_result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC transaction {fixture.transaction_hash} is unavailable"
            )
        block_hash = status.get("block_hash")
        if not isinstance(block_hash, str):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC transaction {fixture.transaction_hash} has no block hash"
            )
        try:
            block = oracle.block_by_hash(block_hash)
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error

        rpc_genesis_header = rpc_genesis.get("header")
        block_transactions = block.get("transactions")
        outputs = transaction.get("outputs")
        self.assertIsInstance(rpc_genesis_header, dict)
        self.assertIsInstance(block_transactions, list)
        self.assertIsInstance(outputs, list)
        self.assertEqual(rpc_genesis_header.get("hash"), api_genesis.get("block_hash"))
        self.assertLessEqual(api_tip, rpc_tip)
        self.assertLessEqual(rpc_tip - api_tip, oracle.settings.max_lag_blocks)
        self.assertEqual("committed", status.get("status"))
        self.assertEqual(fixture.transaction_hash, transaction.get("hash"))
        tx_index = decode_hex_int(status.get("tx_index"), "tx_status.tx_index")
        self.assertEqual(fixture.transaction_hash, block_transactions[tx_index].get("hash"))
        self.assertLess(fixture.rpc_output_index, len(outputs))

        context = (
            f"{oracle.network.name} tx={fixture.transaction_hash} "
            f"id={fixture.cell_output_id} rpc_output={fixture.rpc_output_index}"
        )
        self.assertEqual(200, detail_status, context)
        detail_data = detail_payload.get("data") if isinstance(detail_payload, dict) else None
        detail_attributes = (
            detail_data.get("attributes") if isinstance(detail_data, dict) else None
        )
        display_outputs = (
            detail_attributes.get("display_outputs")
            if isinstance(detail_attributes, dict)
            else None
        )
        self.assertIsInstance(display_outputs, list, context)
        self.assertLess(fixture.rpc_output_index, len(display_outputs), context)
        display_output = display_outputs[fixture.rpc_output_index]
        self.assertIsInstance(display_output, dict, context)
        self.assertEqual(str(fixture.cell_output_id), str(display_output.get("id")), context)
        self.assertEqual(fixture.transaction_hash, display_output.get("generated_tx_hash"), context)
        self.assertEqual(
            fixture.rpc_output_index,
            int(display_output.get("cell_index")),
            context,
        )
        return transaction, status, display_output

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

    def _type_response(
        self,
        oracle: NetworkOracle,
        cell_output_id: int | str,
    ) -> tuple[int, Any]:
        try:
            return _explorer_response(
                oracle,
                f"/v1/cell_output_type_scripts/{cell_output_id}",
            )
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error

    def _type_attributes(
        self,
        oracle: NetworkOracle,
        cell_output_id: int | str,
    ) -> Mapping[str, Any]:
        status, payload = self._type_response(oracle, cell_output_id)
        context = (
            f"{oracle.network.name} id={cell_output_id} status={status} body={payload!r}"
        )
        self.assertEqual(200, status, context)
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        self.assertIsInstance(attributes, dict, context)
        return attributes

    def _assert_type_matches_rpc(
        self,
        network: str,
        fixture: OutputFixture,
        transaction: Mapping[str, Any],
        actual: Mapping[str, Any],
    ) -> tuple[str, str, str, str]:
        outputs = transaction.get("outputs")
        self.assertIsInstance(outputs, list)
        rpc_output = outputs[fixture.rpc_output_index]
        self.assertIsInstance(rpc_output, dict)
        expected_type = rpc_output.get("type")
        self.assertIsInstance(expected_type, dict)

        for field in ("code_hash", "hash_type", "args"):
            message = (
                f"{network} id={fixture.cell_output_id} tx={fixture.transaction_hash} "
                f"rpc_output={fixture.rpc_output_index} field=data.attributes.{field} "
                f"api={actual.get(field)!r} rpc={expected_type.get(field)!r}"
            )
            self.assertEqual(expected_type.get(field), actual.get(field), message)
        expected_hash = ckb_script_hash(expected_type)
        self.assertEqual(
            expected_hash,
            actual.get("script_hash"),
            f"{network} id={fixture.cell_output_id} field=data.attributes.script_hash",
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

    # TEST-MAP: CELL-CONTENT-RPC-09
    def test_typed_output_matches_rpc_type_script_and_computed_hash(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = OUTPUT_TYPE_FIXTURES[network.name].typed
                transaction, status, _display_output = self._load_output_sample(oracle, fixture)
                actual = self._type_attributes(oracle, fixture.cell_output_id)
                self._assert_type_matches_rpc(network.name, fixture, transaction, actual)
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-10
    def test_untyped_output_returns_json_api_null(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = OUTPUT_TYPE_FIXTURES[network.name].untyped
                transaction, status, _display_output = self._load_output_sample(oracle, fixture)
                outputs = transaction.get("outputs")
                self.assertIsInstance(outputs, list)
                self.assertIsNone(outputs[fixture.rpc_output_index].get("type"))
                actual_status, body = self._type_response(oracle, fixture.cell_output_id)
                context = (
                    f"{network.name} id={fixture.cell_output_id} "
                    f"status={actual_status} body={body!r}"
                )
                self.assertEqual(200, actual_status, context)
                self.assertEqual({"data": None}, body, context)
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-26
    def test_typed_and_untyped_outputs_remain_bound_to_their_own_indexes(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = OUTPUT_TYPE_FIXTURES[network.name]
                transaction, status, _display_output = self._load_output_sample(
                    oracle,
                    fixture.typed,
                )
                self.assertEqual(
                    fixture.typed.transaction_hash,
                    fixture.untyped.transaction_hash,
                )
                typed = self._type_attributes(oracle, fixture.typed.cell_output_id)
                self._assert_type_matches_rpc(network.name, fixture.typed, transaction, typed)
                untyped_status, untyped_body = self._type_response(
                    oracle,
                    fixture.untyped.cell_output_id,
                )
                context = (
                    f"{network.name} id={fixture.untyped.cell_output_id} "
                    f"status={untyped_status} body={untyped_body!r}"
                )
                self.assertEqual(200, untyped_status, context)
                self.assertEqual({"data": None}, untyped_body, context)
                self._assert_sample_stable(oracle, fixture.typed.transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-36
    def test_consumed_output_retains_its_original_rpc_type_script(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                network_fixture = OUTPUT_TYPE_FIXTURES[network.name]
                fixture = network_fixture.dead_typed
                transaction, status, display_output = self._load_output_sample(oracle, fixture)
                self.assertEqual("dead", display_output.get("status"))
                self.assertEqual(
                    network_fixture.dead_consuming_transaction_hash,
                    display_output.get("consumed_tx_hash"),
                )
                actual = self._type_attributes(oracle, fixture.cell_output_id)
                self._assert_type_matches_rpc(network.name, fixture, transaction, actual)
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-27
    def test_non_integer_id_returns_the_exact_parameter_error(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                invalid_id = "not-an-integer"
                status, body = self._type_response(oracle, invalid_id)
                context = f"{network.name} id={invalid_id} status={status} body={body!r}"
                self.assertEqual(422, status, context)
                self.assertEqual(INVALID_PARAMETER_ERROR, body, context)

    # TEST-MAP: CELL-CONTENT-RPC-28
    def test_nonexistent_integer_id_returns_the_exact_not_found_error(self) -> None:
        settings = self._settings()
        nonexistent_id = 2**63 - 1

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                status, body = self._type_response(oracle, nonexistent_id)
                context = f"{network.name} id={nonexistent_id} status={status} body={body!r}"
                self.assertEqual(404, status, context)
                self.assertEqual(CELL_OUTPUT_NOT_FOUND_ERROR, body, context)

    # TEST-MAP: CELL-CONTENT-RPC-39
    def test_numeric_id_with_format_suffix_returns_the_same_rpc_type_script(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = OUTPUT_TYPE_FIXTURES[network.name].typed
                transaction, status, _display_output = self._load_output_sample(oracle, fixture)
                plain = self._type_attributes(oracle, fixture.cell_output_id)
                dotted_id = f"{fixture.cell_output_id}.5"
                dotted = self._type_attributes(oracle, dotted_id)
                self._assert_type_matches_rpc(network.name, fixture, transaction, dotted)
                for field in ("code_hash", "hash_type", "args", "script_hash"):
                    self.assertEqual(
                        plain.get(field),
                        dotted.get(field),
                        f"{network.name} id={dotted_id} field=data.attributes.{field}",
                    )
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)


if __name__ == "__main__":
    unittest.main()
