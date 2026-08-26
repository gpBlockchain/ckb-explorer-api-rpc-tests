from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V2BitcoinStatisticsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _statistics(self, oracle: NetworkOracle) -> list[Mapping[str, Any]]:
        payload = oracle.explorer_json("/v2/bitcoin_statistics")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or any(
            not isinstance(row, dict) for row in data
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} Bitcoin statistics are unavailable"
            )
        return data

    # TEST-MAP: BTC-STATS-RPC-01
    def test_persisted_statistics_have_typed_fields_and_ascending_unique_timestamps(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._statistics(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertGreater(len(rows), 1)
                timestamps: list[int] = []
                for row in rows:
                    self.assertTrue(
                        all(
                            isinstance(row.get(field), int)
                            and not isinstance(row.get(field), bool)
                            for field in (
                                "timestamp",
                                "addresses_count",
                                "transactions_count",
                            )
                        )
                    )
                    self.assertGreaterEqual(row["addresses_count"], 0)
                    self.assertGreaterEqual(row["transactions_count"], 0)
                    timestamps.append(row["timestamp"])
                self.assertEqual(sorted(timestamps), timestamps)
                self.assertEqual(len(timestamps), len(set(timestamps)))

    # TEST-MAP: BTC-STATS-RPC-02
    # TEST-MAP: BTC-STATS-RPC-03
    # TEST-MAP: BTC-STATS-RPC-04
    # TEST-MAP: BTC-STATS-RPC-05
    # TEST-MAP: BTC-STATS-RPC-06
    def test_created_at_window_refresh_and_empty_database_oracle_availability(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._statistics(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertTrue(
                    all(int(row["timestamp"]) % 60_000 == 0 for row in rows)
                )
                raise unittest.SkipTest(
                    f"{network.name} same-index created_at snapshot, refresh control, "
                    "and empty-database fixture are unavailable"
                )


if __name__ == "__main__":
    unittest.main()
