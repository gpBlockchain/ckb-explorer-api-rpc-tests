from __future__ import annotations

import csv
import io
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import decode_hex_int, output_address, output_occupied_capacity
from ckb_rpc_correctness.http import HttpClientError
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import DAO_TYPE_HASH


CSV_HEADER = [
    "Txn hash", "Address", "Blockno", "UnixTimestamp", "Method",
    "Amount", "Token", "TxnFee(CKB)", "date(UTC)",
]


class V1ContractTransactionsDownloadCsvRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.cache: dict[tuple[str, tuple[tuple[str, object], ...]], list[list[str]]] = {}

    def _csv(self, oracle: NetworkOracle, **query: object) -> list[list[str]]:
        key = (oracle.network.name, tuple(sorted(query.items())))
        if key not in self.cache:
            url = oracle.network.explorer_api_url + "/v1/contract_transactions/download_csv"
            if query:
                url += "?" + urlencode(query)
            try:
                raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
            except HttpClientError as error:
                raise OracleUnavailable(f"{oracle.network.name} contract transaction CSV unavailable: {error}") from error
            self.cache[key] = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        return self.cache[key]

    def _rpc_sample(
        self,
        oracle: NetworkOracle,
        tx_hash: str,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], list[tuple[Mapping[str, Any], object]]]:
        result = oracle.rpc_result("get_transaction", [tx_hash])
        transaction = result.get("transaction") if isinstance(result, dict) else None
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC transaction {tx_hash} is unavailable")
        if status.get("status") != "committed" or not isinstance(status.get("block_hash"), str):
            raise OracleUnavailable(f"{oracle.network.name} RPC transaction {tx_hash} is not stably committed")
        return transaction, status, oracle.referenced_outputs(transaction)

    def _fee(
        self,
        oracle: NetworkOracle,
        transaction: Mapping[str, Any],
        referenced: list[tuple[Mapping[str, Any], object]],
    ) -> int:
        inputs = transaction.get("inputs")
        outputs = transaction.get("outputs")
        if not isinstance(inputs, list) or not isinstance(outputs, list) or len(inputs) != len(referenced):
            raise OracleUnavailable(f"{oracle.network.name} RPC transaction capacities are unavailable")
        maximum_inputs = 0
        for item, (output, data) in zip(inputs, referenced, strict=True):
            type_script = output.get("type") if isinstance(output, dict) else None
            if (
                isinstance(type_script, dict)
                and type_script.get("code_hash") == DAO_TYPE_HASH
                and data != "0x" + "00" * 8
            ):
                maximum_inputs += decode_hex_int(output.get("capacity"), "withdrawing.capacity")
                maximum_inputs += self._dao_interest(oracle, item["previous_output"], output, data)
            else:
                maximum_inputs += decode_hex_int(output.get("capacity"), "input.capacity")
        return maximum_inputs - sum(
            decode_hex_int(output.get("capacity"), "output.capacity") for output in outputs
        )

    def _dao_interest(
        self,
        oracle: NetworkOracle,
        out_point: Mapping[str, Any],
        withdrawing_output: Mapping[str, Any],
        withdrawing_data: object,
    ) -> int:
        if not isinstance(withdrawing_data, str) or not withdrawing_data.startswith("0x"):
            raise OracleUnavailable(f"{oracle.network.name} DAO withdrawing data is unavailable")
        try:
            deposit_height = int.from_bytes(bytes.fromhex(withdrawing_data[2:]), "little")
        except ValueError as error:
            raise OracleUnavailable(f"{oracle.network.name} DAO withdrawing data is invalid") from error
        previous_hash = out_point.get("tx_hash")
        if not isinstance(previous_hash, str):
            raise OracleUnavailable(f"{oracle.network.name} DAO withdrawing out-point is unavailable")
        result = oracle.rpc_result("get_transaction", [previous_hash])
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(status, dict) or not isinstance(status.get("block_hash"), str):
            raise OracleUnavailable(f"{oracle.network.name} DAO withdrawing block is unavailable")
        deposit_header = oracle.block(deposit_height).get("header")
        withdrawing_header = oracle.block_by_hash(status["block_hash"]).get("header")
        if not isinstance(deposit_header, dict) or not isinstance(withdrawing_header, dict):
            raise OracleUnavailable(f"{oracle.network.name} DAO compensation headers are unavailable")

        def ar(header: Mapping[str, Any]) -> int:
            raw = header.get("dao")
            if not isinstance(raw, str) or not raw.startswith("0x"):
                raise OracleUnavailable(f"{oracle.network.name} DAO header field is unavailable")
            payload = bytes.fromhex(raw[2:])
            if len(payload) != 32:
                raise OracleUnavailable(f"{oracle.network.name} DAO header field is invalid")
            return int.from_bytes(payload[8:16], "little")

        capacity = decode_hex_int(withdrawing_output.get("capacity"), "withdrawing.capacity")
        generating = capacity - output_occupied_capacity(withdrawing_output, withdrawing_data)
        return generating * ar(withdrawing_header) // ar(deposit_header) - generating

    # TEST-MAP: DAO-TX-RPC-11
    def test_three_stage_rows_match_rpc_event_principal_interest_fee_and_block_facts(self) -> None:
        methods = ("Deposit", "Withdraw Request", "Withdraw Finalization")
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    table = self._csv(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(CSV_HEADER, table[0])
                samples = {method: next((row for row in table[1:] if row[4] == method), None) for method in methods}
                if any(row is None for row in samples.values()):
                    raise unittest.SkipTest(f"{network.name} one-window three-stage DAO CSV fixture is unavailable")
                for method in methods:
                    row = samples[method]
                    assert row is not None
                    try:
                        transaction, status, referenced = self._rpc_sample(oracle, row[0])
                        block = oracle.block_by_hash(status["block_hash"])
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    header = block.get("header") if isinstance(block, dict) else None
                    if not isinstance(header, dict):
                        raise unittest.SkipTest(f"{network.name} RPC DAO block is unavailable")
                    candidates: list[tuple[str, int]] = []
                    if method == "Deposit":
                        for index, output in enumerate(transaction["outputs"]):
                            type_script = output.get("type") if isinstance(output, dict) else None
                            if (
                                isinstance(type_script, dict)
                                and type_script.get("code_hash") == DAO_TYPE_HASH
                                and transaction["outputs_data"][index] == "0x" + "00" * 8
                            ):
                                candidates.append((
                                    output_address(output, network.address_hrp),
                                    decode_hex_int(output["capacity"], "deposit.capacity"),
                                ))
                    elif method == "Withdraw Request":
                        for output, data in referenced:
                            type_script = output.get("type") if isinstance(output, dict) else None
                            if (
                                isinstance(type_script, dict)
                                and type_script.get("code_hash") == DAO_TYPE_HASH
                                and data == "0x" + "00" * 8
                            ):
                                candidates.append((
                                    output_address(output, network.address_hrp),
                                    decode_hex_int(output["capacity"], "deposit.capacity"),
                                ))
                    else:
                        for rpc_input, (output, data) in zip(transaction["inputs"], referenced, strict=True):
                            type_script = output.get("type") if isinstance(output, dict) else None
                            if (
                                isinstance(type_script, dict)
                                and type_script.get("code_hash") == DAO_TYPE_HASH
                                and data != "0x" + "00" * 8
                            ):
                                candidates.append((
                                    output_address(output, network.address_hrp),
                                    self._dao_interest(
                                        oracle, rpc_input["previous_output"], output, data
                                    ),
                                ))
                    amount = int(Decimal(row[5]) * 100_000_000)
                    self.assertIn((row[1], amount), candidates)
                    self.assertEqual("CKB", row[6])
                    self.assertEqual(
                        self._fee(oracle, transaction, referenced),
                        int(Decimal(row[7]) * 100_000_000),
                    )
                    timestamp = decode_hex_int(header["timestamp"], "block.timestamp")
                    self.assertEqual(decode_hex_int(header["number"], "block.number"), int(row[2]))
                    self.assertEqual(timestamp, int(row[3]))
                    self.assertEqual(
                        datetime.fromtimestamp(timestamp // 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        row[8],
                    )

    # TEST-MAP: DAO-TX-RPC-12
    def test_timestamp_window_is_inclusive_and_excludes_rows_outside_both_boundaries(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    full = self._csv(oracle)
                    timestamps = sorted({int(row[3]) for row in full[1:]})
                    if len(timestamps) < 4:
                        raise OracleUnavailable(f"{network.name} DAO timestamp boundary fixture is unavailable")
                    below, start, end, above = timestamps[:4]
                    table = self._csv(oracle, start_date=start, end_date=end)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                actual = {int(row[3]) for row in table[1:]}
                self.assertTrue(actual)
                self.assertTrue(all(start <= value <= end for value in actual))
                self.assertIn(start, actual)
                self.assertIn(end, actual)
                self.assertNotIn(below, actual)
                self.assertNotIn(above, actual)

    # TEST-MAP: DAO-TX-RPC-13
    def test_height_window_is_inclusive_and_overrides_conflicting_timestamp_parameters(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    full = self._csv(oracle)
                    heights = sorted({int(row[2]) for row in full[1:]})
                    if len(heights) < 4:
                        raise OracleUnavailable(f"{network.name} DAO height boundary fixture is unavailable")
                    below, start, end, above = heights[:4]
                    table = self._csv(
                        oracle,
                        start_number=start,
                        end_number=end,
                        start_date=2**63,
                        end_date=0,
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                actual = {int(row[2]) for row in table[1:]}
                self.assertTrue(actual)
                self.assertTrue(all(start <= value <= end for value in actual))
                self.assertIn(start, actual)
                self.assertIn(end, actual)
                self.assertNotIn(below, actual)
                self.assertNotIn(above, actual)

    # TEST-MAP: DAO-TX-RPC-14
    def test_empty_genesis_height_window_returns_only_the_fixed_header(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    table = self._csv(oracle, start_number=1, end_number=1)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual([CSV_HEADER], table)


if __name__ == "__main__":
    unittest.main()
