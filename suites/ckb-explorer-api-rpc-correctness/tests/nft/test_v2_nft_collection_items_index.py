from __future__ import annotations

import unittest
from collections import Counter
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


COLLECTION_FIXTURES = {
    "mainnet": 9594,
    "testnet": 20074,
}


class V2NftCollectionItemsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _all_pages(
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
        rows = list(data)
        pages = int(pagination["pages"])
        for page in range(2, pages + 1):
            page_query = dict(query or {})
            page_query["page"] = page
            current = oracle.explorer_json(path, page_query)
            current_data = current.get("data") if isinstance(current, dict) else None
            current_pagination = (
                current.get("pagination") if isinstance(current, dict) else None
            )
            if (
                not isinstance(current_data, list)
                or not isinstance(current_pagination, dict)
                or current_pagination.get("count") != pagination.get("count")
            ):
                raise OracleUnavailable(
                    f"{oracle.network.name} NFT item collection changed while paging"
                )
            rows.extend(current_data)
        if len(rows) != int(pagination["count"]):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT item collection changed while paging"
            )
        return rows, pagination

    # TEST-MAP: NFT-ITEM-RPC-03
    # TEST-MAP: NFT-ITEM-RPC-04
    def test_collection_membership_and_current_cells_match_live_type_scripts(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id = COLLECTION_FIXTURES[network.name]
                item_path = f"/v2/nft/collections/{collection_id}/items"
                transfer_path = f"/v2/nft/collections/{collection_id}/transfers"
                try:
                    detail = oracle.explorer_json(
                        f"/v2/nft/collections/{collection_id}"
                    )
                    items, pagination = self._all_pages(oracle, item_path)
                    transfers, _transfer_pagination = self._all_pages(
                        oracle, transfer_path
                    )
                    current_cells = oracle.rpc_batch_results(
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
                    transfer_items = {
                        int(row["item"]["id"]): row["item"] for row in transfers
                    }
                    live_by_type = oracle.rpc_batch_results(
                        [
                            (
                                "get_cells",
                                [
                                    {
                                        "script": {
                                            key: item["type_script"][key]
                                            for key in ("code_hash", "hash_type", "args")
                                        },
                                        "script_type": "type",
                                        "script_search_mode": "exact",
                                    },
                                    "asc",
                                    "0x2",
                                ],
                            )
                            for item in transfer_items.values()
                        ]
                    )
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                expected_live_ids = {
                    item_id
                    for (item_id, _item), result in zip(
                        transfer_items.items(), live_by_type
                    )
                    if isinstance(result.get("objects"), list)
                    and result["objects"]
                }
                self.assertEqual(expected_live_ids, {int(item["id"]) for item in items})
                self.assertEqual(len(items), int(pagination["count"]))
                self.assertEqual(len(items), int(detail["items_count"]))
                self.assertTrue(
                    any(row["action"] == "mint" for row in transfers)
                )
                self.assertTrue(
                    any(row["action"] == "normal" for row in transfers)
                )
                burnt_ids = {
                    int(row["item"]["id"])
                    for row in transfers
                    if row["action"] == "destruction"
                }
                self.assertTrue(burnt_ids)
                self.assertTrue(burnt_ids.isdisjoint(expected_live_ids))

                for item, live_result in zip(items, current_cells):
                    self.assertEqual("live", live_result.get("status"))
                    cell = live_result.get("cell")
                    output = cell.get("output") if isinstance(cell, dict) else None
                    data = cell.get("data") if isinstance(cell, dict) else None
                    self.assertIsInstance(output, dict)
                    self.assertIsInstance(data, dict)
                    self.assertEqual("live", item["cell"]["status"])
                    self.assertEqual(item["cell"]["data"], data["content"])
                    self.assertEqual(
                        {
                            key: item["type_script"][key]
                            for key in ("code_hash", "hash_type", "args")
                        },
                        output["type"],
                    )
                    self.assertEqual(
                        item["owner"], output_address(output, network.address_hrp)
                    )
                    self.assertEqual(int(collection_id), int(item["collection"]["id"]))
                    self.assertEqual(detail["sn"], item["collection"]["sn"])
                    self.assertEqual(detail["standard"], item["standard"])

    # TEST-MAP: NFT-ITEM-RPC-07
    def test_owner_standard_and_token_filters_are_exact_intersections(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id = COLLECTION_FIXTURES[network.name]
                path = f"/v2/nft/collections/{collection_id}/items"
                try:
                    items, _pagination = self._all_pages(oracle, path)
                    owner = Counter(item["owner"] for item in items).most_common(1)[0][0]
                    target = next(item for item in items if item["owner"] == owner)
                    standard = target["standard"]
                    by_owner, _ = self._all_pages(oracle, path, {"owner": owner})
                    by_standard, _ = self._all_pages(
                        oracle, path, {"standard": standard}
                    )
                    by_token, _ = self._all_pages(
                        oracle, path, {"token_id": target["token_id"]}
                    )
                    combined, _ = self._all_pages(
                        oracle,
                        path,
                        {
                            "owner": owner,
                            "standard": standard,
                            "token_id": target["token_id"],
                        },
                    )
                    other_standard, other_pagination = self._all_pages(
                        oracle,
                        path,
                        {"standard": "nrc721" if standard != "nrc721" else "spore"},
                    )
                except (OracleUnavailable, StopIteration, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual(
                    {int(item["id"]) for item in items if item["owner"] == owner},
                    {int(item["id"]) for item in by_owner},
                )
                self.assertEqual(items, by_standard)
                self.assertEqual([target["id"]], [item["id"] for item in by_token])
                self.assertEqual([target["id"]], [item["id"] for item in combined])
                self.assertEqual([], other_standard)
                self.assertEqual(0, int(other_pagination["count"]))

    # TEST-MAP: NFT-ITEM-RPC-08
    def test_large_token_ids_are_sorted_numerically_and_repeat_stably(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id = COLLECTION_FIXTURES[network.name]
                path = f"/v2/nft/collections/{collection_id}/items"
                try:
                    items, _pagination = self._all_pages(oracle, path)
                    repeated, _repeated_pagination = self._all_pages(oracle, path)
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                token_ids = [int(item["token_id"]) for item in items]
                self.assertGreater(len(token_ids), 1)
                self.assertTrue(any(token_id > 2**64 for token_id in token_ids))
                self.assertEqual(sorted(token_ids), token_ids)
                self.assertEqual(
                    [item["id"] for item in items],
                    [item["id"] for item in repeated],
                )


if __name__ == "__main__":
    unittest.main()
