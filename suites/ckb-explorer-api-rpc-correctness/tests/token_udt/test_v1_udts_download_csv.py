from __future__ import annotations

import csv
import io
import json
import unittest
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Any, Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int, output_address
from ckb_rpc_correctness.http import HttpClientError
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


CSV_HEADER = [
    "Txn hash",
    "Blockno",
    "UnixTimestamp",
    "Method",
    "Token",
    "Amount",
    "Token From",
    "date(UTC)",
]
SMALL_UDTS = {
    "mainnet": ("0x7a12b26b621b6cf6982247855388694743c4da97b18a4ff8ebdf6fb54c1c850f", "1INCH", 18),
    "testnet": ("0xf60ed426477642e3f3fc384d09b6fbf3c6005bd2d106382301138880555a23fe", "PPIG", 6),
}
MULTI_CELL_FIXTURE = (
    "0xf61662cec7118a0373c62b45c9e73cfc2e36cc0606857e36cc539cc179d04deb",
    "ckUSDT",
    6,
    "0x5596b38f9d66301b0a8a6e7220159df5dc36e43eb2113d4d1d4d55366011989b",
    2_115_516,
)
PRECISION_FIXTURES = {
    "mainnet": (
        (
            "decimal-zero",
            "0x38928268eaffd58e25605a923cf61602e914cb8365ba00131ec0bc004cc753d1",
            "COFFEE",
            0,
            "0x6bd6ba9069bec8216d4e4b86a0e31fcc2ad9981810c4af54dad8acc4257e380a",
            17_627_334,
        ),
        (
            "tiny-common-decimal",
            "0xe78165e8b96ceea99bf93bdb86cb5b63d32c265045d674bc53da7e444bb31e1a",
            "dCKB",
            8,
            "0x763132024d4c543f519929bc3b0bc2b0c7aeeaa457c95db20567c2ecf6a5dc0d",
            8_432_684,
        ),
        (
            "large-common-decimal",
            "0x7a12b26b621b6cf6982247855388694743c4da97b18a4ff8ebdf6fb54c1c850f",
            "1INCH",
            18,
            "0xe8dac4cf872711a2af9e8a49db345ac2a11f9e993580bbfc9c40b47e21ae0429",
            6_285_807,
        ),
    ),
    "testnet": (
        (
            "decimal-zero",
            "0xc966167b0d5719b178ebce509ad3f0ea41c539a7d444bc05766b6008f509fee6",
            "TT3",
            0,
            "0x37017262fa45e74fd362443dc2b3a417962e7452f073bbbe8546e25e4c688769",
            14_889_879,
        ),
        (
            "tiny-common-decimal",
            "0x5e4229de7f1a6304099385638e4ef3e85ab7a02b0ed4d4a95783ebd982edb691",
            "ckETH",
            18,
            "0xb29e6b69469c28b9bcefe31d1bd90e0137426d44e7c31f55640bc593f8f8771c",
            1_736_740,
        ),
    ),
}


class V1UdtsDownloadCsvRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.cache: dict[tuple[str, str, tuple[tuple[str, object], ...]], list[list[str]]] = {}

    def _csv(self, oracle: NetworkOracle, type_hash: str, **query: object) -> list[list[str]]:
        key = (oracle.network.name, type_hash, tuple(sorted(query.items())))
        if key not in self.cache:
            params: dict[str, object] = {"id": type_hash}
            params.update(query)
            url = oracle.network.explorer_api_url + "/v1/udts/download_csv?" + urlencode(params)
            try:
                raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
            except HttpClientError as error:
                raise OracleUnavailable(f"{oracle.network.name} Explorer UDT CSV unavailable: {error}") from error
            self.cache[key] = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        return self.cache[key]

    def _catalog(self, oracle: NetworkOracle) -> list[Mapping[str, Any]]:
        payload = oracle.explorer_json("/v1/udts", {"page": 1, "page_size": 100})
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise OracleUnavailable(f"{oracle.network.name} UDT catalog is unavailable")
        rows: list[Mapping[str, Any]] = []
        for item in data:
            attributes = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(attributes, dict):
                raise OracleUnavailable(f"{oracle.network.name} UDT catalog row is unavailable")
            rows.append(attributes)
        return rows

    def _rpc_amounts(
        self,
        oracle: NetworkOracle,
        tx_hash: str,
        type_hash: str,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], dict[str, int], dict[str, int], Counter[str], Counter[str]]:
        result = oracle.rpc_result("get_transaction", [tx_hash])
        transaction = result.get("transaction") if isinstance(result, dict) else None
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC transaction {tx_hash} is unavailable")
        outputs = transaction.get("outputs")
        outputs_data = transaction.get("outputs_data")
        if not isinstance(outputs, list) or not isinstance(outputs_data, list) or len(outputs) != len(outputs_data):
            raise OracleUnavailable(f"{oracle.network.name} RPC transaction {tx_hash} outputs are unavailable")

        input_amounts: dict[str, int] = defaultdict(int)
        output_amounts: dict[str, int] = defaultdict(int)
        input_counts: Counter[str] = Counter()
        output_counts: Counter[str] = Counter()
        for output, data in oracle.referenced_outputs(transaction):
            script = output.get("type")
            if not isinstance(script, dict) or ckb_script_hash(script) != type_hash:
                continue
            if not isinstance(data, str):
                raise OracleUnavailable(f"{oracle.network.name} RPC input UDT data is unavailable")
            raw = bytes.fromhex(data.removeprefix("0x"))
            if len(raw) < 16:
                raise OracleUnavailable(f"{oracle.network.name} RPC input UDT data is shorter than 16 bytes")
            address = output_address(output, oracle.network.address_hrp)
            input_amounts[address] += int.from_bytes(raw[:16], "little")
            input_counts[address] += 1
        for output, data in zip(outputs, outputs_data, strict=True):
            script = output.get("type") if isinstance(output, dict) else None
            if not isinstance(script, dict) or ckb_script_hash(script) != type_hash:
                continue
            if not isinstance(data, str):
                raise OracleUnavailable(f"{oracle.network.name} RPC output UDT data is unavailable")
            raw = bytes.fromhex(data.removeprefix("0x"))
            if len(raw) < 16:
                raise OracleUnavailable(f"{oracle.network.name} RPC output UDT data is shorter than 16 bytes")
            address = output_address(output, oracle.network.address_hrp)
            output_amounts[address] += int.from_bytes(raw[:16], "little")
            output_counts[address] += 1
        return transaction, status, dict(input_amounts), dict(output_amounts), input_counts, output_counts

    # TEST-MAP: UDT-CATALOG-RPC-11
    def test_filtered_rows_header_order_limit_and_committed_block_facts_match_rpc(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                type_hash, symbol, _decimal = SMALL_UDTS[network.name]
                try:
                    table = self._csv(oracle, type_hash)
                    timestamp = int(table[-1][2])
                    height = int(table[-1][1])
                    at_timestamp = self._csv(oracle, type_hash, start_date=timestamp, end_date=timestamp)
                    at_height = self._csv(oracle, type_hash, start_number=height, end_number=height)
                except (OracleUnavailable, IndexError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual(CSV_HEADER, table[0])
                self.assertGreater(len(table), 1)
                self.assertTrue(all(len(row) == len(CSV_HEADER) for row in table[1:]))
                hashes = list(dict.fromkeys(row[0] for row in table[1:]))
                self.assertLessEqual(len(hashes), 500)
                timestamps = [int(next(row[2] for row in table[1:] if row[0] == tx_hash)) for tx_hash in hashes]
                self.assertEqual(timestamps, sorted(timestamps, reverse=True))
                self.assertEqual([CSV_HEADER] + [row for row in table[1:] if int(row[2]) == timestamp], at_timestamp)
                self.assertEqual([CSV_HEADER] + [row for row in table[1:] if int(row[1]) == height], at_height)

                for row in table[1:]:
                    try:
                        result = oracle.rpc_result("get_transaction", [row[0]])
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict) or not isinstance(status, dict):
                            raise OracleUnavailable(f"{network.name} RPC transaction {row[0]} is unavailable")
                        block_hash = status.get("block_hash")
                        if not isinstance(block_hash, str):
                            raise OracleUnavailable(f"{network.name} RPC transaction block is unavailable")
                        block = oracle.block_by_hash(block_hash)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    header = block.get("header") if isinstance(block, dict) else None
                    self.assertIsInstance(header, dict)
                    rpc_timestamp = decode_hex_int(header.get("timestamp"), "block.timestamp")
                    self.assertEqual("committed", status.get("status"))
                    self.assertEqual(row[0], transaction.get("hash"))
                    self.assertEqual(int(row[1]), decode_hex_int(header.get("number"), "block.number"))
                    self.assertEqual(int(row[2]), rpc_timestamp)
                    self.assertEqual(symbol, row[4])
                    self.assertEqual(
                        datetime.fromtimestamp(rpc_timestamp // 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        row[7],
                    )

    # TEST-MAP: UDT-CATALOG-RPC-12
    def test_same_address_cells_are_summed_before_one_row_per_address_and_method_derivation(self) -> None:
        network = next(item for item in self.settings.networks if item.name == "testnet")
        oracle = NetworkOracle(network, self.settings)
        type_hash, symbol, decimal, tx_hash, height = MULTI_CELL_FIXTURE
        try:
            table = self._csv(oracle, type_hash, start_number=height, end_number=height)
            transaction, status, inputs, outputs, input_counts, output_counts = self._rpc_amounts(
                oracle, tx_hash, type_hash
            )
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        rows = [row for row in table[1:] if row[0] == tx_hash]
        addresses = set(inputs) | set(outputs)
        self.assertEqual("committed", status.get("status"))
        self.assertEqual(tx_hash, transaction.get("hash"))
        self.assertGreater(len(addresses), 1)
        self.assertTrue(any(input_counts[address] > 1 for address in addresses))
        self.assertTrue(any(output_counts[address] > 1 for address in addresses))
        self.assertEqual(len(addresses), len(rows))
        self.assertEqual(len(rows), len({row[6] for row in rows}))
        self.assertLess(len(rows), sum(input_counts.values()) + sum(output_counts.values()))
        by_address = {row[6]: row for row in rows}
        for address in addresses:
            amount_in = inputs.get(address, 0)
            amount_out = outputs.get(address, 0)
            change = amount_out - amount_in
            expected_method = "PAYMENT RECEIVED" if change > 0 else "PAYMENT SENT" if change < 0 else "PAYMENT MINT"
            row = by_address[address]
            self.assertEqual(symbol, row[4])
            self.assertEqual(expected_method, row[3])
            self.assertEqual(abs(change), int(Decimal(row[5]) * (10**decimal)))

    # TEST-MAP: UDT-CATALOG-RPC-13
    def test_zero_common_tiny_large_and_high_decimal_amounts_use_exact_integer_scaling(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            for label, type_hash, symbol, decimal, tx_hash, height in PRECISION_FIXTURES[network.name]:
                with self.subTest(network=network.name, precision=label):
                    try:
                        table = self._csv(oracle, type_hash, start_number=height, end_number=height)
                        _transaction, _status, inputs, outputs, _input_counts, _output_counts = self._rpc_amounts(
                            oracle, tx_hash, type_hash
                        )
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    rows = [row for row in table[1:] if row[0] == tx_hash]
                    self.assertGreater(len(rows), 0)
                    self.assertTrue(all(row[4] == symbol for row in rows))
                    for row in rows:
                        raw_change = abs(outputs.get(row[6], 0) - inputs.get(row[6], 0))
                        displayed = Decimal(row[5])
                        self.assertEqual(raw_change, int(displayed * (10**decimal)))
                        self.assertNotIn("e", row[5].lower())
                    if label == "tiny-common-decimal":
                        self.assertTrue(any(Decimal(row[5]) < Decimal("0.000001") for row in rows))
                    if label == "large-common-decimal":
                        self.assertTrue(any(
                            abs(outputs.get(row[6], 0) - inputs.get(row[6], 0)) > 2**53 - 1 for row in rows
                        ))

            with self.subTest(network=network.name, precision="decimal-above-20"):
                try:
                    candidates = []
                    for row in self._catalog(oracle):
                        try:
                            if row.get("published") is True and int(row.get("decimal")) > 20:
                                candidates.append(row)
                        except (TypeError, ValueError):
                            continue
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                selected: tuple[Mapping[str, Any], list[str]] | None = None
                for candidate in candidates:
                    type_hash = candidate.get("type_hash")
                    if not isinstance(type_hash, str):
                        continue
                    try:
                        table = self._csv(oracle, type_hash)
                    except OracleUnavailable:
                        continue
                    if len(table) > 1:
                        selected = candidate, table[1]
                        break
                if selected is None:
                    raise unittest.SkipTest(f"{network.name} published UDT with decimal above 20 is unavailable")
                candidate, row = selected
                type_hash = str(candidate["type_hash"])
                decimal = int(candidate["decimal"])
                try:
                    _transaction, _status, inputs, outputs, _input_counts, _output_counts = self._rpc_amounts(
                        oracle, row[0], type_hash
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                raw_change = abs(outputs.get(row[6], 0) - inputs.get(row[6], 0))
                with localcontext() as context:
                    context.prec = max(80, len(str(raw_change)) + decimal + 10)
                    expected = (Decimal(raw_change) / (Decimal(10) ** decimal)).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                self.assertEqual(f"{expected:.2f}...", row[5])

    # TEST-MAP: UDT-CATALOG-RPC-14
    def test_missing_unpublished_and_unlocatable_ids_return_udt_not_found_without_csv_rows(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            cases = (("invalid", "not-a-type-hash"), ("missing", "0x" + "ff" * 32))
            for label, identifier in cases:
                with self.subTest(network=network.name, identifier=label):
                    try:
                        status, raw = _raw_explorer_response(
                            oracle, "/v1/udts/download_csv?" + urlencode({"id": identifier})
                        )
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(404, status)
                    payload = json.loads(raw)
                    self.assertEqual({1026}, {int(error["code"]) for error in payload})
                    self.assertNotIn(b"Txn hash", raw)

            with self.subTest(network=network.name, identifier="unpublished"):
                try:
                    unpublished = next(
                        (row.get("type_hash") for row in self._catalog(oracle) if row.get("published") is False),
                        None,
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if not isinstance(unpublished, str):
                    raise unittest.SkipTest(f"{network.name} unpublished sUDT fixture is unavailable")
                try:
                    status, raw = _raw_explorer_response(
                        oracle, "/v1/udts/download_csv?" + urlencode({"id": unpublished})
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(404, status)
                payload = json.loads(raw)
                self.assertEqual({1026}, {int(error["code"]) for error in payload})
                self.assertNotIn(b"Txn hash", raw)


if __name__ == "__main__":
    unittest.main()
