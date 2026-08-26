from __future__ import annotations

import unittest
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V2RgbAssetsStatisticsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _rows(
        self, oracle: NetworkOracle, **query: object
    ) -> list[Mapping[str, Any]]:
        payload = oracle.explorer_json("/v2/rgb_assets_statistics", query)
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) for row in rows
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} RGB asset statistics are unavailable"
            )
        return rows

    # TEST-MAP: RGB-ANALYTICS-RPC-01
    def test_persisted_rows_have_exact_decimal_strings_and_ascending_timestamps(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._rows(oracle)
                    replay = self._rows(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if not rows:
                    raise unittest.SkipTest(
                        f"{network.name} has no persisted RGB statistics snapshot"
                    )

                self.assertEqual(rows, replay)
                self.assertEqual(
                    sorted(int(row["created_at_unixtimestamp"]) for row in rows),
                    [int(row["created_at_unixtimestamp"]) for row in rows],
                )
                self.assertEqual(
                    {"ft_count", "dob_count", "holders_count", "transactions_count"},
                    {str(row["indicator"]) for row in rows},
                )
                self.assertEqual(
                    {"global", "ckb", "btc"},
                    {str(row["network"]) for row in rows},
                )
                for row in rows:
                    self.assertEqual(
                        {
                            "indicator",
                            "value",
                            "network",
                            "created_at_unixtimestamp",
                        },
                        set(row),
                    )
                    self.assertIsInstance(row["value"], str)
                    self.assertIsInstance(row["created_at_unixtimestamp"], str)
                    try:
                        value = Decimal(row["value"])
                        timestamp = Decimal(row["created_at_unixtimestamp"])
                    except InvalidOperation as error:
                        self.fail(f"invalid exact decimal statistic: {error}")
                    self.assertEqual(value, value.to_integral_value())
                    self.assertEqual(timestamp, timestamp.to_integral_value())

    # TEST-MAP: RGB-ANALYTICS-RPC-02
    def test_network_and_comma_separated_indicator_filters_are_exact_intersections(self) -> None:
        queries = (
            {"network": "btc"},
            {"indicators": "ft_count"},
            {"indicators": "holders_count,transactions_count"},
            {"network": "ckb", "indicators": "holders_count,transactions_count"},
            {"network": "global", "indicators": "ft_count,dob_count"},
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    all_rows = self._rows(oracle)
                    actual = [self._rows(oracle, **query) for query in queries]
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error

                for query, rows in zip(queries, actual):
                    networks = (
                        {str(query["network"])}
                        if "network" in query
                        else {"global", "ckb", "btc"}
                    )
                    indicators = (
                        set(str(query["indicators"]).split(","))
                        if "indicators" in query
                        else {
                            "ft_count",
                            "dob_count",
                            "holders_count",
                            "transactions_count",
                        }
                    )
                    expected = [
                        row
                        for row in all_rows
                        if row["network"] in networks
                        and row["indicator"] in indicators
                    ]
                    self.assertCountEqual(expected, rows)
                    self.assertEqual(
                        sorted(int(row["created_at_unixtimestamp"]) for row in rows),
                        [int(row["created_at_unixtimestamp"]) for row in rows],
                    )

    # TEST-MAP: RGB-ANALYTICS-RPC-03
    # TEST-MAP: RGB-ANALYTICS-RPC-04
    # TEST-MAP: RGB-ANALYTICS-RPC-06
    # TEST-MAP: RGB-ANALYTICS-RPC-15
    def test_historical_count_recomputation_requires_the_same_index_snapshot(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._rows(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if not rows:
                    raise unittest.SkipTest(
                        f"{network.name} has no RGB statistic snapshot to recompute"
                    )
                latest = max(int(row["created_at_unixtimestamp"]) for row in rows)
                snapshot = [
                    row
                    for row in rows
                    if int(row["created_at_unixtimestamp"]) == latest
                ]
                if {
                    (row["network"], row["indicator"]) for row in snapshot
                } != {
                    ("global", "ft_count"),
                    ("global", "dob_count"),
                    ("btc", "transactions_count"),
                    ("ckb", "transactions_count"),
                    ("btc", "holders_count"),
                    ("ckb", "holders_count"),
                }:
                    raise unittest.SkipTest(
                        f"{network.name} latest RGB statistics snapshot is incomplete"
                    )
                raise unittest.SkipTest(
                    f"{network.name} public endpoints do not expose the same-index historical snapshot at {latest}"
                )


if __name__ == "__main__":
    unittest.main()
