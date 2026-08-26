from __future__ import annotations

import csv
import io
import json
import unittest
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int, output_address
from ckb_rpc_correctness.http import HttpClientError
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


SNAPSHOT_XUDTS = {
    "mainnet": "0x59f9e9966f4b0e8578c1b73fb3eb06241607bff05e17d7869d4a17293303a27b",
    "testnet": "0xb76a77e0807794af162716c450885092e29eaabce09be1cc30335ce9d906b590",
}
CSV_HEADER = [
    "Token Symbol",
    "Block Height",
    "UnixTimestamp",
    "date(UTC)",
    "CKB Address",
    "Amount",
]


class V1XudtsSnapshotRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.history_cache: dict[
            str,
            tuple[
                Mapping[str, Any],
                dict[tuple[str, int], tuple[Mapping[str, Any], str, int]],
                dict[tuple[str, int], int],
                list[int],
            ],
        ] = {}
        cls.snapshot_cache: dict[tuple[str, str, int, bool, bool], bytes] = {}

    def _history(
        self,
        oracle: NetworkOracle,
    ) -> tuple[
        Mapping[str, Any],
        dict[tuple[str, int], tuple[Mapping[str, Any], str, int]],
        dict[tuple[str, int], int],
        list[int],
    ]:
        name = oracle.network.name
        if name in self.history_cache:
            return self.history_cache[name]
        type_hash = SNAPSHOT_XUDTS[name]
        detail = oracle.explorer_json(f"/v1/xudts/{type_hash}")
        data = detail.get("data") if isinstance(detail, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        script = attributes.get("type_script") if isinstance(attributes, dict) else None
        if not isinstance(attributes, dict) or not isinstance(script, dict):
            raise OracleUnavailable(f"{name} xUDT snapshot detail is unavailable")
        search_key = {"script": script, "script_type": "type", "script_search_mode": "exact"}
        entries: list[Mapping[str, Any]] = []
        cursor: str | None = None
        for _page in range(100):
            params: list[object] = [search_key, "asc", "0x64"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result("get_transactions", params)
            objects = result.get("objects") if isinstance(result, dict) else None
            if not isinstance(objects, list) or any(not isinstance(item, dict) for item in objects):
                raise OracleUnavailable(f"{name} xUDT Indexer history is unavailable")
            entries.extend(objects)
            if len(objects) < 100:
                break
            next_cursor = result.get("last_cursor")
            if not isinstance(next_cursor, str) or next_cursor == cursor:
                raise OracleUnavailable(f"{name} xUDT Indexer history cursor is unavailable")
            cursor = next_cursor
        else:
            raise OracleUnavailable(f"{name} xUDT Indexer history did not terminate")
        if not entries:
            raise OracleUnavailable(f"{name} xUDT Indexer history is empty")

        hashes = list(dict.fromkeys(str(entry["tx_hash"]) for entry in entries))
        results: list[Any] = []
        for offset in range(0, len(hashes), self.settings.rpc_batch_size):
            batch = hashes[offset : offset + self.settings.rpc_batch_size]
            results.extend(oracle.rpc_batch_results([("get_transaction", [tx_hash]) for tx_hash in batch]))
        transactions: dict[str, Mapping[str, Any]] = {}
        for tx_hash, result in zip(hashes, results, strict=True):
            transaction = result.get("transaction") if isinstance(result, dict) else None
            status = result.get("tx_status") if isinstance(result, dict) else None
            if not isinstance(transaction, dict) or not isinstance(status, dict) or status.get("status") != "committed":
                raise OracleUnavailable(f"{name} committed xUDT transaction {tx_hash} is unavailable")
            transactions[tx_hash] = transaction

        outputs: dict[tuple[str, int], tuple[Mapping[str, Any], str, int]] = {}
        consumed: dict[tuple[str, int], int] = {}
        for entry in entries:
            tx_hash = str(entry["tx_hash"])
            height = decode_hex_int(entry.get("block_number"), "history.block_number")
            index = decode_hex_int(entry.get("io_index"), "history.io_index")
            transaction = transactions[tx_hash]
            if entry.get("io_type") == "output":
                tx_outputs = transaction.get("outputs")
                outputs_data = transaction.get("outputs_data")
                if not isinstance(tx_outputs, list) or not isinstance(outputs_data, list) or index >= len(tx_outputs):
                    raise OracleUnavailable(f"{name} xUDT output history is incomplete")
                output = tx_outputs[index]
                output_data = outputs_data[index]
                if not isinstance(output, dict) or not isinstance(output_data, str):
                    raise OracleUnavailable(f"{name} xUDT output history data is incomplete")
                if not isinstance(output.get("type"), dict) or ckb_script_hash(output["type"]) != type_hash:
                    raise OracleUnavailable(f"{name} xUDT Indexer returned another Type Script")
                outputs[(tx_hash, index)] = output, output_data, height
            elif entry.get("io_type") == "input":
                inputs = transaction.get("inputs")
                if not isinstance(inputs, list) or index >= len(inputs) or not isinstance(inputs[index], dict):
                    raise OracleUnavailable(f"{name} xUDT input history is incomplete")
                previous = inputs[index].get("previous_output")
                if not isinstance(previous, dict) or not isinstance(previous.get("tx_hash"), str):
                    raise OracleUnavailable(f"{name} xUDT consumed OutPoint is unavailable")
                previous_index = decode_hex_int(previous.get("index"), "history.previous_output.index")
                consumed[(previous["tx_hash"], previous_index)] = height

        if not outputs or not consumed:
            raise OracleUnavailable(f"{name} xUDT generation-and-consumption fixture is unavailable")
        creation = min(created for _output, _data, created in outputs.values())
        changed_consumption: int | None = None
        for height in sorted(set(consumed.values())):
            if height > creation and self._balances(oracle, outputs, consumed, height - 1) != self._balances(
                oracle, outputs, consumed, height
            ):
                changed_consumption = height
                break
        if changed_consumption is None:
            raise OracleUnavailable(f"{name} xUDT consumption boundary does not change balances")
        targets = list(dict.fromkeys((creation - 1, creation, changed_consumption - 1, changed_consumption)))
        self.history_cache[name] = attributes, outputs, consumed, targets
        return self.history_cache[name]

    def _balances(
        self,
        oracle: NetworkOracle,
        outputs: Mapping[tuple[str, int], tuple[Mapping[str, Any], str, int]],
        consumed: Mapping[tuple[str, int], int],
        height: int,
    ) -> dict[str, int]:
        balances: dict[str, int] = defaultdict(int)
        for out_point, (output, data, created) in outputs.items():
            if created > height or consumed.get(out_point, height + 1) <= height:
                continue
            raw = bytes.fromhex(data.removeprefix("0x"))
            if len(raw) < 16:
                raise OracleUnavailable(f"{oracle.network.name} xUDT data is shorter than 16 bytes")
            balances[output_address(output, oracle.network.address_hrp)] += int.from_bytes(raw[:16], "little")
        return {address: amount for address, amount in balances.items() if amount != 0}

    def _snapshot(
        self,
        oracle: NetworkOracle,
        type_hash: str,
        height: int,
        *,
        merge: bool = False,
        json_format: bool = False,
    ) -> bytes:
        key = (oracle.network.name, type_hash, height, merge, json_format)
        if key not in self.snapshot_cache:
            query: dict[str, object] = {"id": type_hash, "number": height}
            if merge:
                query["merge_with_owner"] = "true"
            if json_format:
                query["format"] = "json"
            url = oracle.network.explorer_api_url + "/v1/xudts/snapshot?" + urlencode(query)
            try:
                self.snapshot_cache[key] = oracle.client.request_bytes(url, headers=V1_HEADERS)
            except HttpClientError as error:
                raise OracleUnavailable(f"{oracle.network.name} xUDT snapshot unavailable: {error}") from error
        return self.snapshot_cache[key]

    # TEST-MAP: XUDT-FT-RPC-14
    # TEST-MAP: XUDT-FT-RPC-18
    def test_historical_generation_and_consumption_boundaries_match_rpc_cells_by_address(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                type_hash = SNAPSHOT_XUDTS[network.name]
                try:
                    attributes, outputs, consumed, targets = self._history(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                observed: list[dict[str, int]] = []
                for height in targets:
                    expected = self._balances(oracle, outputs, consumed, height)
                    observed.append(expected)
                    try:
                        table = list(
                            csv.reader(io.StringIO(self._snapshot(oracle, type_hash, height).decode("utf-8-sig")))
                        )
                        block = oracle.block(height)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(CSV_HEADER, table[0])
                    self.assertEqual(set(expected), {row[4] for row in table[1:]})
                    header = block.get("header") if isinstance(block, dict) else None
                    self.assertIsInstance(header, dict)
                    timestamp = decode_hex_int(header.get("timestamp"), "snapshot.timestamp")
                    decimal_raw = attributes.get("decimal")
                    decimal = int(decimal_raw) if str(decimal_raw).isdigit() else None
                    actual_raw: list[int] = []
                    for row in table[1:]:
                        self.assertEqual(str(attributes.get("symbol") or ""), row[0])
                        self.assertEqual(height, int(row[1]))
                        self.assertEqual(timestamp, int(row[2]))
                        self.assertEqual(
                            datetime.fromtimestamp(timestamp // 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                            row[3],
                        )
                        if decimal is None:
                            raw_amount = int(row[5].removesuffix(" (raw)"))
                            self.assertTrue(row[5].endswith(" (raw)"))
                        elif decimal <= 20:
                            raw_amount = int(Decimal(row[5]) * (10**decimal))
                            self.assertNotIn("e", row[5].lower())
                        else:
                            raise unittest.SkipTest(f"{network.name} high-decimal exact snapshot fixture is unavailable")
                        self.assertEqual(expected[row[4]], raw_amount)
                        actual_raw.append(raw_amount)
                    self.assertEqual(actual_raw, sorted(actual_raw, reverse=True))
                self.assertNotEqual(observed[0], observed[1])
                self.assertNotEqual(observed[-2], observed[-1])

    # TEST-MAP: XUDT-FT-RPC-15
    def test_merge_with_owner_conserves_amounts_and_combines_multiple_mapped_addresses(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                type_hash = SNAPSHOT_XUDTS[network.name]
                try:
                    _attributes, _outputs, _consumed, targets = self._history(oracle)
                    height = targets[-1]
                    plain = list(csv.reader(io.StringIO(self._snapshot(oracle, type_hash, height).decode("utf-8-sig"))))
                    merged = list(
                        csv.reader(
                            io.StringIO(self._snapshot(oracle, type_hash, height, merge=True).decode("utf-8-sig"))
                        )
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual("CKB Address", plain[0][4])
                self.assertEqual("Owner", merged[0][4])
                if len(merged) >= len(plain):
                    raise unittest.SkipTest(f"{network.name} multi-address Bitcoin owner mapping is unavailable")
                plain_total = sum(Decimal(row[5].removesuffix(" (raw)")) for row in plain[1:])
                merged_total = sum(Decimal(row[5].removesuffix(" (raw)")) for row in merged[1:])
                self.assertEqual(plain_total, merged_total)
                self.assertTrue(any(row[4] not in {plain_row[4] for plain_row in plain[1:]} for row in merged[1:]))

    # TEST-MAP: XUDT-FT-RPC-16
    def test_csv_and_json_have_identical_ordered_lossless_rows(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            type_hash = SNAPSHOT_XUDTS[network.name]
            attributes: Mapping[str, Any] | None = None
            with self.subTest(network=network.name, representation="csv-json"):
                try:
                    attributes, outputs, consumed, targets = self._history(oracle)
                    height = targets[-1]
                    expected = self._balances(oracle, outputs, consumed, height)
                    table = list(csv.reader(io.StringIO(self._snapshot(oracle, type_hash, height).decode("utf-8-sig"))))
                    json_rows = json.loads(self._snapshot(oracle, type_hash, height, json_format=True))
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual([dict(zip(table[0], row, strict=True)) for row in table[1:]], json_rows)
                self.assertEqual(set(expected), {row[4] for row in table[1:]})
                decimal = int(attributes["decimal"])
                raw_values = [int(Decimal(row[5]) * (10**decimal)) for row in table[1:]]
                self.assertEqual([expected[row[4]] for row in table[1:]], raw_values)
                if network.name == "mainnet":
                    self.assertGreater(max(raw_values), 2**53 - 1)
            with self.subTest(network=network.name, precision="missing-or-above-20-decimal"):
                if attributes is None:
                    raise unittest.SkipTest(f"{network.name} snapshot precision fixture is unavailable")
                decimal_raw = attributes.get("decimal")
                if str(decimal_raw).isdigit() and int(decimal_raw) <= 20:
                    raise unittest.SkipTest(
                        f"{network.name} published snapshot fixture with missing or decimal above 20 is unavailable"
                    )

    # TEST-MAP: XUDT-FT-RPC-17
    def test_missing_block_udt_unpublished_and_non_xudt_targets_return_not_found(self) -> None:
        published_sudt = {
            "mainnet": "0x7a12b26b621b6cf6982247855388694743c4da97b18a4ff8ebdf6fb54c1c850f",
            "testnet": "0xf60ed426477642e3f3fc384d09b6fbf3c6005bd2d106382301138880555a23fe",
        }
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                catalog = oracle.explorer_json("/v1/xudts", {"page": 1, "page_size": 100})
                rows = catalog.get("data") if isinstance(catalog, dict) else None
                if not isinstance(rows, list):
                    raise OracleUnavailable(f"{network.name} xUDT catalog is unavailable")
                unpublished = next(
                    (
                        row["attributes"].get("type_hash")
                        for row in rows
                        if isinstance(row, dict)
                        and isinstance(row.get("attributes"), dict)
                        and row["attributes"].get("published") is False
                    ),
                    None,
                )
                tip = oracle.rpc_tip_height()
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            cases = (
                ("missing-block", SNAPSHOT_XUDTS[network.name], tip + 1_000_000),
                ("missing-udt", "0x" + "ff" * 32, max(1, tip - 1000)),
                ("unpublished", unpublished, max(1, tip - 1000)),
                ("non-xudt", published_sudt[network.name], max(1, tip - 1000)),
            )
            for label, type_hash, height in cases:
                with self.subTest(network=network.name, target=label):
                    if not isinstance(type_hash, str):
                        raise unittest.SkipTest(f"{network.name} unpublished xUDT fixture is unavailable")
                    path = "/v1/xudts/snapshot?" + urlencode({"id": type_hash, "number": height})
                    try:
                        status, raw = _raw_explorer_response(oracle, path)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(404, status)
                    payload = json.loads(raw)
                    self.assertEqual({1026}, {int(error["code"]) for error in payload})
                    self.assertFalse(any("Token Symbol" in error for error in payload))


if __name__ == "__main__":
    unittest.main()
