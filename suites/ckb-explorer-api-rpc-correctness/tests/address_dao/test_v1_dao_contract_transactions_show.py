from __future__ import annotations

import unittest
import urllib.parse
from decimal import Decimal
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_address_dao_transactions_show import _explorer_response
from tests.address_dao.test_v1_addresses_show import ACTIVITY_TRANSACTIONS


DEPOSIT_TRANSACTIONS = {
    "mainnet": "0xcc7c823497cf19a616f3a23ef660b250624544be62f20db76bb36ed661bcb449",
    "testnet": "0x25cc211764095166c16be8dfb32e141a334ae847bcde49979430a80899d2c3c9",
}
WITHDRAW_REQUEST_TRANSACTIONS = {
    "mainnet": "0x315eb9a89c36ac82e8c5fcaa9a19e029b71570269186ea9f62ffc699ae4d50bb",
}
CLAIM_TRANSACTIONS = {
    "mainnet": "0x7c91d9bdfbff8a323d7a2396d4b6fa6da5b51601602fe26a1aefdbe55ebd7330",
}
DAO_CODE_HASH = "0x82d76d1b75fe2fd9a27dfbaa65a039221a380d76c926f378d3f81cf3e7e13f2e"


class V1DaoContractTransactionsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _sample(
        self,
        oracle: NetworkOracle,
        tx_hash: str,
    ) -> tuple[Mapping[str, Any], list[tuple[Mapping[str, Any], object]], Mapping[str, Any]]:
        result = oracle.rpc_result("get_transaction", [tx_hash])
        transaction = result.get("transaction") if isinstance(result, dict) else None
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC transaction {tx_hash} is unavailable")
        referenced = oracle.referenced_outputs(transaction)
        payload = oracle.explorer_json(f"/v1/dao_contract_transactions/{tx_hash}")
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        if not isinstance(attributes, dict):
            raise OracleUnavailable(f"{oracle.network.name} DAO detail {tx_hash} is unavailable")
        return transaction, referenced, attributes

    def _assert_core(self, transaction: Mapping[str, Any], attributes: Mapping[str, Any]) -> None:
        self.assertEqual(transaction.get("hash"), attributes.get("transaction_hash"))
        self.assertEqual(decode_hex_int(transaction.get("version"), "transaction.version"), int(attributes["version"]))
        self.assertEqual(transaction.get("witnesses"), attributes.get("witnesses"))
        self.assertEqual(transaction.get("header_deps"), attributes.get("header_deps"))
        rpc_cell_deps = transaction.get("cell_deps")
        api_cell_deps = attributes.get("cell_deps")
        self.assertIsInstance(rpc_cell_deps, list)
        self.assertIsInstance(api_cell_deps, list)
        self.assertEqual(len(rpc_cell_deps), len(api_cell_deps))
        for rpc_dep, api_dep in zip(rpc_cell_deps, api_cell_deps, strict=True):
            self.assertEqual(rpc_dep.get("dep_type"), api_dep.get("dep_type"))
            self.assertEqual(rpc_dep["out_point"]["tx_hash"], api_dep["out_point"]["tx_hash"])
            self.assertEqual(decode_hex_int(rpc_dep["out_point"]["index"], "cell_dep.index"),
                             int(api_dep["out_point"]["index"]))

    # TEST-MAP: DAO-TX-RPC-05
    @unittest.expectedFailure  # Public detail serialization currently omits all input/output Cells.
    def test_deposit_detail_matches_rpc_structure_and_deposit_output_capacity(self) -> None:
        observations: list[tuple[int, int]] = []
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                transaction, _referenced, attributes = self._sample(oracle, DEPOSIT_TRANSACTIONS[network.name])
            except OracleUnavailable as error:
                continue
            self._assert_core(transaction, attributes)
            deposits = [
                (index, output) for index, output in enumerate(transaction["outputs"])
                if isinstance(output.get("type"), dict)
                and output["type"].get("code_hash") == DAO_CODE_HASH
                and transaction["outputs_data"][index] == "0x" + "00" * 8
            ]
            self.assertTrue(deposits)
            expected_capacity = sum(decode_hex_int(output["capacity"], "deposit.capacity") for _index, output in deposits)
            display_outputs = attributes.get("display_outputs")
            actual_capacity = sum(
                int(Decimal(str(item["capacity"])))
                for item in display_outputs
                if item.get("cell_type") == "nervos_dao_deposit"
            ) if isinstance(display_outputs, list) else 0
            observations.append((expected_capacity, actual_capacity))
        self.assertTrue(observations)
        self.assertEqual(observations, [(expected, expected) for expected, _actual in observations])

    # TEST-MAP: DAO-TX-RPC-06
    @unittest.expectedFailure  # Public detail serialization currently omits all input/output Cells.
    def test_withdraw_request_links_deposit_outpoint_and_encodes_deposit_block_number(self) -> None:
        observations: list[tuple[int, int]] = []
        for network in self.settings.networks:
            tx_hash = WITHDRAW_REQUEST_TRANSACTIONS.get(network.name)
            if tx_hash is None:
                continue
            oracle = NetworkOracle(network, self.settings)
            transaction, referenced, attributes = self._sample(oracle, tx_hash)
            self._assert_core(transaction, attributes)
            deposit_indexes = [
                index for index, (output, data) in enumerate(referenced)
                if isinstance(output.get("type"), dict)
                and output["type"].get("code_hash") == DAO_CODE_HASH
                and data == "0x" + "00" * 8
            ]
            self.assertTrue(deposit_indexes)
            deposit_index = deposit_indexes[0]
            previous_hash = transaction["inputs"][deposit_index]["previous_output"]["tx_hash"]
            previous = oracle.rpc_result("get_transaction", [previous_hash])
            previous_status = previous.get("tx_status") if isinstance(previous, dict) else None
            self.assertIsInstance(previous_status, dict)
            deposit_block_number = decode_hex_int(previous_status.get("block_number"), "deposit.block_number")
            withdrawing_data = transaction["outputs_data"][deposit_index]
            self.assertEqual(deposit_block_number, int.from_bytes(bytes.fromhex(withdrawing_data[2:]), "little"))
            previews = attributes.get("display_inputs")
            preview_count = len(previews) if isinstance(previews, list) else 0
            observations.append((len(transaction["inputs"]), preview_count))
        self.assertTrue(observations)
        self.assertEqual(observations, [(expected, expected) for expected, _actual in observations])

    # TEST-MAP: DAO-TX-RPC-07
    @unittest.expectedFailure  # Public detail serialization currently omits the DAO claim event Cells.
    def test_claim_detail_has_header_dependency_and_exact_integer_interest_event(self) -> None:
        observations: list[tuple[int, int]] = []
        for network in self.settings.networks:
            tx_hash = CLAIM_TRANSACTIONS.get(network.name)
            if tx_hash is None:
                continue
            oracle = NetworkOracle(network, self.settings)
            transaction, referenced, attributes = self._sample(oracle, tx_hash)
            self._assert_core(transaction, attributes)
            self.assertTrue(transaction.get("header_deps"))
            principal = sum(
                decode_hex_int(output["capacity"], "withdrawing.capacity")
                for output, _data in referenced
                if isinstance(output.get("type"), dict) and output["type"].get("code_hash") == DAO_CODE_HASH
            )
            released = sum(
                decode_hex_int(output["capacity"], "claim.capacity")
                for output in transaction["outputs"]
                if output.get("type") is None
            )
            previews = attributes.get("display_inputs")
            interest = sum(
                int(item.get("interest", 0))
                for item in previews
                if item.get("cell_type") == "nervos_dao_withdrawing"
            ) if isinstance(previews, list) else 0
            self.assertGreaterEqual(released, principal)
            observations.append((released - principal, interest))
        self.assertTrue(observations)
        self.assertEqual(observations, [(expected, expected) for expected, _actual in observations])

    # TEST-MAP: DAO-TX-RPC-09
    def test_invalid_missing_and_ordinary_hashes_return_reviewed_errors(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                cases = (
                    ("not-a-hash", 422, 1005),
                    ("0x" + "00" * 32, 404, 1006),
                    (ACTIVITY_TRANSACTIONS[network.name], 404, 1006),
                )
                for tx_hash, expected_status, expected_code in cases:
                    path = "/v1/dao_contract_transactions/" + urllib.parse.quote(tx_hash, safe="")
                    status, payload = _explorer_response(oracle, path)
                    if status == 403 and isinstance(payload, dict) and payload.get("cloudflare_error") is True:
                        raise unittest.SkipTest(f"{network.name} edge rejected negative-path observation")
                    self.assertEqual(expected_status, status)
                    self.assertIsInstance(payload, list)
                    self.assertEqual(expected_code, payload[0].get("code"))


if __name__ == "__main__":
    unittest.main()
