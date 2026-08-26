from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.http import HttpClientError
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings


COLLECTION_FIXTURES = {
    "mainnet": (9594, 9595),
    "testnet": (20139, 20225),
}


class V2NftCollectionItemTransfersShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _first_transfer(
        self, oracle: NetworkOracle, collection_id: int
    ) -> Mapping[str, Any]:
        payload = oracle.explorer_json(
            f"/v2/nft/collections/{collection_id}/transfers"
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT transfer fixture is unavailable"
            )
        return data[0]

    # TEST-MAP: NFT-TX-RPC-13
    @unittest.expectedFailure
    def test_nested_transfer_detail_rejects_mismatched_collection_and_item_parents(self) -> None:
        failures: list[str] = []
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id, other_collection_id = COLLECTION_FIXTURES[network.name]
                try:
                    transfer = self._first_transfer(oracle, collection_id)
                    item_id = transfer["item"]["id"]
                    transfer_id = transfer["id"]
                    valid = oracle.explorer_json(
                        f"/v2/nft/collections/{collection_id}/items/{item_id}"
                        f"/transfers/{transfer_id}"
                    )
                    wrong_collection = oracle.explorer_json(
                        f"/v2/nft/collections/{other_collection_id}/items/{item_id}"
                        f"/transfers/{transfer_id}"
                    )
                    wrong_item = oracle.explorer_json(
                        f"/v2/nft/collections/{collection_id}/items/999999999"
                        f"/transfers/{transfer_id}"
                    )
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(transfer, valid)
                if wrong_collection == transfer:
                    failures.append(
                        f"{network.name}: transfer {transfer_id} ignored collection parent"
                    )
                if wrong_item == transfer:
                    failures.append(
                        f"{network.name}: transfer {transfer_id} ignored item parent"
                    )
        self.assertEqual([], failures)

    # TEST-MAP: NFT-TX-RPC-15
    def test_missing_nested_transfer_id_returns_404(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id, _other_collection_id = COLLECTION_FIXTURES[network.name]
                try:
                    transfer = self._first_transfer(oracle, collection_id)
                    item_id = transfer["item"]["id"]
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                url = (
                    network.explorer_api_url
                    + f"/v2/nft/collections/{collection_id}/items/{item_id}"
                    + "/transfers/999999999"
                )
                with self.assertRaises(HttpClientError) as error:
                    oracle.client.request_json(url, headers=V1_HEADERS)
                self.assertIn("returned HTTP 404:", str(error.exception))


if __name__ == "__main__":
    unittest.main()
