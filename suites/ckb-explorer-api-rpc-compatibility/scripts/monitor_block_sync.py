#!/usr/bin/env python3
"""Poll two CKB Explorer deployments and compare their tips with a CKB RPC."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_EXPLORER_A_URL = "https://testnet-api-ckba.explorer.nervos.org/api"
DEFAULT_EXPLORER_B_URL = "https://testnet-api.explorer.nervos.org/api"
DEFAULT_RPC_URL = "https://testnet.ckbapp.dev/"
V1_MEDIA_TYPE = "application/vnd.api+json"
USER_AGENT = "ckb-explorer-sync-monitor/1.0"


class MonitorError(RuntimeError):
    """A classified endpoint or response error."""


@dataclass
class RpcObservation:
    url: str
    height: int | None = None
    block_hash: str | None = None
    timestamp_ms: int | None = None
    latency_ms: float | None = None
    error: str | None = None


@dataclass
class ExplorerObservation:
    name: str
    url: str
    height: int | None = None
    block_hash: str | None = None
    timestamp_ms: int | None = None
    list_latency_ms: float | None = None
    detail_latency_ms: float | None = None
    lag_blocks: int | None = None
    hash_match: bool | None = None
    status: str = "ERROR"
    error: str | None = None


def endpoint_url(base_url: str, path: str, query: dict[str, str] | None = None) -> str:
    suffix = "" if not query else "?" + urlencode(query)
    return base_url.rstrip("/") + "/" + path.lstrip("/") + suffix


def decode_integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise MonitorError(f"{field} must be an integer, got boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 16 if value.lower().startswith("0x") else 10)
        except ValueError as error:
            raise MonitorError(f"{field} is not an integer: {value!r}") from error
    raise MonitorError(f"{field} is missing or has type {type(value).__name__}")


def request_json(
    url: str,
    *,
    timeout: float,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    v1: bool = False,
) -> Any:
    headers = {
        "Accept": V1_MEDIA_TYPE if v1 else "application/json",
        "User-Agent": USER_AGENT,
    }
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif v1:
        headers["Content-Type"] = V1_MEDIA_TYPE

    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as error:
        detail = error.read(512).decode("utf-8", errors="replace")
        raise MonitorError(f"HTTP {error.code} from {url}: {detail}") from error
    except URLError as error:
        raise MonitorError(f"transport error from {url}: {error.reason}") from error
    except TimeoutError as error:
        raise MonitorError(f"timeout after {timeout:g}s from {url}") from error

    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        sample = raw[:160].decode("utf-8", errors="replace")
        raise MonitorError(f"invalid JSON from {url}: {sample!r}") from error


def fetch_rpc_tip(rpc_url: str, timeout: float) -> RpcObservation:
    started = time.perf_counter()
    observation = RpcObservation(url=rpc_url)
    try:
        payload = request_json(
            rpc_url,
            timeout=timeout,
            method="POST",
            body={"id": 1, "jsonrpc": "2.0", "method": "get_tip_header", "params": []},
        )
        if not isinstance(payload, dict):
            raise MonitorError("RPC response is not an object")
        if payload.get("error") is not None:
            raise MonitorError(f"RPC get_tip_header error: {payload['error']!r}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise MonitorError("RPC get_tip_header result is missing")
        block_hash = result.get("hash")
        if not isinstance(block_hash, str) or not block_hash:
            raise MonitorError("RPC result.hash is missing")
        observation.height = decode_integer(result.get("number"), "RPC result.number")
        observation.timestamp_ms = decode_integer(result.get("timestamp"), "RPC result.timestamp")
        observation.block_hash = block_hash
    except Exception as error:  # Keep a long-running monitor alive on endpoint failures.
        observation.error = str(error)
    observation.latency_ms = round((time.perf_counter() - started) * 1000, 1)
    return observation


def fetch_explorer_tip(name: str, base_url: str, timeout: float) -> ExplorerObservation:
    started = time.perf_counter()
    observation = ExplorerObservation(name=name, url=base_url)
    url = endpoint_url(
        base_url,
        "/v1/blocks",
        {"page": "1", "page_size": "1", "sort": "number.desc"},
    )
    try:
        payload = request_json(url, timeout=timeout, v1=True)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            raise MonitorError("Explorer latest-block response has no data row")
        attributes = data[0].get("attributes") if isinstance(data[0], dict) else None
        if not isinstance(attributes, dict):
            raise MonitorError("Explorer latest-block attributes are missing")
        observation.height = decode_integer(attributes.get("number"), "Explorer block number")
        observation.timestamp_ms = decode_integer(
            attributes.get("timestamp"), "Explorer block timestamp"
        )
    except Exception as error:  # Keep the other endpoints observable when one fails.
        observation.error = str(error)
    observation.list_latency_ms = round((time.perf_counter() - started) * 1000, 1)
    return observation


def fetch_explorer_hash(observation: ExplorerObservation, timeout: float) -> None:
    if observation.height is None:
        return
    started = time.perf_counter()
    url = endpoint_url(observation.url, f"/v1/blocks/{observation.height}")
    try:
        payload = request_json(url, timeout=timeout, v1=True)
        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        block_hash = attributes.get("block_hash") if isinstance(attributes, dict) else None
        if not isinstance(block_hash, str) or not block_hash:
            raise MonitorError("Explorer block detail has no block_hash")
        observation.block_hash = block_hash
    except Exception as error:
        observation.error = str(error)
    observation.detail_latency_ms = round((time.perf_counter() - started) * 1000, 1)


def classify_explorer(
    explorer: ExplorerObservation,
    rpc: RpcObservation,
    *,
    max_lag: int,
    hash_check: bool,
) -> None:
    if explorer.error or rpc.error or explorer.height is None or rpc.height is None:
        explorer.status = "ERROR"
        return

    explorer.lag_blocks = rpc.height - explorer.height
    if explorer.lag_blocks < 0:
        explorer.status = "RPC_BEHIND"
    elif explorer.lag_blocks > max_lag:
        explorer.status = "LAGGING"
    elif explorer.lag_blocks > 0:
        explorer.status = "WITHIN_TOLERANCE"
    elif not hash_check:
        explorer.status = "SYNCED"
    elif explorer.block_hash is None:
        explorer.status = "ERROR"
        explorer.error = explorer.error or "Explorer block hash was not checked"
    else:
        explorer.hash_match = explorer.block_hash.lower() == (rpc.block_hash or "").lower()
        explorer.status = "SYNCED" if explorer.hash_match else "HASH_MISMATCH"


def overall_status(explorers: Sequence[ExplorerObservation], rpc: RpcObservation) -> str:
    statuses = {item.status for item in explorers}
    if rpc.error or "ERROR" in statuses:
        return "ERROR"
    if "HASH_MISMATCH" in statuses or "RPC_BEHIND" in statuses:
        return "DIVERGED"
    if "LAGGING" in statuses:
        return "LAGGING"
    if "WITHIN_TOLERANCE" in statuses:
        return "WITHIN_TOLERANCE"
    return "SYNCED"


def poll_once(args: argparse.Namespace) -> dict[str, Any]:
    poll_started_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
    explorers: list[ExplorerObservation]
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="block-tip") as executor:
        futures = {
            executor.submit(fetch_rpc_tip, args.rpc_url, args.timeout): "rpc",
            executor.submit(
                fetch_explorer_tip, args.explorer_a_name, args.explorer_a_url, args.timeout
            ): "explorer_a",
            executor.submit(
                fetch_explorer_tip, args.explorer_b_name, args.explorer_b_url, args.timeout
            ): "explorer_b",
        }
        observations: dict[str, Any] = {}
        for future in as_completed(futures):
            observations[futures[future]] = future.result()

    rpc: RpcObservation = observations["rpc"]
    explorers = [observations["explorer_a"], observations["explorer_b"]]

    if not args.skip_hash_check and rpc.error is None and rpc.height is not None:
        matching = [item for item in explorers if item.error is None and item.height == rpc.height]
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="block-hash") as executor:
            list(executor.map(lambda item: fetch_explorer_hash(item, args.timeout), matching))

    for explorer in explorers:
        classify_explorer(
            explorer,
            rpc,
            max_lag=args.max_lag,
            hash_check=not args.skip_hash_check,
        )

    height_gap = None
    if all(item.height is not None for item in explorers):
        height_gap = explorers[0].height - explorers[1].height

    return {
        "observed_at": poll_started_at,
        "overall_status": overall_status(explorers, rpc),
        "rpc": asdict(rpc),
        "explorers": [asdict(item) for item in explorers],
        "explorer_a_minus_b_blocks": height_gap,
    }


def format_human(result: dict[str, Any]) -> str:
    rpc = result["rpc"]
    heights = [rpc["height"], *(item["height"] for item in result["explorers"])]
    values = [
        result["observed_at"],
        *("ERROR" if height is None else str(height) for height in heights),
    ]
    return "|".join(values)


def format_errors(result: dict[str, Any]) -> list[str]:
    lines = []
    rpc = result["rpc"]
    if rpc["error"]:
        lines.append(f"ERROR rpc: {rpc['error']}")
    lines.extend(
        f"ERROR {explorer['name']}: {explorer['error']}"
        for explorer in result["explorers"]
        if explorer["error"]
    )
    return lines


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Poll two CKB Explorer latest-block APIs and compare them with a CKB RPC tip."
    )
    parser.add_argument(
        "--explorer-a-url",
        default=os.getenv("BASELINE_API_URL", DEFAULT_EXPLORER_A_URL),
        help=f"first Explorer API base URL (default: {DEFAULT_EXPLORER_A_URL})",
    )
    parser.add_argument(
        "--explorer-b-url",
        default=os.getenv("CANDIDATE_API_URL", DEFAULT_EXPLORER_B_URL),
        help=f"second Explorer API base URL (default: {DEFAULT_EXPLORER_B_URL})",
    )
    parser.add_argument("--explorer-a-name", default="ckba", help="first Explorer output label")
    parser.add_argument("--explorer-b-name", default="explorer", help="second Explorer output label")
    parser.add_argument(
        "--rpc-url",
        default=os.getenv("CKB_RPC_URL", DEFAULT_RPC_URL),
        help=f"CKB JSON-RPC URL (default: {DEFAULT_RPC_URL})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between poll starts (default: 5)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="per-request timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--max-lag",
        type=int,
        default=0,
        help="maximum tolerated Explorer lag in blocks (default: 0)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="number of polls; 0 means run until interrupted (default: 0)",
    )
    parser.add_argument("--once", action="store_true", help="perform one poll and exit")
    parser.add_argument(
        "--skip-hash-check",
        action="store_true",
        help="compare heights only and skip same-height Explorer detail requests",
    )
    parser.add_argument("--json", action="store_true", help="print one compact JSON object per poll")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.max_lag < 0:
        parser.error("--max-lag must be zero or greater")
    if args.count < 0:
        parser.error("--count must be zero or greater")
    if args.once:
        args.count = 1
    return args


def result_exit_code(result: dict[str, Any]) -> int:
    if result["overall_status"] == "ERROR":
        return 2
    if result["overall_status"] in {"LAGGING", "DIVERGED"}:
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    polls = 0
    exit_code = 0
    next_poll = time.monotonic()
    if not args.json:
        print(f"time|rpc|{args.explorer_a_name}|{args.explorer_b_name}", flush=True)
    try:
        while args.count == 0 or polls < args.count:
            if polls:
                time.sleep(max(0.0, next_poll - time.monotonic()))
            started = time.monotonic()
            result = poll_once(args)
            print(
                json.dumps(result, ensure_ascii=False, separators=(",", ":"))
                if args.json
                else format_human(result),
                flush=True,
            )
            if not args.json:
                for message in format_errors(result):
                    print(message, file=sys.stderr, flush=True)
            exit_code = max(exit_code, result_exit_code(result))
            polls += 1
            next_poll = max(next_poll + args.interval, started + args.interval)
    except KeyboardInterrupt:
        print("\nmonitor stopped", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
