from __future__ import annotations

import unittest
from collections import Counter
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import output_address
from ckb_rpc_correctness.http import HttpClientError
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings


HOLDER_FIXTURES = {
    "mainnet": (
        9594,
        "0xc45df9bb746a2b9949ee6081bec51d74c3dea3205691cbde3126234f7fdb130c",
    ),
    "testnet": (
        20139,
        "0x0c89317ba333d960e3ecf46c2e5b48e47f2a224e349bd7259c45999dbecea284",
    ),
}


class V2NftCollectionHoldersIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _holders(
        self,
        oracle: NetworkOracle,
        collection_id: object,
        query: Mapping[str, object] | None = None,
    ) -> Mapping[str, int]:
        payload = oracle.explorer_json(
            f"/v2/nft/collections/{collection_id}/holders", query
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or any(
            not isinstance(address, str) or not isinstance(quantity, int)
            for address, quantity in data.items()
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT holder mapping is unavailable"
            )
        return data

    def _items(
        self, oracle: NetworkOracle, collection_id: object
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json(
            f"/v2/nft/collections/{collection_id}/items"
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        pagination = payload.get("pagination") if isinstance(payload, dict) else None
        if (
            not isinstance(data, list)
            or any(not isinstance(item, dict) for item in data)
            or not isinstance(pagination, dict)
        ):
            raise OracleUnavailable(f"{oracle.network.name} NFT item list is unavailable")
        return data, pagination

    # TEST-MAP: NFT-COLL-RPC-05
    # TEST-MAP: NFT-COLL-RPC-12
    def test_holder_quantities_and_collection_statistics_match_live_item_cells(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                numeric_id, _type_hash = HOLDER_FIXTURES[network.name]
                oracle = NetworkOracle(network, self.settings)
                try:
                    detail = oracle.explorer_json(
                        f"/v2/nft/collections/{numeric_id}"
                    )
                    items, pagination = self._items(oracle, numeric_id)
                    holders = self._holders(oracle, numeric_id)
                    tip = oracle.rpc_result("get_tip_header", [])
                    live_cells = oracle.rpc_batch_results(
                        [
                            (
                                "get_live_cell",
                                [
                                    {
                                        "tx_hash": item["cell"]["tx_hash"],
                                        "index": hex(int(item["cell"]["cell_index"])),
                                    },
                                    True,
                                ],
                            )
                            for item in items
                        ]
                    )
                    newest_events: list[Mapping[str, Any]] = []
                    for item in items:
                        type_script = item["type_script"]
                        result = oracle.rpc_result(
                            "get_transactions",
                            [
                                {
                                    "script": {
                                        key: type_script[key]
                                        for key in ("code_hash", "hash_type", "args")
                                    },
                                    "script_type": "type",
                                    "script_search_mode": "exact",
                                },
                                "desc",
                                "0x1",
                            ],
                        )
                        events = result.get("objects") if isinstance(result, dict) else None
                        if not isinstance(events, list) or not events:
                            raise OracleUnavailable(
                                f"{network.name} NFT item history is unavailable"
                            )
                        newest_events.append(events[0])
                    event_blocks = oracle.rpc_batch_results(
                        [
                            ("get_block_by_number", [block_number])
                            for block_number in dict.fromkeys(
                                event["block_number"] for event in newest_events
                            )
                        ]
                    )
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertIsInstance(detail, dict)
                self.assertIsInstance(tip, dict)
                self.assertEqual(len(items), int(pagination["count"]))
                expected_holders = Counter(str(item["owner"]) for item in items)
                self.assertEqual(dict(expected_holders), holders)
                self.assertEqual(len(items), int(detail["items_count"]))
                self.assertEqual(len(expected_holders), int(detail["holders_count"]))
                self.assertEqual(len(items), sum(holders.values()))
                for item, live_result in zip(items, live_cells):
                    self.assertEqual("live", live_result.get("status"))
                    cell = live_result.get("cell")
                    output = cell.get("output") if isinstance(cell, dict) else None
                    self.assertIsInstance(output, dict)
                    self.assertEqual(
                        item["owner"], output_address(output, network.address_hrp)
                    )

                threshold = int(tip["timestamp"], 16) - 24 * 60 * 60 * 1000
                for block in event_blocks:
                    header = block.get("header") if isinstance(block, dict) else None
                    if not isinstance(header, dict):
                        raise unittest.SkipTest(
                            f"{network.name} NFT history block is unavailable"
                        )
                    self.assertLess(int(header["timestamp"], 16), threshold)
                self.assertEqual(0, int(detail["h24_ckb_transactions_count"]))

    # TEST-MAP: NFT-COLL-RPC-13
    def test_numeric_and_type_hash_identifiers_match_and_owner_filter_is_exact(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                numeric_id, type_hash = HOLDER_FIXTURES[network.name]
                oracle = NetworkOracle(network, self.settings)
                try:
                    numeric = self._holders(oracle, numeric_id)
                    hashed = self._holders(oracle, type_hash)
                    owner = max(numeric, key=numeric.get)
                    filtered = self._holders(
                        oracle, numeric_id, {"address_hash": owner}
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(numeric, hashed)
                self.assertEqual({owner: numeric[owner]}, filtered)

    # TEST-MAP: NFT-COLL-RPC-14
    def test_quantity_sort_orders_distinct_holder_counts(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                numeric_id, _type_hash = HOLDER_FIXTURES[network.name]
                oracle = NetworkOracle(network, self.settings)
                try:
                    ascending = self._holders(
                        oracle, numeric_id, {"sort": "quantity.asc"}
                    )
                    descending = self._holders(
                        oracle, numeric_id, {"sort": "quantity.desc"}
                    )
                    repeated = self._holders(
                        oracle, numeric_id, {"sort": "quantity.desc"}
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertGreater(len(set(ascending.values())), 1)
                self.assertEqual(sorted(ascending.values()), list(ascending.values()))
                self.assertEqual(
                    sorted(descending.values(), reverse=True),
                    list(descending.values()),
                )
                self.assertEqual(ascending, descending)
                self.assertEqual(descending, repeated)

    # TEST-MAP: NFT-COLL-RPC-15
    def test_missing_collection_identifiers_preserve_detail_and_holder_404_contracts(self) -> None:
        identifiers = (999_999_999, "0x" + "00" * 32)
        for network in self.settings.networks:
            for identifier in identifiers:
                with self.subTest(network=network.name, identifier=identifier):
                    oracle = NetworkOracle(network, self.settings)
                    with self.assertRaises(HttpClientError) as detail_error:
                        oracle.client.request_json(
                            network.explorer_api_url
                            + f"/v2/nft/collections/{identifier}",
                            headers=V1_HEADERS,
                        )
                    self.assertIn("returned HTTP 404:", str(detail_error.exception))
                    with self.assertRaises(HttpClientError) as holder_error:
                        oracle.client.request_json(
                            network.explorer_api_url
                            + f"/v2/nft/collections/{identifier}/holders",
                            headers=V1_HEADERS,
                        )
                    message = str(holder_error.exception)
                    self.assertIn("returned HTTP 404:", message)
                    self.assertIn('"code":2001', message)
                    self.assertIn('"title":"token collection not found"', message)


if __name__ == "__main__":
    unittest.main()
