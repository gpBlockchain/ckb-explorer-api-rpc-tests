# CKB Explorer API RPC Compatibility Tests

This suite sends the same deterministic request to a baseline and candidate deployment and reports externally observable compatibility differences.

## Declared Environments

- Baseline: `https://testnet-api-ckba.explorer.nervos.org/api`
- Candidate: `https://testnet-api.explorer.nervos.org/api`
- Fixture RPC: `https://testnet.ckbapp.dev/`

The defaults include the common `/api` prefix; cases use paths beginning with `/v1` or `/v2`. `BASELINE_API_URL` and `CANDIDATE_API_URL` may override them.

## Layout

- `reviews/`: concise reviewer-facing behavior cases.
- `tests/endpoints/`: one generated test file for each of the 153 `API-*` inventory entries.
- `tests/contract/`: cross-endpoint HTTP contract checks.
- `src/ckb_api_compat/`: paired HTTP runner, strict comparator, redaction, reporting, and CLI.
- `config/endpoints.json`: executable route inventory.
- `config/settings.json` and `config/fixtures.example.json`: runtime defaults and deterministic request fixtures.
- `scripts/`: inventory, generated-test, and live-fixture maintenance.
- `skills/compatibility-test/`: suite-specific review and comparison rules.

Review rows are the source of human-approved intent. Their scenario checkboxes show whether exact nearby `TEST-MAP: <CASE-ID>` comments exist; mapping coverage and checkbox consistency are computed by the root checker.

## Default Configuration

The suite reads `config/settings.json` automatically. `RUN_LIVE_COMPAT`,
`RUN_LIVE_KNOWN_DEFECTS`, `RUN_LIVE_MUTATIONS`, and `COMPAT_FIXTURES` are
optional overrides rather than required configuration.

The read-only fixture RPC also has a checked-in `fixture_rpc_url` default. Use
`CKB_RPC_URL` only when temporarily selecting another RPC endpoint.

The checked-in defaults select the two declared URLs and
`config/fixtures.example.json`, enable live comparison, known-defect routes,
bounded CSV exports, and explicitly gated write-method probes, print both
response objects, enforce strict fixture completeness, and write the CLI
report to `/tmp/ckb-api-compat-report.json`. Running `--list` with no environment
variables produces exactly `153 RUN` and `0 SKIP`.

Mutation execution has two gates: global `allow_mutations` and an explicit
`allow_mutation: true` on the individual endpoint case. Both gates have
checked-in defaults. Create/update routes use route-only, nonexistent-resource,
invalid-signature, missing-JWT, or connection-failure fixtures so the HTTP
request executes without a successful state transition.

A different settings file can be selected with `--settings PATH` or
`CKB_COMPAT_SETTINGS`. Environment variables and CLI flags may temporarily
override individual values.

`print_responses: true` prints a structured `api_response` JSON object for
every executed case, including both environments' URL, status, headers, body,
hash, byte count, elapsed time, transport phase, and attempts. Sensitive
headers and JSON fields are redacted. Use `--no-print-responses` or
`PRINT_RESPONSES=false` for summary-only output.

## Stable Commands

No runtime dependency is required beyond Python 3.11 or newer.

```bash
# Setup/check the checked-in endpoint manifest.
python3 scripts/generate_endpoints.py
python3 scripts/generate_endpoint_tests.py
python3 scripts/generate_endpoint_tests.py --check

# Discover/validate real read fixtures through the configured RPC and both APIs.
python3 scripts/refresh_live_fixtures.py
python3 scripts/refresh_live_fixtures.py --write

# Poll both Explorer tips against the CKB RPC every 5 seconds until interrupted.
python3 scripts/monitor_block_sync.py

# Take one synchronization snapshot (useful for cron/CI).
python3 scripts/monitor_block_sync.py --once

# Offline harness unit tests.
PYTHONPATH=src python3 -m unittest \
  tests.test_compare tests.test_http tests.test_manifest tests.test_settings -v

# List all 153 cases using config/settings.json.
PYTHONPATH=src python3 -m ckb_api_compat --list

# Compare all currently enabled cases and write the default report.
PYTHONPATH=src python3 -m ckb_api_compat

# Focused online contract test.
PYTHONPATH=src python3 -m unittest \
  tests.contract.test_v1_media.V1MediaContractTests.test_tp_005_exact_v1_media_headers_dispatch -v

# Focus one concrete API file (API-003: block detail).
PYTHONPATH=src python3 -m unittest \
  tests.endpoints.test_api_003_get_v1_blocks_by_id -v

# Run all 153 separate endpoint files.
PYTHONPATH=src python3 -m unittest discover \
  -s tests/endpoints -p 'test_api_*.py' -v
```

Override the declared pair with `BASELINE_API_URL` and `CANDIDATE_API_URL` or CLI `--baseline`/`--candidate`. The base URLs must already include `/api`.

`scripts/monitor_block_sync.py` defaults to the two declared Explorer URLs, the
declared fixture RPC, and a five-second interval. It queries each Explorer's
latest `/v1/blocks` row concurrently with RPC `get_tip_header`, reports each
Explorer's signed `lag` in blocks, and verifies the block hash whenever its
height equals the RPC tip. The default terminal output prints
`time|rpc|ckba|explorer` once, then appends one pipe-separated local ISO time
and height row per poll; use `--json` for complete structured observations.
`SYNCED` means both height and hash match;
`LAGGING`, `RPC_BEHIND`, `HASH_MISMATCH`, and `ERROR` identify distinct failure
modes. Override inputs with `--explorer-a-url`, `--explorer-b-url`, and
`--rpc-url`; use `--interval`, `--max-lag`, `--count`, or `--json` for other
monitoring and logging needs.

Path parameters are filled from `variables` or per-case `path_params` in the
fixture JSON. Deployment-local IDs can use `baseline_path_params` and
`candidate_path_params`; this is used for the same Cell input/output whose
database ID differs between environments. A missing fixture produces an
explicit skip, and the checked-in `strict_fixtures: true` turns any regression
back into exit status 2. `POST`, `PATCH`, `PUT`, and `DELETE` require both the
global mutation setting (or CLI override) and per-case `allow_mutation: true`.

The stable block hash and transaction hash were resolved from the declared CKB
RPC, then verified through both Explorer deployments. Corresponding Cell output
IDs were extracted separately from each Explorer response because those numeric
IDs are database-local; Cell input subresource routes use an explicit missing-ID
fixture because their local row IDs are not exposed by the public transaction
response. Stable business identifiers such as block hash, transaction hash,
address, UDT type hash, NFT collection serial, and NFT token ID are shared
across sides.

The default comparison is ordered and type-strict. V1 JSON:API resource `id`
values and numeric relational `id`/`*_id` fields are normalized because they are
deployment-local database identifiers. Stable protocol IDs such as `token_id`,
`node_id`, `peer_id`, `channel_id`, and `nft_class_id` remain strict. Additional
normalization still requires per-case RFC 6901 `ignore_paths` or `set_paths`,
and every applied normalization appears in the report. Exit status is 0 for
matches, 1 for compatibility differences, and 2 for invalid/incomplete strict
configuration.

The two `local_node_info` cases explicitly ignore only that deployment's node
identity (`node_id`); advertised protocol IDs and supported versions remain
strict. Per-case rules also normalize database ingestion timestamps and sort
arrays only where the controller query has no complete deterministic ordering.
Business counts, hashes, capacities, rates, and protocol versions are still
compared and remain visible as compatibility differences.

Do not combine concrete API tests into one source file. `config/endpoints.json` is the inventory source, `scripts/generate_endpoint_tests.py` enforces the one-API/one-file mapping, and shared behavior belongs in `tests/endpoint_support.py` or `src/ckb_api_compat/`.

Each generated endpoint file contains an explicit `request_both(method=...,
path=...)` invocation. The shared helper validates those declarations against
the manifest before issuing parallel HTTP requests to the baseline and
candidate URLs.

POST, PATCH, and PUT endpoint files additionally contain their JSON `data`
dictionary and pass it as `json_body=data`. The generator requires an explicit
body for every such route. API-007, API-067, and API-068 are read-only query
operations; create/update routes use the non-transition probes described above.

These commands are part of the suite contract and must stay current when the runner changes.
