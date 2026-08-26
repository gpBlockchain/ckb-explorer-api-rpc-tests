from __future__ import annotations

import json
import unittest
from urllib.parse import quote, urlencode

from ckb_rpc_correctness.ckb import LockScript, ckb2021_address, output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import ACTIVITY_TRANSACTIONS, DAO_ADDRESSES
from tests.portfolio.http import portfolio_response
from tests.portfolio.test_v2_portfolio_sessions_create import MESSAGE, SECP_CODE_HASH, SIGNATURE, SIGNER_ARGS


class V2PortfolioStatisticsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _session(self, oracle: NetworkOracle) -> dict[str, object]:
        address = ckb2021_address(LockScript(SECP_CODE_HASH, "type", SIGNER_ARGS), oracle.network.address_hrp)
        status, raw = portfolio_response(
            oracle,
            "/v2/portfolio/sessions",
            method="POST",
            json_body={"address": address, "message": MESSAGE, "signature": SIGNATURE},
        )
        if status != 200:
            raise OracleUnavailable(f"{oracle.network.name} Portfolio login returned HTTP {status}")
        return json.loads(raw)

    def _tracked_addresses(self, oracle: NetworkOracle, token: str) -> list[str]:
        result = oracle.rpc_result("get_transaction", [ACTIVITY_TRANSACTIONS[oracle.network.name]])
        transaction = result.get("transaction") if isinstance(result, dict) else None
        outputs = transaction.get("outputs") if isinstance(transaction, dict) else None
        if not isinstance(outputs, list) or not outputs or not isinstance(outputs[0], dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC activity address is unavailable")
        addresses = [output_address(outputs[0], oracle.network.address_hrp), DAO_ADDRESSES[oracle.network.name]]
        status, raw = portfolio_response(
            oracle, "/v2/portfolio/addresses", method="POST", json_body={"addresses": addresses}, token=token
        )
        if status != 204:
            raise OracleUnavailable(f"{oracle.network.name} Portfolio address sync returned HTTP {status}: {raw[:200]!r}")
        return addresses

    # TEST-MAP: PORTFOLIO-ASSET-RPC-04
    @unittest.expectedFailure  # A tracked non-DAO address has NULL unclaimed_compensation, so aggregation returns HTTP 500.
    def test_multi_address_capacity_and_dao_totals_equal_the_sum_of_chain_bound_addresses(self) -> None:
        fields = ("balance", "balance_occupied", "dao_deposit", "interest", "dao_compensation")
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    session = self._session(oracle)
                    addresses = self._tracked_addresses(oracle, str(session["jwt"]))
                    detail_rows = []
                    for address in addresses:
                        payload = oracle.explorer_json(f"/v1/addresses/{quote(address, safe='')}")
                        rows = payload.get("data") if isinstance(payload, dict) else None
                        if not isinstance(rows, list) or len(rows) != 1:
                            raise OracleUnavailable(f"{network.name} address aggregate is unavailable")
                        detail_rows.append(rows[0]["attributes"])
                    status, raw = portfolio_response(
                        oracle,
                        "/v2/portfolio/statistics?" + urlencode({"latest_address": addresses[-1]}),
                        token=str(session["jwt"]),
                    )
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(200, status)
                actual = json.loads(raw).get("data")
                self.assertIsInstance(actual, dict)
                for field in fields:
                    self.assertEqual(sum(int(row[field]) for row in detail_rows), int(actual[field]))
                    self.assertTrue(str(actual[field]).isdecimal())

    # TEST-MAP: PORTFOLIO-ASSET-RPC-05
    @unittest.expectedFailure  # The correct retry reaches the same NULL aggregation defect and returns HTTP 500.
    def test_missing_malformed_and_untracked_latest_address_fail_then_tracked_retry_succeeds(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    session = self._session(oracle)
                    token = str(session["jwt"])
                    addresses = self._tracked_addresses(oracle, token)
                    external = ckb2021_address(
                        LockScript(SECP_CODE_HASH, "type", "0x" + "fe" * 20), network.address_hrp
                    )
                    paths = [
                        "/v2/portfolio/statistics",
                        "/v2/portfolio/statistics?" + urlencode({"latest_address": "not-an-address"}),
                        "/v2/portfolio/statistics?" + urlencode({"latest_address": external}),
                    ]
                    failures = [portfolio_response(oracle, path, token=token) for path in paths]
                    success = portfolio_response(
                        oracle,
                        "/v2/portfolio/statistics?" + urlencode({"latest_address": addresses[-1]}),
                        token=token,
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                for (status, raw), code in zip(failures, (2000, 2022, 2007), strict=True):
                    self.assertGreaterEqual(status, 400)
                    errors = json.loads(raw)
                    self.assertIsInstance(errors, list)
                    self.assertEqual(code, errors[0]["code"])
                    self.assertNotIn("data", errors[0])
                self.assertEqual(addresses[-1], json.loads(failures[-1][1])[0]["detail"])
                self.assertEqual(200, success[0])
                self.assertEqual(
                    {"balance", "balance_occupied", "dao_deposit", "interest", "dao_compensation"},
                    set(json.loads(success[1])["data"]),
                )
