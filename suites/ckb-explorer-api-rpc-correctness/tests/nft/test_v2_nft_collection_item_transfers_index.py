from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


COLLECTION_FIXTURES = {
    "mainnet": (9594, 9595),
    "testnet": (20139, 20225),
}


class V2NftCollectionItemTransfersIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _rows(
        self, oracle: NetworkOracle, path: str
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json(path)
        data = payload.get("data") if isinstance(payload, dict) else None
        pagination = payload.get("pagination") if isinstance(payload, dict) else None
        if (
            not isinstance(data, list)
            or any(not isinstance(row, dict) for row in data)
            or not isinstance(pagination, dict)
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} nested NFT transfer list is unavailable"
            )
        return data, pagination

    # TEST-MAP: NFT-TX-RPC-12
    @unittest.expectedFailure
    def test_nested_item_history_honors_item_and_collection_parents(self) -> None:
        failures: list[str] = []
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                collection_id, other_collection_id = COLLECTION_FIXTURES[network.name]
                try:
                    collection_rows, _ = self._rows(
                        oracle,
                        f"/v2/nft/collections/{collection_id}/transfers",
                    )
                    target = next(
                        row
                        for row in collection_rows
                        if sum(
                            candidate["item"]["id"] == row["item"]["id"]
                            for candidate in collection_rows
                        )
                        > 1
                    )
                    item_id = target["item"]["id"]
                    expected = [
                        row
                        for row in collection_rows
                        if row["item"]["id"] == item_id
                    ]
                    nested, nested_pagination = self._rows(
                        oracle,
                        f"/v2/nft/collections/{collection_id}/items/{item_id}/transfers",
                    )
                    wrong_parent, wrong_parent_pagination = self._rows(
                        oracle,
                        f"/v2/nft/collections/{other_collection_id}/items/{item_id}/transfers",
                    )
                    missing_item, missing_item_pagination = self._rows(
                        oracle,
                        f"/v2/nft/collections/{collection_id}/items/999999999/transfers",
                    )
                except (OracleUnavailable, StopIteration, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                if nested != expected or int(nested_pagination["count"]) != len(expected):
                    failures.append(
                        f"{network.name}: item {item_id} returned "
                        f"{nested_pagination['count']} collection events instead of {len(expected)}"
                    )
                if wrong_parent or int(wrong_parent_pagination["count"]) != 0:
                    failures.append(
                        f"{network.name}: mismatched collection returned "
                        f"{wrong_parent_pagination['count']} events"
                    )
                if missing_item or int(missing_item_pagination["count"]) != 0:
                    failures.append(
                        f"{network.name}: missing item returned "
                        f"{missing_item_pagination['count']} collection events"
                    )
        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
