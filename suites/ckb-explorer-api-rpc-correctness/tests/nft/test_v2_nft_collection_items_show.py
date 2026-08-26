from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import output_address
from ckb_rpc_correctness.http import HttpClientError
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings


ITEM_FIXTURES = {
    "mainnet": {
        "m_nft": 9041,
        "nrc721": 9122,
        "spore": 9595,
        "did": 9137,
    },
    "testnet": {
        "m_nft": 18639,
        "nrc721": 1,
        "spore": 20225,
        "did": 18887,
    },
}


class V2NftCollectionItemsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _first_item(
        self, oracle: NetworkOracle, collection_id: object
    ) -> Mapping[str, Any]:
        payload = oracle.explorer_json(
            f"/v2/nft/collections/{collection_id}/items"
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT collection item fixture is unavailable"
            )
        return data[0]

    def _detail(
        self, oracle: NetworkOracle, collection_id: object, token_id: object
    ) -> Mapping[str, Any]:
        payload = oracle.explorer_json(
            f"/v2/nft/collections/{collection_id}/items/{token_id}"
        )
        if not isinstance(payload, dict):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT item detail is unavailable"
            )
        return payload

    # TEST-MAP: NFT-ITEM-RPC-01
    # TEST-MAP: NFT-ITEM-RPC-02
    def test_standard_token_ids_and_detail_cells_match_live_ckb_outputs(self) -> None:
        for network in self.settings.networks:
            for standard, collection_id in ITEM_FIXTURES[network.name].items():
                with self.subTest(network=network.name, standard=standard):
                    oracle = NetworkOracle(network, self.settings)
                    try:
                        listed = self._first_item(oracle, collection_id)
                        detail = self._detail(
                            oracle, collection_id, listed["token_id"]
                        )
                        live_result = oracle.rpc_result(
                            "get_live_cell",
                            [
                                {
                                    "tx_hash": detail["cell"]["tx_hash"],
                                    "index": hex(int(detail["cell"]["cell_index"])),
                                },
                                True,
                            ],
                        )
                    except (OracleUnavailable, ValueError, KeyError) as error:
                        raise unittest.SkipTest(str(error)) from error

                    self.assertEqual(listed, detail)
                    self.assertEqual("live", live_result.get("status"))
                    cell = live_result.get("cell")
                    output = cell.get("output") if isinstance(cell, dict) else None
                    data = cell.get("data") if isinstance(cell, dict) else None
                    self.assertIsInstance(output, dict)
                    self.assertIsInstance(data, dict)
                    self.assertEqual("live", detail["cell"]["status"])
                    self.assertEqual(data["content"], detail["cell"]["data"])
                    self.assertEqual(
                        output["type"],
                        {
                            key: detail["type_script"][key]
                            for key in ("code_hash", "hash_type", "args")
                        },
                    )
                    self.assertEqual(
                        output_address(output, network.address_hrp), detail["owner"]
                    )
                    self.assertEqual(standard if standard != "did" else "spore", detail["standard"])
                    self.assertEqual(int(collection_id), int(detail["collection"]["id"]))

                    args = detail["type_script"]["args"]
                    if standard == "m_nft":
                        expected_token_id = int(args[50:], 16)
                    elif standard == "nrc721":
                        expected_token_id = int(args[132:], 16)
                    else:
                        expected_token_id = int(args, 16)
                    self.assertEqual(expected_token_id, int(detail["token_id"]))

    # TEST-MAP: NFT-ITEM-RPC-06
    def test_numeric_and_sn_collection_paths_return_the_same_list_and_detail(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id = ITEM_FIXTURES[network.name]["spore"]
                try:
                    collection = oracle.explorer_json(
                        f"/v2/nft/collections/{collection_id}"
                    )
                    numeric_list = oracle.explorer_json(
                        f"/v2/nft/collections/{collection_id}/items"
                    )
                    sn_list = oracle.explorer_json(
                        f"/v2/nft/collections/{collection['sn']}/items"
                    )
                    token_id = numeric_list["data"][0]["token_id"]
                    numeric_detail = self._detail(oracle, collection_id, token_id)
                    sn_detail = self._detail(oracle, collection["sn"], token_id)
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(numeric_list["data"], sn_list["data"])
                for field in ("count", "page", "pages", "items", "in"):
                    self.assertEqual(
                        numeric_list["pagination"][field],
                        sn_list["pagination"][field],
                    )
                self.assertEqual(numeric_detail, sn_detail)
                self.assertEqual(collection["sn"], numeric_detail["collection"]["sn"])

    # TEST-MAP: NFT-ITEM-RPC-10
    def test_decimal_hexadecimal_and_zero_padded_token_ids_are_equivalent(self) -> None:
        for network in self.settings.networks:
            for protocol in ("spore", "did"):
                with self.subTest(network=network.name, protocol=protocol):
                    oracle = NetworkOracle(network, self.settings)
                    collection_id = ITEM_FIXTURES[network.name][protocol]
                    try:
                        item = self._first_item(oracle, collection_id)
                        token_id = int(item["token_id"])
                        decimal = self._detail(oracle, collection_id, str(token_id))
                        hexadecimal = self._detail(
                            oracle, collection_id, hex(token_id)
                        )
                        padded = self._detail(
                            oracle,
                            collection_id,
                            "0x0000" + format(token_id, "x"),
                        )
                    except (OracleUnavailable, ValueError, KeyError) as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(decimal, hexadecimal)
                    self.assertEqual(decimal, padded)
                    self.assertEqual(token_id, int(decimal["token_id"]))

    # TEST-MAP: NFT-ITEM-RPC-11
    def test_equal_token_ids_remain_isolated_by_parent_collection(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    global_zero = oracle.explorer_json(
                        "/v2/nft/items", {"token_id": "0"}
                    )
                    zero_items = global_zero["data"]
                    first, second = next(
                        (left, right)
                        for left in zero_items
                        for right in zero_items
                        if left["collection"]["id"] != right["collection"]["id"]
                    )
                    first_detail = self._detail(
                        oracle, first["collection"]["id"], 0
                    )
                    second_detail = self._detail(
                        oracle, second["collection"]["id"], 0
                    )
                    spore = self._first_item(
                        oracle, ITEM_FIXTURES[network.name]["spore"]
                    )
                    missing_url = (
                        network.explorer_api_url
                        + f"/v2/nft/collections/{first['collection']['id']}"
                        + f"/items/{spore['token_id']}"
                    )
                    with self.assertRaises(HttpClientError) as missing_error:
                        oracle.client.request_json(missing_url, headers=V1_HEADERS)
                except (OracleUnavailable, StopIteration, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual(0, int(first_detail["token_id"]))
                self.assertEqual(0, int(second_detail["token_id"]))
                self.assertEqual(
                    int(first["collection"]["id"]),
                    int(first_detail["collection"]["id"]),
                )
                self.assertEqual(
                    int(second["collection"]["id"]),
                    int(second_detail["collection"]["id"]),
                )
                self.assertNotEqual(first_detail["id"], second_detail["id"])
                self.assertIn("returned HTTP 404:", str(missing_error.exception))

    # TEST-MAP: NFT-ITEM-RPC-14
    def test_missing_collection_and_token_paths_return_404_without_item_data(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id = ITEM_FIXTURES[network.name]["spore"]
                urls = (
                    network.explorer_api_url
                    + "/v2/nft/collections/999999999/items",
                    network.explorer_api_url
                    + "/v2/nft/collections/0x"
                    + "00" * 32
                    + "/items",
                    network.explorer_api_url
                    + f"/v2/nft/collections/{collection_id}/items/{2**256 - 1}",
                )
                for url in urls:
                    with self.subTest(url=url):
                        with self.assertRaises(HttpClientError) as error:
                            oracle.client.request_json(url, headers=V1_HEADERS)
                        self.assertIn("returned HTTP 404:", str(error.exception))


if __name__ == "__main__":
    unittest.main()
