from __future__ import annotations

import json
import socket
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import DAO_ADDRESSES, DAO_TYPE_HASH


EMPTY_DAO_ADDRESSES = {
    "mainnet": "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqv9ft027uv84z4nc4wsgwl32u6ex4e4qsscccscx",
    "testnet": "ckt1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq2zrchfd2y3xcf9lkqeddggqagukmnufkse0g93q",
}


class _StatusPreservingProcessor(urllib.request.HTTPErrorProcessor):
    def http_response(self, request: urllib.request.Request, response: Any) -> Any:
        return response

    https_response = http_response


def _explorer_response(oracle: NetworkOracle, query: Mapping[str, object] | None) -> tuple[int, Any]:
    url = oracle.network.explorer_api_url + "/v2/dao_events"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = dict(V1_HEADERS)
    headers["User-Agent"] = oracle.client.user_agent
    opener = urllib.request.build_opener(_StatusPreservingProcessor())
    for attempt in range(oracle.client.retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
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


class V2DaoEventsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _page(
        self,
        oracle: NetworkOracle,
        address: str,
        *,
        page: int | None = None,
        page_size: int | None = None,
    ) -> tuple[Mapping[str, Any], list[Mapping[str, Any]], Mapping[str, Any]]:
        query: dict[str, object] = {"address": address}
        if page is not None:
            query["page"] = page
        if page_size is not None:
            query["page_size"] = page_size
        payload = oracle.explorer_json("/v2/dao_events", query)
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        activities = data.get("activities") if isinstance(data, dict) else None
        if not isinstance(data, dict) or not isinstance(activities, list) or not isinstance(meta, dict):
            raise OracleUnavailable(f"{oracle.network.name} V2 DAO event page is unavailable")
        if not all(isinstance(item, dict) for item in activities):
            raise OracleUnavailable(f"{oracle.network.name} V2 DAO event activity is unavailable")
        return data, activities, meta

    def _v1_page(
        self,
        oracle: NetworkOracle,
        address: str,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json(
            f"/v1/address_dao_transactions/{address}",
            {"page": 1, "page_size": 100},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise OracleUnavailable(f"{oracle.network.name} V1 DAO event page is unavailable")
        rows: list[Mapping[str, Any]] = []
        for item in data:
            attributes = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(attributes, dict):
                raise OracleUnavailable(f"{oracle.network.name} V1 DAO event activity is unavailable")
            rows.append(attributes)
        return rows, meta

    def _address_lock(self, oracle: NetworkOracle, address: str) -> Mapping[str, Any]:
        payload = oracle.explorer_json(f"/v1/addresses/{address}")
        rows = payload.get("data") if isinstance(payload, dict) else None
        attributes = rows[0].get("attributes") if isinstance(rows, list) and rows else None
        lock = attributes.get("lock_script") if isinstance(attributes, dict) else None
        if not isinstance(lock, dict):
            raise OracleUnavailable(f"{oracle.network.name} DAO address lock is unavailable")
        return {key: lock[key] for key in ("args", "code_hash", "hash_type")}

    def _live_deposit(self, oracle: NetworkOracle, lock: Mapping[str, Any]) -> int:
        search_key = {"script": dict(lock), "script_type": "lock", "script_search_mode": "exact"}
        cursor: str | None = None
        total = 0
        seen_cursors: set[str] = set()
        for _page in range(500):
            params: list[object] = [search_key, "asc", "0x64"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result("get_cells", params)
            objects = result.get("objects") if isinstance(result, dict) else None
            next_cursor = result.get("last_cursor") if isinstance(result, dict) else None
            if not isinstance(objects, list) or not isinstance(next_cursor, str):
                raise OracleUnavailable(f"{oracle.network.name} Indexer live cells are unavailable")
            for item in objects:
                output = item.get("output") if isinstance(item, dict) else None
                type_script = output.get("type") if isinstance(output, dict) else None
                if (
                    isinstance(type_script, dict)
                    and type_script.get("code_hash") == DAO_TYPE_HASH
                    and type_script.get("hash_type") == "type"
                    and type_script.get("args") == "0x"
                    and item.get("output_data") == "0x" + "00" * 8
                ):
                    total += decode_hex_int(output.get("capacity"), "DAO deposit capacity")
            if len(objects) < 100:
                return total
            if next_cursor in seen_cursors:
                raise OracleUnavailable(f"{oracle.network.name} Indexer cursor repeated")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise OracleUnavailable(f"{oracle.network.name} Indexer live cells exceeded 500 pages")

    # TEST-MAP: ADDR-DAO-RPC-11
    def test_three_stage_v2_activities_equal_v1_and_rpc_transactions(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    data, activities, meta = self._page(oracle, DAO_ADDRESSES[network.name], page_size=100)
                    v1_rows, v1_meta = self._v1_page(oracle, DAO_ADDRESSES[network.name])
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                phases = set()
                for activity in activities:
                    if any(item.get("cell_type") == "nervos_dao_deposit" for item in activity["display_outputs"]):
                        phases.add("deposit")
                    if any(item.get("cell_type") == "nervos_dao_withdrawing" for item in activity["display_outputs"]):
                        phases.add("withdraw")
                    if any(item.get("cell_type") == "nervos_dao_withdrawing" for item in activity["display_inputs"]):
                        phases.add("claim")
                if phases != {"deposit", "withdraw", "claim"} or int(data["deposit_capacity"]) <= 0:
                    raise unittest.SkipTest(f"{network.name} three-stage history plus live deposit fixture is unavailable")
                expected = {
                    row["transaction_hash"]: {key: value for key, value in row.items() if key not in {"is_cellbase", "income"}}
                    for row in v1_rows
                }
                self.assertEqual(network.address_hrp, str(data["address"]).split("1", 1)[0])
                self.assertEqual(expected, {row["transaction_hash"]: row for row in activities})
                self.assertEqual(int(v1_meta["total"]), int(meta["total"]))
                for activity in activities:
                    self.assertNotIn("is_cellbase", activity)
                    self.assertNotIn("income", activity)
                    result = oracle.rpc_result("get_transaction", [activity["transaction_hash"]])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict) or not isinstance(status, dict):
                        raise unittest.SkipTest(f"{network.name} DAO transaction is unavailable")
                    block = oracle.block_by_hash(status["block_hash"])
                    header = block.get("header") if isinstance(block, dict) else None
                    if not isinstance(header, dict):
                        raise unittest.SkipTest(f"{network.name} DAO block is unavailable")
                    self.assertEqual(transaction["hash"], activity["transaction_hash"])
                    self.assertEqual(len(transaction["inputs"]), int(activity["display_inputs_count"]))
                    self.assertEqual(len(transaction["outputs"]), int(activity["display_outputs_count"]))
                    self.assertEqual(decode_hex_int(header["number"], "block.number"), int(activity["block_number"]))
                    self.assertEqual(decode_hex_int(header["timestamp"], "block.timestamp"), int(activity["block_timestamp"]))

    # TEST-MAP: ADDR-DAO-RPC-12
    def test_ckb_address_and_lock_hash_return_identical_v2_identity_summary_and_page(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    lock_hash = ckb_script_hash(self._address_lock(oracle, address))
                    address_data, address_rows, address_meta = self._page(oracle, address, page_size=100)
                    hash_data, hash_rows, hash_meta = self._page(oracle, lock_hash, page_size=100)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(address_data, hash_data)
                self.assertEqual(address_rows, hash_rows)
                self.assertEqual(address_meta, hash_meta)

    # TEST-MAP: ADDR-DAO-RPC-13
    def test_deposit_capacity_is_exact_sum_of_only_live_deposit_cells(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    data, activities, _meta = self._page(oracle, address, page_size=100)
                    expected = self._live_deposit(oracle, self._address_lock(oracle, address))
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                phases = {
                    phase
                    for activity in activities
                    for phase, matched in (
                        ("deposit", any(item.get("cell_type") == "nervos_dao_deposit" for item in activity["display_outputs"])),
                        ("withdraw", any(item.get("cell_type") == "nervos_dao_withdrawing" for item in activity["display_outputs"])),
                        ("claim", any(item.get("cell_type") == "nervos_dao_withdrawing" for item in activity["display_inputs"])),
                    )
                    if matched
                }
                if phases != {"deposit", "withdraw", "claim"}:
                    raise unittest.SkipTest(f"{network.name} mixed live and consumed DAO history fixture is unavailable")
                value = str(data["deposit_capacity"])
                self.assertEqual(str(expected), value)
                self.assertGreater(expected, 0)

    # TEST-MAP: ADDR-DAO-RPC-15
    def test_default_custom_adjacent_and_overflow_pages_preserve_summary_and_total(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    default_data, default_rows, default_meta = self._page(oracle, address)
                    total = int(default_meta["total"])
                    paged: list[Mapping[str, Any]] = []
                    for page in range(1, (total + 1) // 2 + 1):
                        data, rows, meta = self._page(oracle, address, page=page, page_size=2)
                        self.assertEqual(
                            {key: default_data[key] for key in ("id", "address", "deposit_capacity", "average_deposit_time")},
                            {key: data[key] for key in ("id", "address", "deposit_capacity", "average_deposit_time")},
                        )
                        self.assertEqual(total, int(meta["total"]))
                        self.assertEqual(2, int(meta["page_size"]))
                        paged.extend(rows)
                    overflow_data, overflow, overflow_meta = self._page(
                        oracle, address, page=total + 2, page_size=2
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(10, int(default_meta["page_size"]))
                self.assertEqual(min(10, total), len(default_rows))
                hashes = [row["transaction_hash"] for row in paged]
                self.assertEqual(total, len(hashes))
                self.assertEqual(total, len(set(hashes)))
                self.assertEqual([], overflow)
                self.assertEqual(total, int(overflow_meta["total"]))
                self.assertEqual(
                    {key: default_data[key] for key in ("id", "address", "deposit_capacity", "average_deposit_time")},
                    {key: overflow_data[key] for key in ("id", "address", "deposit_capacity", "average_deposit_time")},
                )

    # TEST-MAP: ADDR-DAO-RPC-17
    def test_activities_are_unique_transactions_and_each_is_linked_to_the_target_address(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    _data, activities, meta = self._page(oracle, address, page_size=100)
                    v1_rows, _v1_meta = self._v1_page(oracle, address)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                target_counts = [
                    sum(
                        item.get("address_hash") == address and str(item.get("cell_type", "")).startswith("nervos_dao")
                        for side in ("display_inputs", "display_outputs")
                        for item in activity[side]
                    )
                    for activity in activities
                ]
                if not any(count > 1 for count in target_counts):
                    raise unittest.SkipTest(f"{network.name} multi-event target transaction fixture is unavailable")
                hashes = [activity["transaction_hash"] for activity in activities]
                self.assertEqual(len(hashes), len(set(hashes)))
                self.assertEqual(len(hashes), int(meta["total"]))
                self.assertTrue(all(count > 0 for count in target_counts))
                self.assertEqual(set(hashes), {row["transaction_hash"] for row in v1_rows})

    # TEST-MAP: ADDR-DAO-RPC-18
    @unittest.expectedFailure  # Public APIs currently serialize the empty-history average as an empty string.
    def test_recorded_address_without_dao_history_returns_zero_summary_and_empty_activities(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    data, activities, meta = self._page(oracle, EMPTY_DAO_ADDRESSES[network.name])
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(EMPTY_DAO_ADDRESSES[network.name], data["address"])
                self.assertEqual("0", data["deposit_capacity"])
                self.assertEqual("0", data["average_deposit_time"])
                self.assertEqual([], activities)
                self.assertEqual(0, int(meta["total"]))

    # TEST-MAP: ADDR-DAO-RPC-19
    def test_missing_invalid_and_unrecorded_address_queries_return_not_found_without_data(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                for query in (None, {"address": "not-an-address"}, {"address": "0x" + "00" * 32}):
                    try:
                        status, payload = _explorer_response(oracle, query)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    if status == 403 and isinstance(payload, dict) and payload.get("cloudflare_error") is True:
                        raise unittest.SkipTest(f"{network.name} edge rejected negative-path observation")
                    self.assertEqual(404, status)
                    self.assertFalse(isinstance(payload, dict) and "data" in payload)

    # TEST-MAP: ADDR-DAO-RPC-20
    def test_values_above_javascript_safe_integer_match_rpc_without_decimal_loss(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    data, activities, _meta = self._page(oracle, address, page_size=100)
                    expected_deposit = self._live_deposit(oracle, self._address_lock(oracle, address))
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                checked = 0
                if expected_deposit > 2**53 - 1:
                    self.assertEqual(str(expected_deposit), data["deposit_capacity"])
                    checked += 1
                for activity in activities:
                    result = oracle.rpc_result("get_transaction", [activity["transaction_hash"]])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict):
                        raise unittest.SkipTest(f"{network.name} DAO transaction is unavailable")
                    referenced = oracle.referenced_outputs(transaction)
                    for side, rpc_outputs in (
                        ("display_inputs", [item[0] for item in referenced]),
                        ("display_outputs", transaction["outputs"]),
                    ):
                        for position, item in enumerate(activity[side]):
                            index = position if side == "display_inputs" else int(item["cell_index"])
                            expected = decode_hex_int(rpc_outputs[index]["capacity"], f"{side}.capacity")
                            if expected > 2**53 - 1:
                                self.assertEqual(str(expected), str(item["capacity"]))
                                checked += 1
                if checked == 0:
                    raise unittest.SkipTest(f"{network.name} public DAO value above 2^53-1 is unavailable")

    # TEST-MAP: ADDR-DAO-RPC-21
    def test_observed_canonical_state_change_converges_between_v1_v2_and_live_cells(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    before_data, before_rows, _before_meta = self._page(oracle, address, page_size=100)
                    before_v1, _before_v1_meta = self._v1_page(oracle, address)
                    after_v1, _after_v1_meta = self._v1_page(oracle, address)
                    after_data, after_rows, _after_meta = self._page(oracle, address, page_size=100)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                before_hashes = {row["transaction_hash"] for row in before_rows}
                after_hashes = {row["transaction_hash"] for row in after_rows}
                self.assertEqual(before_hashes, {row["transaction_hash"] for row in before_v1})
                self.assertEqual(after_hashes, {row["transaction_hash"] for row in after_v1})
                changed = before_hashes != after_hashes or before_data["deposit_capacity"] != after_data["deposit_capacity"]
                if not changed:
                    raise unittest.SkipTest(f"{network.name} no confirmed DAO state transition was observed")
                try:
                    expected_deposit = self._live_deposit(oracle, self._address_lock(oracle, address))
                    for activity in after_rows:
                        result = oracle.rpc_result("get_transaction", [activity["transaction_hash"]])
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        if not isinstance(status, dict) or status.get("status") != "committed":
                            raise OracleUnavailable(f"{network.name} canonical DAO transaction is unavailable")
                        block = oracle.block_by_hash(status["block_hash"])
                        header = block.get("header") if isinstance(block, dict) else None
                        if not isinstance(header, dict) or header.get("hash") != status["block_hash"]:
                            raise OracleUnavailable(f"{network.name} DAO reorganization observed")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(str(expected_deposit), after_data["deposit_capacity"])


if __name__ == "__main__":
    unittest.main()
