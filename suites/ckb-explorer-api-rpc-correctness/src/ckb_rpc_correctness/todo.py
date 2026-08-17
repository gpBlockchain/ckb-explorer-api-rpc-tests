from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SUITE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = SUITE_ROOT.parent / "ckb-explorer-api-rpc-compatibility" / "config" / "endpoints.json"
DEFAULT_REVIEWS = SUITE_ROOT / "reviews"
REVIEW_MARKER = re.compile(r"^评审接口：\s*`(?P<method>[A-Z]+)\s+(?P<path>/api/[^`\s]+)`\s*$")

MODULE_LABELS = {
    "MOD-CHAIN-DATA": "Chain Data",
    "MOD-ADDRESS-DAO": "Address / DAO",
    "MOD-TOKENS": "Token / UDT",
    "MOD-NFT-RGB": "NFT / RGB / Bitcoin",
    "MOD-CONTRACT-SCRIPT": "Contract / Script",
    "MOD-STATISTICS-DISCOVERY": "Statistics / Discovery",
    "MOD-PORTFOLIO": "Portfolio",
    "MOD-FIBER": "Fiber",
}


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    module: str
    purpose: str
    wiring: str

    @property
    def key(self) -> tuple[str, str]:
        return self.method, self.path

    @property
    def api_path(self) -> str:
        return "/api" + self.path


@dataclass(frozen=True)
class TodoInventory:
    reviewed: tuple[Endpoint, ...]
    active: tuple[Endpoint, ...]
    route_audit: tuple[Endpoint, ...]

    @property
    def total(self) -> int:
        return len(self.reviewed) + len(self.active) + len(self.route_audit)


def load_endpoints(manifest_path: Path) -> tuple[Endpoint, ...]:
    payload = json.loads(manifest_path.read_text())
    records = payload.get("endpoints") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise ValueError(f"endpoint manifest has no endpoints list: {manifest_path}")

    endpoints: list[Endpoint] = []
    seen: set[tuple[str, str]] = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"endpoint record {index} is not an object")
        endpoint = Endpoint(
            method=str(record.get("method", "")).upper(),
            path=str(record.get("path", "")),
            module=str(record.get("module", "UNCLASSIFIED")),
            purpose=str(record.get("purpose", "")),
            wiring=str(record.get("wiring", "ACTIVE")),
        )
        if not endpoint.method or not endpoint.path.startswith("/"):
            raise ValueError(f"endpoint record {index} has an invalid method or path")
        if endpoint.key in seen:
            raise ValueError(f"duplicate endpoint in manifest: {endpoint.method} {endpoint.path}")
        seen.add(endpoint.key)
        endpoints.append(endpoint)
    return tuple(endpoints)


def discover_reviewed_interfaces(review_root: Path) -> set[tuple[str, str]]:
    reviewed: set[tuple[str, str]] = set()
    for path in sorted(review_root.rglob("*.md")):
        for line in path.read_text().splitlines():
            match = REVIEW_MARKER.fullmatch(line.strip())
            if not match:
                continue
            api_path = match.group("path")
            manifest_path = api_path.removeprefix("/api")
            key = match.group("method"), manifest_path
            if key in reviewed:
                raise ValueError(f"duplicate reviewed interface marker: {key[0]} {api_path}")
            reviewed.add(key)
    return reviewed


def build_inventory(endpoints: Sequence[Endpoint], reviewed_keys: set[tuple[str, str]]) -> TodoInventory:
    endpoint_keys = {endpoint.key for endpoint in endpoints}
    unknown = sorted(reviewed_keys - endpoint_keys)
    if unknown:
        formatted = ", ".join(f"{method} /api{path}" for method, path in unknown)
        raise ValueError(f"review markers reference endpoints absent from the manifest: {formatted}")

    reviewed: list[Endpoint] = []
    active: list[Endpoint] = []
    route_audit: list[Endpoint] = []
    for endpoint in endpoints:
        if endpoint.key in reviewed_keys:
            reviewed.append(endpoint)
        elif endpoint.wiring == "ACTIVE":
            active.append(endpoint)
        else:
            route_audit.append(endpoint)
    return TodoInventory(tuple(reviewed), tuple(active), tuple(route_audit))


def _group_by_module(endpoints: Iterable[Endpoint]) -> dict[str, list[Endpoint]]:
    groups: dict[str, list[Endpoint]] = defaultdict(list)
    for endpoint in endpoints:
        groups[endpoint.module].append(endpoint)
    return dict(groups)


def _render_groups(lines: list[str], endpoints: Iterable[Endpoint], *, checked: bool) -> None:
    marker = "x" if checked else " "
    for module, items in _group_by_module(endpoints).items():
        label = MODULE_LABELS.get(module, module)
        lines.extend((f"### {label}（{len(items)}）", ""))
        for endpoint in items:
            suffix = f" [{endpoint.wiring}]" if endpoint.wiring != "ACTIVE" else ""
            lines.append(
                f"- [{marker}] `{endpoint.method} {endpoint.api_path}` — {endpoint.purpose}{suffix}"
            )
        lines.append("")


def render_markdown(inventory: TodoInventory, manifest_path: Path) -> str:
    lines = [
        "# CKB Explorer API RPC 正确性 TODO",
        "",
        f"路由来源：`{manifest_path}`",
        "",
        f"- 路由总数：{inventory.total}",
        f"- 已建立评审文档：{len(inventory.reviewed)}",
        f"- 可进入 Gate 2 的 ACTIVE 接口：{len(inventory.active)}",
        f"- 需要路由审计：{len(inventory.route_audit)}",
        "",
        "## 已建立评审文档",
        "",
    ]
    _render_groups(lines, inventory.reviewed, checked=True)
    lines.extend(("## 可进入 Gate 2", ""))
    _render_groups(lines, inventory.active, checked=False)
    lines.extend(("## 需要路由审计", ""))
    _render_groups(lines, inventory.route_audit, checked=False)
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List API correctness review TODOs from route and review sources")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    endpoints = load_endpoints(args.manifest.resolve())
    reviewed = discover_reviewed_interfaces(args.reviews.resolve())
    inventory = build_inventory(endpoints, reviewed)
    print(render_markdown(inventory, args.manifest.resolve()), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
