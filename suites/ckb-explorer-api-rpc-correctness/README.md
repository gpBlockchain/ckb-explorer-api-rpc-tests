# CKB Explorer API RPC Correctness

This suite validates Explorer API data against a CKB RPC on the same network.
It runs every reviewed case independently for public mainnet and testnet.

## Default network pairs

| Network | Explorer API | CKB RPC |
| --- | --- | --- |
| Mainnet | `https://mainnet-api.explorer.nervos.org/api` | `https://mainnet.ckbapp.dev/` |
| Testnet | `https://testnet-api.explorer.nervos.org/api` | `https://testnet.ckbapp.dev/` |

Environment overrides:

- `MAINNET_EXPLORER_API_URL`, `MAINNET_CKB_RPC_URL`
- `TESTNET_EXPLORER_API_URL`, `TESTNET_CKB_RPC_URL`
- `RUN_LIVE_RPC_CORRECTNESS=0` disables live execution

## Commands

```bash
# Deterministic unit tests.
PYTHONPATH=src python3 -m unittest tests.test_ckb tests.test_settings -v

# GET /api/v1/blocks RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_blocks_index -v

# GET /api/v1/blocks/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_blocks_show -v

# Review-to-automation mapping coverage.
python3 ../../scripts/check_test_map.py --root ../..
```

The live test allows Explorer to trail its same-network RPC by at most five
blocks. Sample selection searches up to five recent 100-row list pages so that
low-traffic testnet windows can still supply non-trivial transaction fixtures.
When the selected height changes hash during an assertion, the affected network
subtest is reported as skipped because the oracle observed a reorg.
