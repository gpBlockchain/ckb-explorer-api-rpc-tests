from __future__ import annotations

import json
import unittest
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import ckb_script_hash, output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import ACTIVITY_TRANSACTIONS, SECP_CODE_HASH, _short_address
from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


class V1SuggestQueriesIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: DISCOVERY-RPC-03
    def test_block_height_and_hash_resolve_to_the_same_rpc_block(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    height = oracle.api_tip_height()
                    rpc_block = oracle.block(height)
                    header = rpc_block.get("header") if isinstance(rpc_block, dict) else None
                    if not isinstance(header, dict) or not isinstance(header.get("hash"), str):
                        raise OracleUnavailable(f"{network.name} RPC block header is unavailable")
                    block_hash = header["hash"]
                    by_height = oracle.explorer_json("/v1/suggest_queries", {"q": height})
                    by_hash = oracle.explorer_json("/v1/suggest_queries", {"q": block_hash})
                    fresh_block = oracle.block(height, refresh=True)
                    fresh_header = fresh_block.get("header") if isinstance(fresh_block, dict) else None
                    if not isinstance(fresh_header, dict) or fresh_header.get("hash") != block_hash:
                        raise unittest.SkipTest(f"{network.name} RPC block changed during observation")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                height_data = by_height.get("data") if isinstance(by_height, dict) else None
                hash_data = by_hash.get("data") if isinstance(by_hash, dict) else None
                self.assertIsInstance(height_data, dict)
                self.assertIsInstance(hash_data, dict)
                self.assertEqual("block", height_data.get("type"))
                self.assertEqual("block", hash_data.get("type"))
                self.assertEqual(height_data.get("id"), hash_data.get("id"))
                for data in (height_data, hash_data):
                    attributes = data.get("attributes")
                    self.assertIsInstance(attributes, dict)
                    self.assertEqual(height, int(attributes.get("number")))
                    self.assertEqual(block_hash, attributes.get("block_hash"))

    # TEST-MAP: DISCOVERY-RPC-04
    def test_ckb_transaction_hash_resolves_to_the_rpc_transaction(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    height = oracle.api_tip_height()
                    rpc_block = oracle.block(height)
                    transactions = rpc_block.get("transactions") if isinstance(rpc_block, dict) else None
                    if not isinstance(transactions, list) or not transactions or not isinstance(transactions[0], dict):
                        raise OracleUnavailable(f"{network.name} RPC block transactions are unavailable")
                    tx_hash = transactions[0].get("hash")
                    if not isinstance(tx_hash, str):
                        raise OracleUnavailable(f"{network.name} RPC transaction hash is unavailable")
                    payload = oracle.explorer_json("/v1/suggest_queries", {"q": tx_hash})
                    rpc_result = oracle.rpc_result("get_transaction", [tx_hash])
                    rpc_transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
                    if not isinstance(rpc_transaction, dict):
                        raise OracleUnavailable(f"{network.name} RPC transaction disappeared during observation")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                data = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(data, dict)
                self.assertEqual("ckb_transaction", data.get("type"))
                attributes = data.get("attributes")
                self.assertIsInstance(attributes, dict)
                self.assertEqual(rpc_transaction.get("hash"), attributes.get("transaction_hash"))

    # TEST-MAP: DISCOVERY-RPC-05
    def test_address_encodings_lock_hash_and_script_identifier_resolve_to_rpc_scripts(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    result = oracle.rpc_result("get_transaction", [ACTIVITY_TRANSACTIONS[network.name]])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    outputs = transaction.get("outputs") if isinstance(transaction, dict) else None
                    if not isinstance(outputs, list) or not outputs or not isinstance(outputs[0], dict):
                        raise OracleUnavailable(f"{network.name} RPC address fixture is unavailable")
                    lock = outputs[0].get("lock")
                    type_script = outputs[0].get("type")
                    if not isinstance(lock, dict) or not isinstance(type_script, dict):
                        raise OracleUnavailable(f"{network.name} RPC script fixture is unavailable")
                    full_address = output_address(outputs[0], network.address_hrp)
                    short_address = _short_address(lock, network.address_hrp)
                    lock_hash = ckb_script_hash(lock)
                    address_payloads = [
                        oracle.explorer_json("/v1/suggest_queries", {"q": identifier})
                        for identifier in (full_address, short_address, lock_hash)
                    ]
                    script_payload = oracle.explorer_json(
                        "/v1/suggest_queries", {"q": type_script["code_hash"]}
                    )
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                address_data = [payload.get("data") if isinstance(payload, dict) else None for payload in address_payloads]
                self.assertTrue(all(isinstance(data, dict) for data in address_data))
                self.assertEqual(1, len({data.get("id") for data in address_data}))
                for data in address_data:
                    self.assertEqual("address", data.get("type"))
                    attributes = data.get("attributes")
                    self.assertIsInstance(attributes, dict)
                    actual_lock = attributes.get("lock_script")
                    self.assertIsInstance(actual_lock, dict)
                    self.assertEqual(
                        {key: lock[key] for key in ("args", "code_hash", "hash_type")},
                        {key: actual_lock.get(key) for key in ("args", "code_hash", "hash_type")},
                    )
                script_data = script_payload.get("data") if isinstance(script_payload, dict) else None
                self.assertIsInstance(script_data, dict)
                self.assertIn(script_data.get("type"), {"type_script", "lock_script"})
                script_attributes = script_data.get("attributes")
                self.assertIsInstance(script_attributes, dict)
                self.assertEqual(type_script["code_hash"], script_attributes.get("code_hash"))

    # TEST-MAP: DISCOVERY-RPC-06
    def test_aggregate_query_returns_unique_supported_hits_while_numeric_query_stays_a_block(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    aggregate = oracle.explorer_json(
                        "/v1/suggest_queries", {"q": SECP_CODE_HASH, "filter_by": 0}
                    )
                    height = oracle.api_tip_height()
                    rpc_block = oracle.block(height)
                    header = rpc_block.get("header") if isinstance(rpc_block, dict) else None
                    if not isinstance(header, dict) or not isinstance(header.get("hash"), str):
                        raise OracleUnavailable(f"{network.name} RPC block header is unavailable")
                    numeric = oracle.explorer_json(
                        "/v1/suggest_queries", {"q": height, "filter_by": 0}
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                raw_items = aggregate.get("data") if isinstance(aggregate, dict) else None
                self.assertIsInstance(raw_items, list)
                items: list[dict[str, object]] = []
                for item in raw_items:
                    if isinstance(item, dict):
                        items.append(item)
                    elif isinstance(item, list):
                        self.assertTrue(all(isinstance(member, dict) for member in item))
                        items.extend(item)
                    else:
                        self.fail("aggregate data contains a non-resource member")
                identities = [(item.get("type"), item.get("id")) for item in items]
                self.assertGreaterEqual(len({item.get("type") for item in items}), 2)
                self.assertEqual(len(identities), len(set(identities)))
                lock_hits = [item for item in items if item.get("type") == "lock_script"]
                self.assertTrue(lock_hits)
                self.assertTrue(
                    any(item.get("attributes", {}).get("code_hash") == SECP_CODE_HASH for item in lock_hits)
                )
                numeric_items = numeric.get("data") if isinstance(numeric, dict) else None
                self.assertIsInstance(numeric_items, list)
                self.assertEqual(1, len(numeric_items))
                self.assertEqual("block", numeric_items[0].get("type"))
                self.assertEqual(str(height), numeric_items[0].get("attributes", {}).get("number"))
                self.assertEqual(header["hash"], numeric_items[0].get("attributes", {}).get("block_hash"))

    # TEST-MAP: DISCOVERY-RPC-07
    def test_missing_and_too_short_aggregate_queries_return_404_code_1018(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                paths = [
                    "/v1/suggest_queries?" + urlencode({"q": "0x" + "ff" * 32}),
                    "/v1/suggest_queries?" + urlencode({"q": "x", "filter_by": 0}),
                ]
                try:
                    responses = [_raw_explorer_response(oracle, path) for path in paths]
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                for status, raw in responses:
                    self.assertEqual(404, status)
                    body = json.loads(raw)
                    self.assertIsInstance(body, list)
                    self.assertEqual(1, len(body))
                    self.assertEqual(1018, body[0].get("code"))
                    self.assertNotIn("data", body[0])
