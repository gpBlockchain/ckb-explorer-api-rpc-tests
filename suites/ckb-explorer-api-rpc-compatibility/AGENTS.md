# CKB Explorer API RPC Compatibility Suite Instructions

Inherit repository-wide rules from `../../AGENTS.md`. This file contains only compatibility-suite rules.

## Scope and Layout

- Compare the same deterministic HTTP request against the configured baseline and candidate environments.
- Reviewer-facing cases live in `reviews/`; `../../reviews/README.md` defines the product-area boundaries.
- Executable tests live in `tests/`; runner code lives in `src/ckb_api_compat/`.
- Keep exactly one generated file per `API-*` inventory entry under `tests/endpoints/`. Shared transport and comparison behavior belongs in support modules.
- `config/endpoints.json` is the executable 153-route inventory, not a reviewer-facing case ledger.
- Read `skills/compatibility-test/SKILL.md` before changing this suite.

## Workflow

1. Read the affected review document and inspect target source behavior, failures, dependencies, limits, existing tests, and observables.
2. Add or revise self-contained rows while preserving existing case IDs and priorities unless behavior or impact changed.
3. Present every new, deleted, or materially changed row and stop before editing mapped tests.
4. After explicit human confirmation, synchronize tests with exact nearby `TEST-MAP: <CASE-ID>` comments.
5. After inventory changes, regenerate endpoint files and run `python3 scripts/generate_endpoint_tests.py --check`.
6. Run the narrowest relevant tests and then `python3 ../../scripts/check_test_map.py --root ../..`.

Keep configuration and stable commands in `README.md`. Do not create mapping ledgers, coverage-status documents, review histories, or run archives.
