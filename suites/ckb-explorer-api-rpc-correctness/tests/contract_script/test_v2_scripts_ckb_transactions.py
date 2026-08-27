from __future__ import annotations

import json
import socket
import time
import unittest
import urllib.error
import urllib.request
from typing import Any, Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import DAO_TYPE_HASH


ZERO_HASH = "0x" + "00" * 32
MULTI_CONTRACT_FIXTURES = {
    "mainnet": ("0xd01f5152c267b7f33b9795140c2467742e8424e49ebe2331caec197f7281b60a", "type"),
    "testnet": ("0x58c5f491aba6d61678b7cf7edf4910b1f5e00ec0cde2f42e0abb4fd9aff25a63", "type"),
}


class _StatusPreservingProcessor(urllib.request.HTTPErrorProcessor):
    def http_response(self, request: urllib.request.Request, response: Any) -> Any:
        return response

    https_response = http_response


def _raw_explorer_response(oracle: NetworkOracle, path: str) -> tuple[int, bytes]:
    headers = dict(V1_HEADERS)
    headers["User-Agent"] = oracle.client.user_agent
    opener = urllib.request.build_opener(_StatusPreservingProcessor())
    for attempt in range(oracle.client.retries + 1):
        try:
            request = urllib.request.Request(oracle.network.explorer_api_url + path, headers=headers)
            with opener.open(request, timeout=oracle.client.timeout) as response:
                raw = response.read(oracle.client.max_body_bytes + 1)
                status = int(response.status)
            if len(raw) > oracle.client.max_body_bytes:
                raise OracleUnavailable(f"{oracle.network.name} Explorer response is too large")
            if attempt < oracle.client.retries and (status == 429 or status >= 500):
                time.sleep(0.2 * (attempt + 1))
                continue
            return status, raw
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as error:
            if attempt < oracle.client.retries:
                time.sleep(0.2 * (attempt + 1))
                continue
            raise OracleUnavailable(f"{oracle.network.name} Explorer transport failure: {error}") from error
    raise AssertionError("unreachable HTTP retry loop")


class V2ScriptsCkbTransactionsRpcCorrectnessTests(unittest.TestCase):
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
        payload = oracle.explorer_json("/v2/scripts/ckb_transactions", params)
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("ckb_transactions") if isinstance(data, dict) else None
        meta = data.get("meta") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not isinstance(meta, dict) or not all(isinstance(row, dict) for row in rows):
            raise OracleUnavailable(f"{oracle.network.name} script transaction page is unavailable")
        return rows, meta

    def _identity(self, row: Mapping[str, Any]) -> tuple[str, str]:
        if row.get("hash_type") in {"data", "data1", "data2"}:
            return str(row["data_hash"]), str(row["hash_type"])
        return str(row["type_hash"]), "type"

    # TEST-MAP: SCRIPT-REL-RPC-01
    @unittest.expectedFailure  # Mainnet Data Hash results include transactions without the selected script annotation.
    def test_type_and_data_hash_branches_only_annotate_the_selected_script_identity(self) -> None:
        mismatches: list[str] = []
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    catalog = oracle.explorer_json("/v2/scripts", {"page_size": 100})["data"]
                    data_row = next(
                        row for row in catalog
                        if row.get("data_hash") not in {None, ZERO_HASH}
                        and row.get("type_hash") is None
                        and row.get("hash_type") in {"data", "data1", "data2"}
                    )
                    for code_hash, hash_type in ((DAO_TYPE_HASH, "type"), self._identity(data_row)):
                        rows, _meta = self._page(oracle, code_hash, hash_type, page_size=5)
                        if not rows:
                            mismatches.append(f"{network.name} {hash_type} query returned no transactions")
                            continue
                        for row in rows:
                            selected = [
                                dep for dep in row["cell_deps"]
                                if isinstance(dep.get("script"), dict)
                                and dep["script"].get("code_hash") == code_hash
                                and dep["script"].get("hash_type") == hash_type
                            ]
                            if not selected:
                                mismatches.append(
                                    f"{network.name} {hash_type} transaction {row.get('tx_hash')} "
                                    "has no selected script annotation"
                                )
                except (OracleUnavailable, StopIteration, KeyError, TypeError) as error:
                    raise unittest.SkipTest(str(error)) from error
        self.assertEqual([], mismatches)

    # TEST-MAP: SCRIPT-REL-RPC-02
    def test_every_member_depends_on_one_of_multiple_published_contract_outpoints(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                code_hash, hash_type = MULTI_CONTRACT_FIXTURES[network.name]
                try:
                    info = oracle.explorer_json(
                        "/v2/scripts/general_info", {"code_hash": code_hash, "hash_type": hash_type}
                    )["data"]
                    out_points = set()
                    for record in info:
                        value = record.get("script_out_point")
                        if isinstance(value, str) and value.startswith("0x") and "-" in value:
                            tx_hash, raw_index = value.rsplit("-", 1)
                            if raw_index.isdigit():
                                out_points.add((tx_hash, int(raw_index)))
                    if len(out_points) < 2:
                        raise OracleUnavailable(f"{network.name} multi-out-point published fixture is unavailable")
                    rows, _meta = self._page(oracle, code_hash, hash_type, page_size=100)
                    for row in rows:
                        result = oracle.rpc_result("get_transaction", [row["tx_hash"]])
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict):
                            raise OracleUnavailable(f"{network.name} RPC dependency transaction is unavailable")
                        actual = {
                            (dep["out_point"]["tx_hash"], decode_hex_int(dep["out_point"]["index"], "dep.index"))
                            for dep in transaction["cell_deps"]
                        }
                        self.assertTrue(actual & out_points)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

    # TEST-MAP: SCRIPT-REL-RPC-03
    def test_code_and_dep_group_annotations_match_rpc_dependencies_and_script_use(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    catalog = oracle.explorer_json("/v2/scripts", {"page_size": 100})["data"]
                    dep_group = next(row for row in catalog if row.get("dep_type") == "dep_group")
                    samples = ((DAO_TYPE_HASH, "type", "code"), (*self._identity(dep_group), "dep_group"))
                    for code_hash, hash_type, expected_type in samples:
                        rows, _meta = self._page(oracle, code_hash, hash_type, page_size=3)
                        for row in rows:
                            result = oracle.rpc_result("get_transaction", [row["tx_hash"]])
                            transaction = result.get("transaction") if isinstance(result, dict) else None
                            if not isinstance(transaction, dict):
                                raise OracleUnavailable(f"{network.name} RPC dependency transaction is unavailable")
                            rpc_deps = {
                                (
                                    dep["out_point"]["tx_hash"],
                                    decode_hex_int(dep["out_point"]["index"], "dep.index"),
                                    dep["dep_type"],
                                )
                                for dep in transaction["cell_deps"]
                            }
                            selected = [
                                dep for dep in row["cell_deps"]
                                if isinstance(dep.get("script"), dict)
                                and dep["script"].get("code_hash") == code_hash
                            ]
                            self.assertTrue(selected)
                            for dep in selected:
                                key = (dep["out_point"]["tx_hash"], int(dep["out_point"]["index"]), dep["dep_type"])
                                self.assertIn(key, rpc_deps)
                                self.assertEqual(expected_type, dep["dep_type"])
                                self.assertIn(bool(dep["script"].get("is_lock_script")), {True, False})
                                self.assertIn(bool(dep["script"].get("is_type_script")), {True, False})
                except (OracleUnavailable, StopIteration, KeyError, TypeError) as error:
                    raise unittest.SkipTest(str(error)) from error

    # TEST-MAP: SCRIPT-REL-RPC-04
    def test_transaction_block_structure_fee_capacity_bytes_and_cell_changes_match_rpc(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, _meta = self._page(oracle, DAO_TYPE_HASH, "type", page_size=10)
                    chosen = None
                    for row in rows:
                        result = oracle.rpc_result("get_transaction", [row["tx_hash"]])
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict) or not isinstance(status, dict):
                            continue
                        referenced = oracle.referenced_outputs(transaction)
                        if not any(
                            isinstance(output.get("type"), dict)
                            and output["type"].get("code_hash") == DAO_TYPE_HASH
                            and data != "0x" + "00" * 8
                            for output, data in referenced
                        ):
                            chosen = row, transaction, status, referenced
                            break
                    if chosen is None:
                        raise OracleUnavailable(f"{network.name} normal-fee dependency sample is unavailable")
                    row, transaction, status, referenced = chosen
                    block = oracle.block_by_hash(status["block_hash"])
                    header = block.get("header") if isinstance(block, dict) else None
                    raw = oracle.rpc_result("get_transaction", [row["tx_hash"], "0x0"])
                    raw_transaction = raw.get("transaction") if isinstance(raw, dict) else None
                    if not isinstance(header, dict) or not isinstance(raw_transaction, str):
                        raise OracleUnavailable(f"{network.name} RPC transaction evidence is unavailable")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(transaction["hash"], row["tx_hash"])
                self.assertEqual(decode_hex_int(header["number"], "block.number"), int(row["block_number"]))
                self.assertEqual(decode_hex_int(header["timestamp"], "block.timestamp"), int(row["block_timestamp"]))
                self.assertEqual("committed", row["tx_status"])
                self.assertEqual(transaction["header_deps"], row["header_deps"])
                self.assertEqual(
                    transaction["witnesses"],
                    [item["data"] for item in sorted(row["witnesses"], key=lambda item: int(item["index"]))],
                )
                expected_deps = [
                    {
                        "out_point": {
                            "tx_hash": dep["out_point"]["tx_hash"],
                            "index": decode_hex_int(dep["out_point"]["index"], "dep.index"),
                        },
                        "dep_type": dep["dep_type"],
                    }
                    for dep in transaction["cell_deps"]
                ]
                actual_deps = [
                    {"out_point": dep["out_point"], "dep_type": dep["dep_type"]}
                    for dep in row["cell_deps"]
                ]
                self.assertCountEqual(expected_deps, actual_deps)
                input_capacity = sum(decode_hex_int(output["capacity"], "input.capacity") for output, _ in referenced)
                output_capacity = sum(decode_hex_int(output["capacity"], "output.capacity") for output in transaction["outputs"])
                self.assertEqual(input_capacity - output_capacity, int(row["transaction_fee"]))
                self.assertEqual(input_capacity, int(row["capacity_involved"]))
                self.assertEqual(len(transaction["outputs"]) - len(transaction["inputs"]), int(row["live_cell_changes"]))
                self.assertEqual((len(raw_transaction) - 2) // 2 + 4, int(row["bytes"]))
                self.assertEqual(min(10, len(transaction["inputs"])), len(row["display_inputs"]))
                self.assertEqual(min(10, len(transaction["outputs"])), len(row["display_outputs"]))

    # TEST-MAP: SCRIPT-REL-RPC-05
    def test_default_custom_and_overflow_pages_preserve_capped_order_and_metadata(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    default, default_meta = self._page(oracle, DAO_TYPE_HASH, "type")
                    first, first_meta = self._page(oracle, DAO_TYPE_HASH, "type", page_size=100)
                    total = int(first_meta["total"])
                    paged: list[Mapping[str, Any]] = []
                    for page in range(1, (total + 99) // 100 + 1):
                        rows, meta = self._page(oracle, DAO_TYPE_HASH, "type", page=page, page_size=100)
                        self.assertEqual(total, int(meta["total"]))
                        self.assertEqual(100, int(meta["page_size"]))
                        paged.extend(rows)
                    overflow, overflow_meta = self._page(
                        oracle, DAO_TYPE_HASH, "type", page=(total + 99) // 100 + 1, page_size=100
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(10, int(default_meta["page_size"]))
                self.assertEqual(min(10, total), len(default))
                self.assertEqual(100, int(first_meta["page_size"]))
                self.assertEqual([(row["id"], row["tx_hash"]) for row in first], [
                    (row["id"], row["tx_hash"]) for row in paged[:100]
                ])
                self.assertEqual([(row["id"], row["tx_hash"]) for row in default], [
                    (row["id"], row["tx_hash"]) for row in paged[:len(default)]
                ])
                self.assertEqual(total, len(paged))
                self.assertEqual(total, len({(row["id"], row["tx_hash"]) for row in paged}))
                ordering = []
                for row in paged[:20]:
                    result = oracle.rpc_result("get_transaction", [row["tx_hash"]])
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    if not isinstance(status, dict):
                        raise unittest.SkipTest(f"{network.name} RPC transaction order is unavailable")
                    ordering.append((int(row["block_number"]), decode_hex_int(status["tx_index"], "tx_index")))
                self.assertEqual(ordering, sorted(ordering, reverse=True))
                self.assertEqual([], overflow)
                self.assertEqual(total, int(overflow_meta["total"]))
                self.assertEqual(100, int(overflow_meta["page_size"]))

    # TEST-MAP: SCRIPT-REL-RPC-16
    @unittest.expectedFailure
    def test_zero_lock_transactions_each_contain_an_rpc_zero_lock_cell(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, meta = self._page(oracle, ZERO_HASH, "type", page_size=100)
                    ordering = []
                    for row in rows:
                        result = oracle.rpc_result("get_transaction", [row["tx_hash"]])
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict) or not isinstance(status, dict):
                            raise OracleUnavailable(f"{network.name} Zero Lock RPC transaction is unavailable")
                        referenced = [] if row["is_cellbase"] else oracle.referenced_outputs(transaction)
                        locks = [output["lock"] for output, _ in referenced] + [output["lock"] for output in transaction["outputs"]]
                        self.assertTrue(any(lock.get("code_hash") == ZERO_HASH for lock in locks))
                        ordering.append((int(row["block_number"]), decode_hex_int(status["tx_index"], "tx_index")))
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(len(rows), int(meta["total"]))
                self.assertEqual(ordering, sorted(ordering, reverse=True))

    # TEST-MAP: SCRIPT-REL-RPC-19
    def test_missing_unsupported_and_unknown_script_identity_return_not_found_without_data(self) -> None:
        cases = (
            {"code_hash": DAO_TYPE_HASH},
            {"code_hash": DAO_TYPE_HASH, "hash_type": "unsupported"},
            {"code_hash": "0x" + "ff" * 32, "hash_type": "type"},
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                for query in cases:
                    path = "/v2/scripts/ckb_transactions?" + urlencode(query)
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


if __name__ == "__main__":
    unittest.main()
