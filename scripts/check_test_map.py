#!/usr/bin/env python3
"""Report TEST-MAP coverage and validate review scenario checkboxes."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


CASE_TOKEN = r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{2,}"
REVIEW_ROW = re.compile(
    rf"^\|\s*`?(?P<case>{CASE_TOKEN})`?\s*\|\s*(?P<scenario>[^|]*)\|"
)
TASK_CHECKBOX = re.compile(r"^- \[(?P<state>[ xX])\](?:\s+|$)")
TEST_MAP = re.compile(rf"\bTEST-MAP:\s*(?P<case>{CASE_TOKEN})\b")
CODE_DIR_NAMES = {"tests", "benchmarks", "targets"}
CODE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".swift",
    ".ts",
    ".tsx",
}
SKIP_DIRS = {".git", ".idea", ".pytest_cache", ".venv", "node_modules", "source", "__pycache__"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute TEST-MAP coverage and validate review scenario checkboxes."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Test-project root (default: current directory)",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit non-zero when any review case has no TEST-MAP comment",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON report",
    )
    return parser.parse_args()


def is_skipped(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in SKIP_DIRS for part in relative.parts)


def location(path: Path, line: int, root: Path) -> str:
    return f"{path.relative_to(root).as_posix()}:{line}"


def review_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.md"):
        if is_skipped(path, root) or path.name.lower() == "readme.md":
            continue
        if "reviews" in path.relative_to(root).parts:
            files.append(path)
    return sorted(files)


def code_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    for directory in root.rglob("*"):
        if not directory.is_dir() or directory.name not in CODE_DIR_NAMES:
            continue
        if is_skipped(directory, root):
            continue
        for path in directory.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in CODE_SUFFIXES
                and not is_skipped(path, root)
            ):
                files.add(path)
    return sorted(files)


def collect_review_cases(
    root: Path,
) -> tuple[dict[str, list[str]], dict[str, list[dict[str, object]]]]:
    found: dict[str, list[str]] = defaultdict(list)
    checkboxes: dict[str, list[dict[str, object]]] = defaultdict(list)
    for path in review_files(root):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = REVIEW_ROW.match(line)
            if not match:
                continue
            case = match.group("case")
            place = location(path, number, root)
            checkbox = TASK_CHECKBOX.match(match.group("scenario").strip())
            checked = None if checkbox is None else checkbox.group("state").lower() == "x"
            found[case].append(place)
            checkboxes[case].append({"location": place, "checked": checked})
    return dict(found), dict(checkboxes)


def collect_test_maps(root: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = defaultdict(list)
    for path in code_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, start=1):
            for match in TEST_MAP.finditer(line):
                found[match.group("case")].append(location(path, number, root))
    return dict(found)


def build_report(root: Path) -> dict[str, object]:
    reviews, checkboxes = collect_review_cases(root)
    mappings = collect_test_maps(root)
    review_ids = set(reviews)
    mapped_ids = set(mappings)
    automated = sorted(review_ids & mapped_ids)
    unautomated = sorted(review_ids - mapped_ids)
    orphan = sorted(mapped_ids - review_ids)
    duplicate_reviews = {
        case: places for case, places in sorted(reviews.items()) if len(places) > 1
    }
    multiple_mappings = {
        case: places for case, places in sorted(mappings.items()) if len(places) > 1
    }
    checkbox_mismatches: dict[str, list[dict[str, object]]] = {}
    for case in sorted(review_ids):
        expected = case in mapped_ids
        mismatches = []
        for entry in checkboxes[case]:
            if entry["checked"] != expected:
                mismatches.append(
                    {
                        "location": entry["location"],
                        "expected_checked": expected,
                        "observed_checked": entry["checked"],
                    }
                )
        if mismatches:
            checkbox_mismatches[case] = mismatches
    return {
        "root": str(root),
        "review_case_count": len(review_ids),
        "automated_case_count": len(automated),
        "automation_coverage": f"{len(automated)}/{len(review_ids)}",
        "automated": automated,
        "unautomated": unautomated,
        "orphan_mappings": orphan,
        "duplicate_review_ids": duplicate_reviews,
        "multiple_code_mappings": multiple_mappings,
        "checkbox_mismatches": checkbox_mismatches,
        "review_locations": reviews,
        "mapping_locations": mappings,
    }


def print_human(report: dict[str, object]) -> None:
    print(f"review cases: {report['review_case_count']}")
    print(f"automated cases: {report['automated_case_count']}")
    print(f"automation coverage: {report['automation_coverage']}")
    unautomated = report["unautomated"]
    orphan = report["orphan_mappings"]
    duplicate = report["duplicate_review_ids"]
    multiple = report["multiple_code_mappings"]
    checkbox_mismatches = report["checkbox_mismatches"]
    print(f"unautomated: {', '.join(unautomated) if unautomated else 'none'}")
    print(f"orphan mappings: {', '.join(orphan) if orphan else 'none'}")
    print(f"duplicate review IDs: {', '.join(duplicate) if duplicate else 'none'}")
    print(f"cases with multiple code mappings: {', '.join(multiple) if multiple else 'none'}")
    if checkbox_mismatches:
        details = []
        for case, entries in checkbox_mismatches.items():
            for entry in entries:
                expected = "checked" if entry["expected_checked"] else "unchecked"
                observed_value = entry["observed_checked"]
                observed = (
                    "missing"
                    if observed_value is None
                    else ("checked" if observed_value else "unchecked")
                )
                details.append(
                    f"{case} ({entry['location']}: expected {expected}, found {observed})"
                )
        print(f"checkbox mismatches: {', '.join(details)}")
    else:
        print("checkbox mismatches: none")


def main() -> int:
    args = parse_args()
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"test-project root is not a directory: {root}")
    report = build_report(root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_human(report)
    invalid = bool(
        report["orphan_mappings"]
        or report["duplicate_review_ids"]
        or report["checkbox_mismatches"]
    )
    incomplete = bool(args.require_complete and report["unautomated"])
    return 1 if invalid or incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
