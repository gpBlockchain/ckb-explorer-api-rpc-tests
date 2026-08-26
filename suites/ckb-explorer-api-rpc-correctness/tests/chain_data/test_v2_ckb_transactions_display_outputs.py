from __future__ import annotations

import unittest
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import (
    decode_hex_int,
    output_address,
    output_occupied_capacity,
)
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


@dataclass(frozen=True)
class OutputStatusFixture:
    transaction_hash: str
    output_index: int
    consumed_transaction_hash: str | None


@dataclass(frozen=True)
class DisplayOutputsNetworkFixture:
    ordinary_transaction_hash: str
    reward_cellbase_transaction_hash: str
    multi_output_cellbase_transaction_hash: str
    live_output: OutputStatusFixture
    dead_output: OutputStatusFixture


DISPLAY_OUTPUTS_FIXTURES = {
    "mainnet": DisplayOutputsNetworkFixture(
        ordinary_transaction_hash="0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7",
        reward_cellbase_transaction_hash=(
            "0xae1fa53d770c7571de66c7373528508c4591edca36f7e870c307cd1f88d7e3a4"
        ),
        multi_output_cellbase_transaction_hash=(
            "0xe2fb199810d49a4d8beec56718ba2593b665db9d52299a0f9e6e75416d73ff5c"
        ),
        live_output=OutputStatusFixture(
            transaction_hash="0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7",
            output_index=0,
            consumed_transaction_hash=None,
        ),
        dead_output=OutputStatusFixture(
            transaction_hash="0xae1fa53d770c7571de66c7373528508c4591edca36f7e870c307cd1f88d7e3a4",
            output_index=0,
            consumed_transaction_hash=(
                "0x98db925cc0021864c1958e337ba8752423e11d98acc3cfe498c8e9521cbe3c90"
            ),
        ),
    ),
    "testnet": DisplayOutputsNetworkFixture(
        ordinary_transaction_hash="0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def",
        reward_cellbase_transaction_hash=(
            "0xa3ca91e5368fafec9c61ac3c94152436cb3e8329af078a3ceee66bbd63af8016"
        ),
        multi_output_cellbase_transaction_hash=(
            "0x8f8c79eb6671709633fe6a46de93c0fedc9c1b8a6527a18d3983879542635c9f"
        ),
        live_output=OutputStatusFixture(
            transaction_hash="0x8f8c79eb6671709633fe6a46de93c0fedc9c1b8a6527a18d3983879542635c9f",
            output_index=0,
            consumed_transaction_hash=None,
        ),
        dead_output=OutputStatusFixture(
            transaction_hash="0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def",
            output_index=0,
            consumed_transaction_hash=(
                "0xdeb874f3b0fa0bf09394491b7aedc03af0b1cc9f82c3c5f9c09ced0910cf4c1a"
            ),
        ),
    ),
}


class V2CkbTransactionsDisplayOutputsRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.oracles = tuple(NetworkOracle(network, cls.settings) for network in cls.settings.networks)
        cls.samples: dict[tuple[str, str], tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
        cls.checked_networks: set[str] = set()

    def _assert_network_pair(self, oracle: NetworkOracle) -> None:
        if oracle.network.name in self.checked_networks:
            return
        try:
            api_genesis = oracle.detail_attributes(0)
            rpc_genesis = oracle.block(0)
            api_tip = oracle.api_tip_height()
            rpc_tip = oracle.rpc_tip_height()
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        rpc_header = rpc_genesis.get("header")
        self.assertIsInstance(rpc_header, dict)
        self.assertEqual(rpc_header.get("hash"), api_genesis.get("block_hash"))
        self.assertLessEqual(api_tip, rpc_tip)
        self.assertLessEqual(rpc_tip - api_tip, self.settings.max_lag_blocks)
        self.checked_networks.add(oracle.network.name)

    def _load_sample(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        key = (oracle.network.name, transaction_hash)
        if key in self.samples:
            return self.samples[key]
        self._assert_network_pair(oracle)
        try:
            result = oracle.rpc_result("get_transaction", [transaction_hash])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        transaction = result.get("transaction") if isinstance(result, dict) else None
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC transaction {transaction_hash} is unavailable"
            )
        try:
            block_hash = status.get("block_hash")
            if not isinstance(block_hash, str):
                raise OracleUnavailable(
                    f"{oracle.network.name} RPC transaction {transaction_hash} has no block hash"
                )
            block = oracle.block_by_hash(block_hash)
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        block_transactions = block.get("transactions")
        self.assertIsInstance(block_transactions, list)
        self.assertEqual("committed", status.get("status"))
        self.assertEqual(transaction_hash, transaction.get("hash"))
        tx_index = decode_hex_int(status.get("tx_index"), "tx_status.tx_index")
        self.assertEqual(transaction_hash, block_transactions[tx_index].get("hash"))
        self.samples[key] = transaction, status
        return self.samples[key]

    def _assert_sample_stable(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
        initial_status: Mapping[str, Any],
    ) -> None:
        try:
            result = oracle.rpc_result("get_transaction", [transaction_hash])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(status, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC transaction {transaction_hash} became unavailable"
            )
        if (
            status.get("status") != initial_status.get("status")
            or status.get("block_hash") != initial_status.get("block_hash")
        ):
            raise unittest.SkipTest(
                f"{oracle.network.name} transaction {transaction_hash} changed status or block"
            )

    def _display_outputs(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
        **query: object,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        try:
            payload = oracle.explorer_json(
                f"/v2/ckb_transactions/{transaction_hash}/display_outputs",
                query or None,
            )
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        context = f"{oracle.network.name} tx={transaction_hash} query={query} body={payload!r}"
        self.assertIsInstance(data, list, context)
        self.assertIsInstance(meta, dict, context)
        self.assertTrue(all(isinstance(row, dict) for row in data), context)
        return data, meta

    def _decimal_integer(self, value: object, field: str) -> int:
        try:
            decimal = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            self.fail(f"{field} is not a decimal number: {value!r}; {error}")
        self.assertTrue(decimal.is_finite(), f"{field} must be finite: {value!r}")
        self.assertEqual(decimal, decimal.to_integral_value(), f"{field} is not an integer")
        return int(decimal)

    def _assert_output_identity(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
        output_index: int,
        output: Mapping[str, Any],
        output_data: object,
        actual: Mapping[str, Any],
        *,
        compare_type_script: bool,
    ) -> None:
        context = f"{oracle.network.name} tx={transaction_hash} output={output_index}"
        self.assertEqual(transaction_hash, actual.get("generated_tx_hash"), context)
        self.assertEqual(output_index, int(actual.get("cell_index")), context)
        self.assertEqual(
            decode_hex_int(output.get("capacity"), f"outputs[{output_index}].capacity"),
            self._decimal_integer(actual.get("capacity"), f"{context}.capacity"),
            context,
        )
        self.assertEqual(
            output_occupied_capacity(output, output_data),
            self._decimal_integer(
                actual.get("occupied_capacity"), f"{context}.occupied_capacity"
            ),
            context,
        )
        self.assertEqual(
            output_address(output, oracle.network.address_hrp),
            actual.get("address_hash"),
            context,
        )
        if compare_type_script and isinstance(output.get("type"), dict):
            self.assertEqual(output.get("type"), actual.get("type_script"), context)

    # TEST-MAP: CKB-TX-VIEWS-RPC-15
    def test_all_displayed_outputs_match_rpc_order_capacity_address_and_type(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                transaction_hash = DISPLAY_OUTPUTS_FIXTURES[
                    oracle.network.name
                ].ordinary_transaction_hash
                transaction, status = self._load_sample(oracle, transaction_hash)
                outputs = transaction.get("outputs")
                outputs_data = transaction.get("outputs_data")
                self.assertIsInstance(outputs, list)
                self.assertIsInstance(outputs_data, list)
                self.assertEqual(len(outputs), len(outputs_data))
                self.assertTrue(
                    any(
                        isinstance(output, dict) and isinstance(output.get("type"), dict)
                        for output in outputs
                    )
                )
                data, meta = self._display_outputs(oracle, transaction_hash)
                self.assertEqual(len(outputs), int(meta.get("total")))
                self.assertEqual(len(outputs), len(data))
                for output_index, (output, output_data, actual) in enumerate(
                    zip(outputs, outputs_data, data, strict=True)
                ):
                    self.assertIsInstance(output, dict)
                    self._assert_output_identity(
                        oracle,
                        transaction_hash,
                        output_index,
                        output,
                        output_data,
                        actual,
                        compare_type_script=True,
                    )
                self._assert_sample_stable(oracle, transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-16
    def test_page_size_one_preserves_first_two_rpc_output_positions(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                transaction_hash = DISPLAY_OUTPUTS_FIXTURES[
                    oracle.network.name
                ].ordinary_transaction_hash
                transaction, status = self._load_sample(oracle, transaction_hash)
                outputs = transaction.get("outputs")
                self.assertIsInstance(outputs, list)
                self.assertGreaterEqual(len(outputs), 2)
                pages: list[Mapping[str, Any]] = []
                for page in (1, 2):
                    data, meta = self._display_outputs(
                        oracle, transaction_hash, page=page, page_size=1
                    )
                    self.assertEqual(1, len(data))
                    self.assertEqual(len(outputs), int(meta.get("total")))
                    self.assertEqual(1, int(meta.get("page_size")))
                    pages.append(data[0])
                self.assertEqual(0, int(pages[0].get("cell_index")))
                self.assertEqual(1, int(pages[1].get("cell_index")))
                self.assertNotEqual(pages[0].get("id"), pages[1].get("id"))
                self._assert_sample_stable(oracle, transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-17
    def test_live_and_dead_output_statuses_match_rpc_and_consumer(self) -> None:
        for oracle in self.oracles:
            fixtures = DISPLAY_OUTPUTS_FIXTURES[oracle.network.name]
            for expected_status, fixture in (
                ("live", fixtures.live_output),
                ("dead", fixtures.dead_output),
            ):
                with self.subTest(network=oracle.network.name, status=expected_status):
                    transaction, tx_status = self._load_sample(
                        oracle, fixture.transaction_hash
                    )
                    outputs = transaction.get("outputs")
                    self.assertIsInstance(outputs, list)
                    self.assertLess(fixture.output_index, len(outputs))
                    out_point = {
                        "tx_hash": fixture.transaction_hash,
                        "index": hex(fixture.output_index),
                    }
                    try:
                        before = oracle.rpc_result("get_live_cell", [out_point, True])
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertIsInstance(before, dict)
                    if expected_status == "live":
                        self.assertEqual("live", before.get("status"))
                    else:
                        self.assertEqual("unknown", before.get("status"))
                    data, _meta = self._display_outputs(
                        oracle,
                        fixture.transaction_hash,
                        page=fixture.output_index + 1,
                        page_size=1,
                    )
                    self.assertEqual(1, len(data))
                    actual = data[0]
                    self.assertEqual(expected_status, actual.get("status"))
                    if expected_status == "live":
                        self.assertIn(actual.get("consumed_tx_hash"), (None, ""))
                        self.assertIsNone(fixture.consumed_transaction_hash)
                    else:
                        consumer_hash = fixture.consumed_transaction_hash
                        self.assertIsInstance(consumer_hash, str)
                        self.assertEqual(consumer_hash, actual.get("consumed_tx_hash"))
                        consumer, consumer_status = self._load_sample(oracle, consumer_hash)
                        consumer_inputs = consumer.get("inputs")
                        self.assertIsInstance(consumer_inputs, list)
                        self.assertTrue(
                            any(
                                isinstance(item, dict)
                                and isinstance(item.get("previous_output"), dict)
                                and item["previous_output"].get("tx_hash")
                                == fixture.transaction_hash
                                and decode_hex_int(
                                    item["previous_output"].get("index"),
                                    "consumer.previous_output.index",
                                )
                                == fixture.output_index
                                for item in consumer_inputs
                            )
                        )
                        self._assert_sample_stable(oracle, consumer_hash, consumer_status)
                    try:
                        after = oracle.rpc_result("get_live_cell", [out_point, True])
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertIsInstance(after, dict)
                    self.assertEqual(before.get("status"), after.get("status"))
                    self._assert_sample_stable(oracle, fixture.transaction_hash, tx_status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-18
    def test_mature_cellbase_outputs_and_reward_components_match_rpc(self) -> None:
        reward_fields = {
            "base_reward": "primary",
            "secondary_reward": "secondary",
            "proposal_reward": "proposal",
            "commit_reward": "committed",
        }
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                transaction_hash = DISPLAY_OUTPUTS_FIXTURES[
                    oracle.network.name
                ].reward_cellbase_transaction_hash
                transaction, status = self._load_sample(oracle, transaction_hash)
                outputs = transaction.get("outputs")
                outputs_data = transaction.get("outputs_data")
                self.assertIsInstance(outputs, list)
                self.assertIsInstance(outputs_data, list)
                self.assertEqual(len(outputs), len(outputs_data))
                try:
                    block = oracle.block_by_hash(str(status.get("block_hash")))
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                header = block.get("header")
                self.assertIsInstance(header, dict)
                block_number = decode_hex_int(header.get("number"), "cellbase.header.number")
                target_number = max(0, block_number - self.settings.proposal_window - 1)
                try:
                    target_block = oracle.block(target_number)
                    target_header = target_block.get("header")
                    if not isinstance(target_header, dict):
                        raise OracleUnavailable(
                            f"{oracle.network.name} target block {target_number} has no header"
                        )
                    economic_state = oracle.rpc_result(
                        "get_block_economic_state", [target_header.get("hash")]
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                miner_reward = (
                    economic_state.get("miner_reward")
                    if isinstance(economic_state, dict)
                    else None
                )
                self.assertIsInstance(miner_reward, dict)

                data, meta = self._display_outputs(oracle, transaction_hash)
                self.assertEqual(len(outputs), int(meta.get("total")))
                self.assertEqual(len(outputs), len(data))
                for output_index, (output, output_data, actual) in enumerate(
                    zip(outputs, outputs_data, data, strict=True)
                ):
                    self.assertIsInstance(output, dict)
                    self._assert_output_identity(
                        oracle,
                        transaction_hash,
                        output_index,
                        output,
                        output_data,
                        actual,
                        compare_type_script=False,
                    )
                    self.assertEqual(target_number, int(actual.get("target_block_number")))
                    for api_field, rpc_field in reward_fields.items():
                        self.assertEqual(
                            decode_hex_int(miner_reward.get(rpc_field), f"miner_reward.{rpc_field}"),
                            self._decimal_integer(actual.get(api_field), api_field),
                        )
                self._assert_sample_stable(oracle, transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-19
    def test_multi_output_cellbase_paginates_by_rpc_output_index(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                transaction_hash = DISPLAY_OUTPUTS_FIXTURES[
                    oracle.network.name
                ].multi_output_cellbase_transaction_hash
                transaction, status = self._load_sample(oracle, transaction_hash)
                outputs = transaction.get("outputs")
                outputs_data = transaction.get("outputs_data")
                self.assertIsInstance(outputs, list)
                self.assertIsInstance(outputs_data, list)
                self.assertGreaterEqual(len(outputs), 2)
                self.assertEqual(len(outputs), len(outputs_data))
                pages: list[Mapping[str, Any]] = []
                for page in (1, 2):
                    data, meta = self._display_outputs(
                        oracle, transaction_hash, page=page, page_size=1
                    )
                    self.assertEqual(1, len(data))
                    self.assertEqual(len(outputs), int(meta.get("total")))
                    self.assertEqual(1, int(meta.get("page_size")))
                    pages.append(data[0])
                for output_index, actual in enumerate(pages):
                    output = outputs[output_index]
                    self.assertIsInstance(output, dict)
                    self._assert_output_identity(
                        oracle,
                        transaction_hash,
                        output_index,
                        output,
                        outputs_data[output_index],
                        actual,
                        compare_type_script=False,
                    )
                self.assertNotEqual(pages[0].get("id"), pages[1].get("id"))
                self._assert_sample_stable(oracle, transaction_hash, status)


if __name__ == "__main__":
    unittest.main()
