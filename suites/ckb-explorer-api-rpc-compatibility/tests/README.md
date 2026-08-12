# Compatibility Tests

- `endpoints/` contains exactly one generated Python file per `API-*` inventory row.
- `endpoint_support.py` provides shared request and comparison behavior.
- `contract/` contains cross-endpoint protocol checks.
- `test_compare.py`, `test_http.py`, `test_manifest.py`, and `test_settings.py` verify the reusable harness.
- Every reviewed automated behavior uses an exact nearby comment: `TEST-MAP: <CASE-ID>`.

Regenerate and verify endpoint files:

```bash
python3 scripts/generate_endpoint_tests.py
python3 scripts/generate_endpoint_tests.py --check
```

Run all generated endpoint files:

```bash
PYTHONPATH=src python3 -m unittest discover \
  -s tests/endpoints -p 'test_api_*.py' -v
```

Compute current review-to-code mapping coverage from the project root:

```bash
python3 scripts/check_test_map.py
```

Read the suite `AGENTS.md`, local skill, and affected review document before editing tests.
