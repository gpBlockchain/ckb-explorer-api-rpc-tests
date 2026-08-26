from __future__ import annotations

import csv
import io
import unittest
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.http import HttpClientError
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings


CSV_HEADER = [
    "Txn hash",
    "Blockno",
    "UnixTimestamp",
    "Method",
    "Token",
    "Amount",
    "date(UTC)",
]
CURRENT_FIXTURES = {
    "mainnet": (
        "0xbc48f995eee8f5c2a5610985a5cc02d5d01f08b1a5c42230716191fca29afb76",
        11_994_263,
    ),
    "testnet": (
        "0x0c5375feaaa7dd2a98807444b9bf3d218d3f5d36063e07fbc6c41dbda2fab936",
        11_808_093,
    ),
}
CLOSED_FIXTURES = {
    "mainnet": (
        "0xef95cfef4fa0d6149c3506fa46c82ee651e3b87fc63b98fb771df7d7aa81ba28",
        "0xdc7ffa5799a9d9d0701650c250b3fd77afac59ce7279dc4fcb7944bc0bd568a0",
    ),
    "testnet": (
        "0xe4354bda0d29a0f5389a5044f814c284a04d3a3de79b13a183dbd79562ffd8f4",
        "0x0637334b6867044f27951542c3eae615ed0af860502faebc3788680c09967c4d",
    ),
}


class V1OmigaInscriptionsDownloadCsvRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.cache: dict[
            tuple[str, tuple[tuple[str, object], ...]], list[list[str]]
        ] = {}

    def _csv(self, oracle: NetworkOracle, **query: object) -> list[list[str]]:
        key = (oracle.network.name, tuple(sorted(query.items())))
        if key not in self.cache:
            url = (
                oracle.network.explorer_api_url
                + "/v1/omiga_inscriptions/download_csv?"
                + urlencode(query)
            )
            try:
                raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
            except HttpClientError as error:
                if "transport failure" in str(error) or "response exceeds" in str(error):
                    raise OracleUnavailable(
                        f"{oracle.network.name} Omiga CSV transport is unavailable: {error}"
                    ) from error
                raise AssertionError(f"{oracle.network.name} Omiga CSV request failed: {error}") from error
            self.cache[key] = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        return self.cache[key]

    def _detail(
        self,
        oracle: NetworkOracle,
        identifier: str,
        **query: object,
    ) -> Mapping[str, Any]:
        payload = oracle.explorer_json(f"/v1/omiga_inscriptions/{identifier}", query or None)
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        if not isinstance(attributes, dict):
            raise OracleUnavailable(f"{oracle.network.name} Omiga detail is unavailable")
        return attributes

    def _rpc_expected(
        self,
        oracle: NetworkOracle,
        row: list[str],
        detail: Mapping[str, Any],
        *related_details: Mapping[str, Any],
    ) -> tuple[str, int]:
        result = oracle.rpc_result("get_transaction", [row[0]])
        transaction = result.get("transaction") if isinstance(result, dict) else None
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC transaction {row[0]} is unavailable")
        block_hash = status.get("block_hash")
        if not isinstance(block_hash, str):
            raise OracleUnavailable(f"{oracle.network.name} RPC block for {row[0]} is unavailable")
        block = oracle.block_by_hash(block_hash)
        header = block.get("header") if isinstance(block, dict) else None
        if not isinstance(header, dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC block header for {row[0]} is unavailable")

        type_hash = detail.get("type_hash")
        if not isinstance(type_hash, str):
            raise OracleUnavailable(f"{oracle.network.name} Omiga UDT hash is unavailable")
        known_omiga_hashes: set[str] = set()
        for lifecycle_detail in (detail, *related_details):
            if isinstance(lifecycle_detail.get("type_hash"), str):
                known_omiga_hashes.add(str(lifecycle_detail["type_hash"]))
            if isinstance(lifecycle_detail.get("pre_udt_hash"), str):
                known_omiga_hashes.add(str(lifecycle_detail["pre_udt_hash"]))

        inputs = list(oracle.referenced_outputs(transaction))
        outputs = transaction.get("outputs")
        outputs_data = transaction.get("outputs_data")
        if not isinstance(outputs, list) or not isinstance(outputs_data, list) or len(outputs) != len(outputs_data):
            raise OracleUnavailable(f"{oracle.network.name} RPC outputs for {row[0]} are unavailable")

        omiga_inputs = [
            output
            for output, _data in inputs
            if isinstance(output.get("type"), dict)
            and ckb_script_hash(output["type"]) in known_omiga_hashes
        ]
        omiga_outputs = [
            data
            for output, data in zip(outputs, outputs_data, strict=True)
            if isinstance(output, dict)
            and isinstance(output.get("type"), dict)
            and ckb_script_hash(output["type"]) in known_omiga_hashes
        ]
        if not omiga_outputs or not isinstance(omiga_outputs[0], str):
            raise AssertionError(f"{oracle.network.name} CSV transaction {row[0]} has no Omiga RPC output")

        expected_method = "rebase_mint" if omiga_inputs else "mint"
        raw_amount = bytes.fromhex(omiga_outputs[0].removeprefix("0x"))
        expected_amount = int.from_bytes(raw_amount, "little")
        timestamp = decode_hex_int(header.get("timestamp"), "csv.block.timestamp")
        self.assertEqual("committed", status.get("status"))
        self.assertEqual(row[0], transaction.get("hash"))
        self.assertEqual(int(row[1]), decode_hex_int(header.get("number"), "csv.block.number"))
        self.assertEqual(int(row[2]), timestamp)
        self.assertEqual(
            datetime.fromtimestamp(timestamp // 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            row[6],
        )
        self.assertEqual(detail.get("symbol"), row[4])
        return expected_method, expected_amount

    # TEST-MAP: OMIGA-RPC-09
    # TEST-MAP: OMIGA-RPC-12
    def test_current_and_closed_stage_bounds_order_limit_and_block_facts_match_rpc(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                current_hash, current_height = CURRENT_FIXTURES[network.name]
                closed_info_hash, closed_type_hash = CLOSED_FIXTURES[network.name]
                try:
                    current_detail = self._detail(oracle, current_hash)
                    current_at_height = self._csv(
                        oracle,
                        id=current_hash,
                        start_number=current_height,
                        end_number=current_height,
                    )
                    closed_detail = self._detail(oracle, closed_info_hash, status="closed")
                    closed_latest_detail = self._detail(oracle, closed_info_hash)
                    closed_table = self._csv(oracle, id=closed_info_hash, status="closed")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual(CSV_HEADER, current_at_height[0])
                self.assertGreater(len(current_at_height), 1)
                self.assertEqual("closed", closed_detail.get("mint_status"))
                self.assertEqual(closed_type_hash, closed_detail.get("type_hash"))
                self.assertNotEqual(closed_detail.get("type_hash"), closed_latest_detail.get("type_hash"))
                self.assertEqual(CSV_HEADER, closed_table[0])
                self.assertGreater(len(closed_table), 1)
                self.assertLessEqual(len(closed_table) - 1, 500)
                timestamps = [int(row[2]) for row in closed_table[1:]]
                self.assertEqual(timestamps, sorted(timestamps, reverse=True))

                boundary = closed_table[-1]
                try:
                    closed_at_time = self._csv(
                        oracle,
                        id=closed_info_hash,
                        status="closed",
                        start_date=int(boundary[2]),
                        end_date=int(boundary[2]),
                    )
                    closed_at_height = self._csv(
                        oracle,
                        id=closed_info_hash,
                        status="closed",
                        start_number=int(boundary[1]),
                        end_number=int(boundary[1]),
                    )
                    current_at_time = self._csv(
                        oracle,
                        id=current_hash,
                        start_date=int(current_at_height[1][2]),
                        end_date=int(current_at_height[1][2]),
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                expected_time = [CSV_HEADER] + [
                    row for row in closed_table[1:] if int(row[2]) == int(boundary[2])
                ]
                expected_height = [CSV_HEADER] + [
                    row for row in closed_table[1:] if int(row[1]) == int(boundary[1])
                ]
                self.assertEqual(expected_time, closed_at_time)
                self.assertEqual(expected_height, closed_at_height)
                self.assertEqual(current_at_height, current_at_time)

                for row in current_at_height[1:]:
                    try:
                        self._rpc_expected(oracle, row, current_detail)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                for row in closed_table[1:]:
                    try:
                        self._rpc_expected(oracle, row, closed_detail, closed_latest_detail)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error

    # TEST-MAP: OMIGA-RPC-10
    def test_mint_rebase_mint_and_large_amount_are_derived_from_first_omiga_rpc_output(self) -> None:
        observed_methods: set[str] = set()
        observed_amounts: list[int] = []
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                current_hash, current_height = CURRENT_FIXTURES[network.name]
                closed_info_hash, _closed_type_hash = CLOSED_FIXTURES[network.name]
                try:
                    closed_detail = self._detail(oracle, closed_info_hash, status="closed")
                    samples = [
                        (
                            self._detail(oracle, current_hash),
                            (),
                            self._csv(
                                oracle,
                                id=current_hash,
                                start_number=current_height,
                                end_number=current_height,
                            ),
                        ),
                        (
                            closed_detail,
                            (self._detail(oracle, closed_info_hash),),
                            self._csv(oracle, id=closed_info_hash, status="closed"),
                        ),
                    ]
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                for detail, related_details, table in samples:
                    for row in table[1:]:
                        try:
                            expected_method, expected_amount = self._rpc_expected(
                                oracle, row, detail, *related_details
                            )
                        except OracleUnavailable as error:
                            raise unittest.SkipTest(str(error)) from error
                        self.assertEqual(expected_method, row[3])
                        self.assertEqual(expected_amount, int(row[5]))
                        observed_methods.add(row[3])
                        observed_amounts.append(int(row[5]))
        self.assertTrue({"mint", "rebase_mint"}.issubset(observed_methods))
        self.assertTrue(any(amount > 2**53 - 1 for amount in observed_amounts))


if __name__ == "__main__":
    unittest.main()
