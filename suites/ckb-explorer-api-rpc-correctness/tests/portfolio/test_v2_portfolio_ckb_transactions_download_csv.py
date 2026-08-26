from __future__ import annotations

import csv
import io
import json
import unittest
from decimal import Decimal
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import ACTIVITY_TRANSACTIONS
from tests.portfolio.http import portfolio_response
from tests.portfolio import test_v2_portfolio_ckb_transactions_index as transaction_support


CSV_HEADER = [
    "Txn hash", "Blockno", "UnixTimestamp", "Token", "Method", "Token In",
    "Token Out", "Token Balance Change", "TxnFee(CKB)", "date(UTC)",
]


class V2PortfolioCkbTransactionsDownloadCsvRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _csv(self, oracle: NetworkOracle, token: str, **query: object) -> tuple[int, list[list[str]]]:
        path = "/v2/portfolio/ckb_transactions/download_csv"
        if query:
            path += "?" + urlencode(query)
        status, raw = portfolio_response(oracle, path, token=token)
        try:
            rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        except UnicodeDecodeError as error:
            raise OracleUnavailable(f"{oracle.network.name} Portfolio CSV is not UTF-8") from error
        return status, rows

    def _rpc_facts(
        self, oracle: NetworkOracle, tx_hash: str, addresses: list[str]
    ) -> tuple[int, int, int, int, int]:
        target_locks: set[str] = set()
        for address in addresses:
            payload = oracle.explorer_json(f"/v1/addresses/{address}")
            target_locks.add(ckb_script_hash(payload["data"][0]["attributes"]["lock_script"]))
        result = oracle.rpc_result("get_transaction", [tx_hash])
        transaction = result["transaction"]
        status = result["tx_status"]
        block = oracle.rpc_result("get_block", [status["block_hash"]])
        header = block["header"]
        output_total = sum(
            decode_hex_int(output["capacity"], "output.capacity")
            for output in transaction["outputs"]
            if ckb_script_hash(output["lock"]) in target_locks
        )
        previous = oracle.rpc_batch_results(
            [("get_transaction", [item["previous_output"]["tx_hash"]]) for item in transaction["inputs"]]
        )
        input_total = 0
        all_input_capacity = 0
        for item, prior in zip(transaction["inputs"], previous, strict=True):
            index = decode_hex_int(item["previous_output"]["index"], "input.index")
            output = prior["transaction"]["outputs"][index]
            capacity = decode_hex_int(output["capacity"], "input.capacity")
            all_input_capacity += capacity
            if ckb_script_hash(output["lock"]) in target_locks:
                input_total += capacity
        all_output_capacity = sum(
            decode_hex_int(output["capacity"], "output.capacity") for output in transaction["outputs"]
        )
        return (
            decode_hex_int(header["number"], "block.number"),
            decode_hex_int(header["timestamp"], "block.timestamp"),
            input_total,
            output_total,
            all_input_capacity - all_output_capacity,
        )

    def _shannon(self, value: str) -> int:
        shannon = Decimal(value) * Decimal(100_000_000)
        if shannon != shannon.to_integral_value():
            raise AssertionError(f"CSV CKB value lost Shannon precision: {value}")
        return int(shannon)

    # TEST-MAP: PORTFOLIO-ASSET-RPC-10
    def test_default_height_and_timestamp_ranges_include_boundaries_with_exact_ckb_values(self) -> None:
        helper = transaction_support.V2PortfolioCkbTransactionsIndexRpcCorrectnessTests()
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                tx_hash = ACTIVITY_TRANSACTIONS[network.name]
                try:
                    token, addresses = helper._fixture(oracle)
                    height, timestamp, token_in, token_out, fee = self._rpc_facts(oracle, tx_hash, addresses)
                    default = self._csv(oracle, token)
                    height_rows = self._csv(oracle, token, start_number=height, end_number=height)
                    time_rows = self._csv(oracle, token, start_date=timestamp, end_date=timestamp)
                except (OracleUnavailable, KeyError, TypeError, ValueError, IndexError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(200, default[0])
                self.assertEqual(CSV_HEADER, default[1][0])
                self.assertGreater(len(default[1]), 1)
                self.assertEqual(len(default[1][1:]), len({tuple(row) for row in default[1][1:]}))
                for status, table in (height_rows, time_rows):
                    self.assertEqual(200, status)
                    self.assertEqual(CSV_HEADER, table[0])
                    matches = [row for row in table[1:] if row[0] == tx_hash and row[3] == "CKB"]
                    self.assertEqual(1, len(matches))
                    row = matches[0]
                    self.assertEqual(height, int(row[1]))
                    self.assertEqual(timestamp, int(row[2]))
                    self.assertEqual(token_in, self._shannon(row[5]))
                    self.assertEqual(token_out, self._shannon(row[6]))
                    self.assertEqual(abs(token_out - token_in), self._shannon(row[7]))
                    self.assertEqual("PAYMENT SENT" if token_out < token_in else "PAYMENT RECEIVED", row[4])
                    self.assertEqual(fee, self._shannon(row[8]))

    # TEST-MAP: PORTFOLIO-ASSET-RPC-11
    @unittest.expectedFailure  # Malformed numeric ranges currently escape as an HTTP 500 instead of a parameter contract.
    def test_invalid_ranges_are_empty_or_domain_errors_and_do_not_poison_a_valid_retry(self) -> None:
        helper = transaction_support.V2PortfolioCkbTransactionsIndexRpcCorrectnessTests()
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                tx_hash = ACTIVITY_TRANSACTIONS[network.name]
                try:
                    token, addresses = helper._fixture(oracle)
                    height, timestamp, _token_in, _token_out, _fee = self._rpc_facts(oracle, tx_hash, addresses)
                    reverse = self._csv(oracle, token, start_number=height + 1, end_number=height)
                    disjoint = self._csv(oracle, token, start_number=height + 1, end_number=height + 1)
                    malformed_status, malformed_raw = portfolio_response(
                        oracle,
                        "/v2/portfolio/ckb_transactions/download_csv?" + urlencode({"start_date": "not-a-number"}),
                        token=token,
                    )
                    retry = self._csv(oracle, token, start_date=timestamp, end_date=timestamp)
                except (OracleUnavailable, KeyError, TypeError, ValueError, IndexError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual((200, [CSV_HEADER]), reverse)
                self.assertEqual((200, [CSV_HEADER]), disjoint)
                self.assertIn(malformed_status, {400, 422})
                errors = json.loads(malformed_raw)
                self.assertIsInstance(errors, list)
                self.assertTrue(all("data" not in error for error in errors))
                self.assertEqual(200, retry[0])
                self.assertIn(tx_hash, {row[0] for row in retry[1][1:]})


if __name__ == "__main__":
    unittest.main()
