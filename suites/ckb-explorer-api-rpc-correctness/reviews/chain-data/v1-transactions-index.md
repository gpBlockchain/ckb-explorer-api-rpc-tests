# V1 交易列表 RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 为事实基准，核对不带分页参数的 `GET /api/v1/transactions` 返回的近期普通已提交交易集合、顺序和五个列表字段
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：返回近期 15 笔普通已提交交易的简表；本评审只判断默认列表成员、顺序和链上可推导字段是否与同一 CKB 网络一致，并要求主网、测试网各自产生独立结论。
- 公开主网：Explorer `https://mainnet-api.explorer.nervos.org/api`；CKB RPC `https://mainnet.ckbapp.dev/`。
- 公开测试网：Explorer `https://testnet-api.explorer.nervos.org/api`；CKB RPC `https://testnet.ckbapp.dev/`。
- 输入：每个网络分别调用不带 `page`、`page_size` 的 Explorer `GET /api/v1/transactions`；RPC 使用 `get_tip_header`、`get_block_by_number`、`get_block`、`get_transaction` 取得规范链区块、当前交易及输入引用的上一笔交易。
- 取样：每个网络先用高度 0 的哈希校验 Explorer/RPC 链身份，并确认 Explorer 区块 tip 不高于 RPC 且最多落后 5 个区块；在列表快照稳定时，从对应规范链窗口推导最新普通交易，并确保样本覆盖跨区块交易、同区块多笔普通交易、非零 Live Cell 变化和多个普通输入。比较期间若列表哈希序列变化或同一高度的 RPC 哈希改变，则该网络本次样本按快照变化或重组处理，不作数据正确性结论。
- 成功结果：列表恰好包含 RPC 可确认的最新 15 笔 `committed` 非 Cellbase 交易且无遗漏或重复，按区块时间戳降序、同一区块内交易索引降序排列；RPC 十六进制整数无损转换，容量以 Shannon 整数精确比较。
- 失败结果：指出网络、列表位置、交易哈希、RPC 状态、区块高度与哈希、字段路径、API 值、RPC 原值、转换或推导后的期望值及差异；单个公开 URL 超时、返回错误、缺少区块或输入引用交易时，只将该网络标记为事实基准不可用，不影响另一网络的结论，也不把它判成 API 数据错误。
- 不负责：双 Explorer 环境兼容性、媒体类型、JSON:API 本地 `id` 与标量格式、错误响应、显式分页和 `sort` 参数、缓存时效、交易详情、`POST /api/v1/transactions/query`、待处理交易，以及 RGB/Bitcoin/UDT/DAO 等协议扩展注解；这些行为由通用契约或后续独立评审负责。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `TX-LIST-RPC-01` | - [x] 在公开主网和测试网分别取得稳定的默认交易列表快照，并从同网络 RPC 规范链窗口推导最新普通交易集合 | API 恰好返回 RPC 可确认的最新 15 笔交易；`transaction_hash` 序列没有遗漏或重复，每笔 RPC `tx_status.status` 均为 `committed` 且 `tx_index > 0`，不会包含 Cellbase、待处理、提案中或已拒绝交易 | 最新交易漏同步、重复、混入 Cellbase 或非已提交交易，或长期返回陈旧集合 | P0 |
| `TX-LIST-RPC-02` | - [x] 在公开主网和测试网分别选择同时覆盖跨区块交易和同一区块多笔普通交易的稳定列表快照 | API 交易按 RPC 所属区块 `header.timestamp` 降序排列；同一区块内按 RPC `tx_status.tx_index` 降序排列；来自不同区块且两个排序键都相同的交易不规定相对顺序 | 最新交易顺序反转、同区块交易按链上索引升序或数据库主键/哈希排序，导致时间线错乱 | P0 |
| `TX-LIST-RPC-03` | - [x] 在公开主网和测试网分别对默认列表每笔交易调用 RPC `get_transaction` 并取得其所属区块 | 每行 `transaction_hash` 等于 RPC `transaction.hash`，`block_number` 等于 RPC `tx_status.block_number`，`block_timestamp` 等于所属 RPC 区块 `header.timestamp`，且 RPC 区块哈希与交易状态中的 `block_hash` 一致 | 交易哈希错位、交易关联到错误区块，或区块高度、时间戳进制及持久化值错误 | P0 |
| `TX-LIST-RPC-04` | - [x] 在公开主网和测试网分别核对默认列表中的零变化交易和至少一笔非零变化普通交易 | 每行 `live_cell_changes` 等于对应 RPC 交易 `outputs` 数量减 `inputs` 数量；非零样本保持正负号，Cellbase 的特殊计数规则不会套用到普通交易 | 输入输出漏计、正负号反转、错误加上 Cellbase 基数或所有交易固定显示为零 | P1 |
| `TX-LIST-RPC-05` | - [x] 在公开主网和测试网分别对默认列表中含一个及多个普通输入的交易解析全部 RPC 输入引用 | 每行 `capacity_involved` 等于全部输入引用的上一笔交易对应输出 `capacity` 的 Shannon 整数总和，每个输入按其 `previous_output.index` 恰好计入一次 | 输入引用解析错误、容量遗漏或重复、输出索引错位及大整数精度损失 | P0 |

## 本轮需要确认

- 无；5 条用例均已确认，不同区块且 `block_timestamp`、`tx_index` 两个排序键都相同时不约束相对顺序。
