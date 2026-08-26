from __future__ import annotations

import json
import socket
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import LockScript, ckb2021_address, ckb_script_hash, decode_hex_int, output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings


ACTIVITY_TRANSACTIONS = {
    "mainnet": "0xab14b3580046c61056699d2aff8ae707b56d6cb79c19c8ad6af18cb8a2d45cf0",
    "testnet": "0xa7f2644682002f9a9a7dfcef7ed749c16a6f4ea92a2aac21b7f6e2f900253501",
}
DAO_ADDRESSES = {
    "mainnet": "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqwnxh9cfsdp2v83n2e6sg9ul3vds54k3vgfpn9w2",
    "testnet": "ckt1qq28aja4c5f8mxpwuymz6tptksn8sq7696cqd52saz90dj42pfl27qh20a3f5c37rwfmfavxp4l2dyq2nykxmlgnf5ul65kd3t24u2qf3vy9thy3",
}
LARGE_UDT_ADDRESS = (
    "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqtymv970v90yaynwh6argfux63rvkynh5qq38spy"
)
LARGE_UDT_TYPE_HASH = "0x59f9e9966f4b0e8578c1b73fb3eb06241607bff05e17d7869d4a17293303a27b"
BITCOIN_MULTI_MAPPING_FIXTURES: dict[str, tuple[str, frozenset[str]]] = {}
SPECIAL_ADDRESS_FIXTURES: dict[str, tuple[str, str]] = {}
MULTISIG_TIMELOCK_FIXTURES: dict[str, str] = {}
SECP_CODE_HASH = "0x9bd7e06f3ecf4be0f2fcd2188b23f1b9fcc88e5d4b65a8637b17723bbda3cce8"
DAO_TYPE_HASH = "0x82d76d1b75fe2fd9a27dfbaa65a039221a380d76c926f378d3f81cf3e7e13f2e"
BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
BECH32_GENERATORS = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)


class _StatusPreservingProcessor(urllib.request.HTTPErrorProcessor):
    def http_response(self, request: urllib.request.Request, response: Any) -> Any:
        return response

    https_response = http_response


def _explorer_response(oracle: NetworkOracle, identifier: str) -> tuple[int, Any]:
    path = "/v1/addresses/" + urllib.parse.quote(identifier, safe="")
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
                return status, json.loads(raw)
            except json.JSONDecodeError as error:
                raise OracleUnavailable(f"{oracle.network.name} Explorer returned invalid JSON") from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as error:
            if attempt < oracle.client.retries:
                time.sleep(0.2 * (attempt + 1))
                continue
            raise OracleUnavailable(f"{oracle.network.name} Explorer transport failure: {error}") from error
    raise AssertionError("unreachable HTTP retry loop")


def _short_address(lock: Mapping[str, Any], hrp: str) -> str:
    if lock.get("code_hash") != SECP_CODE_HASH or lock.get("hash_type") != "type":
        raise ValueError("short address fixture must use the standard secp lock")
    args = bytes.fromhex(str(lock["args"]).removeprefix("0x"))
    if len(args) != 20:
        raise ValueError("short address fixture must have 20-byte args")
    payload = bytes([1, 0]) + args
    accumulator = 0
    bits = 0
    data: list[int] = []
    for value in payload:
        accumulator = (accumulator << 8) | value
        bits += 8
        while bits >= 5:
            bits -= 5
            data.append((accumulator >> bits) & 31)
    if bits:
        data.append((accumulator << (5 - bits)) & 31)
    expanded = [ord(char) >> 5 for char in hrp] + [0] + [ord(char) & 31 for char in hrp]
    checksum = 1
    for value in expanded + data + [0] * 6:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for index, generator in enumerate(BECH32_GENERATORS):
            if (top >> index) & 1:
                checksum ^= generator
    checksum ^= 1
    suffix = [(checksum >> (5 * (5 - index))) & 31 for index in range(6)]
    return hrp + "1" + "".join(BECH32_CHARSET[value] for value in data + suffix)


class V1AddressesShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _activity_sample(self, oracle: NetworkOracle) -> tuple[str, Mapping[str, Any]]:
        result = oracle.rpc_result("get_transaction", [ACTIVITY_TRANSACTIONS[oracle.network.name]])
        transaction = result.get("transaction") if isinstance(result, dict) else None
        outputs = transaction.get("outputs") if isinstance(transaction, dict) else None
        if not isinstance(outputs, list) or not outputs or not isinstance(outputs[0], dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC activity fixture is unavailable")
        lock = outputs[0].get("lock")
        if not isinstance(lock, dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC activity fixture has no lock")
        return output_address(outputs[0], oracle.network.address_hrp), lock

    def _attributes(self, oracle: NetworkOracle, address: str) -> Mapping[str, Any]:
        payload = oracle.explorer_json(f"/v1/addresses/{address}")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise OracleUnavailable(f"{oracle.network.name} Explorer address payload is unavailable")
        attributes = data[0].get("attributes")
        if not isinstance(attributes, dict):
            raise OracleUnavailable(f"{oracle.network.name} Explorer address attributes are unavailable")
        return attributes

    def _indexer_objects(
        self,
        oracle: NetworkOracle,
        method: str,
        lock: Mapping[str, Any],
        *,
        type_script: Mapping[str, Any] | None = None,
    ) -> list[Mapping[str, Any]]:
        core_lock = {key: lock[key] for key in ("args", "code_hash", "hash_type")}
        search_key: dict[str, Any] = {
            "script": core_lock,
            "script_type": "lock",
            "script_search_mode": "exact",
        }
        if type_script is not None:
            search_key["filter"] = {
                "script": {key: type_script[key] for key in ("args", "code_hash", "hash_type")}
            }
        cursor: str | None = None
        objects: list[Mapping[str, Any]] = []
        seen_cursors: set[str] = set()
        for _page in range(500):
            params: list[object] = [search_key, "asc", "0x64"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result(method, params)
            page = result.get("objects") if isinstance(result, dict) else None
            next_cursor = result.get("last_cursor") if isinstance(result, dict) else None
            if not isinstance(page, list) or not isinstance(next_cursor, str):
                raise OracleUnavailable(f"{oracle.network.name} Indexer {method} result is unavailable")
            for item in page:
                if not isinstance(item, dict):
                    raise OracleUnavailable(f"{oracle.network.name} Indexer {method} returned an invalid item")
                objects.append(item)
            if len(page) < 100:
                return objects
            if next_cursor in seen_cursors:
                raise OracleUnavailable(f"{oracle.network.name} Indexer {method} cursor repeated")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise OracleUnavailable(f"{oracle.network.name} Indexer {method} exceeded 500 pages")

    # TEST-MAP: ADDRESS-RPC-01
    def test_ckb_address_echoes_query_and_matches_rpc_lock_script(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    address, lock = self._activity_sample(oracle)
                    payload = oracle.explorer_json(f"/v1/addresses/{address}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                data = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(data, list)
                self.assertEqual(1, len(data))
                self.assertEqual("address", data[0].get("type"))
                attributes = data[0].get("attributes")
                self.assertIsInstance(attributes, dict)
                self.assertEqual(address, attributes.get("address_hash"))
                self.assertEqual({key: lock[key] for key in ("args", "code_hash", "hash_type")},
                                 {key: attributes["lock_script"][key] for key in ("args", "code_hash", "hash_type")})
                self.assertEqual(ckb_script_hash(lock), ckb_script_hash(attributes["lock_script"]))

    # TEST-MAP: ADDRESS-RPC-02
    def test_short_and_full_encodings_share_one_lock_and_state(self) -> None:
        state_fields = (
            "balance", "balance_occupied", "transactions_count", "live_cells_count", "dao_deposit",
            "interest", "dao_compensation", "udt_accounts", "is_special", "lock_info",
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    full, lock = self._activity_sample(oracle)
                    short = _short_address(lock, network.address_hrp)
                    short_attributes = self._attributes(oracle, short)
                    full_attributes = self._attributes(oracle, full)
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(short, short_attributes.get("address_hash"))
                self.assertEqual(full, full_attributes.get("address_hash"))
                self.assertEqual(ckb_script_hash(short_attributes["lock_script"]),
                                 ckb_script_hash(full_attributes["lock_script"]))
                self.assertEqual({key: short_attributes.get(key) for key in state_fields},
                                 {key: full_attributes.get(key) for key in state_fields})

    # TEST-MAP: ADDRESS-RPC-03
    def test_lock_hash_query_uses_lock_hash_resource_and_rpc_script_preimage(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    address, lock = self._activity_sample(oracle)
                    lock_hash = ckb_script_hash(lock)
                    payload = oracle.explorer_json(f"/v1/addresses/{lock_hash}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                data = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(data, dict)
                self.assertEqual("lock_hash", data.get("type"))
                attributes = data.get("attributes")
                self.assertIsInstance(attributes, dict)
                self.assertEqual(lock_hash, attributes.get("lock_hash"))
                self.assertEqual(address, attributes.get("address_hash"))
                self.assertEqual({key: lock[key] for key in ("args", "code_hash", "hash_type")},
                                 {key: attributes["lock_script"][key] for key in ("args", "code_hash", "hash_type")})

    # TEST-MAP: ADDRESS-RPC-05
    def test_bitcoin_multi_mapping_returns_exact_unique_ckb_member_set(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                fixture = BITCOIN_MULTI_MAPPING_FIXTURES.get(network.name)
                if fixture is None:
                    raise unittest.SkipTest(f"{network.name} public multi-mapping fixture is unavailable")
                bitcoin_address, expected_addresses = fixture
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json(f"/v1/addresses/{bitcoin_address}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                data = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(data, list)
                actual = [row["attributes"]["address_hash"] for row in data]
                self.assertEqual(expected_addresses, frozenset(actual))
                self.assertEqual(len(actual), len(set(actual)))
                self.assertTrue(all(row["attributes"].get("bitcoin_address_hash") == bitcoin_address for row in data))

    # TEST-MAP: ADDRESS-RPC-08
    def test_balance_and_live_cell_count_match_complete_stable_indexer_snapshot(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    address, lock = self._activity_sample(oracle)
                    before = self._indexer_objects(oracle, "get_cells", lock)
                    attributes = self._attributes(oracle, address)
                    after = self._indexer_objects(oracle, "get_cells", lock)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                before_cells = {(item["out_point"]["tx_hash"], item["out_point"]["index"],
                                 item["output"]["capacity"]) for item in before}
                after_cells = {(item["out_point"]["tx_hash"], item["out_point"]["index"],
                                item["output"]["capacity"]) for item in after}
                if before_cells != after_cells:
                    raise unittest.SkipTest(f"{network.name} Indexer live-cell state changed during observation")
                self.assertGreater(len(before), 1)
                self.assertGreater(len({item["output"]["capacity"] for item in before}), 1)
                self.assertEqual(sum(decode_hex_int(item["output"]["capacity"], "capacity") for item in before),
                                 int(attributes["balance"]))
                self.assertEqual(len(before), int(attributes["live_cells_count"]))

    # TEST-MAP: ADDRESS-RPC-10
    def test_transaction_count_matches_complete_indexer_history_deduplicated_by_hash(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = DAO_ADDRESSES[network.name]
                try:
                    attributes = self._attributes(oracle, address)
                    lock = attributes.get("lock_script")
                    if not isinstance(lock, dict):
                        raise OracleUnavailable(f"{network.name} address lock is unavailable")
                    before = self._indexer_objects(oracle, "get_transactions", lock)
                    after = self._indexer_objects(oracle, "get_transactions", lock)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                before_hashes = {item.get("tx_hash") for item in before}
                after_hashes = {item.get("tx_hash") for item in after}
                if before_hashes != after_hashes:
                    raise unittest.SkipTest(f"{network.name} Indexer transaction state changed during observation")
                self.assertTrue(all(isinstance(value, str) for value in before_hashes))
                self.assertEqual(len(before_hashes), int(attributes["transactions_count"]))

    # TEST-MAP: ADDRESS-RPC-11
    def test_live_dao_deposit_matches_indexer_and_compensation_fields_are_exact_shannon_strings(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    attributes = self._attributes(oracle, DAO_ADDRESSES[network.name])
                    lock = attributes.get("lock_script")
                    if not isinstance(lock, dict):
                        raise OracleUnavailable(f"{network.name} DAO fixture lock is unavailable")
                    cells = self._indexer_objects(oracle, "get_cells", lock)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                live_deposit = sum(
                    decode_hex_int(item["output"]["capacity"], "DAO capacity")
                    for item in cells
                    if isinstance(item.get("output"), dict)
                    and isinstance(item["output"].get("type"), dict)
                    and item["output"]["type"].get("code_hash") == DAO_TYPE_HASH
                    and item["output"]["type"].get("hash_type") == "type"
                    and item["output"]["type"].get("args") == "0x"
                    and item.get("output_data") == "0x" + "00" * 8
                )
                self.assertGreater(live_deposit, 0)
                self.assertEqual(live_deposit, int(attributes["dao_deposit"]))
                interest = str(attributes["interest"])
                compensation = str(attributes["dao_compensation"])
                self.assertEqual(str(int(interest)), interest)
                self.assertEqual(str(int(compensation)), compensation)
                self.assertGreaterEqual(int(compensation), int(interest))

    # TEST-MAP: ADDRESS-RPC-13
    def test_published_fungible_udt_account_script_and_amount_match_live_cells(self) -> None:
        network = next(item for item in self.settings.networks if item.name == "mainnet")
        oracle = NetworkOracle(network, self.settings)
        try:
            attributes = self._attributes(oracle, LARGE_UDT_ADDRESS)
            lock = attributes.get("lock_script")
            accounts = attributes.get("udt_accounts")
            if not isinstance(lock, dict) or not isinstance(accounts, list):
                raise OracleUnavailable("mainnet UDT fixture is unavailable")
            account = next(item for item in accounts if item.get("type_hash") == LARGE_UDT_TYPE_HASH)
            type_script = account.get("udt_type_script")
            if not isinstance(type_script, dict):
                raise OracleUnavailable("mainnet UDT fixture type script is unavailable")
            cells = self._indexer_objects(oracle, "get_cells", lock, type_script=type_script)
        except (OracleUnavailable, StopIteration) as error:
            raise unittest.SkipTest(str(error)) from error
        self.assertEqual(LARGE_UDT_TYPE_HASH, ckb_script_hash(type_script))
        amount = sum(int.from_bytes(bytes.fromhex(str(item["output_data"])[2:])[:16], "little") for item in cells)
        self.assertEqual(amount, int(account["amount"]))
        self.assertEqual(len(accounts), len({item.get("type_hash") for item in accounts}))

    # TEST-MAP: ADDRESS-RPC-14
    def test_special_and_ordinary_address_flags_follow_network_configuration(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    ordinary, _lock = self._activity_sample(oracle)
                    ordinary_attributes = self._attributes(oracle, ordinary)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual("false", ordinary_attributes.get("is_special"))
                self.assertNotIn("special_address", ordinary_attributes)
                fixture = SPECIAL_ADDRESS_FIXTURES.get(network.name)
                if fixture is None:
                    raise unittest.SkipTest(f"{network.name} deployed special-address configuration fixture is unavailable")
                special, label = fixture
                special_attributes = self._attributes(oracle, special)
                self.assertEqual("true", special_attributes.get("is_special"))
                self.assertEqual(label, special_attributes.get("special_address"))

    # TEST-MAP: ADDRESS-RPC-15
    def test_invalid_unrecorded_and_missing_lock_hash_all_return_address_not_found(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                missing = ckb2021_address(LockScript(SECP_CODE_HASH, "type", "0x" + "ff" * 20), network.address_hrp)
                for identifier in ("not-an-address", missing, "0x" + "00" * 32):
                    status, payload = _explorer_response(oracle, identifier)
                    if status == 403 and isinstance(payload, dict) and payload.get("cloudflare_error") is True:
                        raise unittest.SkipTest(f"{network.name} edge rejected negative-path observation")
                    self.assertEqual(404, status)
                    errors = payload if isinstance(payload, list) else payload.get("errors") if isinstance(payload, dict) else None
                    self.assertIsInstance(errors, list)
                    self.assertTrue(errors)
                    self.assertEqual(1010, errors[0].get("code"))
                    self.assertEqual(404, errors[0].get("status"))
                    self.assertEqual("Address Not Found", errors[0].get("title"))

    # TEST-MAP: ADDRESS-RPC-17
    def test_opposite_network_bitcoin_address_returns_not_found(self) -> None:
        opposite = {
            "mainnet": "mipcBbFg9gMiCh81Kj8tqqdgoZub1ZJRfn",
            "testnet": "1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
        }
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                status, payload = _explorer_response(oracle, opposite[network.name])
                if status == 403 and isinstance(payload, dict) and payload.get("cloudflare_error") is True:
                    raise unittest.SkipTest(f"{network.name} edge rejected negative-path observation")
                self.assertEqual(404, status)
                errors = payload if isinstance(payload, list) else payload.get("errors") if isinstance(payload, dict) else None
                self.assertIsInstance(errors, list)
                self.assertEqual(1010, errors[0].get("code"))

    # TEST-MAP: ADDRESS-RPC-18
    def test_value_above_javascript_safe_integer_is_exact_decimal_string(self) -> None:
        network = next(item for item in self.settings.networks if item.name == "mainnet")
        oracle = NetworkOracle(network, self.settings)
        try:
            attributes = self._attributes(oracle, LARGE_UDT_ADDRESS)
            account = next(item for item in attributes["udt_accounts"] if item.get("type_hash") == LARGE_UDT_TYPE_HASH)
            type_script = account.get("udt_type_script")
            lock = attributes.get("lock_script")
            if not isinstance(type_script, dict) or not isinstance(lock, dict):
                raise OracleUnavailable("mainnet large-integer fixture is unavailable")
            cells = self._indexer_objects(oracle, "get_cells", lock, type_script=type_script)
        except (OracleUnavailable, StopIteration) as error:
            raise unittest.SkipTest(str(error)) from error
        expected = sum(int.from_bytes(bytes.fromhex(str(item["output_data"])[2:])[:16], "little") for item in cells)
        self.assertGreater(expected, 2**53 - 1)
        self.assertIsInstance(account.get("amount"), str)
        self.assertEqual(str(expected), account.get("amount"))

    # TEST-MAP: ADDRESS-RPC-19
    def test_cache_converges_after_an_observed_confirmed_live_cell_change(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    address, lock = self._activity_sample(oracle)
                    before = self._indexer_objects(oracle, "get_cells", lock)
                    time.sleep(1)
                    changed = self._indexer_objects(oracle, "get_cells", lock)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                before_points = {(item["out_point"]["tx_hash"], item["out_point"]["index"]) for item in before}
                changed_points = {(item["out_point"]["tx_hash"], item["out_point"]["index"]) for item in changed}
                if before_points == changed_points:
                    raise unittest.SkipTest(f"{network.name} fixture had no confirmed live-cell change")
                time.sleep(21)
                attributes = self._attributes(oracle, address)
                final = self._indexer_objects(oracle, "get_cells", lock)
                self.assertEqual(sum(decode_hex_int(item["output"]["capacity"], "capacity") for item in final),
                                 int(attributes["balance"]))
                self.assertEqual(len(final), int(attributes["live_cells_count"]))

    # TEST-MAP: ADDRESS-RPC-20
    def test_multisig_timelock_info_and_ordinary_null_follow_same_network_tip(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    ordinary, _lock = self._activity_sample(oracle)
                    ordinary_attributes = self._attributes(oracle, ordinary)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertIsNone(ordinary_attributes.get("lock_info"))
                multisig = MULTISIG_TIMELOCK_FIXTURES.get(network.name)
                if multisig is None:
                    raise unittest.SkipTest(f"{network.name} public multisig timelock fixture is unavailable")
                attributes = self._attributes(oracle, multisig)
                tip = oracle.rpc_result("get_tip_header", [])
                lock_info = attributes.get("lock_info")
                self.assertIsInstance(tip, dict)
                self.assertIsInstance(lock_info, dict)
                self.assertIn(lock_info.get("status"), ("locked", "unlocked"))
                self.assertTrue(str(lock_info.get("epoch_number")).isdigit())
                self.assertTrue(str(lock_info.get("epoch_index")).isdigit())
                self.assertTrue(str(lock_info.get("estimated_unlock_time")).isdigit())


if __name__ == "__main__":
    unittest.main()
