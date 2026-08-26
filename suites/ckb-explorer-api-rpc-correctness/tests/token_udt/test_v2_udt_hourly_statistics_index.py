from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V2UdtHourlyStatisticsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _rows(self, oracle: NetworkOracle) -> list[Mapping[str, Any]]:
        payload = oracle.explorer_json("/v2/udt_hourly_statistics")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise OracleUnavailable(f"{oracle.network.name} UDT statistic buckets are unavailable")
        return data

    # TEST-MAP: UDT-HOURLY-RPC-01
    def test_global_buckets_are_unique_descending_field_isolated_decimal_aggregates(self) -> None:
        expected_fields = {
            "ckb_transactions_count",
            "holders_count",
            "created_at_unixtimestamp",
        }
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._rows(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertGreater(len(rows), 1)
                timestamps = [int(row["created_at_unixtimestamp"]) for row in rows]
                self.assertEqual(len(timestamps), len(set(timestamps)))
                self.assertEqual(timestamps, sorted(timestamps, reverse=True))
                for row in rows:
                    self.assertEqual(expected_fields, set(row))
                    self.assertNotIn("amount", row)
                    for field in expected_fields:
                        self.assertIsInstance(row[field], str)
                        self.assertRegex(row[field], r"^\d+$")
                        self.assertEqual(row[field], str(int(row[field])))
                        self.assertNotIn("e", row[field].lower())

    # TEST-MAP: UDT-HOURLY-RPC-02
    def test_values_above_javascript_safe_integer_remain_canonical_decimal_strings(self) -> None:
        observed_large_value = False
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._rows(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                large = [
                    (field, row[field])
                    for row in rows
                    for field in (
                        "ckb_transactions_count",
                        "holders_count",
                        "created_at_unixtimestamp",
                    )
                    if int(row[field]) > 2**53 - 1
                ]
                for _field, value in large:
                    observed_large_value = True
                    self.assertIsInstance(value, str)
                    self.assertRegex(value, r"^\d+$")
                    self.assertEqual(value, str(int(value)))
                    self.assertNotIn("e", value.lower())
        if not observed_large_value:
            self.skipTest("public UDT statistic buckets have no value above 2^53-1")


if __name__ == "__main__":
    unittest.main()
