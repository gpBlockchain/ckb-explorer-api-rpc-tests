from __future__ import annotations

import json
import re
import unittest
from typing import Any, Mapping
from urllib.parse import quote

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


LIVE_UDTS = {
    "mainnet": "0x38928268eaffd58e25605a923cf61602e914cb8365ba00131ec0bc004cc753d1",
    "testnet": "0xf60ed426477642e3f3fc384d09b6fbf3c6005bd2d106382301138880555a23fe",
}
STRING_FIELDS = (
    "total_amount",
    "addresses_count",
    "holders_count",
    "decimal",
    "h24_ckb_transactions_count",
)


class V1UdtsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _attributes(self, oracle: NetworkOracle, type_hash: str) -> Mapping[str, Any]:
        payload = oracle.explorer_json(f"/v1/udts/{type_hash}")
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        if not isinstance(attributes, dict):
            raise OracleUnavailable(f"{oracle.network.name} UDT detail is unavailable")
        self.assertEqual("udt", data.get("type"))
        return attributes

    def _catalog(self, oracle: NetworkOracle) -> list[Mapping[str, Any]]:
        first = oracle.explorer_json("/v1/udts", {"page": 1, "page_size": 100})
        data = first.get("data") if isinstance(first, dict) else None
        meta = first.get("meta") if isinstance(first, dict) else None
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise OracleUnavailable(f"{oracle.network.name} UDT catalog is unavailable")
        rows = list(data)
        try:
            total = int(meta["total"])
        except (KeyError, TypeError, ValueError) as error:
            raise OracleUnavailable(f"{oracle.network.name} UDT catalog total is unavailable") from error
        for page in range(2, (total + 99) // 100 + 1):
            payload = oracle.explorer_json("/v1/udts", {"page": page, "page_size": 100})
            current = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(current, list):
                raise OracleUnavailable(f"{oracle.network.name} UDT catalog page {page} is unavailable")
            rows.extend(current)
        attributes: list[Mapping[str, Any]] = []
        for row in rows:
            item = row.get("attributes") if isinstance(row, dict) else None
            if not isinstance(item, dict):
                raise OracleUnavailable(f"{oracle.network.name} UDT catalog row is unavailable")
            attributes.append(item)
        return attributes

    def _live_cells(self, oracle: NetworkOracle, script: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        search_key = {"script": script, "script_type": "type", "script_search_mode": "exact"}
        cells: list[Mapping[str, Any]] = []
        cursor: str | None = None
        for _page in range(100):
            params: list[object] = [search_key, "asc", "0x64"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result("get_cells", params)
            objects = result.get("objects") if isinstance(result, dict) else None
            if not isinstance(objects, list):
                raise OracleUnavailable(f"{oracle.network.name} Indexer get_cells result is unavailable")
            if any(not isinstance(cell, dict) for cell in objects):
                raise OracleUnavailable(f"{oracle.network.name} Indexer get_cells row is unavailable")
            cells.extend(objects)
            if len(objects) < 100:
                return cells
            next_cursor = result.get("last_cursor")
            if not isinstance(next_cursor, str) or next_cursor == cursor:
                raise OracleUnavailable(f"{oracle.network.name} Indexer get_cells cursor is unavailable")
            cursor = next_cursor
        raise OracleUnavailable(f"{oracle.network.name} Indexer get_cells pagination did not terminate")

    # TEST-MAP: UDT-CATALOG-RPC-08
    # TEST-MAP: UDT-CATALOG-RPC-17
    def test_published_identity_issuer_creation_time_and_live_supply_match_rpc_indexer(self) -> None:
        display_fields = ("symbol", "full_name", "description", "icon_file", "operator_website", "email")
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                type_hash = LIVE_UDTS[network.name]
                try:
                    attributes = self._attributes(oracle, type_hash)
                    script = attributes.get("type_script")
                    if not isinstance(script, dict):
                        raise OracleUnavailable(f"{network.name} UDT Type Script is unavailable")
                    cells = self._live_cells(oracle, script)
                    issuer = attributes.get("issuer_address")
                    if not isinstance(issuer, str):
                        raise OracleUnavailable(f"{network.name} UDT issuer address is unavailable")
                    issuer_payload = oracle.explorer_json(f"/v1/addresses/{quote(issuer, safe='')}")
                    issuer_data = issuer_payload.get("data") if isinstance(issuer_payload, dict) else None
                    issuer_attributes = issuer_data[0].get("attributes") if isinstance(issuer_data, list) and issuer_data else None
                    issuer_lock = issuer_attributes.get("lock_script") if isinstance(issuer_attributes, dict) else None
                    if not isinstance(issuer_lock, dict):
                        raise OracleUnavailable(f"{network.name} UDT issuer Lock Script is unavailable")
                    search_key = {"script": script, "script_type": "type", "script_search_mode": "exact"}
                    transactions = oracle.rpc_result("get_transactions", [search_key, "asc", "0x1"])
                    objects = transactions.get("objects") if isinstance(transactions, dict) else None
                    if not isinstance(objects, list) or not objects or not isinstance(objects[0], dict):
                        raise OracleUnavailable(f"{network.name} Indexer UDT creation transaction is unavailable")
                    creation_height = decode_hex_int(objects[0].get("block_number"), "creation.block_number")
                    creation_block = oracle.block(creation_height)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual(type_hash, attributes.get("type_hash"))
                self.assertEqual(type_hash, ckb_script_hash(script))
                self.assertEqual("sudt", attributes.get("udt_type"))
                self.assertIs(attributes.get("published"), True)
                self.assertTrue(all(field in attributes for field in display_fields))
                self.assertTrue(all(attributes[field] is None or isinstance(attributes[field], str) for field in display_fields))
                self.assertEqual(script.get("args"), ckb_script_hash(issuer_lock))
                header = creation_block.get("header") if isinstance(creation_block, dict) else None
                self.assertIsInstance(header, dict)
                self.assertEqual(
                    decode_hex_int(header.get("timestamp"), "creation.timestamp"),
                    int(attributes["created_at"]),
                )
                self.assertGreater(len(cells), 0)
                total_amount = 0
                for cell in cells:
                    output = cell.get("output")
                    data = cell.get("output_data")
                    if not isinstance(output, dict) or not isinstance(data, str):
                        raise OracleUnavailable(f"{network.name} Indexer live UDT Cell is incomplete")
                    self.assertEqual(script, output.get("type"))
                    self.assertEqual(type_hash, ckb_script_hash(output["type"]))
                    raw = bytes.fromhex(data.removeprefix("0x"))
                    self.assertGreaterEqual(len(raw), 16)
                    total_amount += int.from_bytes(raw[:16], "little")
                self.assertEqual(total_amount, int(attributes["total_amount"]))

    # TEST-MAP: UDT-CATALOG-RPC-09
    def test_counts_amount_decimal_and_masked_email_are_lossless_strings(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name, shape="detail-strings"):
                oracle = NetworkOracle(network, self.settings)
                try:
                    attributes = self._attributes(oracle, LIVE_UDTS[network.name])
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                for field in STRING_FIELDS:
                    self.assertIsInstance(attributes.get(field), str)
                    self.assertRegex(attributes[field], r"^\d+$")
                    self.assertNotIn("e", attributes[field].lower())
                    self.assertEqual(attributes[field], str(int(attributes[field])))
                email = attributes.get("email")
                self.assertIsInstance(email, str)
                self.assertRegex(email, r"^[^@]{2}\*+@\*+[^@]{2}$")

        network = next(item for item in self.settings.networks if item.name == "mainnet")
        oracle = NetworkOracle(network, self.settings)
        try:
            catalog = self._catalog(oracle)
            candidate = next(
                row
                for row in catalog
                if row.get("published") is True
                and isinstance(row.get("email"), str)
                and "*" in row["email"]
                and all(isinstance(row.get(field), str) and row[field].isdigit() for field in STRING_FIELDS)
                and any(int(row[field]) > 2**53 - 1 for field in STRING_FIELDS)
            )
            attributes = self._attributes(oracle, str(candidate["type_hash"]))
        except (OracleUnavailable, StopIteration) as error:
            raise unittest.SkipTest(f"mainnet large masked UDT detail fixture is unavailable: {error}") from error
        self.assertTrue(any(int(attributes[field]) > 2**53 - 1 for field in STRING_FIELDS))
        for field in STRING_FIELDS:
            self.assertEqual(candidate[field], attributes[field])
            self.assertEqual(attributes[field], str(int(attributes[field])))
        self.assertRegex(str(attributes["email"]), r"^[^@]{2}\*+@\*+[^@]{2}$")

    # TEST-MAP: UDT-CATALOG-RPC-10
    def test_invalid_missing_and_unpublished_type_hashes_return_isolated_errors(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                unpublished = next(
                    (row.get("type_hash") for row in self._catalog(oracle) if row.get("published") is False),
                    None,
                )
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            cases = (
                ("invalid", "not-a-type-hash", 422, 1025),
                ("missing", "0x" + "ff" * 32, 404, 1026),
                ("unpublished", unpublished, 404, 1026),
            )
            for label, identifier, expected_status, expected_code in cases:
                with self.subTest(network=network.name, identifier=label):
                    if not isinstance(identifier, str):
                        raise unittest.SkipTest(f"{network.name} unpublished sUDT fixture is unavailable")
                    try:
                        status, raw = _raw_explorer_response(
                            oracle, "/v1/udts/" + quote(identifier, safe="")
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
