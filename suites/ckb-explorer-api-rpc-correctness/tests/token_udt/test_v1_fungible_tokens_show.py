from __future__ import annotations

import unittest

from ckb_rpc_correctness.ckb import ckb_script_hash
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


SSRI_FIXTURES = {
    "testnet": "0x6a08da7ea4d1ab4beb4338526fbcb86accc2617a9413fc014ad2e2f8f63706e9",
}


class V1FungibleTokensShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: XUDT-FT-RPC-12
    def test_ssri_contract_outpoint_matches_committed_rpc_deployment_cell(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                type_hash = SSRI_FIXTURES.get(network.name)
                if type_hash is None:
                    raise unittest.SkipTest(f"{network.name} published SSRI fixture is unavailable")
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.explorer_json(f"/v1/fungible_tokens/{type_hash}")
                    data = payload.get("data") if isinstance(payload, dict) else None
                    attributes = data.get("attributes") if isinstance(data, dict) else None
                    if not isinstance(attributes, dict):
                        raise OracleUnavailable(f"{network.name} SSRI detail is unavailable")
                    script = attributes.get("type_script")
                    outpoint = attributes.get("ssri_contract_outpoint")
                    if not isinstance(script, dict) or not isinstance(outpoint, dict):
                        raise OracleUnavailable(f"{network.name} SSRI deployment reference is unavailable")
                    tx_hash = outpoint.get("tx_hash")
                    cell_index = outpoint.get("cell_index")
                    if not isinstance(tx_hash, str) or not isinstance(cell_index, int):
                        raise OracleUnavailable(f"{network.name} SSRI deployment OutPoint is invalid")
                    result = oracle.rpc_result("get_transaction", [tx_hash])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    outputs = transaction.get("outputs") if isinstance(transaction, dict) else None
                    outputs_data = transaction.get("outputs_data") if isinstance(transaction, dict) else None
                    if (
                        not isinstance(status, dict)
                        or not isinstance(outputs, list)
                        or not isinstance(outputs_data, list)
                        or cell_index >= len(outputs)
                        or cell_index >= len(outputs_data)
                        or not isinstance(outputs[cell_index], dict)
                        or not isinstance(outputs_data[cell_index], str)
                    ):
                        raise OracleUnavailable(f"{network.name} SSRI deployment Cell is unavailable")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual("udt", data.get("type"))
                self.assertEqual(type_hash, attributes.get("type_hash"))
                self.assertEqual(type_hash, ckb_script_hash(script))
                self.assertEqual("ssri", attributes.get("udt_type"))
                self.assertIs(attributes.get("published"), True)
                self.assertEqual("committed", status.get("status"))
                self.assertEqual(tx_hash, transaction.get("hash"))
                deployed_type = outputs[cell_index].get("type")
                self.assertIsInstance(deployed_type, dict)
                self.assertEqual("type", script.get("hash_type"))
                self.assertEqual(script.get("code_hash"), ckb_script_hash(deployed_type))
                self.assertGreater(len(bytes.fromhex(outputs_data[cell_index].removeprefix("0x"))), 0)


if __name__ == "__main__":
    unittest.main()
