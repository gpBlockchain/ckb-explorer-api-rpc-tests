from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings
from tests.chain_data.test_v1_cell_input_lock_scripts_show import (
    ZERO_TX_HASH,
    _explorer_response,
)


@dataclass(frozen=True)
class OutputFixture:
    transaction_hash: str
    cell_output_id: int
    rpc_output_index: int


@dataclass(frozen=True)
class OutputLockNetworkFixture:
    ordinary: OutputFixture
    dead: OutputFixture
    dead_consuming_transaction_hash: str
    cellbase: OutputFixture


OUTPUT_LOCK_FIXTURES = {
    "mainnet": OutputLockNetworkFixture(
        ordinary=OutputFixture(
            transaction_hash="0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7",
            cell_output_id=132446501,
            rpc_output_index=1,
        ),
        dead=OutputFixture(
            transaction_hash="0x9cdda31eb12bc63d0acbf833dc955ef1440feef8b054076518d62d0fa328c8c6",
            cell_output_id=132446485,
            rpc_output_index=0,
        ),
        dead_consuming_transaction_hash=(
            "0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7"
        ),
        cellbase=OutputFixture(
            transaction_hash="0xae1fa53d770c7571de66c7373528508c4591edca36f7e870c307cd1f88d7e3a4",
            cell_output_id=132446493,
            rpc_output_index=0,
        ),
    ),
    "testnet": OutputLockNetworkFixture(
        ordinary=OutputFixture(
            transaction_hash="0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def",
            cell_output_id=207995368,
            rpc_output_index=1,
        ),
        dead=OutputFixture(
            transaction_hash="0x3fda77f50756a1db12282d6a08eec6a9da16f09e53795b28e248a11764fcb102",
            cell_output_id=207995362,
            rpc_output_index=0,
        ),
        dead_consuming_transaction_hash=(
            "0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def"
        ),
        cellbase=OutputFixture(
            transaction_hash="0xa3ca91e5368fafec9c61ac3c94152436cb3e8329af078a3ceee66bbd63af8016",
            cell_output_id=207995403,
            rpc_output_index=0,
        ),
    ),
}


INVALID_PARAMETER_ERROR = [
    {
        "title": "URI parameters is invalid",
        "detail": "URI parameters should be a integer",
        "code": 1015,
        "status": 422,
    }
]
CELL_OUTPUT_NOT_FOUND_ERROR = [
    {
        "title": "Cell Output Not Found",
        "detail": "No cell output records found by given id",
        "code": 1016,
        "status": 404,
    }
]


class V1CellOutputLockScriptsShowRpcCorrectnessTests(unittest.TestCase):
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

    def _lock_attributes(
        self,
        oracle: NetworkOracle,
        cell_output_id: int | str,
    ) -> Mapping[str, Any]:
        try:
            status, payload = _explorer_response(
                oracle,
                f"/v1/cell_output_lock_scripts/{cell_output_id}",
            )
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        context = (
            f"{oracle.network.name} id={cell_output_id} status={status} body={payload!r}"
        )
        self.assertEqual(200, status, context)
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        self.assertIsInstance(attributes, dict, context)
        return attributes

    def _assert_lock_matches_rpc(
        self,
        network: str,
        fixture: OutputFixture,
        transaction: Mapping[str, Any],
        actual: Mapping[str, Any],
    ) -> tuple[str, str, str]:
        outputs = transaction.get("outputs")
        self.assertIsInstance(outputs, list)
        rpc_output = outputs[fixture.rpc_output_index]
        self.assertIsInstance(rpc_output, dict)
        expected_lock = rpc_output.get("lock")
        self.assertIsInstance(expected_lock, dict)

        for field in ("code_hash", "hash_type", "args"):
            message = (
                f"{network} id={fixture.cell_output_id} tx={fixture.transaction_hash} "
                f"rpc_output={fixture.rpc_output_index} field=data.attributes.{field} "
                f"api={actual.get(field)!r} rpc={expected_lock.get(field)!r}"
            )
            self.assertEqual(expected_lock.get(field), actual.get(field), message)
        return tuple(str(expected_lock[field]) for field in ("code_hash", "hash_type", "args"))

    # TEST-MAP: CELL-CONTENT-RPC-08
    def test_nonzero_output_returns_its_own_rpc_lock_script(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = OUTPUT_LOCK_FIXTURES[network.name].ordinary
                transaction, status, _display_output = self._load_output_sample(oracle, fixture)
                outputs = transaction.get("outputs")
                self.assertIsInstance(outputs, list)
                self.assertGreaterEqual(len(outputs), 2)
                self.assertGreater(fixture.rpc_output_index, 0)
                first_lock = outputs[0].get("lock") if isinstance(outputs[0], dict) else None
                selected_output = outputs[fixture.rpc_output_index]
                selected_lock = (
                    selected_output.get("lock") if isinstance(selected_output, dict) else None
                )
                self.assertIsInstance(first_lock, dict)
                self.assertIsInstance(selected_lock, dict)
                self.assertNotEqual(first_lock, selected_lock)

                actual = self._lock_attributes(oracle, fixture.cell_output_id)
                self._assert_lock_matches_rpc(network.name, fixture, transaction, actual)
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-15
    def test_consumed_output_retains_its_original_rpc_lock_script(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                network_fixture = OUTPUT_LOCK_FIXTURES[network.name]
                fixture = network_fixture.dead
                transaction, status, display_output = self._load_output_sample(oracle, fixture)
                self.assertEqual("dead", display_output.get("status"))
                self.assertEqual(
                    network_fixture.dead_consuming_transaction_hash,
                    display_output.get("consumed_tx_hash"),
                )

                actual = self._lock_attributes(oracle, fixture.cell_output_id)
                self._assert_lock_matches_rpc(network.name, fixture, transaction, actual)
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-23
    def test_non_integer_id_returns_the_exact_parameter_error(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                invalid_id = "not-an-integer"
                try:
                    status, body = _explorer_response(
                        oracle,
                        f"/v1/cell_output_lock_scripts/{invalid_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                context = f"{network.name} id={invalid_id} status={status} body={body!r}"
                self.assertEqual(422, status, context)
                self.assertEqual(INVALID_PARAMETER_ERROR, body, context)

    # TEST-MAP: CELL-CONTENT-RPC-24
    def test_nonexistent_integer_id_returns_the_exact_not_found_error(self) -> None:
        settings = self._settings()
        nonexistent_id = 2**63 - 1

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    status, body = _explorer_response(
                        oracle,
                        f"/v1/cell_output_lock_scripts/{nonexistent_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                context = f"{network.name} id={nonexistent_id} status={status} body={body!r}"
                self.assertEqual(404, status, context)
                self.assertEqual(CELL_OUTPUT_NOT_FOUND_ERROR, body, context)

    # TEST-MAP: CELL-CONTENT-RPC-25
    def test_cellbase_output_matches_its_rpc_lock_script(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = OUTPUT_LOCK_FIXTURES[network.name].cellbase
                transaction, status, _display_output = self._load_output_sample(oracle, fixture)
                self.assertEqual(0, decode_hex_int(status.get("tx_index"), "cellbase.tx_index"))
                inputs = transaction.get("inputs")
                self.assertIsInstance(inputs, list)
                self.assertEqual(1, len(inputs))
                previous_output = inputs[0].get("previous_output")
                self.assertIsInstance(previous_output, dict)
                self.assertEqual(ZERO_TX_HASH, previous_output.get("tx_hash"))
                self.assertEqual(
                    0xFFFFFFFF,
                    decode_hex_int(previous_output.get("index"), "cellbase.previous_output.index"),
                )

                actual = self._lock_attributes(oracle, fixture.cell_output_id)
                self._assert_lock_matches_rpc(network.name, fixture, transaction, actual)
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-38
    def test_numeric_id_with_format_suffix_returns_the_same_rpc_lock_script(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = OUTPUT_LOCK_FIXTURES[network.name].ordinary
                transaction, status, _display_output = self._load_output_sample(oracle, fixture)
                plain = self._lock_attributes(oracle, fixture.cell_output_id)
                dotted_id = f"{fixture.cell_output_id}.5"
                dotted = self._lock_attributes(oracle, dotted_id)

                self._assert_lock_matches_rpc(network.name, fixture, transaction, dotted)
                for field in ("code_hash", "hash_type", "args"):
                    self.assertEqual(
                        plain.get(field),
                        dotted.get(field),
                        f"{network.name} id={dotted_id} field=data.attributes.{field}",
                    )
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)


if __name__ == "__main__":
    unittest.main()
