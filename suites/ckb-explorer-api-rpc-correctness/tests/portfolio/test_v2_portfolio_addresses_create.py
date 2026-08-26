from __future__ import annotations

import csv
import hashlib
import io
import json
import unittest
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import LockScript, ckb2021_address, output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import ACTIVITY_TRANSACTIONS, DAO_ADDRESSES
from tests.portfolio.http import portfolio_response
from tests.portfolio.test_v2_portfolio_sessions_create import (
    GENERATOR_PUBLIC_KEY,
    MESSAGE,
    SECP_CODE_HASH,
    SIGNATURE,
    SIGNER_ARGS,
)


SECOND_PUBLIC_KEY = "0x02c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5"
THIRD_PUBLIC_KEY = "0x02f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9"


class V2PortfolioAddressesCreateRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _session(self, oracle: NetworkOracle, args: str, pub_key: str | None = None) -> str:
        body = {
            "address": ckb2021_address(LockScript(SECP_CODE_HASH, "type", args), oracle.network.address_hrp),
            "message": MESSAGE,
            "signature": SIGNATURE,
        }
        if pub_key is not None:
            body["pub_key"] = pub_key
        status, raw = portfolio_response(oracle, "/v2/portfolio/sessions", method="POST", json_body=body)
        if status != 200:
            raise OracleUnavailable(f"{oracle.network.name} Portfolio login returned HTTP {status}")
        return str(json.loads(raw)["jwt"])

    def _pub_key_args(self, pub_key: str) -> str:
        return "0x" + hashlib.blake2b(
            bytes.fromhex(pub_key[2:]), digest_size=32, person=b"ckb-default-hash"
        ).digest()[:20].hex()

    def _activity_address(self, oracle: NetworkOracle) -> str:
        result = oracle.rpc_result("get_transaction", [ACTIVITY_TRANSACTIONS[oracle.network.name]])
        transaction = result.get("transaction") if isinstance(result, dict) else None
        outputs = transaction.get("outputs") if isinstance(transaction, dict) else None
        if not isinstance(outputs, list) or not outputs or not isinstance(outputs[0], dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC activity address is unavailable")
        return output_address(outputs[0], oracle.network.address_hrp)

    # TEST-MAP: PORTFOLIO-ASSET-RPC-01
    @unittest.expectedFailure  # Membership is accepted, but mixed NULL DAO compensation makes both statistics reads HTTP 500.
    def test_duplicate_and_repeated_address_batches_are_idempotent_unions(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    token = self._session(oracle, self._pub_key_args(SECOND_PUBLIC_KEY), SECOND_PUBLIC_KEY)
                    addresses = [self._activity_address(oracle), DAO_ADDRESSES[network.name]]
                    responses = [
                        portfolio_response(
                            oracle,
                            "/v2/portfolio/addresses",
                            method="POST",
                            json_body={"addresses": [addresses[0], addresses[0], addresses[1]]},
                            token=token,
                        ),
                        portfolio_response(
                            oracle,
                            "/v2/portfolio/addresses",
                            method="POST",
                            json_body={"addresses": list(reversed(addresses))},
                            token=token,
                        ),
                    ]
                    statistics = [
                        portfolio_response(
                            oracle,
                            "/v2/portfolio/statistics?" + urlencode({"latest_address": address}),
                            token=token,
                        )
                        for address in addresses
                    ]
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual([204, 204], [status for status, _raw in responses])
                self.assertEqual([200, 200], [status for status, _raw in statistics])
                self.assertEqual(json.loads(statistics[0][1]), json.loads(statistics[1][1]))

    # TEST-MAP: PORTFOLIO-ASSET-RPC-02
    @unittest.expectedFailure  # Both public servers accept a mixed valid/wrong-network batch with HTTP 204.
    def test_mixed_valid_and_wrong_network_batch_rolls_back_all_observable_user_state(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                valid = ckb2021_address(
                    LockScript(SECP_CODE_HASH, "type", "0x" + "fd" * 20), network.address_hrp
                )
                other_hrp = "ckt" if network.address_hrp == "ckb" else "ckb"
                wrong_network = ckb2021_address(
                    LockScript(SECP_CODE_HASH, "type", "0x" + "fc" * 20), other_hrp
                )
                statistics_path = "/v2/portfolio/statistics?" + urlencode({"latest_address": valid})
                try:
                    token = self._session(oracle, self._pub_key_args(THIRD_PUBLIC_KEY), THIRD_PUBLIC_KEY)
                    before = (
                        portfolio_response(oracle, statistics_path, token=token),
                        portfolio_response(oracle, "/v2/portfolio/udt_accounts", token=token),
                        portfolio_response(oracle, "/v2/portfolio/ckb_transactions/download_csv", token=token),
                    )
                    rejected = portfolio_response(
                        oracle,
                        "/v2/portfolio/addresses",
                        method="POST",
                        json_body={"addresses": [valid, wrong_network]},
                        token=token,
                    )
                    after = (
                        portfolio_response(oracle, statistics_path, token=token),
                        portfolio_response(oracle, "/v2/portfolio/udt_accounts", token=token),
                        portfolio_response(oracle, "/v2/portfolio/ckb_transactions/download_csv", token=token),
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(400, rejected[0])
                self.assertEqual(2008, json.loads(rejected[1])[0]["code"])
                self.assertEqual(before, after)
                self.assertEqual(400, after[0][0])
                self.assertEqual(2007, json.loads(after[0][1])[0]["code"])

    # TEST-MAP: PORTFOLIO-ASSET-RPC-03
    @unittest.expectedFailure  # Public statistics and transaction-list aggregation currently return HTTP 500 for user A.
    def test_two_users_cannot_observe_each_others_addresses_assets_or_activity(self) -> None:
        generator_args = self._pub_key_args(GENERATOR_PUBLIC_KEY)
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    token_a = self._session(oracle, SIGNER_ARGS)
                    token_b = self._session(oracle, generator_args, GENERATOR_PUBLIC_KEY)
                    address_a = self._activity_address(oracle)
                    address_b = ckb2021_address(
                        LockScript(SECP_CODE_HASH, "type", "0x" + "fb" * 20), network.address_hrp
                    )
                    for token, address in ((token_a, address_a), (token_b, address_b)):
                        status, raw = portfolio_response(
                            oracle,
                            "/v2/portfolio/addresses",
                            method="POST",
                            json_body={"addresses": [address]},
                            token=token,
                        )
                        if status != 204:
                            raise OracleUnavailable(
                                f"{network.name} Portfolio address sync returned HTTP {status}: {raw[:200]!r}"
                            )
                    stats_a = portfolio_response(
                        oracle,
                        "/v2/portfolio/statistics?" + urlencode({"latest_address": address_a}),
                        token=token_a,
                    )
                    stats_b = portfolio_response(
                        oracle,
                        "/v2/portfolio/statistics?" + urlencode({"latest_address": address_b}),
                        token=token_b,
                    )
                    cross_a = portfolio_response(
                        oracle,
                        "/v2/portfolio/statistics?" + urlencode({"latest_address": address_b}),
                        token=token_a,
                    )
                    cross_b = portfolio_response(
                        oracle,
                        "/v2/portfolio/statistics?" + urlencode({"latest_address": address_a}),
                        token=token_b,
                    )
                    udt_a = portfolio_response(oracle, "/v2/portfolio/udt_accounts", token=token_a)
                    udt_b = portfolio_response(oracle, "/v2/portfolio/udt_accounts", token=token_b)
                    txs_a = portfolio_response(oracle, "/v2/portfolio/ckb_transactions?page_size=2", token=token_a)
                    txs_b = portfolio_response(oracle, "/v2/portfolio/ckb_transactions?page_size=2", token=token_b)
                    csv_a = portfolio_response(
                        oracle, "/v2/portfolio/ckb_transactions/download_csv", token=token_a
                    )
                    csv_b = portfolio_response(
                        oracle, "/v2/portfolio/ckb_transactions/download_csv", token=token_b
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual([400, 400], [cross_a[0], cross_b[0]])
                self.assertEqual([2007, 2007], [json.loads(cross_a[1])[0]["code"], json.loads(cross_b[1])[0]["code"]])
                self.assertEqual([200, 200], [udt_a[0], udt_b[0]])
                self.assertEqual([], json.loads(udt_b[1]))
                rows_a = list(csv.reader(io.StringIO(csv_a[1].decode("utf-8-sig"))))
                rows_b = list(csv.reader(io.StringIO(csv_b[1].decode("utf-8-sig"))))
                self.assertEqual(200, csv_a[0])
                self.assertEqual(200, csv_b[0])
                self.assertGreater(len(rows_a), 1)
                self.assertEqual(1, len(rows_b))
                self.assertIn(ACTIVITY_TRANSACTIONS[network.name], {row[0] for row in rows_a[1:]})
                self.assertEqual(200, stats_b[0])
                self.assertTrue(all(int(value) == 0 for value in json.loads(stats_b[1])["data"].values()))
                self.assertEqual([200, 200, 200], [stats_a[0], txs_a[0], txs_b[0]])


if __name__ == "__main__":
    unittest.main()
