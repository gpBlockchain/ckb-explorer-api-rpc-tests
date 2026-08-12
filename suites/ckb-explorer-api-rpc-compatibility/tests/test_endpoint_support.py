from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace

from ckb_api_compat.models import ComparisonResult, Observation, RequestCase
from tests.endpoint_support import EndpointCompatibilityTestCase


class _RecordingRunner:
    def __init__(self, result: ComparisonResult) -> None:
        self.result = result
        self.calls: list[RequestCase] = []

    def run_case(self, case: RequestCase) -> ComparisonResult:
        self.calls.append(case)
        return self.result


class EndpointRequestDeclarationTests(unittest.TestCase):
    def setUp(self) -> None:
        case = RequestCase(
            id="API-EXAMPLE",
            module="MOD-EXAMPLE",
            method="GET",
            path="/v1/blocks/22000000",
            purpose="example",
            body={"page": 1, "page_size": 2},
        )
        result = ComparisonResult(
            request_id="request-id",
            case_id=case.id,
            matched=True,
            baseline=Observation(
                side="baseline",
                method="GET",
                url="https://baseline/api/v1/blocks/22000000",
                status=200,
                headers={"content-type": "application/json", "set-cookie": "baseline-secret"},
                body=b'{"data":{"ok":true},"token":"baseline-secret"}',
            ),
            candidate=Observation(
                side="candidate",
                method="GET",
                url="https://candidate/api/v1/blocks/22000000",
                status=200,
                headers={"content-type": "application/json", "set-cookie": "candidate-secret"},
                body=b'{"data":{"ok":true},"token":"candidate-secret"}',
            ),
        )
        self.endpoint_test = EndpointCompatibilityTestCase(methodName="runTest")
        self.endpoint_test.API_ID = case.id
        self.endpoint_test.spec = {"id": case.id, "method": "GET", "path": "/v1/blocks/:id"}
        self.endpoint_test.case = case
        self.endpoint_test.runner = _RecordingRunner(result)
        self.endpoint_test.settings = SimpleNamespace(
            print_responses=True,
            max_report_body_chars=200_000,
        )

    def test_explicit_method_and_path_issue_the_materialized_case(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            result = self.endpoint_test.request_both(
                method="GET",
                path="/v1/blocks/:id",
                json_body={"page": 1, "page_size": 2},
            )

        self.assertTrue(result.matched)
        self.assertEqual([self.endpoint_test.case], self.endpoint_test.runner.calls)
        printed = json.loads(stdout.getvalue())
        self.assertEqual("api_response", printed["event"])
        self.assertEqual(200, printed["baseline"]["status"])
        self.assertEqual(200, printed["candidate"]["status"])
        self.assertEqual("<redacted>", printed["baseline"]["headers"]["set-cookie"])
        self.assertNotIn("baseline-secret", printed["baseline"]["body"])

    def test_method_drift_is_rejected_before_any_request(self) -> None:
        with self.assertRaisesRegex(AssertionError, "method drifted"):
            self.endpoint_test.request_both(method="POST", path="/v1/blocks/:id")
        self.assertEqual([], self.endpoint_test.runner.calls)

    def test_path_drift_is_rejected_before_any_request(self) -> None:
        with self.assertRaisesRegex(AssertionError, "path drifted"):
            self.endpoint_test.request_both(method="GET", path="/v1/blocks/:wrong_id")
        self.assertEqual([], self.endpoint_test.runner.calls)

    def test_json_data_drift_is_rejected_before_any_request(self) -> None:
        with self.assertRaisesRegex(AssertionError, "JSON data drifted"):
            self.endpoint_test.request_both(
                method="GET",
                path="/v1/blocks/:id",
                json_body={"page": 99},
            )
        self.assertEqual([], self.endpoint_test.runner.calls)


if __name__ == "__main__":
    unittest.main()
