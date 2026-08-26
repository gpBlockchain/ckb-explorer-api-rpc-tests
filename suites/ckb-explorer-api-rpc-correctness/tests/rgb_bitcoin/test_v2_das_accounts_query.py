from __future__ import annotations

import os
import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import LockScript, ckb2021_address
from ckb_rpc_correctness.http import HttpClientError, JsonHttpClient
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


SECP256K1_BLAKE160_CODE_HASH = (
    "0x9bd7e06f3ecf4be0f2fcd2188b23f1b9fcc88e5d4b65a8637b17723bbda3cce8"
)
DAS_MANAGER_KEYS = (
    "ffd0a46770efcbd6c45f7ca3fe4245625a670b",
    "feb5f35027b942012c35e52d6473627e979a66",
)


class V2DasAccountsQueryRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _reverse_record(self, network_name: str, manager_key: str) -> Mapping[str, Any]:
        endpoint = os.getenv(
            f"{network_name.upper()}_DAS_INDEXER_URL",
            "https://indexer-basic.da.systems/v1",
        ).rstrip("/")
        client = JsonHttpClient(
            timeout=self.settings.timeout_seconds,
            retries=self.settings.transport_retries,
        )
        try:
            payload = client.request_json(
                endpoint + "/reverse/record",
                method="POST",
                json_body={
                    "type": "blockchain",
                    "key_info": {
                        "coin_type": "",
                        "chain_id": "1",
                        "key": "0x" + manager_key,
                    },
                },
            )
        except HttpClientError as error:
            raise OracleUnavailable(
                f"{network_name} DAS Indexer reverse-record oracle is unavailable: {error}"
            ) from error
        if not isinstance(payload, dict) or not isinstance(payload.get("err_no"), int):
            raise OracleUnavailable(
                f"{network_name} DAS Indexer reverse-record oracle returned no result"
            )
        return payload

    # TEST-MAP: DAS-RPC-01
    # TEST-MAP: DAS-RPC-02
    # TEST-MAP: DAS-RPC-05
    def test_batch_record_mapping_matches_das_indexer_and_ignores_invalid_address(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                try:
                    oracle_rows = [
                        self._reverse_record(network.name, manager_key)
                        for manager_key in DAS_MANAGER_KEYS
                    ]
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                accounts: list[str] = []
                for row in oracle_rows:
                    data = row.get("data")
                    if row["err_no"] != 0 or not isinstance(data, dict):
                        continue
                    account = data.get("account")
                    if isinstance(account, str) and account:
                        accounts.append(account)
                if len(accounts) < 2:
                    raise unittest.SkipTest(
                        f"{network.name} public DAS fixtures no longer expose two reverse records"
                    )

                addresses = [
                    ckb2021_address(
                        LockScript(
                            SECP256K1_BLAKE160_CODE_HASH,
                            "type",
                            "0x05" + manager_key,
                        ),
                        network.address_hrp,
                    )
                    for manager_key in DAS_MANAGER_KEYS
                ]
                invalid_address = "invalid-ckb-address"
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.client.request_json(
                        network.explorer_api_url + "/v2/das_accounts",
                        method="POST",
                        json_body={"addresses": addresses + [invalid_address]},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer DAS batch query failed: {error}")

                self.assertIsInstance(payload, dict)
                self.assertNotIn(invalid_address, payload)
                self.assertEqual(addresses, list(payload))
                self.assertEqual(
                    [row["data"]["account"] for row in oracle_rows],
                    [payload[address] for address in addresses],
                )

    # TEST-MAP: DAS-RPC-03
    def test_non_das_algorithm_address_is_preserved_with_empty_name(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                address = ckb2021_address(
                    LockScript(
                        SECP256K1_BLAKE160_CODE_HASH,
                        "type",
                        "0x04" + "11" * 20,
                    ),
                    network.address_hrp,
                )
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.client.request_json(
                        network.explorer_api_url + "/v2/das_accounts",
                        method="POST",
                        json_body={"addresses": [address]},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer DAS non-algorithm query failed: {error}")
                self.assertEqual({address: ""}, payload)

    # TEST-MAP: DAS-RPC-04
    def test_das_indexer_business_error_isolated_to_its_address(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                manager_key = DAS_MANAGER_KEYS[0]
                try:
                    oracle_row = self._reverse_record(network.name, manager_key)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if oracle_row["err_no"] == 0:
                    raise unittest.SkipTest(
                        f"{network.name} DAS business-error fixture now has a reverse record"
                    )

                error_address = ckb2021_address(
                    LockScript(
                        SECP256K1_BLAKE160_CODE_HASH,
                        "type",
                        "0x05" + manager_key,
                    ),
                    network.address_hrp,
                )
                normal_address = ckb2021_address(
                    LockScript(
                        SECP256K1_BLAKE160_CODE_HASH,
                        "type",
                        "0x04" + "22" * 20,
                    ),
                    network.address_hrp,
                )
                oracle = NetworkOracle(network, self.settings)
                try:
                    payload = oracle.client.request_json(
                        network.explorer_api_url + "/v2/das_accounts",
                        method="POST",
                        json_body={"addresses": [error_address, normal_address]},
                    )
                except HttpClientError as error:
                    if "transport failure" in str(error):
                        raise unittest.SkipTest(str(error)) from error
                    self.fail(f"{network.name} Explorer DAS business-error query failed: {error}")
                self.assertEqual({error_address: "", normal_address: ""}, payload)


if __name__ == "__main__":
    unittest.main()
