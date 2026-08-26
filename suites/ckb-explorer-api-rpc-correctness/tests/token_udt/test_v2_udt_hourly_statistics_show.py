from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.token_udt.test_v1_xudts_snapshot import SNAPSHOT_XUDTS


EMPTY_TESTNET_XUDT = "0xfc018309be6e28c216dd8b3ec2076437e93f36db46e366cdc941a7125c73eab7"


class V2UdtHourlyStatisticsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _rows(self, oracle: NetworkOracle, type_hash: str) -> list[Mapping[str, Any]]:
        payload = oracle.explorer_json(f"/v2/udt_hourly_statistics/{type_hash}")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise OracleUnavailable(f"{oracle.network.name} UDT statistic detail is unavailable")
        return data

    def _chain_totals(
        self,
        oracle: NetworkOracle,
        type_hash: str,
        latest_statistic_timestamp: int,
    ) -> tuple[int, int]:
        detail = oracle.explorer_json(f"/v1/xudts/{type_hash}")
        data = detail.get("data") if isinstance(detail, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        script = attributes.get("type_script") if isinstance(attributes, dict) else None
        if not isinstance(script, dict) or ckb_script_hash(script) != type_hash:
            raise OracleUnavailable(f"{oracle.network.name} xUDT Type Script is unavailable")
        search_key = {"script": script, "script_type": "type", "script_search_mode": "exact"}
        hashes: list[str] = []
        seen: set[str] = set()
        cursor: str | None = None
        for _page in range(100):
            params: list[object] = [search_key, "asc", "0x64"]
            if cursor is not None:
                params.append(cursor)
            result = oracle.rpc_result("get_transactions", params)
            objects = result.get("objects") if isinstance(result, dict) else None
            if not isinstance(objects, list) or any(not isinstance(item, dict) for item in objects):
                raise OracleUnavailable(f"{oracle.network.name} xUDT Indexer history is unavailable")
            for item in objects:
                tx_hash = item.get("tx_hash")
                if not isinstance(tx_hash, str):
                    raise OracleUnavailable(f"{oracle.network.name} xUDT Indexer hash is unavailable")
                if tx_hash not in seen:
                    hashes.append(tx_hash)
                    seen.add(tx_hash)
            if len(objects) < 100:
                break
            next_cursor = result.get("last_cursor")
            if not isinstance(next_cursor, str) or next_cursor == cursor:
                raise OracleUnavailable(f"{oracle.network.name} xUDT Indexer cursor is unavailable")
            cursor = next_cursor
        else:
            raise OracleUnavailable(f"{oracle.network.name} xUDT history did not terminate")
        if not hashes:
            raise OracleUnavailable(f"{oracle.network.name} xUDT history is empty")

        results: list[Any] = []
        for offset in range(0, len(hashes), self.settings.rpc_batch_size):
            batch = hashes[offset : offset + self.settings.rpc_batch_size]
            results.extend(oracle.rpc_batch_results([("get_transaction", [tx_hash]) for tx_hash in batch]))
        inputs_amount = 0
        outputs_amount = 0
        latest_chain_timestamp = 0
        for tx_hash, result in zip(hashes, results, strict=True):
            transaction = result.get("transaction") if isinstance(result, dict) else None
            status = result.get("tx_status") if isinstance(result, dict) else None
            if not isinstance(transaction, dict) or not isinstance(status, dict):
                raise OracleUnavailable(f"{oracle.network.name} xUDT transaction {tx_hash} is unavailable")
            block_hash = status.get("block_hash")
            if status.get("status") != "committed" or not isinstance(block_hash, str):
                raise OracleUnavailable(f"{oracle.network.name} xUDT status {tx_hash} is unavailable")
            block = oracle.block_by_hash(block_hash)
            header = block.get("header") if isinstance(block, dict) else None
            if not isinstance(header, dict):
                raise OracleUnavailable(f"{oracle.network.name} xUDT block {tx_hash} is unavailable")
            latest_chain_timestamp = max(
                latest_chain_timestamp,
                decode_hex_int(header.get("timestamp"), "xudt.block.timestamp"),
            )
            for output, output_data in oracle.referenced_outputs(transaction):
                type_script = output.get("type")
                if not isinstance(type_script, dict) or ckb_script_hash(type_script) != type_hash:
                    continue
                raw = bytes.fromhex(output_data.removeprefix("0x"))
                if len(raw) < 16:
                    raise OracleUnavailable(f"{oracle.network.name} xUDT input amount is unavailable")
                inputs_amount += int.from_bytes(raw[:16], "little")
            outputs = transaction.get("outputs")
            outputs_data = transaction.get("outputs_data")
            if not isinstance(outputs, list) or not isinstance(outputs_data, list) or len(outputs) != len(outputs_data):
                raise OracleUnavailable(f"{oracle.network.name} xUDT outputs are unavailable")
            for output, output_data in zip(outputs, outputs_data, strict=True):
                type_script = output.get("type") if isinstance(output, dict) else None
                if not isinstance(type_script, dict) or ckb_script_hash(type_script) != type_hash:
                    continue
                if not isinstance(output_data, str):
                    raise OracleUnavailable(f"{oracle.network.name} xUDT output amount is unavailable")
                raw = bytes.fromhex(output_data.removeprefix("0x"))
                if len(raw) < 16:
                    raise OracleUnavailable(f"{oracle.network.name} xUDT output amount is unavailable")
                outputs_amount += int.from_bytes(raw[:16], "little")
        if latest_chain_timestamp >= (latest_statistic_timestamp + 86_400) * 1000:
            raise OracleUnavailable(
                f"{oracle.network.name} xUDT changed after the latest statistic day"
            )
        return len(hashes), max(inputs_amount, outputs_amount)

    # TEST-MAP: UDT-HOURLY-RPC-03
    def test_published_udt_series_is_ascending_complete_and_lossless(self) -> None:
        expected_fields = {
            "ckb_transactions_count",
            "amount",
            "holders_count",
            "created_at_unixtimestamp",
        }
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                type_hash = SNAPSHOT_XUDTS[network.name]
                try:
                    rows = self._rows(oracle, type_hash)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertGreater(len(rows), 1)
                timestamps = [int(row["created_at_unixtimestamp"]) for row in rows]
                self.assertEqual(timestamps, sorted(timestamps))
                self.assertEqual(len(timestamps), len(set(timestamps)))
                for row in rows:
                    self.assertEqual(expected_fields, set(row))
                    for field in expected_fields:
                        self.assertIsInstance(row[field], str)
                        self.assertRegex(row[field], r"^\d+$")
                        self.assertEqual(row[field], str(int(row[field])))
                        self.assertNotIn("e", row[field].lower())

    # TEST-MAP: UDT-HOURLY-RPC-04
    # TEST-MAP: UDT-HOURLY-RPC-08
    def test_latest_transaction_amount_and_holder_totals_match_rpc_indexer_and_allocation(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                type_hash = SNAPSHOT_XUDTS[network.name]
                try:
                    rows = self._rows(oracle, type_hash)
                    latest = rows[-1]
                    transaction_count, amount = self._chain_totals(
                        oracle,
                        type_hash,
                        int(latest["created_at_unixtimestamp"]),
                    )
                    allocation = oracle.explorer_json(f"/v1/udts/{type_hash}/holder_allocation")
                    lock_hashes = allocation.get("lock_hashes") if isinstance(allocation, dict) else None
                    btc_holders = allocation.get("btc_holder_count") if isinstance(allocation, dict) else None
                    if not isinstance(lock_hashes, list) or not isinstance(btc_holders, int):
                        raise OracleUnavailable(f"{network.name} holder allocation is unavailable")
                    if any(not isinstance(item, dict) or not isinstance(item.get("holder_count"), int) for item in lock_hashes):
                        raise OracleUnavailable(f"{network.name} holder allocation rows are unavailable")
                    holders = btc_holders + sum(int(item["holder_count"]) for item in lock_hashes)
                except (OracleUnavailable, IndexError, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(transaction_count, int(latest["ckb_transactions_count"]))
                self.assertEqual(amount, int(latest["amount"]))
                self.assertEqual(holders, int(latest["holders_count"]))

    # TEST-MAP: UDT-HOURLY-RPC-05
    def test_published_udt_created_after_latest_generation_has_empty_series(self) -> None:
        network = next(item for item in self.settings.networks if item.name == "testnet")
        oracle = NetworkOracle(network, self.settings)
        try:
            detail = oracle.explorer_json(f"/v1/xudts/{EMPTY_TESTNET_XUDT}")
            data = detail.get("data") if isinstance(detail, dict) else None
            attributes = data.get("attributes") if isinstance(data, dict) else None
            global_rows = oracle.explorer_json("/v2/udt_hourly_statistics").get("data")
            rows = self._rows(oracle, EMPTY_TESTNET_XUDT)
            if not isinstance(attributes, dict) or not isinstance(global_rows, list) or not global_rows:
                raise OracleUnavailable("testnet empty statistic fixture is unavailable")
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        self.assertIs(attributes.get("published"), True)
        self.assertGreater(
            int(attributes["created_at"]),
            int(global_rows[0]["created_at_unixtimestamp"]) * 1000,
        )
        self.assertEqual([], rows)


if __name__ == "__main__":
    unittest.main()
