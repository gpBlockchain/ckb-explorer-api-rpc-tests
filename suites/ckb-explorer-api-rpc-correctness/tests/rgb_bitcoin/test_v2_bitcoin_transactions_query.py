from __future__ import annotations

import os
import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.http import HttpClientError, JsonHttpClient
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings


TRANSACTION_FIXTURES = {
    "mainnet": (
        "8a5de352e54e4e6ca3a6eee0732ea488e58d7bf1cff9ae3be50d38ea5b620afa",
        "21858ef435d096b21e116e67059c2bfa42ea20647beccc08e3dc1e18d6452698",
    ),
    "testnet": (
        "e2f3507cabda0f54e33800c9243e873598617c918ada963a7d048fcecffc17b5",
        "c0cd31146244e47b7035b1b96117963b2b2918944d641b5b04b88b4fe1fe60eb",
    ),
}
BITCOIN_RPC_URLS = {
    "mainnet": "https://bitcoin-rpc.publicnode.com",
    "testnet": "https://bitcoin-testnet-rpc.publicnode.com",
}
SIGNET_RPC_URL = "https://bitcoin-signet-rpc.publicnode.com"
SIGNET_TRANSACTION = "436bcf79ac698ba221f2f67ed7c9e42c5ddb6fb8b5f6f6322491f45bd08d8c97"
UNKNOWN_TRANSACTION = "00" * 32


class V2BitcoinTransactionsQueryRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.client = JsonHttpClient(
            timeout=max(cls.settings.timeout_seconds, 65),
            retries=cls.settings.transport_retries,
        )

    def _bitcoin_batch(
        self,
        network_name: str,
        txids: list[str],
        *,
        signet: bool = False,
    ) -> list[Mapping[str, Any]]:
        default_url = SIGNET_RPC_URL if signet else BITCOIN_RPC_URLS[network_name]
        env_name = "TESTNET_BITCOIN_SIGNET_RPC_URL" if signet else f"{network_name.upper()}_BITCOIN_RPC_URL"
        endpoint = os.getenv(env_name, default_url).rstrip("/")
        request = [
            {
                "jsonrpc": "1.0",
                "id": index + 1,
                "method": "getrawtransaction",
                "params": [txid, 2],
            }
            for index, txid in enumerate(txids)
        ]
        try:
            payload = self.client.request_json(endpoint, method="POST", json_body=request)
        except HttpClientError as error:
            raise OracleUnavailable(
                f"{network_name} Bitcoin RPC oracle is unavailable: {error}"
            ) from error
        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
            raise OracleUnavailable(
                f"{network_name} Bitcoin RPC oracle returned an invalid batch result"
            )
        return payload

    def _explorer(self, network: Any, txids: object) -> Mapping[str, Any]:
        oracle = NetworkOracle(network, self.settings)
        payload = oracle.client.request_json(
            network.explorer_api_url + "/v2/bitcoin_transactions",
            method="POST",
            headers=V1_HEADERS,
            json_body={"txids": txids},
        )
        self.assertIsInstance(payload, dict)
        return payload

    # TEST-MAP: BTC-QUERY-RPC-01
    # TEST-MAP: BTC-QUERY-RPC-02
    # TEST-MAP: BTC-QUERY-RPC-09
    def test_single_and_batch_results_match_same_network_bitcoin_rpc(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                txids = list(TRANSACTION_FIXTURES[network.name])
                try:
                    rpc_rows = self._bitcoin_batch(network.name, txids)
                    payload = self._explorer(network, txids)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer Bitcoin batch query failed: {error}")

                expected: dict[str, Mapping[str, Any]] = {}
                for row in rpc_rows:
                    result = row.get("result")
                    if not isinstance(result, dict) or not isinstance(result.get("txid"), str):
                        raise unittest.SkipTest(
                            f"{network.name} Bitcoin RPC fixture result is unavailable"
                        )
                    expected[result["txid"]] = result
                self.assertEqual(set(txids), set(payload))
                self.assertEqual(set(txids), set(expected))
                for txid in txids:
                    wrapper = payload[txid]
                    self.assertIsInstance(wrapper, dict)
                    self.assertIsNone(wrapper.get("error"))
                    self.assertEqual(txid, wrapper.get("result", {}).get("txid"))
                    self.assertEqual(expected[txid], wrapper["result"])

    # TEST-MAP: BTC-QUERY-RPC-03
    def test_successful_item_survives_unknown_and_rpc_error_items(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                valid_txid = TRANSACTION_FIXTURES[network.name][0]
                try:
                    rpc_rows = self._bitcoin_batch(
                        network.name,
                        [valid_txid, UNKNOWN_TRANSACTION, "not-a-txid"],
                    )
                    payload = self._explorer(
                        network,
                        [valid_txid, UNKNOWN_TRANSACTION, "not-a-txid"],
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer Bitcoin partial batch failed: {error}")
                successes = [row for row in rpc_rows if isinstance(row.get("result"), dict)]
                errors = [row for row in rpc_rows if row.get("error") is not None]
                self.assertEqual(1, len(successes))
                self.assertEqual(2, len(errors))
                self.assertEqual({valid_txid}, set(payload))
                self.assertEqual(successes[0]["result"], payload[valid_txid]["result"])

    # TEST-MAP: BTC-QUERY-RPC-04
    def test_duplicate_txid_produces_one_result(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                txid = TRANSACTION_FIXTURES[network.name][0]
                try:
                    payload = self._explorer(network, [txid, txid])
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer duplicate Bitcoin query failed: {error}")
                self.assertEqual([txid], list(payload))
                self.assertEqual(txid, payload[txid]["result"]["txid"])

    # TEST-MAP: BTC-QUERY-RPC-05
    @unittest.expectedFailure
    def test_testnet_merges_signet_success_with_testnet_fallback(self) -> None:
        network = next(item for item in self.settings.networks if item.name == "testnet")
        fallback_txid = TRANSACTION_FIXTURES["testnet"][0]
        try:
            signet_rows = self._bitcoin_batch("testnet", [SIGNET_TRANSACTION], signet=True)
            fallback_rows = self._bitcoin_batch("testnet", [fallback_txid])
            payload = self._explorer(network, [SIGNET_TRANSACTION, fallback_txid])
        except (OracleUnavailable, HttpClientError) as error:
            raise unittest.SkipTest(str(error)) from error
        self.assertIsInstance(signet_rows[0].get("result"), dict)
        self.assertIsInstance(fallback_rows[0].get("result"), dict)
        self.assertEqual({SIGNET_TRANSACTION, fallback_txid}, set(payload))
        self.assertEqual(signet_rows[0]["result"], payload[SIGNET_TRANSACTION]["result"])
        self.assertEqual(fallback_rows[0]["result"], payload[fallback_txid]["result"])

    # TEST-MAP: BTC-QUERY-RPC-06
    def test_all_rpc_errors_return_empty_success_object(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                try:
                    rpc_rows = self._bitcoin_batch(
                        network.name,
                        [UNKNOWN_TRANSACTION, "not-a-txid"],
                    )
                    payload = self._explorer(
                        network,
                        [UNKNOWN_TRANSACTION, "not-a-txid"],
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer all-error Bitcoin batch failed: {error}")
                self.assertTrue(all(row.get("error") is not None for row in rpc_rows))
                self.assertEqual({}, payload)

    # TEST-MAP: BTC-QUERY-RPC-08
    def test_missing_or_non_array_txids_returns_404_empty_object(self) -> None:
        for network in self.settings.networks:
            for body in ({}, {"txids": "not-an-array"}):
                with self.subTest(network=network.name, body=body):
                    oracle = NetworkOracle(network, self.settings)
                    with self.assertRaises(HttpClientError) as raised:
                        oracle.client.request_json(
                            network.explorer_api_url + "/v2/bitcoin_transactions",
                            method="POST",
                            headers=V1_HEADERS,
                            json_body=body,
                        )
                    self.assertIn("returned HTTP 404: {}", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
