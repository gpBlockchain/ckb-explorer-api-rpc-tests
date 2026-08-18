from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import decode_hex_int, output_address, output_occupied_capacity
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


def _addresses_by_transaction(
    oracle: NetworkOracle,
    block: Mapping[str, Any],
) -> list[tuple[str, set[str]]]:
    transactions = block.get("transactions")
    if not isinstance(transactions, list):
        raise OracleUnavailable(f"{oracle.network.name} RPC block transactions are invalid")
    result: list[tuple[str, set[str]]] = []
    for tx_index, transaction in enumerate(transactions):
        if not isinstance(transaction, dict) or not isinstance(transaction.get("hash"), str):
            raise OracleUnavailable(f"{oracle.network.name} RPC transaction {tx_index} is invalid")
        outputs = transaction.get("outputs")
        if not isinstance(outputs, list) or not all(isinstance(output, dict) for output in outputs):
            raise OracleUnavailable(f"{oracle.network.name} RPC transaction {tx_index} outputs are invalid")
        addresses = {output_address(output, oracle.network.address_hrp) for output in outputs}
        if tx_index > 0:
            addresses.update(
                output_address(previous_output, oracle.network.address_hrp)
                for previous_output, _data in oracle.referenced_outputs(transaction)
            )
        result.append((transaction["hash"], addresses))
    return result


class V1BlockTransactionsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.oracles = tuple(NetworkOracle(network, cls.settings) for network in cls.settings.networks)

    # TEST-MAP: BLOCK-TXS-RPC-01
    def test_transaction_hashes_total_and_order_match_rpc(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    cellbase_only = oracle.cellbase_only_sample()
                    with_transactions = oracle.transaction_sample()
                    observations = []
                    for sample in (cellbase_only, with_transactions):
                        header = sample.rpc_block.get("header")
                        block_hash = header.get("hash") if isinstance(header, dict) else None
                        transactions = sample.rpc_block.get("transactions")
                        if not isinstance(block_hash, str) or not isinstance(transactions, list):
                            raise OracleUnavailable(f"{sample.network} height {sample.height} RPC block is invalid")
                        if len(transactions) > self.settings.list_page_size:
                            raise OracleUnavailable(f"{sample.network} height {sample.height} exceeds one API page")
                        rows, meta = oracle.block_transaction_page(block_hash)
                        oracle.ensure_stable(sample)
                        observations.append((sample, transactions, rows, meta))
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                for sample, transactions, rows, meta in observations:
                    expected_hashes = [transaction.get("hash") for transaction in transactions]
                    actual_hashes = [row.get("transaction_hash") for row in rows]
                    self.assertEqual(
                        expected_hashes,
                        actual_hashes,
                        f"{sample.network} height {sample.height} transaction membership or order mismatch",
                    )
                    self.assertEqual(len(transactions), int(meta["total"]))
                    self.assertEqual(len(actual_hashes), len(set(actual_hashes)))

    # TEST-MAP: BLOCK-TXS-RPC-02
    def test_every_transaction_uses_rpc_block_number_and_timestamp(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    sample = oracle.transaction_sample()
                    header = sample.rpc_block.get("header")
                    if not isinstance(header, dict) or not isinstance(header.get("hash"), str):
                        raise OracleUnavailable(f"{sample.network} height {sample.height} RPC header is invalid")
                    rows, _meta = oracle.block_transaction_page(header["hash"])
                    oracle.ensure_stable(sample)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                expected_number = decode_hex_int(header.get("number"), "header.number")
                expected_timestamp = decode_hex_int(header.get("timestamp"), "header.timestamp")
                self.assertGreater(len(rows), 1)
                for row in rows:
                    self.assertEqual(expected_number, int(row["block_number"]))
                    self.assertEqual(expected_timestamp, int(row["block_timestamp"]))

    # TEST-MAP: BLOCK-TXS-RPC-03
    def test_only_first_transaction_is_cellbase_with_special_input_preview(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    sample = oracle.transaction_sample()
                    header = sample.rpc_block.get("header")
                    transactions = sample.rpc_block.get("transactions")
                    block_hash = header.get("hash") if isinstance(header, dict) else None
                    if not isinstance(block_hash, str) or not isinstance(transactions, list) or len(transactions) <= 1:
                        raise OracleUnavailable(f"{sample.network} height {sample.height} RPC transactions are invalid")
                    rows, _meta = oracle.block_transaction_page(block_hash)
                    oracle.ensure_stable(sample)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual(transactions[0].get("hash"), rows[0].get("transaction_hash"))
                self.assertIs(rows[0].get("is_cellbase"), True)
                self.assertTrue(all(row.get("is_cellbase") is False for row in rows[1:]))
                preview = rows[0].get("display_inputs")
                self.assertIsInstance(preview, list)
                self.assertEqual(1, len(preview))
                self.assertIs(preview[0].get("from_cellbase"), True)
                self.assertEqual(transactions[0].get("hash"), preview[0].get("generated_tx_hash"))

    # TEST-MAP: BLOCK-TXS-RPC-04
    def test_input_and_output_counts_match_rpc(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    sample = oracle.transaction_sample()
                    header = sample.rpc_block.get("header")
                    transactions = sample.rpc_block.get("transactions")
                    block_hash = header.get("hash") if isinstance(header, dict) else None
                    if not isinstance(block_hash, str) or not isinstance(transactions, list):
                        raise OracleUnavailable(f"{sample.network} height {sample.height} RPC transactions are invalid")
                    rows, _meta = oracle.block_transaction_page(block_hash)
                    oracle.ensure_stable(sample)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual(len(transactions), len(rows))
                for tx_index, (transaction, row) in enumerate(zip(transactions, rows, strict=True)):
                    inputs = transaction.get("inputs")
                    outputs = transaction.get("outputs")
                    self.assertIsInstance(inputs, list)
                    self.assertIsInstance(outputs, list)
                    expected_inputs = 1 if tx_index == 0 else len(inputs)
                    self.assertEqual(expected_inputs, int(row["display_inputs_count"]))
                    self.assertEqual(len(outputs), int(row["display_outputs_count"]))

    # TEST-MAP: BLOCK-TXS-RPC-05
    def test_normal_input_previews_match_referenced_rpc_outputs(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    sample = oracle.transaction_sample()
                    header = sample.rpc_block.get("header")
                    transactions = sample.rpc_block.get("transactions")
                    block_hash = header.get("hash") if isinstance(header, dict) else None
                    if not isinstance(block_hash, str) or not isinstance(transactions, list) or len(transactions) <= 1:
                        raise OracleUnavailable(f"{sample.network} height {sample.height} has no normal transaction")
                    transaction = transactions[1]
                    if not isinstance(transaction, dict) or not isinstance(transaction.get("inputs"), list):
                        raise OracleUnavailable(f"{sample.network} height {sample.height} normal transaction is invalid")
                    referenced_outputs = oracle.referenced_outputs(transaction)
                    rows, _meta = oracle.block_transaction_page(block_hash)
                    row = next(item for item in rows if item.get("transaction_hash") == transaction.get("hash"))
                    previews = row.get("display_inputs")
                    if not isinstance(previews, list):
                        raise OracleUnavailable(f"{sample.network} height {sample.height} input previews are invalid")
                    oracle.ensure_stable(sample)
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error

                inputs = transaction["inputs"]
                self.assertEqual(min(10, len(inputs)), len(previews))
                for index, (preview, rpc_input, resolved) in enumerate(
                    zip(previews, inputs, referenced_outputs, strict=False)
                ):
                    previous_output, output_data = resolved
                    previous = rpc_input.get("previous_output")
                    since = preview.get("since")
                    self.assertIsInstance(previous, dict)
                    self.assertIsInstance(since, dict)
                    self.assertIs(preview.get("from_cellbase"), False)
                    self.assertEqual(previous.get("tx_hash"), preview.get("generated_tx_hash"))
                    self.assertEqual(
                        decode_hex_int(previous.get("index"), f"inputs[{index}].previous_output.index"),
                        int(preview["cell_index"]),
                    )
                    self.assertEqual(
                        decode_hex_int(rpc_input.get("since"), f"inputs[{index}].since"),
                        decode_hex_int(since.get("raw"), f"display_inputs[{index}].since.raw"),
                    )
                    self.assertEqual(
                        decode_hex_int(previous_output.get("capacity"), f"previous_outputs[{index}].capacity"),
                        int(Decimal(str(preview["capacity"]))),
                    )
                    self.assertEqual(
                        output_occupied_capacity(previous_output, output_data),
                        int(Decimal(str(preview["occupied_capacity"]))),
                    )
                    self.assertEqual(
                        output_address(previous_output, oracle.network.address_hrp),
                        preview.get("address_hash"),
                    )
                    if previous_output.get("type") is not None:
                        self.assertEqual(previous_output.get("type"), preview.get("type_script"))

    # TEST-MAP: BLOCK-TXS-RPC-06
    def test_output_previews_match_rpc_outputs(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    sample = oracle.transaction_sample()
                    header = sample.rpc_block.get("header")
                    transactions = sample.rpc_block.get("transactions")
                    block_hash = header.get("hash") if isinstance(header, dict) else None
                    if not isinstance(block_hash, str) or not isinstance(transactions, list):
                        raise OracleUnavailable(f"{sample.network} height {sample.height} RPC transactions are invalid")
                    rows, _meta = oracle.block_transaction_page(block_hash)
                    oracle.ensure_stable(sample)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                for tx_index, (transaction, row) in enumerate(zip(transactions, rows, strict=True)):
                    outputs = transaction.get("outputs")
                    outputs_data = transaction.get("outputs_data")
                    previews = row.get("display_outputs")
                    self.assertIsInstance(outputs, list)
                    self.assertIsInstance(outputs_data, list)
                    self.assertIsInstance(previews, list)
                    expected_length = len(outputs) if tx_index == 0 else min(10, len(outputs))
                    self.assertEqual(expected_length, len(previews))
                    for output_index, (preview, output, output_data) in enumerate(
                        zip(previews, outputs, outputs_data, strict=False)
                    ):
                        self.assertEqual(transaction.get("hash"), preview.get("generated_tx_hash"))
                        self.assertEqual(output_index, int(preview["cell_index"]))
                        self.assertEqual(
                            decode_hex_int(output.get("capacity"), f"outputs[{output_index}].capacity"),
                            int(Decimal(str(preview["capacity"]))),
                        )
                        self.assertEqual(
                            output_occupied_capacity(output, output_data),
                            int(Decimal(str(preview["occupied_capacity"]))),
                        )
                        self.assertEqual(output_address(output, oracle.network.address_hrp), preview.get("address_hash"))
                        if output.get("type") is not None:
                            self.assertEqual(output.get("type"), preview.get("type_script"))

    # TEST-MAP: BLOCK-TXS-RPC-07
    def test_wide_transaction_previews_keep_full_counts_and_first_ten_items(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    sample = oracle.wide_transaction_sample()
                    header = sample.rpc_block.get("header")
                    transactions = sample.rpc_block.get("transactions")
                    block_hash = header.get("hash") if isinstance(header, dict) else None
                    if not isinstance(block_hash, str) or not isinstance(transactions, list):
                        raise OracleUnavailable(f"{sample.network} height {sample.height} RPC transactions are invalid")
                    transaction = next(
                        item
                        for item in transactions[1:]
                        if isinstance(item, dict)
                        and (
                            isinstance(item.get("inputs"), list)
                            and len(item["inputs"]) > 10
                            or isinstance(item.get("outputs"), list)
                            and len(item["outputs"]) > 10
                        )
                    )
                    rows, _meta = oracle.block_transaction_page(block_hash)
                    row = next(item for item in rows if item.get("transaction_hash") == transaction.get("hash"))
                    oracle.ensure_stable(sample)
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error

                inputs = transaction.get("inputs")
                outputs = transaction.get("outputs")
                input_previews = row.get("display_inputs")
                output_previews = row.get("display_outputs")
                self.assertIsInstance(inputs, list)
                self.assertIsInstance(outputs, list)
                self.assertIsInstance(input_previews, list)
                self.assertIsInstance(output_previews, list)
                self.assertEqual(len(inputs), int(row["display_inputs_count"]))
                self.assertEqual(len(outputs), int(row["display_outputs_count"]))
                self.assertEqual(min(10, len(inputs)), len(input_previews))
                self.assertEqual(min(10, len(outputs)), len(output_previews))
                for preview, rpc_input in zip(input_previews, inputs, strict=False):
                    previous = rpc_input.get("previous_output")
                    self.assertIsInstance(previous, dict)
                    self.assertEqual(previous.get("tx_hash"), preview.get("generated_tx_hash"))
                    self.assertEqual(decode_hex_int(previous.get("index"), "previous_output.index"), int(preview["cell_index"]))
                for output_index, preview in enumerate(output_previews):
                    self.assertEqual(transaction.get("hash"), preview.get("generated_tx_hash"))
                    self.assertEqual(output_index, int(preview["cell_index"]))

    # TEST-MAP: BLOCK-TXS-RPC-08
    def test_transaction_hash_filter_returns_only_the_matching_block_transaction(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    sample = oracle.transaction_sample()
                    header = sample.rpc_block.get("header")
                    transactions = sample.rpc_block.get("transactions")
                    block_hash = header.get("hash") if isinstance(header, dict) else None
                    if not isinstance(block_hash, str) or not isinstance(transactions, list) or len(transactions) <= 1:
                        raise OracleUnavailable(f"{sample.network} height {sample.height} has no filter fixture")
                    tx_hash = transactions[1].get("hash")
                    if not isinstance(tx_hash, str):
                        raise OracleUnavailable(f"{sample.network} height {sample.height} transaction hash is invalid")
                    unfiltered, _meta = oracle.block_transaction_page(block_hash)
                    expected = next(item for item in unfiltered if item.get("transaction_hash") == tx_hash)
                    filtered, meta = oracle.block_transaction_page(block_hash, tx_hash=tx_hash)
                    oracle.ensure_stable(sample)
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual([expected], filtered)
                self.assertEqual(1, int(meta["total"]))

    # TEST-MAP: BLOCK-TXS-RPC-09
    def test_transaction_hash_filter_does_not_cross_block_boundary(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    sample = oracle.transaction_sample()
                    header = sample.rpc_block.get("header")
                    block_hash = header.get("hash") if isinstance(header, dict) else None
                    other_block = oracle.block(sample.height - 1)
                    other_transactions = other_block.get("transactions")
                    if not isinstance(block_hash, str) or not isinstance(other_transactions, list) or not other_transactions:
                        raise OracleUnavailable(f"{sample.network} height {sample.height} cross-block fixture is invalid")
                    other_hash = other_transactions[0].get("hash")
                    if not isinstance(other_hash, str):
                        raise OracleUnavailable(f"{sample.network} adjacent block transaction hash is invalid")
                    filtered, meta = oracle.block_transaction_page(block_hash, tx_hash=other_hash)
                    oracle.ensure_stable(sample)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual([], filtered)
                self.assertEqual(0, int(meta["total"]))

    # TEST-MAP: BLOCK-TXS-RPC-10
    def test_address_filter_matches_rpc_input_and_output_membership_in_chain_order(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    sample = oracle.transaction_sample()
                    header = sample.rpc_block.get("header")
                    block_hash = header.get("hash") if isinstance(header, dict) else None
                    if not isinstance(block_hash, str):
                        raise OracleUnavailable(f"{sample.network} height {sample.height} block hash is invalid")
                    addresses_by_transaction = _addresses_by_transaction(oracle, sample.rpc_block)
                    target_address = next(address for _tx_hash, addresses in addresses_by_transaction[1:] for address in addresses)
                    expected_hashes = [tx_hash for tx_hash, addresses in addresses_by_transaction if target_address in addresses]
                    filtered, meta = oracle.block_transaction_page(block_hash, address_hash=target_address)
                    oracle.ensure_stable(sample)
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error

                actual_hashes = [row.get("transaction_hash") for row in filtered]
                self.assertEqual(expected_hashes, actual_hashes)
                self.assertEqual(len(expected_hashes), int(meta["total"]))
                self.assertEqual(len(actual_hashes), len(set(actual_hashes)))

    # TEST-MAP: BLOCK-TXS-RPC-11
    def test_address_filter_does_not_cross_block_boundary(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    sample = oracle.transaction_sample()
                    header = sample.rpc_block.get("header")
                    block_hash = header.get("hash") if isinstance(header, dict) else None
                    if not isinstance(block_hash, str):
                        raise OracleUnavailable(f"{sample.network} height {sample.height} block hash is invalid")
                    addresses_by_transaction = _addresses_by_transaction(oracle, sample.rpc_block)
                    target_addresses = set().union(*(addresses for _tx_hash, addresses in addresses_by_transaction))
                    foreign_address = None
                    for height in range(sample.height - 1, max(-1, sample.height - 51), -1):
                        other_block = oracle.block(height)
                        other_transactions = other_block.get("transactions")
                        if not isinstance(other_transactions, list):
                            continue
                        for transaction in other_transactions:
                            outputs = transaction.get("outputs") if isinstance(transaction, dict) else None
                            if not isinstance(outputs, list):
                                continue
                            for output in outputs:
                                if not isinstance(output, dict):
                                    continue
                                candidate = output_address(output, oracle.network.address_hrp)
                                if candidate not in target_addresses:
                                    foreign_address = candidate
                                    break
                            if foreign_address:
                                break
                        if foreign_address:
                            break
                    if foreign_address is None:
                        raise OracleUnavailable(f"{sample.network} has no known address outside target block")
                    filtered, meta = oracle.block_transaction_page(block_hash, address_hash=foreign_address)
                    oracle.ensure_stable(sample)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual([], filtered)
                self.assertEqual(0, int(meta["total"]))

    # TEST-MAP: BLOCK-TXS-RPC-12
    def test_transaction_and_address_filters_use_intersection_semantics(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                try:
                    sample = oracle.transaction_sample()
                    header = sample.rpc_block.get("header")
                    block_hash = header.get("hash") if isinstance(header, dict) else None
                    if not isinstance(block_hash, str):
                        raise OracleUnavailable(f"{sample.network} height {sample.height} block hash is invalid")
                    addresses_by_transaction = _addresses_by_transaction(oracle, sample.rpc_block)
                    tx_hash, matching_addresses = addresses_by_transaction[1]
                    matching_address = next(iter(matching_addresses))
                    nonmatching_address = next(
                        address
                        for other_hash, addresses in addresses_by_transaction
                        if other_hash != tx_hash
                        for address in addresses
                        if address not in matching_addresses
                    )
                    matching, matching_meta = oracle.block_transaction_page(
                        block_hash,
                        tx_hash=tx_hash,
                        address_hash=matching_address,
                    )
                    nonmatching, nonmatching_meta = oracle.block_transaction_page(
                        block_hash,
                        tx_hash=tx_hash,
                        address_hash=nonmatching_address,
                    )
                    oracle.ensure_stable(sample)
                except (OracleUnavailable, StopIteration) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual([tx_hash], [row.get("transaction_hash") for row in matching])
                self.assertEqual(1, int(matching_meta["total"]))
                self.assertEqual([], nonmatching)
                self.assertEqual(0, int(nonmatching_meta["total"]))


if __name__ == "__main__":
    unittest.main()
