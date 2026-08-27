# CKB Explorer API RPC Tests

This standalone project compares the CKB Explorer API behavior of a baseline deployment and a candidate deployment.

## Workspace

- `source/ckb-explorer-api-rpc/`: product repository submodule, tracking `develop` at the revision pinned by this project.
- `reviews/README.md`: concise map of test areas and reviewer-facing documents.
- `templates/test-review.md`: required case-table format.
- `suites/ckb-explorer-api-rpc-compatibility/`: paired HTTP compatibility runner, fixtures, review cases, and automated tests.
- `scripts/check_test_map.py`: computes automation coverage from exact `TEST-MAP:` comments and validates matching scenario checkboxes.

## Review Workflow

1. Confirm the test-area boundary in `reviews/README.md`.
2. Review one coherent case table. Each scenario starts with `- [ ]` for no mapped automation or `- [x]` for a matching `TEST-MAP`.
3. After explicit confirmation, implement or update tests with a nearby `TEST-MAP: <CASE-ID>` comment and synchronize the scenario checkbox.
4. Verify the focused test scope and run:

```bash
python3 scripts/check_test_map.py
```

The scenario checkbox is the only automation-status display in review documents; the checker derives its expected value from code. Review documents do not contain approval, coverage, or execution-history fields.
