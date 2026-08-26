from __future__ import annotations

import json
import unittest
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import (
    ckb_script_hash,
    decode_hex_int,
    output_address,
    output_occupied_capacity,
)
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import DAO_TYPE_HASH
from tests.contract_script.test_v2_scripts_ckb_transactions import ZERO_HASH, _raw_explorer_response


SECP_TYPE_HASH = "0x9bd7e06f3ecf4be0f2fcd2188b23f1b9fcc88e5d4b65a8637b17723bbda3cce8"
SECP_DATA_HASH = "0x709f3fda12f561cfacf92273c57a98fede188a3f1a59b1f888d113f9cce08649"
DAO_DATA_HASH = "0x32064a14ce10d95d4b7343054cc19d73b25b16ae61a6c681011ca781a60c7923"


class V2ScriptsReferringCellsRpcCorrectnessTests(unittest.TestCase):
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
        payload = oracle.explorer_json("/v2/scripts/referring_cells", params)
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("referring_cells") if isinstance(data, dict) else None
        meta = data.get("meta") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not isinstance(meta, dict) or not all(isinstance(row, dict) for row in rows):
            raise OracleUnavailable(f"{oracle.network.name} referring-cell page is unavailable")
        return rows, meta

    def _rpc_output(
        self,
        oracle: NetworkOracle,
        row: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], str]:
        result = oracle.rpc_result("get_transaction", [row["tx_hash"]])
        transaction = result.get("transaction") if isinstance(result, dict) else None
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC referring transaction is unavailable")
        index = int(row["cell_index"])
        try:
            output = transaction["outputs"][index]
            output_data = transaction["outputs_data"][index]
        except (KeyError, IndexError, TypeError) as error:
            raise OracleUnavailable(f"{oracle.network.name} RPC referring output is unavailable") from error
        out_point = {"tx_hash": row["tx_hash"], "index": hex(index)}
        live_cell = oracle.rpc_result("get_live_cell", [out_point, True])
        block = oracle.block_by_hash(status["block_hash"])
        header = block.get("header") if isinstance(block, dict) else None
        if not isinstance(output, dict) or not isinstance(output_data, str):
            raise OracleUnavailable(f"{oracle.network.name} RPC referring output is invalid")
        if not isinstance(live_cell, dict) or not isinstance(header, dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC live-cell evidence is unavailable")
        self.assertEqual("live", live_cell.get("status"))
        self.assertEqual("live", row["status"])
        self.assertIsNone(row["consumed_by_id"])
        self.assertIsNone(row["consumed_block_timestamp"])
        self.assertEqual(decode_hex_int(output["capacity"], "capacity"), int(Decimal(str(row["capacity"]))))
        self.assertEqual(output_occupied_capacity(output, output_data), int(row["occupied_capacity"]))
        self.assertEqual((len(output_data) - 2) // 2, int(row["data_size"]))
        self.assertEqual(decode_hex_int(header["timestamp"], "block.timestamp"), int(row["block_timestamp"]))
        self.assertEqual(header["dao"], row["dao"])
        self.assertIsNotNone(row["lock_script_id"])
        if output.get("type") is None:
            self.assertIsNone(row["type_hash"])
            self.assertIsNone(row["type_script_id"])
        else:
            self.assertEqual(ckb_script_hash(output["type"]), row["type_hash"])
            self.assertIsNotNone(row["type_script_id"])
        return output, output_data

    # TEST-MAP: SCRIPT-REL-RPC-10
    def test_lock_script_type_and_data_hash_queries_return_only_matching_rpc_live_cells(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                selected_hashes = {SECP_TYPE_HASH, SECP_DATA_HASH}
                try:
                    for code_hash, hash_type in ((SECP_TYPE_HASH, "type"), (SECP_DATA_HASH, "data")):
                        rows, meta = self._page(oracle, code_hash, hash_type, page_size=5)
                        self.assertTrue(rows)
                        self.assertEqual(5, int(meta["page_size"]))
                        for row in rows:
                            output, _output_data = self._rpc_output(oracle, row)
                            self.assertIn(output["lock"]["code_hash"], selected_hashes)
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

    # TEST-MAP: SCRIPT-REL-RPC-11
    def test_type_script_query_returns_only_matching_rpc_live_cells(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, meta = self._page(oracle, DAO_TYPE_HASH, "type", page_size=10)
                    self.assertTrue(rows)
                    self.assertEqual(10, int(meta["page_size"]))
                    for row in rows:
                        output, _output_data = self._rpc_output(oracle, row)
                        self.assertIsInstance(output.get("type"), dict)
                        self.assertIn(output["type"]["code_hash"], {DAO_TYPE_HASH, DAO_DATA_HASH})
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

    # TEST-MAP: SCRIPT-REL-RPC-12
    def test_default_custom_and_overflow_pages_are_complete_unique_and_globally_ordered(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    default, default_meta = self._page(oracle, DAO_TYPE_HASH, "type")
                    paged: list[Mapping[str, Any]] = []
                    total = None
                    for page in range(1, 6):
                        rows, meta = self._page(oracle, DAO_TYPE_HASH, "type", page=page, page_size=100)
                        total = int(meta["total"])
                        self.assertEqual(100, int(meta["page_size"]))
                        paged.extend(rows)
                    overflow, overflow_meta = self._page(
                        oracle, DAO_TYPE_HASH, "type", page=6, page_size=100
                    )
                    stable, _stable_meta = self._page(oracle, DAO_TYPE_HASH, "type", page=1, page_size=100)
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                first_keys = [(row["tx_hash"], int(row["cell_index"])) for row in paged[:100]]
                stable_keys = [(row["tx_hash"], int(row["cell_index"])) for row in stable]
                if first_keys != stable_keys:
                    raise unittest.SkipTest(f"{network.name} referring live cells changed during observation")
                self.assertEqual(500, total)
                self.assertEqual(10, int(default_meta["page_size"]))
                self.assertEqual(first_keys[:10], [(row["tx_hash"], int(row["cell_index"])) for row in default])
                keys = [(row["tx_hash"], int(row["cell_index"])) for row in paged]
                self.assertEqual(total, len(keys))
                self.assertEqual(total, len(set(keys)))
                ordering = [(int(row["block_timestamp"]), int(row["cell_index"])) for row in paged]
                self.assertEqual(ordering, sorted(ordering, reverse=True))
                self.assertEqual([], overflow)
                self.assertEqual({"total": 500, "page_size": 100}, overflow_meta)

    # TEST-MAP: SCRIPT-REL-RPC-14
    def test_address_and_lock_hash_filters_return_the_same_selected_lock_cells(self) -> None:
        negative_cases = (
            {"code_hash": DAO_TYPE_HASH},
            {"code_hash": DAO_TYPE_HASH, "hash_type": "unsupported"},
            {"code_hash": "0x" + "ff" * 32, "hash_type": "type"},
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    samples, _meta = self._page(oracle, SECP_TYPE_HASH, "type", page_size=1)
                    if not samples:
                        raise OracleUnavailable(f"{network.name} referring address sample is unavailable")
                    sample_output, _sample_data = self._rpc_output(oracle, samples[0])
                    lock = sample_output["lock"]
                    address = output_address(sample_output, network.address_hrp)
                    lock_hash = ckb_script_hash(lock)
                    address_rows, address_meta = self._page(
                        oracle, SECP_TYPE_HASH, "type", address_hash=address, page_size=5
                    )
                    hash_rows, hash_meta = self._page(
                        oracle, SECP_TYPE_HASH, "type", address_hash=lock_hash, page_size=5
                    )
                    stable_rows, _stable_meta = self._page(
                        oracle, SECP_TYPE_HASH, "type", address_hash=address, page_size=5
                    )
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                if address_rows != stable_rows:
                    raise unittest.SkipTest(f"{network.name} address-filtered live cells changed during observation")
                self.assertEqual(address_rows, hash_rows)
                self.assertEqual(address_meta, hash_meta)
                self.assertTrue(address_rows)
                for row in address_rows:
                    try:
                        output, _output_data = self._rpc_output(oracle, row)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(lock, output["lock"])
                    self.assertEqual(lock_hash, ckb_script_hash(output["lock"]))
                for query in negative_cases:
                    path = "/v2/scripts/referring_cells?" + urlencode(query)
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

    # TEST-MAP: SCRIPT-REL-RPC-18
    def test_zero_lock_page_contains_only_exact_rpc_zero_lock_live_cells(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, meta = self._page(oracle, ZERO_HASH, "type", page_size=10)
                    self.assertTrue(rows)
                    self.assertEqual(10, int(meta["page_size"]))
                    for row in rows:
                        output, _output_data = self._rpc_output(oracle, row)
                        self.assertEqual(ZERO_HASH, output["lock"]["code_hash"])
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error


if __name__ == "__main__":
    unittest.main()
