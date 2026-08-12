from __future__ import annotations

import json
import unittest

from ckb_api_compat.compare import compare_observations, normalize_json
from ckb_api_compat.models import Observation, RequestCase
from ckb_api_compat.redact import MASK, redact_headers, redact_url, redact_value
from ckb_api_compat.report import report_payload
from ckb_api_compat.runner import PairedRunner


def observation(side: str, body, *, status: int = 200, content_type: str = "application/json") -> Observation:
    payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
    return Observation(
        side=side,  # type: ignore[arg-type]
        method="GET",
        url=f"https://{side}.example/api/v1/example",
        status=status,
        headers={"content-type": content_type},
        body=payload,
    )


class FakeClient:
    def __init__(self, baseline: Observation, candidate: Observation) -> None:
        self.observations = {"baseline": baseline, "candidate": candidate}
        self.calls: list[str] = []

    def observe(self, side, _base_url, _case):
        self.calls.append(side)
        return self.observations[side]


class ComparisonEngineTests(unittest.TestCase):
    # TP-COMPATIBILITY-API-CONTRACT-030
    def test_tp_030_paired_runner_retains_both_observations(self) -> None:
        case = RequestCase("CASE", "MOD", "GET", "/v1/example", "example")
        baseline = observation("baseline", {"value": 1})
        candidate = observation("candidate", {"value": 1})
        client = FakeClient(baseline, candidate)
        result = PairedRunner("https://baseline.example/api", "https://candidate.example/api", client=client).run_case(case)  # type: ignore[arg-type]
        self.assertTrue(result.matched)
        self.assertEqual({"baseline", "candidate"}, set(client.calls))
        self.assertIs(result.baseline, baseline)
        self.assertIs(result.candidate, candidate)
        self.assertTrue(result.request_id)

    # TP-COMPATIBILITY-API-CONTRACT-031
    def test_tp_031_json_type_value_key_order_status_and_header_diffs_are_located(self) -> None:
        cases = [
            ({"value": 1}, {"value": "1"}, "$.value"),
            ({"value": 1}, {}, "$.value"),
            ({"items": [1, 2]}, {"items": [2, 1]}, "$.items[0]"),
        ]
        case = RequestCase("CASE", "MOD", "GET", "/v1/example", "example")
        for left, right, path in cases:
            with self.subTest(left=left, right=right):
                result = compare_observations("request", case, observation("baseline", left), observation("candidate", right))
                self.assertFalse(result.matched)
                self.assertIn(path, {difference.path for difference in result.differences})
        result = compare_observations(
            "request",
            case,
            observation("baseline", {}, status=200),
            observation("candidate", {}, status=201, content_type="application/problem+json"),
        )
        self.assertEqual({"$status", "$headers.content-type"}, {item.path for item in result.differences})

    def test_status_mode_compares_status_and_selected_headers_without_dynamic_body(self) -> None:
        case = RequestCase("CASE", "MOD", "GET", "/v1/example", "example", mode="status")
        result = compare_observations(
            "request",
            case,
            observation("baseline", {"tip": 10}),
            observation("candidate", {"tip": 11}),
        )
        self.assertTrue(result.matched)

    # TP-COMPATIBILITY-API-CONTRACT-032
    def test_tp_032_only_explicit_json_pointer_paths_are_normalized_and_reported(self) -> None:
        case = RequestCase(
            "CASE",
            "MOD",
            "GET",
            "/v1/example",
            "example",
            ignore_paths=("/meta/generated_at", "/data/*/confirmations"),
        )
        left = {"meta": {"generated_at": 1}, "data": [{"id": "x", "confirmations": 1}]}
        right = {"meta": {"generated_at": 2}, "data": [{"id": "x", "confirmations": 9}]}
        result = compare_observations("request", case, observation("baseline", left), observation("candidate", right))
        self.assertTrue(result.matched)
        self.assertEqual(["ignore:/data/0/confirmations", "ignore:/meta/generated_at"], result.normalizations)
        undeclared = {"meta": {"generated_at": 2}, "data": [{"id": "changed", "confirmations": 9}]}
        result = compare_observations("request", case, observation("baseline", left), observation("candidate", undeclared))
        self.assertFalse(result.matched)
        self.assertEqual("$.data[0].id", result.differences[0].path)

    def test_v1_jsonapi_resource_ids_are_local_but_business_fields_remain_strict(self) -> None:
        case = RequestCase(
            "CASE",
            "MOD",
            "GET",
            "/v1/blocks",
            "blocks",
            ignore_jsonapi_resource_ids=True,
        )
        left = {
            "data": [
                {"id": "22118650", "type": "block_list", "attributes": {"number": "22049187"}}
            ]
        }
        right = {
            "data": [
                {"id": "22118708", "type": "block_list", "attributes": {"number": "22049187"}}
            ]
        }
        result = compare_observations("request", case, observation("baseline", left), observation("candidate", right))
        self.assertTrue(result.matched)
        self.assertEqual(["ignore:/data/0/id"], result.normalizations)

        right["data"][0]["attributes"]["number"] = "22049188"
        result = compare_observations("request", case, observation("baseline", left), observation("candidate", right))
        self.assertFalse(result.matched)
        self.assertEqual("$.data[0].attributes.number", result.differences[0].path)

    def test_jsonapi_id_normalization_covers_relationship_and_included_resources(self) -> None:
        case = RequestCase(
            "CASE",
            "MOD",
            "GET",
            "/v1/example",
            "example",
            ignore_jsonapi_resource_ids=True,
        )
        left = {
            "data": {
                "id": "1",
                "type": "example",
                "relationships": {"owner": {"data": {"id": "2", "type": "address"}}},
            },
            "included": [{"id": "3", "type": "address", "attributes": {"address_hash": "ckt1"}}],
        }
        right = {
            "data": {
                "id": "10",
                "type": "example",
                "relationships": {"owner": {"data": {"id": "20", "type": "address"}}},
            },
            "included": [{"id": "30", "type": "address", "attributes": {"address_hash": "ckt1"}}],
        }
        result = compare_observations("request", case, observation("baseline", left), observation("candidate", right))
        self.assertTrue(result.matched)
        self.assertEqual(
            ["ignore:/data/id", "ignore:/data/relationships/owner/data/id", "ignore:/included/0/id"],
            result.normalizations,
        )

    def test_local_numeric_database_ids_are_ignored_but_stable_protocol_ids_remain_strict(self) -> None:
        case = RequestCase(
            "CASE",
            "MOD",
            "GET",
            "/v2/example",
            "example",
            ignore_local_numeric_ids=True,
        )
        left = {
            "id": 41,
            "data": {
                "block_id": "101",
                "display_inputs": [{"id": "201", "token_id": "7"}],
            },
        }
        right = {
            "id": 99,
            "data": {
                "block_id": "102",
                "display_inputs": [{"id": "301", "token_id": "7"}],
            },
        }
        result = compare_observations("request", case, observation("baseline", left), observation("candidate", right))
        self.assertTrue(result.matched)
        self.assertEqual(
            ["ignore:/data/block_id", "ignore:/data/display_inputs/0/id", "ignore:/id"],
            result.normalizations,
        )

        right["data"]["display_inputs"][0]["token_id"] = "8"
        result = compare_observations("request", case, observation("baseline", left), observation("candidate", right))
        self.assertFalse(result.matched)
        self.assertEqual("$.data.display_inputs[0].token_id", result.differences[0].path)

    # TP-COMPATIBILITY-API-CONTRACT-033
    def test_tp_033_ordered_set_and_csv_modes_have_distinct_semantics(self) -> None:
        left = observation("baseline", {"items": [{"id": 1}, {"id": 2}]})
        right = observation("candidate", {"items": [{"id": 2}, {"id": 1}]})
        ordered = RequestCase("ORDER", "MOD", "GET", "/v1/example", "example", mode="ordered")
        self.assertFalse(compare_observations("request", ordered, left, right).matched)
        set_case = RequestCase("SET", "MOD", "GET", "/v1/example", "example", mode="json", set_paths=("/items",))
        self.assertTrue(compare_observations("request", set_case, left, right).matched)
        csv_case = RequestCase("CSV", "MOD", "GET", "/v1/example.csv", "example", mode="csv")
        csv_result = compare_observations(
            "request",
            csv_case,
            observation("baseline", b'name,value\n"a,b",1\n', content_type="text/csv"),
            observation("candidate", b'name,value\n"a,b",2\n', content_type="text/csv"),
        )
        self.assertEqual("$csv[2,2]", csv_result.differences[0].path)

    # TP-COMPATIBILITY-API-CONTRACT-034
    def test_tp_034_transport_and_decode_failures_name_side_and_phase(self) -> None:
        case = RequestCase("CASE", "MOD", "GET", "/v1/example", "example")
        failed = Observation("baseline", "GET", "https://baseline", phase="transport", error_type="TimeoutError", error="timed out")
        result = compare_observations("request", case, failed, observation("candidate", {}))
        self.assertEqual(("transport", "baseline"), (result.differences[0].phase, result.differences[0].path))
        result = compare_observations("request", case, observation("baseline", b"{"), observation("candidate", {}))
        self.assertEqual(("decode", "baseline"), (result.differences[0].phase, result.differences[0].path))

    # TP-COMPATIBILITY-API-CONTRACT-035
    def test_tp_035_sensitive_headers_queries_and_json_fields_are_redacted(self) -> None:
        self.assertEqual(MASK, redact_headers({"Authorization": "Bearer secret"})["Authorization"])
        self.assertIn("token=%3Credacted%3E", redact_url("https://example/api?token=secret&height=1"))
        self.assertEqual({"nested": {"signature": MASK, "value": 1}}, redact_value({"nested": {"signature": "secret", "value": 1}}))
        case = RequestCase("CASE", "MOD", "GET", "/v1/example", "example")
        base = observation("baseline", {"ok": True})
        base.url += "?access_token=secret"
        base.headers["set-cookie"] = "session=secret"
        payload = report_payload([compare_observations("request", case, base, observation("candidate", {"ok": True}))])
        report = payload["results"][0]["baseline"]
        self.assertNotIn("secret", report["url"])
        self.assertEqual(MASK, report["headers"]["set-cookie"])
        secret_result = compare_observations(
            "request",
            case,
            observation("baseline", {"token": "baseline-secret"}),
            observation("candidate", {"token": "candidate-secret"}),
        )
        secret_report = report_payload([secret_result])["results"][0]
        rendered = json.dumps(secret_report, ensure_ascii=False)
        self.assertNotIn("baseline-secret", rendered)
        self.assertNotIn("candidate-secret", rendered)
        self.assertEqual(MASK, json.loads(secret_report["baseline"]["body"])["token"])

    # TP-COMPATIBILITY-API-CONTRACT-036
    def test_tp_036_http_and_content_mismatch_are_not_retried_by_runner(self) -> None:
        case = RequestCase("CASE", "MOD", "GET", "/v1/example", "example", retries=3)
        client = FakeClient(observation("baseline", {"value": 1}, status=500), observation("candidate", {"value": 2}, status=500))
        result = PairedRunner("https://baseline.example/api", "https://candidate.example/api", client=client).run_case(case)  # type: ignore[arg-type]
        self.assertFalse(result.matched)
        self.assertEqual(2, len(client.calls))


if __name__ == "__main__":
    unittest.main()
