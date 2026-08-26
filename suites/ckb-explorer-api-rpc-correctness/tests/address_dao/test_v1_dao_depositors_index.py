from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


DAO_CODE_HASH = "0x82d76d1b75fe2fd9a27dfbaa65a039221a380d76c926f378d3f81cf3e7e13f2e"


class V1DaoDepositorsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _rows(self, oracle: NetworkOracle) -> list[Mapping[str, Any]]:
        payload = oracle.explorer_json("/v1/dao_depositors")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise OracleUnavailable(f"{oracle.network.name} DAO depositor list is unavailable")
        rows: list[Mapping[str, Any]] = []
        for item in data:
            attributes = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(attributes, dict):
                raise OracleUnavailable(f"{oracle.network.name} DAO depositor row is unavailable")
            rows.append(attributes)
        return rows

    def _live_deposit(self, oracle: NetworkOracle, address: str) -> int:
        payload = oracle.explorer_json(f"/v1/addresses/{address}")
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data[0].get("attributes") if isinstance(data, list) and data else None
        lock = attributes.get("lock_script") if isinstance(attributes, dict) else None
        if not isinstance(lock, dict):
            raise OracleUnavailable(f"{oracle.network.name} depositor lock is unavailable")
        core_lock = {key: lock[key] for key in ("args", "code_hash", "hash_type")}
        search_key = {"script": core_lock, "script_type": "lock", "script_search_mode": "exact"}
        cursor: str | None = None
        total = 0
        for _page in range(100):
            params: list[object] = [search_key, "asc", "0x64"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result("get_cells", params)
            objects = result.get("objects") if isinstance(result, dict) else None
            next_cursor = result.get("last_cursor") if isinstance(result, dict) else None
            if not isinstance(objects, list) or not isinstance(next_cursor, str):
                raise OracleUnavailable(f"{oracle.network.name} Indexer cells are unavailable")
            for item in objects:
                output = item.get("output") if isinstance(item, dict) else None
                type_script = output.get("type") if isinstance(output, dict) else None
                if (
                    isinstance(type_script, dict)
                    and type_script.get("code_hash") == DAO_CODE_HASH
                    and type_script.get("hash_type") == "type"
                    and type_script.get("args") == "0x"
                    and item.get("output_data") == "0x" + "00" * 8
                ):
                    total += decode_hex_int(output.get("capacity"), "deposit.capacity")
            if len(objects) < 100:
                return total
            cursor = next_cursor
        raise OracleUnavailable(f"{oracle.network.name} depositor cells exceeded 100 pages")

    # TEST-MAP: DAO-STATE-RPC-09
    def test_top_depositor_capacities_match_live_deposit_cells_and_average_is_truncated(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._rows(oracle)
                    samples = rows[:3]
                    expected = {
                        row["address_hash"]: self._live_deposit(oracle, str(row["address_hash"]))
                        for row in samples
                    }
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(3, len(samples))
                for row in samples:
                    address = str(row["address_hash"])
                    self.assertGreater(expected[address], 0)
                    self.assertEqual(expected[address], int(row["dao_deposit"]))
                    average = str(row["average_deposit_time"])
                    self.assertEqual(Decimal(average), Decimal(average).quantize(Decimal("0.001")) if "." in average else Decimal(average))
                    self.assertLessEqual(len(average.partition(".")[2]), 3)

    # TEST-MAP: DAO-STATE-RPC-10
    def test_public_depositor_ranking_is_capped_at_one_hundred_and_descending(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = self._rows(oracle)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                deposits = [int(row["dao_deposit"]) for row in rows]
                self.assertLessEqual(len(rows), 100)
                self.assertEqual(100, len(rows))
                self.assertEqual(deposits, sorted(deposits, reverse=True))
                self.assertTrue(all(value > 0 for value in deposits))
                self.assertEqual(len(rows), len({row["address_hash"] for row in rows}))


if __name__ == "__main__":
    unittest.main()
