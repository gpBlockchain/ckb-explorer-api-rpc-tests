# 测试领域与评审文档

目标源码：`https://github.com/nervosnetwork/ckb-explorer.git`，当前分析版本 `develop@0495ecd00a839f7618bad752f5ad92071124a991`。
执行方式：兼容性套件比较基准与候选环境的 HTTP 行为；RPC 正确性套件把 Explorer API 结果与同一网络、同一区块高度的 CKB RPC 结果或可验证推导值比较。机器可执行的路由与 fixture 保存在各套件配置中，不在评审文档重复维护。

| 测试领域 | 责任与边界 | 入口 | 可观察结果 | 评审文档 |
| --- | --- | --- | --- | --- |
| HTTP API 通用契约 | 比较所有接口共有的路由、媒体类型、错误、分页、CSV、缓存和差异报告规则；不判断具体业务数据是否正确 | `/api/v1/*`、`/api/v2/*`、基准与候选 URL | 状态、选定响应头、数据类型和值、顺序、分页、逐字段差异 | `suites/ckb-explorer-api-rpc-compatibility/reviews/http-api-contract.md` |
| V1 区块列表 RPC 正确性 | 在公开主网和测试网分别以 Explorer 返回的区块高度为锚点，与同网络 CKB RPC 核对区块身份及可直接验证的列表字段，并单独观测同步高度差；不跨网络比较，也不评审双 Explorer 环境兼容性、通用 HTTP 契约、分页和排序 | 主网与测试网的 `GET /api/v1/blocks`、`GET /api/v1/blocks/:height`，以及同网络 CKB RPC `get_tip_header`、`get_block_by_number` 与 `get_block_economic_state` | 每个网络内的 API/RPC 链身份、同步高度差、区块高度、哈希、时间戳、交易数量，以及派生字段的计算证据与差异 | `suites/ckb-explorer-api-rpc-correctness/reviews/chain-data/v1-blocks-index.md` |
