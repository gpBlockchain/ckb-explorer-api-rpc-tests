from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any

from ckb_rpc_correctness.oracle import OracleUnavailable


def fiber_rpc(network_name: str, endpoints: list[str], method: str, params: list[object]) -> Any:
    errors: list[str] = []
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for endpoint in endpoints:
        try:
            request = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "ckb-explorer-rpc-correctness/1"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                body = json.loads(response.read(16 * 1024 * 1024))
            if not isinstance(body, dict) or "result" not in body or body.get("error") is not None:
                raise ValueError(f"invalid JSON-RPC response: {body!r}")
            return body["result"]
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"{endpoint}: {error}")
    raise OracleUnavailable(f"{network_name} Fiber RPC unavailable: {'; '.join(errors)}")
