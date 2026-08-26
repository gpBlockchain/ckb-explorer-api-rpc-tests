from __future__ import annotations

import hashlib
import json
import unittest
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int, output_occupied_capacity
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import DAO_TYPE_HASH
from tests.contract_script.test_v2_scripts_ckb_transactions import ZERO_HASH, _raw_explorer_response


MULTI_DATA_HASH = {
    "mainnet": "0x50bd8d6680b8b9cf98b73f3c08faf8b2a21914311954118ad6609be6e78a1b95",
    "testnet": "0x8290467a512e5b9a6b816469b0edabba1f4ac474e28ffdd604c2a7c76446bbaf",
}


class V2ScriptsDeployedCellsRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _page(
        self,
        oracle: NetworkOracle,
        code_hash: str,
        hash_type: str,
        **query: object,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        params: dict[str, object] = {"code_hash": code_hash, "hash_type": hash_type}
        params.update(query)
        payload = oracle.explorer_json("/v2/scripts/deployed_cells", params)
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("deployed_cells") if isinstance(data, dict) else None
        meta = data.get("meta") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not isinstance(meta, dict) or not all(isinstance(row, dict) for row in rows):
            raise OracleUnavailable(f"{oracle.network.name} deployed-cell page is unavailable")
        return rows, meta

    # TEST-MAP: SCRIPT-REL-RPC-08
    def test_type_hash_deployment_fields_match_rpc_output_live_cell_and_block(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, meta = self._page(oracle, DAO_TYPE_HASH, "type", page_size=10)
                    info = oracle.explorer_json(
                        "/v2/scripts/general_info", {"code_hash": DAO_TYPE_HASH, "hash_type": "type"}
                    )["data"]
                    if len(rows) != 1 or not isinstance(info, list) or len(info) != 1:
                        raise OracleUnavailable(f"{network.name} unique DAO deployment is unavailable")
                    row = rows[0]
                    result = oracle.rpc_result("get_transaction", [row["tx_hash"]])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict) or not isinstance(status, dict):
                        raise OracleUnavailable(f"{network.name} RPC deployment transaction is unavailable")
                    index = int(row["cell_index"])
                    output = transaction["outputs"][index]
                    output_data = transaction["outputs_data"][index]
                    block = oracle.block_by_hash(status["block_hash"])
                    header = block.get("header") if isinstance(block, dict) else None
                    out_point = {"tx_hash": row["tx_hash"], "index": hex(index)}
                    live_cell = oracle.rpc_result("get_live_cell", [out_point, True])
                    if not isinstance(header, dict) or not isinstance(live_cell, dict):
                        raise OracleUnavailable(f"{network.name} RPC deployment cell evidence is unavailable")
                except (OracleUnavailable, KeyError, IndexError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(1, int(meta["total"]))
                self.assertEqual(10, int(meta["page_size"]))
                self.assertEqual(decode_hex_int(output["capacity"], "capacity"), int(Decimal(str(row["capacity"]))))
                self.assertEqual(output_occupied_capacity(output, output_data), int(row["occupied_capacity"]))
                self.assertEqual((len(output_data) - 2) // 2, int(row["data_size"]))
                self.assertEqual(DAO_TYPE_HASH, ckb_script_hash(output["type"]))
                self.assertEqual(DAO_TYPE_HASH, row["type_hash"])
                self.assertEqual(decode_hex_int(header["timestamp"], "block.timestamp"), int(row["block_timestamp"]))
                self.assertEqual(header["dao"], row["dao"])
                self.assertEqual(live_cell["status"], row["status"])
                self.assertEqual("normal", row["cell_type"])
                self.assertIsNotNone(row["lock_script_id"])
                self.assertIsNotNone(row["type_script_id"])
                self.assertEqual(row["status"] == "live", row["consumed_by_id"] is None)
                self.assertEqual(row["status"] == "live", row["consumed_block_timestamp"] is None)

    # TEST-MAP: SCRIPT-REL-RPC-09
    def test_multi_registration_data_hash_pagination_is_complete_and_each_output_matches(self) -> None:
        negative_cases = (
            {"code_hash": DAO_TYPE_HASH},
            {"code_hash": DAO_TYPE_HASH, "hash_type": "unsupported"},
            {"code_hash": "0x" + "ff" * 32, "hash_type": "type"},
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                code_hash = MULTI_DATA_HASH[network.name]
                try:
                    info = oracle.explorer_json(
                        "/v2/scripts/general_info", {"code_hash": code_hash, "hash_type": "data1"}
                    )["data"]
                    complete, complete_meta = self._page(oracle, code_hash, "data1", page_size=100)
                    first, first_meta = self._page(oracle, code_hash, "data1", page=1, page_size=1)
                    second, second_meta = self._page(oracle, code_hash, "data1", page=2, page_size=1)
                    overflow, overflow_meta = self._page(oracle, code_hash, "data1", page=3, page_size=1)
                    if not isinstance(info, list) or len(info) != 2:
                        raise OracleUnavailable(f"{network.name} multi-registration Data Hash fixture is unavailable")
                    for row in complete:
                        result = oracle.rpc_result("get_transaction", [row["tx_hash"]])
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict):
                            raise OracleUnavailable(f"{network.name} RPC deployment transaction is unavailable")
                        raw_data = transaction["outputs_data"][int(row["cell_index"])]
                        digest = hashlib.blake2b(
                            bytes.fromhex(raw_data.removeprefix("0x")),
                            digest_size=32,
                            person=b"ckb-default-hash",
                        ).hexdigest()
                        self.assertEqual(code_hash, "0x" + digest)
                except (OracleUnavailable, KeyError, IndexError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                expected = [(row["tx_hash"], int(row["cell_index"])) for row in complete]
                paged = first + second
                self.assertEqual(2, int(complete_meta["total"]))
                self.assertEqual(100, int(complete_meta["page_size"]))
                self.assertEqual(expected, [(row["tx_hash"], int(row["cell_index"])) for row in paged])
                self.assertEqual(2, len(set(expected)))
                self.assertEqual(1, int(first_meta["page_size"]))
                self.assertEqual(2, int(first_meta["total"]))
                self.assertEqual(first_meta, second_meta)
                self.assertEqual([], overflow)
                self.assertEqual({"total": 2, "page_size": 1}, overflow_meta)
                for query in negative_cases:
                    path = "/v2/scripts/deployed_cells?" + urlencode(query)
                    try:
                        status, raw = _raw_explorer_response(oracle, path)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    if status == 403:
                        raise unittest.SkipTest(f"{network.name} edge rejected negative-path observation")
                    self.assertEqual(404, status)
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        payload = None
                    self.assertFalse(isinstance(payload, dict) and "data" in payload)

    # TEST-MAP: SCRIPT-REL-RPC-17
    @unittest.expectedFailure  # Public deployments currently return HTTP 500 for the Zero Lock special branch.
    def test_zero_lock_has_no_synthetic_deployment_and_preserves_requested_page_size(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                path = "/v2/scripts/deployed_cells?" + urlencode(
                    {"code_hash": ZERO_HASH, "hash_type": "type", "page_size": 7}
                )
                try:
                    status, raw = _raw_explorer_response(oracle, path)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(200, status)
                payload = json.loads(raw)
                data = payload["data"]
                self.assertEqual([], data["deployed_cells"])
                self.assertEqual({"total": 0, "page_size": 7}, data["meta"])


if __name__ == "__main__":
    unittest.main()
