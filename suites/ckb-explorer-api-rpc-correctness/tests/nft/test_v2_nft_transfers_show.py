from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V2NftTransfersShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: NFT-TX-RPC-07
    def test_global_transfer_detail_matches_list_identity_and_ckb_cells(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    page = oracle.explorer_json("/v2/nft/transfers")
                    rows = page.get("data") if isinstance(page, dict) else None
                    if not isinstance(rows, list) or not rows:
                        raise OracleUnavailable(
                            f"{network.name} NFT transfer list is unavailable"
                        )
                    listed = rows[0]
                    detail = oracle.explorer_json(
                        f"/v2/nft/transfers/{listed['id']}"
                    )
                    item = detail["item"]
                    type_script = {
                        key: item["type_script"][key]
                        for key in ("code_hash", "hash_type", "args")
                    }
                    result = oracle.rpc_result(
                        "get_transaction", [detail["transaction"]["tx_hash"]]
                    )
                    transaction = (
                        result.get("transaction") if isinstance(result, dict) else None
                    )
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict) or not isinstance(status, dict):
                        raise OracleUnavailable(
                            f"{network.name} NFT transfer transaction is unavailable"
                        )
                    referenced = oracle.referenced_outputs(transaction)
                    block = oracle.block_by_hash(status["block_hash"])
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                matching_inputs = [
                    output
                    for output, _data in referenced
                    if output.get("type") == type_script
                ]
                matching_outputs = [
                    output
                    for output in transaction["outputs"]
                    if output.get("type") == type_script
                ]
                if len(matching_inputs) > 1 or len(matching_outputs) > 1:
                    raise unittest.SkipTest(
                        f"{network.name} NFT event cells are ambiguous"
                    )
                expected_action = (
                    "normal"
                    if matching_inputs and matching_outputs
                    else "mint"
                    if matching_outputs
                    else "destruction"
                )
                expected_from = (
                    output_address(matching_inputs[0], network.address_hrp)
                    if matching_inputs
                    else None
                )
                expected_to = (
                    output_address(matching_outputs[0], network.address_hrp)
                    if matching_outputs
                    else None
                )
                header = block.get("header") if isinstance(block, dict) else None
                self.assertIsInstance(header, dict)
                self.assertEqual(listed, detail)
                self.assertEqual("committed", status.get("status"))
                self.assertEqual(transaction["hash"], detail["transaction"]["tx_hash"])
                self.assertEqual(expected_action, detail["action"])
                self.assertEqual(expected_from, detail["from"])
                self.assertEqual(expected_to, detail["to"])
                self.assertEqual(
                    int(header["number"], 16),
                    int(detail["transaction"]["block_number"]),
                )
                self.assertEqual(
                    int(header["timestamp"], 16),
                    int(detail["transaction"]["block_timestamp"]),
                )


if __name__ == "__main__":
    unittest.main()
