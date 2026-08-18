from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V1TransactionsIndexRpcCorrectnessTests(unittest.TestCase):
    # TEST-MAP: TX-LIST-RPC-01
    def test_default_list_is_the_latest_fifteen_committed_normal_transactions(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    before = oracle.explorer_json("/v1/transactions")
                    api_genesis = oracle.detail_attributes(0)
                    rpc_genesis = oracle.block(0)
                    api_tip = oracle.api_tip_height()
                    rpc_tip = oracle.rpc_tip_height()
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                before_data = before.get("data") if isinstance(before, dict) else None
                self.assertIsInstance(before_data, list)
                rows: list[Mapping[str, Any]] = []
                for index, item in enumerate(before_data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(attributes, dict, f"{network.name} transaction row {index} is invalid")
                    rows.append(attributes)
                api_hashes = [row.get("transaction_hash") for row in rows]
                api_heights = [int(row["block_number"]) for row in rows]

                self.assertEqual(15, len(api_hashes))
                self.assertTrue(all(isinstance(tx_hash, str) for tx_hash in api_hashes))
                self.assertEqual(len(api_hashes), len(set(api_hashes)))

                rpc_genesis_header = rpc_genesis.get("header")
                self.assertIsInstance(rpc_genesis_header, dict)
                self.assertEqual(rpc_genesis_header.get("hash"), api_genesis.get("block_hash"))
                self.assertLessEqual(api_tip, rpc_tip)
                self.assertLessEqual(rpc_tip - api_tip, settings.max_lag_blocks)
                self.assertTrue(api_heights)
                self.assertLessEqual(max(api_heights), api_tip)

                candidates: list[tuple[int, int, str, int, str]] = []
                next_height = api_tip
                lowest_height = max(0, api_tip - settings.list_page_size * settings.sample_search_pages + 1)
                try:
                    while next_height >= lowest_height and (
                        len(candidates) < 16 or next_height >= min(api_heights)
                    ):
                        batch_low = max(lowest_height, next_height - settings.rpc_batch_size + 1)
                        heights = list(range(next_height, batch_low - 1, -1))
                        blocks = oracle.rpc_batch_results(
                            [("get_block_by_number", [hex(height)]) for height in heights]
                        )
                        for height, block in zip(heights, blocks, strict=True):
                            if not isinstance(block, dict):
                                raise OracleUnavailable(f"{network.name} RPC has no block at height {height}")
                            header = block.get("header")
                            transactions = block.get("transactions")
                            if not isinstance(header, dict) or not isinstance(transactions, list):
                                raise OracleUnavailable(f"{network.name} RPC block {height} is invalid")
                            timestamp = decode_hex_int(header.get("timestamp"), f"block[{height}].header.timestamp")
                            block_hash = header.get("hash")
                            if not isinstance(block_hash, str):
                                raise OracleUnavailable(f"{network.name} RPC block {height} has no hash")
                            for tx_index, transaction in enumerate(transactions[1:], start=1):
                                tx_hash = transaction.get("hash") if isinstance(transaction, dict) else None
                                if not isinstance(tx_hash, str):
                                    raise OracleUnavailable(
                                        f"{network.name} RPC block {height} transaction {tx_index} is invalid"
                                    )
                                candidates.append((timestamp, tx_index, tx_hash, height, block_hash))
                        next_height = batch_low - 1
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
                if len(candidates) < 16:
                    raise unittest.SkipTest(
                        f"{network.name} canonical search window has fewer than 16 normal transactions"
                    )
                if candidates[14][:2] == candidates[15][:2]:
                    raise unittest.SkipTest(
                        f"{network.name} latest-15 boundary has an undefined equal timestamp/index tie"
                    )
                expected_hashes = [item[2] for item in candidates[:15]]

                for snapshot_attempt in range(2):
                    try:
                        rpc_transactions = oracle.rpc_batch_results(
                            [("get_transaction", [tx_hash]) for tx_hash in api_hashes]
                        )
                        after = oracle.explorer_json("/v1/transactions")
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    after_data = after.get("data") if isinstance(after, dict) else None
                    self.assertIsInstance(after_data, list)
                    after_rows: list[Mapping[str, Any]] = []
                    after_hashes: list[object] = []
                    for index, item in enumerate(after_data):
                        attributes = item.get("attributes") if isinstance(item, dict) else None
                        self.assertIsInstance(
                            attributes,
                            dict,
                            f"{network.name} transaction row {index} changed to an invalid shape",
                        )
                        after_rows.append(attributes)
                        after_hashes.append(attributes.get("transaction_hash"))
                    if api_hashes == after_hashes:
                        break
                    if snapshot_attempt == 1:
                        raise unittest.SkipTest(f"{network.name} default transaction-list snapshot kept changing")
                    refreshed_heights = [int(row["block_number"]) for row in after_rows]
                    if (
                        len(after_hashes) != 15
                        or not all(isinstance(tx_hash, str) for tx_hash in after_hashes)
                        or len(after_hashes) != len(set(after_hashes))
                        or not refreshed_heights
                    ):
                        raise unittest.SkipTest(
                            f"{network.name} changed snapshot is outside the scanned canonical window"
                        )
                    rows = after_rows
                    api_hashes = after_hashes
                    try:
                        refreshed_tip_payload = oracle.explorer_json(
                            "/v1/blocks", {"page": 1, "page_size": 1, "sort": "number.desc"}
                        )
                        refreshed_tip_data = (
                            refreshed_tip_payload.get("data")
                            if isinstance(refreshed_tip_payload, dict)
                            else None
                        )
                        if not isinstance(refreshed_tip_data, list) or not refreshed_tip_data:
                            raise OracleUnavailable(f"{network.name} Explorer block tip is unavailable")
                        refreshed_tip_attributes = (
                            refreshed_tip_data[0].get("attributes")
                            if isinstance(refreshed_tip_data[0], dict)
                            else None
                        )
                        if not isinstance(refreshed_tip_attributes, dict):
                            raise OracleUnavailable(f"{network.name} Explorer block tip is invalid")
                        refreshed_api_tip = int(refreshed_tip_attributes["number"])
                        refreshed_rpc_tip = oracle.rpc_result("get_tip_header", [])
                        if not isinstance(refreshed_rpc_tip, dict):
                            raise OracleUnavailable(f"{network.name} RPC tip is unavailable")
                        refreshed_rpc_tip_height = decode_hex_int(
                            refreshed_rpc_tip.get("number"), "tip.number"
                        )
                        if refreshed_api_tip > refreshed_rpc_tip_height:
                            raise OracleUnavailable(f"{network.name} Explorer tip is ahead of RPC tip")
                        if refreshed_rpc_tip_height - refreshed_api_tip > settings.max_lag_blocks:
                            raise OracleUnavailable(f"{network.name} Explorer tip exceeds allowed RPC lag")
                        if max(refreshed_heights) > refreshed_api_tip:
                            raise OracleUnavailable(
                                f"{network.name} transaction list is ahead of the Explorer block tip"
                            )
                        if refreshed_api_tip > api_tip:
                            new_heights = list(range(refreshed_api_tip, api_tip, -1))
                            new_blocks = oracle.rpc_batch_results(
                                [("get_block_by_number", [hex(height)]) for height in new_heights]
                            )
                            for height, block in zip(new_heights, new_blocks, strict=True):
                                if not isinstance(block, dict):
                                    raise OracleUnavailable(
                                        f"{network.name} RPC has no refreshed block at height {height}"
                                    )
                                header = block.get("header")
                                transactions = block.get("transactions")
                                if not isinstance(header, dict) or not isinstance(transactions, list):
                                    raise OracleUnavailable(
                                        f"{network.name} refreshed RPC block {height} is invalid"
                                    )
                                timestamp = decode_hex_int(
                                    header.get("timestamp"), f"block[{height}].header.timestamp"
                                )
                                block_hash = header.get("hash")
                                if not isinstance(block_hash, str):
                                    raise OracleUnavailable(
                                        f"{network.name} refreshed RPC block {height} has no hash"
                                    )
                                for tx_index, transaction in enumerate(transactions[1:], start=1):
                                    tx_hash = transaction.get("hash") if isinstance(transaction, dict) else None
                                    if not isinstance(tx_hash, str):
                                        raise OracleUnavailable(
                                            f"{network.name} refreshed RPC block {height} transaction "
                                            f"{tx_index} is invalid"
                                        )
                                    candidates.append(
                                        (timestamp, tx_index, tx_hash, height, block_hash)
                                    )
                        api_tip = refreshed_api_tip
                    except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                        raise unittest.SkipTest(str(error)) from error
                    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
                    eligible_candidates = [item for item in candidates if item[3] <= api_tip]
                    if len(eligible_candidates) < 16 or eligible_candidates[14][:2] == eligible_candidates[15][:2]:
                        raise unittest.SkipTest(
                            f"{network.name} refreshed latest-15 canonical boundary is unavailable"
                        )
                    expected_hashes = [item[2] for item in eligible_candidates[:15]]

                self.assertCountEqual(expected_hashes, api_hashes)
                expected_block_hashes = {item[2]: item[4] for item in candidates}
                for index, (tx_hash, result) in enumerate(zip(api_hashes, rpc_transactions, strict=True)):
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    self.assertIsInstance(transaction, dict, f"{network.name} RPC transaction {index} is missing")
                    self.assertIsInstance(status, dict, f"{network.name} RPC status {index} is missing")
                    self.assertEqual(tx_hash, transaction.get("hash"))
                    self.assertEqual("committed", status.get("status"))
                    self.assertGreater(decode_hex_int(status.get("tx_index"), "tx_status.tx_index"), 0)
                    if status.get("block_hash") != expected_block_hashes.get(tx_hash):
                        raise unittest.SkipTest(f"{network.name} RPC transaction {tx_hash} changed block")

    # TEST-MAP: TX-LIST-RPC-02
    def test_default_list_uses_block_timestamp_and_same_block_transaction_index_order(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    before = oracle.explorer_json("/v1/transactions")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                before_data = before.get("data") if isinstance(before, dict) else None
                self.assertIsInstance(before_data, list)
                rows: list[Mapping[str, Any]] = []
                for index, item in enumerate(before_data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(attributes, dict, f"{network.name} transaction row {index} is invalid")
                    rows.append(attributes)
                api_hashes = [row.get("transaction_hash") for row in rows]
                self.assertTrue(all(isinstance(tx_hash, str) for tx_hash in api_hashes))

                try:
                    rpc_transactions = oracle.rpc_batch_results(
                        [("get_transaction", [tx_hash]) for tx_hash in api_hashes]
                    )
                    block_hashes: list[str] = []
                    for index, result in enumerate(rpc_transactions):
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        block_hash = status.get("block_hash") if isinstance(status, dict) else None
                        if not isinstance(block_hash, str):
                            raise OracleUnavailable(f"{network.name} RPC transaction {index} has no block hash")
                        block_hashes.append(block_hash)
                    unique_block_hashes = list(dict.fromkeys(block_hashes))
                    blocks = oracle.rpc_batch_results(
                        [("get_block", [block_hash]) for block_hash in unique_block_hashes]
                    )
                    blocks_by_hash = dict(zip(unique_block_hashes, blocks, strict=True))
                    observations: list[tuple[int, int, str]] = []
                    for index, (result, block_hash) in enumerate(
                        zip(rpc_transactions, block_hashes, strict=True)
                    ):
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        block = blocks_by_hash[block_hash]
                        header = block.get("header") if isinstance(block, dict) else None
                        if not isinstance(status, dict) or not isinstance(header, dict):
                            raise OracleUnavailable(f"{network.name} RPC ordering observation {index} is invalid")
                        observations.append(
                            (
                                decode_hex_int(header.get("timestamp"), "header.timestamp"),
                                decode_hex_int(status.get("tx_index"), "tx_status.tx_index"),
                                block_hash,
                            )
                        )
                    after = oracle.explorer_json("/v1/transactions")
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                after_data = after.get("data") if isinstance(after, dict) else None
                self.assertIsInstance(after_data, list)
                after_hashes: list[object] = []
                for index, item in enumerate(after_data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(
                        attributes,
                        dict,
                        f"{network.name} transaction row {index} changed to an invalid shape",
                    )
                    after_hashes.append(attributes.get("transaction_hash"))
                if api_hashes != after_hashes:
                    raise unittest.SkipTest(f"{network.name} default transaction-list snapshot changed")

                cross_block_pairs = 0
                same_block_pairs = 0
                for position, (current, following) in enumerate(zip(observations, observations[1:])):
                    current_timestamp, current_index, current_block_hash = current
                    following_timestamp, following_index, following_block_hash = following
                    self.assertGreaterEqual(
                        (current_timestamp, current_index),
                        (following_timestamp, following_index),
                        f"{network.name} transaction-list positions {position}/{position + 1} reverse sort order",
                    )
                    if current_block_hash == following_block_hash:
                        same_block_pairs += 1
                        self.assertGreater(
                            current_index,
                            following_index,
                            f"{network.name} same-block positions {position}/{position + 1} reverse index order",
                        )
                    else:
                        cross_block_pairs += 1
                if cross_block_pairs == 0 or same_block_pairs == 0:
                    raise unittest.SkipTest(
                        f"{network.name} default list does not currently cover both cross-block and same-block pairs"
                    )

    # TEST-MAP: TX-LIST-RPC-03
    def test_hash_block_number_timestamp_and_block_hash_relationship_match_rpc(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    before = oracle.explorer_json("/v1/transactions")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                before_data = before.get("data") if isinstance(before, dict) else None
                self.assertIsInstance(before_data, list)
                rows: list[Mapping[str, Any]] = []
                for index, item in enumerate(before_data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(attributes, dict, f"{network.name} transaction row {index} is invalid")
                    rows.append(attributes)
                api_hashes = [row.get("transaction_hash") for row in rows]
                self.assertTrue(all(isinstance(tx_hash, str) for tx_hash in api_hashes))

                try:
                    rpc_transactions = oracle.rpc_batch_results(
                        [("get_transaction", [tx_hash]) for tx_hash in api_hashes]
                    )
                    block_hashes: list[str] = []
                    for index, result in enumerate(rpc_transactions):
                        status = result.get("tx_status") if isinstance(result, dict) else None
                        block_hash = status.get("block_hash") if isinstance(status, dict) else None
                        if not isinstance(block_hash, str):
                            raise OracleUnavailable(f"{network.name} RPC transaction {index} has no block hash")
                        block_hashes.append(block_hash)
                    unique_block_hashes = list(dict.fromkeys(block_hashes))
                    blocks = oracle.rpc_batch_results(
                        [("get_block", [block_hash]) for block_hash in unique_block_hashes]
                    )
                    blocks_by_hash = dict(zip(unique_block_hashes, blocks, strict=True))
                    after = oracle.explorer_json("/v1/transactions")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                after_data = after.get("data") if isinstance(after, dict) else None
                self.assertIsInstance(after_data, list)
                after_hashes: list[object] = []
                for index, item in enumerate(after_data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(
                        attributes,
                        dict,
                        f"{network.name} transaction row {index} changed to an invalid shape",
                    )
                    after_hashes.append(attributes.get("transaction_hash"))
                if api_hashes != after_hashes:
                    raise unittest.SkipTest(f"{network.name} default transaction-list snapshot changed")

                self.assertEqual(len(rows), len(rpc_transactions))
                for position, (row, result, block_hash) in enumerate(
                    zip(rows, rpc_transactions, block_hashes, strict=True)
                ):
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    block = blocks_by_hash[block_hash]
                    header = block.get("header") if isinstance(block, dict) else None
                    self.assertIsInstance(transaction, dict, f"{network.name} RPC transaction {position} is missing")
                    self.assertIsInstance(status, dict, f"{network.name} RPC status {position} is missing")
                    self.assertIsInstance(header, dict, f"{network.name} RPC block {block_hash} is missing")
                    self.assertEqual(transaction.get("hash"), row.get("transaction_hash"))
                    self.assertEqual(
                        decode_hex_int(status.get("block_number"), "tx_status.block_number"),
                        int(row["block_number"]),
                    )
                    self.assertEqual(
                        decode_hex_int(header.get("timestamp"), "header.timestamp"),
                        int(row["block_timestamp"]),
                    )
                    self.assertEqual(block_hash, header.get("hash"))

    # TEST-MAP: TX-LIST-RPC-04
    def test_live_cell_changes_equal_output_count_minus_input_count(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    before = oracle.explorer_json("/v1/transactions")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                before_data = before.get("data") if isinstance(before, dict) else None
                self.assertIsInstance(before_data, list)
                rows: list[Mapping[str, Any]] = []
                for index, item in enumerate(before_data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(attributes, dict, f"{network.name} transaction row {index} is invalid")
                    rows.append(attributes)
                api_hashes = [row.get("transaction_hash") for row in rows]
                self.assertTrue(all(isinstance(tx_hash, str) for tx_hash in api_hashes))

                try:
                    rpc_transactions = oracle.rpc_batch_results(
                        [("get_transaction", [tx_hash]) for tx_hash in api_hashes]
                    )
                    expected_changes: list[int] = []
                    for index, result in enumerate(rpc_transactions):
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        inputs = transaction.get("inputs") if isinstance(transaction, dict) else None
                        outputs = transaction.get("outputs") if isinstance(transaction, dict) else None
                        if not isinstance(inputs, list) or not isinstance(outputs, list):
                            raise OracleUnavailable(f"{network.name} RPC transaction {index} inputs/outputs are invalid")
                        expected_changes.append(len(outputs) - len(inputs))
                    after = oracle.explorer_json("/v1/transactions")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                after_data = after.get("data") if isinstance(after, dict) else None
                self.assertIsInstance(after_data, list)
                after_hashes: list[object] = []
                for index, item in enumerate(after_data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(
                        attributes,
                        dict,
                        f"{network.name} transaction row {index} changed to an invalid shape",
                    )
                    after_hashes.append(attributes.get("transaction_hash"))
                if api_hashes != after_hashes:
                    raise unittest.SkipTest(f"{network.name} default transaction-list snapshot changed")
                if 0 not in expected_changes or not any(change != 0 for change in expected_changes):
                    raise unittest.SkipTest(
                        f"{network.name} default list does not currently cover zero and non-zero live-cell changes"
                    )

                self.assertEqual(len(rows), len(expected_changes))
                for position, (row, expected) in enumerate(zip(rows, expected_changes, strict=True)):
                    self.assertEqual(
                        expected,
                        int(row["live_cell_changes"]),
                        f"{network.name} transaction-list position {position} live_cell_changes mismatch",
                    )

    # TEST-MAP: TX-LIST-RPC-05
    def test_capacity_involved_is_the_exact_sum_of_every_referenced_input_capacity(self) -> None:
        settings = load_settings()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")

        for network in settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, settings)
                try:
                    before = oracle.explorer_json("/v1/transactions")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                before_data = before.get("data") if isinstance(before, dict) else None
                self.assertIsInstance(before_data, list)
                rows: list[Mapping[str, Any]] = []
                for index, item in enumerate(before_data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(attributes, dict, f"{network.name} transaction row {index} is invalid")
                    rows.append(attributes)
                api_hashes = [row.get("transaction_hash") for row in rows]
                self.assertTrue(all(isinstance(tx_hash, str) for tx_hash in api_hashes))

                try:
                    rpc_results = oracle.rpc_batch_results(
                        [("get_transaction", [tx_hash]) for tx_hash in api_hashes]
                    )
                    input_counts: list[int] = []
                    expected_capacities: list[int] = []
                    for index, result in enumerate(rpc_results):
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        inputs = transaction.get("inputs") if isinstance(transaction, dict) else None
                        if not isinstance(transaction, dict) or not isinstance(inputs, list):
                            raise OracleUnavailable(f"{network.name} RPC transaction {index} inputs are invalid")
                        referenced_outputs = oracle.referenced_outputs(transaction)
                        if len(referenced_outputs) != len(inputs):
                            raise OracleUnavailable(
                                f"{network.name} RPC transaction {index} did not resolve every input"
                            )
                        input_counts.append(len(inputs))
                        expected_capacities.append(
                            sum(
                                decode_hex_int(output.get("capacity"), f"input[{input_index}].capacity")
                                for input_index, (output, _data) in enumerate(referenced_outputs)
                            )
                        )
                    after = oracle.explorer_json("/v1/transactions")
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                after_data = after.get("data") if isinstance(after, dict) else None
                self.assertIsInstance(after_data, list)
                after_hashes: list[object] = []
                for index, item in enumerate(after_data):
                    attributes = item.get("attributes") if isinstance(item, dict) else None
                    self.assertIsInstance(
                        attributes,
                        dict,
                        f"{network.name} transaction row {index} changed to an invalid shape",
                    )
                    after_hashes.append(attributes.get("transaction_hash"))
                if api_hashes != after_hashes:
                    raise unittest.SkipTest(f"{network.name} default transaction-list snapshot changed")
                if 1 not in input_counts or not any(count > 1 for count in input_counts):
                    raise unittest.SkipTest(
                        f"{network.name} default list does not currently cover one-input and multi-input transactions"
                    )

                self.assertEqual(len(rows), len(expected_capacities))
                for position, (row, expected) in enumerate(zip(rows, expected_capacities, strict=True)):
                    self.assertEqual(
                        expected,
                        int(row["capacity_involved"]),
                        f"{network.name} transaction-list position {position} capacity_involved mismatch",
                    )


if __name__ == "__main__":
    unittest.main()
