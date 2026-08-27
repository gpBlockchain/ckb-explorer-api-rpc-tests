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

Transient transport failures, including read timeouts, HTTP 429 responses, and
HTTP 5xx responses, are retried three times by default (four total attempts).

## Commands

```bash
# Deterministic unit tests.
PYTHONPATH=src python3 -m unittest tests.test_ckb tests.test_http tests.test_oracle tests.test_settings -v

# GET /api/v1/blocks RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_blocks_index -v

# GET /api/v1/blocks/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_blocks_show -v

# GET /api/v1/blocks/download_csv RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_blocks_download_csv -v

# GET /api/v1/block_transactions/:block_hash RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_block_transactions_show -v

# GET /api/v1/transactions RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_transactions_index -v

# GET /api/v1/transactions/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_transactions_show -v

# GET /api/v1/cell_input_lock_scripts/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_cell_input_lock_scripts_show -v

# GET /api/v1/cell_input_type_scripts/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_cell_input_type_scripts_show -v

# GET /api/v1/cell_input_data/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_cell_input_data_show -v

# GET /api/v1/cell_output_lock_scripts/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_cell_output_lock_scripts_show -v

# GET /api/v1/cell_output_type_scripts/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_cell_output_type_scripts_show -v

# GET /api/v1/cell_output_data/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_cell_output_data_show -v

# GET /api/v2/ckb_transactions/:id/details RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v2_ckb_transactions_details -v

# GET /api/v2/ckb_transactions/:id/display_inputs RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v2_ckb_transactions_display_inputs -v

# GET /api/v2/ckb_transactions/:id/display_outputs RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v2_ckb_transactions_display_outputs -v

# GET /api/v2/transactions/:id/raw RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v2_transactions_raw -v

# GET /api/v2/transactions/:id/details RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v2_transactions_details -v

# GET /api/v2/pending_transactions RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v2_pending_transactions_index -v

# GET /api/v2/pending_transactions/count RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v2_pending_transactions_count -v

# GET /api/v2/blocks/by_epoch RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v2_blocks_by_epoch -v

# GET /api/v2/blocks/ckb_node_versions RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v2_blocks_ckb_node_versions -v

# GET /api/v1/addresses/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v1_addresses_show -v

# GET /api/v1/address_dao_transactions/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v1_address_dao_transactions_show -v

# GET /api/v1/address_transactions/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v1_address_transactions_show -v

# GET /api/v1/address_transactions/download_csv RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v1_address_transactions_download_csv -v

# GET /api/v1/dao_contract_transactions/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v1_dao_contract_transactions_show -v

# GET /api/v1/dao_depositors RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v1_dao_depositors_index -v

# GET /api/v1/dao_depositors/download_csv RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v1_dao_depositors_download_csv -v

# GET /api/v1/address_pending_transactions/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v1_address_pending_transactions_show -v

# GET /api/v1/address_live_cells/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v1_address_live_cells_show -v

# GET /api/v1/address_deployed_cells/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v1_address_deployed_cells_show -v

# GET /api/v2/dao_events RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v2_dao_events_index -v

# GET /api/v1/contract_transactions/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v1_contract_transactions_show -v

# GET /api/v1/contract_transactions/download_csv RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v1_contract_transactions_download_csv -v

# GET /api/v1/contracts/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.address_dao.test_v1_contracts_show -v

# GET /api/v2/scripts RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.contract_script.test_v2_scripts_index -v

# GET /api/v2/scripts/ckb_transactions RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.contract_script.test_v2_scripts_ckb_transactions -v

# GET /api/v2/scripts/deployed_cells RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.contract_script.test_v2_scripts_deployed_cells -v

# GET /api/v2/scripts/referring_cells RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.contract_script.test_v2_scripts_referring_cells -v

# GET /api/v2/scripts/general_info RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.contract_script.test_v2_scripts_general_info -v

# GET /api/v1/udt_queries correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_udt_queries_index -v

# GET /api/v1/udts correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_udts_index -v

# GET /api/v1/udts/download_csv RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_udts_download_csv -v

# GET /api/v1/udts/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_udts_show -v

# GET /api/v1/udts/:id/holder_allocation RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_udts_holder_allocation -v

# GET /api/v1/xudts correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_xudts_index -v

# GET /api/v1/xudts/snapshot RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_xudts_snapshot -v

# GET /api/v1/xudts/:id RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_xudts_show -v

# GET /api/v1/fungible_tokens correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_fungible_tokens_index -v

# GET /api/v1/fungible_tokens/download_csv RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_fungible_tokens_download_csv -v

# GET /api/v1/fungible_tokens/:id RPC correctness against public SSRI fixtures.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_fungible_tokens_show -v

# GET /api/v1/omiga_inscriptions lifecycle, pagination, and sorting correctness.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_omiga_inscriptions_index -v

# GET /api/v1/omiga_inscriptions/download_csv stage, bounds, and RPC-derived row correctness.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_omiga_inscriptions_download_csv -v

# GET /api/v1/omiga_inscriptions/:id lifecycle selection and Info/UDT Cell correctness.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_omiga_inscriptions_show -v

# GET /api/v1/udt_transactions/:id membership, filters, pagination, and preview correctness.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_udt_transactions_show -v

# GET /api/v1/address_udt_transactions/:id pagination, previews, income, and validation correctness.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_address_udt_transactions_show -v

# PATCH and PUT /api/v1/udt_verifications/:id no-contact and missing-UDT error correctness.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v1_udt_verifications_patch -v

# GET /api/v2/udt_hourly_statistics aggregate bucket and integer-string correctness.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v2_udt_hourly_statistics_index -v

# GET /api/v2/udt_hourly_statistics/:id series and RPC/Indexer aggregate correctness.
PYTHONPATH=src python3 -m unittest tests.token_udt.test_v2_udt_hourly_statistics_show -v

# POST /api/v2/das_accounts batch mapping, validation, and DAS Indexer correctness.
PYTHONPATH=src python3 -m unittest tests.rgb_bitcoin.test_v2_das_accounts_query -v

# POST /api/v2/bitcoin_transactions raw transaction, partial error, and fallback correctness.
PYTHONPATH=src python3 -m unittest tests.rgb_bitcoin.test_v2_bitcoin_transactions_query -v

# GET /api/v2/ckb_transactions/:id/rgb_digest CKB commitment and Bitcoin linkage correctness.
PYTHONPATH=src python3 -m unittest tests.rgb_bitcoin.test_v2_ckb_transactions_rgb_digest -v

# GET /api/v2/nft/collections filtering, ordering, and pagination correctness.
PYTHONPATH=src python3 -m unittest tests.nft.test_v2_nft_collections_index -v

# GET /api/v2/nft/collections/:id chain identity and protocol metadata correctness.
PYTHONPATH=src python3 -m unittest tests.nft.test_v2_nft_collections_show -v

# GET /api/v2/nft/collections/:collection_id/holders live ownership and quantity correctness.
PYTHONPATH=src python3 -m unittest tests.nft.test_v2_nft_collection_holders_index -v

# GET /api/v2/nft/collections/:collection_id/transfers chain event, filtering, and parent-scope correctness.
PYTHONPATH=src python3 -m unittest tests.nft.test_v2_nft_collection_transfers_index -v

# GET /api/v2/nft/collections/:collection_id/items live membership, filtering, and numeric ordering correctness.
PYTHONPATH=src python3 -m unittest tests.nft.test_v2_nft_collection_items_index -v

# GET /api/v2/nft/collections/:collection_id/items/:id chain identity, token decoding, and parent-scope correctness.
PYTHONPATH=src python3 -m unittest tests.nft.test_v2_nft_collection_items_show -v

# GET /api/v2/nft/collections/:collection_id/items/:item_id/transfers parent-scope correctness.
PYTHONPATH=src python3 -m unittest tests.nft.test_v2_nft_collection_item_transfers_index -v

# GET /api/v2/nft/collections/:collection_id/items/:item_id/transfers/:id detail identity and parent-scope correctness.
PYTHONPATH=src python3 -m unittest tests.nft.test_v2_nft_collection_item_transfers_show -v

# GET /api/v2/nft/items global live-cell membership, standard coverage, and pagination correctness.
PYTHONPATH=src python3 -m unittest tests.nft.test_v2_nft_items_index -v

# GET /api/v2/nft/transfers cross-collection event identity and chain ordering correctness.
PYTHONPATH=src python3 -m unittest tests.nft.test_v2_nft_transfers_index -v

# GET /api/v2/nft/transfers/download_csv collection scope, RPC fee, inclusive ranges, and 500-row cap correctness.
PYTHONPATH=src python3 -m unittest tests.nft.test_v2_nft_transfers_download_csv -v

# GET /api/v2/nft/transfers/:id list/detail identity and CKB Cell-event correctness.
PYTHONPATH=src python3 -m unittest tests.nft.test_v2_nft_transfers_show -v

# GET /api/v2/bitcoin_statistics persisted series shape/order and same-index oracle availability.
PYTHONPATH=src python3 -m unittest tests.rgb_bitcoin.test_v2_bitcoin_statistics_index -v

# GET /api/v2/bitcoin_addresses/:id bound/unbound live-cell counts and empty-address correctness.
PYTHONPATH=src python3 -m unittest tests.rgb_bitcoin.test_v2_bitcoin_addresses_show -v

# GET /api/v2/bitcoin_addresses/:id/rgb_cells Bitcoin-outpoint grouping, Cell details, and pagination correctness.
PYTHONPATH=src python3 -m unittest tests.rgb_bitcoin.test_v2_bitcoin_addresses_rgb_cells -v

# GET /api/v2/bitcoin_addresses/:id/udt_accounts published bound UDT aggregation and exact uint128 amount correctness.
PYTHONPATH=src python3 -m unittest tests.rgb_bitcoin.test_v2_bitcoin_addresses_udt_accounts -v

# GET /api/v2/rgb_live_cells lock filtering, CKB/Bitcoin membership, page cap, and invalid-code-hash correctness.
PYTHONPATH=src python3 -m unittest tests.rgb_bitcoin.test_v2_rgb_live_cells_index -v

# GET /api/v2/rgb_transactions CKB/Bitcoin fields, workflow, filtering, sorting, and pagination correctness.
PYTHONPATH=src python3 -m unittest tests.rgb_bitcoin.test_v2_rgb_transactions_index -v

# GET /api/v2/rgb_assets_statistics persisted rows, decimal precision, ordering, filters, and snapshot-oracle handling.
PYTHONPATH=src python3 -m unittest tests.rgb_bitcoin.test_v2_rgb_assets_statistics_index -v

# GET /api/v2/rgb_top_holders/:id exact CKB/Bitcoin aggregation, global ranking, ratios, and error correctness.
PYTHONPATH=src python3 -m unittest tests.rgb_bitcoin.test_v2_rgb_top_holders_show -v

# GET /api/v1/external/stats/:id indexed-tip and unknown-identifier correctness.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v1_external_stats_show -v

# GET /api/v1/suggest_queries block, transaction, address, script, aggregate, and not-found correctness.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v1_suggest_queries_index -v

# GET /api/v1/statistics fixed-tip epoch, difficulty, windows, rates, and reorg-state correctness.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v1_statistics_index -v

# GET /api/v1/statistics/:id single metrics, node info, rankings, runtime cache, and invalid-name correctness.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v1_statistics_show -v

# GET /api/v1/nets complete configured-node local_node_info correctness.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v1_nets_index -v

# GET /api/v1/nets/:id selector consistency, invalid-name, and cache-snapshot correctness.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v1_nets_show -v

# GET /api/v1/statistic_info_charts difficulty, Uncle Rate, and keyed Hash Rate cache correctness.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v1_statistic_info_charts_index -v

# GET /api/v1/daily_statistics/:id isolation, ordering, combined snapshots, cache, and invalid-name correctness.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v1_daily_statistics_show -v

# GET /api/v1/epoch_statistics/:id full-Epoch RPC formulas, limit ordering, maxima, and invalid-name correctness.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v1_epoch_statistics_show -v

# GET /api/v1/market_data homepage/detail independent supply snapshots and exact decimal format.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v1_market_data_index -v

# GET /api/v1/market_data/:id supply formula branches, precision, and unknown-ID correctness.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v1_market_data_show -v

# GET /api/v1/distribution_data/:id latest/combined distributions, rolling sequence, and miner windows.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v1_distribution_data_show -v

# GET /api/v1/monetary_data/:id monthly APC/inflation formulas, alignment, and invalid-name correctness.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v1_monetary_data_show -v

# GET /api/v2/monitors/daily_statistics application-timezone freshness correctness.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v2_monitors_daily_statistics_index -v

# GET /api/v2/statistics/transaction_fees committed/pending/daily fee-window correctness.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v2_statistics_transaction_fees -v

# GET /api/v2/statistics/contract_resource_distributed Active rows, Type Hash filtering, and CKB precision.
PYTHONPATH=src python3 -m unittest tests.statistics_discovery.test_v2_statistics_contract_resource_distributed -v

# POST /api/v2/portfolio/sessions signature recovery, JWT, reuse, malformed input, and mismatch correctness.
PYTHONPATH=src python3 -m unittest tests.portfolio.test_v2_portfolio_sessions_create -v

# PATCH/PUT /api/v2/portfolio/user JWT rejection, persistence, isolation, blank-name, and rollback correctness.
PYTHONPATH=src python3 -m unittest tests.portfolio.test_v2_portfolio_user_update -v

# GET /api/v2/portfolio/statistics multi-address CKB/DAO sums and latest-address synchronization correctness.
PYTHONPATH=src python3 -m unittest tests.portfolio.test_v2_portfolio_statistics_index -v

# POST /api/v2/portfolio/addresses duplicate union, atomic batch rejection, and tenant-isolation correctness.
PYTHONPATH=src python3 -m unittest tests.portfolio.test_v2_portfolio_addresses_create -v

# GET /api/v2/portfolio/udt_accounts sUDT aggregation/filters and four NFT branch correctness.
PYTHONPATH=src python3 -m unittest tests.portfolio.test_v2_portfolio_udt_accounts_index -v

# GET /api/v2/portfolio/ckb_transactions committed deduplication, exact income, scope, filters, sort, and pages.
PYTHONPATH=src python3 -m unittest tests.portfolio.test_v2_portfolio_ckb_transactions_index -v

# GET /api/v2/portfolio/ckb_transactions/download_csv default/ranged exact CSV and invalid-range recovery.
PYTHONPATH=src python3 -m unittest tests.portfolio.test_v2_portfolio_ckb_transactions_download_csv -v

# GET /api/v2/fiber/peers configured membership and READY-channel Fiber RPC aggregates.
PYTHONPATH=src python3 -m unittest tests.fiber.test_v2_fiber_peers_index -v

# POST /api/v2/fiber/peers connection validation, one-time sync, idempotent merge, and failure isolation.
PYTHONPATH=src python3 -m unittest tests.fiber.test_v2_fiber_peers_create -v

# GET /api/v2/fiber/peers/:peer_id owned Channel identity and not-found recovery correctness.
PYTHONPATH=src python3 -m unittest tests.fiber.test_v2_fiber_peers_show -v

# GET /api/v2/fiber/channels/:channel_id Fiber RPC identity/balances, peer direction, and not-found recovery.
PYTHONPATH=src python3 -m unittest tests.fiber.test_v2_fiber_channels_show -v

# GET /api/v2/fiber/graph_nodes upstream membership/search/pagination and soft-delete history boundaries.
PYTHONPATH=src python3 -m unittest tests.fiber.test_v2_fiber_graph_nodes_index -v

# GET /api/v2/fiber/graph_nodes/addresses active addresses and deduplicated open-connection correctness.
PYTHONPATH=src python3 -m unittest tests.fiber.test_v2_fiber_graph_nodes_addresses -v

# GET /api/v2/fiber/graph_nodes/:node_id active/history aggregates and three-route not-found recovery.
PYTHONPATH=src python3 -m unittest tests.fiber.test_v2_fiber_graph_nodes_show -v

# GET /api/v2/fiber/graph_nodes/:node_id/graph_channels incident history, CKB funding, filters, and pages.
PYTHONPATH=src python3 -m unittest tests.fiber.test_v2_fiber_graph_node_channels -v

# GET /api/v2/fiber/graph_nodes/:node_id/transactions event identity, CKB blocks, filters, sort, and pages.
PYTHONPATH=src python3 -m unittest tests.fiber.test_v2_fiber_graph_node_transactions -v

# GET /api/v2/fiber/graph_channels active membership, filters, CKB funding, UDT, and close consumption.
PYTHONPATH=src python3 -m unittest tests.fiber.test_v2_fiber_graph_channels_index -v

# GET /api/v2/fiber/statistics seven-day window, graph aggregates, means/medians, and liquidity correctness.
PYTHONPATH=src python3 -m unittest tests.fiber.test_v2_fiber_statistics_index -v

# GET /api/v2/fiber/statistics/:id four indicator projections, 14-day windows, and list consistency.
PYTHONPATH=src python3 -m unittest tests.fiber.test_v2_fiber_statistics_show -v

# POST /api/v1/transactions/query RPC correctness against both public networks.
PYTHONPATH=src python3 -m unittest tests.chain_data.test_v1_transactions_query -v

# Review-to-automation mapping coverage.
python3 ../../scripts/check_test_map.py --root ../..
```

The live test allows Explorer to trail its same-network RPC by at most five
blocks. Sample selection searches up to five recent 100-row list pages so that
low-traffic testnet windows can still supply non-trivial transaction fixtures.
When the selected height changes hash during an assertion, the affected network
subtest is reported as skipped because the oracle observed a reorg.
The block-transaction preview boundary needs a normal transaction with more
than ten inputs or outputs; a network whose configured search window has no
such transaction reports that case as unavailable instead of using a fixture
that does not exercise the boundary.
The block CSV contract keeps the latest 500 matching heights in descending
order. A transport timeout on the public date-only export is reported as an
unavailable live observation rather than a CSV value mismatch.
The default transaction-list checks require a stable 15-row snapshot. A
snapshot without the reviewed same-block, live-cell-change, or input-count
fixtures reports only the affected network and case as unavailable.
Transaction-detail fixtures are deeply confirmed immutable transactions chosen
to cover Header Dependencies, mixed Type Scripts, more than ten Cells, and
Cellbase behavior without relying on a moving latest-list snapshot.
Cell-input Lock Script fixtures are deeply confirmed multi-input transactions
whose Explorer `CellInput.id` values map to fixed RPC input positions. Their
same-block input sequences also anchor real Cellbase IDs for the 404 contract.
Cell-input Type Script fixtures reuse those stable typed, untyped, and Cellbase
inputs and add fixed transactions whose first two referenced outputs carry
different non-null Type Scripts for input-isolation coverage.
Cell-input Data fixtures additionally require the Input Data response resource
ID to equal the selected transaction display input's Cell Output ID before an
RPC data comparison. A stale or publicly unresolvable internal CellInput ID is
reported as an unavailable network subtest instead of a data mismatch.
Transaction-query fixtures use complete address histories for membership,
ordering, pagination, and signed income checks, plus deeply confirmed mixed-Type
and wide transactions for the two ten-Cell preview boundaries. The omitted-address
case follows the controller's existing global-query branch and reports HTTP 500
as a correctness failure.
