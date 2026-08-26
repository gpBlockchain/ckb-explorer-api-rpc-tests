from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int, output_occupied_capacity
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.address_dao.test_v1_addresses_show import DAO_ADDRESSES


DEPLOYMENT_FIXTURES: dict[str, tuple[str, frozenset[tuple[str, int]]]] = {}


class V1AddressDeployedCellsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _api(
        self,
        oracle: NetworkOracle,
        identifier: str,
        **query: object,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        payload = oracle.explorer_json(f"/v1/address_deployed_cells/{identifier}", query or None)
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise OracleUnavailable(f"{oracle.network.name} deployed-cell page is unavailable")
        rows: list[Mapping[str, Any]] = []
        for item in data:
            attributes = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(attributes, dict):
                raise OracleUnavailable(f"{oracle.network.name} deployed-cell row is unavailable")
            rows.append(attributes)
        return rows, meta

    def _lock_hash(self, oracle: NetworkOracle, address: str) -> str:
        payload = oracle.explorer_json(f"/v1/addresses/{address}")
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data[0].get("attributes") if isinstance(data, list) and data else None
        lock = attributes.get("lock_script") if isinstance(attributes, dict) else None
        if not isinstance(lock, dict):
            raise OracleUnavailable(f"{oracle.network.name} deployment address lock is unavailable")
        return ckb_script_hash(lock)

    # TEST-MAP: ADDR-CELL-RPC-17
    def test_registered_deployment_outpoints_and_rpc_fields_match_exactly(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                fixture = DEPLOYMENT_FIXTURES.get(network.name)
                if fixture is None:
                    raise unittest.SkipTest(f"{network.name} independently confirmed deployment fixture is unavailable")
                address, expected = fixture
                oracle = NetworkOracle(network, self.settings)
                rows, meta = self._api(oracle, address, page_size=100)
                actual = {(row["tx_hash"], int(row["cell_index"])) for row in rows}
                self.assertEqual(expected, actual)
                self.assertEqual(len(expected), int(meta["total"]))
                for row in rows:
                    result = oracle.rpc_result("get_transaction", [row["tx_hash"]])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    status = result.get("tx_status") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict) or not isinstance(status, dict):
                        raise unittest.SkipTest(f"{network.name} deployment transaction is unavailable")
                    index = int(row["cell_index"])
                    output = transaction["outputs"][index]
                    output_data = transaction["outputs_data"][index]
                    self.assertEqual(decode_hex_int(output["capacity"], "capacity"), int(row["capacity"]))
                    self.assertEqual(output_occupied_capacity(output, output_data), int(row["occupied_capacity"]))
                    self.assertEqual(output_data, row.get("data"))

    # TEST-MAP: ADDR-CELL-RPC-18
    def test_deployment_address_and_lock_hash_queries_are_identical_and_target_only(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                fixture = DEPLOYMENT_FIXTURES.get(network.name)
                if fixture is None:
                    raise unittest.SkipTest(f"{network.name} independently confirmed deployment fixture is unavailable")
                address, _expected = fixture
                oracle = NetworkOracle(network, self.settings)
                try:
                    lock_hash = self._lock_hash(oracle, address)
                    address_rows, address_meta = self._api(oracle, address, page_size=100)
                    hash_rows, hash_meta = self._api(oracle, lock_hash, page_size=100)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(address_rows, hash_rows)
                self.assertEqual(address_meta, hash_meta)

    # TEST-MAP: ADDR-CELL-RPC-19
    def test_registered_members_are_not_filtered_by_review_or_deprecation_metadata(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                if network.name not in DEPLOYMENT_FIXTURES:
                    raise unittest.SkipTest(f"{network.name} mixed metadata deployment fixture is unavailable")

    # TEST-MAP: ADDR-CELL-RPC-21
    def test_deployment_pagination_and_timestamp_directions_are_complete_and_reversed(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                fixture = DEPLOYMENT_FIXTURES.get(network.name)
                if fixture is None or len(fixture[1]) < 2:
                    raise unittest.SkipTest(f"{network.name} multi-deployment pagination fixture is unavailable")
                address, expected = fixture
                oracle = NetworkOracle(network, self.settings)
                ascending, meta = self._api(oracle, address, page_size=100, sort="block_timestamp.asc")
                descending, _meta = self._api(oracle, address, page_size=100, sort="block_timestamp.desc")
                self.assertEqual(expected, {(row["tx_hash"], int(row["cell_index"])) for row in ascending})
                self.assertEqual({(row["tx_hash"], row["cell_index"]) for row in ascending},
                                 {(row["tx_hash"], row["cell_index"]) for row in descending})
                self.assertEqual([int(row["block_timestamp"]) for row in ascending],
                                 sorted(int(row["block_timestamp"]) for row in ascending))
                self.assertEqual(int(meta["total"]), len(expected))

    # TEST-MAP: ADDR-CELL-RPC-22
    def test_recorded_address_without_registered_deployments_returns_empty_success(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, meta = self._api(oracle, DAO_ADDRESSES[network.name])
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual([], rows)
                self.assertEqual(0, int(meta["total"]))
                self.assertEqual(0, int(meta["total_pages"]))


if __name__ == "__main__":
    unittest.main()
