from __future__ import annotations

import json
import unittest
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import quote

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response
from tests.token_udt.test_v1_omiga_inscriptions_download_csv import CLOSED_FIXTURES


INFO_CODE_HASHES = {
    "mainnet": "0x5c33fc69bd72e895a63176147c6ab0bb5758d1c7a32e0914f99f9ec1bed90d41",
    "testnet": "0x50fdea2d0030a8d0b3d69f883b471cab2a29cae6f01923f19cecac0f27fdaaa6",
}
STANDALONE_FIXTURES = {
    "mainnet": "0x337a6180ec47adb81b4024688a0e196aca19cbe14e7f4918751f492b38cbb457",
    "testnet": "0x0c5375feaaa7dd2a98807444b9bf3d218d3f5d36063e07fbc6c41dbda2fab936",
}
STATUS_BY_BYTE = {0: "minting", 1: "closed", 2: "rebase_start"}


class V1OmigaInscriptionsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _attributes(
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
        self.assertEqual("udt", data.get("type"))
        return attributes

    def _parse_info_data(self, value: str) -> Mapping[str, Any]:
        raw = bytes.fromhex(value.removeprefix("0x"))
        if len(raw) < 68:
            raise OracleUnavailable("Omiga Info Cell data is too short")
        offset = 0
        decimal = raw[offset]
        offset += 1
        name_size = raw[offset]
        offset += 1
        name = raw[offset : offset + name_size].decode("utf-8")
        offset += name_size
        symbol_size = raw[offset]
        offset += 1
        symbol = raw[offset : offset + symbol_size].decode("utf-8")
        offset += symbol_size
        if len(raw) < offset + 65:
            raise OracleUnavailable("Omiga Info Cell data fields are incomplete")
        udt_hash = "0x" + raw[offset : offset + 32].hex()
        offset += 32
        expected_supply = int.from_bytes(raw[offset : offset + 16], "little")
        offset += 16
        mint_limit = int.from_bytes(raw[offset : offset + 16], "little")
        offset += 16
        mint_status = raw[offset]
        return {
            "decimal": decimal,
            "full_name": name or None,
            "symbol": symbol or None,
            "type_hash": udt_hash,
            "expected_supply": expected_supply,
            "mint_limit": mint_limit,
            "mint_status": STATUS_BY_BYTE.get(mint_status),
        }

    def _matching_info_output(
        self,
        oracle: NetworkOracle,
        detail: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
        args = detail.get("inscription_info_id")
        if not isinstance(args, str):
            raise OracleUnavailable(f"{oracle.network.name} Omiga Info args are unavailable")
        info_script = {
            "code_hash": INFO_CODE_HASHES[oracle.network.name],
            "hash_type": "type",
            "args": args,
        }
        if ckb_script_hash(info_script) != detail.get("info_type_hash"):
            raise AssertionError(f"{oracle.network.name} Omiga Info Type Hash mismatches its script")
        search_key = {"script": info_script, "script_type": "type", "script_search_mode": "exact"}
        history = oracle.rpc_result("get_transactions", [search_key, "asc", "0x64"])
        entries = history.get("objects") if isinstance(history, dict) else None
        if not isinstance(entries, list):
            raise OracleUnavailable(f"{oracle.network.name} Omiga Info history is unavailable")
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("io_type") != "output":
                continue
            tx_hash = entry.get("tx_hash")
            if not isinstance(tx_hash, str):
                continue
            result = oracle.rpc_result("get_transaction", [tx_hash])
            transaction = result.get("transaction") if isinstance(result, dict) else None
            status = result.get("tx_status") if isinstance(result, dict) else None
            if not isinstance(transaction, dict) or not isinstance(status, dict):
                raise OracleUnavailable(f"{oracle.network.name} Omiga Info transaction is unavailable")
            index = decode_hex_int(entry.get("io_index"), "info.io_index")
            outputs = transaction.get("outputs")
            outputs_data = transaction.get("outputs_data")
            if (
                not isinstance(outputs, list)
                or not isinstance(outputs_data, list)
                or index >= len(outputs)
                or index >= len(outputs_data)
                or not isinstance(outputs[index], dict)
                or not isinstance(outputs_data[index], str)
            ):
                raise OracleUnavailable(f"{oracle.network.name} Omiga Info output is unavailable")
            parsed = self._parse_info_data(outputs_data[index])
            if parsed.get("type_hash") == detail.get("type_hash") and parsed.get("mint_status") == detail.get(
                "mint_status"
            ):
                block_hash = status.get("block_hash")
                if not isinstance(block_hash, str):
                    raise OracleUnavailable(f"{oracle.network.name} Omiga Info block is unavailable")
                block = oracle.block_by_hash(block_hash)
                self.assertEqual("committed", status.get("status"))
                self.assertEqual(info_script, outputs[index].get("type"))
                return parsed, block, info_script
        raise OracleUnavailable(f"{oracle.network.name} matching Omiga Info Cell is unavailable")

    def _live_cells(
        self,
        oracle: NetworkOracle,
        script: Mapping[str, Any],
    ) -> list[Mapping[str, Any]]:
        search_key = {"script": script, "script_type": "type", "script_search_mode": "exact"}
        cells: list[Mapping[str, Any]] = []
        cursor: str | None = None
        for _page in range(100):
            params: list[object] = [search_key, "asc", "0x64"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result("get_cells", params)
            objects = result.get("objects") if isinstance(result, dict) else None
            if not isinstance(objects, list) or any(not isinstance(item, dict) for item in objects):
                raise OracleUnavailable(f"{oracle.network.name} Omiga live Cells are unavailable")
            cells.extend(objects)
            if len(objects) < 100:
                return cells
            next_cursor = result.get("last_cursor")
            if not isinstance(next_cursor, str) or next_cursor == cursor:
                raise OracleUnavailable(f"{oracle.network.name} Omiga live Cell cursor is unavailable")
            cursor = next_cursor
        raise OracleUnavailable(f"{oracle.network.name} Omiga live Cell pagination did not terminate")

    # TEST-MAP: OMIGA-RPC-05
    def test_udt_hash_and_info_hash_select_the_same_latest_lifecycle_stage(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                info_hash, closed_type_hash = CLOSED_FIXTURES[network.name]
                try:
                    by_info = self._attributes(oracle, info_hash)
                    by_udt = self._attributes(oracle, str(by_info["type_hash"]))
                    closed = self._attributes(oracle, info_hash, status="closed")
                except (OracleUnavailable, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(by_info, by_udt)
                self.assertEqual("rebase_start", by_info.get("mint_status"))
                self.assertEqual(info_hash, by_info.get("info_type_hash"))
                self.assertEqual(closed_type_hash, by_info.get("pre_udt_hash"))
                self.assertGreater(int(by_info["created_at"]), int(closed["created_at"]))

    # TEST-MAP: OMIGA-RPC-06
    def test_closed_info_hash_selects_only_the_exact_closed_predecessor(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                info_hash, closed_type_hash = CLOSED_FIXTURES[network.name]
                try:
                    closed = self._attributes(oracle, info_hash, status="closed")
                    current = self._attributes(oracle, info_hash)
                    parsed, _block, _script = self._matching_info_output(oracle, closed)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual("closed", closed.get("mint_status"))
                self.assertEqual("closed", parsed.get("mint_status"))
                self.assertEqual(info_hash, closed.get("info_type_hash"))
                self.assertEqual(closed_type_hash, closed.get("type_hash"))
                self.assertNotEqual(current.get("type_hash"), closed.get("type_hash"))

    # TEST-MAP: OMIGA-RPC-07
    def test_current_fields_info_data_type_script_and_live_supply_match_rpc_indexer(self) -> None:
        observed_exact_integers: list[int] = []
        string_fields = (
            "total_amount",
            "addresses_count",
            "decimal",
            "h24_ckb_transactions_count",
            "created_at",
            "holders_count",
        )
        required_fields = (
            "mint_status",
            "mint_limit",
            "expected_supply",
            "inscription_info_id",
            "info_type_hash",
            "pre_udt_hash",
            "is_repeated_symbol",
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                info_hash, closed_type_hash = CLOSED_FIXTURES[network.name]
                try:
                    detail = self._attributes(oracle, info_hash)
                    parsed, block, info_script = self._matching_info_output(oracle, detail)
                    type_script = detail.get("type_script")
                    if not isinstance(type_script, dict):
                        raise OracleUnavailable(f"{network.name} Omiga Type Script is unavailable")
                    cells = self._live_cells(oracle, type_script)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertTrue(all(field in detail for field in required_fields))
                self.assertEqual(detail.get("type_hash"), ckb_script_hash(type_script))
                self.assertEqual(detail.get("info_type_hash"), ckb_script_hash(info_script))
                self.assertEqual(detail.get("inscription_info_id"), info_script.get("args"))
                self.assertEqual(closed_type_hash, detail.get("pre_udt_hash"))
                self.assertIsInstance(detail.get("is_repeated_symbol"), bool)
                self.assertEqual(detail.get("full_name"), parsed.get("full_name"))
                self.assertEqual(detail.get("symbol"), parsed.get("symbol"))
                self.assertEqual(detail.get("type_hash"), parsed.get("type_hash"))
                self.assertEqual(detail.get("mint_status"), parsed.get("mint_status"))
                self.assertEqual(int(detail["decimal"]), parsed.get("decimal"))
                self.assertEqual(Decimal(str(parsed["mint_limit"])), Decimal(str(detail["mint_limit"])))
                self.assertEqual(
                    Decimal(str(parsed["expected_supply"])), Decimal(str(detail["expected_supply"]))
                )
                observed_exact_integers.extend(
                    (int(parsed["mint_limit"]), int(parsed["expected_supply"]))
                )
                header = block.get("header") if isinstance(block, dict) else None
                self.assertIsInstance(header, dict)
                self.assertEqual(
                    int(detail["created_at"]),
                    decode_hex_int(header.get("timestamp"), "info.block.timestamp"),
                )

                self.assertGreater(len(cells), 0)
                total_amount = 0
                for cell in cells:
                    output = cell.get("output")
                    output_data = cell.get("output_data")
                    if not isinstance(output, dict) or not isinstance(output_data, str):
                        raise OracleUnavailable(f"{network.name} Omiga live Cell is incomplete")
                    self.assertEqual(type_script, output.get("type"))
                    raw = bytes.fromhex(output_data.removeprefix("0x"))
                    self.assertGreaterEqual(len(raw), 16)
                    total_amount += int.from_bytes(raw, "little")
                self.assertEqual(total_amount, int(detail["total_amount"]))
                for field in string_fields:
                    self.assertIsInstance(detail.get(field), str)
                    self.assertRegex(str(detail[field]), r"^\d+$")
                    self.assertNotIn("e", str(detail[field]).lower())
                for field in ("mint_limit", "expected_supply"):
                    self.assertIsInstance(detail.get(field), str)
                    self.assertRegex(str(detail[field]), r"^\d+(?:\.0+)?$")
                    self.assertNotIn("e", str(detail[field]).lower())
        self.assertTrue(any(value > 2**53 - 1 for value in observed_exact_integers))

    # TEST-MAP: OMIGA-RPC-08
    def test_malformed_missing_and_closed_stage_mismatch_return_isolated_errors(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                standalone = self._attributes(oracle, STANDALONE_FIXTURES[network.name])
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            info_hash = standalone.get("info_type_hash")
            if not isinstance(info_hash, str):
                raise unittest.SkipTest(f"{network.name} standalone Omiga Info Hash is unavailable")
            cases = (
                ("malformed", "not-a-type-hash", "", 422, 1025),
                ("missing", "0x" + "ff" * 32, "", 404, 1026),
                ("closed-stage-mismatch", info_hash, "?status=closed", 404, 1026),
            )
            for label, identifier, query, expected_status, expected_code in cases:
                with self.subTest(network=network.name, identifier=label):
                    try:
                        status, raw = _raw_explorer_response(
                            oracle,
                            "/v1/omiga_inscriptions/" + quote(identifier, safe="") + query,
                        )
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(expected_status, status)
                    payload = json.loads(raw)
                    self.assertIsInstance(payload, list)
                    self.assertEqual({expected_code}, {int(error["code"]) for error in payload})
                    self.assertFalse(any("data" in error for error in payload))


if __name__ == "__main__":
    unittest.main()
