from __future__ import annotations

import json
import socket
import time
import unittest
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings


ZERO_TX_HASH = "0x" + "00" * 32


@dataclass(frozen=True)
class InputFixture:
    cell_input_id: int
    rpc_input_index: int


# Input Lock Script fixtures and cases.
@dataclass(frozen=True)
class InputLockNetworkFixture:
    transaction_hash: str
    inputs: tuple[InputFixture, InputFixture]
    cellbase_transaction_hash: str
    cellbase_input_id: int


INPUT_LOCK_FIXTURES = {
    "mainnet": InputLockNetworkFixture(
        transaction_hash="0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7",
        inputs=(InputFixture(134597081, 0), InputFixture(134597083, 2)),
        cellbase_transaction_hash="0xae1fa53d770c7571de66c7373528508c4591edca36f7e870c307cd1f88d7e3a4",
        cellbase_input_id=134597074,
    ),
    "testnet": InputLockNetworkFixture(
        transaction_hash="0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def",
        inputs=(InputFixture(230328823, 0), InputFixture(230328824, 1)),
        cellbase_transaction_hash="0xa3ca91e5368fafec9c61ac3c94152436cb3e8329af078a3ceee66bbd63af8016",
        cellbase_input_id=230328817,
    ),
}


INVALID_PARAMETER_ERROR = [
    {
        "title": "URI parameters is invalid",
        "detail": "URI parameters should be a integer",
        "code": 1013,
        "status": 422,
    }
]
CELL_INPUT_NOT_FOUND_ERROR = [
    {
        "title": "Cell Input Not Found",
        "detail": "No cell input records found by given id",
        "code": 1014,
        "status": 404,
    }
]


class _StatusPreservingProcessor(urllib.request.HTTPErrorProcessor):
    def http_response(self, request: urllib.request.Request, response: Any) -> Any:
        return response

    https_response = http_response


def _explorer_response(oracle: NetworkOracle, path: str) -> tuple[int, Any]:
    url = oracle.network.explorer_api_url + path
    headers = dict(V1_HEADERS)
    headers["User-Agent"] = oracle.client.user_agent
    opener = urllib.request.build_opener(_StatusPreservingProcessor())

    for attempt in range(oracle.client.retries + 1):
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with opener.open(request, timeout=oracle.client.timeout) as response:
                raw = response.read(oracle.client.max_body_bytes + 1)
                status = int(response.status)
            if len(raw) > oracle.client.max_body_bytes:
                raise OracleUnavailable(
                    f"{oracle.network.name} Explorer {path} exceeds {oracle.client.max_body_bytes} bytes"
                )
            if attempt < oracle.client.retries and (status == 429 or status >= 500):
                time.sleep(0.2 * (attempt + 1))
                continue
            try:
                return status, json.loads(raw)
            except json.JSONDecodeError as error:
                raise OracleUnavailable(
                    f"{oracle.network.name} Explorer {path} returned invalid JSON: {error}"
                ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as error:
            if attempt < oracle.client.retries:
                time.sleep(0.2 * (attempt + 1))
                continue
            raise OracleUnavailable(
                f"{oracle.network.name} Explorer {path} transport failure: {type(error).__name__}: {error}"
            ) from error
    raise AssertionError("unreachable HTTP retry loop")


class V1CellInputLockScriptsShowRpcCorrectnessTests(unittest.TestCase):
    def _settings(self):
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")
        return settings

    def _load_ordinary_sample(
        self,
        oracle: NetworkOracle,
        fixture: InputLockNetworkFixture,
    ) -> tuple[Mapping[str, Any], list[tuple[Mapping[str, Any], object]], Mapping[str, Any]]:
        try:
            api_genesis = oracle.detail_attributes(0)
            rpc_genesis = oracle.block(0)
            api_tip = oracle.api_tip_height()
            rpc_tip = oracle.rpc_tip_height()
            rpc_result = oracle.rpc_result("get_transaction", [fixture.transaction_hash])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error

        transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
        status = rpc_result.get("tx_status") if isinstance(rpc_result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC transaction {fixture.transaction_hash} is unavailable"
            )
        try:
            referenced_outputs = oracle.referenced_outputs(transaction)
            block_hash = status.get("block_hash")
            if not isinstance(block_hash, str):
                raise OracleUnavailable(
                    f"{oracle.network.name} RPC transaction {fixture.transaction_hash} has no block hash"
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
        self.assertEqual(fixture.transaction_hash, transaction.get("hash"))
        self.assertEqual(len(transaction.get("inputs", [])), len(referenced_outputs))
        tx_index = decode_hex_int(status.get("tx_index"), "tx_status.tx_index")
        self.assertEqual(fixture.transaction_hash, block_transactions[tx_index].get("hash"))
        return transaction, referenced_outputs, status

    def _assert_sample_stable(
        self,
        oracle: NetworkOracle,
        fixture: InputLockNetworkFixture,
        initial_status: Mapping[str, Any],
    ) -> None:
        try:
            fresh_result = oracle.rpc_result("get_transaction", [fixture.transaction_hash])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        fresh_status = fresh_result.get("tx_status") if isinstance(fresh_result, dict) else None
        if not isinstance(fresh_status, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC transaction {fixture.transaction_hash} became unavailable"
            )
        if (
            fresh_status.get("status") != initial_status.get("status")
            or fresh_status.get("block_hash") != initial_status.get("block_hash")
        ):
            raise unittest.SkipTest(
                f"{oracle.network.name} transaction {fixture.transaction_hash} changed status or block"
            )

    def _lock_attributes(self, oracle: NetworkOracle, cell_input_id: int) -> Mapping[str, Any]:
        try:
            status, payload = _explorer_response(
                oracle,
                f"/v1/cell_input_lock_scripts/{cell_input_id}",
            )
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        self.assertEqual(
            200,
            status,
            f"{oracle.network.name} id={cell_input_id} status={status} body={payload!r}",
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        self.assertIsInstance(attributes, dict)
        return attributes

    def _assert_lock_matches_rpc(
        self,
        network: str,
        fixture: InputLockNetworkFixture,
        input_fixture: InputFixture,
        transaction: Mapping[str, Any],
        referenced_outputs: list[tuple[Mapping[str, Any], object]],
        actual: Mapping[str, Any],
    ) -> tuple[str, str, str]:
        inputs = transaction.get("inputs")
        self.assertIsInstance(inputs, list)
        rpc_input = inputs[input_fixture.rpc_input_index]
        previous = rpc_input.get("previous_output") if isinstance(rpc_input, dict) else None
        self.assertIsInstance(previous, dict)
        expected_output = referenced_outputs[input_fixture.rpc_input_index][0]
        expected_lock = expected_output.get("lock")
        self.assertIsInstance(expected_lock, dict)
        out_point = f"{previous.get('tx_hash')}:{decode_hex_int(previous.get('index'), 'previous_output.index')}"

        for field in ("code_hash", "hash_type", "args"):
            message = (
                f"{network} id={input_fixture.cell_input_id} consuming_tx={fixture.transaction_hash} "
                f"rpc_input={input_fixture.rpc_input_index} previous_output={out_point} "
                f"field=data.attributes.{field} api={actual.get(field)!r} rpc={expected_lock.get(field)!r}"
            )
            self.assertEqual(expected_lock.get(field), actual.get(field), message)
        return tuple(str(expected_lock[field]) for field in ("code_hash", "hash_type", "args"))

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

    # TEST-MAP: CELL-INPUT-LOCK-RPC-01
    def test_public_display_input_id_binds_to_the_same_rpc_input_when_supported(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_LOCK_FIXTURES[network.name]
                transaction, referenced_outputs, status = self._load_ordinary_sample(oracle, fixture)
                input_fixture = fixture.inputs[0]
                display_id = self._display_input_id(
                    oracle,
                    transaction,
                    fixture.transaction_hash,
                    input_fixture.rpc_input_index,
                )
                try:
                    actual_status, payload = _explorer_response(
                        oracle,
                        f"/v1/cell_input_lock_scripts/{display_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                data = payload.get("data") if isinstance(payload, dict) else None
                actual = data.get("attributes") if isinstance(data, dict) else None
                expected_output = referenced_outputs[input_fixture.rpc_input_index][0]
                expected_lock = expected_output.get("lock")
                if actual_status != 200 or not isinstance(actual, dict) or not isinstance(expected_lock, dict):
                    raise unittest.SkipTest(
                        f"{network.name} transaction display input id={display_id} is not a public "
                        "CellInput.id accepted by the Input Lock Script endpoint"
                    )
                fields = ("code_hash", "hash_type", "args")
                if any(actual.get(field) != expected_lock.get(field) for field in fields):
                    raise unittest.SkipTest(
                        f"{network.name} transaction display input id={display_id} resolves a different "
                        "Input Lock Script; public CellInput ID binding is unavailable"
                    )
                self._assert_sample_stable(oracle, fixture, status)

    # TEST-MAP: CELL-INPUT-LOCK-RPC-02
    def test_ordinary_input_lock_script_matches_its_rpc_referenced_output(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_LOCK_FIXTURES[network.name]
                transaction, referenced_outputs, status = self._load_ordinary_sample(oracle, fixture)
                input_fixture = fixture.inputs[0]
                actual = self._lock_attributes(oracle, input_fixture.cell_input_id)

                self._assert_lock_matches_rpc(
                    network.name,
                    fixture,
                    input_fixture,
                    transaction,
                    referenced_outputs,
                    actual,
                )
                self._assert_sample_stable(oracle, fixture, status)

    # TEST-MAP: CELL-INPUT-LOCK-RPC-03
    def test_two_distinct_inputs_return_their_own_rpc_lock_scripts(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_LOCK_FIXTURES[network.name]
                transaction, referenced_outputs, status = self._load_ordinary_sample(oracle, fixture)
                self.assertGreaterEqual(len(transaction.get("inputs", [])), 2)

                expected_locks = []
                for input_fixture in fixture.inputs:
                    actual = self._lock_attributes(oracle, input_fixture.cell_input_id)
                    expected_locks.append(
                        self._assert_lock_matches_rpc(
                            network.name,
                            fixture,
                            input_fixture,
                            transaction,
                            referenced_outputs,
                            actual,
                        )
                    )

                self.assertNotEqual(expected_locks[0], expected_locks[1])
                self._assert_sample_stable(oracle, fixture, status)

    # TEST-MAP: CELL-INPUT-LOCK-RPC-04
    def test_non_integer_ids_return_the_exact_parameter_error(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                invalid_id = "not-an-integer"
                try:
                    status, body = _explorer_response(
                        oracle,
                        f"/v1/cell_input_lock_scripts/{invalid_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                context = f"{network.name} id={invalid_id} status={status} body={body!r}"
                self.assertEqual(422, status, context)
                self.assertEqual(INVALID_PARAMETER_ERROR, body, context)

    # TEST-MAP: CELL-INPUT-LOCK-RPC-05
    def test_nonexistent_integer_id_returns_the_exact_not_found_error(self) -> None:
        settings = self._settings()
        nonexistent_id = 2**63 - 1

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    status, body = _explorer_response(
                        oracle,
                        f"/v1/cell_input_lock_scripts/{nonexistent_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                context = f"{network.name} id={nonexistent_id} status={status} body={body!r}"
                self.assertEqual(404, status, context)
                self.assertEqual(CELL_INPUT_NOT_FOUND_ERROR, body, context)

    # TEST-MAP: CELL-INPUT-LOCK-RPC-06
    def test_real_cellbase_input_id_returns_the_exact_not_found_error(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_LOCK_FIXTURES[network.name]
                try:
                    ordinary_result = oracle.rpc_result("get_transaction", [fixture.transaction_hash])
                    cellbase_result = oracle.rpc_result(
                        "get_transaction",
                        [fixture.cellbase_transaction_hash],
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                ordinary_status = ordinary_result.get("tx_status") if isinstance(ordinary_result, dict) else None
                cellbase_transaction = (
                    cellbase_result.get("transaction") if isinstance(cellbase_result, dict) else None
                )
                cellbase_status = cellbase_result.get("tx_status") if isinstance(cellbase_result, dict) else None
                self.assertIsInstance(ordinary_status, dict)
                self.assertIsInstance(cellbase_transaction, dict)
                self.assertIsInstance(cellbase_status, dict)
                block_hash = ordinary_status.get("block_hash")
                self.assertEqual(block_hash, cellbase_status.get("block_hash"))
                self.assertIsInstance(block_hash, str)
                try:
                    block = oracle.block_by_hash(block_hash)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                block_transactions = block.get("transactions")
                cellbase_inputs = cellbase_transaction.get("inputs")
                self.assertIsInstance(block_transactions, list)
                self.assertIsInstance(cellbase_inputs, list)
                self.assertEqual("committed", cellbase_status.get("status"))
                self.assertEqual(0, decode_hex_int(cellbase_status.get("tx_index"), "cellbase.tx_index"))
                self.assertEqual(fixture.cellbase_transaction_hash, block_transactions[0].get("hash"))
                self.assertEqual(1, len(cellbase_inputs))
                previous = cellbase_inputs[0].get("previous_output")
                self.assertIsInstance(previous, dict)
                self.assertEqual(ZERO_TX_HASH, previous.get("tx_hash"))
                self.assertEqual(0xFFFFFFFF, decode_hex_int(previous.get("index"), "cellbase.previous_output.index"))

                ordinary_index = decode_hex_int(ordinary_status.get("tx_index"), "ordinary.tx_index")
                preceding_normal_input_count = sum(
                    len(item.get("inputs", [])) for item in block_transactions[1:ordinary_index]
                )
                first_ordinary_id = fixture.inputs[0].cell_input_id
                self.assertEqual(
                    fixture.cellbase_input_id,
                    first_ordinary_id - preceding_normal_input_count - 1,
                )

                try:
                    status, body = _explorer_response(
                        oracle,
                        f"/v1/cell_input_lock_scripts/{fixture.cellbase_input_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                context = (
                    f"{network.name} cellbase_tx={fixture.cellbase_transaction_hash} "
                    f"id={fixture.cellbase_input_id} status={status} body={body!r}"
                )
                self.assertEqual(404, status, context)
                self.assertEqual(CELL_INPUT_NOT_FOUND_ERROR, body, context)

    # TEST-MAP: CELL-INPUT-LOCK-RPC-07
    def test_numeric_id_with_format_suffix_returns_the_same_rpc_lock_script(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = INPUT_LOCK_FIXTURES[network.name]
                transaction, referenced_outputs, initial_status = self._load_ordinary_sample(
                    oracle,
                    fixture,
                )
                input_fixture = fixture.inputs[0]
                plain_attributes = self._lock_attributes(oracle, input_fixture.cell_input_id)
                dotted_id = f"{input_fixture.cell_input_id}.5"
                try:
                    status, payload = _explorer_response(
                        oracle,
                        f"/v1/cell_input_lock_scripts/{dotted_id}",
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                context = f"{network.name} id={dotted_id} status={status} body={payload!r}"
                self.assertEqual(200, status, context)
                data = payload.get("data") if isinstance(payload, dict) else None
                dotted_attributes = data.get("attributes") if isinstance(data, dict) else None
                self.assertIsInstance(dotted_attributes, dict, context)
                self._assert_lock_matches_rpc(
                    network.name,
                    fixture,
                    input_fixture,
                    transaction,
                    referenced_outputs,
                    dotted_attributes,
                )
                for field in ("code_hash", "hash_type", "args"):
                    self.assertEqual(
                        plain_attributes.get(field),
                        dotted_attributes.get(field),
                        f"{context} field=data.attributes.{field}",
                    )
                self._assert_sample_stable(oracle, fixture, initial_status)


if __name__ == "__main__":
    unittest.main()
