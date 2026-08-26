from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import quote, urlencode

from ckb_rpc_correctness.ckb import (
    ckb_script_hash,
    decode_hex_int,
    output_address,
    output_occupied_capacity,
)
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


UDT_FIXTURES = {
    "mainnet": "0xbc48f995eee8f5c2a5610985a5cc02d5d01f08b1a5c42230716191fca29afb76",
    "testnet": "0x0c5375feaaa7dd2a98807444b9bf3d218d3f5d36063e07fbc6c41dbda2fab936",
}
EMPTY_UDT_FIXTURES = {
    "mainnet": "0x2b60a41da2bc100ccfb8e5e9781c240ede570b56df04a27a162e32146dc6673f",
    "testnet": "0xf37f387231b00aebaa12981a8dcb3ccebec78cb2e8f34f79e5e89c6ddb0fbf51",
}


class V1UdtTransactionsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.page_cache: dict[
            tuple[str, str, tuple[tuple[str, object], ...]],
            tuple[list[Mapping[str, Any]], Mapping[str, Any]],
        ] = {}

    def _page(
        self,
        oracle: NetworkOracle,
        type_hash: str,
        **query: object,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        key = (oracle.network.name, type_hash, tuple(sorted(query.items())))
        if key not in self.page_cache:
            payload = oracle.explorer_json(f"/v1/udt_transactions/{type_hash}", query or None)
            data = payload.get("data") if isinstance(payload, dict) else None
            meta = payload.get("meta") if isinstance(payload, dict) else None
            if not isinstance(data, list) or not isinstance(meta, dict):
                raise OracleUnavailable(f"{oracle.network.name} UDT transaction page is unavailable")
            rows: list[Mapping[str, Any]] = []
            for item in data:
                attributes = item.get("attributes") if isinstance(item, dict) else None
                if not isinstance(attributes, dict):
                    raise OracleUnavailable(f"{oracle.network.name} UDT transaction row is unavailable")
                rows.append(attributes)
            self.page_cache[key] = rows, meta
        return self.page_cache[key]

    def _all(
        self,
        oracle: NetworkOracle,
        type_hash: str,
        **query: object,
    ) -> list[Mapping[str, Any]]:
        params = dict(query)
        params.update(page=1, page_size=100)
        first, meta = self._page(oracle, type_hash, **params)
        try:
            total = int(meta["total"])
        except (KeyError, TypeError, ValueError) as error:
            raise OracleUnavailable(f"{oracle.network.name} UDT transaction total is unavailable") from error
        rows = list(first)
        for page in range(2, (total + 99) // 100 + 1):
            params["page"] = page
            current, current_meta = self._page(oracle, type_hash, **params)
            if int(current_meta.get("total", -1)) != total:
                raise OracleUnavailable(f"{oracle.network.name} UDT history changed during pagination")
            rows.extend(current)
        if len(rows) != total:
            raise OracleUnavailable(f"{oracle.network.name} UDT transaction pagination omitted rows")
        return rows

    def _type_script(self, oracle: NetworkOracle, type_hash: str) -> Mapping[str, Any]:
        payload = oracle.explorer_json(f"/v1/udts/{type_hash}")
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        script = attributes.get("type_script") if isinstance(attributes, dict) else None
        if not isinstance(script, dict):
            raise OracleUnavailable(f"{oracle.network.name} UDT Type Script is unavailable")
        if ckb_script_hash(script) != type_hash:
            raise OracleUnavailable(f"{oracle.network.name} UDT Type Script hash is inconsistent")
        return script

    def _indexer_hashes(self, oracle: NetworkOracle, script: Mapping[str, Any]) -> set[str]:
        search_key = {"script": script, "script_type": "type", "script_search_mode": "exact"}
        hashes: set[str] = set()
        cursor: str | None = None
        for _page in range(100):
            params: list[object] = [search_key, "asc", "0x64"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result("get_transactions", params)
            objects = result.get("objects") if isinstance(result, dict) else None
            if not isinstance(objects, list) or any(not isinstance(item, dict) for item in objects):
                raise OracleUnavailable(f"{oracle.network.name} UDT Indexer history is unavailable")
            for item in objects:
                tx_hash = item.get("tx_hash")
                if not isinstance(tx_hash, str):
                    raise OracleUnavailable(f"{oracle.network.name} UDT Indexer hash is unavailable")
                hashes.add(tx_hash)
            if len(objects) < 100:
                return hashes
            next_cursor = result.get("last_cursor")
            if not isinstance(next_cursor, str) or next_cursor == cursor:
                raise OracleUnavailable(f"{oracle.network.name} UDT Indexer cursor is unavailable")
            cursor = next_cursor
        raise OracleUnavailable(f"{oracle.network.name} UDT Indexer history did not terminate")

    # TEST-MAP: UDT-TX-RPC-01
    # TEST-MAP: UDT-TX-RPC-13
    def test_committed_unique_membership_matches_same_network_indexer_type_script_history(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                type_hash = UDT_FIXTURES[network.name]
                try:
                    rows = self._all(oracle, type_hash)
                    script = self._type_script(oracle, type_hash)
                    indexer_hashes = self._indexer_hashes(oracle, script)
                    hashes = [str(row["transaction_hash"]) for row in rows]
                    results = oracle.rpc_batch_results(
                        [("get_transaction", [tx_hash]) for tx_hash in hashes]
                    )
                except (OracleUnavailable, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertGreater(len(hashes), 0)
                self.assertEqual(len(hashes), len(set(hashes)))
                self.assertEqual(indexer_hashes, set(hashes))
                for tx_hash, result in zip(hashes, results, strict=True):
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict) or not isinstance(status, dict):
                        raise unittest.SkipTest(f"{network.name} RPC transaction {tx_hash} is unavailable")
                    self.assertEqual(tx_hash, transaction.get("hash"))
                    self.assertEqual("committed", status.get("status"))

    # TEST-MAP: UDT-TX-RPC-02
    def test_default_adjacent_and_oversized_pages_follow_rpc_block_time_and_index_order(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                type_hash = UDT_FIXTURES[network.name]
                try:
                    default, default_meta = self._page(oracle, type_hash)
                    first, first_meta = self._page(oracle, type_hash, page=1, page_size=1)
                    second, second_meta = self._page(oracle, type_hash, page=2, page_size=1)
                    combined, combined_meta = self._page(oracle, type_hash, page=1, page_size=2)
                    oversized, oversized_meta = self._page(oracle, type_hash, page=1, page_size=101)
                    hashes = [str(row["transaction_hash"]) for row in default]
                    results = oracle.rpc_batch_results(
                        [("get_transaction", [tx_hash]) for tx_hash in hashes]
                    )
                    observations: list[tuple[int, int]] = []
                    for tx_hash, result in zip(hashes, results, strict=True):
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        block_hash = status.get("block_hash") if isinstance(status, dict) else None
                        if not isinstance(status, dict) or not isinstance(block_hash, str):
                            raise OracleUnavailable(f"{network.name} RPC status for {tx_hash} is unavailable")
                        block = oracle.block_by_hash(block_hash)
                        header = block.get("header") if isinstance(block, dict) else None
                        if not isinstance(header, dict):
                            raise OracleUnavailable(f"{network.name} RPC block for {tx_hash} is unavailable")
                        observations.append(
                            (
                                decode_hex_int(header.get("timestamp"), "transaction.block_timestamp"),
                                decode_hex_int(status.get("tx_index"), "transaction.tx_index"),
                            )
                        )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(10, int(default_meta["page_size"]))
                self.assertEqual(first + second, combined[:2])
                self.assertEqual(first_meta["total"], second_meta["total"])
                self.assertEqual(first_meta["total"], combined_meta["total"])
                self.assertLessEqual(int(oversized_meta["page_size"]), 100)
                self.assertLessEqual(len(oversized), int(oversized_meta["page_size"]))
                self.assertEqual(observations, sorted(observations, reverse=True))

    # TEST-MAP: UDT-TX-RPC-03
    def test_zero_negative_noninteger_and_combined_invalid_pagination_report_all_fields(self) -> None:
        cases = (
            ({"page": 0}, {1007}),
            ({"page": -1}, {1007}),
            ({"page": "x"}, {1007}),
            ({"page_size": 0}, {1008}),
            ({"page_size": -1}, {1008}),
            ({"page_size": "x"}, {1008}),
            ({"page": 0, "page_size": "x"}, {1007, 1008}),
        )
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            for query, expected_codes in cases:
                with self.subTest(network=network.name, query=query):
                    path = (
                        f"/v1/udt_transactions/{UDT_FIXTURES[network.name]}?"
                        + urlencode(query)
                    )
                    try:
                        status, raw = _raw_explorer_response(oracle, path)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(400, status)
                    payload = json.loads(raw)
                    self.assertEqual(expected_codes, {int(error["code"]) for error in payload})
                    self.assertFalse(any("data" in error for error in payload))

    # TEST-MAP: UDT-TX-RPC-04
    def test_transaction_hash_filter_returns_exact_member_or_empty_without_cross_udt_match(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                type_hash = UDT_FIXTURES[network.name]
                try:
                    rows = self._all(oracle, type_hash)
                    member_hash = str(rows[0]["transaction_hash"])
                    member, member_meta = self._page(oracle, type_hash, tx_hash=member_hash)
                    genesis = oracle.block(0)
                    transactions = genesis.get("transactions") if isinstance(genesis, dict) else None
                    other_hash = transactions[0].get("hash") if isinstance(transactions, list) and transactions else None
                    if not isinstance(other_hash, str):
                        raise OracleUnavailable(f"{network.name} genesis transaction is unavailable")
                    other, other_meta = self._page(oracle, type_hash, tx_hash=other_hash)
                except (OracleUnavailable, IndexError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual([member_hash], [row["transaction_hash"] for row in member])
                self.assertEqual(1, int(member_meta["total"]))
                self.assertEqual([], other)
                self.assertEqual(0, int(other_meta["total"]))

    # TEST-MAP: UDT-TX-RPC-05
    def test_address_filter_is_the_deduplicated_intersection_with_rpc_input_output_participation(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                type_hash = UDT_FIXTURES[network.name]
                try:
                    rows = self._all(oracle, type_hash)
                    hashes = [str(row["transaction_hash"]) for row in rows]
                    results = oracle.rpc_batch_results(
                        [("get_transaction", [tx_hash]) for tx_hash in hashes]
                    )
                    addresses_by_hash: dict[str, set[str]] = {}
                    for tx_hash, result in zip(hashes, results, strict=True):
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict):
                            raise OracleUnavailable(f"{network.name} RPC transaction {tx_hash} is unavailable")
                        outputs = transaction.get("outputs")
                        if not isinstance(outputs, list) or any(not isinstance(output, dict) for output in outputs):
                            raise OracleUnavailable(f"{network.name} RPC outputs for {tx_hash} are unavailable")
                        addresses = {output_address(output, network.address_hrp) for output in outputs}
                        addresses.update(
                            output_address(output, network.address_hrp)
                            for output, _data in oracle.referenced_outputs(transaction)
                        )
                        addresses_by_hash[tx_hash] = addresses
                    candidates = set().union(*addresses_by_hash.values())
                    target = min(
                        candidates,
                        key=lambda address: sum(address in values for values in addresses_by_hash.values()),
                    )
                    expected = [tx_hash for tx_hash in hashes if target in addresses_by_hash[tx_hash]]
                    actual, meta = self._page(oracle, type_hash, address_hash=target, page=1, page_size=100)
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                actual_hashes = [str(row["transaction_hash"]) for row in actual]
                self.assertGreater(len(expected), 0)
                self.assertEqual(expected, actual_hashes)
                self.assertEqual(len(actual_hashes), len(set(actual_hashes)))
                self.assertEqual(len(expected), int(meta["total"]))

    # TEST-MAP: UDT-TX-RPC-06
    def test_summary_counts_previews_creation_time_and_optional_flags_match_rpc(self) -> None:
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._all(oracle, UDT_FIXTURES[network.name])
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                for row in rows:
                    tx_hash = str(row["transaction_hash"])
                    try:
                        result = oracle.rpc_result("get_transaction", [tx_hash])
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict) or not isinstance(status, dict):
                            raise OracleUnavailable(f"{network.name} RPC transaction {tx_hash} is unavailable")
                        block_hash = status.get("block_hash")
                        if not isinstance(block_hash, str):
                            raise OracleUnavailable(f"{network.name} RPC block for {tx_hash} is unavailable")
                        block = oracle.block_by_hash(block_hash)
                        referenced = oracle.referenced_outputs(transaction)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    header = block.get("header") if isinstance(block, dict) else None
                    inputs = transaction.get("inputs")
                    outputs = transaction.get("outputs")
                    outputs_data = transaction.get("outputs_data")
                    display_inputs = row.get("display_inputs")
                    display_outputs = row.get("display_outputs")
                    self.assertIsInstance(header, dict)
                    self.assertIsInstance(inputs, list)
                    self.assertIsInstance(outputs, list)
                    self.assertIsInstance(outputs_data, list)
                    self.assertIsInstance(display_inputs, list)
                    self.assertIsInstance(display_outputs, list)
                    self.assertEqual("committed", status.get("status"))
                    self.assertEqual(tx_hash, transaction.get("hash"))
                    self.assertEqual(
                        decode_hex_int(status.get("block_number"), "transaction.block_number"),
                        int(row["block_number"]),
                    )
                    self.assertEqual(
                        decode_hex_int(header.get("timestamp"), "transaction.block_timestamp"),
                        int(row["block_timestamp"]),
                    )
                    tx_index = decode_hex_int(status.get("tx_index"), "transaction.tx_index")
                    self.assertEqual(tx_index == 0, row.get("is_cellbase"))
                    self.assertEqual(len(inputs), int(row["display_inputs_count"]))
                    self.assertEqual(len(outputs), int(row["display_outputs_count"]))
                    self.assertEqual(min(10, len(inputs)), len(display_inputs))
                    self.assertEqual(min(10, len(outputs)), len(display_outputs))
                    self.assertIsNone(row.get("income"))
                    self.assertIsInstance(row.get("is_rgb_transaction"), bool)
                    self.assertIsInstance(row.get("is_btc_time_lock"), bool)
                    self.assertTrue(row.get("rgb_txid") is None or isinstance(row.get("rgb_txid"), str))
                    self.assertTrue(
                        row.get("rgb_transfer_step") is None
                        or isinstance(row.get("rgb_transfer_step"), str)
                    )
                    created = datetime.strptime(str(row["created_at"]), "%Y-%m-%d %H:%M:%S %z")
                    delta = created.astimezone(timezone.utc) - epoch
                    created_seconds = delta.days * 86_400 + delta.seconds
                    self.assertRegex(str(row["create_timestamp"]), r"^\d+$")
                    self.assertEqual(created_seconds, int(row["create_timestamp"]) // 1000)

                    for index, (rpc_input, previous, display) in enumerate(
                        zip(inputs[:10], referenced[:10], display_inputs, strict=True)
                    ):
                        output, output_data = previous
                        out_point = rpc_input.get("previous_output")
                        since = display.get("since")
                        self.assertIsInstance(out_point, dict)
                        self.assertIsInstance(since, dict)
                        self.assertEqual(out_point.get("tx_hash"), display.get("generated_tx_hash"))
                        self.assertEqual(
                            decode_hex_int(out_point.get("index"), f"inputs[{index}].index"),
                            int(display["cell_index"]),
                        )
                        self.assertEqual(
                            decode_hex_int(rpc_input.get("since"), f"inputs[{index}].since"),
                            decode_hex_int(since.get("raw"), f"display_inputs[{index}].since"),
                        )
                        self.assertEqual(
                            decode_hex_int(output.get("capacity"), f"inputs[{index}].capacity"),
                            int(Decimal(str(display["capacity"]))),
                        )
                        self.assertEqual(
                            output_occupied_capacity(output, output_data),
                            int(Decimal(str(display["occupied_capacity"]))),
                        )
                        self.assertEqual(output_address(output, network.address_hrp), display.get("address_hash"))
                        self.assertEqual(output.get("type") or "", display.get("type_script"))

                    for index, (output, output_data, display) in enumerate(
                        zip(outputs[:10], outputs_data[:10], display_outputs, strict=True)
                    ):
                        self.assertEqual(tx_hash, display.get("generated_tx_hash"))
                        self.assertEqual(index, int(display["cell_index"]))
                        self.assertEqual(
                            decode_hex_int(output.get("capacity"), f"outputs[{index}].capacity"),
                            int(Decimal(str(display["capacity"]))),
                        )
                        self.assertEqual(
                            output_occupied_capacity(output, output_data),
                            int(Decimal(str(display["occupied_capacity"]))),
                        )
                        self.assertEqual(output_address(output, network.address_hrp), display.get("address_hash"))
                        self.assertEqual(output.get("type") or "", display.get("type_script"))

    # TEST-MAP: UDT-TX-RPC-07
    def test_empty_history_and_page_beyond_last_return_empty_data_with_filtered_meta(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    empty, empty_meta = self._page(oracle, EMPTY_UDT_FIXTURES[network.name])
                    first, first_meta = self._page(oracle, UDT_FIXTURES[network.name])
                    beyond, beyond_meta = self._page(
                        oracle,
                        UDT_FIXTURES[network.name],
                        page=int(first_meta["total_pages"]) + 1,
                    )
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual([], empty)
                self.assertEqual(0, int(empty_meta["total"]))
                self.assertEqual(0, int(empty_meta["total_pages"]))
                self.assertEqual(10, int(empty_meta["page_size"]))
                self.assertGreater(len(first), 0)
                self.assertEqual([], beyond)
                self.assertEqual(int(first_meta["total"]), int(beyond_meta["total"]))
                self.assertEqual(int(first_meta["total_pages"]), int(beyond_meta["total_pages"]))
                self.assertEqual(10, int(beyond_meta["page_size"]))

    # TEST-MAP: UDT-TX-RPC-08
    def test_invalid_hashes_addresses_and_missing_or_unpublished_udts_return_isolated_errors(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                catalog = oracle.explorer_json("/v1/udts", {"page": 1, "page_size": 100})
                data = catalog.get("data") if isinstance(catalog, dict) else None
                if not isinstance(data, list):
                    raise OracleUnavailable(f"{network.name} UDT catalog is unavailable")
                unpublished = next(
                    (
                        row["attributes"].get("type_hash")
                        for row in data
                        if isinstance(row, dict)
                        and isinstance(row.get("attributes"), dict)
                        and row["attributes"].get("published") is False
                    ),
                    None,
                )
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            if not isinstance(unpublished, str):
                raise unittest.SkipTest(f"{network.name} unpublished UDT fixture is unavailable")
            type_hash = UDT_FIXTURES[network.name]
            cases = (
                ("invalid-type", "/v1/udt_transactions/bad", 422, 1025),
                ("invalid-transaction", f"/v1/udt_transactions/{type_hash}?tx_hash=bad", 422, 1005),
                ("invalid-address", f"/v1/udt_transactions/{type_hash}?address_hash=bad", 404, 1010),
                ("missing-udt", "/v1/udt_transactions/" + "0x" + "ff" * 32, 404, 1026),
                ("unpublished-udt", "/v1/udt_transactions/" + quote(unpublished, safe=""), 404, 1026),
            )
            for label, path, expected_status, expected_code in cases:
                with self.subTest(network=network.name, error=label):
                    try:
                        status, raw = _raw_explorer_response(oracle, path)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(expected_status, status)
                    payload = json.loads(raw)
                    self.assertIsInstance(payload, list)
                    self.assertEqual({expected_code}, {int(error["code"]) for error in payload})
                    self.assertFalse(any("data" in error for error in payload))


if __name__ == "__main__":
    unittest.main()
