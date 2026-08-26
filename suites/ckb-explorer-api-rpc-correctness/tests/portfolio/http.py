from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS

from tests.contract_script.test_v2_scripts_ckb_transactions import _StatusPreservingProcessor


def portfolio_response(
    oracle: NetworkOracle,
    path: str,
    *,
    method: str = "GET",
    json_body: object | None = None,
    token: str | None = None,
) -> tuple[int, bytes]:
    headers = dict(V1_HEADERS)
    headers["User-Agent"] = oracle.client.user_agent
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = None if json_body is None else json.dumps(json_body, separators=(",", ":")).encode()
    opener = urllib.request.build_opener(_StatusPreservingProcessor())
    for attempt in range(oracle.client.retries + 1):
        try:
            request = urllib.request.Request(
                oracle.network.explorer_api_url + path,
                data=data,
                headers=headers,
                method=method,
            )
            with opener.open(request, timeout=oracle.client.timeout) as response:
                raw = response.read(oracle.client.max_body_bytes + 1)
                status = int(response.status)
            if len(raw) > oracle.client.max_body_bytes:
                raise OracleUnavailable(f"{oracle.network.name} Explorer response is too large")
            if attempt < oracle.client.retries and (status == 429 or status >= 500):
                time.sleep(0.2 * (attempt + 1))
                continue
            return status, raw
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as error:
            if attempt < oracle.client.retries:
                time.sleep(0.2 * (attempt + 1))
                continue
            raise OracleUnavailable(f"{oracle.network.name} Explorer transport failure: {error}") from error
    raise AssertionError("unreachable HTTP retry loop")
