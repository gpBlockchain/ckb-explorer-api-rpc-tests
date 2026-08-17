from __future__ import annotations

import unittest
from decimal import Decimal
from math import ceil
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import decode_hex_int, output_address, output_occupied_capacity
from ckb_rpc_correctness.http import HttpClientError
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings


COLLECTION_FIXTURES = {
    "mainnet": ("0xba86729380f7e033d722e8fc197159db4dbd4ad6e05e28e297be8230e12a0af7", 0),
    "testnet": ("0x01ee3b9299136f07b659d5e7a9804b4d11d5b47d985abd749f5b353e4528cccf", 1),
}
PREVIEW_FIXTURES = {
    "mainnet": ("0x1604dde852e7f26367e5c1fcf4dc554c03385e1353691c9cd1ea9bc73d5796a8", 1),
    "testnet": ("0x926de250e2771d0dc9bb49d6a9f27877d3ca7c46d473017a92cce5eed111cac6", 0),
}
WIDE_FIXTURES = {
    "mainnet": ("0x4a72d274cd96f060a5184f4cf781f7c8999542843fdd9347fb8443fb58387efc", 0),
    "testnet": ("0x01ee3b9299136f07b659d5e7a9804b4d11d5b47d985abd749f5b353e4528cccf", 0),
}
INCOME_FIXTURES = {
    "mainnet": ("0xad59c28fa123035ecb0eb2092b745398f48f079eb5b346d37e9c05d6b2796e48", 1),
    "testnet": ("0x926de250e2771d0dc9bb49d6a9f27877d3ca7c46d473017a92cce5eed111cac6", 0),
}


class V1TransactionsQueryRpcCorrectnessTests(unittest.TestCase):
    # TEST-MAP: TX-QUERY-RPC-01
    def test_address_query_matches_complete_unique_indexer_transaction_set(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture_hash, output_index = COLLECTION_FIXTURES[network.name]
                try:
                    api_genesis = oracle.detail_attributes(0)
                    rpc_genesis = oracle.block(0)
                    api_tip = oracle.api_tip_height()
                    rpc_tip = oracle.rpc_tip_height()
                    fixture_result = oracle.rpc_result("get_transaction", [fixture_hash])
                    fixture_transaction = (
                        fixture_result.get("transaction") if isinstance(fixture_result, dict) else None
                    )
                    if not isinstance(fixture_transaction, dict):
                        raise OracleUnavailable(
                            f"{network.name} RPC collection fixture {fixture_hash} is unavailable"
                        )
                    outputs = fixture_transaction.get("outputs")
                    if not isinstance(outputs, list) or output_index >= len(outputs):
                        raise OracleUnavailable(
                            f"{network.name} RPC collection fixture {fixture_hash} has no output {output_index}"
                        )
                    lock_script = outputs[output_index].get("lock")
                    if not isinstance(lock_script, dict):
                        raise OracleUnavailable(
                            f"{network.name} RPC collection fixture {fixture_hash} output lock is unavailable"
                        )
                    address = output_address(outputs[output_index], network.address_hrp)

                    indexer_events: list[Mapping[str, Any]] = []
                    cursor: str | None = None
                    for _page in range(100):
                        params: list[object] = [
                            {
                                "script": lock_script,
                                "script_type": "lock",
                                "script_search_mode": "exact",
                            },
                            "desc",
                            "0x64",
                        ]
                        if cursor is not None:
                            params.append(cursor)
                        result = oracle.rpc_result("get_transactions", params)
                        objects = result.get("objects") if isinstance(result, dict) else None
                        last_cursor = result.get("last_cursor") if isinstance(result, dict) else None
                        if not isinstance(objects, list) or not isinstance(last_cursor, str):
                            raise OracleUnavailable(
                                f"{network.name} Indexer transaction page is unavailable for {address}"
                            )
                        for event in objects:
                            if not isinstance(event, dict):
                                raise OracleUnavailable(
                                    f"{network.name} Indexer returned an invalid transaction event"
                                )
                            indexer_events.append(event)
                        if len(objects) < 100:
                            break
                        if last_cursor == cursor:
                            raise OracleUnavailable(f"{network.name} Indexer cursor did not advance")
                        cursor = last_cursor
                    else:
                        raise OracleUnavailable(
                            f"{network.name} Indexer history for {address} exceeded 100 pages"
                        )

                    payload = oracle.client.request_json(
                        network.explorer_api_url + "/v1/transactions/query",
                        method="POST",
                        headers=V1_HEADERS,
                        json_body={"address": address, "page": 1, "page_size": 100},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer address query failed: {error}")
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                genesis_header = rpc_genesis.get("header")
                data = payload.get("data") if isinstance(payload, dict) else None
                meta = payload.get("meta") if isinstance(payload, dict) else None
                self.assertIsInstance(genesis_header, dict)
                self.assertEqual(genesis_header.get("hash"), api_genesis.get("block_hash"))
                self.assertLessEqual(api_tip, rpc_tip)
                self.assertLessEqual(rpc_tip - api_tip, settings.max_lag_blocks)
                self.assertIsInstance(data, list)
                self.assertIsInstance(meta, dict)

                ordered_events = sorted(
                    indexer_events,
                    key=lambda event: (
                        decode_hex_int(event.get("block_number"), "indexer.block_number"),
                        decode_hex_int(event.get("tx_index"), "indexer.tx_index"),
                    ),
                    reverse=True,
                )
                expected_hashes = list(
                    dict.fromkeys(event.get("tx_hash") for event in ordered_events)
                )
                api_hashes: list[object] = []
                for position, item in enumerate(data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(
                        attributes,
                        dict,
                        f"{network.name} address-query row {position} is invalid",
                    )
                    api_hashes.append(attributes.get("transaction_hash"))

                if int(meta["total"]) > 100:
                    raise unittest.SkipTest(
                        f"{network.name} selected address history no longer fits the reviewed complete page"
                    )
                self.assertEqual(len(api_hashes), len(set(api_hashes)))
                self.assertCountEqual(expected_hashes, api_hashes)
                self.assertEqual(len(expected_hashes), int(meta["total"]))

    # TEST-MAP: TX-QUERY-RPC-02
    def test_address_query_order_matches_descending_indexer_block_and_transaction_index(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture_hash, output_index = COLLECTION_FIXTURES[network.name]
                try:
                    fixture_result = oracle.rpc_result("get_transaction", [fixture_hash])
                    fixture_transaction = (
                        fixture_result.get("transaction") if isinstance(fixture_result, dict) else None
                    )
                    if not isinstance(fixture_transaction, dict):
                        raise OracleUnavailable(
                            f"{network.name} RPC collection fixture {fixture_hash} is unavailable"
                        )
                    outputs = fixture_transaction.get("outputs")
                    if not isinstance(outputs, list) or output_index >= len(outputs):
                        raise OracleUnavailable(
                            f"{network.name} RPC collection fixture {fixture_hash} has no output {output_index}"
                        )
                    lock_script = outputs[output_index].get("lock")
                    if not isinstance(lock_script, dict):
                        raise OracleUnavailable(
                            f"{network.name} RPC collection fixture {fixture_hash} output lock is unavailable"
                        )
                    address = output_address(outputs[output_index], network.address_hrp)

                    indexer_events: list[Mapping[str, Any]] = []
                    cursor: str | None = None
                    for _page in range(100):
                        params: list[object] = [
                            {
                                "script": lock_script,
                                "script_type": "lock",
                                "script_search_mode": "exact",
                            },
                            "desc",
                            "0x64",
                        ]
                        if cursor is not None:
                            params.append(cursor)
                        result = oracle.rpc_result("get_transactions", params)
                        objects = result.get("objects") if isinstance(result, dict) else None
                        last_cursor = result.get("last_cursor") if isinstance(result, dict) else None
                        if not isinstance(objects, list) or not isinstance(last_cursor, str):
                            raise OracleUnavailable(
                                f"{network.name} Indexer transaction page is unavailable for {address}"
                            )
                        indexer_events.extend(objects)
                        if len(objects) < 100:
                            break
                        if last_cursor == cursor:
                            raise OracleUnavailable(f"{network.name} Indexer cursor did not advance")
                        cursor = last_cursor
                    else:
                        raise OracleUnavailable(
                            f"{network.name} Indexer history for {address} exceeded 100 pages"
                        )

                    payload = oracle.client.request_json(
                        network.explorer_api_url + "/v1/transactions/query",
                        method="POST",
                        headers=V1_HEADERS,
                        json_body={"address": address, "page": 1, "page_size": 100},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer address query failed: {error}")
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                meta = payload.get("meta") if isinstance(payload, dict) else None
                self.assertIsInstance(data, list)
                self.assertIsInstance(meta, dict)
                if int(meta["total"]) > 100:
                    raise unittest.SkipTest(
                        f"{network.name} selected address history no longer fits the reviewed complete page"
                    )
                api_hashes: list[object] = []
                for position, item in enumerate(data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(
                        attributes,
                        dict,
                        f"{network.name} address-query row {position} is invalid",
                    )
                    api_hashes.append(attributes.get("transaction_hash"))

                ordered_events = sorted(
                    indexer_events,
                    key=lambda event: (
                        decode_hex_int(event.get("block_number"), "indexer.block_number"),
                        decode_hex_int(event.get("tx_index"), "indexer.tx_index"),
                    ),
                    reverse=True,
                )
                expected_hashes = list(
                    dict.fromkeys(event.get("tx_hash") for event in ordered_events)
                )
                self.assertEqual(expected_hashes, api_hashes)
                self.assertEqual(len(expected_hashes), len(set(expected_hashes)))

    # TEST-MAP: TX-QUERY-RPC-03
    def test_default_and_explicit_pages_are_exact_slices_of_indexer_history(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture_hash, output_index = COLLECTION_FIXTURES[network.name]
                try:
                    fixture_result = oracle.rpc_result("get_transaction", [fixture_hash])
                    fixture_transaction = (
                        fixture_result.get("transaction") if isinstance(fixture_result, dict) else None
                    )
                    if not isinstance(fixture_transaction, dict):
                        raise OracleUnavailable(
                            f"{network.name} RPC collection fixture {fixture_hash} is unavailable"
                        )
                    outputs = fixture_transaction.get("outputs")
                    if not isinstance(outputs, list) or output_index >= len(outputs):
                        raise OracleUnavailable(
                            f"{network.name} RPC collection fixture {fixture_hash} has no output {output_index}"
                        )
                    lock_script = outputs[output_index].get("lock")
                    if not isinstance(lock_script, dict):
                        raise OracleUnavailable(
                            f"{network.name} RPC collection fixture {fixture_hash} output lock is unavailable"
                        )
                    address = output_address(outputs[output_index], network.address_hrp)

                    indexer_events: list[Mapping[str, Any]] = []
                    cursor: str | None = None
                    for _page in range(100):
                        params: list[object] = [
                            {
                                "script": lock_script,
                                "script_type": "lock",
                                "script_search_mode": "exact",
                            },
                            "desc",
                            "0x64",
                        ]
                        if cursor is not None:
                            params.append(cursor)
                        result = oracle.rpc_result("get_transactions", params)
                        objects = result.get("objects") if isinstance(result, dict) else None
                        last_cursor = result.get("last_cursor") if isinstance(result, dict) else None
                        if not isinstance(objects, list) or not isinstance(last_cursor, str):
                            raise OracleUnavailable(
                                f"{network.name} Indexer transaction page is unavailable for {address}"
                            )
                        indexer_events.extend(objects)
                        if len(objects) < 100:
                            break
                        if last_cursor == cursor:
                            raise OracleUnavailable(f"{network.name} Indexer cursor did not advance")
                        cursor = last_cursor
                    else:
                        raise OracleUnavailable(
                            f"{network.name} Indexer history for {address} exceeded 100 pages"
                        )

                    default_payload = oracle.client.request_json(
                        network.explorer_api_url + "/v1/transactions/query",
                        method="POST",
                        headers=V1_HEADERS,
                        json_body={"address": address},
                    )
                    first_payload = oracle.client.request_json(
                        network.explorer_api_url + "/v1/transactions/query",
                        method="POST",
                        headers=V1_HEADERS,
                        json_body={"address": address, "page": 1, "page_size": 3},
                    )
                    second_payload = oracle.client.request_json(
                        network.explorer_api_url + "/v1/transactions/query",
                        method="POST",
                        headers=V1_HEADERS,
                        json_body={"address": address, "page": 2, "page_size": 3},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer address pagination failed: {error}")
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                ordered_events = sorted(
                    indexer_events,
                    key=lambda event: (
                        decode_hex_int(event.get("block_number"), "indexer.block_number"),
                        decode_hex_int(event.get("tx_index"), "indexer.tx_index"),
                    ),
                    reverse=True,
                )
                expected_hashes = list(
                    dict.fromkeys(event.get("tx_hash") for event in ordered_events)
                )
                self.assertGreater(len(expected_hashes), 10)

                observed_payloads = (default_payload, first_payload, second_payload)
                observed_hashes: list[list[object]] = []
                observed_meta: list[Mapping[str, Any]] = []
                for payload_index, payload in enumerate(observed_payloads):
                    data = payload.get("data") if isinstance(payload, dict) else None
                    meta = payload.get("meta") if isinstance(payload, dict) else None
                    self.assertIsInstance(data, list)
                    self.assertIsInstance(meta, dict)
                    hashes: list[object] = []
                    for position, item in enumerate(data):
                        attributes = item.get("attributes") if isinstance(item, dict) else None
                        self.assertIsInstance(
                            attributes,
                            dict,
                            f"{network.name} pagination response {payload_index} row {position} is invalid",
                        )
                        hashes.append(attributes.get("transaction_hash"))
                    observed_hashes.append(hashes)
                    observed_meta.append(meta)

                last_page = ceil(len(expected_hashes) / 3)
                try:
                    last_payload = oracle.client.request_json(
                        network.explorer_api_url + "/v1/transactions/query",
                        method="POST",
                        headers=V1_HEADERS,
                        json_body={"address": address, "page": last_page, "page_size": 3},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer last address page failed: {error}")
                last_data = last_payload.get("data") if isinstance(last_payload, dict) else None
                last_meta = last_payload.get("meta") if isinstance(last_payload, dict) else None
                self.assertIsInstance(last_data, list)
                self.assertIsInstance(last_meta, dict)
                last_hashes: list[object] = []
                for position, item in enumerate(last_data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(
                        attributes,
                        dict,
                        f"{network.name} last address page row {position} is invalid",
                    )
                    last_hashes.append(attributes.get("transaction_hash"))

                self.assertEqual(expected_hashes[:10], observed_hashes[0])
                self.assertEqual(expected_hashes[:3], observed_hashes[1])
                self.assertEqual(expected_hashes[3:6], observed_hashes[2])
                self.assertTrue(set(observed_hashes[1]).isdisjoint(observed_hashes[2]))
                self.assertEqual(expected_hashes[(last_page - 1) * 3 : last_page * 3], last_hashes)
                self.assertLess(len(last_hashes), 3)
                for meta in (*observed_meta, last_meta):
                    self.assertEqual(len(expected_hashes), int(meta["total"]))
                self.assertEqual(3, int(observed_meta[1]["page_size"]))
                self.assertEqual(3, int(observed_meta[2]["page_size"]))
                self.assertEqual(3, int(last_meta["page_size"]))
                self.assertEqual(last_page, int(observed_meta[1]["total_pages"]))
                self.assertEqual(last_page, int(observed_meta[2]["total_pages"]))
                self.assertEqual(last_page, int(last_meta["total_pages"]))

    # TEST-MAP: TX-QUERY-RPC-04
    def test_query_row_identity_block_fields_status_and_full_counts_match_rpc(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture_hash, output_index = COLLECTION_FIXTURES[network.name]
                try:
                    fixture_result = oracle.rpc_result("get_transaction", [fixture_hash])
                    fixture_transaction = (
                        fixture_result.get("transaction") if isinstance(fixture_result, dict) else None
                    )
                    if not isinstance(fixture_transaction, dict):
                        raise OracleUnavailable(
                            f"{network.name} RPC collection fixture {fixture_hash} is unavailable"
                        )
                    outputs = fixture_transaction.get("outputs")
                    if not isinstance(outputs, list) or output_index >= len(outputs):
                        raise OracleUnavailable(
                            f"{network.name} RPC collection fixture {fixture_hash} has no output {output_index}"
                        )
                    address = output_address(outputs[output_index], network.address_hrp)
                    payload = oracle.client.request_json(
                        network.explorer_api_url + "/v1/transactions/query",
                        method="POST",
                        headers=V1_HEADERS,
                        json_body={"address": address, "page": 1, "page_size": 10},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer address query failed: {error}")
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(data, list)
                self.assertTrue(data)
                rows: list[Mapping[str, Any]] = []
                for position, item in enumerate(data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(
                        attributes,
                        dict,
                        f"{network.name} address-query row {position} is invalid",
                    )
                    rows.append(attributes)
                hashes = [row.get("transaction_hash") for row in rows]
                self.assertTrue(all(isinstance(tx_hash, str) for tx_hash in hashes))

                try:
                    rpc_results = oracle.rpc_batch_results(
                        [("get_transaction", [tx_hash]) for tx_hash in hashes]
                    )
                    block_hashes: list[str] = []
                    for position, result in enumerate(rpc_results):
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        block_hash = status.get("block_hash") if isinstance(status, dict) else None
                        if not isinstance(block_hash, str):
                            raise OracleUnavailable(
                                f"{network.name} RPC query transaction {position} has no block hash"
                            )
                        block_hashes.append(block_hash)
                    unique_block_hashes = list(dict.fromkeys(block_hashes))
                    blocks = oracle.rpc_batch_results(
                        [("get_block", [block_hash]) for block_hash in unique_block_hashes]
                    )
                    blocks_by_hash = dict(zip(unique_block_hashes, blocks, strict=True))
                    after_payload = oracle.client.request_json(
                        network.explorer_api_url + "/v1/transactions/query",
                        method="POST",
                        headers=V1_HEADERS,
                        json_body={"address": address, "page": 1, "page_size": 10},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer address snapshot refresh failed: {error}")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                after_data = after_payload.get("data") if isinstance(after_payload, dict) else None
                self.assertIsInstance(after_data, list)
                after_hashes: list[object] = []
                for position, item in enumerate(after_data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(
                        attributes,
                        dict,
                        f"{network.name} refreshed address-query row {position} is invalid",
                    )
                    after_hashes.append(attributes.get("transaction_hash"))
                if hashes != after_hashes:
                    raise unittest.SkipTest(f"{network.name} address-query snapshot changed")

                for position, (row, result, block_hash) in enumerate(
                    zip(rows, rpc_results, block_hashes, strict=True)
                ):
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    block = blocks_by_hash[block_hash]
                    header = block.get("header") if isinstance(block, dict) else None
                    self.assertIsInstance(transaction, dict)
                    self.assertIsInstance(status, dict)
                    self.assertIsInstance(header, dict)
                    inputs = transaction.get("inputs")
                    outputs = transaction.get("outputs")
                    self.assertIsInstance(inputs, list)
                    self.assertIsInstance(outputs, list)
                    self.assertEqual(transaction.get("hash"), row.get("transaction_hash"))
                    self.assertEqual("committed", status.get("status"))
                    self.assertGreater(
                        decode_hex_int(status.get("tx_index"), f"transactions[{position}].tx_index"),
                        0,
                    )
                    self.assertIs(row.get("is_cellbase"), False)
                    self.assertEqual(
                        decode_hex_int(status.get("block_number"), f"transactions[{position}].block_number"),
                        int(row["block_number"]),
                    )
                    self.assertEqual(
                        decode_hex_int(header.get("timestamp"), f"blocks[{position}].timestamp"),
                        int(row["block_timestamp"]),
                    )
                    self.assertEqual(len(inputs), int(row["display_inputs_count"]))
                    self.assertEqual(len(outputs), int(row["display_outputs_count"]))

    # TEST-MAP: TX-QUERY-RPC-05
    def test_query_input_previews_match_referenced_rpc_outputs_in_order(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                tx_hash, output_index = PREVIEW_FIXTURES[network.name]
                try:
                    rpc_result = oracle.rpc_result("get_transaction", [tx_hash])
                    transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
                    if not isinstance(transaction, dict):
                        raise OracleUnavailable(
                            f"{network.name} RPC preview fixture {tx_hash} is unavailable"
                        )
                    outputs = transaction.get("outputs")
                    if not isinstance(outputs, list) or output_index >= len(outputs):
                        raise OracleUnavailable(
                            f"{network.name} RPC preview fixture {tx_hash} has no output {output_index}"
                        )
                    address = output_address(outputs[output_index], network.address_hrp)
                    referenced_outputs = oracle.referenced_outputs(transaction)
                    payload = oracle.client.request_json(
                        network.explorer_api_url + "/v1/transactions/query",
                        method="POST",
                        headers=V1_HEADERS,
                        json_body={"address": address, "page": 1, "page_size": 100},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer input-preview query failed: {error}")
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(data, list)
                target: Mapping[str, Any] | None = None
                for item in data:
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    if isinstance(attributes, dict) and attributes.get("transaction_hash") == tx_hash:
                        target = attributes
                        break
                if target is None:
                    raise unittest.SkipTest(
                        f"{network.name} preview fixture {tx_hash} left the first 100 address transactions"
                    )

                inputs = transaction.get("inputs")
                display_inputs = target.get("display_inputs")
                self.assertIsInstance(inputs, list)
                self.assertIsInstance(display_inputs, list)
                self.assertGreater(len(inputs), 1)
                self.assertTrue(any(output.get("type") is None for output, _data in referenced_outputs))
                self.assertTrue(any(output.get("type") is not None for output, _data in referenced_outputs))
                self.assertEqual(min(10, len(inputs)), len(display_inputs))

                for index, (rpc_input, referenced, display) in enumerate(
                    zip(inputs[:10], referenced_outputs[:10], display_inputs, strict=True)
                ):
                    previous_output, output_data = referenced
                    previous = rpc_input.get("previous_output") if isinstance(rpc_input, dict) else None
                    since = display.get("since") if isinstance(display, dict) else None
                    self.assertIsInstance(previous, dict)
                    self.assertIsInstance(since, dict)
                    self.assertEqual(previous.get("tx_hash"), display.get("generated_tx_hash"))
                    self.assertEqual(
                        decode_hex_int(previous.get("index"), f"inputs[{index}].previous_output.index"),
                        int(display["cell_index"]),
                    )
                    self.assertEqual(
                        decode_hex_int(rpc_input.get("since"), f"inputs[{index}].since"),
                        decode_hex_int(since.get("raw"), f"display_inputs[{index}].since.raw"),
                    )
                    self.assertEqual(
                        Decimal(decode_hex_int(previous_output.get("capacity"), "previous_output.capacity")),
                        Decimal(str(display["capacity"])),
                    )
                    self.assertEqual(
                        output_occupied_capacity(previous_output, output_data),
                        int(Decimal(str(display["occupied_capacity"]))),
                    )
                    self.assertEqual(
                        output_address(previous_output, network.address_hrp),
                        display.get("address_hash"),
                    )
                    if previous_output.get("type") is None:
                        self.assertEqual("", display.get("type_script"))
                    else:
                        self.assertEqual(previous_output.get("type"), display.get("type_script"))

    # TEST-MAP: TX-QUERY-RPC-06
    def test_query_output_previews_match_rpc_outputs_in_index_order(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                tx_hash, output_index = PREVIEW_FIXTURES[network.name]
                try:
                    rpc_result = oracle.rpc_result("get_transaction", [tx_hash])
                    transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
                    if not isinstance(transaction, dict):
                        raise OracleUnavailable(
                            f"{network.name} RPC preview fixture {tx_hash} is unavailable"
                        )
                    outputs = transaction.get("outputs")
                    outputs_data = transaction.get("outputs_data")
                    if (
                        not isinstance(outputs, list)
                        or not isinstance(outputs_data, list)
                        or output_index >= len(outputs)
                    ):
                        raise OracleUnavailable(
                            f"{network.name} RPC preview fixture {tx_hash} outputs are unavailable"
                        )
                    address = output_address(outputs[output_index], network.address_hrp)
                    payload = oracle.client.request_json(
                        network.explorer_api_url + "/v1/transactions/query",
                        method="POST",
                        headers=V1_HEADERS,
                        json_body={"address": address, "page": 1, "page_size": 100},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer output-preview query failed: {error}")
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(data, list)
                target: Mapping[str, Any] | None = None
                for item in data:
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    if isinstance(attributes, dict) and attributes.get("transaction_hash") == tx_hash:
                        target = attributes
                        break
                if target is None:
                    raise unittest.SkipTest(
                        f"{network.name} preview fixture {tx_hash} left the first 100 address transactions"
                    )

                display_outputs = target.get("display_outputs")
                self.assertIsInstance(display_outputs, list)
                self.assertGreater(len(outputs), 1)
                self.assertEqual(len(outputs), len(outputs_data))
                self.assertTrue(any(output.get("type") is None for output in outputs))
                self.assertTrue(any(output.get("type") is not None for output in outputs))
                self.assertEqual(min(10, len(outputs)), len(display_outputs))

                for index, (output, output_data, display) in enumerate(
                    zip(outputs[:10], outputs_data[:10], display_outputs, strict=True)
                ):
                    self.assertEqual(tx_hash, display.get("generated_tx_hash"))
                    self.assertEqual(index, int(display["cell_index"]))
                    self.assertEqual(
                        Decimal(decode_hex_int(output.get("capacity"), f"outputs[{index}].capacity")),
                        Decimal(str(display["capacity"])),
                    )
                    self.assertEqual(
                        output_occupied_capacity(output, output_data),
                        int(Decimal(str(display["occupied_capacity"]))),
                    )
                    self.assertEqual(output_address(output, network.address_hrp), display.get("address_hash"))
                    if output.get("type") is None:
                        self.assertEqual("", display.get("type_script"))
                    else:
                        self.assertEqual(output.get("type"), display.get("type_script"))

    # TEST-MAP: TX-QUERY-RPC-07
    def test_query_previews_stop_at_ten_while_counts_keep_full_rpc_lengths(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                tx_hash, output_index = WIDE_FIXTURES[network.name]
                try:
                    rpc_result = oracle.rpc_result("get_transaction", [tx_hash])
                    transaction = rpc_result.get("transaction") if isinstance(rpc_result, dict) else None
                    if not isinstance(transaction, dict):
                        raise OracleUnavailable(f"{network.name} RPC wide fixture {tx_hash} is unavailable")
                    inputs = transaction.get("inputs")
                    outputs = transaction.get("outputs")
                    outputs_data = transaction.get("outputs_data")
                    if (
                        not isinstance(inputs, list)
                        or not isinstance(outputs, list)
                        or not isinstance(outputs_data, list)
                        or output_index >= len(outputs)
                    ):
                        raise OracleUnavailable(
                            f"{network.name} RPC wide fixture {tx_hash} cells are unavailable"
                        )
                    address = output_address(outputs[output_index], network.address_hrp)
                    referenced_outputs = oracle.referenced_outputs(transaction)
                    payload = oracle.client.request_json(
                        network.explorer_api_url + "/v1/transactions/query",
                        method="POST",
                        headers=V1_HEADERS,
                        json_body={"address": address, "page": 1, "page_size": 100},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer wide-preview query failed: {error}")
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                self.assertIsInstance(data, list)
                target: Mapping[str, Any] | None = None
                for item in data:
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    if isinstance(attributes, dict) and attributes.get("transaction_hash") == tx_hash:
                        target = attributes
                        break
                if target is None:
                    raise unittest.SkipTest(
                        f"{network.name} wide fixture {tx_hash} left the first 100 address transactions"
                    )

                display_inputs = target.get("display_inputs")
                display_outputs = target.get("display_outputs")
                self.assertIsInstance(display_inputs, list)
                self.assertIsInstance(display_outputs, list)
                self.assertGreater(max(len(inputs), len(outputs)), 10)
                self.assertEqual(len(inputs), int(target["display_inputs_count"]))
                self.assertEqual(len(outputs), int(target["display_outputs_count"]))
                self.assertEqual(min(10, len(inputs)), len(display_inputs))
                self.assertEqual(min(10, len(outputs)), len(display_outputs))

                if len(inputs) > 10:
                    tenth_input = inputs[9]
                    tenth_previous = tenth_input.get("previous_output")
                    tenth_display = display_inputs[9]
                    self.assertIsInstance(tenth_previous, dict)
                    self.assertEqual(tenth_previous.get("tx_hash"), tenth_display.get("generated_tx_hash"))
                    self.assertEqual(
                        decode_hex_int(tenth_previous.get("index"), "inputs[9].previous_output.index"),
                        int(tenth_display["cell_index"]),
                    )
                    self.assertEqual(
                        output_address(referenced_outputs[9][0], network.address_hrp),
                        tenth_display.get("address_hash"),
                    )
                if len(outputs) > 10:
                    tenth_display = display_outputs[9]
                    self.assertEqual(tx_hash, tenth_display.get("generated_tx_hash"))
                    self.assertEqual(9, int(tenth_display["cell_index"]))
                    self.assertEqual(
                        output_address(outputs[9], network.address_hrp),
                        tenth_display.get("address_hash"),
                    )

    # TEST-MAP: TX-QUERY-RPC-08
    def test_income_equals_query_address_output_capacity_minus_input_capacity(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                fixture_hash, output_index = INCOME_FIXTURES[network.name]
                try:
                    fixture_result = oracle.rpc_result("get_transaction", [fixture_hash])
                    fixture_transaction = (
                        fixture_result.get("transaction") if isinstance(fixture_result, dict) else None
                    )
                    if not isinstance(fixture_transaction, dict):
                        raise OracleUnavailable(
                            f"{network.name} RPC income fixture {fixture_hash} is unavailable"
                        )
                    outputs = fixture_transaction.get("outputs")
                    if not isinstance(outputs, list) or output_index >= len(outputs):
                        raise OracleUnavailable(
                            f"{network.name} RPC income fixture {fixture_hash} has no output {output_index}"
                        )
                    query_lock = outputs[output_index].get("lock")
                    if not isinstance(query_lock, dict):
                        raise OracleUnavailable(
                            f"{network.name} RPC income fixture {fixture_hash} lock is unavailable"
                        )
                    address = output_address(outputs[output_index], network.address_hrp)
                    payload = oracle.client.request_json(
                        network.explorer_api_url + "/v1/transactions/query",
                        method="POST",
                        headers=V1_HEADERS,
                        json_body={"address": address, "page": 1, "page_size": 100},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer income query failed: {error}")
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                data = payload.get("data") if isinstance(payload, dict) else None
                meta = payload.get("meta") if isinstance(payload, dict) else None
                self.assertIsInstance(data, list)
                self.assertIsInstance(meta, dict)
                if int(meta["total"]) > 100:
                    raise unittest.SkipTest(
                        f"{network.name} selected income history no longer fits one complete page"
                    )
                self.assertEqual(int(meta["total"]), len(data))
                rows: list[Mapping[str, Any]] = []
                hashes: list[str] = []
                for position, item in enumerate(data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(
                        attributes,
                        dict,
                        f"{network.name} income-query row {position} is invalid",
                    )
                    tx_hash = attributes.get("transaction_hash")
                    self.assertIsInstance(tx_hash, str)
                    rows.append(attributes)
                    hashes.append(tx_hash)

                try:
                    rpc_results = oracle.rpc_batch_results(
                        [("get_transaction", [tx_hash]) for tx_hash in hashes]
                    )
                    transactions_by_hash: dict[str, Mapping[str, Any]] = {}
                    previous_hashes: list[str] = []
                    for tx_hash, result in zip(hashes, rpc_results, strict=True):
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict) or not isinstance(status, dict):
                            raise OracleUnavailable(
                                f"{network.name} RPC income transaction {tx_hash} is unavailable"
                            )
                        if status.get("status") != "committed":
                            raise OracleUnavailable(
                                f"{network.name} RPC income transaction {tx_hash} is not committed"
                            )
                        transactions_by_hash[tx_hash] = transaction
                        inputs = transaction.get("inputs")
                        if not isinstance(inputs, list):
                            raise OracleUnavailable(
                                f"{network.name} RPC income transaction {tx_hash} inputs are invalid"
                            )
                        for item in inputs:
                            previous = item.get("previous_output") if isinstance(item, dict) else None
                            previous_hash = previous.get("tx_hash") if isinstance(previous, dict) else None
                            if not isinstance(previous_hash, str):
                                raise OracleUnavailable(
                                    f"{network.name} RPC income transaction {tx_hash} has an invalid input"
                                )
                            if previous_hash not in transactions_by_hash and previous_hash not in previous_hashes:
                                previous_hashes.append(previous_hash)
                    missing_previous = [
                        tx_hash for tx_hash in previous_hashes if tx_hash not in transactions_by_hash
                    ]
                    previous_results = oracle.rpc_batch_results(
                        [("get_transaction", [tx_hash]) for tx_hash in missing_previous]
                    )
                    for tx_hash, result in zip(missing_previous, previous_results, strict=True):
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict):
                            raise OracleUnavailable(
                                f"{network.name} RPC previous income transaction {tx_hash} is unavailable"
                            )
                        transactions_by_hash[tx_hash] = transaction
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                signs: set[int] = set()
                for position, (row, tx_hash) in enumerate(zip(rows, hashes, strict=True)):
                    transaction = transactions_by_hash[tx_hash]
                    inputs = transaction.get("inputs")
                    outputs = transaction.get("outputs")
                    self.assertIsInstance(inputs, list)
                    self.assertIsInstance(outputs, list)
                    output_capacity = 0
                    for output in outputs:
                        self.assertIsInstance(output, dict)
                        if output.get("lock") == query_lock:
                            output_capacity += decode_hex_int(
                                output.get("capacity"),
                                f"transactions[{position}].output.capacity",
                            )
                    input_capacity = 0
                    for input_position, item in enumerate(inputs):
                        previous = item.get("previous_output") if isinstance(item, dict) else None
                        self.assertIsInstance(previous, dict)
                        previous_hash = previous.get("tx_hash")
                        previous_index = decode_hex_int(
                            previous.get("index"),
                            f"transactions[{position}].inputs[{input_position}].index",
                        )
                        previous_transaction = transactions_by_hash[previous_hash]
                        previous_outputs = previous_transaction.get("outputs")
                        self.assertIsInstance(previous_outputs, list)
                        self.assertLess(previous_index, len(previous_outputs))
                        previous_output = previous_outputs[previous_index]
                        self.assertIsInstance(previous_output, dict)
                        if previous_output.get("lock") == query_lock:
                            input_capacity += decode_hex_int(
                                previous_output.get("capacity"),
                                f"transactions[{position}].inputs[{input_position}].capacity",
                            )

                    expected_income = output_capacity - input_capacity
                    self.assertEqual(Decimal(expected_income), Decimal(str(row["income"])))
                    signs.add(0 if expected_income == 0 else (1 if expected_income > 0 else -1))

                self.assertEqual({-1, 0, 1}, signs)

    # TEST-MAP: TX-QUERY-RPC-09
    def test_omitted_address_returns_recent_normal_page_with_null_income(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    baseline = oracle.explorer_json("/v1/transactions")
                    payload = oracle.client.request_json(
                        network.explorer_api_url + "/v1/transactions/query",
                        method="POST",
                        headers=V1_HEADERS,
                        json_body={},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(
                        f"{network.name} omitted-address query must return the existing global branch, not {error}"
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                baseline_data = baseline.get("data") if isinstance(baseline, dict) else None
                data = payload.get("data") if isinstance(payload, dict) else None
                meta = payload.get("meta") if isinstance(payload, dict) else None
                self.assertIsInstance(baseline_data, list)
                self.assertIsInstance(data, list)
                self.assertIsInstance(meta, dict)

                expected_hashes: list[object] = []
                for position, item in enumerate(baseline_data[:10]):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(
                        attributes,
                        dict,
                        f"{network.name} baseline transaction row {position} is invalid",
                    )
                    expected_hashes.append(attributes.get("transaction_hash"))

                observed_hashes: list[object] = []
                for position, item in enumerate(data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(
                        attributes,
                        dict,
                        f"{network.name} omitted-address row {position} is invalid",
                    )
                    observed_hashes.append(attributes.get("transaction_hash"))
                    self.assertIs(attributes.get("is_cellbase"), False)
                    self.assertIsNone(attributes.get("income"))

                self.assertEqual(expected_hashes, observed_hashes)
                self.assertEqual(10, int(meta["page_size"]))


if __name__ == "__main__":
    unittest.main()
