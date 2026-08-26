from __future__ import annotations

import json
import unittest
from typing import Any, Mapping
from urllib.parse import quote

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response
from tests.token_udt.test_v1_xudts_snapshot import SNAPSHOT_XUDTS


VALID_TAGS = {
    "invalid",
    "suspicious",
    "out-of-length-range",
    "rgb++",
    "layer-1-asset",
    "supply-limited",
    "utility",
    "layer-2-asset",
    "supply-unlimited",
}
STRING_FIELDS = (
    "total_amount",
    "addresses_count",
    "holders_count",
    "decimal",
    "h24_ckb_transactions_count",
    "created_at",
)


class V1XudtsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _attributes(self, oracle: NetworkOracle, type_hash: str) -> Mapping[str, Any]:
        payload = oracle.explorer_json(f"/v1/xudts/{type_hash}")
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        if not isinstance(attributes, dict):
            raise OracleUnavailable(f"{oracle.network.name} xUDT detail is unavailable")
        self.assertEqual("udt", data.get("type"))
        return attributes

    def _compatible_fixture(self, oracle: NetworkOracle) -> tuple[str, object]:
        payload = oracle.explorer_json(
            "/v1/xudts", {"type": "xudt_compatible", "page": 1, "page_size": 100}
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise OracleUnavailable(f"{oracle.network.name} xUDT-compatible catalog is unavailable")
        for row in data:
            attributes = row.get("attributes") if isinstance(row, dict) else None
            if (
                isinstance(attributes, dict)
                and attributes.get("published") is True
                and attributes.get("udt_type") == "xudt_compatible"
                and str(attributes.get("decimal", "")).isdigit()
                and isinstance(attributes.get("type_hash"), str)
            ):
                return attributes["type_hash"], attributes.get("xudt_tags")
        raise OracleUnavailable(f"{oracle.network.name} published xUDT-compatible fixture is unavailable")

    # TEST-MAP: XUDT-FT-RPC-07
    def test_published_xudt_and_compatible_details_match_rpc_type_scripts(self) -> None:
        display_fields = ("symbol", "full_name", "description", "icon_file", "operator_website", "email")
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                compatible_hash, compatible_tags = self._compatible_fixture(oracle)
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            fixtures = (
                ("xudt", SNAPSHOT_XUDTS[network.name], None),
                ("xudt_compatible", compatible_hash, compatible_tags),
            )
            for expected_type, type_hash, catalog_tags in fixtures:
                with self.subTest(network=network.name, udt_type=expected_type):
                    try:
                        attributes = self._attributes(oracle, type_hash)
                        script = attributes.get("type_script")
                        if not isinstance(script, dict):
                            raise OracleUnavailable(f"{network.name} xUDT Type Script is unavailable")
                        search_key = {"script": script, "script_type": "type", "script_search_mode": "exact"}
                        history = oracle.rpc_result("get_transactions", [search_key, "asc", "0x64"])
                        entries = history.get("objects") if isinstance(history, dict) else None
                        output_entry = next(
                            (entry for entry in entries or [] if isinstance(entry, dict) and entry.get("io_type") == "output"),
                            None,
                        )
                        if not isinstance(output_entry, dict):
                            raise OracleUnavailable(f"{network.name} xUDT Type Script history is unavailable")
                        result = oracle.rpc_result("get_transaction", [output_entry["tx_hash"]])
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict) or not isinstance(status, dict):
                            raise OracleUnavailable(f"{network.name} xUDT transaction is unavailable")
                        index = decode_hex_int(output_entry.get("io_index"), "xudt.io_index")
                        outputs = transaction.get("outputs")
                        if not isinstance(outputs, list) or index >= len(outputs) or not isinstance(outputs[index], dict):
                            raise OracleUnavailable(f"{network.name} xUDT transaction output is unavailable")
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error

                    self.assertEqual("committed", status.get("status"))
                    self.assertEqual(type_hash, attributes.get("type_hash"))
                    self.assertEqual(type_hash, ckb_script_hash(script))
                    self.assertEqual(script, outputs[index].get("type"))
                    self.assertEqual(expected_type, attributes.get("udt_type"))
                    self.assertIs(attributes.get("published"), True)
                    self.assertTrue(all(field in attributes for field in display_fields))
                    self.assertTrue(
                        all(attributes[field] is None or isinstance(attributes[field], str) for field in display_fields)
                    )
                    for field in STRING_FIELDS:
                        self.assertIsInstance(attributes.get(field), str)
                        self.assertRegex(attributes[field], r"^\d+$")
                    tags = attributes.get("xudt_tags")
                    self.assertTrue(tags is None or isinstance(tags, list))
                    if isinstance(tags, list):
                        self.assertEqual(len(tags), len(set(tags)))
                        self.assertTrue(set(tags).issubset(VALID_TAGS))
                    if expected_type == "xudt_compatible":
                        self.assertEqual(catalog_tags, tags)

    # TEST-MAP: XUDT-FT-RPC-08
    def test_malformed_missing_and_unpublished_type_hashes_return_isolated_errors(self) -> None:
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
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            cases = (
                ("malformed", "not-a-type-hash", 422, 1025),
                ("missing", "0x" + "ff" * 32, 404, 1026),
                ("unpublished", unpublished, 404, 1026),
            )
            for label, identifier, expected_status, expected_code in cases:
                with self.subTest(network=network.name, identifier=label):
                    if not isinstance(identifier, str):
                        raise unittest.SkipTest(f"{network.name} unpublished xUDT fixture is unavailable")
                    try:
                        status, raw = _raw_explorer_response(
                            oracle, "/v1/xudts/" + quote(identifier, safe="")
                        )
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(expected_status, status)
                    payload = json.loads(raw)
                    self.assertEqual({expected_code}, {int(error["code"]) for error in payload})
                    self.assertFalse(any("data" in error for error in payload))


if __name__ == "__main__":
    unittest.main()
