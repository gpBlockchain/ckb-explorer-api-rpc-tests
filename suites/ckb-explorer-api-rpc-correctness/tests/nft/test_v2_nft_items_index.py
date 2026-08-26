from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


BURNT_COLLECTION_FIXTURES = {
    "mainnet": 9594,
    "testnet": 20074,
}

PAGED_COLLECTION_FIXTURES = {
    "mainnet": 9122,
    "testnet": 19633,
}


class V2NftItemsIndexRpcCorrectnessTests(unittest.TestCase):
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
                f"{oracle.network.name} NFT item page is unavailable"
            )
        return data, pagination

    # TEST-MAP: NFT-ITEM-RPC-05
    @unittest.expectedFailure
    def test_global_standard_partitions_return_only_live_chain_cells_and_exclude_burnt_item(self) -> None:
        partition_errors: list[str] = []
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    _unfiltered, unfiltered_pagination = self._page(
                        oracle, "/v2/nft/items"
                    )
                    partitions = {
                        standard: self._page(
                            oracle, "/v2/nft/items", {"standard": standard}
                        )
                        for standard in ("m_nft", "nrc721", "spore", "cota")
                    }
                    cell_items = [
                        item
                        for standard in ("m_nft", "nrc721", "spore")
                        for item in partitions[standard][0]
                    ]
                    live_results = oracle.rpc_batch_results(
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
                            for item in cell_items
                        ]
                    )
                    destruction_rows, _ = self._page(
                        oracle,
                        f"/v2/nft/collections/{BURNT_COLLECTION_FIXTURES[network.name]}/transfers",
                        {"transfer_action": "destruction"},
                    )
                    burnt = destruction_rows[0]["item"]
                    same_token, _ = self._page(
                        oracle,
                        "/v2/nft/items",
                        {"token_id": burnt["token_id"]},
                    )
                except (OracleUnavailable, IndexError, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                partition_total = sum(
                    int(pagination["count"])
                    for _rows, pagination in partitions.values()
                )
                if int(unfiltered_pagination["count"]) != partition_total:
                    partition_errors.append(
                        f"{network.name}: global count {unfiltered_pagination['count']} "
                        f"!= four-standard count {partition_total}"
                    )
                for standard, (rows, pagination) in partitions.items():
                    self.assertTrue(all(item["standard"] == standard for item in rows))
                    self.assertGreaterEqual(int(pagination["count"]), len(rows))
                for item, live_result in zip(cell_items, live_results):
                    self.assertEqual("live", live_result.get("status"))
                    cell = live_result.get("cell")
                    output = cell.get("output") if isinstance(cell, dict) else None
                    data = cell.get("data") if isinstance(cell, dict) else None
                    self.assertIsInstance(output, dict)
                    self.assertIsInstance(data, dict)
                    self.assertEqual("live", item["cell"]["status"])
                    self.assertEqual(data["content"], item["cell"]["data"])
                    self.assertEqual(
                        output["type"],
                        {
                            key: item["type_script"][key]
                            for key in ("code_hash", "hash_type", "args")
                        },
                    )
                    self.assertEqual(
                        output_address(output, network.address_hrp), item["owner"]
                    )
                    self.assertEqual(item["standard"], item["collection"]["standard"])
                self.assertEqual("dead", burnt["cell"]["status"])
                self.assertNotIn(int(burnt["id"]), {int(item["id"]) for item in same_token})
        self.assertEqual([], partition_errors)

    # TEST-MAP: NFT-ITEM-RPC-09
    @unittest.expectedFailure
    def test_global_and_collection_adjacent_and_overflow_pages_are_consistent(self) -> None:
        pagination_errors: list[str] = []
        for network in self.settings.networks:
            for path in (
                "/v2/nft/items",
                f"/v2/nft/collections/{PAGED_COLLECTION_FIXTURES[network.name]}/items",
            ):
                with self.subTest(network=network.name, path=path):
                    oracle = NetworkOracle(network, self.settings)
                    try:
                        first, first_pagination = self._page(
                            oracle, path, {"page": 1}
                        )
                        second, second_pagination = self._page(
                            oracle, path, {"page": 2}
                        )
                        repeated_first, _ = self._page(oracle, path, {"page": 1})
                        repeated_second, _ = self._page(oracle, path, {"page": 2})
                        overflow_page = int(first_pagination["pages"]) + 1
                        overflow, overflow_pagination = self._page(
                            oracle, path, {"page": overflow_page}
                        )
                    except (OracleUnavailable, ValueError, KeyError) as error:
                        raise unittest.SkipTest(str(error)) from error

                    first_ids = [int(item["id"]) for item in first]
                    second_ids = [int(item["id"]) for item in second]
                    token_ids = [int(item["token_id"]) for item in first + second]
                    self.assertEqual(first_ids, [int(item["id"]) for item in repeated_first])
                    self.assertEqual(second_ids, [int(item["id"]) for item in repeated_second])
                    duplicates = sorted(set(first_ids).intersection(second_ids))
                    if duplicates:
                        pagination_errors.append(
                            f"{network.name} {path}: adjacent-page duplicates {duplicates}"
                        )
                    self.assertEqual(sorted(token_ids), token_ids)
                    self.assertEqual(1, int(first_pagination["page"]))
                    self.assertEqual(2, int(second_pagination["page"]))
                    self.assertEqual(
                        first_pagination["count"], second_pagination["count"]
                    )
                    self.assertEqual(
                        first_pagination["pages"], second_pagination["pages"]
                    )
                    self.assertEqual(len(first), int(first_pagination["in"]))
                    self.assertEqual(len(second), int(second_pagination["in"]))
                    self.assertEqual([], overflow)
                    self.assertEqual(overflow_page, int(overflow_pagination["page"]))
                    if overflow_pagination["in"] != 0:
                        pagination_errors.append(
                            f"{network.name} {path}: overflow pagination.in="
                            f"{overflow_pagination['in']!r}"
                        )
                    self.assertEqual(
                        first_pagination["count"], overflow_pagination["count"]
                    )
        self.assertEqual([], pagination_errors)


if __name__ == "__main__":
    unittest.main()
