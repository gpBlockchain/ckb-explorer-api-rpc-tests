from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Mapping


class HttpClientError(RuntimeError):
    pass


class JsonHttpClient:
    def __init__(
        self,
        *,
        timeout: float = 30,
        retries: int = 1,
        user_agent: str = "ckb-rpc-correctness/0.1.0",
        max_body_bytes: int = 20_000_000,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
        self.max_body_bytes = max_body_bytes

    def request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        json_body: object | None = None,
    ) -> Any:
        request_headers = dict(headers or {})
        request_headers.setdefault("User-Agent", self.user_agent)
        body = None
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        for attempt in range(self.retries + 1):
            request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read(self.max_body_bytes + 1)
                    if len(raw) > self.max_body_bytes:
                        raise HttpClientError(f"{url} response exceeds {self.max_body_bytes} bytes")
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError as error:
                        raise HttpClientError(f"{url} returned invalid JSON: {error}") from error
            except urllib.error.HTTPError as error:
                try:
                    detail = error.read(4096).decode("utf-8", errors="replace")
                finally:
                    error.close()
                if attempt < self.retries and (error.code == 429 or error.code >= 500):
                    time.sleep(0.2 * (attempt + 1))
                    continue
                raise HttpClientError(f"{url} returned HTTP {error.code}: {detail}") from error
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as error:
                if attempt < self.retries:
                    time.sleep(0.2 * (attempt + 1))
                    continue
                raise HttpClientError(f"{url} transport failure: {type(error).__name__}: {error}") from error
        raise AssertionError("unreachable HTTP retry loop")
