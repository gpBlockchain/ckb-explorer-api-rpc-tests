from __future__ import annotations

import hashlib
import json
import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import LockScript, ckb2021_address, ckb_script_hash, output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.nft.test_v2_nft_collection_items_show import ITEM_FIXTURES
from tests.portfolio.http import portfolio_response
from tests.portfolio.test_v2_portfolio_sessions_create import MESSAGE, SECP_CODE_HASH, SIGNATURE


FOURTH_PUBLIC_KEY = "0x02e493dbf1c10d80f3581e4904930b1404cc6c13900ee0758474fa94abe8c4cd13"
UNPUBLISHED_UDTS = {
    "mainnet": (
        "0xf6857309b1703340af7af202ea6b2de0c5d0921528e285b8189dabebaf6ccc69",
        "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqtymv970v90yaynwh6argfux63rvkynh5qq38spy",
    ),
    "testnet": (
        "0xd539846e1c27c12696f26165434ceaabd4a741350dda8fdf4a320b496c7f440c",
        "ckt1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq0rdytdfup6zyeste62kx39clvegsn7mss7d6sej",
    ),
}


class V2PortfolioUdtAccountsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _session(self, oracle: NetworkOracle) -> str:
        args = "0x" + hashlib.blake2b(
            bytes.fromhex(FOURTH_PUBLIC_KEY[2:]), digest_size=32, person=b"ckb-default-hash"
        ).digest()[:20].hex()
        address = ckb2021_address(LockScript(SECP_CODE_HASH, "type", args), oracle.network.address_hrp)
        status, raw = portfolio_response(
            oracle,
            "/v2/portfolio/sessions",
            method="POST",
            json_body={
                "address": address,
                "message": MESSAGE,
                "signature": SIGNATURE,
                "pub_key": FOURTH_PUBLIC_KEY,
            },
        )
        if status != 200:
            raise OracleUnavailable(f"{oracle.network.name} Portfolio login returned HTTP {status}")
        return str(json.loads(raw)["jwt"])

    def _cells(self, oracle: NetworkOracle, script: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        core = {key: script[key] for key in ("args", "code_hash", "hash_type")}
        search_key = {"script": core, "script_type": "type", "script_search_mode": "exact"}
        cells: list[Mapping[str, Any]] = []
        cursor: str | None = None
        for _page in range(100):
            params: list[object] = [search_key, "asc", "0x64"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result("get_cells", params)
            objects = result.get("objects") if isinstance(result, dict) else None
            if not isinstance(objects, list) or any(not isinstance(cell, dict) for cell in objects):
                raise OracleUnavailable(f"{oracle.network.name} Indexer UDT cells are unavailable")
            cells.extend(objects)
            if len(objects) < 100:
                return cells
            next_cursor = result.get("last_cursor")
            if not isinstance(next_cursor, str) or next_cursor == cursor:
                raise OracleUnavailable(f"{oracle.network.name} Indexer UDT cursor is unavailable")
            cursor = next_cursor
        raise OracleUnavailable(f"{oracle.network.name} UDT cells exceeded 100 pages")

    def _published_fixture(
        self, oracle: NetworkOracle
    ) -> tuple[Mapping[str, Any], list[Mapping[str, Any]], list[str]]:
        payload = oracle.explorer_json("/v1/udts", {"page": 1, "page_size": 100})
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise OracleUnavailable(f"{oracle.network.name} UDT catalog is unavailable")
        for item in data:
            attributes = item.get("attributes") if isinstance(item, dict) else None
            script = attributes.get("type_script") if isinstance(attributes, dict) else None
            if attributes.get("published") is not True or not isinstance(script, dict):
                continue
            cells = self._cells(oracle, script)
            owners = list(dict.fromkeys(output_address(cell["output"], oracle.network.address_hrp) for cell in cells))
            if len(owners) >= 2:
                return attributes, cells, owners[:2]
        raise OracleUnavailable(f"{oracle.network.name} two-holder published sUDT is unavailable")

    def _sync(self, oracle: NetworkOracle, token: str, addresses: list[str]) -> None:
        status, raw = portfolio_response(
            oracle,
            "/v2/portfolio/addresses",
            method="POST",
            json_body={"addresses": addresses},
            token=token,
        )
        if status != 204:
            raise OracleUnavailable(f"{oracle.network.name} Portfolio address sync returned HTTP {status}: {raw[:200]!r}")

    # TEST-MAP: PORTFOLIO-ASSET-RPC-06
    @unittest.expectedFailure  # The controller passes nil explicitly, so the default query returns no published accounts.
    def test_sudt_accounts_merge_rpc_amounts_and_apply_publication_filters(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    token = self._session(oracle)
                    published, cells, owners = self._published_fixture(oracle)
                    unpublished_hash, unpublished_owner = UNPUBLISHED_UDTS[network.name]
                    self._sync(oracle, token, owners + [unpublished_owner])
                    default = portfolio_response(oracle, "/v2/portfolio/udt_accounts?cell_type=sudt", token=token)
                    visible = portfolio_response(
                        oracle, "/v2/portfolio/udt_accounts?cell_type=sudt&published=true", token=token
                    )
                    hidden = portfolio_response(
                        oracle, "/v2/portfolio/udt_accounts?cell_type=sudt&published=false", token=token
                    )
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual([200, 200, 200], [default[0], visible[0], hidden[0]])
                visible_rows = json.loads(visible[1])
                hidden_rows = json.loads(hidden[1])
                actual = next(row for row in visible_rows if row["type_hash"] == published["type_hash"])
                expected = sum(
                    int.from_bytes(bytes.fromhex(str(cell["output_data"])[2:])[:16], "little")
                    for cell in cells
                    if output_address(cell["output"], network.address_hrp) in owners
                )
                self.assertEqual(expected, int(actual["amount"]))
                self.assertEqual(str(expected), actual["amount"])
                self.assertIsInstance(actual["decimal"], str)
                self.assertEqual(1, sum(row["type_hash"] == published["type_hash"] for row in visible_rows))
                self.assertTrue(all(row["type_hash"] != unpublished_hash for row in visible_rows))
                self.assertIn(unpublished_hash, {row["type_hash"] for row in hidden_rows})
                self.assertTrue(all(row["type_hash"] != published["type_hash"] for row in hidden_rows))
                self.assertEqual(visible_rows, json.loads(default[1]))

    # TEST-MAP: PORTFOLIO-ASSET-RPC-07
    @unittest.expectedFailure  # Both public servers return HTTP 500 while aggregating the four tracked NFT branches.
    def test_nft_branches_preserve_rpc_identity_token_ids_and_optional_collection_data(self) -> None:
        expected_types = {
            "m_nft": "m_nft_token",
            "nrc721": "nrc_721_token",
            "spore": "spore_cell",
            "did": "did_cell",
        }
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    token = self._session(oracle)
                    items = {
                        standard: oracle.explorer_json(f"/v2/nft/collections/{collection_id}/items")["data"][0]
                        for standard, collection_id in ITEM_FIXTURES[network.name].items()
                    }
                    self._sync(oracle, token, list(dict.fromkeys(str(item["owner"]) for item in items.values())))
                    live = {
                        standard: oracle.rpc_result(
                            "get_live_cell",
                            [{"tx_hash": item["cell"]["tx_hash"], "index": hex(int(item["cell"]["cell_index"]))}, True],
                        )
                        for standard, item in items.items()
                    }
                    status, raw = portfolio_response(oracle, "/v2/portfolio/udt_accounts?cell_type=nft", token=token)
                except (OracleUnavailable, KeyError, TypeError, ValueError, IndexError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(200, status)
                rows = [row for row in json.loads(raw) if isinstance(row, dict)]
                for standard, item in items.items():
                    cell = live[standard].get("cell") if isinstance(live[standard], dict) else None
                    output = cell.get("output") if isinstance(cell, dict) else None
                    self.assertEqual("live", live[standard].get("status"))
                    self.assertIsInstance(output, dict)
                    self.assertEqual(item["owner"], output_address(output, network.address_hrp))
                    self.assertEqual(item["type_script"]["script_hash"], ckb_script_hash(output["type"]))
                    matches = [row for row in rows if row.get("type_hash") == item["type_script"]["script_hash"]]
                    self.assertEqual(1, len(matches))
                    account = matches[0]
                    self.assertEqual(expected_types[standard], account["udt_type"])
                    self.assertEqual(str(item["token_id"]), account["amount"])
                    self.assertIsInstance(account.get("collection"), dict)
                    self.assertIn("type_hash", account["collection"])


if __name__ == "__main__":
    unittest.main()
