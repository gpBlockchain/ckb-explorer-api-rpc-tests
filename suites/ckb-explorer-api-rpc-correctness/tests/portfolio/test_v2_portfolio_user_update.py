from __future__ import annotations

import hashlib
import json
import time
import unittest

from ckb_rpc_correctness.ckb import LockScript, ckb2021_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.portfolio.http import portfolio_response
from tests.portfolio.test_v2_portfolio_sessions_create import (
    GENERATOR_PUBLIC_KEY,
    MESSAGE,
    PUBLIC_KEY,
    SECP_CODE_HASH,
    SIGNATURE,
    SIGNER_ARGS,
)


class V2PortfolioUserUpdateRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _address(self, hrp: str, args: str = SIGNER_ARGS) -> str:
        return ckb2021_address(LockScript(SECP_CODE_HASH, "type", args), hrp)

    def _login(self, oracle: NetworkOracle, *, second: bool = False) -> dict[str, object]:
        if second:
            args = "0x" + hashlib.blake2b(
                bytes.fromhex(GENERATOR_PUBLIC_KEY[2:]), digest_size=32, person=b"ckb-default-hash"
            ).digest()[:20].hex()
            request = {
                "address": self._address(oracle.network.address_hrp, args),
                "message": MESSAGE,
                "signature": SIGNATURE,
                "pub_key": GENERATOR_PUBLIC_KEY,
            }
        else:
            request = {
                "address": self._address(oracle.network.address_hrp),
                "message": MESSAGE,
                "signature": SIGNATURE,
                "pub_key": PUBLIC_KEY,
            }
        status, raw = portfolio_response(
            oracle, "/v2/portfolio/sessions", method="POST", json_body=request
        )
        if status != 200:
            raise OracleUnavailable(f"{oracle.network.name} Portfolio login returned HTTP {status}")
        return json.loads(raw)

    # TEST-MAP: PORTFOLIO-AUTH-RPC-05
    def test_patch_and_put_reject_invalid_jwts_without_changing_the_name(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    before = self._login(oracle)
                    for method in ("PATCH", "PUT"):
                        for token in (None, "not-a-jwt", str(before["jwt"])[:-1] + "x"):
                            status, _raw = portfolio_response(
                                oracle,
                                "/v2/portfolio/user",
                                method=method,
                                json_body={"name": "must-not-apply"},
                                token=token,
                            )
                            self.assertGreaterEqual(status, 400)
                    after = self._login(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(before["name"], after["name"])
                raise unittest.SkipTest(
                    f"{network.name} signing secret is unavailable for expired and nonexistent-UUID valid JWT fixtures"
                )

    # TEST-MAP: PORTFOLIO-AUTH-RPC-06
    def test_patch_and_put_persist_the_last_name_and_restore_the_fixture(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    session = self._login(oracle)
                    observed = session["name"]
                    restore_name = observed or "rpc-test-baseline"
                    token = str(session["jwt"])
                    try:
                        for method, name in (
                            ("PATCH", f"rpc-patch-{network.name}-{int(time.time())}"),
                            ("PUT", f"rpc-put-{network.name}-{int(time.time())}"),
                        ):
                            status, raw = portfolio_response(
                                oracle,
                                "/v2/portfolio/user",
                                method=method,
                                json_body={"name": name},
                                token=token,
                            )
                            self.assertEqual(204, status)
                            self.assertEqual(b"", raw)
                            self.assertEqual(name, self._login(oracle)["name"])
                    finally:
                        portfolio_response(
                            oracle,
                            "/v2/portfolio/user",
                            method="PATCH",
                            json_body={"name": restore_name},
                            token=token,
                        )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

    # TEST-MAP: PORTFOLIO-AUTH-RPC-07
    def test_one_users_jwt_does_not_change_the_other_users_name(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    user_a = self._login(oracle)
                    user_b = self._login(oracle, second=True)
                    original_a, original_b = user_a["name"] or "rpc-test-baseline", user_b["name"]
                    name = f"isolated-a-{network.name}-{int(time.time())}"
                    try:
                        status, _raw = portfolio_response(
                            oracle,
                            "/v2/portfolio/user",
                            method="PATCH",
                            json_body={"name": name},
                            token=str(user_a["jwt"]),
                        )
                        self.assertEqual(204, status)
                        self.assertEqual(name, self._login(oracle)["name"])
                        self.assertEqual(original_b, self._login(oracle, second=True)["name"])
                    finally:
                        portfolio_response(
                            oracle,
                            "/v2/portfolio/user",
                            method="PATCH",
                            json_body={"name": original_a},
                            token=str(user_a["jwt"]),
                        )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

    # TEST-MAP: PORTFOLIO-AUTH-RPC-08
    def test_blank_names_fail_for_both_methods_and_a_later_valid_update_succeeds(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    session = self._login(oracle)
                    observed = session["name"]
                    restore_name = observed or "rpc-test-baseline"
                    token = str(session["jwt"])
                    for method in ("PATCH", "PUT"):
                        for body in ({}, {"name": ""}, {"name": "   "}):
                            status, _raw = portfolio_response(
                                oracle, "/v2/portfolio/user", method=method, json_body=body, token=token
                            )
                            self.assertGreaterEqual(status, 400)
                    self.assertEqual(observed, self._login(oracle)["name"])
                    valid = f"valid-after-errors-{network.name}-{int(time.time())}"
                    status, _raw = portfolio_response(
                        oracle,
                        "/v2/portfolio/user",
                        method="PATCH",
                        json_body={"name": valid},
                        token=token,
                    )
                    self.assertEqual(204, status)
                    self.assertEqual(valid, self._login(oracle)["name"])
                    portfolio_response(
                        oracle,
                        "/v2/portfolio/user",
                        method="PATCH",
                        json_body={"name": restore_name},
                        token=token,
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
