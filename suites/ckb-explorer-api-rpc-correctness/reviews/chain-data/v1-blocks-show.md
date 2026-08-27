# V1 区块详情 RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 为事实基准，核对 `GET /api/v1/blocks/:id` 的高度/哈希查询语义及全部可由链数据或确定公式验证的详情字段
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按十进制区块高度或 `0x` 前缀区块哈希返回一个规范链区块的详情；本评审只判断 Explorer 详情值是否与同一 CKB 网络一致，并要求主网、测试网各自产生独立结论。
- 公开主网：Explorer `https://mainnet-api.explorer.nervos.org/api`；CKB RPC `https://mainnet.ckbapp.dev/`。
- 公开测试网：Explorer `https://testnet-api.explorer.nervos.org/api`；CKB RPC `https://testnet.ckbapp.dev/`。
- 输入：每个网络分别调用 Explorer `GET /api/v1/blocks/:height` 和 `GET /api/v1/blocks/:block_hash`；RPC 使用 `get_tip_header`、`get_block_by_number`、`get_block`、`get_block_economic_state` 及必要的 Epoch/共识参数查询。
- 取样：每个网络先用高度 0 的哈希校验 Explorer/RPC 链身份；普通字段选取双方均已取得的已确认区块，计数、叔块、费用、大小和 cycles 使用能实际触发对应行为的样本，奖励使用成熟区块与仍在 `proposal_window` 内的区块。比较期间若同一高度的 RPC 哈希改变，则该网络本次样本按重组处理，不作数据正确性结论。
- 成功结果：RPC 十六进制整数无损转换为十进制后，直接字段与 Explorer 精确一致；Epoch、难度、容量、费用、奖励、大小和 cycles 按源码采用的确定公式计算，所有金额均以 Shannon 整数比较。
- 失败结果：指出网络、查询方式、区块高度与哈希、API 值、RPC 原值、转换或计算后的期望值及差异字段；单个公开 URL 超时、返回错误、缺少目标区块或缺少所需 RPC 扩展结果时，只将该网络标记为事实基准不可用，不影响另一网络的结论，也不把它判成 API 数据错误。
- 不负责：双 Explorer 环境兼容性、媒体类型、JSON:API 本地 `id` 与标量类型、格式错误或不存在的 `:id` 错误契约、分页、缓存、CSV、区块列表排序及区块交易列表；这些 HTTP 行为由兼容性评审负责。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `BLOCK-DETAIL-RPC-01` | - [x] 在公开主网和测试网分别选取同一已确认区块，先以十进制高度、再以同网络 RPC 返回的区块哈希查询详情 | 每个网络内两次查询返回完全相同的 `attributes`；`number` 与 RPC 高度一致，`block_hash` 与 RPC `header.hash` 一致 | 高度和哈希走到不同记录、缓存键串扰或详情指向非规范区块 | P0 |
| `BLOCK-DETAIL-RPC-02` | - [x] 在公开主网和测试网分别对同一已确认区块核对详情中的直接区块头字段 | 每个网络的 `timestamp`、`version`、`nonce` 和 `transactions_root` 分别等于同网络 RPC `header` 对应值，十六进制整数无损转为十进制 | 区块头字段错位、进制或精度转换错误、交易根关联错误 | P0 |
| `BLOCK-DETAIL-RPC-03` | - [x] 在公开主网和测试网分别解码同一已确认区块的 RPC `header.epoch` | 每个网络的 `epoch`、`block_index_in_epoch` 和 `length` 等于紧凑 Epoch 字段解码值，`start_number = number - block_index_in_epoch` | Epoch 位段、区块索引或起始高度计算错误 | P0 |
| `BLOCK-DETAIL-RPC-04` | - [x] 在公开主网和测试网分别用 RPC `header.compact_target` 计算同一区块难度 | 每个网络的 `difficulty` 等于 compact target 展开后按 CKB 难度规则得到的整数，计算全程不使用浮点数 | compact target 解析、舍入或大整数精度错误导致难度失真 | P1 |
| `BLOCK-DETAIL-RPC-05` | - [x] 在公开主网和测试网分别选择包含 Cellbase 和普通交易的已确认区块核对交易数量 | 每个网络的 `transactions_count` 等于 RPC `transactions` 数组长度，Cellbase 计入且每笔交易只计一次 | 交易漏同步、重复入库或错误排除 Cellbase | P0 |
| `BLOCK-DETAIL-RPC-06` | - [x] 在公开主网和测试网分别选择 proposals 非空的已确认区块核对提案数量 | 每个网络的 `proposals_count` 等于 RPC `proposals` 数组长度 | 提案漏同步、重复计数或读取了错误区块的提案 | P1 |
| `BLOCK-DETAIL-RPC-07` | - [x] 在公开主网和测试网分别选择含叔块与不含叔块的已确认区块核对叔块信息 | 含叔块时 `uncles_count` 等于 RPC `uncles` 长度且 `uncle_block_hashes` 按 RPC 顺序列出全部叔块头哈希；无叔块时计数为 `0` 且哈希列表为 `null` | 叔块漏记、重复、顺序或哈希关联错误，以及空值语义漂移 | P1 |
| `BLOCK-DETAIL-RPC-08` | - [x] 在公开主网和测试网分别选择 Cellbase witness 非空的已确认区块核对矿工字段 | 解码 RPC 第一笔交易首个 witness 后，Lock Script 按对应网络编码的地址等于 `miner_hash`，消息原始字节的 `0x` 十六进制表示等于 `miner_message` | Cellbase witness 偏移解析、网络地址编码或矿工消息截取错误 | P1 |
| `BLOCK-DETAIL-RPC-09` | - [x] 在公开主网和测试网分别对含多个输出的已确认区块汇总所有 RPC 交易输出容量 | 每个网络的 `total_cell_capacity` 等于区块内所有输出 `capacity` 的 Shannon 整数总和，包括 Cellbase 输出 | 输出遗漏、重复或容量进制/精度错误导致区块总容量失真 | P1 |
| `BLOCK-DETAIL-RPC-10` | - [x] 在公开主网和测试网分别对包含不同 Lock Script、Type Script 和 data 长度输出的已确认区块计算 Cell 最小占用容量 | 每个网络的 `cell_consumed` 等于所有输出按 CKB 最小占用容量规则计算后的 Shannon 整数总和 | Script 或 data 字节数计算错误导致区块 Cell 占用量失真 | P1 |
| `BLOCK-DETAIL-RPC-11` | - [x] 在公开主网和测试网分别选择 RPC `get_block_economic_state` 已可用且 `txs_fee` 非零的成熟区块 | 每个网络的 `total_transaction_fee` 等于 RPC `txs_fee` 的十六进制解码值，以 Shannon 整数精确比较 | 普通交易或 DAO 交易费用漏算、重复计算或精度错误 | P0 |
| `BLOCK-DETAIL-RPC-12` | - [x] 在公开主网和测试网分别选择至少落后各自 tip `proposal_window + 1` 个区块且经济状态可用的成熟区块 | `reward_status` 为 `issued`，`reward = primary + secondary`；`received_tx_fee_status` 为 `calculated`，`received_tx_fee = proposal + committed`；`miner_reward` 等于上述四项之和，均与同网络 RPC `miner_reward` 精确一致 | 奖励成熟状态未更新、发行或费用分成遗漏、矿工总收益计算错误 | P0 |
| `BLOCK-DETAIL-RPC-13` | - [x] 在公开主网和测试网分别选择仍处于各自 tip `proposal_window` 内、尚无最终经济状态的非创世区块 | `reward_status` 和 `received_tx_fee_status` 均为 `pending`，`received_tx_fee` 为 `0`，`miner_reward = reward`，且 `reward` 等于按该网络 Epoch 奖励、减半规则和区块在 Epoch 中位置计算的基础奖励 | 未成熟区块提前计发费用、状态提前完成或基础奖励计算错误 | P1 |
| `BLOCK-DETAIL-RPC-14` | - [x] 在公开主网和测试网分别查询高度 0 的创世区块详情 | `reward_status` 为 `issued`，`reward`、`received_tx_fee` 和 `miner_reward` 均为 `0`，`received_tx_fee_status` 为 `pending` | 创世区块被错误计发奖励或套用普通区块的费用成熟逻辑 | P2 |
| `BLOCK-DETAIL-RPC-15` | - [x] 在公开主网和测试网分别选择正文非空的已确认区块，按 CKB 序列化规则计算区块大小 | 每个网络的 `size` 等于同一 RPC 区块不包含叔块 proposals 的序列化字节数 | 区块大小遗漏字段、重复计入叔块 proposals 或序列化长度计算错误 | P1 |
| `BLOCK-DETAIL-RPC-16` | - [x] 在公开主网和测试网分别选择包含普通交易且 RPC 支持返回 cycles 的已确认区块 | 每个网络的 `cycles` 等于 RPC cycles 数组中所有非 Cellbase 交易 cycles 的十六进制解码值之和 | Cellbase 错误计入、交易 cycles 漏加或大整数转换错误 | P1 |
| `BLOCK-DETAIL-RPC-17` | - [x] 在公开主网和测试网分别选择一个统计已生成的完整 Epoch，并核对其中任一区块详情的 Epoch 极值 | `largest_block_in_epoch` 等于该 Epoch 全部区块 `size` 最大值，`max_cycles_in_epoch` 等于该 Epoch 全部非空 `cycles` 最大值 | Epoch 统计漏块、跨 Epoch 串值或极值聚合错误 | P2 |
| `BLOCK-DETAIL-RPC-18` | - [x] 在公开主网和测试网分别查询当前尚未结束 Epoch 中的区块详情 | 在完整 Epoch 统计生成前，`largest_block_in_epoch` 和 `max_cycles_in_epoch` 均为 `null`，不会混入上一 Epoch 的统计 | 未完成 Epoch 展示陈旧或跨 Epoch 的极值 | P2 |
| `BLOCK-DETAIL-RPC-19` | - [x] 在公开主网和测试网分别于完整 Epoch 统计生成且缓存刷新后查询不同区块的全链极值字段 | 同一网络各区块返回相同的 `largest_block` 和 `max_cycles`；两者分别等于所有完整 Epoch 的区块大小最大值和区块 cycles 最大值 | 全链极值缓存串网、漏 Epoch、回退或因当前查询区块而变化 | P2 |

## 本轮需要确认

- 请确认 `BLOCK-DETAIL-RPC-01` 至 `BLOCK-DETAIL-RPC-19` 的场景、预期结果和优先级可作为后续自动化依据。
- 无待确认的产品行为；格式错误、不存在资源、媒体类型和 JSON 标量类型继续由 HTTP API 通用契约评审覆盖，不在本表重复。
