from __future__ import annotations

import unittest

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V2StatisticsTransactionFeesRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # The persisted hourly fee window currently trails the live transaction index by millions of IDs.
    # TEST-MAP: CURRENT-STATS-RPC-12
    @unittest.expectedFailure
    def test_committed_fee_rows_are_the_latest_ten_thousand_exact_fee_over_byte_records(self) -> None:
        mismatches: list[str] = []
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                payload = oracle.explorer_json("/v2/statistics/transaction_fees")
                recent = oracle.explorer_json("/v1/transactions", {"page": 1, "page_size": 100})
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            rows = payload.get("transaction_fee_rates") if isinstance(payload, dict) else None
            recent_rows = recent.get("data") if isinstance(recent, dict) else None
            self.assertIsInstance(rows, list)
            self.assertIsInstance(recent_rows, list)
            self.assertLessEqual(len(rows), 10_000)
            self.assertTrue(all(row["fee_rate"] > 0 and row["timestamp"] > 0 and row["confirmation_time"] > 0 for row in rows))
            latest_index_id = max(int(row["id"]) for row in recent_rows)
            if not rows or int(rows[0]["id"]) < latest_index_id - 10_000:
                mismatches.append(
                    f"{network.name}: fee id {rows[0]['id'] if rows else None}, index id {latest_index_id}"
                )
        self.assertEqual([], mismatches)

    # The endpoint currently returns 21 daily buckets instead of the reviewed latest 20 UTC days.
    # TEST-MAP: CURRENT-STATS-RPC-13
    @unittest.expectedFailure
    def test_pending_and_daily_fee_rows_exclude_zero_bytes_and_use_twenty_utc_days(self) -> None:
        mismatches: list[str] = []
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                payload = oracle.explorer_json("/v2/statistics/transaction_fees")
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            pending = payload.get("pending_transaction_fee_rates")
            daily = payload.get("last_n_days_transaction_fee_rates")
            self.assertIsInstance(pending, list)
            self.assertIsInstance(daily, list)
            self.assertLessEqual(len(pending), 100)
            self.assertTrue(all(row["fee_rate"] > 0 for row in pending))
            if len(daily) != 20:
                mismatches.append(f"{network.name}: {len(daily)} daily rows")
        self.assertEqual([], mismatches)
