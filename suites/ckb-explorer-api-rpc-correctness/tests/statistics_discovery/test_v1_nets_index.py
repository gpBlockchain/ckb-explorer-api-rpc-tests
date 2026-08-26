from __future__ import annotations

import unittest

from ckb_rpc_correctness.ckb import decode_hex_int
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


class V1NetsIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # The configured public RPC is load-balanced and currently exposes a different node ID.
    # TEST-MAP: DISCOVERY-RPC-08
    @unittest.expectedFailure
    def test_complete_local_node_info_matches_the_configured_rpc_instance(self) -> None:
        mismatches: list[str] = []
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                rpc = oracle.rpc_result("local_node_info", [])
                payload = oracle.explorer_json("/v1/nets")
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            self.assertIsInstance(rpc, dict)
            data = payload.get("data") if isinstance(payload, dict) else None
            self.assertIsInstance(data, dict)
            self.assertEqual("net_info", data.get("type"))
            info = data.get("attributes", {}).get("local_node_info")
            self.assertIsInstance(info, dict)
            expected_addresses = [
                {"address": row["address"], "score": decode_hex_int(row["score"], "address.score")}
                for row in rpc.get("addresses", [])
            ]
            expected_protocols = [
                {
                    "id": decode_hex_int(row["id"], "protocol.id"),
                    "name": row["name"],
                    "support_versions": row["support_versions"],
                }
                for row in rpc.get("protocols", [])
            ]
            expected = {
                "version": rpc.get("version"),
                "node_id": rpc.get("node_id"),
                "active": rpc.get("active"),
                "addresses": expected_addresses,
                "protocols": expected_protocols,
                "connections": decode_hex_int(rpc.get("connections"), "connections"),
            }
            if expected != info:
                mismatches.append(f"{network.name}: expected {expected!r}, got {info!r}")
        self.assertEqual([], mismatches)
