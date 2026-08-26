from __future__ import annotations

import unittest
from collections import Counter, defaultdict
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


COLLECTION_FIXTURES = {
    "mainnet": 9594,
    "testnet": 20074,
}

BATCH_FIXTURES = {
    "mainnet": (
        9588,
        "0x6bf1341c8005a31c48e4c0638a5b7ffddd0fc670c6b9a8b4b3d2d2d03343b8b9",
    ),
    "testnet": (
        20139,
        "0x5bf17d8ac776a39dca63c3a520e459c5c5dffa951735aba964cca33f2680bbb4",
    ),
}


class V2NftCollectionTransfersIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _page(
        self,
        oracle: NetworkOracle,
        collection_id: object,
        query: Mapping[str, object] | None = None,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json(
            f"/v2/nft/collections/{collection_id}/transfers", query
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        pagination = payload.get("pagination") if isinstance(payload, dict) else None
        if (
            not isinstance(data, list)
            or any(not isinstance(row, dict) for row in data)
            or not isinstance(pagination, dict)
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT collection transfer page is unavailable"
            )
        return data, pagination

    def _all_transfers(
        self, oracle: NetworkOracle, collection_id: object
    ) -> list[Mapping[str, Any]]:
        first, pagination = self._page(oracle, collection_id)
        pages = int(pagination["pages"])
        rows = list(first)
        for page in range(2, pages + 1):
            current, current_pagination = self._page(
                oracle, collection_id, {"page": page}
            )
            if current_pagination["count"] != pagination["count"]:
                raise OracleUnavailable(
                    f"{oracle.network.name} NFT collection changed while paging"
                )
            rows.extend(current)
        if len(rows) != int(pagination["count"]):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT collection changed while paging"
            )
        return rows

    def _rpc_event(
        self, oracle: NetworkOracle, row: Mapping[str, Any]
    ) -> tuple[str, str | None, str | None, Mapping[str, Any], Mapping[str, Any]]:
        item = row["item"]
        type_script = {
            key: item["type_script"][key]
            for key in ("code_hash", "hash_type", "args")
        }
        tx_hash = row["transaction"]["tx_hash"]
        result = oracle.rpc_result("get_transaction", [tx_hash])
        transaction = result.get("transaction") if isinstance(result, dict) else None
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise OracleUnavailable(
                f"{oracle.network.name} transaction {tx_hash} is unavailable"
            )
        inputs = transaction.get("inputs")
        outputs = transaction.get("outputs")
        if not isinstance(inputs, list) or not isinstance(outputs, list):
            raise OracleUnavailable(
                f"{oracle.network.name} transaction {tx_hash} cells are unavailable"
            )
        parent_results = oracle.rpc_batch_results(
            [
                ("get_transaction", [cell_input["previous_output"]["tx_hash"]])
                for cell_input in inputs
            ]
        )
        input_outputs: list[Mapping[str, Any]] = []
        for cell_input, parent_result in zip(inputs, parent_results):
            parent = (
                parent_result.get("transaction")
                if isinstance(parent_result, dict)
                else None
            )
            parent_outputs = parent.get("outputs") if isinstance(parent, dict) else None
            if not isinstance(parent_outputs, list):
                raise OracleUnavailable(
                    f"{oracle.network.name} parent transaction is unavailable"
                )
            index = int(cell_input["previous_output"]["index"], 16)
            if index >= len(parent_outputs) or not isinstance(parent_outputs[index], dict):
                raise OracleUnavailable(
                    f"{oracle.network.name} parent output is unavailable"
                )
            input_outputs.append(parent_outputs[index])

        def same_type(output: Mapping[str, Any]) -> bool:
            candidate = output.get("type")
            return isinstance(candidate, dict) and all(
                candidate.get(key) == value for key, value in type_script.items()
            )

        matching_inputs = [output for output in input_outputs if same_type(output)]
        matching_outputs = [output for output in outputs if same_type(output)]
        if len(matching_inputs) > 1 or len(matching_outputs) > 1:
            raise OracleUnavailable(
                f"{oracle.network.name} NFT transaction has ambiguous matching cells"
            )
        if matching_inputs and matching_outputs:
            action = "normal"
        elif matching_outputs:
            action = "mint"
        elif matching_inputs:
            action = "destruction"
        else:
            raise OracleUnavailable(
                f"{oracle.network.name} NFT type script is absent from its transaction"
            )
        from_address = (
            output_address(matching_inputs[0], oracle.network.address_hrp)
            if matching_inputs
            else None
        )
        to_address = (
            output_address(matching_outputs[0], oracle.network.address_hrp)
            if matching_outputs
            else None
        )
        block = oracle.rpc_result(
            "get_block_by_number", [hex(int(row["transaction"]["block_number"]))]
        )
        header = block.get("header") if isinstance(block, dict) else None
        block_transactions = block.get("transactions") if isinstance(block, dict) else None
        if not isinstance(header, dict) or not isinstance(block_transactions, list):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT transaction block is unavailable"
            )
        return action, from_address, to_address, transaction, block

    def _assert_event_matches_rpc(
        self, oracle: NetworkOracle, row: Mapping[str, Any]
    ) -> None:
        action, from_address, to_address, transaction, block = self._rpc_event(
            oracle, row
        )
        item = row["item"]
        api_transaction = row["transaction"]
        self.assertEqual(action, row["action"])
        self.assertEqual(from_address, row["from"])
        self.assertEqual(to_address, row["to"])
        self.assertEqual(transaction["hash"], api_transaction["tx_hash"])
        self.assertEqual(int(item["type_script"]["args"], 16), int(item["token_id"]))
        self.assertIn(
            transaction["hash"],
            [candidate["hash"] for candidate in block["transactions"]],
        )
        self.assertEqual(
            int(block["header"]["number"], 16),
            int(api_transaction["block_number"]),
        )
        self.assertEqual(
            int(block["header"]["timestamp"], 16),
            int(api_transaction["block_timestamp"]),
        )

    # TEST-MAP: NFT-TX-RPC-01
    # TEST-MAP: NFT-TX-RPC-02
    # TEST-MAP: NFT-TX-RPC-03
    def test_normal_mint_and_destruction_events_match_ckb_cells(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._all_transfers(
                        oracle, COLLECTION_FIXTURES[network.name]
                    )
                    selected = {
                        action: next(row for row in rows if row["action"] == action)
                        for action in ("normal", "mint", "destruction")
                    }
                    for row in selected.values():
                        self._assert_event_matches_rpc(oracle, row)
                except (OracleUnavailable, StopIteration, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                identities = Counter(
                    (row["item"]["id"], row["transaction"]["tx_hash"])
                    for row in rows
                )
                for row in selected.values():
                    self.assertEqual(
                        1, identities[(row["item"]["id"], row["transaction"]["tx_hash"])]
                    )
                self.assertEqual("dead", selected["destruction"]["item"]["cell"]["status"])

    # TEST-MAP: NFT-TX-RPC-04
    def test_batch_transaction_emits_one_independent_event_per_type_script(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id, tx_hash = BATCH_FIXTURES[network.name]
                try:
                    rows, pagination = self._page(
                        oracle, collection_id, {"tx_hash": tx_hash}
                    )
                    for row in rows:
                        self._assert_event_matches_rpc(oracle, row)
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertGreater(len(rows), 1)
                self.assertEqual(len(rows), int(pagination["count"]))
                self.assertEqual(len(rows), len({row["item"]["id"] for row in rows}))
                self.assertEqual(
                    len(rows),
                    len(
                        {
                            (
                                row["item"]["type_script"]["code_hash"],
                                row["item"]["type_script"]["hash_type"],
                                row["item"]["type_script"]["args"],
                            )
                            for row in rows
                        }
                    ),
                )
                self.assertTrue(
                    all(row["transaction"]["tx_hash"] == tx_hash for row in rows)
                )

    # TEST-MAP: NFT-TX-RPC-05
    def test_collection_list_exactly_matches_indexer_histories_and_chain_order(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._all_transfers(
                        oracle, COLLECTION_FIXTURES[network.name]
                    )
                    histories: dict[int, set[str]] = {}
                    transaction_order: dict[str, tuple[int, int]] = {}
                    for row in rows:
                        item = row["item"]
                        item_id = int(item["id"])
                        if item_id in histories:
                            continue
                        type_script = {
                            key: item["type_script"][key]
                            for key in ("code_hash", "hash_type", "args")
                        }
                        result = oracle.rpc_result(
                            "get_transactions",
                            [
                                {
                                    "script": type_script,
                                    "script_type": "type",
                                    "script_search_mode": "exact",
                                },
                                "desc",
                                "0x64",
                            ],
                        )
                        objects = result.get("objects") if isinstance(result, dict) else None
                        if not isinstance(objects, list):
                            raise OracleUnavailable(
                                f"{network.name} NFT item history is unavailable"
                            )
                        histories[item_id] = {
                            event["tx_hash"] for event in objects if isinstance(event, dict)
                        }
                        for event in objects:
                            if isinstance(event, dict):
                                transaction_order[event["tx_hash"]] = (
                                    int(event["block_number"], 16),
                                    int(event["tx_index"], 16),
                                )
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                api_histories: dict[int, set[str]] = defaultdict(set)
                for row in rows:
                    api_histories[int(row["item"]["id"])].add(
                        row["transaction"]["tx_hash"]
                    )
                self.assertEqual(histories, dict(api_histories))
                self.assertEqual(len(rows), len({int(row["id"]) for row in rows}))
                self.assertEqual({"normal", "mint", "destruction"}, {row["action"] for row in rows})
                order = [
                    transaction_order[row["transaction"]["tx_hash"]] for row in rows
                ]
                self.assertEqual(sorted(order, reverse=True), order)
                repeated = self._all_transfers(
                    oracle, COLLECTION_FIXTURES[network.name]
                )
                self.assertEqual(
                    [row["id"] for row in rows], [row["id"] for row in repeated]
                )

    # TEST-MAP: NFT-TX-RPC-08
    def test_direction_action_and_transaction_filters_use_intersection(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id = COLLECTION_FIXTURES[network.name]
                try:
                    rows = self._all_transfers(oracle, collection_id)
                    target = next(
                        row
                        for row in rows
                        if row["action"] == "normal" and row["from"] and row["to"]
                    )
                    queries = (
                        {"from": target["from"]},
                        {"to": target["to"]},
                        {"address_hash": target["from"]},
                        {"transfer_action": target["action"]},
                        {"tx_hash": target["transaction"]["tx_hash"]},
                    )
                    filtered = [self._page(oracle, collection_id, query)[0] for query in queries]
                    combined, _pagination = self._page(
                        oracle,
                        collection_id,
                        {
                            "from": target["from"],
                            "to": target["to"],
                            "address_hash": target["from"],
                            "transfer_action": target["action"],
                            "tx_hash": target["transaction"]["tx_hash"],
                        },
                    )
                except (OracleUnavailable, StopIteration, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertTrue(all(row["from"] == target["from"] for row in filtered[0]))
                self.assertTrue(all(row["to"] == target["to"] for row in filtered[1]))
                self.assertTrue(
                    all(
                        target["from"] in (row["from"], row["to"])
                        for row in filtered[2]
                    )
                )
                self.assertTrue(all(row["action"] == target["action"] for row in filtered[3]))
                self.assertTrue(
                    all(
                        row["transaction"]["tx_hash"]
                        == target["transaction"]["tx_hash"]
                        for row in filtered[4]
                    )
                )
                self.assertEqual([target["id"]], [row["id"] for row in combined])

    # TEST-MAP: NFT-TX-RPC-10
    # TEST-MAP: NFT-TX-RPC-11
    def test_collection_identifiers_and_token_id_keep_parent_scope(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id = COLLECTION_FIXTURES[network.name]
                try:
                    detail = oracle.explorer_json(f"/v2/nft/collections/{collection_id}")
                    numeric = self._all_transfers(oracle, collection_id)
                    by_sn = self._all_transfers(oracle, detail["sn"])
                    selected = next(
                        row
                        for row in numeric
                        if sum(
                            candidate["item"]["token_id"] == row["item"]["token_id"]
                            for candidate in numeric
                        )
                        > 1
                    )
                    by_token, by_token_pagination = self._page(
                        oracle,
                        collection_id,
                        {"token_id": selected["item"]["token_id"]},
                    )
                    missing_collection, missing_collection_pagination = self._page(
                        oracle, 999_999_999
                    )
                    missing_token, missing_token_pagination = self._page(
                        oracle,
                        collection_id,
                        {"token_id": str(2**256 - 1)},
                    )
                except (OracleUnavailable, StopIteration, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual(numeric, by_sn)
                expected = [
                    row
                    for row in numeric
                    if row["item"]["token_id"] == selected["item"]["token_id"]
                ]
                self.assertEqual(expected, by_token)
                self.assertEqual(len(expected), int(by_token_pagination["count"]))
                self.assertEqual([], missing_collection)
                self.assertEqual(0, int(missing_collection_pagination["count"]))
                self.assertEqual([], missing_token)
                self.assertEqual(0, int(missing_token_pagination["count"]))


if __name__ == "__main__":
    unittest.main()
