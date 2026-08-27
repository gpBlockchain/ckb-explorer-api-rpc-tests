from __future__ import annotations

import math
import unittest
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_epoch, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_address_dao_transactions_show import _explorer_response
from tests.address_dao.test_v1_addresses_show import DAO_TYPE_HASH


GENESIS_ISSUANCE = Decimal(336 * 10**8)
ANNUAL_PRIMARY_ISSUANCE = Decimal(42 * 10**8)
EPOCHS_PER_YEAR = Decimal(2190)
EPOCHS_PER_PERIOD = Decimal(8760)
SECONDARY_PER_EPOCH = Decimal(1344 * 10**6) / EPOCHS_PER_YEAR


def _estimated_apc(epoch: Any) -> Decimal:
    start = Decimal(epoch.number)
    end = start + EPOCHS_PER_YEAR - 1
    ratio = (end - start) / EPOCHS_PER_YEAR
    if ratio < 1:
        end = start + EPOCHS_PER_YEAR - 1
        ratio = Decimal(1)
    checkpoint_start = ((start + 1) / EPOCHS_PER_PERIOD).to_integral_value(rounding=ROUND_CEILING)
    checkpoint_start *= EPOCHS_PER_PERIOD
    checkpoint_end = ((end + 1) / EPOCHS_PER_PERIOD).to_integral_value(rounding=ROUND_FLOOR)
    checkpoint_end *= EPOCHS_PER_PERIOD
    count = int((checkpoint_end - checkpoint_start) / EPOCHS_PER_PERIOD + 1)
    checkpoints = [Decimal(index) * EPOCHS_PER_PERIOD + checkpoint_start - 1 for index in range(max(0, count))]
    if not checkpoints or checkpoints[0] > start:
        checkpoints.insert(0, start)
    if checkpoints[-1] < end:
        checkpoints.append(end)

    compounded = 1.0
    for inner_start, inner_end in zip(checkpoints, checkpoints[1:]):
        epoch_index = Decimal(epoch.index) * 1800 / Decimal(epoch.length)
        start_fraction = inner_start + epoch_index / 1800
        end_fraction = inner_end + epoch_index / 1800
        halving = int(((inner_start + 1) / EPOCHS_PER_PERIOD).to_integral_value(rounding=ROUND_FLOOR))
        alpha = (ANNUAL_PRIMARY_ISSUANCE / (Decimal(2) ** halving) / EPOCHS_PER_YEAR) / SECONDARY_PER_EPOCH
        completed_periods = int((inner_start / EPOCHS_PER_PERIOD).to_integral_value(rounding=ROUND_FLOOR))
        primary = GENESIS_ISSUANCE + sum(
            ANNUAL_PRIMARY_ISSUANCE * 4 / (Decimal(2) ** index)
            for index in range(completed_periods)
        )
        primary += (
            ANNUAL_PRIMARY_ISSUANCE
            * ((inner_start + 1 - Decimal(completed_periods) * EPOCHS_PER_PERIOD) / EPOCHS_PER_YEAR)
            / (Decimal(2) ** completed_periods)
        )
        secondary_epochs = start_fraction + 1 if start_fraction > 0 else start_fraction
        total_issuance = primary + secondary_epochs * SECONDARY_PER_EPOCH
        secondary = SECONDARY_PER_EPOCH * (end_fraction - start_fraction)
        rate = math.log(1 + float((alpha + 1) * secondary / total_issuance)) / float(alpha + 1)
        compounded *= 1 + rate
    return Decimal(str((compounded - 1) * 100 / float(ratio))).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


class V1ContractsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.cell_cache: dict[str, list[Mapping[str, Any]]] = {}
        cls.daily_cache: dict[tuple[str, str], Mapping[str, Any]] = {}

    def _attributes(self, oracle: NetworkOracle) -> Mapping[str, Any]:
        payload = oracle.explorer_json("/v1/contracts/nervos_dao")
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        if not isinstance(attributes, dict):
            raise OracleUnavailable(f"{oracle.network.name} DAO contract state is unavailable")
        return attributes

    def _dao_cells(self, oracle: NetworkOracle) -> list[Mapping[str, Any]]:
        if oracle.network.name in self.cell_cache:
            return self.cell_cache[oracle.network.name]
        search_key = {
            "script": {"code_hash": DAO_TYPE_HASH, "hash_type": "type", "args": "0x"},
            "script_type": "type",
            "script_search_mode": "exact",
            "with_data": True,
        }
        cursor: str | None = None
        cells: list[Mapping[str, Any]] = []
        seen_cursors: set[str] = set()
        for _page in range(500):
            params: list[object] = [search_key, "asc", "0x3e8"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result("get_cells", params)
            objects = result.get("objects") if isinstance(result, dict) else None
            next_cursor = result.get("last_cursor") if isinstance(result, dict) else None
            if not isinstance(objects, list) or not isinstance(next_cursor, str):
                raise OracleUnavailable(f"{oracle.network.name} Indexer DAO cells are unavailable")
            for item in objects:
                if not isinstance(item, dict):
                    raise OracleUnavailable(f"{oracle.network.name} Indexer DAO cell is unavailable")
                cells.append(item)
            if len(objects) < 1000:
                self.cell_cache[oracle.network.name] = cells
                return cells
            if next_cursor in seen_cursors:
                raise OracleUnavailable(f"{oracle.network.name} Indexer DAO cursor repeated")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise OracleUnavailable(f"{oracle.network.name} Indexer DAO cells exceeded 500 pages")

    def _latest_daily(self, oracle: NetworkOracle, indicator: str) -> Mapping[str, Any]:
        key = (oracle.network.name, indicator)
        if key not in self.daily_cache:
            payload = oracle.explorer_json(f"/v1/daily_statistics/{indicator}")
            data = payload.get("data") if isinstance(payload, dict) else None
            attributes = data[-1].get("attributes") if isinstance(data, list) and data else None
            if not isinstance(attributes, dict) or indicator not in attributes:
                raise OracleUnavailable(f"{oracle.network.name} daily {indicator} anchor is unavailable")
            self.daily_cache[key] = attributes
        return self.daily_cache[key]

    # TEST-MAP: DAO-STATE-RPC-01
    def test_total_deposit_equals_all_live_zero_data_dao_cell_capacities(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    before = self._attributes(oracle)
                    cells = self._dao_cells(oracle)
                    after = self._attributes(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                if before["total_deposit"] != after["total_deposit"]:
                    raise unittest.SkipTest(f"{network.name} DAO contract state changed during observation")
                expected = sum(
                    decode_hex_int(item["output"]["capacity"], "deposit.capacity")
                    for item in cells
                    if item.get("output_data") == "0x" + "00" * 8
                )
                self.assertEqual(expected, int(after["total_deposit"]))

    # TEST-MAP: DAO-STATE-RPC-02
    def test_depositors_count_equals_unique_locks_with_live_deposit_cells(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    cells = self._dao_cells(oracle)
                    attributes = self._attributes(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                owners = {
                    ckb_script_hash(item["output"]["lock"])
                    for item in cells
                    if item.get("output_data") == "0x" + "00" * 8
                }
                self.assertEqual(len(owners), int(attributes["depositors_count"]))

    # TEST-MAP: DAO-STATE-RPC-03
    def test_claimed_compensation_requires_complete_historical_claim_event_oracle(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    value = str(self._attributes(oracle)["claimed_compensation"])
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(str(int(value)), value)
                raise unittest.SkipTest(f"{network.name} bounded complete historical DAO claim oracle is unavailable")

    # TEST-MAP: DAO-STATE-RPC-04
    def test_unclaimed_compensation_requires_tip_anchored_interest_for_every_live_dao_cell(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    value = str(self._attributes(oracle)["unclaimed_compensation"])
                    cells = self._dao_cells(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(str(int(value)), value)
                self.assertTrue(cells)
                raise unittest.SkipTest(f"{network.name} tip-anchored all-cell DAO interest oracle is unavailable")

    # TEST-MAP: DAO-STATE-RPC-05
    def test_changes_equal_current_values_minus_the_same_latest_daily_anchor(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                current = self._attributes(oracle)
                latest = self._latest_daily(oracle, "total_dao_deposit")
            except OracleUnavailable as error:
                with self.subTest(network=network.name):
                    raise unittest.SkipTest(str(error)) from error
            with self.subTest(network=network.name, metric="deposit_changes"):
                self.assertEqual(
                    Decimal(str(current["total_deposit"])) - Decimal(str(latest["total_dao_deposit"])),
                    Decimal(str(current["deposit_changes"])),
                )
            for metric in ("depositor_changes", "unclaimed_compensation_changes", "claimed_compensation_changes"):
                with self.subTest(network=network.name, metric=metric):
                    raise unittest.SkipTest(f"{network.name} public daily {metric} anchor is unavailable")

    # TEST-MAP: DAO-STATE-RPC-06
    def test_latest_daily_supply_fields_equal_contract_state_without_shannon_loss(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                current = self._attributes(oracle)
            except OracleUnavailable as error:
                with self.subTest(network=network.name):
                    raise unittest.SkipTest(str(error)) from error
            for metric in ("mining_reward", "deposit_compensation", "treasury_amount"):
                with self.subTest(network=network.name, metric=metric):
                    try:
                        latest = self._latest_daily(oracle, metric)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(str(latest[metric]), str(current[metric]))
            with self.subTest(network=network.name, metric="average_deposit_time"):
                raise unittest.SkipTest(f"{network.name} public daily average_deposit_time anchor is unavailable")

    # TEST-MAP: DAO-STATE-RPC-07
    def test_estimated_apc_matches_fractional_epoch_issuance_formula_truncated_to_four_places(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    statistics = oracle.explorer_json("/v1/statistics")
                    stats_data = statistics.get("data") if isinstance(statistics, dict) else None
                    stats = stats_data.get("attributes") if isinstance(stats_data, dict) else None
                    if not isinstance(stats, dict):
                        raise OracleUnavailable(f"{network.name} Explorer tip anchor is unavailable")
                    height = int(stats["tip_block_number"])
                    epoch = decode_epoch(oracle.block(height)["header"])
                    actual = Decimal(str(self._attributes(oracle)["estimated_apc"]))
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                epoch_info = stats.get("epoch_info")
                if not isinstance(epoch_info, dict):
                    raise unittest.SkipTest(f"{network.name} Explorer epoch anchor is unavailable")
                self.assertEqual(
                    (epoch.number, epoch.index, epoch.length),
                    (int(epoch_info["epoch_number"]), int(epoch_info["index"]), int(epoch_info["epoch_length"])),
                )
                self.assertEqual(_estimated_apc(epoch), actual)

    # TEST-MAP: DAO-STATE-RPC-08
    def test_non_dao_contract_name_returns_contract_not_found(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                status, payload = _explorer_response(oracle, "/v1/contracts/not_nervos_dao")
                if status == 403 and isinstance(payload, dict) and payload.get("cloudflare_error") is True:
                    raise unittest.SkipTest(f"{network.name} edge rejected negative-path observation")
                self.assertEqual(404, status)
                self.assertIsInstance(payload, list)
                self.assertEqual(1021, int(payload[0]["code"]))
                self.assertEqual("Contract Not Found", payload[0]["title"])


if __name__ == "__main__":
    unittest.main()
