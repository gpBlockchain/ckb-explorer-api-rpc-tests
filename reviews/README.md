# 测试领域与评审文档

目标源码：`https://github.com/nervosnetwork/ckb-explorer.git`，当前分析版本 `develop@0495ecd00a839f7618bad752f5ad92071124a991`。
执行方式：兼容性套件比较基准与候选环境的 HTTP 行为；RPC 正确性套件把 Explorer API 结果与同一网络、同一区块高度的 CKB RPC 结果或可验证推导值比较。机器可执行的路由与 fixture 保存在各套件配置中，不在评审文档重复维护。

| 测试领域 | 责任与边界 | 入口 | 可观察结果 | 评审文档 |
| --- | --- | --- | --- | --- |
| HTTP API 通用契约 | 比较所有接口共有的路由、媒体类型、错误、分页、CSV、缓存和差异报告规则；不判断具体业务数据是否正确 | `/api/v1/*`、`/api/v2/*`、基准与候选 URL | 状态、选定响应头、数据类型和值、顺序、分页、逐字段差异 | `suites/ckb-explorer-api-rpc-compatibility/reviews/http-api-contract.md` |
| V1 区块列表 RPC 正确性 | 在公开主网和测试网分别以 Explorer 返回的区块高度为锚点，与同网络 CKB RPC 核对区块身份及可直接验证的列表字段，并单独观测同步高度差；不跨网络比较，也不评审双 Explorer 环境兼容性、通用 HTTP 契约、分页和排序 | 主网与测试网的 `GET /api/v1/blocks`、`GET /api/v1/blocks/:height`，以及同网络 CKB RPC `get_tip_header`、`get_block_by_number` 与 `get_block_economic_state` | 每个网络内的 API/RPC 链身份、同步高度差、区块高度、哈希、时间戳、交易数量，以及派生字段的计算证据与差异 | `suites/ckb-explorer-api-rpc-correctness/reviews/chain-data/v1-blocks-index.md` |
| V1 区块详情 RPC 正确性 | 在公开主网和测试网分别按区块高度与区块哈希查询同一规范链区块，并用同网络 CKB RPC 及可验证推导值核对详情字段；不跨网络比较，也不评审双 Explorer 环境兼容性、通用 HTTP 契约和区块交易列表 | 主网与测试网的 `GET /api/v1/blocks/:id`，以及同网络 CKB RPC `get_block_by_number`、`get_block`、`get_block_economic_state` 与必要的链参数查询 | 高度与哈希两种查询的一致性、区块头与 Epoch 字段、交易/提案/叔块计数及根哈希、容量/费用/奖励、矿工信息、区块大小与 cycles 等可核对详情值及差异 | `suites/ckb-explorer-api-rpc-correctness/reviews/chain-data/v1-blocks-show.md` |
| V1 区块交易列表 RPC 正确性 | 在公开主网和测试网分别以规范链区块哈希查询 Explorer 交易列表，并用同网络 CKB RPC 核对交易归属、顺序和可由链数据推导的摘要字段；不跨网络比较，也不评审双 Explorer 环境兼容性、通用 HTTP 契约、分页规则、创建时间以及 RGB/Bitcoin 索引注解 | 主网与测试网的 `GET /api/v1/block_transactions/:block_hash` 及其 `tx_hash`、`address_hash` 过滤条件，以及同网络 CKB RPC `get_block`、`get_transaction` | 区块内交易集合与链上顺序、交易哈希、Cellbase 标识、区块高度与时间戳、输入输出计数和预览，以及按交易哈希或链上地址过滤后的成员关系及差异 | `suites/ckb-explorer-api-rpc-correctness/reviews/chain-data/v1-block-transactions-show.md` |
