# V1 区块列表 RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 为事实基准，核对 `GET /api/v1/blocks` 返回区块的链身份、同步高度和六个列表字段
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：返回近期区块简表；本评审只判断 Explorer 数据是否与同一 CKB 网络的规范链数据一致，并要求主网、测试网各自产生独立结论。
- 公开主网：Explorer `https://mainnet-api.explorer.nervos.org/api`；CKB RPC `https://mainnet.ckbapp.dev/`。
- 公开测试网：Explorer `https://testnet-api.explorer.nervos.org/api`；CKB RPC `https://testnet.ckbapp.dev/`。
- 输入：每个网络分别调用 Explorer `GET /api/v1/blocks`；辅助使用 `GET /api/v1/blocks/:height` 取得列表未暴露的区块哈希；RPC 使用 `get_tip_header`、`get_block_by_number` 和 `get_block_economic_state`。
- 取样：每个网络先记录 API 与 RPC tip；字段核对使用 API 已返回且同网络 RPC 可按同一高度取得的区块，reward 使用至少落后该网络 tip `proposal_window + 1` 个区块的成熟样本。比较期间若同一高度的 RPC 哈希改变，则该网络的本次样本按重组处理，不作数据正确性结论。
- 成功结果：RPC 十六进制整数无损转换为十进制后，区块身份和所有可验证字段与 API 字符串值精确一致；派生字段按源码使用的确定公式计算。
- 失败结果：指出网络、区块高度、API 值、RPC 原值、转换或计算后的期望值及差异字段；单个公开 URL 超时、返回错误或缺少目标高度时，只将该网络标记为事实基准不可用，不影响另一网络的结论，也不把它判成 API 数据错误。
- 不负责：双 Explorer 环境兼容性、媒体类型、分页、排序、缓存、CSV、数据库本地 JSON:API `id`，以及未出现在区块列表中的详情字段。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `BLOCKS-RPC-01` | - [x] 在公开主网对和测试网对开始字段核对前，分别取得 Explorer 高度 0 的区块详情和同网络 RPC 高度 0 的区块 | 每个网络内的创世区块哈希完全相同；一个网络仅在自身通过链身份校验后继续字段比较，另一网络的结果不受影响 | 主网与测试网 URL 配错、交叉配对或连接到其他链而产生错误结论 | P0 |
| `BLOCKS-RPC-02` | - [x] 在公开主网和测试网各自的同一观测窗口内读取 RPC tip 与 Explorer 列表首项高度 | 当 Explorer 不高于同网络 RPC 时允许最多落后 5 个区块，并分别输出带符号的高度差；Explorer 高于 RPC 时标记该网络事实基准落后且不据此判定 API 数据错误 | 任一网络索引停止同步、RPC 节点落后或旧数据被当成当前链数据 | P0 |
| `BLOCKS-RPC-03` | - [x] 在公开主网和测试网分别对 Explorer 返回的已确认区块高度调用同网络 RPC `get_block_by_number` | 每个网络的 API `number` 转为整数后都等于 RPC `header.number` 的十六进制解码值，RPC 返回高度与请求高度一致 | 高度序列写错、十六进制转换错误或列表项对应到错误区块 | P0 |
| `BLOCKS-RPC-04` | - [x] 在公开主网和测试网分别对同一已确认区块比较 Explorer `timestamp` 与同网络 RPC 区块头 | 每个网络的 API 毫秒时间戳都等于 RPC `header.timestamp` 的十六进制解码值 | 时间戳单位、进制或持久化值错误导致区块时间失真 | P0 |
| `BLOCKS-RPC-05` | - [x] 在公开主网和测试网分别对同一已确认高度读取 Explorer 区块详情并取得同网络 RPC 区块 | 每个网络的详情 `block_hash` 都与 RPC `header.hash` 完全相同，证明列表高度指向该网络规范链上的同一区块 | 重组处理、索引映射或数据源错误使同一高度关联到非规范区块 | P0 |
| `BLOCKS-RPC-06` | - [x] 在公开主网和测试网分别对包含 Cellbase 和普通交易的已确认区块比较交易数量 | 每个网络的 API `transactions_count` 都等于 RPC `transactions` 数组长度，Cellbase 计入总数且每笔交易只计一次 | 交易漏同步、重复入库或错误排除 Cellbase | P0 |
| `BLOCKS-RPC-07` | - [x] 在公开主网和测试网分别对包含不同输入输出数量交易的已确认区块核对 `live_cell_changes` | 每个网络的 API 值都等于 `1 + Σ(每笔非 Cellbase 交易的 outputs 数量 - inputs 数量)` | Cellbase、输入或输出计数错误导致 Live Cell 增量失真 | P1 |
| `BLOCKS-RPC-08` | - [x] 在公开主网和测试网分别对 Cellbase witness 非空的已确认区块核对 `miner_hash` | 从同网络 RPC 第一笔交易的首个 witness 解码 Cellbase lock script，按主网或测试网规则生成的地址与对应 API `miner_hash` 完全相同 | witness 解码、Lock Script 提取或网络地址编码错误导致矿工身份错误 | P1 |
| `BLOCKS-RPC-09` | - [x] 在公开主网和测试网分别对至少落后各自 tip `proposal_window + 1` 个区块、且 RPC 已返回经济状态的成熟区块核对 `reward` | 每个网络的 API `reward` 都等于同网络 RPC `miner_reward.primary + miner_reward.secondary`，以 Shannon 整数精确比较 | 奖励成熟状态未更新、主次发行遗漏或金额精度错误 | P0 |
| `BLOCKS-RPC-10` | - [x] 在公开主网和测试网分别对创世区块核对 `reward` | 两个网络的 API `reward` 都为 `0`，且后续区块处理不会把创世区块改写为已发行奖励 | 创世区块被错误计发或延迟改写奖励 | P2 |

## 本轮需要确认

- 无；10 条用例均已确认，主网和测试网的 `MAX_LAG_BLOCKS` 均为 5。
