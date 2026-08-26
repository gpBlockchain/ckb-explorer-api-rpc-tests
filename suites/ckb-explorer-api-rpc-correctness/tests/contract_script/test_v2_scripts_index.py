from __future__ import annotations

import hashlib
import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


ZERO_HASH = "0x" + "00" * 32


class V2ScriptsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.catalog_cache: dict[tuple[str, tuple[tuple[str, object], ...]], tuple[list[Mapping[str, Any]], Mapping[str, Any]]] = {}
        cls.info_cache: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}

    def _catalog(
        self,
        oracle: NetworkOracle,
        **query: object,
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        key = (oracle.network.name, tuple(sorted(query.items())))
        if key not in self.catalog_cache:
            payload = oracle.explorer_json("/v2/scripts", query or None)
            data = payload.get("data") if isinstance(payload, dict) else None
            meta = payload.get("meta") if isinstance(payload, dict) else None
            if not isinstance(data, list) or not isinstance(meta, dict) or not all(isinstance(row, dict) for row in data):
                raise OracleUnavailable(f"{oracle.network.name} script catalog is unavailable")
            self.catalog_cache[key] = (data, meta)
        return self.catalog_cache[key]

    def _identity(self, row: Mapping[str, Any]) -> tuple[str, str]:
        if row.get("hash_type") in {"data", "data1", "data2"}:
            return str(row["data_hash"]), str(row["hash_type"])
        return str(row["type_hash"]), "type"

    def _info(self, oracle: NetworkOracle, code_hash: str, hash_type: str) -> list[Mapping[str, Any]]:
        key = (oracle.network.name, code_hash, hash_type)
        if key not in self.info_cache:
            payload = oracle.explorer_json(
                "/v2/scripts/general_info", {"code_hash": code_hash, "hash_type": hash_type}
            )
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
                raise OracleUnavailable(f"{oracle.network.name} script general info is unavailable")
            self.info_cache[key] = data
        return self.info_cache[key]

    def _matching_info(self, oracle: NetworkOracle, row: Mapping[str, Any]) -> Mapping[str, Any]:
        code_hash, hash_type = self._identity(row)
        matches = [
            info for info in self._info(oracle, code_hash, hash_type)
            if info.get("name") == row.get("name")
            and info.get("type_hash") == row.get("type_hash")
            and info.get("data_hash") == row.get("data_hash")
        ]
        if len(matches) != 1:
            raise OracleUnavailable(f"{oracle.network.name} unique script metadata record is unavailable")
        return matches[0]

    def _out_point(self, info: Mapping[str, Any]) -> Mapping[str, str]:
        value = info.get("script_out_point")
        if not isinstance(value, str) or "-" not in value:
            raise ValueError("script out-point is unavailable")
        tx_hash, raw_index = value.rsplit("-", 1)
        if not tx_hash.startswith("0x") or not raw_index.isdigit():
            raise ValueError("script out-point is invalid")
        return {"tx_hash": tx_hash, "index": hex(int(raw_index))}

    def _assert_dep_type(
        self,
        oracle: NetworkOracle,
        code_hash: str,
        hash_type: str,
        out_point: Mapping[str, str],
        expected_dep_type: str,
    ) -> None:
        payload = oracle.explorer_json(
            "/v2/scripts/ckb_transactions",
            {"code_hash": code_hash, "hash_type": hash_type, "page_size": 10},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("ckb_transactions") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise OracleUnavailable(f"{oracle.network.name} script dependency samples are unavailable")
        observed: list[str] = []
        for row in rows:
            tx_hash = row.get("tx_hash") if isinstance(row, dict) else None
            if not isinstance(tx_hash, str):
                raise OracleUnavailable(f"{oracle.network.name} script dependency transaction is unavailable")
            result = oracle.rpc_result("get_transaction", [tx_hash])
            transaction = result.get("transaction") if isinstance(result, dict) else None
            if not isinstance(transaction, dict):
                raise OracleUnavailable(f"{oracle.network.name} RPC dependency transaction is unavailable")
            for dependency in transaction.get("cell_deps", []):
                rpc_out_point = dependency.get("out_point") if isinstance(dependency, dict) else None
                if rpc_out_point == out_point:
                    observed.append(str(dependency.get("dep_type")))
        if not observed:
            raise unittest.SkipTest(f"{oracle.network.name} first dependency page has no selected out-point")
        self.assertEqual({expected_dep_type}, set(observed))

    # TEST-MAP: SCRIPT-CATALOG-RPC-01
    @unittest.expectedFailure  # Testnet FlashSigner is listed although its published deployment out-point is unknown.
    def test_every_catalog_member_is_verified_and_has_live_deployment_evidence(self) -> None:
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                rows, meta = self._catalog(oracle, page_size=100)
            except OracleUnavailable as error:
                with self.subTest(network=network.name):
                    raise unittest.SkipTest(str(error)) from error
            self.assertEqual(len(rows), int(meta["total"]))
            for row in rows:
                with self.subTest(network=network.name, script=row.get("name")):
                    if row.get("type_hash") == ZERO_HASH and row.get("data_hash") == ZERO_HASH:
                        self.assertTrue(row.get("is_zero_lock"))
                        continue
                    try:
                        info = self._matching_info(oracle, row)
                        self.assertIs(True, info.get("verified"))
                        self.assertIs(False, info.get("is_deployed_cell_dead"))
                        out_point = self._out_point(info)
                        result = oracle.rpc_result("get_live_cell", [out_point, True])
                    except (OracleUnavailable, ValueError) as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertIsInstance(result, dict)
                    self.assertEqual("live", result.get("status"))

    # TEST-MAP: SCRIPT-CATALOG-RPC-02
    def test_type_hash_script_matches_rpc_type_script_and_dependency_type(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, _meta = self._catalog(oracle, page_size=100)
                    row = info = out_point = type_script = None
                    for candidate in rows:
                        if (
                            candidate.get("type_hash") in {None, ZERO_HASH}
                            or candidate.get("hash_type") in {"data", "data1", "data2"}
                        ):
                            continue
                        candidate_info = self._matching_info(oracle, candidate)
                        candidate_out_point = self._out_point(candidate_info)
                        result = oracle.rpc_result("get_transaction", [candidate_out_point["tx_hash"]])
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict):
                            continue
                        output = transaction["outputs"][decode_hex_int(candidate_out_point["index"], "out_point.index")]
                        candidate_type_script = output.get("type") if isinstance(output, dict) else None
                        if isinstance(candidate_type_script, dict):
                            row, info, out_point, type_script = candidate, candidate_info, candidate_out_point, candidate_type_script
                            break
                    if not all(isinstance(value, dict) for value in (row, info, out_point, type_script)):
                        raise OracleUnavailable(f"{network.name} deployed Type Script fixture is unavailable")
                    assert isinstance(row, dict) and isinstance(out_point, dict) and isinstance(type_script, dict)
                    self.assertEqual(row["type_hash"], ckb_script_hash(type_script))
                    self._assert_dep_type(
                        oracle, str(row["type_hash"]), "type", out_point, str(row["dep_type"])
                    )
                except (OracleUnavailable, StopIteration, ValueError, IndexError) as error:
                    raise unittest.SkipTest(str(error)) from error

    # TEST-MAP: SCRIPT-CATALOG-RPC-03
    def test_data_hash_script_matches_rpc_output_data_and_dependency_type(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, _meta = self._catalog(oracle, page_size=100)
                    row = next(
                        item for item in rows
                        if item.get("data_hash") not in {None, ZERO_HASH}
                        and item.get("hash_type") in {"data", "data1", "data2"}
                    )
                    info = self._matching_info(oracle, row)
                    out_point = self._out_point(info)
                    result = oracle.rpc_result("get_transaction", [out_point["tx_hash"]])
                    transaction = result.get("transaction") if isinstance(result, dict) else None
                    if not isinstance(transaction, dict):
                        raise OracleUnavailable(f"{network.name} RPC deployment transaction is unavailable")
                    index = decode_hex_int(out_point["index"], "out_point.index")
                    raw_data = transaction["outputs_data"][index]
                    digest = hashlib.blake2b(
                        bytes.fromhex(raw_data.removeprefix("0x")),
                        digest_size=32,
                        person=b"ckb-default-hash",
                    ).hexdigest()
                    self.assertEqual(row["data_hash"], "0x" + digest)
                    self.assertIn(row["hash_type"], {"data", "data1", "data2"})
                    self._assert_dep_type(
                        oracle, str(row["data_hash"]), str(row["hash_type"]), out_point, str(row["dep_type"])
                    )
                except (OracleUnavailable, StopIteration, ValueError, IndexError) as error:
                    raise unittest.SkipTest(str(error)) from error

    # TEST-MAP: SCRIPT-CATALOG-RPC-04
    def test_lock_type_and_combined_script_type_filters_are_exact(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    all_rows, _meta = self._catalog(oracle, page_size=100)
                    lock_rows, _lock_meta = self._catalog(oracle, script_type="lock", page_size=100)
                    type_rows, _type_meta = self._catalog(oracle, script_type="type", page_size=100)
                    both_rows, _both_meta = self._catalog(oracle, script_type="lock,type", page_size=100)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                key = lambda row: (row.get("name"), row.get("type_hash"), row.get("data_hash"))
                self.assertEqual({key(row) for row in all_rows if row.get("is_lock_script")}, {key(row) for row in lock_rows})
                self.assertEqual({key(row) for row in all_rows if row.get("is_type_script")}, {key(row) for row in type_rows})
                self.assertEqual(
                    {key(row) for row in all_rows if row.get("is_lock_script") and row.get("is_type_script")},
                    {key(row) for row in both_rows},
                )

    # TEST-MAP: SCRIPT-CATALOG-RPC-05
    def test_single_notes_are_exact_and_multiple_notes_form_a_deduplicated_union(self) -> None:
        predicates = {
            "ownerless_cell": lambda row: row.get("is_zero_lock") is True,
            "deprecated": lambda row: row.get("deprecated") is True,
            "rfc": lambda row: row.get("rfc") is not None,
            "website": lambda row: row.get("website") is not None,
            "open_source": lambda row: row.get("source_url") is not None,
        }
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    rows, _meta = self._catalog(oracle, page_size=100)
                    filtered = {
                        note: self._catalog(oracle, notes=note, page_size=100)[0]
                        for note in predicates
                    }
                    union_rows, _union_meta = self._catalog(
                        oracle, notes="deprecated,rfc,website", page_size=100
                    )
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                key = lambda row: (row.get("name"), row.get("type_hash"), row.get("data_hash"))
                for note, predicate in predicates.items():
                    self.assertEqual({key(row) for row in rows if predicate(row)}, {key(row) for row in filtered[note]})
                expected_union = {
                    key(row) for row in rows
                    if predicates["deprecated"](row) or predicates["rfc"](row) or predicates["website"](row)
                }
                actual_union = [key(row) for row in union_rows]
                self.assertEqual(expected_union, set(actual_union))
                self.assertEqual(len(actual_union), len(set(actual_union)))

    # TEST-MAP: SCRIPT-CATALOG-RPC-06
    def test_timestamp_and_capacity_sorts_use_integer_values_in_both_directions(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    default, _meta = self._catalog(oracle, page_size=100)
                    timestamp_asc, _meta = self._catalog(oracle, sort="timestamp.asc", page_size=100)
                    timestamp_desc, _meta = self._catalog(oracle, sort="timestamp.desc", page_size=100)
                    capacity_asc, _meta = self._catalog(oracle, sort="capacity.asc", page_size=100)
                    capacity_desc, _meta = self._catalog(oracle, sort="capacity.desc", page_size=100)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                timestamps = lambda rows: [int(row["deployed_block_timestamp"]) for row in rows]
                capacities = lambda rows: [int(row["total_referring_cells_capacity"]) for row in rows]
                self.assertEqual(timestamps(default), timestamps(timestamp_asc))
                self.assertEqual(timestamps(timestamp_asc), sorted(timestamps(timestamp_asc)))
                self.assertEqual(timestamps(timestamp_desc), sorted(timestamps(timestamp_desc), reverse=True))
                self.assertEqual(capacities(capacity_asc), sorted(capacities(capacity_asc)))
                self.assertEqual(capacities(capacity_desc), sorted(capacities(capacity_desc), reverse=True))

    # TEST-MAP: SCRIPT-CATALOG-RPC-07
    def test_default_custom_all_adjacent_and_overflow_pages_are_complete(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    default, default_meta = self._catalog(oracle)
                    complete, complete_meta = self._catalog(oracle, page_size=100)
                    total = int(complete_meta["total"])
                    paged: list[Mapping[str, Any]] = []
                    for page in range(1, (total + 6) // 7 + 1):
                        rows, meta = self._catalog(oracle, page=page, page_size=7)
                        self.assertEqual(total, int(meta["total"]))
                        self.assertEqual(7, int(meta["page_size"]))
                        paged.extend(rows)
                    overflow, overflow_meta = self._catalog(oracle, page=(total + 6) // 7 + 1, page_size=7)
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(10, int(default_meta["page_size"]))
                self.assertEqual(min(10, total), len(default))
                keys = [(row.get("name"), row.get("type_hash"), row.get("data_hash")) for row in paged]
                complete_keys = [(row.get("name"), row.get("type_hash"), row.get("data_hash")) for row in complete]
                self.assertEqual(set(complete_keys), set(keys))
                self.assertEqual(total, len(keys))
                self.assertEqual(total, len(set(keys)))
                self.assertEqual([], overflow)
                self.assertEqual(total, int(overflow_meta["total"]))
                self.assertEqual(7, int(overflow_meta["page_size"]))


if __name__ == "__main__":
    unittest.main()
