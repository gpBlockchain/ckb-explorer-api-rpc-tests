from __future__ import annotations

import json
import unittest
from typing import Any, Mapping
from urllib.parse import quote

from ckb_rpc_correctness.ckb import ckb_script_hash
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response
from tests.token_udt import test_v1_udts_show as show_support


LIVE_UDTS = show_support.LIVE_UDTS


class V1UdtsHolderAllocationRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _allocation(self, oracle: NetworkOracle, type_hash: str) -> Mapping[str, Any]:
        payload = oracle.explorer_json(f"/v1/udts/{type_hash}/holder_allocation")
        if not isinstance(payload, dict):
            raise OracleUnavailable(f"{oracle.network.name} UDT holder allocation is unavailable")
        return payload

    # TEST-MAP: UDT-CATALOG-RPC-15
    def test_default_bitcoin_count_and_available_contract_holder_counts_follow_live_type_cells(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            type_hash = LIVE_UDTS[network.name]
            allocation: Mapping[str, Any] | None = None
            with self.subTest(network=network.name, allocation="default-zero"):
                try:
                    allocation = self._allocation(oracle, type_hash)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual({"btc_holder_count", "lock_hashes"}, set(allocation))
                self.assertIsInstance(allocation["btc_holder_count"], int)
                self.assertIsInstance(allocation["lock_hashes"], list)
                self.assertGreaterEqual(allocation["btc_holder_count"], 0)
                if not allocation["lock_hashes"]:
                    self.assertEqual(0, allocation["btc_holder_count"])

            with self.subTest(network=network.name, allocation="known-contracts"):
                if allocation is None:
                    raise unittest.SkipTest(f"{network.name} holder allocation fact is unavailable")
                lock_hashes = allocation["lock_hashes"]
                if len(lock_hashes) < 2:
                    raise unittest.SkipTest(
                        f"{network.name} published UDT with multiple holder-allocation contracts is unavailable"
                    )
                try:
                    details = oracle.explorer_json(f"/v1/udts/{type_hash}")
                    data = details.get("data") if isinstance(details, dict) else None
                    attributes = data.get("attributes") if isinstance(data, dict) else None
                    script = attributes.get("type_script") if isinstance(attributes, dict) else None
                    if not isinstance(script, dict):
                        raise OracleUnavailable(f"{network.name} UDT Type Script is unavailable")
                    helper = show_support.V1UdtsShowRpcCorrectnessTests()
                    cells = helper._live_cells(oracle, script)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                seen_contracts: set[tuple[str, str]] = set()
                for contract in lock_hashes:
                    self.assertIsInstance(contract, dict)
                    self.assertIsInstance(contract.get("name"), str)
                    self.assertIsInstance(contract.get("code_hash"), str)
                    self.assertIn(contract.get("hash_type"), {"data", "data1", "type"})
                    self.assertIsInstance(contract.get("holder_count"), int)
                    key = (contract["code_hash"], contract["hash_type"])
                    self.assertNotIn(key, seen_contracts)
                    seen_contracts.add(key)
                    holders = {
                        ckb_script_hash(cell["output"]["lock"])
                        for cell in cells
                        if isinstance(cell.get("output"), dict)
                        and isinstance(cell["output"].get("lock"), dict)
                        and cell["output"]["lock"].get("code_hash") == contract["code_hash"]
                        and cell["output"]["lock"].get("hash_type") == contract["hash_type"]
                    }
                    self.assertEqual(len(holders), contract["holder_count"])

    # TEST-MAP: UDT-CATALOG-RPC-16
    def test_invalid_missing_and_unpublished_targets_return_errors_without_allocation_data(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                catalog_helper = show_support.V1UdtsShowRpcCorrectnessTests()
                unpublished = next(
                    (row.get("type_hash") for row in catalog_helper._catalog(oracle) if row.get("published") is False),
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
                            oracle,
                            "/v1/udts/" + quote(identifier, safe="") + "/holder_allocation",
                        )
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(expected_status, status)
                    payload = json.loads(raw)
                    self.assertEqual({expected_code}, {int(error["code"]) for error in payload})
                    self.assertFalse(any("btc_holder_count" in error or "lock_hashes" in error for error in payload))


if __name__ == "__main__":
    unittest.main()
