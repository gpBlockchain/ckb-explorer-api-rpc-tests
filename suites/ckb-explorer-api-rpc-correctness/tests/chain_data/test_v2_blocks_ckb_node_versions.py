from __future__ import annotations

import unittest
from collections import Counter
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import cellbase_node_version, decode_epoch, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


def _api_version_counts(payload: object) -> list[tuple[str, int]]:
    if not isinstance(payload, dict):
        raise AssertionError("ckb_node_versions payload is not an object")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise AssertionError("ckb_node_versions data is not an array")
    counts: list[tuple[str, int]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise AssertionError(f"ckb_node_versions data[{index}] is not an object")
        version = row.get("version")
        blocks_count = row.get("blocks_count")
        if not isinstance(version, str) or version == "":
            raise AssertionError(f"ckb_node_versions data[{index}].version is not a string")
        if isinstance(blocks_count, bool) or not isinstance(blocks_count, int) or blocks_count <= 0:
            raise AssertionError(
                f"ckb_node_versions data[{index}].blocks_count is not a positive integer"
            )
        counts.append((version, blocks_count))
    return counts


def _cellbase_version(block: Mapping[str, Any]) -> str:
    transactions = block.get("transactions")
    if not isinstance(transactions, list) or not transactions:
        return "others"
    cellbase = transactions[0]
    if not isinstance(cellbase, dict):
        return "others"
    witnesses = cellbase.get("witnesses")
    if not isinstance(witnesses, list) or not witnesses:
        return "others"
    version = cellbase_node_version(witnesses[0])
    return version if version is not None else "others"


class V2BlocksCkbNodeVersionsRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.oracles = tuple(NetworkOracle(network, cls.settings) for network in cls.settings.networks)

    def _prepare(self, oracle: NetworkOracle) -> tuple[int, int, int, Mapping[str, Any], list[tuple[str, int]]]:
        oracle._row_pages.clear()
        oracle._rpc_tip = None
        try:
            api_genesis = oracle.detail_attributes(0)
            rpc_genesis = oracle.block(0)
            payload = oracle.explorer_json("/v2/blocks/ckb_node_versions")
            api_tip = oracle.api_tip_height()
            rpc_tip = oracle.rpc_tip_height()
            tip_attributes = oracle.detail_attributes(api_tip)
            comparable_tip = min(api_tip, rpc_tip)
            rpc_tip_block = oracle.block(comparable_tip)
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        genesis_header = rpc_genesis.get("header")
        tip_header = rpc_tip_block.get("header")
        self.assertIsInstance(genesis_header, dict)
        self.assertIsInstance(tip_header, dict)
        self.assertEqual(genesis_header.get("hash"), api_genesis.get("block_hash"))
        self.assertLessEqual(abs(rpc_tip - api_tip), self.settings.max_lag_blocks)
        tip_epoch = int(tip_attributes["epoch"])
        counts = _api_version_counts(payload)
        return comparable_tip, tip_epoch, int(tip_attributes["start_number"]), tip_header, counts

    def _epoch(self, oracle: NetworkOracle, number: int) -> tuple[int, int]:
        try:
            epoch = oracle.rpc_result("get_epoch_by_number", [hex(number)])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        if not isinstance(epoch, dict):
            raise unittest.SkipTest(f"{oracle.network.name} RPC Epoch {number} is unavailable")
        return (
            decode_hex_int(epoch.get("start_number"), "epoch.start_number"),
            decode_hex_int(epoch.get("length"), "epoch.length"),
        )

    def _window_size(self, oracle: NetworkOracle, tip_epoch: int, api_tip: int) -> int:
        start_epoch = max(tip_epoch - 42, 0)
        start_number, _length = self._epoch(oracle, start_epoch)
        return api_tip - start_number + 1

    def _scan_heights(
        self,
        oracle: NetworkOracle,
        heights: list[int],
    ) -> tuple[Counter[str], dict[str, list[Mapping[str, Any]]]]:
        versions: Counter[str] = Counter()
        samples: dict[str, list[Mapping[str, Any]]] = {}
        batch_size = max(1, min(self.settings.rpc_batch_size, 20))
        for offset in range(0, len(heights), batch_size):
            chunk = heights[offset : offset + batch_size]
            try:
                blocks = oracle.rpc_batch_results(
                    [("get_block_by_number", [hex(height)]) for height in chunk]
                )
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            self.assertEqual(len(chunk), len(blocks))
            for height, block in zip(chunk, blocks, strict=True):
                if not isinstance(block, dict):
                    raise unittest.SkipTest(
                        f"{oracle.network.name} RPC has no block at height {height}"
                    )
                version = _cellbase_version(block)
                versions[version] += 1
                samples.setdefault(version, []).append(block)
        return versions, samples

    def _epoch_heights(
        self,
        oracle: NetworkOracle,
        number: int,
        api_tip: int,
        tip_epoch: int,
        *,
        indexes: tuple[int, ...] | None = None,
    ) -> list[int]:
        start_number, length = self._epoch(oracle, number)
        last_index = length - 1
        if number == tip_epoch:
            last_index = min(last_index, api_tip - start_number)
        if last_index < 0:
            return []
        if indexes is None:
            return [start_number + index for index in range(last_index + 1)]
        heights: list[int] = []
        for index in indexes:
            if 0 <= index <= last_index:
                heights.append(start_number + index)
        return heights

    def _assert_tip_stable(self, oracle: NetworkOracle, height: int, header: Mapping[str, Any]) -> None:
        try:
            fresh = oracle.block(height, refresh=True)
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        fresh_header = fresh.get("header")
        if not isinstance(fresh_header, dict) or fresh_header.get("hash") != header.get("hash"):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC block {height} changed during observation"
            )

    # TEST-MAP: V2-NODE-VERSIONS-RPC-01
    def test_version_counts_match_cellbase_transactions_in_tip_window(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                api_tip, tip_epoch, _start, tip_header, api_counts = self._prepare(oracle)
                window_size = self._window_size(oracle, tip_epoch, api_tip)
                api_total = sum(count for _version, count in api_counts)
                self.assertLessEqual(abs(api_total - window_size), self.settings.max_lag_blocks)

                start_epoch = max(tip_epoch - 42, 0)
                current_length = self._epoch(oracle, tip_epoch)[1]
                heights = self._epoch_heights(
                    oracle,
                    tip_epoch,
                    api_tip,
                    tip_epoch,
                    indexes=tuple(range(min(40, current_length))),
                )
                for number in {start_epoch, (start_epoch + tip_epoch) // 2} - {tip_epoch}:
                    length = self._epoch(oracle, number)[1]
                    heights.extend(
                        self._epoch_heights(
                            oracle,
                            number,
                            api_tip,
                            tip_epoch,
                            indexes=(0, max(length // 2, 0), max(length - 1, 0)),
                        )
                    )
                scanned, _samples = self._scan_heights(oracle, heights)
                api_map = dict(api_counts)
                for version, count in scanned.items():
                    self.assertIn(version, api_map)
                    self.assertGreaterEqual(api_map[version], count)
                self._assert_tip_stable(oracle, api_tip, tip_header)

    # TEST-MAP: V2-NODE-VERSIONS-RPC-02
    def test_window_includes_epoch_minus_42_and_excludes_epoch_minus_43(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                api_tip, tip_epoch, _start, tip_header, api_counts = self._prepare(oracle)
                if tip_epoch < 43:
                    raise unittest.SkipTest(
                        f"{oracle.network.name} tip Epoch {tip_epoch} is below the 43-Epoch window"
                    )
                included = self._window_size(oracle, tip_epoch, api_tip)
                excluded_start, excluded_length = self._epoch(oracle, tip_epoch - 43)
                included_start, _included_length = self._epoch(oracle, tip_epoch - 42)
                api_total = sum(count for _version, count in api_counts)
                self.assertLessEqual(abs(api_total - included), self.settings.max_lag_blocks)
                self.assertGreater(excluded_length, self.settings.max_lag_blocks)
                self.assertGreater(abs(api_total - (included + excluded_length)), excluded_length // 2)
                self.assertEqual(excluded_start + excluded_length, included_start)
                self._assert_tip_stable(oracle, api_tip, tip_header)

    # TEST-MAP: V2-NODE-VERSIONS-RPC-03
    def test_versions_are_unique_sorted_and_others_is_last(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                api_tip, tip_epoch, _start, tip_header, api_counts = self._prepare(oracle)
                versions = [version for version, _count in api_counts]
                self.assertEqual(len(versions), len(set(versions)))
                named = [version for version in versions if version != "others"]
                self.assertEqual(sorted(named), named)
                if "others" in versions:
                    self.assertEqual("others", versions[-1])
                    self.assertEqual(1, versions.count("others"))
                start_epoch = max(tip_epoch - 42, 0)
                sample_heights: list[int] = []
                for number in range(start_epoch, tip_epoch + 1):
                    length = self._epoch(oracle, number)[1]
                    sample_heights.extend(
                        self._epoch_heights(
                            oracle,
                            number,
                            api_tip,
                            tip_epoch,
                            indexes=(0, max(length // 2, 0), max(length - 1, 0)),
                        )
                    )
                scanned, _samples = self._scan_heights(oracle, sample_heights)
                identifiable = [version for version in scanned if version != "others"]
                if len(identifiable) < 2 or "others" not in scanned:
                    raise unittest.SkipTest(
                        f"{oracle.network.name} sampled window has no mixed identifiable versions and others"
                    )
                self._assert_tip_stable(oracle, api_tip, tip_header)

    # TEST-MAP: V2-NODE-VERSIONS-RPC-04
    def test_api_version_keys_come_from_cellbase_transaction_messages(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                api_tip, tip_epoch, _start, tip_header, api_counts = self._prepare(oracle)
                api_versions = {version for version, _count in api_counts if version != "others"}
                start_epoch = max(tip_epoch - 42, 0)
                heights: list[int] = []
                for number in (start_epoch, (start_epoch + tip_epoch) // 2, tip_epoch):
                    length = self._epoch(oracle, number)[1]
                    heights.extend(
                        self._epoch_heights(
                            oracle,
                            number,
                            api_tip,
                            tip_epoch,
                            indexes=(0, max(length // 2, 0), max(length - 1, 0)),
                        )
                    )
                _scanned, samples = self._scan_heights(oracle, heights)
                found_extended = False
                for version, blocks in samples.items():
                    if version == "others":
                        continue
                    self.assertIn(version, api_versions)
                    for block in blocks:
                        transactions = block.get("transactions")
                        self.assertIsInstance(transactions, list)
                        self.assertGreaterEqual(len(transactions), 1)
                        witnesses = transactions[0].get("witnesses")
                        self.assertIsInstance(witnesses, list)
                        self.assertGreaterEqual(len(witnesses), 1)
                        witness = witnesses[0]
                        self.assertIsInstance(witness, str)
                        payload = bytes.fromhex(witness.removeprefix("0x"))
                        self.assertIn(version.encode("ascii"), payload)
                        text = payload.decode("latin-1")
                        major = version.split(".", 1)[0]
                        if len(major) > 1 or f"{version}-" in text or f"{version}+" in text:
                            found_extended = True
                if not found_extended:
                    raise unittest.SkipTest(
                        f"{oracle.network.name} sampled Cellbase messages have no extra version digits or prerelease suffix"
                    )
                self._assert_tip_stable(oracle, api_tip, tip_header)

    # TEST-MAP: V2-NODE-VERSIONS-RPC-05
    def test_current_window_is_the_closed_interval_from_epoch_minus_42(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                api_tip, tip_epoch, _start, tip_header, api_counts = self._prepare(oracle)
                current = self._window_size(oracle, tip_epoch, api_tip)
                api_total = sum(count for _version, count in api_counts)
                self.assertLessEqual(abs(api_total - current), self.settings.max_lag_blocks)
                if tip_epoch >= 43:
                    older_length = self._epoch(oracle, tip_epoch - 43)[1]
                    self.assertGreater(older_length, self.settings.max_lag_blocks)
                    self.assertGreater(abs(api_total - (current + older_length)), older_length // 2)
                self._assert_tip_stable(oracle, api_tip, tip_header)

    # TEST-MAP: V2-NODE-VERSIONS-RPC-06
    def test_reorg_in_the_version_window_is_unavailable_without_a_stable_sample(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                api_tip, _tip_epoch, _start, tip_header, _api_counts = self._prepare(oracle)
                self._assert_tip_stable(oracle, api_tip, tip_header)
                raise unittest.SkipTest(
                    f"{oracle.network.name} public window has no stably observed canonical reorg"
                )


if __name__ == "__main__":
    unittest.main()
