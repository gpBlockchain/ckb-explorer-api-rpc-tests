from __future__ import annotations

import unittest

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V2StatisticsContractResourceDistributedRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: CURRENT-STATS-RPC-14
    def test_unfiltered_rows_are_active_contracts_with_all_nonzero_index_dimensions(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows = oracle.explorer_json("/v2/statistics/contract_resource_distributed")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertIsInstance(rows, list)
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(
                        {"name", "code_hash", "hash_type", "tx_count", "h24_tx_count", "ckb_amount", "address_count"},
                        set(row),
                    )
                    self.assertGreater(int(row["tx_count"]), 0)
                    self.assertGreater(int(row["address_count"]), 0)
                    self.assertGreater(float(row["ckb_amount"]), 0)
                    self.assertGreaterEqual(int(row["h24_tx_count"]), 0)
                raise unittest.SkipTest(
                    f"{network.name} public RPC/Indexer has no atomic global contract association-count snapshot"
                )

    # TEST-MAP: CURRENT-STATS-RPC-15
    def test_type_hash_filter_is_exact_multi_value_and_capacity_is_plain_ckb_decimal(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    catalog = oracle.explorer_json("/v2/scripts", {"page_size": 100}).get("data")
                    all_rows = oracle.explorer_json("/v2/statistics/contract_resource_distributed")
                    published_hashes = {row.get("type_hash") for row in catalog if isinstance(row, dict)}
                    candidates = [row["code_hash"] for row in all_rows if row.get("code_hash") in published_hashes]
                    if not candidates:
                        raise OracleUnavailable(f"{network.name} published Active contract fixture is unavailable")
                    selected = candidates[:2]
                    filtered = oracle.explorer_json(
                        "/v2/statistics/contract_resource_distributed", {"code_hashes": ",".join(selected)}
                    )
                    missing = oracle.explorer_json(
                        "/v2/statistics/contract_resource_distributed", {"code_hashes": "0x" + "ff" * 32}
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertTrue(filtered)
                self.assertTrue(all(row["code_hash"] in set(selected) for row in filtered))
                self.assertEqual([], missing)
                for row in filtered:
                    text = str(row["ckb_amount"])
                    self.assertRegex(text, r"^\d+(?:\.\d{1,8})?$")
                    self.assertNotIn("e", text.lower())
