---
name: compatibility-test
description: Maintains concise CKB Explorer API RPC compatibility review cases and direct TEST-MAP automation mappings. Use for changes inside this suite.
---

# Compatibility Test Skill

## Stable Domain Rules

- Send the same deterministic method, path, headers, query, and body to the configured baseline and candidate.
- Compare status, selected headers, decoded structure, scalar types, stable values, ordering, pagination, and CSV cells.
- Normalize only explicitly approved deployment-local or volatile fields and report every applied normalization.
- Treat V1 JSON:API resource IDs and numeric relational database IDs as deployment-local where configured; keep protocol and business IDs strict.
- Retain both raw observations and identify the side, phase, endpoint, and exact differing field.
- Retry only configured transient transport failures; do not retry deterministic HTTP or content mismatches.
- Redact secrets without hiding response behavior.
- Keep one generated test file per `API-*` inventory entry.

## Review and Mapping

- Use `reviews/` as the only human-facing case source and the exact five-column table from the root instructions.
- Preserve the existing case ID when changing wording, expectation, or priority.
- Mark unresolved expectations with `待确认：` and stop for review.
- Do not edit automated tests for a new, deleted, or materially changed row until the user confirms it.
- After confirmation, add the exact nearby comment `TEST-MAP: <CASE-ID>`.
- Derive coverage with `python3 ../../scripts/check_test_map.py --root ../..`; do not persist coverage status in Markdown.
