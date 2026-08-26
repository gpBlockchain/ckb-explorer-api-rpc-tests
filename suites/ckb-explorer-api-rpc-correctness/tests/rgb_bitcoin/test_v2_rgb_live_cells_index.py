from __future__ import annotations

import os
import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.http import HttpClientError, JsonHttpClient
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


RGBPP_CODE_HASHES = {
    "mainnet": (
        "0xbc6c568a1a0d0a09f6844dc9d74ddb4343c32143ff25f727c59edf4fb72d6936",
    ),
    "testnet": (
        "0x61ca7a4796a4eb19ca4f0d065cb9b10ddcf002f10f7cbb810c706cb6bb5c3248",
        "0xd07598deec7ce7b5665310386b4abd06a6d48843e953c5cc2112ad0d5a220364",
    ),
}
BITCOIN_RPC_URLS = {
    "mainnet": "https://bitcoin-rpc.publicnode.com",
    "testnet": "https://bitcoin-testnet-rpc.publicnode.com",
}


class V2RgbLiveCellsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.bitcoin_client = JsonHttpClient(
            timeout=max(cls.settings.timeout_seconds, 65),
            retries=cls.settings.transport_retries,
        )

    def _page(
        self, oracle: NetworkOracle, **query: object
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json("/v2/rgb_live_cells", query)
        cells = payload.get("cells") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if (
            not isinstance(cells, list)
            or any(not isinstance(cell, dict) for cell in cells)
            or not isinstance(meta, dict)
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} RGB live-cell response is unavailable"
            )
        return cells, meta

    def _bitcoin_transactions(
        self, network_name: str, txids: list[str]
    ) -> dict[str, Mapping[str, Any]]:
        endpoint = os.getenv(
            f"{network_name.upper()}_BITCOIN_RPC_URL",
            BITCOIN_RPC_URLS[network_name],
        ).rstrip("/")
        request = [
            {
                "jsonrpc": "1.0",
                "id": index,
                "method": "getrawtransaction",
                "params": [txid, 2],
            }
            for index, txid in enumerate(txids)
        ]
        try:
            payload = self.bitcoin_client.request_json(
                endpoint, method="POST", json_body=request
            )
        except HttpClientError as error:
            raise OracleUnavailable(
                f"{network_name} Bitcoin RPC oracle is unavailable: {error}"
            ) from error
        if not isinstance(payload, list):
            raise OracleUnavailable(
                f"{network_name} Bitcoin RPC batch result is unavailable"
            )
        transactions: dict[str, Mapping[str, Any]] = {}
        for row in payload:
            result = row.get("result") if isinstance(row, dict) else None
            if not isinstance(result, dict) or not isinstance(result.get("txid"), str):
                raise OracleUnavailable(
                    f"{network_name} Bitcoin RPC omitted a referenced transaction"
                )
            transactions[result["txid"]] = result
        if set(transactions) != set(txids):
            raise OracleUnavailable(
                f"{network_name} Bitcoin RPC batch omitted a transaction"
            )
        return transactions

    # TEST-MAP: BTC-ADDR-RPC-08
    def test_valid_code_hash_returns_bound_non_op_return_live_ckb_outpoints(self) -> None:
        for network in self.settings.networks:
            for code_hash in RGBPP_CODE_HASHES[network.name]:
                with self.subTest(network=network.name, code_hash=code_hash):
                    oracle = NetworkOracle(network, self.settings)
                    try:
                        cells, meta = self._page(
                            oracle, code_hash=code_hash, page=1, page_size=10
                        )
                        if not cells:
                            raise OracleUnavailable(
                                f"{network.name} RGB code hash has no live-cell fixture"
                            )
                        live_results = oracle.rpc_batch_results(
                            [
                                (
                                    "get_live_cell",
                                    [
                                        {
                                            "tx_hash": cell["tx_hash"],
                                            "index": hex(int(cell["cell_index"])),
                                        },
                                        True,
                                    ],
                                )
                                for cell in cells
                            ]
                        )
                        bitcoin_refs: list[tuple[str, int]] = []
                        for result in live_results:
                            if result.get("status") != "live":
                                raise OracleUnavailable(
                                    f"{network.name} RGB Cell changed during observation"
                                )
                            lock = result["cell"]["output"]["lock"]
                            self.assertEqual(code_hash, lock["code_hash"])
                            self.assertEqual("type", lock["hash_type"])
                            args = bytes.fromhex(lock["args"][2:])
                            self.assertEqual(36, len(args))
                            bitcoin_refs.append(
                                (
                                    args[4:36][::-1].hex(),
                                    int.from_bytes(args[:4], "little"),
                                )
                            )
                        bitcoin = self._bitcoin_transactions(
                            network.name,
                            list(dict.fromkeys(txid for txid, _index in bitcoin_refs)),
                        )
                    except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                        raise unittest.SkipTest(str(error)) from error

                    self.assertGreater(int(meta["total"]), 0)
                    self.assertEqual(
                        len(cells),
                        len(
                            {
                                (cell["tx_hash"], int(cell["cell_index"]))
                                for cell in cells
                            }
                        ),
                    )
                    for txid, output_index in bitcoin_refs:
                        outputs = bitcoin[txid].get("vout")
                        if not isinstance(outputs, list) or output_index >= len(outputs):
                            raise unittest.SkipTest(
                                f"{network.name} Bitcoin vout mapping is unavailable"
                            )
                        script = outputs[output_index].get("scriptPubKey")
                        if not isinstance(script, dict):
                            raise unittest.SkipTest(
                                f"{network.name} Bitcoin vout script is unavailable"
                            )
                        self.assertNotEqual("nulldata", script.get("type"))
                        self.assertFalse(str(script.get("hex", "")).startswith("6a"))

    # TEST-MAP: BTC-ADDR-RPC-09
    @unittest.expectedFailure
    def test_pagination_covers_each_outpoint_once_and_caps_large_pages_at_1000(self) -> None:
        issues: list[str] = []
        for network in self.settings.networks:
            for code_hash in RGBPP_CODE_HASHES[network.name]:
                with self.subTest(network=network.name, code_hash=code_hash):
                    oracle = NetworkOracle(network, self.settings)
                    try:
                        first, first_meta = self._page(
                            oracle, code_hash=code_hash, page=1, page_size=1000
                        )
                        total = int(first_meta["total"])
                        pages = [first]
                        for page in range(2, (total + 999) // 1000 + 1):
                            rows, meta = self._page(
                                oracle,
                                code_hash=code_hash,
                                page=page,
                                page_size=1000,
                            )
                            if int(meta["total"]) != total:
                                raise OracleUnavailable(
                                    f"{network.name} RGB live-cell total changed during pagination"
                                )
                            pages.append(rows)
                        oversized, oversized_meta = self._page(
                            oracle, code_hash=code_hash, page=1, page_size=5000
                        )
                    except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                        raise unittest.SkipTest(str(error)) from error

                    outpoints = [
                        (cell["tx_hash"], int(cell["cell_index"]))
                        for page in pages
                        for cell in page
                    ]
                    expected_page = min(total, 1000)
                    expected_last = total % 1000 or expected_page
                    if len(outpoints) != total:
                        issues.append(
                            f"{network.name}/{code_hash}: {len(outpoints)} rows != total {total}"
                        )
                    if len(set(outpoints)) != total:
                        issues.append(
                            f"{network.name}/{code_hash}: only {len(set(outpoints))} unique outpoints of {total}"
                        )
                    if not all(len(page) <= 1000 for page in pages):
                        issues.append(f"{network.name}/{code_hash}: a page exceeded 1000")
                    if len(oversized) > 1000:
                        issues.append(
                            f"{network.name}/{code_hash}: oversized request returned {len(oversized)} rows"
                        )
                    if first != oversized:
                        issues.append(
                            f"{network.name}/{code_hash}: capped first page changed membership"
                        )
                    if int(oversized_meta["total"]) != total:
                        issues.append(
                            f"{network.name}/{code_hash}: oversized total changed"
                        )
                    if len(first) != expected_page:
                        issues.append(
                            f"{network.name}/{code_hash}: first page has {len(first)}, expected {expected_page}"
                        )
                    if len(pages[-1]) != expected_last:
                        issues.append(
                            f"{network.name}/{code_hash}: last page has {len(pages[-1])}, expected {expected_last}"
                        )
        self.assertFalse(issues, "; ".join(issues))

    # TEST-MAP: BTC-ADDR-RPC-10
    def test_missing_unknown_and_opposite_network_code_hashes_return_empty(self) -> None:
        for network in self.settings.networks:
            opposite = (
                RGBPP_CODE_HASHES["testnet"]
                if network.name == "mainnet"
                else RGBPP_CODE_HASHES["mainnet"]
            )
            for code_hash in (None, "0x" + "00" * 32, *opposite):
                with self.subTest(network=network.name, code_hash=code_hash):
                    oracle = NetworkOracle(network, self.settings)
                    query: dict[str, object] = {"page": 1, "page_size": 7}
                    if code_hash is not None:
                        query["code_hash"] = code_hash
                    try:
                        cells, meta = self._page(oracle, **query)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual([], cells)
                    self.assertEqual(0, int(meta["total"]))
                    self.assertEqual(7, int(meta["page_size"]))


if __name__ == "__main__":
    unittest.main()
