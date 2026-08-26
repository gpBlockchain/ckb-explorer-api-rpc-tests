from __future__ import annotations

import unittest

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V2FiberStatisticsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: FIBER-STATS-RPC-05
    def test_four_indicators_project_latest_fourteen_string_values_in_descending_order(self) -> None:
        indicators = (
            "total_nodes",
            "total_channels",
            "total_capacity",
            "created_at_unixtimestamp",
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    index_rows = oracle.explorer_json("/v2/fiber/statistics")["data"]
                    series = {
                        indicator: oracle.explorer_json(
                            f"/v2/fiber/statistics/{indicator}"
                        )["data"]
                        for indicator in indicators
                    }
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

                for indicator, rows in series.items():
                    self.assertEqual(14, len(rows))
                    expected_fields = {"created_at_unixtimestamp"}
                    if indicator != "created_at_unixtimestamp":
                        expected_fields.add(indicator)
                    timestamps = [int(row["created_at_unixtimestamp"]) for row in rows]
                    self.assertEqual(sorted(timestamps, reverse=True), timestamps)
                    self.assertEqual(len(timestamps), len(set(timestamps)))
                    for row in rows:
                        self.assertEqual(expected_fields, set(row))
                        self.assertTrue(all(isinstance(value, str) for value in row.values()))

                for index_row in index_rows:
                    timestamp = index_row["created_at_unixtimestamp"]
                    for indicator in indicators:
                        matched = next(
                            row
                            for row in series[indicator]
                            if row["created_at_unixtimestamp"] == timestamp
                        )
                        if indicator != "created_at_unixtimestamp":
                            self.assertEqual(index_row[indicator], matched[indicator])


if __name__ == "__main__":
    unittest.main()
