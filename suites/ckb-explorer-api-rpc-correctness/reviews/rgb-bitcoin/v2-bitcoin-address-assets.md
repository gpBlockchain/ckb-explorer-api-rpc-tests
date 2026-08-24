# V2 Bitcoin 地址关联 RGB 资产正确性用例评审

评审范围：核对 Bitcoin 地址映射的 RGB Live Cells、绑定状态、Cell 详情和已发布 UDT 余额，并核对按 RGB++ code hash 查询的全局 Live Cell outpoints
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：将 Bitcoin 地址解析到一个或多个 CKB 地址，返回其 live RGB Cell 计数、按 Bitcoin outpoint 分组的 Cells 和 UDT 账户；另提供按 RGB++ Lock code hash 查询 bound live cells 的入口。
- 输入：`GET /api/v2/bitcoin_addresses/:id`、`GET /api/v2/bitcoin_addresses/:id/rgb_cells`、`GET /api/v2/bitcoin_addresses/:id/udt_accounts`、`GET /api/v2/rgb_live_cells`，参数 `page`、`page_size`、`code_hash`；事实基准为同网络 CKB RPC/Indexer、Bitcoin RPC 和 RGB++ Lock args/outpoint 映射。
- 成功结果：仅统计或返回符合 Cell live 状态、Bitcoin vout 状态和代币发布条件的记录；容量使用 Shannon 整数，UDT amount 使用链上整数原始单位。
- 失败结果：合法但未映射的 Bitcoin 地址返回零计数或空集合；非法地址的稳定错误契约待确认；独立上游不可用时不作数据错误结论。
- 不负责：普通 Bitcoin 余额、已消费 CKB Cells、未发布代币元数据真伪、RGB 交易摘要、全局统计和通用分页错误格式。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `BTC-ADDR-RPC-01` | 一个合法 Bitcoin 地址映射到一个或多个 CKB 地址，关联 vout 同时包含 bound、unbound、binding、normal 状态及 live/dead Cell | 地址详情的 `bound_live_cells_count` 只计 bound 且 live 的 Cell，`unbound_live_cells_count` 只计 unbound 且 live 的 Cell；binding、normal 和非 live Cell 均不计入，多个映射 CKB 地址的计数正确合并 | 状态过滤错误、dead Cell 被当作持仓或多映射地址漏计/重复 | P0 |
| `BTC-ADDR-RPC-02` | 合法 Bitcoin 地址没有任何 CKB 地址映射，或映射地址当前没有符合条件的 Cell | 地址详情返回两个计数均为 0，`rgb_cells` 返回空分组且 total 为 0，`udt_accounts` 返回空数组 | 空持仓被报错、返回陈旧资产或把不存在的映射当成一个 Cell | P1 |
| `BTC-ADDR-RPC-03` | 同一 Bitcoin 交易 outpoint 通过多个映射记录关联多个 live CKB Cells，请求该地址的 `rgb_cells` | 响应以 Bitcoin `txid` 和 vout index 为一个分组，分组内 Cell 集合与 CKB RPC/Indexer 的 live 关联 Cells 完全一致；同一 outpoint 只计一个分页成员 | 同一 Bitcoin outpoint 被拆成重复行，或跨 outpoint 合并 Cells | P0 |
| `BTC-ADDR-RPC-04` | 核对 `rgb_cells` 中每个 live Cell 的链上详情 | `tx_hash`、`cell_index`、区块高度/时间、capacity、occupied capacity、Lock/Type Script、Output Data、type hash、cell type、tags 和可链上推导的 extra info 与同网络 RPC 精确一致，所有整数无浮点转换 | RGB Cell 指向错误 CKB outpoint、脚本或数据，或容量单位和精度错误 | P0 |
| `BTC-ADDR-RPC-05` | 对稳定的 Bitcoin outpoint 分组集合请求相邻页及不同合法 `page_size` | 各页分组连续且无重复，`meta.total` 等于去重后的 Bitcoin outpoint 数而不是 Cell 数，`meta.page_size` 等于请求页容量 | 按 Cell 而非 outpoint 计页导致分页总数和成员错乱 | P1 |
| `BTC-ADDR-RPC-06` | 映射 CKB 地址持有多个 live `udt`、`xudt`、`xudt_compatible` Cells，包含相同 type hash 多 Cell、不同 cell type、已发布和未发布 UDT，以及 unbound、binding、bound vout | `udt_accounts` 按 `(cell_type,type_hash)` 聚合 amount，只返回已发布 UDT，并排除 unbound 与 binding vout；每项 symbol、decimal、type hash、类型脚本和图标来自对应发布记录，amount 等于符合条件 live Cells 的链上整数金额之和 | 不同代币或类型合并、未发布资产泄漏、未绑定资产提前计入或余额重复 | P0 |
| `BTC-ADDR-RPC-07` | 某个符合条件 UDT 的单 Cell amount 或聚合总额超过 `2^53` | 返回 amount 以整数原始单位与 CKB Cell Data 解码总和完全一致，低位不因浮点转换丢失，且不使用代币 decimal 缩放后比较 | 大额 UDT 余额被静默舍入并影响持仓显示 | P0 |
| `BTC-ADDR-RPC-08` | 使用当前网络配置内合法 RGB++ Lock code hash 请求 `rgb_live_cells` | 结果只包含使用该 code hash、hash type 为协议要求、Bitcoin vout 为 bound、非 OP_RETURN 且 CKB Cell 为 live 的 outpoints；每项 `tx_hash/cell_index` 与 CKB RPC 一致 | 非 RGB++、未绑定、OP_RETURN 或 dead Cell 混入 Live Cell 集合 | P0 |
| `BTC-ADDR-RPC-09` | 对稳定的合法 code hash Live Cell 集合请求相邻页、较大合法 `page_size` 及末页 | 页成员无重复或遗漏，`meta.total` 等于全部符合条件 Cells，页大小最多按接口上限 1000 执行 | 大页绕过上限、分页漏项或总数采用未过滤集合 | P1 |
| `BTC-ADDR-RPC-10` | `rgb_live_cells` 的 `code_hash` 缺失或不属于当前网络配置的 RGB++ code hashes | 返回空 `cells`、`meta.total=0` 和当前页大小，不回退为全量查询 | 无效 code hash 意外暴露全部 RGB Cells 或跨网络脚本数据 | P1 |
| `BTC-ADDR-RPC-11` | 对三个 Bitcoin 地址接口提交既不是合法 Bitcoin 地址、CKB 地址也不是 Lock Hash 的 `:id` | 待确认：应返回哪一种稳定客户端错误或空结果契约；三个入口应保持一致，不暴露未处理的空对象方法异常 | 非法地址在相邻接口产生互相矛盾结果或服务端异常 | P1 |
| `BTC-ADDR-RPC-12` | 正确性核对期间 CKB RPC/Indexer、Bitcoin RPC 或地址映射事实基准缺少目标 outpoint，或观察到 CKB 重组 | 仅将受影响网络和样本标记为 oracle 不可用，不把事实基准缺失判为 API Cell/余额不匹配 | 上游裁剪、重组或映射延迟制造错误回归结论 | P1 |

## 本轮需要确认

- `BTC-ADDR-RPC-11`：非法 `:id` 在三个 Bitcoin 地址入口应统一采用哪一种状态和错误/空结果结构。
- 其余成员、状态、分组与 amount 语义由当前查询条件和序列化器明确规定。
