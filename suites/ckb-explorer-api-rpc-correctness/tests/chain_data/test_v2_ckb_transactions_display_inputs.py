from __future__ import annotations

import json
import re
import socket
import time
import unittest
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import (
    ckb_script_hash,
    decode_hex_int,
    output_address,
    output_occupied_capacity,
)
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings


ZERO_TX_HASH = "0x" + "00" * 32


@dataclass(frozen=True)
class UdtInputFixture:
    transaction_hash: str
    type_hash: str
    cell_type: str
    info_field: str


@dataclass(frozen=True)
class DisplayInputsNetworkFixture:
    ordinary_transaction_hash: str
    cellbase_transaction_hash: str
    udt_input: UdtInputFixture


DISPLAY_INPUTS_FIXTURES = {
    "mainnet": DisplayInputsNetworkFixture(
        ordinary_transaction_hash="0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7",
        cellbase_transaction_hash="0xae1fa53d770c7571de66c7373528508c4591edca36f7e870c307cd1f88d7e3a4",
        udt_input=UdtInputFixture(
            transaction_hash="0x2afff0376860381cab26f9ffdcce08f6eca0ce66d0e02643150e5960577a5f48",
            type_hash="0x59f9e9966f4b0e8578c1b73fb3eb06241607bff05e17d7869d4a17293303a27b",
            cell_type="xudt",
            info_field="xudt_info",
        ),
    ),
    "testnet": DisplayInputsNetworkFixture(
        ordinary_transaction_hash="0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def",
        cellbase_transaction_hash="0xa3ca91e5368fafec9c61ac3c94152436cb3e8329af078a3ceee66bbd63af8016",
        udt_input=UdtInputFixture(
            transaction_hash="0x3c57557ef883e1c2388678e6a284f1e221d9b4a7dfdd341729da147254ec5712",
            type_hash="0x3b6afac4101eea2e297c4270ab0e4e3cc0d3d9ab882025b2b0b9face48249204",
            cell_type="udt",
            info_field="udt_info",
        ),
    ),
}


class _StatusPreservingProcessor(urllib.request.HTTPErrorProcessor):
    def http_response(self, request: urllib.request.Request, response: Any) -> Any:
        return response

    https_response = http_response


def _explorer_response(oracle: NetworkOracle, path: str) -> tuple[int, Any, bytes]:
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
                    f"{oracle.network.name} Explorer {path} exceeds "
                    f"{oracle.client.max_body_bytes} bytes"
                )
            if attempt < oracle.client.retries and (status == 429 or status >= 500):
                time.sleep(0.2 * (attempt + 1))
                continue
            if not raw:
                return status, None, raw
            try:
                return status, json.loads(raw), raw
            except json.JSONDecodeError as error:
                raise OracleUnavailable(
                    f"{oracle.network.name} Explorer {path} returned invalid JSON: {error}"
                ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as error:
            if attempt < oracle.client.retries:
                time.sleep(0.2 * (attempt + 1))
                continue
            raise OracleUnavailable(
                f"{oracle.network.name} Explorer {path} transport failure: "
                f"{type(error).__name__}: {error}"
            ) from error
    raise AssertionError("unreachable HTTP retry loop")


class V2CkbTransactionsDisplayInputsRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.oracles = tuple(NetworkOracle(network, cls.settings) for network in cls.settings.networks)
        cls.samples: dict[tuple[str, str], tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
        cls.checked_networks: set[str] = set()

    def _assert_network_pair(self, oracle: NetworkOracle) -> None:
        if oracle.network.name in self.checked_networks:
            return
        try:
            api_genesis = oracle.detail_attributes(0)
            rpc_genesis = oracle.block(0)
            api_tip = oracle.api_tip_height()
            rpc_tip = oracle.rpc_tip_height()
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        rpc_header = rpc_genesis.get("header")
        self.assertIsInstance(rpc_header, dict)
        self.assertEqual(rpc_header.get("hash"), api_genesis.get("block_hash"))
        self.assertLessEqual(api_tip, rpc_tip)
        self.assertLessEqual(rpc_tip - api_tip, self.settings.max_lag_blocks)
        self.checked_networks.add(oracle.network.name)

    def _load_sample(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        key = (oracle.network.name, transaction_hash)
        if key in self.samples:
            return self.samples[key]
        self._assert_network_pair(oracle)
        try:
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
            block_hash = status.get("block_hash")
            if not isinstance(block_hash, str):
                raise OracleUnavailable(
                    f"{oracle.network.name} RPC transaction {transaction_hash} has no block hash"
                )
            block = oracle.block_by_hash(block_hash)
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        block_transactions = block.get("transactions")
        self.assertIsInstance(block_transactions, list)
        self.assertEqual("committed", status.get("status"))
        self.assertEqual(transaction_hash, transaction.get("hash"))
        tx_index = decode_hex_int(status.get("tx_index"), "tx_status.tx_index")
        self.assertEqual(transaction_hash, block_transactions[tx_index].get("hash"))
        self.samples[key] = transaction, status
        return self.samples[key]

    def _assert_sample_stable(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
        initial_status: Mapping[str, Any],
    ) -> None:
        try:
            result = oracle.rpc_result("get_transaction", [transaction_hash])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        status = result.get("tx_status") if isinstance(result, dict) else None
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

    def _display_inputs(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
        **query: object,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        try:
            payload = oracle.explorer_json(
                f"/v2/ckb_transactions/{transaction_hash}/display_inputs",
                query or None,
            )
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        context = f"{oracle.network.name} tx={transaction_hash} query={query} body={payload!r}"
        self.assertIsInstance(data, list, context)
        self.assertIsInstance(meta, dict, context)
        self.assertTrue(all(isinstance(row, dict) for row in data), context)
        return data, meta

    def _referenced_outputs(
        self,
        oracle: NetworkOracle,
        transaction: Mapping[str, Any],
    ) -> list[tuple[Mapping[str, Any], object]]:
        try:
            return oracle.referenced_outputs(transaction)
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error

    def _median_timestamp(
        self,
        oracle: NetworkOracle,
        status: Mapping[str, Any],
    ) -> int:
        block_hash = status.get("block_hash")
        self.assertIsInstance(block_hash, str)
        try:
            value = oracle.rpc_result("get_block_median_time", [block_hash])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        return decode_hex_int(value, "get_block_median_time.result")

    def _decimal_integer(self, value: object, field: str) -> int:
        try:
            decimal = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            self.fail(f"{field} is not a decimal number: {value!r}; {error}")
        self.assertTrue(decimal.is_finite(), f"{field} must be finite: {value!r}")
        self.assertEqual(decimal, decimal.to_integral_value(), f"{field} is not an integer")
        return int(decimal)

    def _assert_input_identity(
        self,
        oracle: NetworkOracle,
        input_index: int,
        rpc_input: Mapping[str, Any],
        previous_output: Mapping[str, Any],
        previous_data: object,
        actual: Mapping[str, Any],
        median_timestamp: int,
    ) -> None:
        previous = rpc_input.get("previous_output")
        self.assertIsInstance(previous, dict)
        previous_hash = previous.get("tx_hash")
        previous_index = decode_hex_int(
            previous.get("index"),
            f"inputs[{input_index}].previous_output.index",
        )
        context = (
            f"{oracle.network.name} input={input_index} "
            f"previous_output={previous_hash}:{previous_index}"
        )
        self.assertIs(False, actual.get("from_cellbase"), context)
        self.assertEqual(previous_hash, actual.get("generated_tx_hash"), context)
        self.assertEqual(previous_index, int(actual.get("cell_index")), context)
        self.assertEqual(
            decode_hex_int(previous_output.get("capacity"), "previous_output.capacity"),
            self._decimal_integer(actual.get("capacity"), f"{context}.capacity"),
            context,
        )
        self.assertEqual(
            output_occupied_capacity(previous_output, previous_data),
            self._decimal_integer(
                actual.get("occupied_capacity"), f"{context}.occupied_capacity"
            ),
            context,
        )
        self.assertEqual(
            output_address(previous_output, oracle.network.address_hrp),
            actual.get("address_hash"),
            context,
        )
        expected_type_script = previous_output.get("type")
        if expected_type_script is None:
            self.assertEqual("", actual.get("type_script"), context)
        else:
            self.assertEqual(expected_type_script, actual.get("type_script"), context)
        since = actual.get("since")
        self.assertIsInstance(since, dict, context)
        expected_since = decode_hex_int(rpc_input.get("since"), f"inputs[{input_index}].since")
        self.assertEqual(f"0x{expected_since:016x}", since.get("raw"), context)
        self.assertEqual(median_timestamp, int(since.get("median_timestamp")), context)

    # TEST-MAP: CKB-TX-VIEWS-RPC-11
    def test_all_displayed_inputs_match_rpc_previous_outputs_and_since(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                transaction_hash = DISPLAY_INPUTS_FIXTURES[
                    oracle.network.name
                ].ordinary_transaction_hash
                transaction, status = self._load_sample(oracle, transaction_hash)
                inputs = transaction.get("inputs")
                self.assertIsInstance(inputs, list)
                references = self._referenced_outputs(oracle, transaction)
                self.assertEqual(len(inputs), len(references))
                data, meta = self._display_inputs(oracle, transaction_hash)
                self.assertEqual(len(inputs), int(meta.get("total")))
                self.assertEqual(len(inputs), len(data))
                median_timestamp = self._median_timestamp(oracle, status)
                for input_index, (rpc_input, reference, actual) in enumerate(
                    zip(inputs, references, data, strict=True)
                ):
                    self.assertIsInstance(rpc_input, dict)
                    previous_output, previous_data = reference
                    self._assert_input_identity(
                        oracle,
                        input_index,
                        rpc_input,
                        previous_output,
                        previous_data,
                        actual,
                        median_timestamp,
                    )
                self._assert_sample_stable(oracle, transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-12
    def test_page_size_one_preserves_first_two_rpc_input_positions(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                transaction_hash = DISPLAY_INPUTS_FIXTURES[
                    oracle.network.name
                ].ordinary_transaction_hash
                transaction, status = self._load_sample(oracle, transaction_hash)
                inputs = transaction.get("inputs")
                self.assertIsInstance(inputs, list)
                self.assertGreaterEqual(len(inputs), 2)

                pages: list[Mapping[str, Any]] = []
                for page in (1, 2):
                    data, meta = self._display_inputs(
                        oracle,
                        transaction_hash,
                        page=page,
                        page_size=1,
                    )
                    self.assertEqual(1, len(data), f"{oracle.network.name} page={page}")
                    self.assertEqual(len(inputs), int(meta.get("total")))
                    self.assertEqual(1, int(meta.get("page_size")))
                    pages.append(data[0])

                out_points: list[tuple[str, int]] = []
                for input_index, row in enumerate(pages):
                    rpc_input = inputs[input_index]
                    self.assertIsInstance(rpc_input, dict)
                    previous = rpc_input.get("previous_output")
                    self.assertIsInstance(previous, dict)
                    expected_hash = previous.get("tx_hash")
                    expected_index = decode_hex_int(
                        previous.get("index"),
                        f"inputs[{input_index}].previous_output.index",
                    )
                    self.assertEqual(expected_hash, row.get("generated_tx_hash"))
                    self.assertEqual(expected_index, int(row.get("cell_index")))
                    out_points.append((str(row.get("generated_tx_hash")), int(row.get("cell_index"))))
                self.assertEqual(2, len(set(out_points)))
                self._assert_sample_stable(oracle, transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-13
    def test_cellbase_has_one_synthetic_empty_input_for_reward_target(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                transaction_hash = DISPLAY_INPUTS_FIXTURES[
                    oracle.network.name
                ].cellbase_transaction_hash
                transaction, status = self._load_sample(oracle, transaction_hash)
                inputs = transaction.get("inputs")
                self.assertIsInstance(inputs, list)
                self.assertEqual(1, len(inputs))
                rpc_input = inputs[0]
                previous = rpc_input.get("previous_output") if isinstance(rpc_input, dict) else None
                self.assertIsInstance(previous, dict)
                self.assertEqual("0x" + "00" * 32, previous.get("tx_hash"))

                data, meta = self._display_inputs(oracle, transaction_hash)
                self.assertEqual(1, len(data))
                self.assertEqual(1, int(meta.get("total")))
                row = data[0]
                self.assertIs(True, row.get("from_cellbase"))
                self.assertEqual(transaction_hash, row.get("generated_tx_hash"))
                for field in ("id", "capacity", "occupied_capacity", "address_hash"):
                    self.assertIn(row.get(field), (None, ""), f"{oracle.network.name} {field}")
                for field in ("cell_index", "cell_type", "since", "type_script"):
                    self.assertIsNone(row.get(field), f"{oracle.network.name} {field}")

                try:
                    block = oracle.block_by_hash(str(status.get("block_hash")))
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                header = block.get("header")
                self.assertIsInstance(header, dict)
                block_number = decode_hex_int(header.get("number"), "header.number")
                expected_target = max(0, block_number - self.settings.proposal_window - 1)
                self.assertEqual(expected_target, int(row.get("target_block_number")))
                self._assert_sample_stable(oracle, transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-14
    def test_cellbase_second_page_repeats_the_same_synthetic_input(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                transaction_hash = DISPLAY_INPUTS_FIXTURES[
                    oracle.network.name
                ].cellbase_transaction_hash
                _transaction, status = self._load_sample(oracle, transaction_hash)
                first, first_meta = self._display_inputs(
                    oracle, transaction_hash, page=1, page_size=1
                )
                second, second_meta = self._display_inputs(
                    oracle, transaction_hash, page=2, page_size=1
                )
                self.assertEqual(1, len(first))
                self.assertEqual(first, second)
                self.assertIs(True, second[0].get("from_cellbase"))
                self.assertEqual(1, int(first_meta.get("total")))
                self.assertEqual(1, int(second_meta.get("total")))
                self.assertEqual(1, int(first_meta.get("page_size")))
                self.assertEqual(1, int(second_meta.get("page_size")))
                self._assert_sample_stable(oracle, transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-24
    def test_typed_and_untyped_inputs_keep_independent_type_scripts(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                transaction_hash = DISPLAY_INPUTS_FIXTURES[
                    oracle.network.name
                ].ordinary_transaction_hash
                transaction, status = self._load_sample(oracle, transaction_hash)
                references = self._referenced_outputs(oracle, transaction)
                typed_index = next(
                    (
                        index
                        for index, (output, _data) in enumerate(references)
                        if isinstance(output.get("type"), dict)
                    ),
                    None,
                )
                untyped_index = next(
                    (
                        index
                        for index, (output, _data) in enumerate(references)
                        if output.get("type") is None
                    ),
                    None,
                )
                self.assertIsNotNone(typed_index)
                self.assertIsNotNone(untyped_index)
                self.assertNotEqual(typed_index, untyped_index)
                data, meta = self._display_inputs(oracle, transaction_hash)
                self.assertEqual(len(references), int(meta.get("total")))
                expected_type = references[int(typed_index)][0].get("type")
                self.assertIsInstance(expected_type, dict)
                self.assertEqual(expected_type, data[int(typed_index)].get("type_script"))
                self.assertEqual("", data[int(untyped_index)].get("type_script"))
                self._assert_sample_stable(oracle, transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-25
    def test_nonzero_since_is_fixed_width_and_matches_rpc_median_time(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                transaction_hash = DISPLAY_INPUTS_FIXTURES[
                    oracle.network.name
                ].ordinary_transaction_hash
                transaction, status = self._load_sample(oracle, transaction_hash)
                inputs = transaction.get("inputs")
                self.assertIsInstance(inputs, list)
                input_index = next(
                    (
                        index
                        for index, rpc_input in enumerate(inputs)
                        if isinstance(rpc_input, dict)
                        and decode_hex_int(rpc_input.get("since"), f"inputs[{index}].since") != 0
                    ),
                    None,
                )
                self.assertIsNotNone(input_index)
                data, _meta = self._display_inputs(oracle, transaction_hash)
                since = data[int(input_index)].get("since")
                self.assertIsInstance(since, dict)
                raw = since.get("raw")
                self.assertIsInstance(raw, str)
                self.assertRegex(raw, re.compile(r"^0x[0-9a-f]{16}$"))
                expected = decode_hex_int(
                    inputs[int(input_index)].get("since"),
                    f"inputs[{input_index}].since",
                )
                self.assertNotEqual(0, expected)
                self.assertEqual(expected, int(raw[2:], 16))
                self.assertEqual(
                    self._median_timestamp(oracle, status),
                    int(since.get("median_timestamp")),
                )
                self._assert_sample_stable(oracle, transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-26
    def test_udt_input_info_comes_from_rpc_previous_output(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                fixture = DISPLAY_INPUTS_FIXTURES[oracle.network.name].udt_input
                transaction, status = self._load_sample(oracle, fixture.transaction_hash)
                inputs = transaction.get("inputs")
                self.assertIsInstance(inputs, list)
                references = self._referenced_outputs(oracle, transaction)
                input_index = next(
                    (
                        index
                        for index, (output, _data) in enumerate(references)
                        if isinstance(output.get("type"), dict)
                        and ckb_script_hash(output["type"]) == fixture.type_hash
                    ),
                    None,
                )
                self.assertIsNotNone(input_index)
                index = int(input_index)
                previous_output, previous_data = references[index]
                self.assertIsInstance(previous_data, str)
                raw_data = bytes.fromhex(previous_data.removeprefix("0x"))
                self.assertGreaterEqual(len(raw_data), 16)
                expected_amount = int.from_bytes(raw_data[:16], "little")
                previous = inputs[index].get("previous_output")
                self.assertIsInstance(previous, dict)

                data, meta = self._display_inputs(oracle, fixture.transaction_hash)
                self.assertEqual(len(inputs), int(meta.get("total")))
                actual = data[index]
                self.assertEqual(previous.get("tx_hash"), actual.get("generated_tx_hash"))
                self.assertEqual(
                    decode_hex_int(previous.get("index"), "previous_output.index"),
                    int(actual.get("cell_index")),
                )
                self.assertEqual(fixture.cell_type, actual.get("cell_type"))
                self.assertEqual(previous_output.get("type"), actual.get("type_script"))
                info = actual.get(fixture.info_field)
                self.assertIsInstance(info, dict)
                self.assertEqual(expected_amount, self._decimal_integer(info.get("amount"), "amount"))
                self.assertEqual(fixture.type_hash, info.get("type_hash"))
                self.assertEqual(info, actual.get("extra_info"))
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-27
    def test_malformed_and_missing_transaction_hashes_return_empty_404(self) -> None:
        for oracle in self.oracles:
            for identifier in ("not-a-hash", ZERO_TX_HASH):
                with self.subTest(network=oracle.network.name, identifier=identifier):
                    path = f"/v2/ckb_transactions/{identifier}/display_inputs"
                    try:
                        status, payload, raw = _explorer_response(oracle, path)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(404, status, f"{oracle.network.name} body={raw!r}")
                    self.assertEqual(b"", raw)
                    self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
