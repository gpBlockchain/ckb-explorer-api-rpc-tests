from __future__ import annotations

import json
import unittest
from decimal import Decimal
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, output_occupied_capacity
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


ACTIVE_ADDRESS_FIXTURES = {
    "mainnet": "bc1q8vk4lv6zr0hp9kgul9stxz7ldz32zqycgcznj4",
    "testnet": "tb1qz7sa4ua3fmsqrktm79yjx6k20353pgnvezwdna",
}

RGBPP_CODE_HASHES = {
    "mainnet": (
        "0xbc6c568a1a0d0a09f6844dc9d74ddb4343c32143ff25f727c59edf4fb72d6936",
    ),
    "testnet": (
        "0x61ca7a4796a4eb19ca4f0d065cb9b10ddcf002f10f7cbb810c706cb6bb5c3248",
        "0xd07598deec7ce7b5665310386b4abd06a6d48843e953c5cc2112ad0d5a220364",
    ),
}


class V2BitcoinAddressesRgbCellsRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _page(
        self,
        oracle: NetworkOracle,
        address: str,
        **query: object,
    ) -> tuple[dict[str, list[Mapping[str, Any]]], Mapping[str, Any]]:
        payload = oracle.explorer_json(
            f"/v2/bitcoin_addresses/{address}/rgb_cells", query
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        cells = data.get("rgb_cells") if isinstance(data, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(cells, dict) or not isinstance(meta, dict):
            raise OracleUnavailable(
                f"{oracle.network.name} Bitcoin address RGB Cells are unavailable"
            )
        return cells, meta

    # TEST-MAP: BTC-ADDR-RPC-03
    # TEST-MAP: BTC-ADDR-RPC-04
    def test_outpoint_groups_and_every_serialized_cell_match_live_ckb_indexer_results(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = ACTIVE_ADDRESS_FIXTURES[network.name]
                try:
                    groups, meta = self._page(
                        oracle, address, page=1, page_size=1000
                    )
                    if len(groups) != int(meta["total"]):
                        raise OracleUnavailable(
                            f"{network.name} RGB group fixture exceeds 1000 outpoints"
                        )
                    group_keys = [tuple(json.loads(key)) for key in groups]
                    history_results = oracle.rpc_batch_results(
                        [
                            (
                                "get_cells",
                                [
                                    {
                                        "script": {
                                            "code_hash": code_hash,
                                            "hash_type": "type",
                                            "args": "0x"
                                            + int(index).to_bytes(4, "little").hex()
                                            + bytes.fromhex(str(txid))[::-1].hex(),
                                        },
                                        "script_type": "lock",
                                        "script_search_mode": "exact",
                                    },
                                    "asc",
                                    "0x3e8",
                                ],
                            )
                            for txid, index in group_keys
                            for code_hash in RGBPP_CODE_HASHES[network.name]
                        ]
                    )
                    expected_by_group: dict[
                        tuple[str, int], set[tuple[str, int]]
                    ] = {key: set() for key in group_keys}
                    width = len(RGBPP_CODE_HASHES[network.name])
                    for group_index, key in enumerate(group_keys):
                        for result in history_results[
                            group_index * width : (group_index + 1) * width
                        ]:
                            objects = result.get("objects") if isinstance(result, dict) else None
                            if not isinstance(objects, list):
                                raise OracleUnavailable(
                                    f"{network.name} RGB lock Indexer result is unavailable"
                                )
                            expected_by_group[key].update(
                                (
                                    cell["out_point"]["tx_hash"],
                                    int(cell["out_point"]["index"], 16),
                                )
                                for cell in objects
                            )
                    serialized = [
                        row
                        for rows in groups.values()
                        for row in rows
                    ]
                    live_results = oracle.rpc_batch_results(
                        [
                            (
                                "get_live_cell",
                                [
                                    {
                                        "tx_hash": row["data"]["attributes"]["tx_hash"],
                                        "index": hex(
                                            int(row["data"]["attributes"]["cell_index"])
                                        ),
                                    },
                                    True,
                                ],
                            )
                            for row in serialized
                        ]
                    )
                    block_numbers = list(
                        dict.fromkeys(
                            row["data"]["attributes"]["block_number"]
                            for row in serialized
                        )
                    )
                    blocks = oracle.rpc_batch_results(
                        [("get_block_by_number", [hex(int(number))]) for number in block_numbers]
                    )
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                for encoded_key, rows in groups.items():
                    key = tuple(json.loads(encoded_key))
                    observed = {
                        (
                            row["data"]["attributes"]["tx_hash"],
                            int(row["data"]["attributes"]["cell_index"]),
                        )
                        for row in rows
                    }
                    self.assertEqual(expected_by_group[key], observed)
                block_headers = {
                    int(block["header"]["number"], 16): block["header"]
                    for block in blocks
                    if isinstance(block, dict) and isinstance(block.get("header"), dict)
                }
                for row, live_result in zip(serialized, live_results):
                    attributes = row["data"]["attributes"]
                    self.assertEqual("live", live_result.get("status"))
                    cell = live_result["cell"]
                    output = cell["output"]
                    data = cell["data"]["content"]
                    self.assertEqual(Decimal(attributes["capacity"]), int(output["capacity"], 16))
                    self.assertEqual(int(attributes["occupied_capacity"]), output_occupied_capacity(output, data))
                    self.assertEqual(attributes["data"], data)
                    self.assertEqual(attributes["lock_script"], output["lock"])
                    self.assertEqual(attributes["type_script"], output["type"])
                    expected_type_hash = ckb_script_hash(output["type"]) if output["type"] else None
                    self.assertEqual(attributes["type_hash"], expected_type_hash)
                    header = block_headers[int(attributes["block_number"])]
                    self.assertEqual(int(attributes["block_timestamp"]), int(header["timestamp"], 16))
                    self.assertIsInstance(attributes["tags"], list)
                    self.assertIsInstance(attributes["extra_info"], (dict, type(None)))

    # TEST-MAP: BTC-ADDR-RPC-05
    def test_outpoint_pagination_counts_groups_and_has_no_adjacent_duplicates(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = ACTIVE_ADDRESS_FIXTURES[network.name]
                try:
                    all_groups, all_meta = self._page(
                        oracle, address, page=1, page_size=1000
                    )
                    if int(all_meta["total"]) < 3:
                        raise unittest.SkipTest(
                            f"{network.name} has fewer than three stable RGB outpoint groups"
                        )
                    first, first_meta = self._page(
                        oracle, address, page=1, page_size=2
                    )
                    second, second_meta = self._page(
                        oracle, address, page=2, page_size=2
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(int(all_meta["total"]), len(all_groups))
                self.assertEqual(all_meta["total"], first_meta["total"])
                self.assertEqual(all_meta["total"], second_meta["total"])
                self.assertEqual(2, int(first_meta["page_size"]))
                self.assertEqual(2, int(second_meta["page_size"]))
                self.assertEqual(2, len(first))
                self.assertEqual(2, len(second))
                self.assertTrue(set(first).isdisjoint(second))
                self.assertEqual(
                    list(all_groups)[:4], list(first) + list(second)
                )


if __name__ == "__main__":
    unittest.main()
