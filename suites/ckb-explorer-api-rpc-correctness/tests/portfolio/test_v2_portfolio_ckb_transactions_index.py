from __future__ import annotations

import json
import unittest
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import LockScript, ckb2021_address, ckb_script_hash, decode_hex_int, output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import ACTIVITY_TRANSACTIONS, DAO_ADDRESSES
from tests.nft.test_v2_nft_collection_items_show import ITEM_FIXTURES
from tests.portfolio.http import portfolio_response
from tests.portfolio.test_v2_portfolio_sessions_create import MESSAGE, SECP_CODE_HASH, SIGNATURE, SIGNER_ARGS


class V2PortfolioCkbTransactionsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _fixture(self, oracle: NetworkOracle) -> tuple[str, list[str]]:
        address = ckb2021_address(LockScript(SECP_CODE_HASH, "type", SIGNER_ARGS), oracle.network.address_hrp)
        status, raw = portfolio_response(
            oracle,
            "/v2/portfolio/sessions",
            method="POST",
            json_body={"address": address, "message": MESSAGE, "signature": SIGNATURE},
        )
        if status != 200:
            raise OracleUnavailable(f"{oracle.network.name} Portfolio login returned HTTP {status}")
        token = str(json.loads(raw)["jwt"])
        result = oracle.rpc_result("get_transaction", [ACTIVITY_TRANSACTIONS[oracle.network.name]])
        transaction = result.get("transaction") if isinstance(result, dict) else None
        outputs = transaction.get("outputs") if isinstance(transaction, dict) else None
        if not isinstance(outputs, list) or not outputs or not isinstance(outputs[0], dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC activity transaction is unavailable")
        addresses = [output_address(outputs[0], oracle.network.address_hrp), DAO_ADDRESSES[oracle.network.name]]
        sync_status, sync_raw = portfolio_response(
            oracle,
            "/v2/portfolio/addresses",
            method="POST",
            json_body={"addresses": addresses},
            token=token,
        )
        if sync_status != 204:
            raise OracleUnavailable(
                f"{oracle.network.name} Portfolio address sync returned HTTP {sync_status}: {sync_raw[:200]!r}"
            )
        return token, addresses

    def _income(self, oracle: NetworkOracle, tx_hash: str, addresses: list[str]) -> int:
        target_locks: set[str] = set()
        for address in addresses:
            payload = oracle.explorer_json(f"/v1/addresses/{address}")
            lock = payload["data"][0]["attributes"]["lock_script"]
            target_locks.add(ckb_script_hash(lock))
        result = oracle.rpc_result("get_transaction", [tx_hash])
        transaction = result["transaction"]
        output_capacity = sum(
            decode_hex_int(output["capacity"], "output.capacity")
            for output in transaction["outputs"]
            if ckb_script_hash(output["lock"]) in target_locks
        )
        previous = oracle.rpc_batch_results(
            [("get_transaction", [item["previous_output"]["tx_hash"]]) for item in transaction["inputs"]]
        )
        input_capacity = 0
        for item, previous_result in zip(transaction["inputs"], previous, strict=True):
            index = decode_hex_int(item["previous_output"]["index"], "input.index")
            output = previous_result["transaction"]["outputs"][index]
            if ckb_script_hash(output["lock"]) in target_locks:
                input_capacity += decode_hex_int(output["capacity"], "input.capacity")
        return output_capacity - input_capacity

    # TEST-MAP: PORTFOLIO-ASSET-RPC-08
    @unittest.expectedFailure  # Both public transaction-list routes currently return HTTP 500 before serialization.
    def test_committed_multi_address_transaction_is_deduplicated_with_exact_rpc_income(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                tx_hash = ACTIVITY_TRANSACTIONS[network.name]
                try:
                    token, addresses = self._fixture(oracle)
                    expected_income = self._income(oracle, tx_hash, addresses)
                    status, raw = portfolio_response(
                        oracle,
                        "/v2/portfolio/ckb_transactions?" + urlencode({"tx_hash": tx_hash, "page_size": 100}),
                        token=token,
                    )
                except (OracleUnavailable, KeyError, TypeError, ValueError, IndexError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(200, status)
                payload = json.loads(raw)
                rows = [row["attributes"] for row in payload["data"]]
                matches = [row for row in rows if row["transaction_hash"] == tx_hash]
                self.assertEqual(1, len(matches))
                self.assertEqual(expected_income, int(matches[0]["income"]))
                self.assertEqual("committed", oracle.rpc_result("get_transaction", [tx_hash])["tx_status"]["status"])

    # TEST-MAP: PORTFOLIO-ASSET-RPC-09
    @unittest.expectedFailure  # Filtered, sorted, and paged public requests currently all return HTTP 500.
    def test_user_scoped_address_and_hash_filters_have_stable_adjacent_pages(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    token, addresses = self._fixture(oracle)
                    nft = oracle.explorer_json(
                        f"/v2/nft/collections/{ITEM_FIXTURES[network.name]['spore']}/items"
                    )["data"][0]
                    external_address = str(nft["owner"])
                    external_tx = str(nft["cell"]["tx_hash"])
                    paths = {
                        "tracked": "/v2/portfolio/ckb_transactions?" + urlencode({"address_hash": addresses[0], "page_size": 2}),
                        "hash": "/v2/portfolio/ckb_transactions?" + urlencode({"tx_hash": ACTIVITY_TRANSACTIONS[network.name]}),
                        "first": "/v2/portfolio/ckb_transactions?" + urlencode({"sort": "time.desc", "page": 1, "page_size": 1}),
                        "second": "/v2/portfolio/ckb_transactions?" + urlencode({"sort": "time.desc", "page": 2, "page_size": 1}),
                        "combined": "/v2/portfolio/ckb_transactions?" + urlencode({"sort": "time.desc", "page": 1, "page_size": 2}),
                        "external": "/v2/portfolio/ckb_transactions?" + urlencode({"address_hash": external_address, "tx_hash": external_tx}),
                    }
                    responses = {name: portfolio_response(oracle, path, token=token) for name, path in paths.items()}
                except (OracleUnavailable, KeyError, TypeError, ValueError, IndexError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertTrue(all(status == 200 for status, _raw in responses.values()))
                parsed = {name: json.loads(raw) for name, (_status, raw) in responses.items()}
                self.assertEqual([], parsed["external"]["data"])
                self.assertEqual(
                    parsed["first"]["data"] + parsed["second"]["data"],
                    parsed["combined"]["data"][:2],
                )
                self.assertEqual(
                    {ACTIVITY_TRANSACTIONS[network.name]},
                    {row["attributes"]["transaction_hash"] for row in parsed["hash"]["data"]},
                )
                self.assertTrue(parsed["tracked"]["data"])


if __name__ == "__main__":
    unittest.main()
