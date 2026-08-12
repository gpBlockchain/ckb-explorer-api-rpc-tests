#!/usr/bin/env python3
"""Generate the executable endpoint manifest from the confirmed Markdown inventory."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


SECTION = re.compile(r"^### `(MOD-[A-Z-]+)` .*\((\d+)\)$")
ROW = re.compile(
    r"^\| `(GET|POST|PATCH|PUT|DELETE)` \| `([^`]+)` \| `([^`]+)` \| ([^|]+?) \| `(ACTIVE|ROUTE_ONLY|NAMESPACE_MISMATCH)` \|$"
)
EXPECTED_STATUS = {"ACTIVE": 124, "ROUTE_ONLY": 22, "NAMESPACE_MISMATCH": 7}


def parse_inventory(path: Path) -> list[dict]:
    current_module: str | None = None
    declared: dict[str, int] = {}
    endpoints: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        section = SECTION.match(line)
        if section:
            current_module = section.group(1)
            declared[current_module] = int(section.group(2))
            continue
        row = ROW.match(line)
        if not row:
            continue
        if current_module is None:
            raise ValueError("inventory row appears outside a MOD section")
        method, source_path, action, purpose, wiring = row.groups()
        if not source_path.startswith("/api/"):
            raise ValueError(f"unexpected source path: {source_path}")
        endpoints.append(
            {
                "id": f"API-{len(endpoints) + 1:03d}",
                "module": current_module,
                "method": method,
                "path": source_path.removeprefix("/api"),
                "source_path": source_path,
                "controller_action": action,
                "purpose": purpose.strip(),
                "wiring": wiring,
                "mode": "csv" if "download_csv" in source_path else "auto",
            }
        )
    keys = [(item["method"], item["source_path"]) for item in endpoints]
    if len(endpoints) != 153 or len(set(keys)) != 153:
        raise ValueError(f"expected 153 unique method/path rows, found {len(endpoints)}/{len(set(keys))}")
    actual_status = Counter(item["wiring"] for item in endpoints)
    if dict(actual_status) != EXPECTED_STATUS:
        raise ValueError(f"wiring counts drifted: {dict(actual_status)}")
    actual_modules = Counter(item["module"] for item in endpoints)
    if dict(actual_modules) != declared:
        raise ValueError(f"declared module counts {declared} differ from rows {dict(actual_modules)}")
    return endpoints


def main() -> int:
    script = Path(__file__).resolve()
    suite = script.parents[1]
    project = suite.parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=project / "docs" / "test-modules.md")
    parser.add_argument("--output", type=Path, default=suite / "config" / "endpoints.json")
    args = parser.parse_args()
    endpoints = parse_inventory(args.inventory)
    payload = {
        "schema_version": 1,
        "source": "docs/test-modules.md",
        "source_revision": "0495ecd00a839f7618bad752f5ad92071124a991",
        "base_path_contract": "base URLs include /api; endpoint paths begin with /v1 or /v2",
        "endpoints": endpoints,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated {len(endpoints)} endpoints -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
