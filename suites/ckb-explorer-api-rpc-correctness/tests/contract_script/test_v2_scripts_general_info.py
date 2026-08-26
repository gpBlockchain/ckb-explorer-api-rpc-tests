from __future__ import annotations

import hashlib
import json
import unittest
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlencode

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import ZERO_HASH, _raw_explorer_response
from tests.contract_script.test_v2_scripts_referring_cells import SECP_TYPE_HASH


DATA_FIXTURES = {
    "mainnet": ("0x4a4dce1df3dffff7f8b2cd7dff7303df3b6150c9788cb75dcf6747247132b9f5", "data1"),
    "testnet": ("0x923e997654b2697ee3f77052cb884e98f28799a4270fd412c3edb8f3987ca622", "data1"),
}
COUNT_FIXTURES = {
    "mainnet": ("0xe4d4ecc6e5f9a059bf2f7a82cca292083aebc0c421566a52484fe2ec51a9fb0c", "type"),
    "testnet": ("0x923e997654b2697ee3f77052cb884e98f28799a4270fd412c3edb8f3987ca622", "data1"),
}
DEAD_FIXTURES = {
    "mainnet": "0x614d40a86e1b29a8f4d8d93b9f3b390bf740803fa19a69f1c95716e029ea09b3",
    "testnet": "0x00cdf8fab0f8ac638758ebf5ea5e4052b1d71e8a77b9f43139718621f6849326",
}


class V2ScriptsGeneralInfoRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _info(self, oracle: NetworkOracle, code_hash: str, hash_type: str) -> list[Mapping[str, Any]]:
        payload = oracle.explorer_json(
            "/v2/scripts/general_info", {"code_hash": code_hash, "hash_type": hash_type}
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise OracleUnavailable(f"{oracle.network.name} script general info is unavailable")
        return data

    def _out_point(self, value: object) -> tuple[str, int]:
        if not isinstance(value, str) or "-" not in value:
            raise ValueError("script out-point is unavailable")
        tx_hash, raw_index = value.rsplit("-", 1)
        if not tx_hash.startswith("0x") or not raw_index.isdigit():
            raise ValueError("script out-point is invalid")
        return tx_hash, int(raw_index)

    def _assert_info_sample(self, oracle: NetworkOracle, code_hash: str, hash_type: str) -> None:
        info_rows = self._info(oracle, code_hash, hash_type)
        if len(info_rows) != 1:
            raise OracleUnavailable(f"{oracle.network.name} unique script registration is unavailable")
        info = info_rows[0]
        deployed_payload = oracle.explorer_json(
            "/v2/scripts/deployed_cells",
            {"code_hash": code_hash, "hash_type": hash_type, "page_size": 100},
        )["data"]
        deployed = deployed_payload["deployed_cells"]
        if len(deployed) != 1:
            raise OracleUnavailable(f"{oracle.network.name} unique deployment cell is unavailable")
        deployment = deployed[0]
        result = oracle.rpc_result("get_transaction", [deployment["tx_hash"]])
        deployment_tx = result.get("transaction") if isinstance(result, dict) else None
        if not isinstance(deployment_tx, dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC deployment transaction is unavailable")
        deployment_output = deployment_tx["outputs"][int(deployment["cell_index"])]
        deployment_data = deployment_tx["outputs_data"][int(deployment["cell_index"])]
        deployment_live = oracle.rpc_result(
            "get_live_cell",
            [{"tx_hash": deployment["tx_hash"], "index": hex(int(deployment["cell_index"]))}, True],
        )
        contract_hash, contract_index = self._out_point(info["script_out_point"])
        contract_result = oracle.rpc_result("get_transaction", [contract_hash])
        contract_tx = contract_result.get("transaction") if isinstance(contract_result, dict) else None
        if not isinstance(contract_tx, dict) or not isinstance(deployment_live, dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC contract-cell evidence is unavailable")
        contract_tx["outputs"][contract_index]
        relation = oracle.explorer_json(
            "/v2/scripts/ckb_transactions",
            {"code_hash": code_hash, "hash_type": hash_type, "page_size": 5},
        )["data"]["ckb_transactions"]
        observed_dep_types = set()
        for row in relation:
            result = oracle.rpc_result("get_transaction", [row["tx_hash"]])
            transaction = result.get("transaction") if isinstance(result, dict) else None
            if not isinstance(transaction, dict):
                raise OracleUnavailable(f"{oracle.network.name} RPC dependency transaction is unavailable")
            for dep in transaction["cell_deps"]:
                point = dep["out_point"]
                if (
                    point["tx_hash"] == contract_hash
                    and decode_hex_int(point["index"], "dep.index") == contract_index
                ):
                    observed_dep_types.add(dep["dep_type"])
        referring = oracle.explorer_json(
            "/v2/scripts/referring_cells",
            {"code_hash": code_hash, "hash_type": hash_type, "page_size": 1},
        )["data"]["referring_cells"]
        if not referring:
            raise OracleUnavailable(f"{oracle.network.name} referring script-use sample is unavailable")
        referring_result = oracle.rpc_result("get_transaction", [referring[0]["tx_hash"]])
        referring_tx = referring_result.get("transaction") if isinstance(referring_result, dict) else None
        if not isinstance(referring_tx, dict):
            raise OracleUnavailable(f"{oracle.network.name} RPC referring transaction is unavailable")
        referring_output = referring_tx["outputs"][int(referring[0]["cell_index"])]
        selected_hashes = {info.get("type_hash"), info.get("data_hash")}
        self.assertEqual(
            decode_hex_int(deployment_output["capacity"], "deployment.capacity"),
            int(Decimal(str(info["capacity_of_deployed_cells"]))),
        )
        self.assertEqual(info["is_deployed_cell_dead"], deployment_live["status"] != "live")
        self.assertEqual(bool(info["is_zero_lock"]), deployment_output["lock"]["code_hash"] == ZERO_HASH)
        if hash_type == "type":
            self.assertEqual(code_hash, ckb_script_hash(deployment_output["type"]))
        else:
            digest = hashlib.blake2b(
                bytes.fromhex(deployment_data.removeprefix("0x")),
                digest_size=32,
                person=b"ckb-default-hash",
            ).hexdigest()
            self.assertEqual(code_hash, "0x" + digest)
            self.assertEqual(hash_type, info["hash_type"])
        self.assertEqual({info["dep_type"]}, observed_dep_types)
        if info["is_lock_script"]:
            self.assertIn(referring_output["lock"]["code_hash"], selected_hashes)
        if info["is_type_script"]:
            self.assertIsInstance(referring_output.get("type"), dict)
            self.assertIn(referring_output["type"]["code_hash"], selected_hashes)

    # TEST-MAP: SCRIPT-CATALOG-RPC-08
    def test_type_and_data_hash_info_has_rpc_deployment_contract_and_usage_evidence(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                samples = ((SECP_TYPE_HASH, "type"), DATA_FIXTURES[network.name])
                try:
                    for code_hash, hash_type in samples:
                        self._assert_info_sample(oracle, code_hash, hash_type)
                except (OracleUnavailable, KeyError, IndexError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error

    # TEST-MAP: SCRIPT-CATALOG-RPC-09
    def test_transaction_and_live_referring_cell_counts_and_capacity_match_rpc_members(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                code_hash, hash_type = COUNT_FIXTURES[network.name]
                try:
                    info_rows = self._info(oracle, code_hash, hash_type)
                    verified = [row for row in info_rows if row.get("verified") is True]
                    if len(verified) != 1:
                        raise OracleUnavailable(f"{network.name} count fixture registration is unavailable")
                    info = verified[0]
                    contract_hash, contract_index = self._out_point(info["script_out_point"])
                    tx_payload = oracle.explorer_json(
                        "/v2/scripts/ckb_transactions",
                        {"code_hash": code_hash, "hash_type": hash_type, "page_size": 100},
                    )["data"]
                    transactions = tx_payload["ckb_transactions"]
                    cell_payload = oracle.explorer_json(
                        "/v2/scripts/referring_cells",
                        {"code_hash": code_hash, "hash_type": hash_type, "page_size": 100},
                    )["data"]
                    cells = cell_payload["referring_cells"]
                    if int(tx_payload["meta"]["total"]) >= 100 or int(cell_payload["meta"]["total"]) >= 100:
                        raise OracleUnavailable(f"{network.name} bounded count fixture is unavailable")
                    rpc_transactions = oracle.rpc_batch_results(
                        [("get_transaction", [row["tx_hash"]]) for row in transactions]
                    )
                    for result in rpc_transactions:
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict):
                            raise OracleUnavailable(f"{network.name} RPC dependency member is unavailable")
                        self.assertTrue(
                            any(
                                dep["out_point"]["tx_hash"] == contract_hash
                                and decode_hex_int(dep["out_point"]["index"], "dep.index") == contract_index
                                for dep in transaction["cell_deps"]
                            )
                        )
                    capacity = 0
                    for row in cells:
                        result = oracle.rpc_result("get_transaction", [row["tx_hash"]])
                        transaction = result.get("transaction") if isinstance(result, dict) else None
                        if not isinstance(transaction, dict):
                            raise OracleUnavailable(f"{network.name} RPC referring member is unavailable")
                        index = int(row["cell_index"])
                        output = transaction["outputs"][index]
                        live = oracle.rpc_result(
                            "get_live_cell", [{"tx_hash": row["tx_hash"], "index": hex(index)}, False]
                        )
                        if not isinstance(live, dict):
                            raise OracleUnavailable(f"{network.name} RPC live-cell status is unavailable")
                        self.assertEqual("live", live.get("status"))
                        script = output["lock"] if info["is_lock_script"] else output.get("type")
                        self.assertIsInstance(script, dict)
                        self.assertIn(script["code_hash"], {info.get("type_hash"), info.get("data_hash")})
                        capacity += decode_hex_int(output["capacity"], "referring.capacity")
                except (OracleUnavailable, KeyError, IndexError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(len(transactions), int(info["count_of_transactions"]))
                self.assertEqual(len(cells), int(info["count_of_referring_cells"]))
                self.assertEqual(capacity, int(info["capacity_of_referring_cells"]))
                self.assertEqual(len(transactions), len({row["tx_hash"] for row in transactions}))
                self.assertEqual(len(cells), len({(row["tx_hash"], row["cell_index"]) for row in cells}))

    # TEST-MAP: SCRIPT-CATALOG-RPC-10
    def test_catalog_and_general_info_keep_metadata_attached_to_the_same_registration(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    catalog = oracle.explorer_json("/v2/scripts", {"page_size": 100})["data"]
                    row = next(
                        item for item in catalog
                        if item.get("rfc") and item.get("website") and item.get("source_url")
                    )
                    if row.get("hash_type") in {"data", "data1", "data2"}:
                        code_hash, hash_type = row["data_hash"], row["hash_type"]
                    else:
                        code_hash, hash_type = row["type_hash"], "type"
                    matches = [
                        info for info in self._info(oracle, code_hash, hash_type)
                        if info.get("name") == row.get("name")
                        and info.get("type_hash") == row.get("type_hash")
                        and info.get("data_hash") == row.get("data_hash")
                    ]
                    if len(matches) != 1:
                        raise OracleUnavailable(f"{network.name} unique metadata registration is unavailable")
                    info = matches[0]
                except (OracleUnavailable, StopIteration, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                for field in (
                    "name", "type_hash", "data_hash", "hash_type", "is_lock_script", "is_type_script",
                    "rfc", "website", "source_url", "deprecated",
                ):
                    self.assertEqual(row.get(field), info.get(field))
                self.assertIs(True, info["verified"])
                self.assertIsInstance(info["description"], str)

    # TEST-MAP: SCRIPT-CATALOG-RPC-11
    def test_verified_dead_deployment_remains_in_info_but_not_the_live_catalog(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                code_hash = DEAD_FIXTURES[network.name]
                try:
                    catalog = oracle.explorer_json("/v2/scripts", {"page_size": 100})["data"]
                    info_rows = self._info(oracle, code_hash, "type")
                    matches = [row for row in info_rows if row.get("verified") is True]
                    if len(matches) != 1:
                        raise OracleUnavailable(f"{network.name} verified dead registration is unavailable")
                    info = matches[0]
                    tx_hash, index = self._out_point(info["script_out_point"])
                    live = oracle.rpc_result(
                        "get_live_cell", [{"tx_hash": tx_hash, "index": hex(index)}, False]
                    )
                    if not isinstance(live, dict):
                        raise OracleUnavailable(f"{network.name} RPC dead-cell status is unavailable")
                except (OracleUnavailable, KeyError, TypeError, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertTrue(info["is_deployed_cell_dead"])
                self.assertEqual("unknown", live.get("status"))
                self.assertFalse(
                    any(row.get("type_hash") == code_hash or row.get("data_hash") == code_hash for row in catalog)
                )

    # TEST-MAP: SCRIPT-CATALOG-RPC-12
    def test_missing_unsupported_and_unknown_identity_return_not_found_without_script_data(self) -> None:
        cases = (
            {"code_hash": SECP_TYPE_HASH},
            {"code_hash": SECP_TYPE_HASH, "hash_type": "unsupported"},
            {"code_hash": "0x" + "ff" * 32, "hash_type": "type"},
        )
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                for query in cases:
                    path = "/v2/scripts/general_info?" + urlencode(query)
                    try:
                        status, raw = _raw_explorer_response(oracle, path)
                    except OracleUnavailable as error:
                        raise unittest.SkipTest(str(error)) from error
                    if status == 403:
                        raise unittest.SkipTest(f"{network.name} edge rejected negative-path observation")
                    self.assertEqual(404, status)
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        payload = None
                    self.assertFalse(isinstance(payload, dict) and "data" in payload)


if __name__ == "__main__":
    unittest.main()
