from __future__ import annotations

import csv
import io
import unittest
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.http import HttpClientError
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings


CSV_HEADER = [
    "Txn hash",
    "Blockno",
    "UnixTimestamp",
    "NFT ID",
    "Method",
    "NFT From",
    "NFT to",
    "TxnFee(CKB)",
    "date(UTC)",
]

SMALL_COLLECTION_FIXTURES = {
    "mainnet": 9594,
    "testnet": 20074,
}

BUSY_COLLECTION_FIXTURES = {
    "mainnet": 578,
    "testnet": 1,
}


class V2NftTransfersDownloadCsvRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.csv_cache: dict[
            tuple[str, tuple[tuple[str, object], ...]], list[list[str]]
        ] = {}

    def _csv(self, oracle: NetworkOracle, **query: object) -> list[list[str]]:
        key = (oracle.network.name, tuple(sorted(query.items())))
        if key not in self.csv_cache:
            url = (
                oracle.network.explorer_api_url
                + "/v2/nft/transfers/download_csv?"
                + urlencode(query)
            )
            try:
                raw = oracle.client.request_bytes(url, headers=V1_HEADERS)
            except HttpClientError as error:
                raise OracleUnavailable(
                    f"{oracle.network.name} NFT CSV is unavailable: {error}"
                ) from error
            self.csv_cache[key] = list(
                csv.reader(io.StringIO(raw.decode("utf-8-sig")))
            )
        return self.csv_cache[key]

    def _transfer_page(
        self,
        oracle: NetworkOracle,
        collection_id: object,
        page: int = 1,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json(
            f"/v2/nft/collections/{collection_id}/transfers", {"page": page}
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        pagination = payload.get("pagination") if isinstance(payload, dict) else None
        if (
            not isinstance(data, list)
            or any(not isinstance(row, dict) for row in data)
            or not isinstance(pagination, dict)
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT transfer page is unavailable"
            )
        return data, pagination

    def _all_transfers(
        self, oracle: NetworkOracle, collection_id: object
    ) -> list[Mapping[str, Any]]:
        first, pagination = self._transfer_page(oracle, collection_id)
        rows = list(first)
        for page in range(2, int(pagination["pages"]) + 1):
            current, current_pagination = self._transfer_page(
                oracle, collection_id, page
            )
            if current_pagination["count"] != pagination["count"]:
                raise OracleUnavailable(
                    f"{oracle.network.name} NFT collection changed while paging"
                )
            rows.extend(current)
        if len(rows) != int(pagination["count"]):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT collection changed while paging"
            )
        return rows

    @staticmethod
    def _api_csv_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
        method = {
            "normal": "Transfer",
            "destruction": "Burn",
            "mint": "Mint",
        }[row["action"]]
        return (
            row["transaction"]["tx_hash"],
            row["item"]["token_id"],
            method,
            row["from"] or "/",
            row["to"] or "/",
        )

    @staticmethod
    def _csv_key(row: list[str]) -> tuple[str, str, str, str, str]:
        return row[0], row[3], row[4], row[5], row[6]

    # TEST-MAP: NFT-TX-RPC-17
    def test_numeric_and_sn_exports_have_exact_header_and_collection_events(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id = SMALL_COLLECTION_FIXTURES[network.name]
                try:
                    collection = oracle.explorer_json(
                        f"/v2/nft/collections/{collection_id}"
                    )
                    transfers = self._all_transfers(oracle, collection_id)
                    start = min(
                        int(row["transaction"]["block_timestamp"])
                        for row in transfers
                    )
                    end = max(
                        int(row["transaction"]["block_timestamp"])
                        for row in transfers
                    )
                    numeric = self._csv(
                        oracle,
                        collection_id=collection_id,
                        start_date=start,
                        end_date=end,
                    )
                    by_sn = self._csv(
                        oracle,
                        collection_id=collection["sn"],
                        start_date=start,
                        end_date=end,
                    )
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual(CSV_HEADER, numeric[0])
                self.assertEqual(numeric, by_sn)
                self.assertEqual(len(transfers), len(numeric) - 1)
                self.assertEqual(
                    Counter(self._api_csv_key(row) for row in transfers),
                    Counter(self._csv_key(row) for row in numeric[1:]),
                )
                self.assertEqual(
                    {"Transfer", "Burn", "Mint"}, {row[4] for row in numeric[1:]}
                )

    # TEST-MAP: NFT-TX-RPC-18
    def test_action_empty_addresses_fee_and_utc_time_match_rpc(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id = SMALL_COLLECTION_FIXTURES[network.name]
                try:
                    transfers = self._all_transfers(oracle, collection_id)
                    table = self._csv(oracle, collection_id=collection_id)
                    selected = {
                        action: next(row for row in transfers if row["action"] == action)
                        for action in ("normal", "destruction", "mint")
                    }
                    for action, transfer in selected.items():
                        csv_row = next(
                            row
                            for row in table[1:]
                            if self._csv_key(row) == self._api_csv_key(transfer)
                        )
                        result = oracle.rpc_result(
                            "get_transaction", [transfer["transaction"]["tx_hash"]]
                        )
                        transaction = (
                            result.get("transaction")
                            if isinstance(result, dict)
                            else None
                        )
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict) or not isinstance(status, dict):
                            raise OracleUnavailable(
                                f"{network.name} NFT CSV transaction is unavailable"
                            )
                        referenced = oracle.referenced_outputs(transaction)
                        block = oracle.block_by_hash(status["block_hash"])
                        header = block.get("header") if isinstance(block, dict) else None
                        if not isinstance(header, dict):
                            raise OracleUnavailable(
                                f"{network.name} NFT CSV block is unavailable"
                            )
                        input_capacity = sum(
                            decode_hex_int(output["capacity"], "input.capacity")
                            for output, _data in referenced
                        )
                        output_capacity = sum(
                            decode_hex_int(output["capacity"], "output.capacity")
                            for output in transaction["outputs"]
                        )
                        timestamp = decode_hex_int(
                            header["timestamp"], "block.timestamp"
                        )
                        self.assertEqual("committed", status.get("status"))
                        self.assertEqual(
                            input_capacity - output_capacity,
                            int(Decimal(csv_row[7]) * 100_000_000),
                        )
                        self.assertEqual(
                            datetime.fromtimestamp(
                                timestamp // 1000, tz=timezone.utc
                            ).strftime("%Y-%m-%d %H:%M:%S"),
                            csv_row[8],
                        )
                        self.assertEqual("/" if action == "mint" else transfer["from"], csv_row[5])
                        self.assertEqual(
                            "/" if action == "destruction" else transfer["to"],
                            csv_row[6],
                        )
                except (OracleUnavailable, StopIteration, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

    # TEST-MAP: NFT-TX-RPC-19
    def test_timestamp_and_height_boundaries_are_inclusive_and_intersect(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id = SMALL_COLLECTION_FIXTURES[network.name]
                try:
                    full = self._csv(oracle, collection_id=collection_id)
                    target = full[1 + (len(full) - 1) // 2]
                    timestamp = int(target[2])
                    height = int(target[1])
                    at_time = self._csv(
                        oracle,
                        collection_id=collection_id,
                        start_date=timestamp,
                        end_date=timestamp,
                    )
                    at_height = self._csv(
                        oracle,
                        collection_id=collection_id,
                        start_number=height,
                        end_number=height,
                    )
                    combined = self._csv(
                        oracle,
                        collection_id=collection_id,
                        start_date=timestamp,
                        end_date=timestamp,
                        start_number=height,
                        end_number=height,
                    )
                except (OracleUnavailable, IndexError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                expected_time = [CSV_HEADER] + [
                    row for row in full[1:] if int(row[2]) == timestamp
                ]
                expected_height = [CSV_HEADER] + [
                    row for row in full[1:] if int(row[1]) == height
                ]
                expected_combined = [CSV_HEADER] + [
                    row
                    for row in full[1:]
                    if int(row[2]) == timestamp and int(row[1]) == height
                ]
                self.assertEqual(expected_time, at_time)
                self.assertEqual(expected_height, at_height)
                self.assertEqual(expected_combined, combined)
                self.assertIn(target, combined)

    # TEST-MAP: NFT-TX-RPC-20
    def test_busy_collection_export_is_capped_to_latest_500_transfer_ids(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id = BUSY_COLLECTION_FIXTURES[network.name]
                try:
                    table = self._csv(oracle, collection_id=collection_id)
                    repeated = self._csv(
                        oracle, collection_id=collection_id, start_number=0
                    )
                    all_transfers = self._all_transfers(oracle, collection_id)
                    if len(all_transfers) <= 500:
                        raise OracleUnavailable(
                            f"{network.name} busy NFT collection fixture is unavailable"
                        )
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual(CSV_HEADER, table[0])
                self.assertEqual(500, len(table) - 1)
                self.assertEqual(table, repeated)
                observed_by_key = {
                    self._api_csv_key(row): row for row in all_transfers
                }
                csv_keys = [self._csv_key(row) for row in table[1:]]
                mapped_ids = [
                    int(observed_by_key[key]["id"])
                    for key in csv_keys
                    if key in observed_by_key
                ]
                self.assertGreater(len(mapped_ids), 250)
                self.assertEqual(
                    sorted(mapped_ids, reverse=True), mapped_ids
                )
                oldest_observed_export_id = min(mapped_ids)
                self.assertTrue(
                    {
                        key
                        for key, row in observed_by_key.items()
                        if int(row["id"]) >= oldest_observed_export_id
                    }.issubset(set(csv_keys))
                )
                self.assertEqual(len(table) - 1, len({tuple(row) for row in table[1:]}))


if __name__ == "__main__":
    unittest.main()
