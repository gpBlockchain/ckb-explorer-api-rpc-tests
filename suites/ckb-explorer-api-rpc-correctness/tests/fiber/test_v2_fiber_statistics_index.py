from __future__ import annotations

import unittest
from collections import defaultdict
from decimal import Decimal

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.fiber import test_v2_fiber_graph_nodes_index as node_support


def decimal_integer(value: object, field: str) -> int:
    number = Decimal(str(value))
    if number != number.to_integral_value():
        raise ValueError(f"{field} is not an integer: {value!r}")
    return int(number)


class V2FiberStatisticsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: FIBER-STATS-RPC-01
    def test_latest_seven_snapshots_have_complete_fields_and_strict_descending_dates(self) -> None:
        expected_fields = {
            "total_nodes",
            "total_channels",
            "total_capacity",
            "mean_value_locked",
            "mean_fee_rate",
            "medium_value_locked",
            "medium_fee_rate",
            "created_at_unixtimestamp",
            "total_liquidity",
        }
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = oracle.explorer_json("/v2/fiber/statistics")["data"]
                    dates = oracle.explorer_json(
                        "/v2/fiber/statistics/created_at_unixtimestamp"
                    )["data"]
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertGreater(len(dates), 7)
                self.assertEqual(7, len(rows))
                self.assertEqual(
                    [row["created_at_unixtimestamp"] for row in dates[:7]],
                    [row["created_at_unixtimestamp"] for row in rows],
                )
                timestamps = [int(row["created_at_unixtimestamp"]) for row in rows]
                self.assertEqual(sorted(timestamps, reverse=True), timestamps)
                self.assertEqual(len(timestamps), len(set(timestamps)))
                self.assertTrue(
                    all(left > right for left, right in zip(timestamps, timestamps[1:]))
                )
                for row in rows:
                    self.assertEqual(expected_fields, set(row))
                    self.assertTrue(
                        all(isinstance(row[field], str) for field in expected_fields - {"total_liquidity"})
                    )
                    self.assertIsInstance(row["total_liquidity"], list)

    # TEST-MAP: FIBER-STATS-RPC-02
    def test_latest_counts_and_total_capacity_match_current_active_graph_snapshot(self) -> None:
        helper = node_support.V2FiberGraphNodesIndexRpcCorrectnessTests()
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    latest = oracle.explorer_json("/v2/fiber/statistics")["data"][0]
                    nodes = helper._all_nodes(oracle)
                    channel_payload = oracle.explorer_json(
                        "/v2/fiber/graph_channels", {"page": 1, "page_size": 100}
                    )
                    channels = channel_payload["data"]["fiber_graph_channels"]
                    if len(channels) != int(channel_payload["meta"]["total"]):
                        raise OracleUnavailable(
                            f"{network.name} Fiber Graph Channel snapshot exceeds one page"
                        )
                except (OracleUnavailable, KeyError, TypeError, ValueError, IndexError) as error:
                    raise unittest.SkipTest(str(error)) from error
                active_nodes = [row for row in nodes if row["deleted_at_timestamp"] is None]
                self.assertEqual(len(active_nodes), int(latest["total_nodes"]))
                self.assertEqual(len(channels), int(latest["total_channels"]))
                self.assertEqual(
                    sum(decimal_integer(row["capacity"], "graph.capacity") for row in channels),
                    decimal_integer(latest["total_capacity"], "statistics.total_capacity"),
                )

    # TEST-MAP: FIBER-STATS-RPC-03
    @unittest.expectedFailure  # The mean fee currently sums both directions but divides by Channel count.
    def test_capacity_and_bidirectional_fee_means_and_medians_follow_integer_formulas(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    latest = oracle.explorer_json("/v2/fiber/statistics")["data"][0]
                    channels = oracle.explorer_json(
                        "/v2/fiber/graph_channels", {"page": 1, "page_size": 100}
                    )["data"]["fiber_graph_channels"]
                    histories: dict[str, dict[str, dict[str, object]]] = {}
                    for node_id in {str(row["node1"]) for row in channels}:
                        history = oracle.explorer_json(
                            f"/v2/fiber/graph_nodes/{node_id}/graph_channels",
                            {"page": 1, "page_size": 100},
                        )["data"]["fiber_graph_channels"]
                        histories[node_id] = {row["channel_outpoint"]: row for row in history}
                except (OracleUnavailable, KeyError, TypeError, ValueError, IndexError) as error:
                    raise unittest.SkipTest(str(error)) from error

                capacities = sorted(
                    decimal_integer(row["capacity"], "graph.capacity") for row in channels
                )
                if not capacities:
                    self.assertEqual("0", latest["mean_value_locked"])
                    self.assertEqual("", latest["medium_value_locked"])
                    self.assertEqual("0", latest["mean_fee_rate"])
                    self.assertEqual("", latest["medium_fee_rate"])
                    continue

                mean_numerator = sum(capacities)
                mean_value = decimal_integer(latest["mean_value_locked"], "mean_value_locked")
                mean_floor, remainder = divmod(mean_numerator, len(capacities))
                self.assertIn(mean_value, {mean_floor, mean_floor + bool(remainder)})
                middle = len(capacities) // 2
                median_numerator = (
                    capacities[middle] * 2
                    if len(capacities) % 2
                    else capacities[middle - 1] + capacities[middle]
                )
                self.assertEqual(0, median_numerator % 2)
                self.assertEqual(
                    median_numerator // 2,
                    decimal_integer(latest["medium_value_locked"], "medium_value_locked"),
                )

                rates: list[int] = []
                for channel in channels:
                    historical = histories[str(channel["node1"])][channel["channel_outpoint"]]
                    for field in ("update_info_of_node1", "update_info_of_node2"):
                        rate = historical[field].get("fee_rate")
                        if rate not in (None, ""):
                            rates.append(int(rate))
                sorted_rates = sorted(rates)
                middle = len(sorted_rates) // 2
                median_rate_numerator = (
                    sorted_rates[middle] * 2
                    if len(sorted_rates) % 2
                    else sorted_rates[middle - 1] + sorted_rates[middle]
                )
                self.assertEqual(0, sum(rates) % len(rates))
                self.assertEqual(0, median_rate_numerator % 2)
                self.assertEqual(
                    median_rate_numerator // 2,
                    decimal_integer(latest["medium_fee_rate"], "medium_fee_rate"),
                )
                self.assertEqual(
                    sum(rates) // len(rates),
                    decimal_integer(latest["mean_fee_rate"], "mean_fee_rate"),
                )

    # TEST-MAP: FIBER-STATS-RPC-04
    @unittest.expectedFailure  # Liquidity currently visits each open Channel once from each endpoint Node.
    def test_open_ckb_and_udt_liquidity_counts_each_channel_once(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    latest = oracle.explorer_json("/v2/fiber/statistics")["data"][0]
                    channels = oracle.explorer_json(
                        "/v2/fiber/graph_channels", {"page": 1, "page_size": 100}
                    )["data"]["fiber_graph_channels"]
                except (OracleUnavailable, KeyError, TypeError, ValueError, IndexError) as error:
                    raise unittest.SkipTest(str(error)) from error

                expected: dict[str, int] = defaultdict(int)
                udt_metadata: dict[str, tuple[str, str, bool]] = {}
                for channel in channels:
                    if channel["closed_transaction_info"]:
                        continue
                    udt = channel["open_transaction_info"]["udt_info"]
                    if udt:
                        type_hash = str(udt["type_hash"])
                        expected[type_hash] += int(udt["amount"])
                        udt_metadata[type_hash] = (
                            str(udt["symbol"]),
                            str(udt["decimal"]),
                            bool(udt["published"]),
                        )
                    else:
                        expected[""] += decimal_integer(channel["capacity"], "graph.capacity")

                actual: dict[str, int] = {}
                for item in latest["total_liquidity"]:
                    type_hash = str(item.get("type_hash", ""))
                    actual[type_hash] = decimal_integer(item["amount"], "liquidity.amount")
                    if type_hash:
                        symbol, decimal, published = udt_metadata[type_hash]
                        self.assertEqual(symbol, item["symbol"])
                        self.assertEqual(decimal, item["decimal"])
                        self.assertEqual(published, item["published"])
                    else:
                        self.assertEqual("CKB", item["symbol"])
                self.assertEqual(dict(expected), actual)

    # TEST-MAP: FIBER-STATS-RPC-07
    def test_underfilled_or_empty_history_is_not_padded(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = oracle.explorer_json("/v2/fiber/statistics")["data"]
                    series = oracle.explorer_json("/v2/fiber/statistics/total_nodes")["data"]
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                if len(rows) == 7 and len(series) == 14:
                    raise unittest.SkipTest(
                        f"{network.name} has no underfilled Fiber Statistic history fixture"
                    )
                self.assertLessEqual(len(rows), 7)
                self.assertLessEqual(len(series), 14)
                self.assertEqual(
                    len(rows), len({row["created_at_unixtimestamp"] for row in rows})
                )
                self.assertEqual(
                    len(series), len({row["created_at_unixtimestamp"] for row in series})
                )


if __name__ == "__main__":
    unittest.main()
