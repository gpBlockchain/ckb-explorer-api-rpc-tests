# V1 交易详情 RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 为事实基准，核对 `GET /api/v1/transactions/:id` 对已提交普通交易和 Cellbase 返回的原始结构、区块归属、Cells 展示开关及可由链数据确定推导的详情字段
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按交易哈希返回单笔 CKB 交易详情；本评审只判断已提交普通交易和 Cellbase 的链上字段是否与同网络 RPC 一致，并要求主网、测试网各自产生独立结论。
- 公开主网：Explorer `https://mainnet-api.explorer.nervos.org/api`；CKB RPC `https://mainnet.ckbapp.dev/`。
- 公开测试网：Explorer `https://testnet-api.explorer.nervos.org/api`；CKB RPC `https://testnet.ckbapp.dev/`。
- 输入：每个网络分别以规范链交易哈希调用 Explorer `GET /api/v1/transactions/:id`，并按用例省略 `display_cells` 或传入 `true`、`false`；RPC 使用 `get_transaction` 的结构化与 `0x0` 序列化结果、`get_block` 及输入引用的上一笔交易。
- 取样：每个网络先用高度 0 的哈希校验 Explorer/RPC 链身份，并确认 Explorer tip 不高于 RPC 且最多落后 5 个区块；普通样本覆盖非空 witnesses、Cell Dependencies、Header Dependencies、类型脚本、多个输入输出、非零交易费和 cycles，边界样本至少一侧超过 10 个 Cells；Cellbase 使用至少落后 tip `proposal_window + 1` 个区块的非创世样本。比较期间若交易状态、所属区块哈希或同高度 RPC 区块哈希改变，则该网络本次样本按状态变化或重组处理，不作数据正确性结论。
- 成功结果：RPC 十六进制整数无损转换后，交易身份、原始向量、区块字段和 Cells 顺序与 Explorer 一致；容量、费用、占用容量和序列化大小均以整数精确推导，地址按对应网络编码，默认详情不截断 Cells，`display_cells=false` 只关闭两个 Cells 数组。
- 失败结果：指出网络、交易哈希、RPC 状态与区块哈希、字段路径、API 值、RPC 原值及转换或推导后的期望值；单个公开 URL 超时、RPC 缺少交易、上一笔交易或区块时，只将该网络标记为事实基准不可用，不影响另一网络的结论。
- 不负责：双 Explorer 环境兼容性、媒体类型和错误响应、待处理/提案中/拒绝交易及 `detailed_message`、本地 JSON:API `id`、`income`、全局与 Epoch 大小/cycles 极值、Cells 的数据库状态与消费交易、Median Time、标签、Cell 类型、Dependency Script 识别及 RGB/Bitcoin/UDT/DAO/NFT/Fiber 等协议扩展注解；这些行为由通用契约、待处理交易、统计或协议专项评审负责。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `TX-DETAIL-RPC-01` | 在公开主网和测试网分别以一笔稳定的普通已提交交易哈希查询详情，并取得同网络 RPC 交易及所属区块 | `transaction_hash` 等于 RPC `transaction.hash`，`tx_status` 为 `committed`，`is_cellbase` 为 `false`，`block_number` 等于 RPC 状态区块高度，`block_timestamp` 等于所属 RPC 区块时间戳，`version` 等于 RPC 版本的十进制值，且 RPC 状态区块哈希与所属区块哈希一致 | 返回错误交易、把普通交易标成 Cellbase、状态陈旧、关联错误区块或高度、时间戳、版本进制错误 | P0 |
| `TX-DETAIL-RPC-02` | 在公开主网和测试网分别选择具有非空 witnesses、Cell Dependencies 和 Header Dependencies 的普通已提交交易查询详情 | `witnesses` 和 `header_deps` 分别与 RPC 同名数组逐项同序相等；`cell_deps` 数量和顺序与 RPC 一致，每项 `dep_type`、Out Point 交易哈希及解码后的输出索引一致 | Witness、Header Dependency 或 Cell Dependency 遗漏、重复、乱序或关联到错误 Out Point | P0 |
| `TX-DETAIL-RPC-03` | 在公开主网和测试网分别选择含多个普通输入、且引用输出同时覆盖无 Type Script 和有 Type Script 的已提交交易 | 默认 `display_inputs` 与 RPC `inputs` 等长同序；每项 `from_cellbase` 为 `false`，引用交易哈希、输出索引和 `since.raw` 对应 RPC 输入，`capacity`、`occupied_capacity`、网络地址及存在时的 `type_script` 对应被引用的 RPC 输出 | 输入被截断或乱序、引用解析和 Since 错误、容量或占用容量精度丢失、地址跨网络编码或 Type Script 错位 | P0 |
| `TX-DETAIL-RPC-04` | 在公开主网和测试网分别选择含多个普通输出、且同时覆盖无 Type Script 和有 Type Script 的已提交交易 | 默认 `display_outputs` 与 RPC `outputs` 等长并按输出索引排列；每项 `generated_tx_hash` 等于当前交易哈希，`cell_index`、`capacity`、`occupied_capacity`、网络地址及存在时的 `type_script` 对应同索引 RPC 输出和 `outputs_data` | 输出被截断、遗漏、重复或乱序，交易归属、容量、数据占用、地址网络或 Type Script 映射错误 | P0 |
| `TX-DETAIL-RPC-05` | 在公开主网和测试网分别选择输入或输出数量超过 10 的普通已提交交易，以默认参数查询详情 | `display_inputs` 和 `display_outputs` 分别返回全部 RPC 输入和输出而不是只返回前 10 项；数组长度等于 RPC 长度，最后一项仍对应最后一个 RPC 输入引用或输出索引 | 详情端点误用列表预览上限，导致第 11 项及后续 Cells 静默丢失 | P1 |
| `TX-DETAIL-RPC-06` | 在公开主网和测试网分别对同一普通已提交交易省略 `display_cells`、传入 `true` 和传入 `false` | 省略参数与 `display_cells=true` 返回相同的完整 `display_inputs`、`display_outputs`；`display_cells=false` 令两个数组都为空，交易哈希、状态、区块字段和原始交易向量保持不变 | 布尔开关含义反转、只关闭一侧 Cells、默认错误关闭 Cells 或连带删除非 Cells 字段 | P1 |
| `TX-DETAIL-RPC-07` | 在公开主网和测试网分别选择至少含一个输入且交易费非零的普通已提交交易 | `transaction_fee` 等于所有输入引用的上一笔 RPC 输出容量总和减去当前 RPC 输出容量总和，结果按 Shannon 整数精确比较且不使用浮点数 | 输入或输出容量漏算、正负方向反转、CKB/Shannon 单位混用或大整数精度丢失 | P0 |
| `TX-DETAIL-RPC-08` | 在公开主网和测试网分别取得普通交易和 Cellbase 的 RPC `get_transaction` `0x0` 序列化结果 | `bytes` 等于 RPC 序列化交易十六进制负载的字节数再加 4 字节长度前缀；普通交易和 Cellbase 均精确一致 | 使用 JSON 文本长度、漏算长度前缀、十六进制字符数误当字节数或异步回填错误 | P1 |
| `TX-DETAIL-RPC-09` | 在公开主网和测试网分别选择 RPC 返回非零 cycles 的普通已提交交易 | `cycles` 等于 RPC `get_transaction` 返回的十六进制 cycles 解码值，使用整数精确比较 | cycles 关联到同区块其他交易、遗漏更新、十六进制转换或大整数精度错误 | P1 |
| `TX-DETAIL-RPC-10` | 在公开主网和测试网分别选择一个非创世、已确认的 Cellbase 交易查询详情 | `transaction_hash` 等于 RPC Cellbase 哈希，`tx_status` 为 `committed`，`is_cellbase` 为 `true`，`transaction_fee` 为 `0`，`cycles` 与 RPC 一样为空；`display_inputs` 仅有一项且 `from_cellbase` 为 `true`、`generated_tx_hash` 等于当前交易哈希、`target_block_number` 等于所属区块高度减 `proposal_window + 1`，`display_outputs` 数量等于 RPC 输出数量 | Cellbase 被当作普通交易解析、虚构输入引用或手续费/cycles，目标奖励区块偏移错误，或 Cellbase 输出遗漏 | P0 |

## 本轮需要确认

- 无；10 条用例及范围排除项均已确认，本轮只核对标准 CKB RPC 可直接取得或确定推导的字段。
