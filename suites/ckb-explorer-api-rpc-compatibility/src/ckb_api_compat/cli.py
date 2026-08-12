from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .http import StdlibHttpClient
from .manifest import build_cases, filter_cases, load_endpoint_specs, load_fixture_config
from .report import report_payload, write_report
from .runner import PairedRunner
from .settings import DEFAULT_SETTINGS_FILE, load_settings


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Compare two CKB Explorer API deployments")
    result.add_argument("--settings", default=str(DEFAULT_SETTINGS_FILE))
    result.add_argument("--manifest")
    result.add_argument("--fixtures")
    result.add_argument("--baseline")
    result.add_argument("--candidate")
    result.add_argument("--case", action="append", dest="case_ids")
    result.add_argument("--module", action="append", dest="modules")
    result.add_argument("--timeout", type=float)
    result.add_argument("--retries", type=int)
    result.add_argument("--max-body-bytes", type=int)
    result.add_argument("--max-report-body-chars", type=int)
    result.add_argument("--include-known-defects", action=argparse.BooleanOptionalAction, default=None)
    result.add_argument("--allow-mutations", action=argparse.BooleanOptionalAction, default=None)
    result.add_argument("--run-exports", action=argparse.BooleanOptionalAction, default=None)
    result.add_argument("--strict-fixtures", action=argparse.BooleanOptionalAction, default=None)
    result.add_argument("--fail-fast", action=argparse.BooleanOptionalAction, default=None)
    result.add_argument("--print-responses", action=argparse.BooleanOptionalAction, default=None)
    result.add_argument("--list", action="store_true", dest="list_only")
    result.add_argument("--report")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        settings = load_settings(args.settings)
        manifest_file = Path(args.manifest).expanduser().resolve() if args.manifest else settings.manifest_file
        fixtures_file = Path(args.fixtures).expanduser().resolve() if args.fixtures else settings.fixtures_file
        baseline = args.baseline or settings.baseline_url
        candidate = args.candidate or settings.candidate_url
        timeout = args.timeout if args.timeout is not None else settings.timeout_seconds
        retries = args.retries if args.retries is not None else settings.transport_retries
        max_body_bytes = args.max_body_bytes if args.max_body_bytes is not None else settings.max_body_bytes
        max_report_body_chars = (
            args.max_report_body_chars
            if args.max_report_body_chars is not None
            else settings.max_report_body_chars
        )
        include_known_defects = (
            args.include_known_defects
            if args.include_known_defects is not None
            else settings.include_known_defects
        )
        allow_mutations = args.allow_mutations if args.allow_mutations is not None else settings.allow_mutations
        run_exports = args.run_exports if args.run_exports is not None else settings.run_exports
        strict_fixtures = args.strict_fixtures if args.strict_fixtures is not None else settings.strict_fixtures
        fail_fast = args.fail_fast if args.fail_fast is not None else settings.fail_fast
        print_responses = (
            args.print_responses if args.print_responses is not None else settings.print_responses
        )
        report_file = Path(args.report).expanduser().resolve() if args.report else settings.report_file
        endpoints = load_endpoint_specs(manifest_file)
        fixtures = load_fixture_config(fixtures_file)
        cases = build_cases(
            endpoints,
            fixtures,
            allow_mutations=allow_mutations,
            include_known_defects=include_known_defects,
            enable_csv_exports=run_exports,
            default_timeout=timeout,
            default_retries=retries,
        )
        cases = filter_cases(
            cases,
            ids=set(args.case_ids) if args.case_ids else None,
            modules=set(args.modules) if args.modules else None,
        )
        if args.list_only:
            for case in cases:
                state = "RUN" if case.enabled else f"SKIP ({case.skip_reason})"
                print(f"{case.id}\t{case.module}\t{case.method}\t{case.path}\t{case.wiring}\t{state}")
            return 0
        runner = PairedRunner(
            baseline,
            candidate,
            client=StdlibHttpClient(max_body_bytes=max_body_bytes),
        )
        results = runner.run(cases, fail_fast=fail_fast)
        payload = report_payload(results, max_body_chars=max_report_body_chars)
        print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))
        for result in payload["results"]:
            if print_responses and not result["skipped"]:
                print(
                    json.dumps(
                        {"event": "api_response", **result},
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
            if result["skipped"]:
                print(f"SKIP {result['case_id']}: {result['skip_reason']}")
            elif not result["matched"]:
                print(f"FAIL {result['case_id']}")
                for diff in result["differences"][:20]:
                    print(f"  {diff['phase']} {diff['path']}: {diff['detail']}")
            else:
                print(f"PASS {result['case_id']}")
        write_report(report_file, payload)
        if payload["summary"]["mismatched"]:
            return 1
        if strict_fixtures and payload["summary"]["skipped"]:
            return 2
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"configuration error: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
