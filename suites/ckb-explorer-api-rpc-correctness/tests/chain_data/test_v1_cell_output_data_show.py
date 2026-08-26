from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings
from tests.chain_data.test_v1_cell_input_lock_scripts_show import _explorer_response
from tests.chain_data.test_v1_cell_output_lock_scripts_show import (
    CELL_OUTPUT_NOT_FOUND_ERROR,
    INVALID_PARAMETER_ERROR,
    OutputFixture,
)


MAXIMUM_DOWNLOADABLE_SIZE = 64000


@dataclass(frozen=True)
class OutputDataNetworkFixture:
    nonempty: OutputFixture
    empty: OutputFixture
    dead_nonempty: OutputFixture
    dead_consuming_transaction_hash: str


OUTPUT_DATA_FIXTURES = {
    "mainnet": OutputDataNetworkFixture(
        nonempty=OutputFixture(
            transaction_hash="0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7",
            cell_output_id=132446500,
            rpc_output_index=0,
        ),
        empty=OutputFixture(
            transaction_hash="0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7",
            cell_output_id=132446501,
            rpc_output_index=1,
        ),
        dead_nonempty=OutputFixture(
            transaction_hash="0x9cdda31eb12bc63d0acbf833dc955ef1440feef8b054076518d62d0fa328c8c6",
            cell_output_id=132446485,
            rpc_output_index=0,
        ),
        dead_consuming_transaction_hash=(
            "0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7"
        ),
    ),
    "testnet": OutputDataNetworkFixture(
        nonempty=OutputFixture(
            transaction_hash="0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def",
            cell_output_id=207995367,
            rpc_output_index=0,
        ),
        empty=OutputFixture(
            transaction_hash="0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def",
            cell_output_id=207995368,
            rpc_output_index=1,
        ),
        dead_nonempty=OutputFixture(
            transaction_hash="0x3fda77f50756a1db12282d6a08eec6a9da16f09e53795b28e248a11764fcb102",
            cell_output_id=207995362,
            rpc_output_index=0,
        ),
        dead_consuming_transaction_hash=(
            "0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def"
        ),
    ),
}


# Add an immutable public fixture here once a same-network Explorer ID and RPC
# out-point at the exact boundary is confirmed. An empty map means the oracle is
# explicitly unavailable rather than silently substituting a smaller sample.
EXACT_LIMIT_FIXTURES: dict[str, OutputFixture] = {}
OVER_LIMIT_FIXTURES: dict[str, OutputFixture] = {}


OUTPUT_DATA_TOO_LARGE_ERROR = [
    {
        "title": "Output Data is Too Large",
        "detail": "You can download output data up to 64 KB",
        "code": 1022,
        "status": 400,
    }
]


class V1CellOutputDataShowRpcCorrectnessTests(unittest.TestCase):
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
        outputs_data = transaction.get("outputs_data")
        self.assertIsInstance(rpc_genesis_header, dict)
        self.assertIsInstance(block_transactions, list)
        self.assertIsInstance(outputs, list)
        self.assertIsInstance(outputs_data, list)
        self.assertEqual(len(outputs), len(outputs_data))
        self.assertEqual(rpc_genesis_header.get("hash"), api_genesis.get("block_hash"))
        self.assertLessEqual(api_tip, rpc_tip)
        self.assertLessEqual(rpc_tip - api_tip, oracle.settings.max_lag_blocks)
        self.assertEqual("committed", status.get("status"))
        self.assertEqual(fixture.transaction_hash, transaction.get("hash"))
        tx_index = decode_hex_int(status.get("tx_index"), "tx_status.tx_index")
        self.assertEqual(fixture.transaction_hash, block_transactions[tx_index].get("hash"))
        self.assertLess(fixture.rpc_output_index, len(outputs_data))

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

    def _data_response(
        self,
        oracle: NetworkOracle,
        cell_output_id: int | str,
    ) -> tuple[int, Any]:
        try:
            return _explorer_response(oracle, f"/v1/cell_output_data/{cell_output_id}")
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error

    def _data_value(
        self,
        oracle: NetworkOracle,
        cell_output_id: int | str,
    ) -> tuple[str, str]:
        status, payload = self._data_response(oracle, cell_output_id)
        context = (
            f"{oracle.network.name} id={cell_output_id} status={status} body={payload!r}"
        )
        self.assertEqual(200, status, context)
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        self.assertIsInstance(attributes, dict, context)
        resource_id = data.get("id") if isinstance(data, dict) else None
        value = attributes.get("data")
        self.assertIsNotNone(resource_id, context)
        self.assertIsInstance(value, str, context)
        return str(resource_id), value

    def _rpc_data(
        self,
        fixture: OutputFixture,
        transaction: Mapping[str, Any],
    ) -> str:
        outputs_data = transaction.get("outputs_data")
        self.assertIsInstance(outputs_data, list)
        expected = outputs_data[fixture.rpc_output_index]
        self.assertIsInstance(expected, str)
        self.assertTrue(expected.startswith("0x"))
        return expected

    def _assert_data_matches_rpc(
        self,
        network: str,
        fixture: OutputFixture,
        transaction: Mapping[str, Any],
        resource_id: str,
        actual: str,
    ) -> str:
        expected = self._rpc_data(fixture, transaction)
        context = (
            f"{network} id={fixture.cell_output_id} tx={fixture.transaction_hash} "
            f"rpc_output={fixture.rpc_output_index}"
        )
        self.assertEqual(str(fixture.cell_output_id), resource_id, context)
        self.assertEqual(expected, actual, context)
        return expected

    # TEST-MAP: CELL-CONTENT-RPC-11
    def test_nonempty_output_data_matches_rpc_bytes(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = OUTPUT_DATA_FIXTURES[network.name].nonempty
                transaction, status, _display_output = self._load_output_sample(oracle, fixture)
                resource_id, actual = self._data_value(oracle, fixture.cell_output_id)
                expected = self._assert_data_matches_rpc(
                    network.name,
                    fixture,
                    transaction,
                    resource_id,
                    actual,
                )
                size = len(bytes.fromhex(expected[2:]))
                self.assertGreater(size, 0)
                self.assertLessEqual(size, MAXIMUM_DOWNLOADABLE_SIZE)
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-12
    def test_empty_output_data_is_exactly_0x(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = OUTPUT_DATA_FIXTURES[network.name].empty
                transaction, status, _display_output = self._load_output_sample(oracle, fixture)
                resource_id, actual = self._data_value(oracle, fixture.cell_output_id)
                expected = self._assert_data_matches_rpc(
                    network.name,
                    fixture,
                    transaction,
                    resource_id,
                    actual,
                )
                self.assertEqual("0x", expected)
                self.assertEqual("0x", actual)
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-13
    def test_exactly_64000_byte_output_data_is_downloadable_when_public_fixture_exists(self) -> None:
        settings = self._settings()
        exercised = False

        for network in settings.networks:
            fixture = EXACT_LIMIT_FIXTURES.get(network.name)
            if fixture is None:
                continue
            exercised = True
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                transaction, status, _display_output = self._load_output_sample(oracle, fixture)
                expected = self._rpc_data(fixture, transaction)
                self.assertEqual(MAXIMUM_DOWNLOADABLE_SIZE, len(bytes.fromhex(expected[2:])))
                resource_id, actual = self._data_value(oracle, fixture.cell_output_id)
                self._assert_data_matches_rpc(
                    network.name,
                    fixture,
                    transaction,
                    resource_id,
                    actual,
                )
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)

        if not exercised:
            self.skipTest("no confirmed public output fixture has exactly 64000 data bytes")

    # TEST-MAP: CELL-CONTENT-RPC-14
    def test_over_64000_byte_output_data_returns_the_exact_size_error_when_fixture_exists(self) -> None:
        settings = self._settings()
        exercised = False

        for network in settings.networks:
            fixture = OVER_LIMIT_FIXTURES.get(network.name)
            if fixture is None:
                continue
            exercised = True
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                transaction, status, _display_output = self._load_output_sample(oracle, fixture)
                expected = self._rpc_data(fixture, transaction)
                self.assertGreater(len(bytes.fromhex(expected[2:])), MAXIMUM_DOWNLOADABLE_SIZE)
                actual_status, body = self._data_response(oracle, fixture.cell_output_id)
                context = (
                    f"{network.name} id={fixture.cell_output_id} "
                    f"status={actual_status} body={body!r}"
                )
                self.assertEqual(400, actual_status, context)
                self.assertEqual(OUTPUT_DATA_TOO_LARGE_ERROR, body, context)
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)

        if not exercised:
            self.skipTest("no confirmed public output fixture has more than 64000 data bytes")

    # TEST-MAP: CELL-CONTENT-RPC-29
    def test_two_different_outputs_return_their_own_rpc_data(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = OUTPUT_DATA_FIXTURES[network.name]
                transaction, status, _display_output = self._load_output_sample(
                    oracle,
                    fixture.nonempty,
                )
                self.assertEqual(
                    fixture.nonempty.transaction_hash,
                    fixture.empty.transaction_hash,
                )
                values = []
                for output in (fixture.nonempty, fixture.empty):
                    resource_id, actual = self._data_value(oracle, output.cell_output_id)
                    expected = self._assert_data_matches_rpc(
                        network.name,
                        output,
                        transaction,
                        resource_id,
                        actual,
                    )
                    self.assertLessEqual(
                        len(bytes.fromhex(expected[2:])),
                        MAXIMUM_DOWNLOADABLE_SIZE,
                    )
                    values.append(expected)
                self.assertNotEqual(values[0], values[1])
                self._assert_sample_stable(oracle, fixture.nonempty.transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-37
    def test_consumed_output_retains_its_original_rpc_data(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                network_fixture = OUTPUT_DATA_FIXTURES[network.name]
                fixture = network_fixture.dead_nonempty
                transaction, status, display_output = self._load_output_sample(oracle, fixture)
                self.assertEqual("dead", display_output.get("status"))
                self.assertEqual(
                    network_fixture.dead_consuming_transaction_hash,
                    display_output.get("consumed_tx_hash"),
                )
                resource_id, actual = self._data_value(oracle, fixture.cell_output_id)
                expected = self._assert_data_matches_rpc(
                    network.name,
                    fixture,
                    transaction,
                    resource_id,
                    actual,
                )
                self.assertLessEqual(
                    len(bytes.fromhex(expected[2:])),
                    MAXIMUM_DOWNLOADABLE_SIZE,
                )
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)

    # TEST-MAP: CELL-CONTENT-RPC-30
    def test_non_integer_id_returns_the_exact_parameter_error(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                invalid_id = "not-an-integer"
                status, body = self._data_response(oracle, invalid_id)
                context = f"{network.name} id={invalid_id} status={status} body={body!r}"
                self.assertEqual(422, status, context)
                self.assertEqual(INVALID_PARAMETER_ERROR, body, context)

    # TEST-MAP: CELL-CONTENT-RPC-31
    def test_nonexistent_integer_id_returns_the_exact_not_found_error(self) -> None:
        settings = self._settings()
        nonexistent_id = 2**63 - 1

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                status, body = self._data_response(oracle, nonexistent_id)
                context = f"{network.name} id={nonexistent_id} status={status} body={body!r}"
                self.assertEqual(404, status, context)
                self.assertEqual(CELL_OUTPUT_NOT_FOUND_ERROR, body, context)

    # TEST-MAP: CELL-CONTENT-RPC-40
    def test_numeric_id_with_format_suffix_returns_the_same_rpc_data(self) -> None:
        settings = self._settings()

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture = OUTPUT_DATA_FIXTURES[network.name].nonempty
                transaction, status, _display_output = self._load_output_sample(oracle, fixture)
                plain_id, plain = self._data_value(oracle, fixture.cell_output_id)
                dotted_id = f"{fixture.cell_output_id}.5"
                dotted_resource_id, dotted = self._data_value(oracle, dotted_id)
                expected = self._assert_data_matches_rpc(
                    network.name,
                    fixture,
                    transaction,
                    dotted_resource_id,
                    dotted,
                )
                self.assertEqual(str(fixture.cell_output_id), plain_id)
                self.assertEqual(expected, plain)
                self.assertEqual(plain, dotted)
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)


if __name__ == "__main__":
    unittest.main()
