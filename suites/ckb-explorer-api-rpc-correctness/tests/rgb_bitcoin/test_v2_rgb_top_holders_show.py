from __future__ import annotations

import os
import unittest
from collections import defaultdict
from decimal import Decimal, localcontext
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, output_address
from ckb_rpc_correctness.http import HttpClientError, JsonHttpClient
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


RGBPP_CODE_HASHES = {
    "mainnet": {
        "0xbc6c568a1a0d0a09f6844dc9d74ddb4343c32143ff25f727c59edf4fb72d6936"
    },
    "testnet": {
        "0x61ca7a4796a4eb19ca4f0d065cb9b10ddcf002f10f7cbb810c706cb6bb5c3248",
        "0xd07598deec7ce7b5665310386b4abd06a6d48843e953c5cc2112ad0d5a220364",
    },
}
BITCOIN_RPC_URLS = {
    "mainnet": "https://bitcoin-rpc.publicnode.com",
    "testnet": "https://bitcoin-testnet-rpc.publicnode.com",
}
MIXED_HOLDER_FIXTURES = {
    "mainnet": "0x71ff665b40ba044b1981ea9a8965189559c8e01e8cdfa34a3cc565e1f870a95c",
}
LARGE_HOLDER_FIXTURES = {
    "mainnet": "0x3390b8cb174b5623fd72a2dc5af13ea428ff171573f500b0e796e1f7336bcabe",
}
BTC_HOLDER_FIXTURES = {
    "mainnet": MIXED_HOLDER_FIXTURES["mainnet"],
    "testnet": "0x6bbae56439b88dbeabf3bb5f537cbe51005a14109128284036c47fc444d2772e",
}
EMPTY_HOLDER_FIXTURES = {
    "mainnet": "0x0b21cb78297b2bd1b7d23ec8fa5bfe11d1474132c278696078628ba38a059b45",
}
ZERO_SUPPLY_FIXTURES = {
    "mainnet": "0xc3d279c55f5e1781fc40e57816ddb036b31fc9f83a985eace34b2966e0039477",
}
SUDT_FIXTURES = {
    "mainnet": "0x7a12b26b621b6cf6982247855388694743c4da97b18a4ff8ebdf6fb54c1c850f",
    "testnet": "0xf60ed426477642e3f3fc384d09b6fbf3c6005bd2d106382301138880555a23fe",
}


class V2RgbTopHoldersShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.bitcoin_client = JsonHttpClient(
            timeout=max(cls.settings.timeout_seconds, 65),
            retries=cls.settings.transport_retries,
        )

    def _detail(
        self, oracle: NetworkOracle, type_hash: str
    ) -> Mapping[str, Any]:
        payload = oracle.explorer_json(f"/v1/xudts/{type_hash}")
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        if not isinstance(attributes, dict):
            raise OracleUnavailable(
                f"{oracle.network.name} xUDT detail is unavailable"
            )
        return attributes

    def _holders(
        self, oracle: NetworkOracle, type_hash: str
    ) -> list[Mapping[str, Any]]:
        payload = oracle.explorer_json(f"/v2/rgb_top_holders/{type_hash}")
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) for row in rows
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} RGB top holders are unavailable"
            )
        return rows

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
        for item in payload:
            result = item.get("result") if isinstance(item, dict) else None
            if not isinstance(result, dict) or not isinstance(result.get("txid"), str):
                raise OracleUnavailable(
                    f"{network_name} Bitcoin RPC omitted a mapped transaction"
                )
            transactions[result["txid"]] = result
        if set(transactions) != set(txids):
            raise OracleUnavailable(
                f"{network_name} Bitcoin RPC batch omitted a mapped transaction"
            )
        return transactions

    def _chain_balances(
        self, oracle: NetworkOracle, type_hash: str
    ) -> tuple[dict[tuple[str, str], int], dict[str, list[str]], int]:
        attributes = self._detail(oracle, type_hash)
        type_script = attributes.get("type_script")
        if not isinstance(type_script, dict) or ckb_script_hash(type_script) != type_hash:
            raise OracleUnavailable(
                f"{oracle.network.name} xUDT Type Script is unavailable"
            )
        search_key = {
            "script": type_script,
            "script_type": "type",
            "script_search_mode": "exact",
        }
        cells: list[Mapping[str, Any]] = []
        cursor: str | None = None
        for _page in range(100):
            params: list[object] = [search_key, "asc", "0x3e8"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result("get_cells", params)
            objects = result.get("objects") if isinstance(result, dict) else None
            if not isinstance(objects, list) or any(
                not isinstance(cell, dict) for cell in objects
            ):
                raise OracleUnavailable(
                    f"{oracle.network.name} Indexer xUDT cells are unavailable"
                )
            cells.extend(objects)
            if len(objects) < 1000:
                break
            next_cursor = result.get("last_cursor")
            if not isinstance(next_cursor, str) or next_cursor == cursor:
                raise OracleUnavailable(
                    f"{oracle.network.name} Indexer xUDT cursor is unavailable"
                )
            cursor = next_cursor
        else:
            raise OracleUnavailable(
                f"{oracle.network.name} Indexer xUDT pagination did not terminate"
            )

        parsed: list[tuple[Mapping[str, Any], int]] = []
        bitcoin_refs: list[tuple[str, int]] = []
        for cell in cells:
            output = cell.get("output")
            output_data = cell.get("output_data")
            if not isinstance(output, dict) or not isinstance(output_data, str):
                raise OracleUnavailable(
                    f"{oracle.network.name} Indexer xUDT Cell is incomplete"
                )
            raw = bytes.fromhex(output_data[2:])
            if len(raw) < 16:
                raise OracleUnavailable(
                    f"{oracle.network.name} xUDT Cell data is shorter than uint128"
                )
            amount = int.from_bytes(raw[:16], "little")
            if amount <= 0:
                continue
            parsed.append((output, amount))
            lock = output["lock"]
            if lock["code_hash"] in RGBPP_CODE_HASHES[oracle.network.name]:
                args = bytes.fromhex(lock["args"][2:])
                if len(args) != 36:
                    raise OracleUnavailable(
                        f"{oracle.network.name} RGB++ Lock args are unavailable"
                    )
                bitcoin_refs.append(
                    (args[4:36][::-1].hex(), int.from_bytes(args[:4], "little"))
                )

        bitcoin = self._bitcoin_transactions(
            oracle.network.name,
            list(dict.fromkeys(txid for txid, _index in bitcoin_refs)),
        ) if bitcoin_refs else {}
        balances: defaultdict[tuple[str, str], int] = defaultdict(int)
        bitcoin_locks: defaultdict[str, list[str]] = defaultdict(list)
        for output, amount in parsed:
            lock = output["lock"]
            if lock["code_hash"] in RGBPP_CODE_HASHES[oracle.network.name]:
                args = bytes.fromhex(lock["args"][2:])
                txid = args[4:36][::-1].hex()
                index = int.from_bytes(args[:4], "little")
                outputs = bitcoin[txid].get("vout")
                if not isinstance(outputs, list) or index >= len(outputs):
                    raise OracleUnavailable(
                        f"{oracle.network.name} mapped Bitcoin vout is unavailable"
                    )
                script = outputs[index].get("scriptPubKey")
                address = script.get("address") if isinstance(script, dict) else None
                if not isinstance(address, str):
                    raise OracleUnavailable(
                        f"{oracle.network.name} mapped Bitcoin address is unavailable"
                    )
                balances[("btc", address)] += amount
                bitcoin_locks[address].append(str(lock["args"]))
            else:
                balances[("ckb", output_address(output, oracle.network.address_hrp))] += amount
        return dict(balances), dict(bitcoin_locks), int(attributes["total_amount"])

    # TEST-MAP: RGB-ANALYTICS-RPC-07
    def test_unknown_and_sudt_type_hashes_return_404(self) -> None:
        for network in self.settings.networks:
            for label, type_hash in (
                ("unknown", "0x" + "ff" * 32),
                ("sudt", SUDT_FIXTURES[network.name]),
            ):
                with self.subTest(network=network.name, target=label):
                    oracle = NetworkOracle(network, self.settings)
                    with self.assertRaises(HttpClientError) as raised:
                        oracle.client.request_json(
                            network.explorer_api_url
                            + f"/v2/rgb_top_holders/{type_hash}"
                        )
                    self.assertIn("returned HTTP 404", str(raised.exception))

    # TEST-MAP: RGB-ANALYTICS-RPC-08
    def test_bitcoin_holder_with_multiple_mapped_ckb_locks_is_aggregated_once(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                type_hash = BTC_HOLDER_FIXTURES[network.name]
                oracle = NetworkOracle(network, self.settings)
                try:
                    balances, bitcoin_locks, _total = self._chain_balances(
                        oracle, type_hash
                    )
                    rows = self._holders(oracle, type_hash)
                    candidate = next(
                        address
                        for address, locks in bitcoin_locks.items()
                        if len(set(locks)) > 1
                        and any(
                            row["network"] == "btc"
                            and row["address_hash"] == address
                            for row in rows
                        )
                    )
                except StopIteration as error:
                    raise unittest.SkipTest(
                        f"{network.name} public top-ten fixture has no Bitcoin holder backed by multiple CKB locks"
                    ) from error
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                matches = [
                    row
                    for row in rows
                    if row["network"] == "btc" and row["address_hash"] == candidate
                ]
                self.assertEqual(1, len(matches))
                self.assertEqual(
                    balances[("btc", candidate)], int(Decimal(matches[0]["amount"]))
                )

    # TEST-MAP: RGB-ANALYTICS-RPC-09
    # TEST-MAP: RGB-ANALYTICS-RPC-10
    def test_mixed_ckb_and_bitcoin_balances_form_one_exact_global_top_ten(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                type_hash = MIXED_HOLDER_FIXTURES.get(network.name)
                if type_hash is None:
                    raise unittest.SkipTest(
                        f"{network.name} public index has no stable mixed-network xUDT fixture"
                    )
                oracle = NetworkOracle(network, self.settings)
                try:
                    balances, _bitcoin_locks, _total = self._chain_balances(
                        oracle, type_hash
                    )
                    rows = self._holders(oracle, type_hash)
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                expected = sorted(
                    balances.items(), key=lambda item: item[1], reverse=True
                )[:10]
                actual = [
                    (
                        (str(row["network"]), str(row["address_hash"])),
                        int(Decimal(row["amount"])),
                    )
                    for row in rows
                ]
                self.assertEqual(10, len(actual))
                self.assertEqual(expected, actual)
                self.assertEqual({"btc", "ckb"}, {network for (network, _), _ in actual})
                self.assertEqual(
                    len(actual), len({address for (network, address), _ in actual})
                )
                self.assertEqual(
                    sorted((amount for _holder, amount in actual), reverse=True),
                    [amount for _holder, amount in actual],
                )

    # TEST-MAP: RGB-ANALYTICS-RPC-11
    def test_large_amount_ranking_uses_exact_integer_values(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                type_hash = LARGE_HOLDER_FIXTURES.get(network.name)
                if type_hash is None:
                    raise unittest.SkipTest(
                        f"{network.name} public index has no stable large-holder fixture"
                    )
                oracle = NetworkOracle(network, self.settings)
                try:
                    balances, _bitcoin_locks, _total = self._chain_balances(
                        oracle, type_hash
                    )
                    rows = self._holders(oracle, type_hash)
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                expected = sorted(balances.values(), reverse=True)
                actual = [int(Decimal(row["amount"])) for row in rows]
                self.assertGreater(max(actual), 2**53 - 1)
                self.assertEqual(expected[:10], actual)
                if len(expected) < 11:
                    raise unittest.SkipTest(
                        f"{network.name} large-holder fixture has fewer than eleven holders"
                    )
                spacing = 1 << max(expected[9].bit_length() - 53, 0)
                if not 0 < expected[9] - expected[10] < spacing:
                    raise unittest.SkipTest(
                        f"{network.name} public top-ten boundary has no sub-double-spacing amount difference"
                    )

    # TEST-MAP: RGB-ANALYTICS-RPC-12
    def test_position_ratio_uses_total_supply_and_stable_five_decimal_format(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                type_hash = MIXED_HOLDER_FIXTURES.get(network.name)
                if type_hash is None:
                    raise unittest.SkipTest(
                        f"{network.name} public index has no ratio fixture"
                    )
                oracle = NetworkOracle(network, self.settings)
                try:
                    balances, _bitcoin_locks, total = self._chain_balances(
                        oracle, type_hash
                    )
                    rows = self._holders(oracle, type_hash)
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertGreater(total, 0)
                with localcontext() as context:
                    context.prec = 80
                    for row in rows:
                        key = (str(row["network"]), str(row["address_hash"]))
                        amount = balances[key]
                        expected = format(Decimal(amount) / Decimal(total), ".5f")
                        self.assertRegex(str(row["position_ratio"]), r"^\d+\.\d{5}$")
                        self.assertEqual(expected, row["position_ratio"])

        network = next(item for item in self.settings.networks if item.name == "mainnet")
        oracle = NetworkOracle(network, self.settings)
        zero_hash = ZERO_SUPPLY_FIXTURES["mainnet"]
        try:
            detail = self._detail(oracle, zero_hash)
            rows = self._holders(oracle, zero_hash)
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        self.assertEqual(0, int(detail["total_amount"]))
        self.assertEqual([], rows)

    # TEST-MAP: RGB-ANALYTICS-RPC-13
    def test_xudt_without_positive_live_balances_returns_empty(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                type_hash = EMPTY_HOLDER_FIXTURES.get(network.name)
                if type_hash is None:
                    raise unittest.SkipTest(
                        f"{network.name} public index has no empty-holder xUDT fixture"
                    )
                oracle = NetworkOracle(network, self.settings)
                try:
                    balances, _bitcoin_locks, _total = self._chain_balances(
                        oracle, type_hash
                    )
                    rows = self._holders(oracle, type_hash)
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual({}, balances)
                self.assertEqual([], rows)


if __name__ == "__main__":
    unittest.main()
