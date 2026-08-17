# CKB Explorer API RPC Correctness Suite Instructions

Inherit repository-wide rules from `../../AGENTS.md`.

## Scope

- Compare one public CKB Explorer API with a CKB RPC from the same network.
- Mainnet and testnet produce independent subtest results; never compare values across networks.
- Reviewer-facing cases live in `reviews/`; executable tests live in `tests/`; reusable code lives in `src/ckb_rpc_correctness/`.
- Use exact nearby `TEST-MAP: <CASE-ID>` comments and preserve reviewed case IDs.
- Treat RPC transport failure, a missing RPC result, or an observed reorg as an unavailable oracle rather than an API data mismatch.
- Decode RPC hexadecimal integers without floating-point conversion and compare monetary values in Shannon.

## Verification

1. Run unit tests for settings and CKB derivations.
2. Run the focused live interface test against both configured public network pairs.
3. Run `python3 ../../scripts/check_test_map.py --root ../..`.
