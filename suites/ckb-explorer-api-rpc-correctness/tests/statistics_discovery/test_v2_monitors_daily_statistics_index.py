from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


BEIJING = timezone(timedelta(hours=8))


class V2MonitorsDailyStatisticsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: HIST-STATS-RPC-17
    @unittest.expectedFailure
    def test_yesterday_latest_daily_record_reports_ok(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    history = oracle.explorer_json("/v1/daily_statistics/transactions_count")
                    monitor = oracle.explorer_json("/v2/monitors/daily_statistics")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                rows = history.get("data") if isinstance(history, dict) else None
                self.assertIsInstance(rows, list)
                self.assertTrue(rows)
                latest = int(rows[-1]["attributes"]["created_at_unixtimestamp"])
                latest_date = datetime.fromtimestamp(latest, BEIJING).date()
                yesterday = datetime.now(BEIJING).date() - timedelta(days=1)
                if latest_date != yesterday:
                    raise unittest.SkipTest(f"{network.name} latest Daily record is {latest_date}, not yesterday")
                self.assertEqual({"status": "ok"}, monitor)

    # TEST-MAP: HIST-STATS-RPC-18
    def test_stale_latest_daily_record_reports_error(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    history = oracle.explorer_json("/v1/daily_statistics/transactions_count")
                    monitor = oracle.explorer_json("/v2/monitors/daily_statistics")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                rows = history.get("data") if isinstance(history, dict) else None
                self.assertIsInstance(rows, list)
                self.assertTrue(rows)
                latest = int(rows[-1]["attributes"]["created_at_unixtimestamp"])
                latest_date = datetime.fromtimestamp(latest, BEIJING).date()
                yesterday = datetime.now(BEIJING).date() - timedelta(days=1)
                if latest_date == yesterday:
                    raise unittest.SkipTest(f"{network.name} latest Daily record is current")
                self.assertEqual({"status": "error"}, monitor)
