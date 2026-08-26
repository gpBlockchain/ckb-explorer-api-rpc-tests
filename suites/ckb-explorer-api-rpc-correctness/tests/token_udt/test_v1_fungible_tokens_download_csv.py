from __future__ import annotations

import csv
import io
import socket
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings

from tests.token_udt import test_v1_udts_download_csv as udt_csv_support


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


class V1FungibleTokensDownloadCsvRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.cache: dict[
            tuple[str, str, str, tuple[tuple[str, object], ...]],
            tuple[list[list[str]], Mapping[str, str]],
        ] = {}

    def _download(
        self,
        oracle: NetworkOracle,
        endpoint: str,
        type_hash: str,
        **query: object,
    ) -> tuple[list[list[str]], Mapping[str, str]]:
        key = (oracle.network.name, endpoint, type_hash, tuple(sorted(query.items())))
        if key in self.cache:
            return self.cache[key]
        params: dict[str, object] = {"id": type_hash}
        params.update(query)
        url = oracle.network.explorer_api_url + f"/v1/{endpoint}/download_csv?" + urlencode(params)
        headers = dict(V1_HEADERS)
        headers["User-Agent"] = oracle.client.user_agent
        for attempt in range(oracle.client.retries + 1):
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=oracle.client.timeout) as response:
                    raw = response.read(oracle.client.max_body_bytes + 1)
                    response_headers = dict(response.headers.items())
                if len(raw) > oracle.client.max_body_bytes:
                    raise OracleUnavailable(f"{oracle.network.name} {endpoint} CSV is too large")
                table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
                self.cache[key] = table, response_headers
                return self.cache[key]
            except urllib.error.HTTPError as error:
                status = error.code
                error.close()
                if attempt < oracle.client.retries and (status == 429 or status >= 500):
                    time.sleep(0.2 * (attempt + 1))
                    continue
                raise OracleUnavailable(f"{oracle.network.name} {endpoint} CSV returned HTTP {status}") from error
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as error:
                if attempt < oracle.client.retries:
                    time.sleep(0.2 * (attempt + 1))
                    continue
                raise OracleUnavailable(f"{oracle.network.name} {endpoint} CSV transport failure: {error}") from error
        raise AssertionError("unreachable CSV retry loop")

    # TEST-MAP: XUDT-FT-RPC-13
    @unittest.expectedFailure  # Both public xUDT exporters currently emit only the header for xUDT Cell histories.
    def test_shared_entries_return_identical_filtered_rpc_rows_with_distinct_filenames(self) -> None:
        nonempty_exports: dict[str, bool] = {}
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    catalog = oracle.explorer_json(
                        "/v1/xudts",
                        {"sort": "addresses_count.desc", "page": 1, "page_size": 20},
                    )
                    fixture = None
                    transaction_page = None
                    for item in catalog["data"]:
                        attributes = item["attributes"]
                        if not attributes.get("published") or attributes.get("udt_type") not in {
                            "xudt",
                            "xudt_compatible",
                        }:
                            continue
                        candidate = oracle.explorer_json(
                            f"/v1/udt_transactions/{attributes['type_hash']}",
                            {"page": 1, "page_size": 1},
                        )
                        if int(candidate["meta"]["total"]) > 0:
                            fixture = attributes
                            transaction_page = candidate
                            break
                    if fixture is None or transaction_page is None:
                        raise OracleUnavailable(
                            f"{network.name} has no published xUDT with committed transactions"
                        )
                    type_hash = str(fixture["type_hash"])
                    symbol = str(fixture["symbol"])
                    decimal = int(fixture["decimal"])
                    xudt_table, xudt_headers = self._download(oracle, "xudts", type_hash)
                    fungible_table, fungible_headers = self._download(oracle, "fungible_tokens", type_hash)
                    listed_transaction = transaction_page["data"][0]["attributes"]
                    listed_rpc = oracle.rpc_result(
                        "get_transaction", [listed_transaction["transaction_hash"]]
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(CSV_HEADER, xudt_table[0])
                self.assertEqual(xudt_table, fungible_table)
                self.assertEqual("committed", listed_rpc["tx_status"]["status"])
                self.assertEqual(
                    listed_transaction["transaction_hash"], listed_rpc["transaction"]["hash"]
                )
                xudt_disposition = next(
                    (value for key, value in xudt_headers.items() if key.lower() == "content-disposition"), ""
                )
                fungible_disposition = next(
                    (value for key, value in fungible_headers.items() if key.lower() == "content-disposition"), ""
                )
                self.assertIn("filename=xudt_transactions.csv", xudt_disposition)
                self.assertIn("filename=udt_transactions.csv", fungible_disposition)
                nonempty_exports[network.name] = len(fungible_table) > 1
                if len(fungible_table) == 1:
                    continue
                hashes = list(dict.fromkeys(row[0] for row in fungible_table[1:]))
                self.assertLessEqual(len(hashes), 500)
                timestamps = [
                    int(next(row[2] for row in fungible_table[1:] if row[0] == tx_hash)) for tx_hash in hashes
                ]
                self.assertEqual(timestamps, sorted(timestamps, reverse=True))

                helper = udt_csv_support.V1UdtsDownloadCsvRpcCorrectnessTests()
                for row in fungible_table[1:]:
                    try:
                        transaction, status, inputs, outputs, _input_counts, _output_counts = helper._rpc_amounts(
                            oracle, row[0], type_hash
                        )
                        block_hash = status.get("block_hash")
                        if not isinstance(block_hash, str):
                            raise OracleUnavailable(f"{network.name} CSV transaction block is unavailable")
                        block = oracle.block_by_hash(block_hash)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    header = block.get("header") if isinstance(block, dict) else None
                    self.assertIsInstance(header, dict)
                    timestamp = decode_hex_int(header.get("timestamp"), "csv.block.timestamp")
                    amount_in = inputs.get(row[6], 0)
                    amount_out = outputs.get(row[6], 0)
                    change = amount_out - amount_in
                    expected_method = (
                        "PAYMENT RECEIVED" if change > 0 else "PAYMENT SENT" if change < 0 else "PAYMENT MINT"
                    )
                    self.assertEqual("committed", status.get("status"))
                    self.assertEqual(row[0], transaction.get("hash"))
                    self.assertEqual(int(row[1]), decode_hex_int(header.get("number"), "csv.block.number"))
                    self.assertEqual(int(row[2]), timestamp)
                    self.assertEqual(symbol, row[4])
                    self.assertEqual(expected_method, row[3])
                    self.assertEqual(abs(change), int(Decimal(row[5]) * (10**decimal)))
                    self.assertEqual(
                        datetime.fromtimestamp(timestamp // 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        row[7],
                    )

                boundary_timestamp = int(fungible_table[-1][2])
                boundary_height = int(fungible_table[-1][1])
                expected_timestamp = [CSV_HEADER] + [
                    row for row in fungible_table[1:] if int(row[2]) == boundary_timestamp
                ]
                expected_height = [CSV_HEADER] + [
                    row for row in fungible_table[1:] if int(row[1]) == boundary_height
                ]
                for endpoint in ("xudts", "fungible_tokens"):
                    try:
                        at_timestamp, _headers = self._download(
                            oracle,
                            endpoint,
                            type_hash,
                            start_date=boundary_timestamp,
                            end_date=boundary_timestamp,
                        )
                        at_height, _headers = self._download(
                            oracle,
                            endpoint,
                            type_hash,
                            start_number=boundary_height,
                            end_number=boundary_height,
                        )
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(expected_timestamp, at_timestamp)
                    self.assertEqual(expected_height, at_height)

        self.assertEqual(
            {network.name: True for network in self.settings.networks},
            nonempty_exports,
        )


if __name__ == "__main__":
    unittest.main()
