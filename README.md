# CKB Explorer API RPC Tests

This standalone project compares the CKB Explorer API behavior of a baseline deployment and a candidate deployment.

## Workspace

- `source/ckb-explorer-api-rpc/`: product repository submodule, tracking `develop` at the revision pinned by this project.
- `reviews/README.md`: concise map of test areas and reviewer-facing documents.
- `templates/test-review.md`: required case-table format.
- `suites/ckb-explorer-api-rpc-compatibility/`: paired HTTP compatibility runner, fixtures, review cases, and automated tests.
- `scripts/check_test_map.py`: computes automation coverage from review case IDs and exact `TEST-MAP:` comments.

## Review Workflow

1. Confirm the test-area boundary in `reviews/README.md`.
2. Review one coherent case table. Each row contains the sole case ID, scenario, expected result, prevented problem, and priority.
3. After explicit confirmation, implement or update tests with a nearby `TEST-MAP: <CASE-ID>` comment.
4. Verify the focused test scope and run:

```bash
python3 scripts/check_test_map.py
```

Review documents do not contain approval, coverage, automation, or execution-history fields. Automation coverage is always derived from code.
