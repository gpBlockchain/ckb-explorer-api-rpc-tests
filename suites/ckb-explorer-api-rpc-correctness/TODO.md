# CKB Explorer API RPC 正确性 TODO

- 已完成：`GET /api/v1/blocks`
- 已完成：`GET /api/v1/blocks/:id`
- ACTIVE TODO：122
- 路由审计 TODO：29

## gp：Chain Data（20）

- [ ] `GET /api/v1/blocks/download_csv` — 导出区块 CSV
- [ ] `GET /api/v1/block_transactions/:id` — 区块交易列表
- [ ] `GET /api/v1/transactions` — 交易列表
- [ ] `GET /api/v1/transactions/:id` — 交易详情
- [ ] `POST /api/v1/transactions/query` — 批量/条件查询交易
- [ ] `GET /api/v1/cell_input_lock_scripts/:id` — 输入 Cell Lock Script
- [ ] `GET /api/v1/cell_input_type_scripts/:id` — 输入 Cell Type Script
- [ ] `GET /api/v1/cell_input_data/:id` — 输入 Cell Data
- [ ] `GET /api/v1/cell_output_lock_scripts/:id` — 输出 Cell Lock Script
- [ ] `GET /api/v1/cell_output_type_scripts/:id` — 输出 Cell Type Script
- [ ] `GET /api/v1/cell_output_data/:id` — 输出 Cell Data
- [ ] `GET /api/v2/ckb_transactions/:id/details` — 交易资产变更明细
- [ ] `GET /api/v2/ckb_transactions/:id/display_inputs` — 分页展示交易输入
- [ ] `GET /api/v2/ckb_transactions/:id/display_outputs` — 分页展示交易输出
- [ ] `GET /api/v2/transactions/:id/raw` — 原始交易结构
- [ ] `GET /api/v2/transactions/:id/details` — CKB 容量变更明细
- [ ] `GET /api/v2/pending_transactions` — 待处理交易列表
- [ ] `GET /api/v2/pending_transactions/count` — 待处理交易数量
- [ ] `GET /api/v2/blocks/ckb_node_versions` — CKB 节点版本分布
- [ ] `GET /api/v2/blocks/by_epoch` — 按 Epoch 查询区块

## scz：Address / DAO + Contract / Script（19）

- [ ] `GET /api/v1/addresses/:id` — 地址详情
- [ ] `GET /api/v1/address_dao_transactions/:id` — 地址 DAO 交易
- [ ] `GET /api/v1/address_transactions/:id` — 地址交易列表
- [ ] `GET /api/v1/address_transactions/download_csv` — 导出地址交易 CSV
- [ ] `GET /api/v1/dao_contract_transactions/:id` — DAO 合约交易
- [ ] `GET /api/v1/dao_depositors` — DAO 存款人列表
- [ ] `GET /api/v1/dao_depositors/download_csv` — 导出 DAO 存款人 CSV
- [ ] `GET /api/v1/address_pending_transactions/:id` — 地址待处理交易
- [ ] `GET /api/v1/address_live_cells/:id` — 地址 Live Cells
- [ ] `GET /api/v1/address_deployed_cells/:id` — 地址部署 Cells
- [ ] `GET /api/v2/dao_events` — DAO 事件列表
- [ ] `GET /api/v1/contract_transactions/:id` — 合约交易列表
- [ ] `GET /api/v1/contract_transactions/download_csv` — 导出合约交易 CSV
- [ ] `GET /api/v1/contracts/:id` — 合约详情
- [ ] `GET /api/v2/scripts` — 脚本列表
- [ ] `GET /api/v2/scripts/ckb_transactions` — 脚本关联交易
- [ ] `GET /api/v2/scripts/deployed_cells` — 脚本部署 Cells
- [ ] `GET /api/v2/scripts/referring_cells` — 脚本引用 Cells
- [ ] `GET /api/v2/scripts/general_info` — 脚本通用信息

## xyl：Token / UDT（23）

- [ ] `GET /api/v1/udt_queries` — UDT 搜索
- [ ] `GET /api/v1/udts` — UDT 列表
- [ ] `GET /api/v1/udts/download_csv` — 导出 UDT CSV
- [ ] `GET /api/v1/udts/:id` — UDT 详情
- [ ] `PATCH /api/v1/udts/:id` — 更新 UDT 元数据
- [ ] `PUT /api/v1/udts/:id` — 更新 UDT 元数据
- [ ] `GET /api/v1/udts/:id/holder_allocation` — UDT 持仓分布
- [ ] `GET /api/v1/xudts` — xUDT 列表
- [ ] `GET /api/v1/xudts/download_csv` — 导出 xUDT CSV
- [ ] `GET /api/v1/xudts/snapshot` — xUDT 快照
- [ ] `GET /api/v1/xudts/:id` — xUDT 详情
- [ ] `GET /api/v1/fungible_tokens` — 同质化代币列表
- [ ] `GET /api/v1/fungible_tokens/download_csv` — 导出同质化代币 CSV
- [ ] `GET /api/v1/fungible_tokens/:id` — 同质化代币详情
- [ ] `GET /api/v1/omiga_inscriptions` — Omiga 铭文列表
- [ ] `GET /api/v1/omiga_inscriptions/download_csv` — 导出 Omiga 铭文 CSV
- [ ] `GET /api/v1/omiga_inscriptions/:id` — Omiga 铭文详情
- [ ] `GET /api/v1/udt_transactions/:id` — UDT 交易列表
- [ ] `GET /api/v1/address_udt_transactions/:id` — 地址 UDT 交易
- [ ] `PATCH /api/v1/udt_verifications/:id` — 更新 UDT 验证
- [ ] `PUT /api/v1/udt_verifications/:id` — 更新 UDT 验证
- [ ] `GET /api/v2/udt_hourly_statistics` — UDT 小时统计列表
- [ ] `GET /api/v2/udt_hourly_statistics/:id` — UDT 小时统计详情

## gp：NFT / RGB / Bitcoin（23）

- [ ] `POST /api/v2/das_accounts` — DAS 账户查询
- [ ] `POST /api/v2/bitcoin_transactions` — Bitcoin 交易查询
- [ ] `GET /api/v2/ckb_transactions/:id/rgb_digest` — RGB++ 交易摘要
- [ ] `GET /api/v2/nft/collections` — NFT 集合列表
- [ ] `GET /api/v2/nft/collections/:id` — NFT 集合详情
- [ ] `GET /api/v2/nft/collections/:collection_id/holders` — NFT 集合持有人
- [ ] `GET /api/v2/nft/collections/:collection_id/transfers` — NFT 集合转移记录
- [ ] `GET /api/v2/nft/collections/:collection_id/items` — 集合 NFT Item 列表
- [ ] `GET /api/v2/nft/collections/:collection_id/items/:id` — NFT Item 详情
- [ ] `GET /api/v2/nft/collections/:collection_id/items/:item_id/transfers` — NFT Item 转移列表
- [ ] `GET /api/v2/nft/collections/:collection_id/items/:item_id/transfers/:id` — NFT Item 转移详情
- [ ] `GET /api/v2/nft/items` — 全局 NFT Item 列表
- [ ] `GET /api/v2/nft/transfers` — 全局 NFT 转移列表
- [ ] `GET /api/v2/nft/transfers/download_csv` — 导出 NFT 转移 CSV
- [ ] `GET /api/v2/nft/transfers/:id` — NFT 转移详情
- [ ] `GET /api/v2/bitcoin_statistics` — Bitcoin 统计
- [ ] `GET /api/v2/bitcoin_addresses/:id` — Bitcoin 地址详情
- [ ] `GET /api/v2/bitcoin_addresses/:id/rgb_cells` — Bitcoin 地址 RGB Cells
- [ ] `GET /api/v2/bitcoin_addresses/:id/udt_accounts` — Bitcoin 地址 UDT 账户
- [ ] `GET /api/v2/rgb_live_cells` — RGB Live Cells
- [ ] `GET /api/v2/rgb_transactions` — RGB 交易列表
- [ ] `GET /api/v2/rgb_assets_statistics` — RGB 资产统计
- [ ] `GET /api/v2/rgb_top_holders/:id` — RGB Top Holders

## scz：Statistics / Discovery（17）

- [ ] `GET /api/v1/external/stats/:id` — 外部统计详情
- [ ] `GET /api/v1/suggest_queries` — 搜索建议
- [ ] `GET /api/v1/statistics` — 统计列表
- [ ] `GET /api/v1/statistics/:id` — 统计详情
- [ ] `GET /api/v1/nets` — 网络信息列表
- [ ] `GET /api/v1/nets/:id` — 网络信息详情
- [ ] `GET /api/v1/statistic_info_charts` — 统计图表
- [ ] `GET /api/v1/daily_statistics/:id` — 每日统计
- [ ] `GET /api/v1/block_statistics/:id` — 区块统计（源码标注 unused）
- [ ] `GET /api/v1/epoch_statistics/:id` — Epoch 统计
- [ ] `GET /api/v1/market_data` — 市场数据列表
- [ ] `GET /api/v1/market_data/:id` — 市场数据详情
- [ ] `GET /api/v1/distribution_data/:id` — 分布数据
- [ ] `GET /api/v1/monetary_data/:id` — 货币数据
- [ ] `GET /api/v2/monitors/daily_statistics` — 监控每日统计
- [ ] `GET /api/v2/statistics/transaction_fees` — 交易手续费统计
- [ ] `GET /api/v2/statistics/contract_resource_distributed` — 合约资源分布

## xyl：Portfolio + Fiber（20）

- [ ] `POST /api/v2/portfolio/sessions` — 创建 Portfolio 会话
- [ ] `PATCH /api/v2/portfolio/user` — 更新 Portfolio 用户
- [ ] `PUT /api/v2/portfolio/user` — 更新 Portfolio 用户
- [ ] `GET /api/v2/portfolio/statistics` — Portfolio 统计
- [ ] `POST /api/v2/portfolio/addresses` — 添加 Portfolio 地址
- [ ] `GET /api/v2/portfolio/udt_accounts` — Portfolio UDT 账户
- [ ] `GET /api/v2/portfolio/ckb_transactions` — Portfolio 交易列表
- [ ] `GET /api/v2/portfolio/ckb_transactions/download_csv` — 导出 Portfolio 交易 CSV
- [ ] `GET /api/v2/fiber/peers` — Fiber Peer 列表
- [ ] `POST /api/v2/fiber/peers` — 创建/测试 Fiber Peer 连接
- [ ] `GET /api/v2/fiber/peers/:peer_id` — Fiber Peer 详情
- [ ] `GET /api/v2/fiber/channels/:channel_id` — Fiber Channel 详情
- [ ] `GET /api/v2/fiber/graph_nodes` — Fiber Graph Node 列表
- [ ] `GET /api/v2/fiber/graph_nodes/addresses` — Fiber Graph Node 地址列表
- [ ] `GET /api/v2/fiber/graph_nodes/:node_id` — Fiber Graph Node 详情
- [ ] `GET /api/v2/fiber/graph_nodes/:node_id/graph_channels` — 节点关联 Channel
- [ ] `GET /api/v2/fiber/graph_nodes/:node_id/transactions` — 节点关联交易
- [ ] `GET /api/v2/fiber/graph_channels` — Fiber Graph Channel 列表
- [ ] `GET /api/v2/fiber/statistics` — Fiber 统计列表
- [ ] `GET /api/v2/fiber/statistics/:id` — Fiber 统计详情

## gp：路由审计（29）

- [ ] `GET /api/v2/ckb_transactions` — V2 交易列表 [ROUTE_ONLY]
- [ ] `GET /api/v2/ckb_transactions/:id` — V2 交易详情 [ROUTE_ONLY]
- [ ] `GET /api/v2/transactions` — REST 交易列表 [ROUTE_ONLY]
- [ ] `POST /api/v2/transactions` — REST 创建交易 [ROUTE_ONLY]
- [ ] `GET /api/v2/transactions/new` — REST 新建交易表单 [ROUTE_ONLY]
- [ ] `GET /api/v2/transactions/:id` — REST 交易详情 [ROUTE_ONLY]
- [ ] `GET /api/v2/transactions/:id/edit` — REST 编辑交易表单 [ROUTE_ONLY]
- [ ] `PATCH /api/v2/transactions/:id` — REST 更新交易 [ROUTE_ONLY]
- [ ] `PUT /api/v2/transactions/:id` — REST 更新交易 [ROUTE_ONLY]
- [ ] `DELETE /api/v2/transactions/:id` — REST 删除交易 [ROUTE_ONLY]
- [ ] `POST /api/v2/nft/collections` — 创建 NFT 集合 [ROUTE_ONLY]
- [ ] `GET /api/v2/nft/collections/new` — NFT 集合新建表单 [ROUTE_ONLY]
- [ ] `GET /api/v2/nft/collections/:id/edit` — NFT 集合编辑表单 [ROUTE_ONLY]
- [ ] `PATCH /api/v2/nft/collections/:id` — 更新 NFT 集合 [ROUTE_ONLY]
- [ ] `PUT /api/v2/nft/collections/:id` — 更新 NFT 集合 [ROUTE_ONLY]
- [ ] `DELETE /api/v2/nft/collections/:id` — 删除 NFT 集合 [ROUTE_ONLY]
- [ ] `POST /api/v2/nft/collections/:collection_id/items` — 创建 NFT Item [ROUTE_ONLY]
- [ ] `GET /api/v2/nft/collections/:collection_id/items/new` — NFT Item 新建表单 [ROUTE_ONLY]
- [ ] `GET /api/v2/nft/collections/:collection_id/items/:id/edit` — NFT Item 编辑表单 [ROUTE_ONLY]
- [ ] `PATCH /api/v2/nft/collections/:collection_id/items/:id` — 更新 NFT Item [ROUTE_ONLY]
- [ ] `PUT /api/v2/nft/collections/:collection_id/items/:id` — 更新 NFT Item [ROUTE_ONLY]
- [ ] `DELETE /api/v2/nft/collections/:collection_id/items/:id` — 删除 NFT Item [ROUTE_ONLY]
- [ ] `GET /api/v2/nft/cota/nft_classes` — CoTA NFT Class 列表 [NAMESPACE_MISMATCH]
- [ ] `GET /api/v2/nft/cota/nft_classes/:nft_class_id/tokens` — CoTA Token 列表 [NAMESPACE_MISMATCH]
- [ ] `GET /api/v2/nft/cota/nft_classes/:nft_class_id/tokens/:id/claimed` — CoTA Token 领取状态 [NAMESPACE_MISMATCH]
- [ ] `GET /api/v2/nft/cota/nft_classes/:nft_class_id/tokens/:id/sender` — CoTA Token 发送者 [NAMESPACE_MISMATCH]
- [ ] `GET /api/v2/nft/cota/transactions` — CoTA 交易列表 [NAMESPACE_MISMATCH]
- [ ] `GET /api/v2/nft/cota/issuers/:id` — CoTA Issuer 详情 [NAMESPACE_MISMATCH]
- [ ] `GET /api/v2/nft/cota/issuers/:id/minted` — CoTA Issuer 铸造记录 [NAMESPACE_MISMATCH]
