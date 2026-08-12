from __future__ import annotations

import csv
import io
import json
from copy import deepcopy
from typing import Any

from .models import ComparisonResult, Difference, Observation, RequestCase


MAX_DIFFERENCES = 200
_MISSING = object()


def _pointer_segments(pointer: str) -> list[str]:
    if pointer in ("", "/"):
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"JSON normalization path must be an RFC 6901 pointer: {pointer}")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _walk_targets(value: Any, segments: list[str], prefix: str = ""):
    if not segments:
        yield None, None, value, prefix or "/"
        return
    head, *tail = segments
    if isinstance(value, dict):
        keys = list(value) if head == "*" else [head]
        for key in keys:
            if key in value:
                path = f"{prefix}/{key.replace('~', '~0').replace('/', '~1')}"
                if tail:
                    yield from _walk_targets(value[key], tail, path)
                else:
                    yield value, key, value[key], path
    elif isinstance(value, list):
        indexes = range(len(value)) if head == "*" else ([int(head)] if head.isdigit() else [])
        for index in indexes:
            if 0 <= index < len(value):
                path = f"{prefix}/{index}"
                if tail:
                    yield from _walk_targets(value[index], tail, path)
                else:
                    yield value, index, value[index], path


def normalize_json(
    value: Any, *, ignore_paths: tuple[str, ...], set_paths: tuple[str, ...]
) -> tuple[Any, list[str]]:
    result = deepcopy(value)
    applied: list[str] = []
    for pointer in ignore_paths:
        segments = _pointer_segments(pointer)
        if not segments:
            result = "<normalized>"
            applied.append(f"ignore:{pointer or '/'}")
            continue
        for parent, key, _old, actual in list(_walk_targets(result, segments)):
            if parent is not None:
                parent[key] = "<normalized>"
                applied.append(f"ignore:{actual}")
    for pointer in set_paths:
        segments = _pointer_segments(pointer)
        targets = [(None, None, result, "/")] if not segments else list(_walk_targets(result, segments))
        for parent, key, old, actual in targets:
            if not isinstance(old, list):
                raise ValueError(f"set path {actual} does not select a JSON array")
            ordered = sorted(old, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            if parent is None:
                result = ordered
            else:
                parent[key] = ordered
            applied.append(f"set:{actual}")
    return result, applied


def jsonapi_resource_id_paths(value: Any) -> tuple[str, ...]:
    """Return RFC 6901 paths for JSON:API resource IDs, not attribute IDs."""
    paths: list[str] = []

    def visit(item: Any, prefix: str) -> None:
        if isinstance(item, dict):
            if "type" in item and "id" in item:
                paths.append(f"{prefix}/id" or "/id")
            for key, child in item.items():
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                visit(child, f"{prefix}/{escaped}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{prefix}/{index}")

    visit(value, "")
    return tuple(paths)


STABLE_NUMERIC_ID_KEYS = frozenset(
    {
        "token_id",
        "node_id",
        "peer_id",
        "channel_id",
        "nft_class_id",
        "chain_id",
        "network_id",
    }
)


def local_numeric_id_paths(value: Any) -> tuple[str, ...]:
    """Return paths for deployment-local integer database identifiers.

    Explorer responses mix stable chain identities (hashes, block numbers,
    token IDs) with local relational keys.  Local keys are recognized by name
    and only normalized when their value is an integer or a decimal integer
    string.  Stable protocol identifiers remain strict.
    """
    paths: list[str] = []

    def numeric(item: Any) -> bool:
        return (isinstance(item, int) and not isinstance(item, bool)) or (
            isinstance(item, str) and item.isdecimal()
        )

    def visit(item: Any, prefix: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                name = str(key)
                escaped = name.replace("~", "~0").replace("/", "~1")
                path = f"{prefix}/{escaped}"
                if (
                    (name == "id" or name.endswith("_id"))
                    and name not in STABLE_NUMERIC_ID_KEYS
                    and numeric(child)
                ):
                    paths.append(path)
                visit(child, path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{prefix}/{index}")

    visit(value, "")
    return tuple(paths)


def _typed(value: Any) -> dict[str, Any]:
    return {"type": type(value).__name__, "value": value}


def _json_differences(baseline: Any, candidate: Any, path: str = "$") -> list[Difference]:
    differences: list[Difference] = []

    def visit(left: Any, right: Any, current: str) -> None:
        if len(differences) >= MAX_DIFFERENCES:
            return
        if type(left) is not type(right):
            differences.append(Difference("content", current, _typed(left), _typed(right), "JSON scalar/container type differs"))
            return
        if isinstance(left, dict):
            for key in sorted(set(left) | set(right)):
                child = f"{current}.{key}"
                if key not in left:
                    differences.append(Difference("content", child, "<missing>", _typed(right[key]), "key missing from baseline"))
                elif key not in right:
                    differences.append(Difference("content", child, _typed(left[key]), "<missing>", "key missing from candidate"))
                else:
                    visit(left[key], right[key], child)
        elif isinstance(left, list):
            if len(left) != len(right):
                differences.append(Difference("content", current, len(left), len(right), "array length differs"))
            for index, (left_item, right_item) in enumerate(zip(left, right)):
                visit(left_item, right_item, f"{current}[{index}]")
        elif left != right:
            differences.append(Difference("content", current, _typed(left), _typed(right), "JSON value differs"))

    visit(baseline, candidate, path)
    return differences


def _csv_differences(left_body: bytes, right_body: bytes) -> list[Difference]:
    try:
        left = list(csv.reader(io.StringIO(left_body.decode("utf-8-sig"), newline="")))
    except (UnicodeDecodeError, csv.Error) as error:
        return [Difference("decode", "baseline", type(error).__name__, None, str(error))]
    try:
        right = list(csv.reader(io.StringIO(right_body.decode("utf-8-sig"), newline="")))
    except (UnicodeDecodeError, csv.Error) as error:
        return [Difference("decode", "candidate", None, type(error).__name__, str(error))]
    differences: list[Difference] = []
    if len(left) != len(right):
        differences.append(Difference("content", "$csv", len(left), len(right), "CSV row count differs"))
    for row_index, (left_row, right_row) in enumerate(zip(left, right), start=1):
        if len(left_row) != len(right_row):
            differences.append(Difference("content", f"$csv[{row_index}]", len(left_row), len(right_row), "CSV column count differs"))
        for column_index, (left_cell, right_cell) in enumerate(zip(left_row, right_row), start=1):
            if left_cell != right_cell:
                differences.append(Difference("content", f"$csv[{row_index},{column_index}]", left_cell, right_cell, "CSV cell differs"))
                if len(differences) >= MAX_DIFFERENCES:
                    return differences
    return differences


def compare_observations(
    request_id: str,
    case: RequestCase,
    baseline: Observation,
    candidate: Observation,
) -> ComparisonResult:
    differences: list[Difference] = []
    normalizations: list[str] = []
    if not baseline.transport_ok or not candidate.transport_ok:
        if not baseline.transport_ok:
            differences.append(Difference("transport", "baseline", baseline.error_type, None, baseline.error or "transport failure"))
        if not candidate.transport_ok:
            differences.append(Difference("transport", "candidate", None, candidate.error_type, candidate.error or "transport failure"))
        return ComparisonResult(request_id, case.id, False, baseline, candidate, differences)
    if baseline.status != candidate.status:
        differences.append(Difference("status", "$status", baseline.status, candidate.status, "HTTP status differs"))
    for name in case.selected_headers:
        left = baseline.headers.get(name, _MISSING)
        right = candidate.headers.get(name, _MISSING)
        if left != right:
            differences.append(
                Difference(
                    "headers",
                    f"$headers.{name}",
                    "<missing>" if left is _MISSING else left,
                    "<missing>" if right is _MISSING else right,
                    "selected response header differs",
                )
            )
    mode = case.mode
    if mode == "auto":
        media = baseline.headers.get("content-type", "").lower()
        mode = "csv" if "csv" in media else "json" if "json" in media else "raw"
    if mode == "status":
        pass
    elif mode in ("json", "ordered", "set"):
        left_error: Exception | None = None
        right_error: Exception | None = None
        try:
            left_json = json.loads(baseline.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            left_error = error
            left_json = _MISSING
        try:
            right_json = json.loads(candidate.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            right_error = error
            right_json = _MISSING
        if left_error and right_error:
            if baseline.body != candidate.body:
                differences.append(
                    Difference(
                        "decode",
                        "$body",
                        baseline.body.decode("utf-8", errors="replace"),
                        candidate.body.decode("utf-8", errors="replace"),
                        "both JSON decodes failed and raw bodies differ",
                    )
                )
        elif left_error:
            differences.append(Difference("decode", "baseline", type(left_error).__name__, None, str(left_error)))
        elif right_error:
            differences.append(Difference("decode", "candidate", None, type(right_error).__name__, str(right_error)))
        else:
            set_paths = case.set_paths
            if mode == "set" and not set_paths:
                set_paths = ("/",)
            try:
                ignore_paths = case.ignore_paths
                if case.ignore_jsonapi_resource_ids:
                    ignore_paths = tuple(
                        dict.fromkeys(
                            ignore_paths
                            + jsonapi_resource_id_paths(left_json)
                            + jsonapi_resource_id_paths(right_json)
                        )
                    )
                if case.ignore_local_numeric_ids:
                    ignore_paths = tuple(
                        dict.fromkeys(
                            ignore_paths
                            + local_numeric_id_paths(left_json)
                            + local_numeric_id_paths(right_json)
                        )
                    )
                left_json, left_applied = normalize_json(left_json, ignore_paths=ignore_paths, set_paths=set_paths)
                right_json, right_applied = normalize_json(right_json, ignore_paths=ignore_paths, set_paths=set_paths)
                normalizations = sorted(set(left_applied + right_applied))
                differences.extend(_json_differences(left_json, right_json))
            except ValueError as error:
                differences.append(Difference("normalization", "$", None, None, str(error)))
    elif mode == "csv":
        differences.extend(_csv_differences(baseline.body, candidate.body))
    elif mode == "raw" and baseline.body != candidate.body:
        differences.append(Difference("content", "$raw", baseline.body.hex(), candidate.body.hex(), "raw response bytes differ"))
    else:
        if mode not in ("status", "json", "ordered", "set", "csv", "raw"):
            differences.append(Difference("configuration", "$mode", mode, None, "unsupported comparison mode"))
    differences = differences[:MAX_DIFFERENCES]
    return ComparisonResult(request_id, case.id, not differences, baseline, candidate, differences, normalizations)
