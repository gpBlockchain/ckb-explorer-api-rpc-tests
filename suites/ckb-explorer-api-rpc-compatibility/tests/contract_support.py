from __future__ import annotations

import json
import unittest
from dataclasses import replace

from ckb_api_compat.http import StdlibHttpClient
from ckb_api_compat.models import RequestCase
from ckb_api_compat.runner import PairedRunner
from ckb_api_compat.settings import load_settings


SETTINGS = load_settings()
RUN_LIVE = SETTINGS.run_live
RUN_EXPORTS = SETTINGS.run_exports
V1_HEADERS = {"Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}


@unittest.skipUnless(RUN_LIVE, f"live execution disabled in {SETTINGS.settings_file}")
class LiveContractTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.runner = PairedRunner(
            SETTINGS.baseline_url,
            SETTINGS.candidate_url,
            client=StdlibHttpClient(max_body_bytes=SETTINGS.max_body_bytes),
        )

    def assert_case(self, case: RequestCase, expected_status: int | None = None):
        if case.path.startswith("/v1/") and not case.ignore_jsonapi_resource_ids:
            case = replace(case, ignore_jsonapi_resource_ids=True)
        result = self.runner.run_case(case)
        self.assertFalse(result.skipped, result.skip_reason)
        if not result.matched:
            detail = [
                {
                    "phase": difference.phase,
                    "path": difference.path,
                    "baseline": difference.baseline,
                    "candidate": difference.candidate,
                    "detail": difference.detail,
                }
                for difference in result.differences
            ]
            self.fail(f"{case.id} mismatch: {json.dumps(detail, ensure_ascii=False, default=str)}")
        if expected_status is not None:
            self.assertEqual(expected_status, result.baseline.status)
            self.assertEqual(expected_status, result.candidate.status)
        return result
