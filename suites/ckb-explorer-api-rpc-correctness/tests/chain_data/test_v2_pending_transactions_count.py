from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V2PendingTransactionsCountRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _pool(
        self,
        oracle: NetworkOracle,
    ) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
        try:
            result = oracle.rpc_result("get_raw_tx_pool", [True])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        pending = result.get("pending") if isinstance(result, dict) else None
        proposed = result.get("proposed") if isinstance(result, dict) else None
        if not isinstance(pending, dict) or not isinstance(proposed, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC verbose transaction-pool result is unavailable"
            )
        return pending, proposed

    # TEST-MAP: PENDING-RPC-12
    def test_empty_stable_rpc_pool_returns_zero_list_and_count_contracts(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    api_genesis = oracle.detail_attributes(0)
                    rpc_genesis = oracle.block(0)
                    api_tip = oracle.api_tip_height()
                    rpc_tip = oracle.rpc_tip_height()
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                rpc_header = rpc_genesis.get("header")
                self.assertIsInstance(rpc_header, dict)
                self.assertEqual(rpc_header.get("hash"), api_genesis.get("block_hash"))
                self.assertLessEqual(api_tip, rpc_tip)
                self.assertLessEqual(rpc_tip - api_tip, self.settings.max_lag_blocks)

                before_pending, before_proposed = self._pool(oracle)
                if before_pending or before_proposed:
                    raise unittest.SkipTest(f"{network.name} RPC pending/proposed pool is not empty")
                try:
                    list_payload = oracle.explorer_json("/v2/pending_transactions")
                    count_payload = oracle.explorer_json("/v2/pending_transactions/count")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                after_pending, after_proposed = self._pool(oracle)
                if before_pending != after_pending or before_proposed != after_proposed:
                    raise unittest.SkipTest(
                        f"{network.name} RPC pending/proposed transaction-pool snapshot changed"
                    )

                data = list_payload.get("data") if isinstance(list_payload, dict) else None
                meta = list_payload.get("meta") if isinstance(list_payload, dict) else None
                count = count_payload.get("data") if isinstance(count_payload, dict) else None
                self.assertEqual([], data)
                self.assertIsInstance(meta, dict)
                self.assertEqual(0, int(meta.get("total")))
                self.assertEqual(10, int(meta.get("page_size")))
                self.assertIsInstance(count, int)
                self.assertEqual(0, count)


if __name__ == "__main__":
    unittest.main()
