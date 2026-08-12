from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from ckb_api_compat.manifest import build_cases, load_endpoint_specs, load_fixture_config
from ckb_api_compat.settings import load_settings


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "endpoints.json"


class EndpointManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.endpoints = load_endpoint_specs(MANIFEST)

    # TP-COMPATIBILITY-API-CONTRACT-001
    def test_tp_001_manifest_contains_all_124_active_routes(self) -> None:
        active = [item for item in self.endpoints if item["wiring"] == "ACTIVE"]
        self.assertEqual(124, len(active))
        self.assertEqual(124, len({(item["method"], item["path"]) for item in active}))

    # TP-COMPATIBILITY-API-CONTRACT-002
    def test_tp_002_manifest_preserves_22_route_only_cases_as_known_defects(self) -> None:
        route_only = [item for item in self.endpoints if item["wiring"] == "ROUTE_ONLY"]
        self.assertEqual(22, len(route_only))
        cases = build_cases(route_only, {"variables": {}, "cases": {}}, include_known_defects=False)
        self.assertTrue(all(not case.enabled and "ROUTE_ONLY" in (case.skip_reason or "") for case in cases))

    # TP-COMPATIBILITY-API-CONTRACT-003
    def test_tp_003_manifest_preserves_seven_namespace_mismatch_cases(self) -> None:
        mismatches = [item for item in self.endpoints if item["wiring"] == "NAMESPACE_MISMATCH"]
        self.assertEqual(7, len(mismatches))
        self.assertTrue(all("/v2/nft/cota/" in item["path"] for item in mismatches))

    # TP-COMPATIBILITY-API-CONTRACT-004
    def test_tp_004_method_and_path_are_a_unique_route_identity(self) -> None:
        keys = [(item["method"], item["path"]) for item in self.endpoints]
        self.assertEqual(153, len(keys))
        self.assertEqual(153, len(set(keys)))
        self.assertNotIn(("TRACE", "/v1/blocks"), set(keys))

    def test_inventory_distribution_is_stable(self) -> None:
        self.assertEqual(
            {"GET": 129, "POST": 9, "PATCH": 6, "PUT": 6, "DELETE": 3},
            dict(Counter(item["method"] for item in self.endpoints)),
        )
        self.assertEqual(
            {"ACTIVE": 124, "ROUTE_ONLY": 22, "NAMESPACE_MISMATCH": 7},
            dict(Counter(item["wiring"] for item in self.endpoints)),
        )

    def test_v1_jsonapi_local_ids_are_ignored_but_v2_ids_remain_strict(self) -> None:
        fixtures = {
            "comparison_defaults": {
                "ignore_v1_jsonapi_resource_ids": True,
                "ignore_local_numeric_ids": True,
            },
            "variables": {},
            "cases": {},
        }
        specs = [
            {"id": "V1", "module": "MOD", "method": "GET", "path": "/v1/items", "purpose": "v1", "wiring": "ACTIVE"},
            {"id": "V2", "module": "MOD", "method": "GET", "path": "/v2/items", "purpose": "v2", "wiring": "ACTIVE"},
        ]
        v1, v2 = build_cases(specs, fixtures)
        self.assertTrue(v1.ignore_jsonapi_resource_ids)
        self.assertFalse(v2.ignore_jsonapi_resource_ids)
        self.assertTrue(v1.ignore_local_numeric_ids)
        self.assertTrue(v2.ignore_local_numeric_ids)

    def test_missing_path_fixture_skips_and_mutations_require_two_explicit_switches(self) -> None:
        endpoint = {
            "id": "EXAMPLE",
            "module": "MOD",
            "method": "PATCH",
            "path": "/v1/items/:id",
            "purpose": "update",
            "wiring": "ACTIVE",
        }
        disabled = build_cases([endpoint], {"variables": {}, "cases": {"EXAMPLE": {}}}, allow_mutations=True)[0]
        self.assertFalse(disabled.enabled)
        enabled = build_cases(
            [endpoint],
            {"variables": {"id": "42"}, "cases": {"EXAMPLE": {"allow_mutation": True}}},
            allow_mutations=True,
        )[0]
        self.assertTrue(enabled.enabled)
        self.assertEqual("/v1/items/42", enabled.path)

    def test_side_specific_path_params_resolve_local_ids_without_changing_route_identity(self) -> None:
        endpoint = {
            "id": "LOCAL-ID",
            "module": "MOD",
            "method": "GET",
            "path": "/v1/cells/:id",
            "purpose": "same cell",
            "wiring": "ACTIVE",
        }
        case = build_cases(
            [endpoint],
            {
                "variables": {},
                "cases": {
                    "LOCAL-ID": {
                        "baseline_path_params": {"id": 41},
                        "candidate_path_params": {"id": 99},
                    }
                },
            },
        )[0]
        self.assertTrue(case.enabled)
        self.assertEqual("/v1/cells/:id", case.path)
        self.assertEqual("/v1/cells/41", case.path_for("baseline"))
        self.assertEqual("/v1/cells/99", case.path_for("candidate"))

    def test_checked_in_defaults_enable_all_153_cases_without_skip(self) -> None:
        settings = load_settings()
        fixtures = load_fixture_config(settings.fixtures_file)
        cases = build_cases(
            self.endpoints,
            fixtures,
            allow_mutations=settings.allow_mutations,
            include_known_defects=settings.include_known_defects,
            enable_csv_exports=settings.run_exports,
            default_timeout=settings.timeout_seconds,
            default_retries=settings.transport_retries,
        )
        disabled = {case.id: case.skip_reason for case in cases if not case.enabled}
        self.assertTrue(settings.strict_fixtures)
        self.assertEqual(153, len(cases))
        self.assertEqual({}, disabled)

    # TP-COMPATIBILITY-API-CONTRACT-023
    def test_csv_exports_require_an_explicit_case_enable_switch(self) -> None:
        endpoint = {
            "id": "CSV",
            "module": "MOD",
            "method": "GET",
            "path": "/v1/items/download_csv",
            "purpose": "export",
            "wiring": "ACTIVE",
            "mode": "csv",
        }
        disabled = build_cases([endpoint], {"variables": {}, "cases": {}})[0]
        self.assertFalse(disabled.enabled)
        self.assertIn("CSV export disabled", disabled.skip_reason or "")
        enabled = build_cases([endpoint], {"variables": {}, "cases": {"CSV": {"enabled": True}}})[0]
        self.assertTrue(enabled.enabled)


if __name__ == "__main__":
    unittest.main()
