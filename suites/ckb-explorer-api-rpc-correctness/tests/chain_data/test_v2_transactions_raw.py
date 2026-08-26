from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


RAW_FIXTURES = {
    "mainnet": "0xba86729380f7e033d722e8fc197159db4dbd4ad6e05e28e297be8230e12a0af7",
    "testnet": "0x926de250e2771d0dc9bb49d6a9f27877d3ca7c46d473017a92cce5eed111cac6",
}
CELLBASE_FIXTURES = {
    "mainnet": "0x309bd4333114ec1394bd8226f4d54e318decfa6a168b94d188b1ed136c8eb5e1",
    "testnet": "0xe90b5763d3b53779a55ceac54c33fa6dc9113c0570de3a8ef696c9ad58db41b8",
}
ZERO_TX_HASH = "0x" + "00" * 32


class V2TransactionsRawRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _load(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
        try:
            api_genesis = oracle.detail_attributes(0)
            rpc_genesis = oracle.block(0)
            api_tip = oracle.api_tip_height()
            rpc_tip = oracle.rpc_tip_height()
            result = oracle.rpc_result("get_transaction", [transaction_hash])
            payload = oracle.explorer_json(f"/v2/transactions/{transaction_hash}/raw")
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error

        rpc_header = rpc_genesis.get("header")
        transaction = result.get("transaction") if isinstance(result, dict) else None
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC transaction {transaction_hash} is unavailable"
            )
        self.assertIsInstance(rpc_header, dict)
        self.assertEqual(rpc_header.get("hash"), api_genesis.get("block_hash"))
        self.assertLessEqual(api_tip, rpc_tip)
        self.assertLessEqual(rpc_tip - api_tip, self.settings.max_lag_blocks)
        self.assertIsInstance(payload, dict)
        self.assertEqual("committed", status.get("status"))
        self.assertEqual(transaction_hash, transaction.get("hash"))
        return transaction, status, payload

    def _normalized(self, transaction: Mapping[str, Any]) -> Mapping[str, Any]:
        inputs = transaction.get("inputs")
        outputs = transaction.get("outputs")
        cell_deps = transaction.get("cell_deps")
        self.assertIsInstance(inputs, list)
        self.assertIsInstance(outputs, list)
        self.assertIsInstance(cell_deps, list)
        return {
            "hash": transaction.get("hash"),
            "version": decode_hex_int(transaction.get("version"), "version"),
            "header_deps": transaction.get("header_deps"),
            "cell_deps": [
                {
                    "dep_type": item.get("dep_type"),
                    "out_point": {
                        "tx_hash": item.get("out_point", {}).get("tx_hash"),
                        "index": decode_hex_int(
                            item.get("out_point", {}).get("index"),
                            f"cell_deps[{index}].out_point.index",
                        ),
                    },
                }
                for index, item in enumerate(cell_deps)
            ],
            "inputs": [
                {
                    "since": decode_hex_int(item.get("since"), f"inputs[{index}].since"),
                    "previous_output": {
                        "tx_hash": item.get("previous_output", {}).get("tx_hash"),
                        "index": decode_hex_int(
                            item.get("previous_output", {}).get("index"),
                            f"inputs[{index}].previous_output.index",
                        ),
                    },
                }
                for index, item in enumerate(inputs)
            ],
            "outputs": [
                {
                    "capacity": decode_hex_int(
                        item.get("capacity"), f"outputs[{index}].capacity"
                    ),
                    "lock": item.get("lock"),
                    "type": item.get("type"),
                }
                for index, item in enumerate(outputs)
            ],
            "outputs_data": transaction.get("outputs_data"),
            "witnesses": transaction.get("witnesses"),
        }

    def _assert_stable(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
        initial_status: Mapping[str, Any],
    ) -> None:
        try:
            fresh = oracle.rpc_result("get_transaction", [transaction_hash])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        status = fresh.get("tx_status") if isinstance(fresh, dict) else None
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

    # TEST-MAP: V2-TX-RPC-01
    @unittest.expectedFailure
    def test_confirmed_raw_transaction_matches_rpc_fields_and_array_order(self) -> None:
        mismatches: list[str] = []
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                transaction_hash = RAW_FIXTURES[network.name]
                transaction, status, payload = self._load(oracle, transaction_hash)
                inputs = transaction.get("inputs")
                outputs = transaction.get("outputs")
                cell_deps = transaction.get("cell_deps")
                header_deps = transaction.get("header_deps")
                witnesses = transaction.get("witnesses")
                self.assertIsInstance(inputs, list)
                self.assertIsInstance(outputs, list)
                self.assertIsInstance(cell_deps, list)
                self.assertIsInstance(header_deps, list)
                self.assertIsInstance(witnesses, list)
                self.assertGreater(len(inputs), 1)
                self.assertGreater(len(outputs), 1)
                self.assertTrue(cell_deps)
                self.assertTrue(header_deps)
                self.assertTrue(witnesses)
                expected = self._normalized(transaction)
                actual = self._normalized(payload)
                if expected != actual:
                    mismatches.append(
                        f"{network.name} tx={transaction_hash}: expected={expected!r}; actual={actual!r}"
                    )
                self._assert_stable(oracle, transaction_hash, status)
        self.assertEqual([], mismatches, "\n".join(mismatches))

    # TEST-MAP: V2-TX-RPC-02
    def test_cellbase_raw_transaction_preserves_system_input_outputs_data_and_witness(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                transaction_hash = CELLBASE_FIXTURES[network.name]
                transaction, status, payload = self._load(oracle, transaction_hash)
                inputs = transaction.get("inputs")
                self.assertIsInstance(inputs, list)
                self.assertEqual(1, len(inputs))
                previous_output = inputs[0].get("previous_output")
                self.assertIsInstance(previous_output, dict)
                self.assertEqual(ZERO_TX_HASH, previous_output.get("tx_hash"))
                self.assertEqual(
                    0xFFFFFFFF,
                    decode_hex_int(previous_output.get("index"), "cellbase.previous_output.index"),
                )
                self.assertEqual(self._normalized(transaction), self._normalized(payload))
                self._assert_stable(oracle, transaction_hash, status)


if __name__ == "__main__":
    unittest.main()
