from __future__ import annotations

import json
import socket
import unittest
import urllib.error
import urllib.request
from typing import Mapping

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings

from tests.token_udt.test_v1_udt_transactions_show import UDT_FIXTURES


class V1UdtVerificationsPatchRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _update(
        self,
        oracle: NetworkOracle,
        method: str,
        type_hash: str,
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(
            oracle.network.explorer_api_url + f"/v1/udt_verifications/{type_hash}",
            data=b"{}",
            method=method,
            headers={**V1_HEADERS, "User-Agent": oracle.client.user_agent},
        )
        try:
            with urllib.request.urlopen(request, timeout=oracle.client.timeout) as response:
                return response.status, response.read(oracle.client.max_body_bytes + 1)
        except urllib.error.HTTPError as error:
            try:
                return error.code, error.read(4096)
            finally:
                error.close()
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as error:
            raise OracleUnavailable(
                f"{oracle.network.name} verification {method} transport is unavailable: {error}"
            ) from error

    # TEST-MAP: UDT-META-RPC-11
    def test_patch_and_put_missing_udt_and_no_contact_email_return_distinct_errors(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            no_email_hash = UDT_FIXTURES[network.name]
            try:
                detail = oracle.explorer_json(f"/v1/udts/{no_email_hash}")
                data = detail.get("data") if isinstance(detail, dict) else None
                attributes = data.get("attributes") if isinstance(data, dict) else None
                if not isinstance(attributes, Mapping):
                    raise OracleUnavailable(f"{network.name} no-email UDT fixture is unavailable")
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            self.assertIsNone(attributes.get("email"))
            for method in ("PATCH", "PUT"):
                with self.subTest(network=network.name, method=method):
                    try:
                        missing_status, missing_raw = self._update(
                            oracle, method, "0x" + "ff" * 32
                        )
                        no_email_status, no_email_raw = self._update(
                            oracle, method, no_email_hash
                        )
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(404, missing_status)
                    self.assertEqual(400, no_email_status)
                    missing = json.loads(missing_raw)
                    no_email = json.loads(no_email_raw)
                    self.assertEqual({1026}, {int(error["code"]) for error in missing})
                    self.assertEqual({1033}, {int(error["code"]) for error in no_email})
                    self.assertFalse(any("data" in error for error in missing + no_email))


if __name__ == "__main__":
    unittest.main()
