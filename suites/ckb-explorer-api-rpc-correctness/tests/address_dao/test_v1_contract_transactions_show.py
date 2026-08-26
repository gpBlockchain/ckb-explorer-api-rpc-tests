from __future__ import annotations

import json
import socket
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import ACTIVITY_TRANSACTIONS, DAO_ADDRESSES, DAO_TYPE_HASH
from tests.address_dao.test_v2_dao_events_index import EMPTY_DAO_ADDRESSES


class _StatusPreservingProcessor(urllib.request.HTTPErrorProcessor):
    def http_response(self, request: urllib.request.Request, response: Any) -> Any:
        return response

    https_response = http_response


def _explorer_response(
    oracle: NetworkOracle,
    identifier: str,
    query: Mapping[str, object] | None = None,
) -> tuple[int, Any]:
    path = "/v1/contract_transactions/" + urllib.parse.quote(identifier, safe="")
    if query:
        path += "?" + urllib.parse.urlencode(query)
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
            try:
                return status, json.loads(raw) if raw else None
            except json.JSONDecodeError as error:
                raise OracleUnavailable(f"{oracle.network.name} Explorer returned invalid JSON") from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as error:
            if attempt < oracle.client.retries:
                time.sleep(0.2 * (attempt + 1))
                continue
            raise OracleUnavailable(f"{oracle.network.name} Explorer transport failure: {error}") from error
    raise AssertionError("unreachable HTTP retry loop")


class V1ContractTransactionsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _page(
        self,
        oracle: NetworkOracle,
        **query: object,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json("/v1/contract_transactions/nervos_dao", query or None)
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise OracleUnavailable(f"{oracle.network.name} contract transaction page is unavailable")
        rows: list[Mapping[str, Any]] = []
        for item in data:
            attributes = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(attributes, dict):
                raise OracleUnavailable(f"{oracle.network.name} contract transaction row is unavailable")
            rows.append(attributes)
        return rows, meta

    def _indexer_window(self, oracle: NetworkOracle) -> list[str]:
        search_key = {
            "script": {"code_hash": DAO_TYPE_HASH, "hash_type": "type", "args": "0x"},
            "script_type": "type",
            "script_search_mode": "exact",
        }
        result = oracle.rpc_result("get_transactions", [search_key, "desc", "0x64"])
        objects = result.get("objects") if isinstance(result, dict) else None
        if not isinstance(objects, list) or not objects:
            raise OracleUnavailable(f"{oracle.network.name} Indexer DAO window is unavailable")
        hashes: list[str] = []
        for item in objects:
            tx_hash = item.get("tx_hash") if isinstance(item, dict) else None
            if not isinstance(tx_hash, str):
                raise OracleUnavailable(f"{oracle.network.name} Indexer DAO event is unavailable")
            if tx_hash not in hashes:
                hashes.append(tx_hash)
        return hashes

    def _is_dao_transaction(self, oracle: NetworkOracle, transaction: Mapping[str, Any]) -> bool:
        outputs = transaction.get("outputs")
        if not isinstance(outputs, list):
            raise OracleUnavailable(f"{oracle.network.name} RPC transaction outputs are unavailable")
        previous = oracle.referenced_outputs(transaction)
        candidates = list(outputs) + [output for output, _data in previous]
        return any(
            isinstance(output, dict)
            and isinstance(output.get("type"), dict)
            and output["type"].get("code_hash") == DAO_TYPE_HASH
            and output["type"].get("hash_type") == "type"
            and output["type"].get("args") == "0x"
            for output in candidates
        )

    # TEST-MAP: DAO-TX-RPC-01
    def test_latest_committed_member_window_matches_deduplicated_indexer_dao_events(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    before = self._indexer_window(oracle)
                    rows, _meta = self._page(oracle, page=1, page_size=10)
                    after = self._indexer_window(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if before != after:
                    raise unittest.SkipTest(f"{network.name} Indexer DAO window changed during observation")
                hashes = [row["transaction_hash"] for row in rows]
                self.assertEqual(before[:10], hashes)
                self.assertEqual(len(hashes), len(set(hashes)))
                for tx_hash in hashes:
                    result = oracle.rpc_result("get_transaction", [tx_hash])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict) or not isinstance(status, dict):
                        raise unittest.SkipTest(f"{network.name} RPC DAO transaction is unavailable")
                    self.assertEqual("committed", status.get("status"))
                    self.assertTrue(self._is_dao_transaction(oracle, transaction))

    # TEST-MAP: DAO-TX-RPC-02
    @unittest.expectedFailure  # Public APIs reset overflow-page meta.page_size to the default 10.
    def test_default_custom_adjacent_and_overflow_pages_match_indexer_order(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    indexer_hashes = self._indexer_window(oracle)
                    default_rows, default_meta = self._page(oracle)
                    first, first_meta = self._page(oracle, page=1, page_size=2)
                    second, second_meta = self._page(oracle, page=2, page_size=2)
                    third, third_meta = self._page(oracle, page=3, page_size=2)
                    overflow, overflow_meta = self._page(
                        oracle, page=int(first_meta["total_pages"]) + 1, page_size=2
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(10, int(default_meta["page_size"]))
                self.assertEqual(10, len(default_rows))
                combined = first + second + third
                hashes = [row["transaction_hash"] for row in combined]
                self.assertEqual(indexer_hashes[:6], hashes)
                self.assertEqual(len(hashes), len(set(hashes)))
                self.assertEqual(
                    [int(row["block_timestamp"]) for row in combined],
                    sorted((int(row["block_timestamp"]) for row in combined), reverse=True),
                )
                totals = {int(meta["total"]) for meta in (default_meta, first_meta, second_meta, third_meta, overflow_meta)}
                self.assertEqual(1, len(totals))
                self.assertEqual({2}, {int(meta["page_size"]) for meta in (first_meta, second_meta, third_meta, overflow_meta)})
                self.assertEqual([], overflow)

    # TEST-MAP: DAO-TX-RPC-03
    def test_transaction_hash_filter_returns_only_a_dao_member_and_excludes_an_rpc_nonmember(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, _meta = self._page(oracle, page=1, page_size=1)
                    if not rows:
                        raise OracleUnavailable(f"{network.name} DAO list is empty")
                    dao_hash = rows[0]["transaction_hash"]
                    filtered, filtered_meta = self._page(oracle, tx_hash=dao_hash)
                    normal_hash = ACTIVITY_TRANSACTIONS[network.name]
                    normal_result = oracle.rpc_result("get_transaction", [normal_hash])
                    normal_transaction = normal_result.get("transaction") if isinstance(normal_result, dict) else None
                    if not isinstance(normal_transaction, dict):
                        raise OracleUnavailable(f"{network.name} ordinary transaction is unavailable")
                    ordinary, ordinary_meta = self._page(oracle, tx_hash=normal_hash)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if self._is_dao_transaction(oracle, normal_transaction):
                    raise unittest.SkipTest(f"{network.name} recorded ordinary transaction became a DAO member")
                self.assertEqual([dao_hash], [row["transaction_hash"] for row in filtered])
                self.assertEqual(1, int(filtered_meta["total"]))
                result = oracle.rpc_result("get_transaction", [dao_hash])
                transaction = result.get("transaction") if isinstance(result, dict) else None
                status = result.get("tx_status") if isinstance(result, dict) else None
                self.assertIsInstance(transaction, dict)
                self.assertIsInstance(status, dict)
                self.assertEqual("committed", status.get("status"))
                self.assertEqual([], ordinary)
                self.assertEqual(0, int(ordinary_meta["total"]))

    # TEST-MAP: DAO-TX-RPC-04
    def test_address_filter_is_the_intersection_of_dao_membership_and_address_ledger(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    rows, meta = self._page(oracle, address_hash=address, page_size=100)
                    payload = oracle.explorer_json(
                        f"/v1/address_dao_transactions/{address}", {"page": 1, "page_size": 100}
                    )
                    address_data = payload.get("data") if isinstance(payload, dict) else None
                    address_meta = payload.get("meta") if isinstance(payload, dict) else None
                    if not isinstance(address_data, list) or not isinstance(address_meta, dict):
                        raise OracleUnavailable(f"{network.name} address DAO page is unavailable")
                    empty, empty_meta = self._page(
                        oracle, address_hash=EMPTY_DAO_ADDRESSES[network.name], page_size=100
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                expected = [item["attributes"] for item in address_data]
                self.assertEqual(expected, rows)
                self.assertEqual(int(address_meta["total"]), int(meta["total"]))
                self.assertTrue(
                    all(
                        any(
                            item.get("address_hash") == address
                            for side in ("display_inputs", "display_outputs")
                            for item in row[side]
                        )
                        for row in rows
                    )
                )
                self.assertEqual([], empty)
                self.assertEqual(0, int(empty_meta["total"]))

    # TEST-MAP: DAO-TX-RPC-08
    def test_non_dao_contract_name_returns_contract_not_found(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    status, errors = _explorer_response(oracle, "not_nervos_dao")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if status == 403 and isinstance(errors, dict) and errors.get("cloudflare_error") is True:
                    raise unittest.SkipTest(f"{network.name} edge rejected negative-path observation")
                self.assertEqual(404, status)
                self.assertIsInstance(errors, list)
                self.assertEqual(1021, int(errors[0]["code"]))
                self.assertEqual("Contract Not Found", errors[0]["title"])

    # TEST-MAP: DAO-TX-RPC-10
    def test_invalid_page_and_page_size_return_all_corresponding_validation_errors(self) -> None:
        cases = (
            ({"page": 0}, [1007]),
            ({"page": "not-an-integer"}, [1007]),
            ({"page_size": 0}, [1008]),
            ({"page_size": "not-an-integer"}, [1008]),
            ({"page": 0, "page_size": "not-an-integer"}, [1007, 1008]),
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                for query, expected_codes in cases:
                    try:
                        status, errors = _explorer_response(oracle, "nervos_dao", query)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    if status == 403 and isinstance(errors, dict) and errors.get("cloudflare_error") is True:
                        raise unittest.SkipTest(f"{network.name} edge rejected negative-path observation")
                    self.assertEqual(400, status)
                    self.assertIsInstance(errors, list)
                    self.assertEqual(expected_codes, [int(error["code"]) for error in errors])


if __name__ == "__main__":
    unittest.main()
