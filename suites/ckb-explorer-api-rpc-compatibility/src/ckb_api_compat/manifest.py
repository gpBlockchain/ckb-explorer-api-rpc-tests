from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .models import RequestCase


PATH_SLOT = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")
MUTATING_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})
VALID_WIRING = frozenset({"ACTIVE", "ROUTE_ONLY", "NAMESPACE_MISMATCH"})


def _read_json(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def load_endpoint_specs(path: str | Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("endpoints"), list):
        raise ValueError("manifest must be an object containing an endpoints array")
    endpoints = payload["endpoints"]
    ids: set[str] = set()
    keys: set[tuple[str, str]] = set()
    for item in endpoints:
        required = {"id", "module", "method", "path", "purpose", "wiring"}
        if not isinstance(item, dict) or not required.issubset(item):
            raise ValueError(f"invalid endpoint entry: {item!r}")
        item["method"] = str(item["method"]).upper()
        if item["wiring"] not in VALID_WIRING:
            raise ValueError(f"invalid wiring for {item['id']}: {item['wiring']}")
        if item["id"] in ids:
            raise ValueError(f"duplicate endpoint id: {item['id']}")
        key = (item["method"], item["path"])
        if key in keys:
            raise ValueError(f"duplicate method/path: {key}")
        ids.add(item["id"])
        keys.add(key)
    return endpoints


def load_fixture_config(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {"comparison_defaults": {}, "variables": {}, "cases": {}}
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError("fixture file must contain an object")
    variables = payload.get("variables", {})
    cases = payload.get("cases", {})
    comparison_defaults = payload.get("comparison_defaults", {})
    if not isinstance(variables, dict) or not isinstance(cases, dict) or not isinstance(comparison_defaults, dict):
        raise ValueError("fixture comparison_defaults, variables, and cases must be objects")
    return {
        "comparison_defaults": comparison_defaults,
        "variables": variables,
        "cases": cases,
    }


def _resolve_path(path: str, variables: dict[str, Any], path_params: dict[str, Any]) -> tuple[str, list[str]]:
    merged = {**variables, **path_params}
    missing: list[str] = []

    def replace_slot(match: re.Match[str]) -> str:
        name = match.group(1)
        value = merged.get(name)
        if value is None or value == "":
            missing.append(name)
            return match.group(0)
        from urllib.parse import quote

        return quote(str(value), safe="")

    return PATH_SLOT.sub(replace_slot, path), missing


def build_cases(
    endpoint_specs: Iterable[dict[str, Any]],
    fixture_config: dict[str, Any],
    *,
    allow_mutations: bool = False,
    include_known_defects: bool = False,
    enable_csv_exports: bool = False,
    default_timeout: float = 20.0,
    default_retries: int = 0,
) -> list[RequestCase]:
    variables = fixture_config.get("variables", {})
    overrides = fixture_config.get("cases", {})
    comparison_defaults = fixture_config.get("comparison_defaults", {})
    if not isinstance(comparison_defaults, dict):
        raise ValueError("comparison_defaults must be an object")
    ignore_v1_jsonapi_resource_ids = comparison_defaults.get(
        "ignore_v1_jsonapi_resource_ids",
        False,
    )
    if not isinstance(ignore_v1_jsonapi_resource_ids, bool):
        raise ValueError("ignore_v1_jsonapi_resource_ids must be true or false")
    ignore_local_numeric_ids = comparison_defaults.get("ignore_local_numeric_ids", False)
    if not isinstance(ignore_local_numeric_ids, bool):
        raise ValueError("ignore_local_numeric_ids must be true or false")
    cases: list[RequestCase] = []
    for spec in endpoint_specs:
        override = overrides.get(spec["id"], {})
        if not isinstance(override, dict):
            raise ValueError(f"fixture case {spec['id']} must be an object")
        common_path_params = override.get("path_params", {})
        baseline_path_params = {**common_path_params, **override.get("baseline_path_params", {})}
        candidate_path_params = {**common_path_params, **override.get("candidate_path_params", {})}
        baseline_path, baseline_missing = _resolve_path(spec["path"], variables, baseline_path_params)
        candidate_path, candidate_missing = _resolve_path(spec["path"], variables, candidate_path_params)
        path = baseline_path if baseline_path == candidate_path else spec["path"]
        method = spec["method"].upper()
        wiring = spec["wiring"]
        enabled = bool(override.get("enabled", True))
        reason = override.get("skip_reason")
        if spec.get("mode") == "csv" and "enabled" not in override and not enable_csv_exports:
            enabled = False
            reason = reason or "CSV export disabled until the case fixture explicitly enables it"
        if wiring != "ACTIVE" and not include_known_defects:
            enabled = False
            reason = reason or f"known route wiring state {wiring}; use --include-known-defects"
        missing = sorted(set(baseline_missing + candidate_missing))
        if missing:
            if wiring != "ACTIVE" and include_known_defects:
                for name in missing:
                    baseline_path = baseline_path.replace(f":{name}", "__compat_missing__")
                    candidate_path = candidate_path.replace(f":{name}", "__compat_missing__")
                path = baseline_path if baseline_path == candidate_path else spec["path"]
            else:
                enabled = False
                reason = reason or "missing path fixture(s): " + ", ".join(missing)
        mutation_allowed = bool(override.get("allow_mutation", False))
        if method in MUTATING_METHODS and not allow_mutations:
            enabled = False
            reason = reason or "mutation disabled by settings or CLI"
        elif method in MUTATING_METHODS and not mutation_allowed:
            enabled = False
            reason = reason or "mutation case requires allow_mutation=true"
        headers = {str(k): str(v) for k, v in override.get("headers", {}).items()}
        if path.startswith("/v1/"):
            headers.setdefault("Accept", "application/vnd.api+json")
            headers.setdefault("Content-Type", "application/vnd.api+json")
        cases.append(
            RequestCase(
                id=spec["id"],
                module=spec["module"],
                method=method,
                path=path,
                purpose=spec["purpose"],
                baseline_path=baseline_path,
                candidate_path=candidate_path,
                wiring=wiring,
                headers=headers,
                query=override.get("query", {}),
                body=override.get("body"),
                mode=override.get("mode", spec.get("mode", "auto")),
                selected_headers=tuple(override.get("selected_headers", ["content-type"])),
                ignore_paths=tuple(override.get("ignore_paths", [])),
                ignore_jsonapi_resource_ids=bool(
                    override.get(
                        "ignore_jsonapi_resource_ids",
                        ignore_v1_jsonapi_resource_ids and spec["path"].startswith("/v1/"),
                    )
                ),
                ignore_local_numeric_ids=bool(
                    override.get("ignore_local_numeric_ids", ignore_local_numeric_ids)
                ),
                set_paths=tuple(override.get("set_paths", [])),
                timeout=float(override.get("timeout", default_timeout)),
                retries=int(override.get("retries", default_retries)),
                enabled=enabled,
                allow_mutation=mutation_allowed,
                skip_reason=reason,
            )
        )
    return cases


def filter_cases(
    cases: Iterable[RequestCase], *, ids: set[str] | None = None, modules: set[str] | None = None
) -> list[RequestCase]:
    result = []
    for case in cases:
        if ids and case.id not in ids:
            continue
        if modules and case.module not in modules:
            continue
        result.append(case)
    return result
