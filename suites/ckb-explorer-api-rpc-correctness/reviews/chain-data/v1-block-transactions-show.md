# V1 区块交易列表 RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 为事实基准，核对 `GET /api/v1/block_transactions/:block_hash` 返回的区块交易集合、链上顺序、可验证摘要字段以及 `tx_hash`、`address_hash` 过滤语义
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 `0x` 前缀规范链区块哈希返回该区块的交易摘要列表，并可按交易哈希或链上地址进一步过滤；本评审只判断 Explorer 结果是否与同一 CKB 网络一致，并要求主网、测试网各自产生独立结论。
- 公开主网：Explorer `https://mainnet-api.explorer.nervos.org/api`；CKB RPC `https://mainnet.ckbapp.dev/`。
- 公开测试网：Explorer `https://testnet-api.explorer.nervos.org/api`；CKB RPC `https://testnet.ckbapp.dev/`。
- 输入：每个网络分别调用 Explorer `GET /api/v1/block_transactions/:block_hash`，并按用例附加 `tx_hash`、`address_hash`；RPC 使用 `get_tip_header`、`get_block_by_number`、`get_block` 和 `get_transaction` 取得区块、当前交易及输入引用的上一笔交易。
- 取样：每个网络先用高度 0 的哈希校验 Explorer/RPC 链身份；分别选择仅含 Cellbase、含普通交易、地址参与关系可由 Lock Script 推导以及普通交易输入或输出超过 10 项的已确认区块。分页仅用于收集完整结果，不评审分页协议本身；比较期间若同一高度的 RPC 哈希改变，则该网络本次样本按重组处理，不作数据正确性结论。
- 成功结果：Explorer 交易集合、链上顺序、区块上下文和过滤结果与同网络 RPC 精确一致；RPC 十六进制整数无损转换后比较，容量和占用容量均以 Shannon 整数核对，地址按主网或测试网规则从 Lock Script 编码。
- 失败结果：指出网络、区块高度与哈希、过滤条件、交易哈希、字段路径、API 值、RPC 原值、转换或推导后的期望值及差异；单个公开 URL 超时、返回错误、缺少目标区块或输入引用交易时，只将该网络标记为事实基准不可用，不影响另一网络的结论，也不把它判成 API 数据错误。
- 不负责：双 Explorer 环境兼容性、媒体类型、JSON:API 本地 `id` 与标量格式、错误响应、分页规则、缓存、`created_at`、`create_timestamp`、`income`、Cell 状态与消费交易反向索引，以及 RGB/Bitcoin/UDT/DAO 等扩展注解；这些行为由通用契约或对应领域评审负责。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `BLOCK-TXS-RPC-01` | 在公开主网和测试网分别选择一个仅含 Cellbase 的已确认区块和一个含普通交易的已确认区块，以 RPC 区块哈希查询全部交易 | 每个网络、每个样本的 API `transaction_hash` 序列与 RPC `transactions` 哈希序列完全相同且顺序一致，`meta.total` 等于 RPC 交易数量，没有遗漏或重复 | 区块交易漏同步、重复、关联到其他区块或按数据库主键而非链上索引排序 | P0 |
| `BLOCK-TXS-RPC-02` | 在公开主网和测试网分别核对同一区块返回的每一条交易摘要所带区块上下文 | 每条记录的 `block_number` 和 `block_timestamp` 分别等于 RPC `header.number`、`header.timestamp` 的十六进制解码值，且所有记录均属于请求的区块 | 交易摘要串入其他区块，或区块高度、时间戳进制和持久化值错误 | P0 |
| `BLOCK-TXS-RPC-03` | 在公开主网和测试网分别核对仅含 Cellbase 与含普通交易区块的 Cellbase 标识及特殊输入预览 | RPC 第一笔交易对应的 API 记录是列表首项且仅该项 `is_cellbase` 为 `true`；其 `display_inputs` 仅有一项，`from_cellbase` 为 `true` 且 `generated_tx_hash` 等于 Cellbase 交易哈希，其余交易 `is_cellbase` 为 `false` | Cellbase 被漏标、重复标记、排到普通交易之后或套用普通输入引用逻辑 | P0 |
| `BLOCK-TXS-RPC-04` | 在公开主网和测试网分别选择输入输出数量不同的普通交易，并同时核对同区块 Cellbase 的输入输出计数 | Cellbase 的 `display_inputs_count` 为 `1`，普通交易的 `display_inputs_count` 等于 RPC `inputs` 长度；每笔交易的 `display_outputs_count` 等于 RPC `outputs` 长度 | Cellbase 输入计数错误，或普通交易输入输出被遗漏、重复及混用预览数量 | P0 |
| `BLOCK-TXS-RPC-05` | 在公开主网和测试网分别选择至少含一个普通输入的交易，用 RPC 输入引用定位上一笔交易输出并核对输入预览 | `display_inputs` 按 RPC 输入顺序返回前 `min(10, inputs_count)` 项；每项 `from_cellbase` 为 `false`，`generated_tx_hash`、`cell_index`、`since.raw`、`capacity`、`occupied_capacity`、`address_hash` 和存在时的 `type_script` 分别等于引用输出及输入的可验证值，容量按 Shannon 整数比较 | 输入预览乱序、指向错误上一输出、since 错位、容量或 Script 字节计算错误、地址按错误网络编码 | P1 |
| `BLOCK-TXS-RPC-06` | 在公开主网和测试网分别核对 Cellbase 与普通交易的输出预览 | 每笔交易的 `display_outputs` 按 RPC 输出索引顺序返回可展示项；每项 `generated_tx_hash` 等于当前交易哈希，`cell_index`、`capacity`、`occupied_capacity`、`address_hash` 和存在时的 `type_script` 分别等于 RPC 输出或其确定推导值，容量按 Shannon 整数比较 | 输出预览乱序、关联到错误交易、容量或 Script 字节计算错误、地址按错误网络编码 | P1 |
| `BLOCK-TXS-RPC-07` | 在公开主网和测试网分别选择普通交易输入或输出超过 10 项的已确认区块 | 对超过 10 项的一侧，完整 `display_inputs_count` 或 `display_outputs_count` 仍等于 RPC 总数，预览数组恰好包含链上顺序的前 10 项；未超过 10 项的一侧完整返回 | 预览截断导致总数被改写、返回任意 10 项、边界多一项或少一项 | P1 |
| `BLOCK-TXS-RPC-08` | 在公开主网和测试网分别从目标区块 RPC 交易中选择一个哈希作为 `tx_hash` 过滤条件 | API 仅返回该区块中哈希完全相同的一笔交易，`meta.total` 为 `1`，其摘要与未过滤列表中的同一交易一致 | 交易哈希过滤失效、跨区块命中、返回多条记录或改变摘要内容 | P1 |
| `BLOCK-TXS-RPC-09` | 在公开主网和测试网分别使用另一个规范链区块中的有效交易哈希过滤目标区块 | API `data` 为空且 `meta.total` 为 `0`，不会因为交易哈希在全链存在而把其他区块的交易返回 | 过滤条件绕过区块范围，导致跨区块交易泄漏到结果 | P1 |
| `BLOCK-TXS-RPC-10` | 在公开主网和测试网分别从目标区块 RPC 输出 Lock Script 推导一个参与地址，并以该地址过滤区块交易 | API 返回的交易哈希集合等于该区块中任一输入引用输出或当前输出属于该地址的 RPC 交易集合，每笔只出现一次并保持原链上顺序，`meta.total` 等于该集合大小 | 地址关联漏建、只识别输入或输出、重复返回同一交易、串入其他地址或排序改变 | P1 |
| `BLOCK-TXS-RPC-11` | 在公开主网和测试网分别选择一个 Explorer 已知但未参与目标区块的有效链上地址过滤该区块 | API `data` 为空且 `meta.total` 为 `0`，不会因为地址在全链存在而返回该地址的其他区块交易 | 地址过滤绕过区块范围或把全链地址交易混入区块结果 | P1 |
| `BLOCK-TXS-RPC-12` | 在公开主网和测试网分别同时传入 `tx_hash` 与 `address_hash`，覆盖交易确实涉及该地址和交易不涉及该地址两种组合 | 两个过滤条件按交集生效：匹配组合仅返回该笔交易且 `meta.total` 为 `1`，不匹配组合返回空数组且 `meta.total` 为 `0` | 组合过滤只应用一个条件、按并集返回或因条件顺序产生不同结果 | P1 |

## 本轮需要确认

- 请确认 `BLOCK-TXS-RPC-01` 至 `BLOCK-TXS-RPC-12` 的场景、预期结果和优先级可作为后续自动化依据。
- 请确认 `BLOCK-TXS-RPC-07` 在某个公开网络的近期窗口没有超过 10 项的样本时，该网络将报告事实基准样本不可用，而不会用未触发边界的交易代替。
- 无其他待确认的产品行为；错误契约、分页、缓存、数据库本地字段和扩展协议注解继续由相邻评审覆盖，不在本表重复。
