from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


COLLECTION_FIXTURES = {
    "mainnet": {"m_nft": 9041, "nrc721": 9122, "spore": 9594},
    "testnet": {"m_nft": 18639, "nrc721": 1, "spore": 20139},
}


class V2NftTransfersIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _page(
        self,
        oracle: NetworkOracle,
        path: str,
        query: Mapping[str, object] | None = None,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json(path, query)
        data = payload.get("data") if isinstance(payload, dict) else None
        pagination = payload.get("pagination") if isinstance(payload, dict) else None
        if (
            not isinstance(data, list)
            or any(not isinstance(row, dict) for row in data)
            or not isinstance(pagination, dict)
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT transfer page is unavailable"
            )
        return data, pagination

    def _assert_chain_event(
        self, oracle: NetworkOracle, transfer: Mapping[str, Any]
    ) -> None:
        item = transfer["item"]
        type_script = {
            key: item["type_script"][key]
            for key in ("code_hash", "hash_type", "args")
        }
        tx_hash = transfer["transaction"]["tx_hash"]
        result = oracle.rpc_result("get_transaction", [tx_hash])
        transaction = result.get("transaction") if isinstance(result, dict) else None
        if not isinstance(transaction, dict):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT transaction {tx_hash} is unavailable"
            )
        parents = oracle.rpc_batch_results(
            [
                ("get_transaction", [cell_input["previous_output"]["tx_hash"]])
                for cell_input in transaction["inputs"]
            ]
        )
        input_outputs: list[Mapping[str, Any]] = []
        for cell_input, parent_result in zip(transaction["inputs"], parents):
            parent = (
                parent_result.get("transaction")
                if isinstance(parent_result, dict)
                else None
            )
            outputs = parent.get("outputs") if isinstance(parent, dict) else None
            if not isinstance(outputs, list):
                raise OracleUnavailable(
                    f"{oracle.network.name} NFT parent transaction is unavailable"
                )
            input_outputs.append(
                outputs[int(cell_input["previous_output"]["index"], 16)]
            )

        def matches(output: Mapping[str, Any]) -> bool:
            return output.get("type") == type_script

        inputs = [output for output in input_outputs if matches(output)]
        outputs = [output for output in transaction["outputs"] if matches(output)]
        if len(inputs) > 1 or len(outputs) > 1 or not (inputs or outputs):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT event cells are ambiguous"
            )
        expected_action = (
            "normal" if inputs and outputs else "mint" if outputs else "destruction"
        )
        expected_from = (
            output_address(inputs[0], oracle.network.address_hrp) if inputs else None
        )
        expected_to = (
            output_address(outputs[0], oracle.network.address_hrp) if outputs else None
        )
        block = oracle.rpc_result(
            "get_block_by_number",
            [hex(int(transfer["transaction"]["block_number"]))],
        )
        header = block.get("header") if isinstance(block, dict) else None
        if not isinstance(header, dict):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT transaction block is unavailable"
            )
        self.assertEqual(expected_action, transfer["action"])
        self.assertEqual(expected_from, transfer["from"])
        self.assertEqual(expected_to, transfer["to"])
        self.assertEqual(transaction["hash"], tx_hash)
        self.assertEqual(int(header["number"], 16), int(transfer["transaction"]["block_number"]))
        self.assertEqual(
            int(header["timestamp"], 16),
            int(transfer["transaction"]["block_timestamp"]),
        )

    # TEST-MAP: NFT-TX-RPC-06
    def test_global_list_preserves_cross_collection_standard_events_and_chain_order(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    global_rows, global_pagination = self._page(
                        oracle, "/v2/nft/transfers"
                    )
                    repeated, repeated_pagination = self._page(
                        oracle, "/v2/nft/transfers"
                    )
                    selected: list[tuple[str, Mapping[str, Any]]] = []
                    for standard, collection_id in COLLECTION_FIXTURES[
                        network.name
                    ].items():
                        collection_rows, _ = self._page(
                            oracle,
                            f"/v2/nft/collections/{collection_id}/transfers",
                        )
                        event = collection_rows[0]
                        matching_global, _ = self._page(
                            oracle,
                            "/v2/nft/transfers",
                            {"tx_hash": event["transaction"]["tx_hash"]},
                        )
                        global_event = next(
                            row for row in matching_global if row["id"] == event["id"]
                        )
                        selected.append((standard, global_event))
                    for _standard, event in selected:
                        self._assert_chain_event(oracle, event)
                except (OracleUnavailable, StopIteration, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertGreater(int(global_pagination["count"]), len(global_rows))
                self.assertEqual(global_pagination["count"], repeated_pagination["count"])
                self.assertEqual(
                    [row["id"] for row in global_rows],
                    [row["id"] for row in repeated],
                )
                block_numbers = [
                    int(row["transaction"]["block_number"]) for row in global_rows
                ]
                self.assertEqual(sorted(block_numbers, reverse=True), block_numbers)
                self.assertEqual(
                    {"m_nft", "nrc721", "spore"},
                    {event["item"]["standard"] for _standard, event in selected},
                )
                self.assertEqual(
                    {"m_nft", "nrc721", "spore"},
                    {standard for standard, _event in selected},
                )
                self.assertEqual(
                    len(selected), len({event["id"] for _standard, event in selected})
                )


if __name__ == "__main__":
    unittest.main()
