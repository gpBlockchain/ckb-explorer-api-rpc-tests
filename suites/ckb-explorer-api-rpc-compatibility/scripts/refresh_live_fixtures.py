#!/usr/bin/env python3
"""Discover stable read fixtures from CKB RPC and both Explorer deployments.

The script only calls read-only RPC methods and HTTP GET endpoints.  It prints
the proposed fixture changes by default; ``--write`` atomically updates the
selected fixture file after every discovered identifier has been observed in
both Explorer environments.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SUITE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUITE_ROOT / "src"))

from ckb_api_compat.settings import DEFAULT_SETTINGS_FILE, load_settings  # noqa: E402


USER_AGENT = "ckb-api-compat-fixture-discovery/0.1.0"
V1_ACCEPT = "application/vnd.api+json"
READ_TX_CASES = (
    "API-006",
    "API-015",
    "API-016",
    "API-017",
    "API-018",
    "API-022",
    "API-023",
    "API-027",
    "API-028",
    "API-037",
    "API-069",
)
ADDRESS_CASES = (
    "API-033",
    "API-034",
    "API-035",
    "API-040",
    "API-041",
    "API-042",
    "API-062",
)


def http_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    accept: str = "application/json",
    content_type: str | None = None,
    timeout: float = 60,
) -> tuple[int, Any]:
    payload = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    headers = {"Accept": accept, "User-Agent": USER_AGENT}
    if payload is not None or content_type is not None:
        headers["Content-Type"] = content_type or "application/json"
    request = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except HTTPError as error:
        raw = error.read()
        status = error.code
    try:
        decoded = json.loads(raw) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        decoded = raw.decode("utf-8", errors="replace")
    return status, decoded


def api_get(base_url: str, path: str, query: dict[str, Any] | None = None) -> tuple[int, Any]:
    suffix = "" if not query else "?" + urlencode(query)
    accept = V1_ACCEPT if path.startswith("/v1/") else "application/json"
    return http_json(
        base_url.rstrip("/") + path + suffix,
        accept=accept,
        content_type=V1_ACCEPT if path.startswith("/v1/") else None,
    )


def require_200(label: str, response: tuple[int, Any]) -> Any:
    status, payload = response
    if status != 200:
        raise RuntimeError(f"{label} returned HTTP {status}: {payload!r}")
    return payload


def rpc_call(rpc_url: str, method: str, params: list[Any]) -> Any:
    status, payload = http_json(
        rpc_url,
        method="POST",
        body={"id": 1, "jsonrpc": "2.0", "method": method, "params": params},
    )
    if status != 200 or not isinstance(payload, dict) or payload.get("error"):
        raise RuntimeError(f"RPC {method} failed with HTTP {status}: {payload!r}")
    return payload.get("result")


def case(fixtures: dict[str, Any], case_id: str) -> dict[str, Any]:
    return fixtures.setdefault("cases", {}).setdefault(case_id, {})


def path_value(fixtures: dict[str, Any], case_id: str, name: str = "id") -> Any:
    return case(fixtures, case_id).get("path_params", {}).get(name)


def set_path(fixtures: dict[str, Any], case_id: str, **values: Any) -> None:
    case(fixtures, case_id)["path_params"] = values


def set_side_paths(
    fixtures: dict[str, Any],
    case_id: str,
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    entry = case(fixtures, case_id)
    entry.pop("path_params", None)
    entry["baseline_path_params"] = baseline
    entry["candidate_path_params"] = candidate


def tx_attributes(payload: Any, label: str) -> dict[str, Any]:
    try:
        attributes = payload["data"]["attributes"]
    except (KeyError, TypeError) as error:
        raise RuntimeError(f"{label} transaction response has no JSON:API attributes") from error
    if not isinstance(attributes, dict):
        raise RuntimeError(f"{label} transaction attributes are not an object")
    return attributes


def matching_display_output(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[Any, Any]:
        return item.get("generated_tx_hash"), item.get("cell_index")

    baseline_outputs = baseline.get("display_outputs") or []
    candidate_by_key = {key(item): item for item in candidate.get("display_outputs") or []}
    for output in baseline_outputs:
        other = candidate_by_key.get(key(output))
        if other and output.get("id") is not None and other.get("id") is not None:
            return output, other
    raise RuntimeError("no shared transaction output with side-local IDs was found")


def common_fiber_node(settings: Any) -> str:
    query = {"page": 1, "page_size": 100}
    baseline = require_200(
        "baseline Fiber graph channels",
        api_get(settings.baseline_url, "/v2/fiber/graph_channels", query),
    )
    candidate = require_200(
        "candidate Fiber graph channels",
        api_get(settings.candidate_url, "/v2/fiber/graph_channels", query),
    )
    try:
        baseline_channels = baseline["data"]["fiber_graph_channels"]
        candidate_channels = candidate["data"]["fiber_graph_channels"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("Fiber graph channel response has an unexpected shape") from error
    candidate_outpoints = {item.get("channel_outpoint") for item in candidate_channels}
    nodes: list[str] = []
    for channel in baseline_channels:
        if channel.get("channel_outpoint") not in candidate_outpoints:
            continue
        nodes.extend(str(channel[name]) for name in ("node1", "node2") if channel.get(name))
    for node_id in dict.fromkeys(nodes):
        paths = (
            f"/v2/fiber/graph_nodes/{node_id}",
            f"/v2/fiber/graph_nodes/{node_id}/graph_channels",
            f"/v2/fiber/graph_nodes/{node_id}/transactions",
        )
        if all(
            api_get(base, path, query if path != paths[0] else None)[0] == 200
            for base in (settings.baseline_url, settings.candidate_url)
            for path in paths
        ):
            return node_id
    raise RuntimeError("no shared Fiber node returned HTTP 200 for detail, channels, and transactions")


def discover(settings: Any, fixtures: dict[str, Any]) -> dict[str, Any]:
    block_number = int(str(path_value(fixtures, "API-003")))
    block = rpc_call(settings.fixture_rpc_url, "get_block_by_number", [hex(block_number)])
    if not isinstance(block, dict):
        raise RuntimeError(f"RPC has no block at configured height {block_number}")
    block_hash = block.get("header", {}).get("hash")
    configured_tx = str(path_value(fixtures, "API-006"))
    rpc_transaction = rpc_call(settings.fixture_rpc_url, "get_transaction", [configured_tx])
    tx_hash = (
        rpc_transaction.get("transaction", {}).get("hash")
        if isinstance(rpc_transaction, dict)
        else None
    )
    if not block_hash or tx_hash != configured_tx:
        raise RuntimeError("configured RPC block or transaction is not available")

    baseline_payload = require_200(
        "baseline transaction detail",
        api_get(settings.baseline_url, f"/v1/transactions/{tx_hash}"),
    )
    candidate_payload = require_200(
        "candidate transaction detail",
        api_get(settings.candidate_url, f"/v1/transactions/{tx_hash}"),
    )
    baseline_tx = tx_attributes(baseline_payload, "baseline")
    candidate_tx = tx_attributes(candidate_payload, "candidate")
    baseline_output, candidate_output = matching_display_output(baseline_tx, candidate_tx)
    if baseline_tx.get("transaction_hash") != candidate_tx.get("transaction_hash"):
        raise RuntimeError("Explorer deployments returned different business transactions")
    address = baseline_output.get("address_hash")
    if not address or address != candidate_output.get("address_hash"):
        raise RuntimeError("shared output address differs between Explorer deployments")

    set_path(fixtures, "API-003", id=str(block_number))
    set_path(fixtures, "API-004", id=block_hash)
    for case_id in READ_TX_CASES:
        set_path(fixtures, case_id, id=tx_hash)
    for case_id in ADDRESS_CASES:
        existing = case(fixtures, case_id).get("path_params", {})
        set_path(fixtures, case_id, **{**existing, "id": address})
    for case_id in ("API-011", "API-012", "API-013"):
        set_side_paths(
            fixtures,
            case_id,
            baseline={"id": str(baseline_output["id"])},
            candidate={"id": str(candidate_output["id"])},
        )

    fiber_node_id = common_fiber_node(settings)
    for case_id in ("API-148", "API-149", "API-150"):
        set_path(fixtures, case_id, node_id=fiber_node_id)
    case(fixtures, "API-106").setdefault("headers", {})["Accept"] = "application/json"

    return {
        "rpc_block_number": block_number,
        "rpc_block_hash": block_hash,
        "transaction_hash": tx_hash,
        "address": address,
        "baseline_cell_output_id": str(baseline_output["id"]),
        "candidate_cell_output_id": str(candidate_output["id"]),
        "fiber_node_id": fiber_node_id,
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", delete=False
    ) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_FILE))
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--rpc")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    settings = load_settings(args.settings)
    if args.rpc:
        object.__setattr__(settings, "fixture_rpc_url", args.rpc.rstrip("/"))
    fixture_path = (args.fixtures or settings.fixtures_file).expanduser().resolve()
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    before = json.dumps(fixtures, ensure_ascii=False, sort_keys=True)
    discovered = discover(settings, fixtures)
    changed = before != json.dumps(fixtures, ensure_ascii=False, sort_keys=True)
    if args.write:
        atomic_write(fixture_path, fixtures)
    print(
        json.dumps(
            {
                "fixture_file": str(fixture_path),
                "mode": "write" if args.write else "dry-run",
                "changed": changed,
                "discovered": discovered,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
