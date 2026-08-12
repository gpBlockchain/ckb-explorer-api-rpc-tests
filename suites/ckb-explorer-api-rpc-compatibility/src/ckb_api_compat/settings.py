from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SUITE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_FILE = SUITE_ROOT / "config" / "settings.json"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    settings_file: Path
    baseline_url: str
    candidate_url: str
    fixture_rpc_url: str
    manifest_file: Path
    fixtures_file: Path
    report_file: Path
    run_live: bool
    include_known_defects: bool
    allow_mutations: bool
    run_exports: bool
    strict_fixtures: bool
    fail_fast: bool
    print_responses: bool
    timeout_seconds: float
    transport_retries: int
    max_body_bytes: int
    max_report_body_chars: int


def _boolean(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in TRUE_VALUES:
            return True
        if lowered in FALSE_VALUES:
            return False
    raise ValueError(f"{name} must be true or false")


def _env_boolean(environ: Mapping[str, str], name: str, default: bool) -> bool:
    value = environ.get(name)
    return default if value is None else _boolean(value, name)


def _path(value: object, *, settings_file: Path, name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty path string")
    path = Path(value).expanduser()
    return path if path.is_absolute() else settings_file.parent / path


def load_settings(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> RuntimeSettings:
    env = os.environ if environ is None else environ
    selected = Path(env.get("CKB_COMPAT_SETTINGS", str(path or DEFAULT_SETTINGS_FILE))).expanduser().resolve()
    with selected.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("settings file must contain a JSON object")

    def required(name: str):
        if name not in payload:
            raise ValueError(f"settings missing required key: {name}")
        return payload[name]

    baseline = env.get("BASELINE_API_URL", str(required("baseline_url"))).rstrip("/")
    candidate = env.get("CANDIDATE_API_URL", str(required("candidate_url"))).rstrip("/")
    manifest_value = env.get("COMPAT_MANIFEST", str(required("manifest_file")))
    fixtures_value = env.get("COMPAT_FIXTURES", str(required("fixtures_file")))
    report_value = env.get("COMPAT_REPORT", str(required("report_file")))
    settings = RuntimeSettings(
        settings_file=selected,
        baseline_url=baseline,
        candidate_url=candidate,
        fixture_rpc_url=env.get("CKB_RPC_URL", str(payload.get("fixture_rpc_url", "https://testnet.ckbapp.dev/"))).rstrip("/"),
        manifest_file=_path(manifest_value, settings_file=selected, name="manifest_file"),
        fixtures_file=_path(fixtures_value, settings_file=selected, name="fixtures_file"),
        report_file=_path(report_value, settings_file=selected, name="report_file"),
        run_live=_env_boolean(env, "RUN_LIVE_COMPAT", _boolean(required("run_live"), "run_live")),
        include_known_defects=_env_boolean(
            env,
            "RUN_LIVE_KNOWN_DEFECTS",
            _boolean(required("include_known_defects"), "include_known_defects"),
        ),
        allow_mutations=_env_boolean(
            env,
            "RUN_LIVE_MUTATIONS",
            _boolean(required("allow_mutations"), "allow_mutations"),
        ),
        run_exports=_env_boolean(env, "RUN_LIVE_EXPORTS", _boolean(required("run_exports"), "run_exports")),
        strict_fixtures=_env_boolean(
            env,
            "STRICT_FIXTURES",
            _boolean(required("strict_fixtures"), "strict_fixtures"),
        ),
        fail_fast=_env_boolean(env, "FAIL_FAST", _boolean(required("fail_fast"), "fail_fast")),
        print_responses=_env_boolean(
            env,
            "PRINT_RESPONSES",
            _boolean(required("print_responses"), "print_responses"),
        ),
        timeout_seconds=float(required("timeout_seconds")),
        transport_retries=int(required("transport_retries")),
        max_body_bytes=int(required("max_body_bytes")),
        max_report_body_chars=int(required("max_report_body_chars")),
    )
    if not settings.baseline_url.startswith(("http://", "https://")):
        raise ValueError("baseline_url must use http:// or https://")
    if not settings.candidate_url.startswith(("http://", "https://")):
        raise ValueError("candidate_url must use http:// or https://")
    if not settings.fixture_rpc_url.startswith(("http://", "https://")):
        raise ValueError("fixture_rpc_url must use http:// or https://")
    if settings.timeout_seconds <= 0 or settings.transport_retries < 0:
        raise ValueError("timeout_seconds must be positive and transport_retries nonnegative")
    if settings.max_body_bytes <= 0 or settings.max_report_body_chars <= 0:
        raise ValueError("body limits must be positive")
    return settings
