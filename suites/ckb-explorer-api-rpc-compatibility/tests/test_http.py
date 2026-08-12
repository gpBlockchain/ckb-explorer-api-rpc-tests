from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from ckb_api_compat.http import StdlibHttpClient
from ckb_api_compat.models import RequestCase


class FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.status = status
        self._body = body
        self.headers = headers

    def read(self, limit: int = -1) -> bytes:
        return self._body if limit < 0 else self._body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class StdlibHttpClientTests(unittest.TestCase):
    def test_post_serializes_explicit_json_data_into_the_request_body(self) -> None:
        case = RequestCase(
            "CASE",
            "MOD",
            "POST",
            "/v2/das_accounts",
            "query",
            body={"addresses": ["test"]},
        )
        response = FakeResponse(200, b"{}", {"Content-Type": "application/json"})
        with patch("urllib.request.urlopen", return_value=response) as mocked:
            StdlibHttpClient().observe("baseline", "https://example.test/api", case)

        request = mocked.call_args.args[0]
        self.assertEqual("POST", request.method)
        self.assertEqual(b'{"addresses":["test"]}', request.data)
        self.assertEqual("application/json", request.get_header("Content-type"))

    def test_http_success_keeps_status_headers_body_query_and_attempt(self) -> None:
        case = RequestCase("CASE", "MOD", "GET", "/ok", "ok", query={"page": 1})
        response = FakeResponse(200, b'{"ok":true}', {"Content-Type": "application/json"})
        with patch("urllib.request.urlopen", return_value=response) as mocked:
            result = StdlibHttpClient().observe("baseline", "https://example.test/api", case)
        self.assertEqual(200, result.status)
        self.assertEqual("application/json", result.headers["content-type"])
        self.assertEqual({"ok": True}, json.loads(result.body))
        self.assertEqual(1, len(result.attempts))
        self.assertEqual("https://example.test/api/ok?page=1", mocked.call_args.args[0].full_url)

    def test_each_side_can_use_its_own_deployment_local_resource_id(self) -> None:
        case = RequestCase(
            "CASE",
            "MOD",
            "GET",
            "/v1/cells/:id",
            "same semantic cell",
            baseline_path="/v1/cells/41",
            candidate_path="/v1/cells/99",
        )
        response = FakeResponse(200, b"{}", {"Content-Type": "application/json"})
        with patch("urllib.request.urlopen", return_value=response) as mocked:
            StdlibHttpClient().observe("baseline", "https://baseline.test/api", case)
            StdlibHttpClient().observe("candidate", "https://candidate.test/api", case)
        self.assertEqual("https://baseline.test/api/v1/cells/41", mocked.call_args_list[0].args[0].full_url)
        self.assertEqual("https://candidate.test/api/v1/cells/99", mocked.call_args_list[1].args[0].full_url)

    # TP-COMPATIBILITY-API-CONTRACT-036
    def test_http_error_is_an_observation_and_never_retried(self) -> None:
        case = RequestCase("CASE", "MOD", "GET", "/error", "error", retries=3)
        error = urllib.error.HTTPError(
            "https://example.test/api/error",
            422,
            "unprocessable",
            {"Content-Type": "application/json"},
            io.BytesIO(b'{"error":"fixture"}'),
        )
        with patch("urllib.request.urlopen", side_effect=error) as mocked:
            result = StdlibHttpClient().observe("baseline", "https://example.test/api", case)
        self.assertEqual(422, result.status)
        self.assertEqual(1, mocked.call_count)
        self.assertEqual("http", result.phase)

    # TP-COMPATIBILITY-API-CONTRACT-036
    def test_transport_failure_retries_and_keeps_all_attempts(self) -> None:
        case = RequestCase("CASE", "MOD", "GET", "/retry", "retry", retries=1)
        response = FakeResponse(200, b"{}", {"Content-Type": "application/json"})
        with patch("urllib.request.urlopen", side_effect=[urllib.error.URLError("temporary"), response]) as mocked:
            result = StdlibHttpClient().observe("baseline", "https://example.test/api", case)
        self.assertEqual(200, result.status)
        self.assertEqual(2, mocked.call_count)
        self.assertEqual(["transport", "complete"], [attempt.phase for attempt in result.attempts])


if __name__ == "__main__":
    unittest.main()
