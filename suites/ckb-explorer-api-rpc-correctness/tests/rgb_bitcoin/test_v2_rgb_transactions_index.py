from __future__ import annotations

import os
import unittest
from typing import Any, Mapping

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
BTC_TIME_CODE_HASHES = {
    "mainnet": {
        "0x70d64497a075bd651e98ac030455ea200637ee325a12ad08aff03f1a117e5a62"
    },
    "testnet": {
        "0x00cdf8fab0f8ac638758ebf5ea5e4052b1d71e8a77b9f43139718621f6849326",
        "0x80a09eca26d77cea1f5a69471c59481be7404febf40ee90f886c36a948385b55",
    },
}
BITCOIN_RPC_URLS = {
    "mainnet": "https://bitcoin-rpc.publicnode.com",
    "testnet": "https://bitcoin-testnet-rpc.publicnode.com",
}
DIRECTIONS = ("withinBTC", "in", "leapoutBTC")


class V2RgbTransactionsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.bitcoin_client = JsonHttpClient(
            timeout=max(cls.settings.timeout_seconds, 65),
            retries=cls.settings.transport_retries,
        )

    def _page(
        self, oracle: NetworkOracle, **query: object
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json("/v2/rgb_transactions", query)
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("ckb_transactions") if isinstance(data, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if (
            not isinstance(rows, list)
            or any(not isinstance(row, dict) for row in rows)
            or not isinstance(meta, dict)
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} RGB transaction list is unavailable"
            )
        return rows, meta

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
                    f"{network_name} Bitcoin RPC omitted an RGB transaction"
                )
            transactions[result["txid"]] = result
        if set(transactions) != set(txids):
            raise OracleUnavailable(
                f"{network_name} Bitcoin RPC batch omitted an RGB transaction"
            )
        return transactions

    def _workflow(
        self,
        network_name: str,
        transaction: Mapping[str, Any],
        parents: Mapping[str, Mapping[str, Any]],
    ) -> tuple[str | None, str | None]:
        def lock_type(output: Mapping[str, Any]) -> str | None:
            code_hash = output["lock"]["code_hash"]
            if code_hash in RGBPP_CODE_HASHES[network_name]:
                return "rgbpp"
            if code_hash in BTC_TIME_CODE_HASHES[network_name]:
                return "btc_time"
            return None

        inputs = {
            lock_type(
                parents[item["previous_output"]["tx_hash"]]["outputs"][
                    int(item["previous_output"]["index"], 16)
                ]
            )
            for item in transaction["inputs"]
            if parents[item["previous_output"]["tx_hash"]]["outputs"][
                int(item["previous_output"]["index"], 16)
            ].get("type")
            is not None
        }
        outputs = {
            lock_type(output)
            for output in transaction["outputs"]
            if output.get("type") is not None
        }
        if inputs == {"rgbpp"} and outputs == {"rgbpp"}:
            return "withinBTC", "isomorphic"
        if inputs == {"rgbpp"} and outputs in (
            {"btc_time"},
            {"btc_time", "rgbpp"},
        ):
            return "in", "isomorphic"
        if inputs == {"btc_time"}:
            return "in", "unlock"
        if "rgbpp" not in inputs and "rgbpp" in outputs:
            return "leapoutBTC", "isomorphic"
        return None, None

    # TEST-MAP: RGB-TX-RPC-07
    def test_chain_fields_workflow_cell_changes_and_bitcoin_txid_match_rpc(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = [
                        self._page(
                            oracle,
                            leap_direction=direction,
                            sort="number.desc",
                            page=1,
                            page_size=1,
                        )[0][0]
                        for direction in DIRECTIONS
                    ]
                    transaction_results = oracle.rpc_batch_results(
                        [("get_transaction", [row["tx_hash"]]) for row in rows]
                    )
                    transactions: list[Mapping[str, Any]] = []
                    statuses: list[Mapping[str, Any]] = []
                    parent_hashes: list[str] = []
                    for result in transaction_results:
                        transaction = (
                            result.get("transaction")
                            if isinstance(result, dict)
                            else None
                        )
                        status = (
                            result.get("tx_status")
                            if isinstance(result, dict)
                            else None
                        )
                        if not isinstance(transaction, dict) or not isinstance(
                            status, dict
                        ):
                            raise OracleUnavailable(
                                f"{network.name} CKB RGB transaction is unavailable"
                            )
                        transactions.append(transaction)
                        statuses.append(status)
                        parent_hashes.extend(
                            item["previous_output"]["tx_hash"]
                            for item in transaction["inputs"]
                        )
                    unique_parents = list(dict.fromkeys(parent_hashes))
                    parent_results = oracle.rpc_batch_results(
                        [("get_transaction", [tx_hash]) for tx_hash in unique_parents]
                    )
                    parents = {
                        tx_hash: result["transaction"]
                        for tx_hash, result in zip(unique_parents, parent_results)
                        if isinstance(result, dict)
                        and isinstance(result.get("transaction"), dict)
                    }
                    if len(parents) != len(unique_parents):
                        raise OracleUnavailable(
                            f"{network.name} CKB parent transaction is unavailable"
                        )
                    block_hashes = [str(status["block_hash"]) for status in statuses]
                    headers = oracle.rpc_batch_results(
                        [("get_header", [block_hash]) for block_hash in block_hashes]
                    )
                    bitcoin_txids = [str(row["rgb_txid"]) for row in rows]
                    bitcoin = self._bitcoin_transactions(
                        network.name, list(dict.fromkeys(bitcoin_txids))
                    )
                    v1_transactions = [
                        oracle.explorer_json(f"/v1/transactions/{row['tx_hash']}")
                        for row in rows
                    ]
                    v1_blocks = [
                        oracle.explorer_json(f"/v1/blocks/{block_hash}")
                        for block_hash in block_hashes
                    ]
                except (
                    OracleUnavailable,
                    KeyError,
                    IndexError,
                    TypeError,
                    ValueError,
                ) as error:
                    raise unittest.SkipTest(str(error)) from error

                for row, transaction, header, v1_tx, v1_block in zip(
                    rows, transactions, headers, v1_transactions, v1_blocks
                ):
                    if not isinstance(header, dict):
                        raise unittest.SkipTest(
                            f"{network.name} CKB block header is unavailable"
                        )
                    self.assertEqual(row["tx_hash"], transaction["hash"])
                    self.assertEqual(int(header["number"], 16), int(row["block_number"]))
                    self.assertEqual(
                        int(header["timestamp"], 16), int(row["block_timestamp"])
                    )
                    self.assertEqual(
                        str(row["id"]), str(v1_tx["data"]["id"])
                    )
                    self.assertEqual(
                        str(row["block_id"]), str(v1_block["data"]["id"])
                    )
                    expected_workflow = self._workflow(
                        network.name, transaction, parents
                    )
                    self.assertEqual(
                        expected_workflow,
                        (row["leap_direction"], row["transfer_step"]),
                    )
                    rgb_outputs = [
                        output
                        for output in transaction["outputs"]
                        if output.get("type") is not None
                        and output["lock"]["code_hash"]
                        in RGBPP_CODE_HASHES[network.name]
                    ]
                    self.assertEqual(len(rgb_outputs), int(row["rgb_cell_changes"]))
                    referenced_txids = {
                        bytes.fromhex(output["lock"]["args"][2:])[4:36][::-1].hex()
                        for output in rgb_outputs
                    }
                    if referenced_txids:
                        self.assertIn(row["rgb_txid"], referenced_txids)
                    self.assertEqual(row["rgb_txid"], bitcoin[row["rgb_txid"]]["txid"])

    # TEST-MAP: RGB-TX-RPC-08
    def test_direction_filters_are_exact_subsequences_of_the_unfiltered_list(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    unfiltered, _meta = self._page(
                        oracle, sort="number.desc", page=1, page_size=100
                    )
                    filtered = {
                        direction: self._page(
                            oracle,
                            leap_direction=direction,
                            sort="number.desc",
                            page=1,
                            page_size=100,
                        )[0]
                        for direction in DIRECTIONS
                    }
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                for direction, rows in filtered.items():
                    self.assertTrue(rows)
                    self.assertTrue(
                        all(row["leap_direction"] == direction for row in rows)
                    )
                    expected_prefix = [
                        row for row in unfiltered if row["leap_direction"] == direction
                    ]
                    self.assertEqual(expected_prefix, rows[: len(expected_prefix)])

    # TEST-MAP: RGB-TX-RPC-09
    def test_supported_sort_fields_and_default_have_the_documented_order(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    pages = {
                        sort: self._page(
                            oracle, sort=sort, page=1, page_size=100
                        )[0]
                        for sort in (
                            "number.asc",
                            "number.desc",
                            "confirmation.asc",
                            "confirmation.desc",
                            "time.asc",
                            "time.desc",
                        )
                    }
                    default, _meta = self._page(oracle, page=1, page_size=100)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                for field in ("number", "confirmation"):
                    for order, reverse in (("asc", False), ("desc", True)):
                        values = [
                            int(row["block_number"])
                            for row in pages[f"{field}.{order}"]
                        ]
                        self.assertEqual(sorted(values, reverse=reverse), values)
                for order, reverse in (("asc", False), ("desc", True)):
                    values = [
                        int(row["block_timestamp"])
                        for row in pages[f"time.{order}"]
                    ]
                    self.assertEqual(sorted(values, reverse=reverse), values)
                self.assertEqual(
                    [int(row["block_number"]) for row in pages["number.desc"]],
                    [int(row["block_number"]) for row in default],
                )

    # TEST-MAP: RGB-TX-RPC-10
    @unittest.expectedFailure
    def test_adjacent_pages_match_one_combined_page_and_filtered_totals(self) -> None:
        issues: list[str] = []
        for network in self.settings.networks:
            for direction in (None, *DIRECTIONS):
                with self.subTest(network=network.name, direction=direction):
                    oracle = NetworkOracle(network, self.settings)
                    query: dict[str, object] = {"sort": "number.desc"}
                    if direction is not None:
                        query["leap_direction"] = direction
                    try:
                        first, first_meta = self._page(
                            oracle, **query, page=1, page_size=5
                        )
                        second, second_meta = self._page(
                            oracle, **query, page=2, page_size=5
                        )
                        combined, combined_meta = self._page(
                            oracle, **query, page=1, page_size=10
                        )
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error

                    label = f"{network.name}/{direction or 'all'}"
                    if combined != first + second:
                        issues.append(
                            f"{label}: adjacent pages differ from the combined page"
                        )
                    if len(combined) != len(
                        {row["tx_hash"] for row in combined}
                    ):
                        issues.append(f"{label}: combined page contains duplicate hashes")
                    if not (
                        first_meta["total"]
                        == second_meta["total"]
                        == combined_meta["total"]
                    ):
                        issues.append(f"{label}: pagination totals differ")
                    if int(first_meta["page_size"]) != 5:
                        issues.append(f"{label}: first page_size is not 5")
                    if int(second_meta["page_size"]) != 5:
                        issues.append(f"{label}: second page_size is not 5")
                    if int(combined_meta["page_size"]) != 10:
                        issues.append(f"{label}: combined page_size is not 10")
        self.assertFalse(issues, "; ".join(issues))


if __name__ == "__main__":
    unittest.main()
