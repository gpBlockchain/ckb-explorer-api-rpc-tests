from __future__ import annotations

import base64
import hashlib
import json
import time
import unittest

from ckb_rpc_correctness.ckb import LockScript, ckb2021_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.portfolio.http import portfolio_response


MESSAGE = "0x95e919c41e1ae7593730097e9bb1185787b046ae9f47b4a10ff4e22f9c3e3eab"
SIGNATURE = "0x1e94db61cff452639cf7dd991cf0c856923dcf74af24b6f575b91479ad2c8ef40769812d1cf1fd1a15d2f6cb9ef3d91260ef27e65e1f9be399887e9a5447786301"
PUBLIC_KEY = "0x024a501efd328e062c8675f2365970728c859c592beeefd6be8ead3d901330bc01"
SECP_CODE_HASH = "0x9bd7e06f3ecf4be0f2fcd2188b23f1b9fcc88e5d4b65a8637b17723bbda3cce8"
SIGNER_ARGS = "0x36c329ed630d6ce750712a477543672adab57f4c"
GENERATOR_PUBLIC_KEY = "0x0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"


class V2PortfolioSessionsCreateRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _address(self, hrp: str, args: str = SIGNER_ARGS) -> str:
        return ckb2021_address(LockScript(SECP_CODE_HASH, "type", args), hrp)

    def _payload(self, token: str) -> dict[str, object]:
        encoded = token.split(".")[1]
        encoded += "=" * (-len(encoded) % 4)
        return json.loads(base64.urlsafe_b64decode(encoded))

    # TEST-MAP: PORTFOLIO-AUTH-RPC-01
    def test_valid_network_signature_recovers_key_and_issues_a_bounded_working_jwt(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    status, raw = portfolio_response(
                        oracle,
                        "/v2/portfolio/sessions",
                        method="POST",
                        json_body={"address": self._address(network.address_hrp), "message": MESSAGE, "signature": SIGNATURE},
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                body = json.loads(raw)
                self.assertEqual(200, status)
                self.assertEqual({"name", "jwt"}, set(body))
                claims = self._payload(body["jwt"])
                self.assertIsInstance(claims.get("uuid"), str)
                self.assertGreater(int(claims["exp"]), int(time.time()))
                self.assertLessEqual(int(claims["exp"]) - int(time.time()), 16 * 24 * 60 * 60)
                protected_status, protected_raw = portfolio_response(
                    oracle, "/v2/portfolio/udt_accounts", token=body["jwt"]
                )
                self.assertEqual(200, protected_status)
                self.assertIsInstance(json.loads(protected_raw), list)

    # TEST-MAP: PORTFOLIO-AUTH-RPC-02
    def test_repeated_and_explicit_public_key_logins_reuse_one_user(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                base = {"address": self._address(network.address_hrp), "message": MESSAGE, "signature": SIGNATURE}
                try:
                    responses = [
                        portfolio_response(oracle, "/v2/portfolio/sessions", method="POST", json_body=base),
                        portfolio_response(
                            oracle, "/v2/portfolio/sessions", method="POST", json_body={**base, "pub_key": PUBLIC_KEY}
                        ),
                    ]
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                bodies = [json.loads(raw) for status, raw in responses if status == 200]
                self.assertEqual(2, len(bodies))
                self.assertEqual(bodies[0]["name"], bodies[1]["name"])
                self.assertEqual(self._payload(bodies[0]["jwt"])["uuid"], self._payload(bodies[1]["jwt"])["uuid"])

    # TEST-MAP: PORTFOLIO-AUTH-RPC-03
    def test_wrong_network_and_malformed_required_fields_return_no_jwt(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                other_hrp = "ckt" if network.address_hrp == "ckb" else "ckb"
                valid = {"address": self._address(network.address_hrp), "message": MESSAGE, "signature": SIGNATURE}
                requests = [
                    {**valid, "address": self._address(other_hrp)},
                    {**valid, "message": ""},
                    {**valid, "message": "not-hex"},
                    {**valid, "signature": ""},
                    {**valid, "signature": "not-hex"},
                ]
                try:
                    responses = [
                        portfolio_response(oracle, "/v2/portfolio/sessions", method="POST", json_body=request)
                        for request in requests
                    ]
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                for status, raw in responses:
                    self.assertGreaterEqual(status, 400)
                    self.assertNotIn("jwt", json.loads(raw))

    # Explicit pub_key currently bypasses verification that the supplied signature belongs to that key.
    # TEST-MAP: PORTFOLIO-AUTH-RPC-04
    @unittest.expectedFailure
    def test_signature_and_explicit_public_key_must_match_the_claimed_address(self) -> None:
        forged_args = "0x" + hashlib.blake2b(
            bytes.fromhex(GENERATOR_PUBLIC_KEY[2:]), digest_size=32, person=b"ckb-default-hash"
        ).digest()[:20].hex()
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                status, raw = portfolio_response(
                    oracle,
                    "/v2/portfolio/sessions",
                    method="POST",
                    json_body={
                        "address": self._address(network.address_hrp, forged_args),
                        "message": MESSAGE,
                        "signature": SIGNATURE,
                        "pub_key": GENERATOR_PUBLIC_KEY,
                    },
                )
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            self.assertGreaterEqual(status, 400)
            self.assertNotIn("jwt", json.loads(raw))
