# V2 Bitcoin 原始交易批量查询正确性用例评审

评审范围：按 txid 批量查询 Bitcoin 原始交易，并与 CKB 网络所对应的 Bitcoin mainnet 或 signet/testnet RPC 核对
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：批量代理 Bitcoin RPC `getrawtransaction(txid, 2)`，并按成功返回的 txid 组织结果。
- 输入：`POST /api/v2/bitcoin_transactions`，请求字段 `txids`；主网使用 Bitcoin mainnet，测试网按配置优先 signet 并对缺失结果回退备用节点。
- 成功结果：响应对象只包含成功取得的交易，每个键是交易自身 txid，每个值是对应 Bitcoin JSON-RPC 完整结果。
- 失败结果：单项 Bitcoin RPC 错误从结果中省略；整批调用抛出异常时返回空对象和 404。
- 不负责：RGB++ 关联、CKB 交易字段、Bitcoin mempool 接纳策略、缓存命中细节和通用 HTTP 响应头。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `BTC-QUERY-RPC-01` | - [x] 在主网或测试网提交一个可由对应 Bitcoin RPC 以 verbosity 2 查询的 txid | 响应仅含该 txid 键，JSON-RPC `result.txid` 与请求一致，区块身份、确认数、vin、vout、金额和脚本等返回字段与同网络 RPC 完全一致 | 查询到错误 Bitcoin 网络、错误交易或使用非 verbose 原始格式 | P0 |
| `BTC-QUERY-RPC-02` | - [x] 一次提交多个均可查询且分属不同区块或确认状态的 txid | 响应成员集合与请求 txid 集合一致，每个键关联自己的 RPC 结果；响应对象键顺序不作为正确性条件 | 批量索引错位、遗漏、重复或把一笔交易内容写到另一 txid 下 | P0 |
| `BTC-QUERY-RPC-03` | - [x] 同一批请求包含可查询 txid、未知 txid 和返回单项 RPC error 的 txid | 所有成功项保持完整返回，未知或 error 项不出现在响应中；失败项不清空成功子集 | 批量部分失败被提升为整批失败，或错误对象被当成正常交易返回 | P1 |
| `BTC-QUERY-RPC-04` | - [x] 同一 txid 在请求数组中重复出现 | 响应中该 txid 只出现一个键，内容仍与 Bitcoin RPC 的唯一交易结果一致 | 重复请求产生重复业务对象或不一致副本 | P2 |
| `BTC-QUERY-RPC-05` | - [x] 测试网查询中 signet 节点返回部分交易，剩余 txid 只可由配置的备用 Bitcoin 节点取得 | 响应合并两个节点的成功结果，每个请求 txid 至多出现一次，signet 已返回项不被备用结果错误覆盖 | 跨节点回退漏项、重复项或混入与配置网络不符的数据 | P1 |
| `BTC-QUERY-RPC-06` | - [x] Bitcoin RPC 对批内所有 txid 都返回单项 error，但批调用本身正常完成 | 响应为空对象且请求成功完成，不产生伪造交易结果 | 全部未命中被错误包装为任意一笔交易或不可区分的内部异常 | P1 |
| `BTC-QUERY-RPC-07` | - [ ] 批量 Bitcoin RPC 调用发生传输异常、响应无法解析或返回非预期顶层结构 | API 返回 404 和空 JSON 对象，不返回之前未确认完整的部分结果 | 上游整批失败时泄漏陈旧或半成品交易数据 | P1 |
| `BTC-QUERY-RPC-08` | - [x] 请求省略 `txids` 或提交不能作为 txid 数组处理的值 | API 按当前错误边界返回 404 和空 JSON 对象，不把无效参数转发成正常 Bitcoin 查询 | 参数错误触发不稳定响应或错误命中缓存键 | P1 |
| `BTC-QUERY-RPC-09` | - [x] 正确性测试用于独立复核的 Bitcoin RPC 暂时不可用，但 Explorer API 已返回结果 | 仅将该网络本次 oracle 标记为不可用，不据此判定 API 原始交易不匹配；另一网络独立执行 | 外部节点故障制造错误回归结论或跨网络连带失败 | P1 |

## 本轮需要确认

- 无；单项错误省略、整批异常返回 404 空对象及测试网回退均由当前实现明确规定。
