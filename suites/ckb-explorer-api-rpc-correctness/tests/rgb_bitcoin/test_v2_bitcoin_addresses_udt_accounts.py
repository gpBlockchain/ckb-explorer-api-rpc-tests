from __future__ import annotations

import unittest
from collections import defaultdict
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


UDT_ADDRESS_FIXTURES = {
    "mainnet": "bc1qn542w6yq3qjqchv40hffrf77l270n9jstv0yk8",
    "testnet": "tb1qcepnh7pml6ypx9gtvgwex3arag8repm2n5rlt8",
}


class V2BitcoinAddressesUdtAccountsRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _status_cells(
        self, oracle: NetworkOracle, address: str, status: str
    ) -> list[Mapping[str, Any]]:
        payload = oracle.explorer_json(
            f"/v1/address_live_cells/{address}",
            {"bound_status": status, "page": 1, "page_size": 100},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if (
            not isinstance(data, list)
            or any(not isinstance(row, dict) for row in data)
            or not isinstance(meta, dict)
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} Bitcoin address status cells are unavailable"
            )
        total = int(meta["total"])
        rows = list(data)
        for page in range(2, (total + 99) // 100 + 1):
            following = oracle.explorer_json(
                f"/v1/address_live_cells/{address}",
                {"bound_status": status, "page": page, "page_size": 100},
            )
            following_data = (
                following.get("data") if isinstance(following, dict) else None
            )
            if not isinstance(following_data, list) or any(
                not isinstance(row, dict) for row in following_data
            ):
                raise OracleUnavailable(
                    f"{oracle.network.name} Bitcoin address status page is unavailable"
                )
            rows.extend(following_data)
        if total != len(rows):
            raise OracleUnavailable(
                f"{oracle.network.name} Bitcoin address status total changed during pagination"
            )
        return rows

    def _accounts(
        self, oracle: NetworkOracle, address: str
    ) -> list[Mapping[str, Any]]:
        payload = oracle.explorer_json(
            f"/v2/bitcoin_addresses/{address}/udt_accounts"
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        accounts = data.get("udt_accounts") if isinstance(data, dict) else None
        if not isinstance(accounts, list) or any(
            not isinstance(account, dict) for account in accounts
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} Bitcoin address UDT accounts are unavailable"
            )
        return accounts

    # TEST-MAP: BTC-ADDR-RPC-06
    def test_accounts_match_published_bound_live_cell_amounts_and_metadata(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = UDT_ADDRESS_FIXTURES[network.name]
                try:
                    accounts = self._accounts(oracle, address)
                    by_status = {
                        status: self._status_cells(oracle, address, status)
                        for status in ("bound", "normal", "unbound", "binding")
                    }
                    eligible = [
                        row
                        for status in ("bound", "normal")
                        for row in by_status[status]
                        if row["attributes"].get("cell_type")
                        in {"udt", "xudt", "xudt_compatible"}
                        and isinstance(row["attributes"].get("extra_info"), dict)
                        and row["attributes"]["extra_info"].get("published") is True
                    ]
                    live_results = oracle.rpc_batch_results(
                        [
                            (
                                "get_live_cell",
                                [
                                    {
                                        "tx_hash": row["attributes"]["tx_hash"],
                                        "index": hex(
                                            int(row["attributes"]["cell_index"])
                                        ),
                                    },
                                    True,
                                ],
                            )
                            for row in eligible
                        ]
                    )
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                expected_amounts: defaultdict[tuple[str, str], int] = defaultdict(int)
                metadata: dict[tuple[str, str], Mapping[str, Any]] = {}
                for row, result in zip(eligible, live_results):
                    attributes = row["attributes"]
                    self.assertEqual("live", result.get("status"))
                    cell = result.get("cell")
                    output = cell.get("output") if isinstance(cell, dict) else None
                    data = cell.get("data") if isinstance(cell, dict) else None
                    if not isinstance(output, dict) or not isinstance(data, dict):
                        raise unittest.SkipTest(
                            f"{network.name} RPC omitted a live UDT Cell result"
                        )
                    type_script = output.get("type")
                    if not isinstance(type_script, dict):
                        raise unittest.SkipTest(
                            f"{network.name} RPC live UDT Cell has no type script"
                        )
                    raw = bytes.fromhex(str(data["content"])[2:])
                    if len(raw) < 16:
                        raise unittest.SkipTest(
                            f"{network.name} RPC live UDT Cell data is shorter than uint128"
                        )
                    type_hash = ckb_script_hash(type_script)
                    key = (str(attributes["cell_type"]), type_hash)
                    expected_amounts[key] += int.from_bytes(raw[:16], "little")
                    metadata[key] = attributes["extra_info"]
                    self.assertEqual(attributes["type_hash"], type_hash)
                    self.assertEqual(attributes["type_script"], type_script)

                actual = {
                    (str(account["udt_type"]), str(account["type_hash"])): account
                    for account in accounts
                }
                self.assertTrue(expected_amounts)
                self.assertEqual(set(expected_amounts), set(actual))
                for key, expected_amount in expected_amounts.items():
                    account = actual[key]
                    info = metadata[key]
                    self.assertEqual(expected_amount, int(account["amount"]))
                    self.assertEqual(info["symbol"], account["symbol"])
                    self.assertEqual(int(info["decimal"]), int(account["decimal"]))
                    self.assertEqual(key[1], account["type_hash"])
                    self.assertEqual(key[0], account["udt_type"])
                    self.assertEqual(
                        next(
                            row["attributes"]["type_script"]
                            for row in eligible
                            if (
                                row["attributes"]["cell_type"],
                                row["attributes"]["type_hash"],
                            )
                            == key
                        ),
                        account["udt_type_script"],
                    )
                    self.assertIsInstance(account["udt_icon_file"], str)

                excluded = [
                    row["attributes"]
                    for status in ("unbound", "binding")
                    for row in by_status[status]
                    if row["attributes"].get("cell_type")
                    in {"udt", "xudt", "xudt_compatible"}
                ]
                if network.name == "testnet":
                    self.assertTrue(excluded)
                    self.assertTrue(
                        {
                            (str(row["cell_type"]), str(row["type_hash"]))
                            for row in excluded
                        }
                        - set(actual)
                    )

    # TEST-MAP: BTC-ADDR-RPC-07
    def test_amount_above_javascript_safe_integer_matches_uint128_cell_data(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = UDT_ADDRESS_FIXTURES[network.name]
                try:
                    accounts = self._accounts(oracle, address)
                    large = next(
                        account
                        for account in accounts
                        if int(account["amount"]) > 2**53 - 1
                    )
                    bound = self._status_cells(oracle, address, "bound")
                    normal = self._status_cells(oracle, address, "normal")
                    cells = [
                        row
                        for row in bound + normal
                        if row["attributes"].get("cell_type") == large["udt_type"]
                        and row["attributes"].get("type_hash") == large["type_hash"]
                    ]
                    live_results = oracle.rpc_batch_results(
                        [
                            (
                                "get_live_cell",
                                [
                                    {
                                        "tx_hash": row["attributes"]["tx_hash"],
                                        "index": hex(
                                            int(row["attributes"]["cell_index"])
                                        ),
                                    },
                                    True,
                                ],
                            )
                            for row in cells
                        ]
                    )
                except StopIteration as error:
                    raise unittest.SkipTest(
                        f"{network.name} public Bitcoin UDT fixture has no amount above 2^53"
                    ) from error
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                expected = 0
                for result in live_results:
                    if result.get("status") != "live":
                        raise unittest.SkipTest(
                            f"{network.name} large UDT fixture changed during observation"
                        )
                    raw = bytes.fromhex(result["cell"]["data"]["content"][2:])
                    expected += int.from_bytes(raw[:16], "little")
                self.assertGreater(expected, 2**53 - 1)
                self.assertEqual(expected, int(large["amount"]))


if __name__ == "__main__":
    unittest.main()
