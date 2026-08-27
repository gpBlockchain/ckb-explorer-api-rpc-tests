from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from ckb_rpc_correctness.http import HttpClientError, JsonHttpClient


class JsonHttpClientTests(unittest.TestCase):
    def test_request_json_retries_read_timeout_then_returns_response(self) -> None:
        timed_out_response = MagicMock()
        timed_out_response.__enter__.return_value = timed_out_response
        timed_out_response.read.side_effect = TimeoutError("read timed out")
        successful_response = MagicMock()
        successful_response.__enter__.return_value = successful_response
        successful_response.read.return_value = b'{"height": 22208581}'
        client = JsonHttpClient(timeout=1)

        with (
            patch(
                "ckb_rpc_correctness.http.urllib.request.urlopen",
                side_effect=[timed_out_response, successful_response],
            ) as urlopen,
            patch("ckb_rpc_correctness.http.time.sleep") as sleep,
        ):
            payload = client.request_json("https://explorer.invalid/api/v1/blocks/22208581")

        self.assertEqual({"height": 22208581}, payload)
        self.assertEqual(2, urlopen.call_count)
        sleep.assert_called_once_with(0.2)

    def test_request_json_reports_transport_failure_after_retry_budget_is_exhausted(self) -> None:
        timed_out_response = MagicMock()
        timed_out_response.__enter__.return_value = timed_out_response
        timed_out_response.read.side_effect = TimeoutError("read timed out")
        client = JsonHttpClient(timeout=1)

        with (
            patch(
                "ckb_rpc_correctness.http.urllib.request.urlopen",
                return_value=timed_out_response,
            ) as urlopen,
            patch("ckb_rpc_correctness.http.time.sleep") as sleep,
            self.assertRaisesRegex(HttpClientError, "transport failure: TimeoutError: read timed out"),
        ):
            client.request_json("https://explorer.invalid/api/v1/blocks/22208581")

        self.assertEqual(4, urlopen.call_count)
        self.assertEqual(3, sleep.call_count)
        for actual, expected in zip(
            (item.args[0] for item in sleep.call_args_list),
            (0.2, 0.4, 0.6),
            strict=True,
        ):
            self.assertAlmostEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
