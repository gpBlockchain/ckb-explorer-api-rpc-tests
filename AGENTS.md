# CKB Explorer API RPC Test Project Instructions

This is the repository-wide instruction source. Keep stable project rules here and suite-specific execution rules inside each suite.

## Purpose and Target

- Maintain automated tests independently from the product source repository.
- Source repository: `https://github.com/nervosnetwork/ckb-explorer.git`.
- Local source checkout: `source/ckb-explorer-api-rpc/`; default revision: `develop`.
- Test objects: Rails JSON/CSV APIs under `/api/v1` and `/api/v2`, including public reads, authenticated portfolio operations, exports, and Fiber/RGB/Bitcoin extensions.
- Stable entry points: `BASELINE_API_URL`, `CANDIDATE_API_URL`, `config/routes.rb`, and `config/routes/v2.rb`.
- Reviewer-facing test scope lives in `reviews/README.md`; suite review documents live under each suite's `reviews/` directory.

## Source Workspace

- Reuse `source/ckb-explorer-api-rpc/` when it is the matching Git checkout. Initialize or update the configured submodule only when absent, and never overwrite a conflicting path.
- Track the source checkout only as a Git submodule; do not add its contents to this test repository.
- For PR work, fetch the base and head revisions, inspect the diff first, then read wider source context only as needed.
- Do not persist PR-specific analysis reports or source exploration notes.

## Human Review Contract

Reviewers should need only one stable case ID and one self-contained row:

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `AREA-01` | - [ ] 提交有效请求 | 返回预期结果并产生一次预期副作用 | 正常请求失败或被重复处理 | P0 |

- The case ID is also the Test Point ID. Do not introduce separate module, function, coverage, or test-point ID chains.
- Start each scenario cell with `- [ ]` when no matching `TEST-MAP` exists and `- [x]` when one exists; new cases start unchecked.
- Keep each case on one physical Markdown row and describe concrete product behavior.
- Use P0 for release-blocking core behavior, P1 for important failure, recovery, and boundary behavior, and P2 for lower-impact edges.
- Preserve the case ID when correcting wording, expectations, or priority. Add an ID only for a new independently observable behavior.
- Put `待确认：<decision>` in the expected-result cell when behavior is ambiguous and repeat the decision under `本轮需要确认`.
- Do not store per-case proposal, approval, coverage, or automation statuses beyond the scenario checkbox.
- Do not put test paths, implementation steps, source-evidence chains, run history, or mapping tables in the main case table.

Before writing cases, internally consider core behavior, validation, state transitions, failure/recovery, caller trust, cross-component effects, ordering/replay, persistence/restart, compatibility, resource limits, and security-sensitive inputs. Emit only target-supported cases.

## Review Gates

1. **Test-area map:** for a new area, update `reviews/README.md` with its responsibility, boundary, entry points, observables, and review-document path; present the map and stop.
2. **Review cases:** create or revise one coherent review document from `templates/test-review.md`; present every new, deleted, or materially changed row and stop.
3. **Automation:** change mapped tests only after explicit human confirmation of the current rows. Add the exact nearby comment `TEST-MAP: <CASE-ID>`, set the scenario checkbox to `- [x]`, run focused tests, then run `python3 scripts/check_test_map.py`.

Existing unchanged reviewed rows remain eligible for implementation. Any new, deleted, or behavior-changing row reopens the review gate.

## Automation Style

- Prefer direct Arrange-Act-Assert tests whose scenario, action, and oracle can be understood in one pass.
- Reuse existing fixtures and helpers when they remain transparent, but add abstractions only when they remove meaningful repetition without hiding the case-specific setup or expected behavior.
- Avoid unnecessary helpers, wrappers, builders, parameterization, shared setup, and test-only frameworks.
- Keep assertions focused on the smallest sufficient set of caller-observable results, state changes, side effects, or errors. Do not assert implementation details or restate the setup as the oracle.

## Maintenance

- Read this file, the affected suite's `AGENTS.md` and local skill, the relevant review document, and mapped tests.
- Find automation by searching for `TEST-MAP: <CASE-ID>`; mirror that mapping with the scenario checkbox and do not maintain a separate mapping ledger.
- Update an existing row in place when its behavior changes. Add or remove rows only when independently observable behavior is added or removed.
- For PR analysis, translate each behavior change into affected review rows and the minimum test change for a concrete failure mode.
- For every added or materially changed automated case, report why the case is needed and how its observable assertions prove the expected behavior.
- Keep stable commands in the relevant suite README and use the target project's native runner and conventions.
- Persist only stable instructions/commands, `reviews/README.md`, concise review documents, executable tests/fixtures/configuration, and `scripts/check_test_map.py`.

## Handoff

For review-document work, report changed rows, exact decisions needing review, mapping coverage from the checker, verification, residual risk, and the next explicit gate. For PR work use:

```text
PR impact:
- <changed behavior> -> <review document and case IDs> -> <required test action>
Changed cases:
- <ID> [P0/P1/P2] <scenario> -> <expected result>
Added automation:
- <ID>: why <behavior or regression risk>; assertions <observable result, state, side effect, or error and why it proves the expectation>
Automation coverage: <mapped>/<reviewed>; unmapped: <IDs or none>
Verification: <command> -> <result and exit status>
Residual risk: <ambiguous, manual, unobservable, or none>
Needs review: <exact product decision or none>
Next gate: <review confirmation or implementation/verification action>
```

Passing tests support the identified behavior but do not prove that unknown risks are absent.
