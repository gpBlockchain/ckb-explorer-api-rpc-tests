from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


ACTIVE_ADDRESS_FIXTURES = {
    "mainnet": "bc1q8vk4lv6zr0hp9kgul9stxz7ldz32zqycgcznj4",
    "testnet": "tb1qz7sa4ua3fmsqrktm79yjx6k20353pgnvezwdna",
}

EMPTY_ADDRESS_FIXTURES = {
    "mainnet": "bc1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq9e75rs",
    "testnet": "tb1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq0l98cr",
}


class V2BitcoinAddressesShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _status_cells(
        self, oracle: NetworkOracle, address: str, status: str
    ) -> tuple[list[Mapping[str, Any]], int]:
        payload = oracle.explorer_json(
            f"/v1/address_live_cells/{address}",
            {"bound_status": status, "page_size": 1000},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if (
            not isinstance(data, list)
            or any(not isinstance(row, dict) for row in data)
            or not isinstance(meta, dict)
        ):
            raise OracleUnavailable(
                f"{oracle.network.name} Bitcoin address status cells are unavailable"
            )
        total = int(meta["total"])
        if total != len(data):
            raise OracleUnavailable(
                f"{oracle.network.name} status fixture exceeds one 1000-cell page"
            )
        return data, total

    # TEST-MAP: BTC-ADDR-RPC-01
    # TEST-MAP: BTC-ADDR-RPC-12
    def test_detail_counts_only_bound_and_unbound_live_ckb_cells(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = ACTIVE_ADDRESS_FIXTURES[network.name]
                try:
                    detail = oracle.explorer_json(
                        f"/v2/bitcoin_addresses/{address}"
                    )
                    by_status = {
                        status: self._status_cells(oracle, address, status)
                        for status in ("bound", "unbound", "binding", "normal")
                    }
                    serialized_cells = [
                        row
                        for rows, _total in by_status.values()
                        for row in rows
                    ]
                    rpc_cells = oracle.rpc_batch_results(
                        [
                            (
                                "get_live_cell",
                                [
                                    {
                                        "tx_hash": row["attributes"]["tx_hash"],
                                        "index": hex(
                                            int(row["attributes"]["cell_index"])
                                        ),
                                    },
                                    True,
                                ],
                            )
                            for row in serialized_cells
                        ]
                    )
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error

                self.assertEqual(
                    by_status["bound"][1], int(detail["bound_live_cells_count"])
                )
                self.assertEqual(
                    by_status["unbound"][1], int(detail["unbound_live_cells_count"])
                )
                self.assertGreater(
                    by_status["bound"][1] + by_status["unbound"][1], 0
                )
                if network.name == "testnet":
                    self.assertGreater(by_status["binding"][1], 0)
                    self.assertNotEqual(
                        sum(total for _rows, total in by_status.values()),
                        int(detail["bound_live_cells_count"])
                        + int(detail["unbound_live_cells_count"]),
                    )
                for serialized, live_result in zip(serialized_cells, rpc_cells):
                    attributes = serialized["attributes"]
                    self.assertEqual("live", live_result.get("status"))
                    cell = live_result.get("cell")
                    output = cell.get("output") if isinstance(cell, dict) else None
                    data = cell.get("data") if isinstance(cell, dict) else None
                    self.assertIsInstance(output, dict)
                    self.assertIsInstance(data, dict)
                    self.assertEqual(attributes["capacity"], str(int(output["capacity"], 16)) + ".0")
                    self.assertEqual(attributes["data"], data["content"])

    # TEST-MAP: BTC-ADDR-RPC-02
    def test_unmapped_valid_bitcoin_address_returns_zero_and_empty_assets(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                address = EMPTY_ADDRESS_FIXTURES[network.name]
                try:
                    detail = oracle.explorer_json(
                        f"/v2/bitcoin_addresses/{address}"
                    )
                    cells = oracle.explorer_json(
                        f"/v2/bitcoin_addresses/{address}/rgb_cells"
                    )
                    accounts = oracle.explorer_json(
                        f"/v2/bitcoin_addresses/{address}/udt_accounts"
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(
                    {"unbound_live_cells_count": 0, "bound_live_cells_count": 0},
                    detail,
                )
                self.assertEqual({}, cells["data"]["rgb_cells"])
                self.assertEqual(0, int(cells["meta"]["total"]))
                self.assertEqual([], accounts["data"]["udt_accounts"])


if __name__ == "__main__":
    unittest.main()
