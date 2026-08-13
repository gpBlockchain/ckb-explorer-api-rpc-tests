# 测试领域与评审文档

目标源码：`https://github.com/nervosnetwork/ckb-explorer.git`，当前分析版本 `develop@0495ecd00a839f7618bad752f5ad92071124a991`。
执行方式：兼容性套件向基准环境和候选环境发送同一确定性请求，比较可观察的 HTTP 行为；机器可执行的 153 条路由清单保存在套件配置中，不在评审文档重复维护。

| 测试领域 | 责任与边界 | 入口 | 可观察结果 | 评审文档 |
| --- | --- | --- | --- | --- |
| HTTP API 通用契约 | 比较所有接口共有的路由、媒体类型、错误、分页、CSV、缓存和差异报告规则；不判断具体业务数据是否正确 | `/api/v1/*`、`/api/v2/*`、基准与候选 URL | 状态、选定响应头、数据类型和值、顺序、分页、逐字段差异 | `suites/ckb-explorer-api-rpc-compatibility/reviews/http-api-contract.md` |
