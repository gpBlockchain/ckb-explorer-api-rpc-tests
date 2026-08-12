from __future__ import annotations

import base64
import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


CompareMode = Literal["auto", "status", "json", "ordered", "set", "csv", "raw"]


@dataclass(frozen=True, slots=True)
class RequestCase:
    id: str
    module: str
    method: str
    path: str
    purpose: str
    baseline_path: str | None = None
    candidate_path: str | None = None
    wiring: str = "ACTIVE"
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    body: Any = None
    mode: CompareMode = "auto"
    selected_headers: tuple[str, ...] = ("content-type",)
    ignore_paths: tuple[str, ...] = ()
    ignore_jsonapi_resource_ids: bool = False
    ignore_local_numeric_ids: bool = False
    set_paths: tuple[str, ...] = ()
    timeout: float = 20.0
    retries: int = 0
    enabled: bool = True
    allow_mutation: bool = False
    skip_reason: str | None = None

    def __post_init__(self) -> None:
        method = self.method.upper()
        object.__setattr__(self, "method", method)
        object.__setattr__(
            self,
            "selected_headers",
            tuple(name.lower() for name in self.selected_headers),
        )
        if not self.id or not self.path.startswith("/"):
            raise ValueError("case id must be nonempty and path must begin with '/'")
        for side_path in (self.baseline_path, self.candidate_path):
            if side_path is not None and not side_path.startswith("/"):
                raise ValueError("side-specific paths must begin with '/'")
        if self.timeout <= 0 or self.retries < 0:
            raise ValueError("timeout must be positive and retries cannot be negative")

    def path_for(self, side: Literal["baseline", "candidate"]) -> str:
        """Return the resolved path for one environment.

        Some Explorer resources expose deployment-local database IDs.  A case
        can therefore point each environment at the same semantic resource
        while retaining ``path`` as the endpoint's canonical route.
        """
        if side == "baseline":
            return self.baseline_path or self.path
        return self.candidate_path or self.path


@dataclass(slots=True)
class Attempt:
    number: int
    phase: str
    elapsed_ms: float
    error_type: str | None = None
    error: str | None = None


@dataclass(slots=True)
class Observation:
    side: Literal["baseline", "candidate"]
    method: str
    url: str
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    elapsed_ms: float = 0.0
    phase: str = "complete"
    error_type: str | None = None
    error: str | None = None
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def transport_ok(self) -> bool:
        return self.status is not None and self.error is None

    def to_dict(self, *, max_body_chars: int = 200_000) -> dict[str, Any]:
        try:
            decoded = self.body.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            decoded = base64.b64encode(self.body).decode("ascii")
            encoding = "base64"
        truncated = len(decoded) > max_body_chars
        if truncated:
            decoded = decoded[:max_body_chars]
        return {
            "side": self.side,
            "method": self.method,
            "url": self.url,
            "status": self.status,
            "headers": dict(sorted(self.headers.items())),
            "body": decoded,
            "body_encoding": encoding,
            "body_sha256": hashlib.sha256(self.body).hexdigest(),
            "body_bytes": len(self.body),
            "body_truncated": truncated,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "phase": self.phase,
            "error_type": self.error_type,
            "error": self.error,
            "attempts": [asdict(attempt) for attempt in self.attempts],
        }


@dataclass(frozen=True, slots=True)
class Difference:
    phase: str
    path: str
    baseline: Any
    candidate: Any
    detail: str


@dataclass(slots=True)
class ComparisonResult:
    request_id: str
    case_id: str
    matched: bool
    baseline: Observation
    candidate: Observation
    differences: list[Difference] = field(default_factory=list)
    normalizations: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None

    def to_dict(self, *, max_body_chars: int = 200_000) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "case_id": self.case_id,
            "matched": self.matched,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "differences": [asdict(item) for item in self.differences],
            "normalizations": self.normalizations,
            "baseline": self.baseline.to_dict(max_body_chars=max_body_chars),
            "candidate": self.candidate.to_dict(max_body_chars=max_body_chars),
        }
