from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Literal
from urllib.parse import urlencode

from .models import Attempt, Observation, RequestCase


class StdlibHttpClient:
    def __init__(self, *, max_body_bytes: int = 10_000_000, user_agent: str = "ckb-api-compat/0.1.0") -> None:
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self.max_body_bytes = max_body_bytes
        self.user_agent = user_agent

    @staticmethod
    def _url(side: Literal["baseline", "candidate"], base_url: str, case: RequestCase) -> str:
        url = base_url.rstrip("/") + case.path_for(side)
        if case.query:
            url += "?" + urlencode(case.query, doseq=True)
        return url

    def observe(
        self,
        side: Literal["baseline", "candidate"],
        base_url: str,
        case: RequestCase,
    ) -> Observation:
        url = self._url(side, base_url, case)
        body: bytes | None = None
        headers = {name: value for name, value in case.headers.items()}
        headers.setdefault("User-Agent", self.user_agent)
        if case.body is not None:
            if isinstance(case.body, bytes):
                body = case.body
            elif isinstance(case.body, str):
                body = case.body.encode("utf-8")
            else:
                body = json.dumps(case.body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                headers.setdefault("Content-Type", "application/json")
        attempts: list[Attempt] = []
        for attempt_number in range(1, case.retries + 2):
            started = time.monotonic()
            request = urllib.request.Request(url, data=body, headers=headers, method=case.method)
            try:
                with urllib.request.urlopen(request, timeout=case.timeout) as response:
                    payload = response.read(self.max_body_bytes + 1)
                    if len(payload) > self.max_body_bytes:
                        raise ValueError(f"response exceeds max_body_bytes={self.max_body_bytes}")
                    elapsed = (time.monotonic() - started) * 1000
                    attempts.append(Attempt(attempt_number, "complete", elapsed))
                    return Observation(
                        side=side,
                        method=case.method,
                        url=url,
                        status=response.status,
                        headers={name.lower(): value for name, value in response.headers.items()},
                        body=payload,
                        elapsed_ms=elapsed,
                        attempts=attempts,
                    )
            except urllib.error.HTTPError as error:
                response_headers = {name.lower(): value for name, value in error.headers.items()}
                try:
                    payload = error.read(self.max_body_bytes + 1)
                finally:
                    error.close()
                elapsed = (time.monotonic() - started) * 1000
                if len(payload) > self.max_body_bytes:
                    payload = payload[: self.max_body_bytes]
                attempts.append(Attempt(attempt_number, "http", elapsed))
                return Observation(
                    side=side,
                    method=case.method,
                    url=url,
                    status=error.code,
                    headers=response_headers,
                    body=payload,
                    elapsed_ms=elapsed,
                    phase="http",
                    attempts=attempts,
                )
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError, ValueError) as error:
                elapsed = (time.monotonic() - started) * 1000
                error_type = type(error).__name__
                attempts.append(Attempt(attempt_number, "transport", elapsed, error_type, str(error)))
                if attempt_number <= case.retries:
                    continue
                return Observation(
                    side=side,
                    method=case.method,
                    url=url,
                    elapsed_ms=elapsed,
                    phase="transport",
                    error_type=error_type,
                    error=str(error),
                    attempts=attempts,
                )
        raise AssertionError("unreachable retry loop")
