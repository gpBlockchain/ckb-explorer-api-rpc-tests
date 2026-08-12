from __future__ import annotations

import json
import unittest
from functools import lru_cache

from ckb_api_compat.http import StdlibHttpClient
from ckb_api_compat.manifest import build_cases, load_endpoint_specs, load_fixture_config
from ckb_api_compat.models import ComparisonResult
from ckb_api_compat.report import result_dict
from ckb_api_compat.runner import PairedRunner
from ckb_api_compat.settings import load_settings


@lru_cache(maxsize=1)
def _runtime_context():
    settings = load_settings()
    manifest = load_endpoint_specs(settings.manifest_file)
    fixtures = load_fixture_config(settings.fixtures_file)
    cases = build_cases(
        manifest,
        fixtures,
        allow_mutations=settings.allow_mutations,
        include_known_defects=settings.include_known_defects,
        enable_csv_exports=settings.run_exports,
        default_timeout=settings.timeout_seconds,
        default_retries=settings.transport_retries,
    )
    runner = PairedRunner(
        settings.baseline_url,
        settings.candidate_url,
        client=StdlibHttpClient(max_body_bytes=settings.max_body_bytes),
    )
    return (
        settings,
        {spec["id"]: spec for spec in manifest},
        {case.id: case for case in cases},
        runner,
    )


class EndpointCompatibilityTestCase(unittest.TestCase):
    """Shared execution only; every concrete API lives in its own test file."""

    API_ID = ""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        settings, specs_by_id, cases_by_id, runner = _runtime_context()
        if not settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {settings.settings_file}")
        if cls.API_ID not in cases_by_id:
            raise AssertionError(f"generated endpoint test references unknown API ID: {cls.API_ID}")
        cls.spec = specs_by_id[cls.API_ID]
        cls.case = cases_by_id[cls.API_ID]
        cls.runner = runner
        cls.settings = settings

    def request_both(self, *, method: str, path: str, json_body: object = None) -> ComparisonResult:
        """Issue this file's declared request to both configured environments."""
        case = self.case
        self.assertEqual(
            self.spec["method"],
            method.upper(),
            f"{self.API_ID} test method drifted from the endpoint manifest",
        )
        self.assertEqual(
            self.spec["path"],
            path,
            f"{self.API_ID} test path drifted from the endpoint manifest",
        )
        self.assertEqual(
            case.body,
            json_body,
            f"{self.API_ID} test JSON data drifted from the endpoint fixture",
        )
        if not case.enabled:
            self.skipTest(case.skip_reason or "case disabled")
        result = self.runner.run_case(case)
        if self.settings.print_responses:
            print(
                json.dumps(
                    {
                        "event": "api_response",
                        **result_dict(
                            result,
                            max_body_chars=self.settings.max_report_body_chars,
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                flush=True,
            )
        return result

    def assert_responses_compatible(self, result: ComparisonResult) -> None:
        """Assert the paired HTTP observations have compatible responses."""
        case = self.case
        self.assertFalse(result.skipped, result.skip_reason)
        if result.matched:
            return
        details = [
            {
                "phase": difference.phase,
                "path": difference.path,
                "baseline": difference.baseline,
                "candidate": difference.candidate,
                "detail": difference.detail,
            }
            for difference in result.differences
        ]
        self.fail(
            f"{case.id} {case.method} {case.path} compatibility mismatch: "
            + json.dumps(details, ensure_ascii=False, default=str)
        )
