# V2 原始交易与 CKB 容量变更明细 RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 为事实基准，核对 `GET /api/v2/transactions/:id/raw` 的原始交易结构和 `GET /api/v2/transactions/:id/details` 的普通 CKB 容量变更明细
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：`raw` 返回指定交易的链上结构并为 Cell Dep 附加 Explorer 合约脚本元数据；`details` 按地址汇总该交易普通 Cell 的 CKB 容量净变化。
- 公开主网：Explorer `https://mainnet-api.explorer.nervos.org/api`；CKB RPC `https://mainnet.ckbapp.dev/`。
- 公开测试网：Explorer `https://testnet-api.explorer.nervos.org/api`；CKB RPC `https://testnet.ckbapp.dev/`。
- 输入：每个网络分别使用 Explorer 已索引的稳定交易哈希调用两个 V2 接口；RPC 使用 `get_transaction` 取得目标交易，并按每个普通输入的 OutPoint 再取得前序交易输出。
- 取样：主网和测试网独立取样；非 Cellbase 样本集合覆盖多输入、多输出、非空 Cell Dep、Header Dep、Witness、同地址多次输入输出和普通与非普通 Cell 混合交易，另取每个网络的 Cellbase 交易。比较期间目标交易或其所在区块发生重组时，该网络样本不作数据正确性结论。
- 成功结果：RPC 十六进制整数无损转换后，`raw` 的链上字段、数组顺序和对应关系与 RPC 一致；`details` 的地址和容量按同网络 Lock Script 地址编码及 Shannon 整数精确推导，主网与测试网分别产生结论。
- 失败结果：指出网络、交易哈希、接口、字段或地址、API 值、RPC 原值及归一化或推导后的期望值；RPC 传输失败、缺少目标交易或前序交易、或观测到重组时，仅将对应网络事实基准标记为不可用。
- 排除范围：双 Explorer 环境兼容性、媒体类型、缓存与 ETag，以及 Cell Dep `script` 扩展中尚未确认事实基准的合约名称和角色元数据；无效或不存在 ID 的行为单独列为待确认契约。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `V2-TX-RPC-01` | 在公开主网和测试网分别选择已确认的非 Cellbase 交易，样本集合覆盖多输入、多输出以及非空 Cell Dep、Header Dep、Witness，调用 `GET /api/v2/transactions/:id/raw` 并读取同网络 RPC `get_transaction` | 每个网络内，API 的 `hash`、`version`、`header_deps`、`inputs`、`outputs`、`outputs_data`、`witnesses` 及 Cell Dep 的 `dep_type`、OutPoint 都与 RPC 交易一致；十六进制整数无损归一化后比较，所有数组保持 RPC 顺序，且第 N 个 `outputs_data` 对应第 N 个 `outputs` | 原始交易漏字段、数组乱序、OutPoint 错位、十六进制转换错误或输出数据与输出 Cell 错配 | P0 |
| `V2-TX-RPC-02` | 在公开主网和测试网分别对已确认区块的 Cellbase 交易调用原始交易接口并读取同网络 RPC 交易 | API 与 RPC 的 Cellbase 原始交易一致，唯一输入的系统 OutPoint、`since`、输出、输出数据和 Witness 均保持原值；系统 OutPoint 为全零交易哈希及索引 `0xffffffff` | Cellbase 被按普通输入序列化、系统 OutPoint 或区块高度型 `since` 被改写 | P1 |
| `V2-TX-RPC-03` | 对含 Cell Dep 的原始交易观察每个依赖项附带的 `script` 扩展 | 待确认：是否把 `script.name/code_hash/hash_type/is_lock_script/is_type_script` 纳入 RPC 正确性评审并定义合约元数据事实基准，还是仅核对 RPC 可直接证明的 `dep_type` 与 OutPoint | Explorer 扩展元数据错误长期未被发现，或把非 RPC 字段错误地按节点原始结构验收 | P1 |
| `V2-TX-RPC-04` | 在公开主网和测试网分别选择含重复地址、且该地址同时出现在多个普通输入和输出中的已确认非 Cellbase 交易，调用 `GET /api/v2/transactions/:id/details` | 按同网络 RPC 逐个解析输入 OutPoint 的前序输出和本交易输出，将 Lock Script 编码为对应网络地址，并以 Shannon 整数计算 `Σ普通输出容量-Σ普通输入容量`；API 每个地址仅出现一次且容量净额精确一致，每项仅含一个 `asset/token_name/entity_type=CKB`、`transfer_type=simple_transfer` 的 transfer | 同地址未聚合、输入输出符号反转、容量精度或单位错误、主测试网地址编码混用 | P0 |
| `V2-TX-RPC-05` | 在公开主网和测试网分别选择同一地址同时涉及普通 Cell 与已识别 DAO、UDT 或其他非 `normal` Cell 的已确认交易 | API 只按普通 Cell 计算该地址的 CKB simple-transfer 净额；非 `normal` Cell 的容量不计入结果，其余地址集合和净额仍与 RPC 加同网络 Cell 类型规则的推导值一致 | DAO、Token 或 NFT Cell 中锁定的容量被误报为普通 CKB 转账，或过滤特殊 Cell 时连带遗漏普通 Cell | P1 |
| `V2-TX-RPC-06` | 已确认非 Cellbase 交易中某地址的多个普通输入与输出容量完全抵消 | 待确认：保持当前行为，返回该地址一次且 `capacity` 为零；还是从 `data` 中省略零净变化地址 | 零变化地址的展示语义不稳定，前端出现无意义记录或误漏参与地址 | P2 |
| `V2-TX-RPC-07` | 对已确认 Cellbase 交易调用容量变更明细接口 | 待确认：保持当前行为返回空 `data`，还是按 Cellbase 输出报告矿工地址的正容量变化并使用非 `simple_transfer` 语义 | 区块奖励被静默隐藏，或被错误描述为普通转账 | P2 |
| `V2-TX-RPC-08` | 在公开主网和测试网分别选择 RPC `cell_deps=[]`、`header_deps=[]`，且包含无 Type Script 输出、空 Output Data 或值为 `0x` 的 Witness 元素的已确认交易，请求原始交易 | API 对空依赖数组明确返回 `[]` 而非 `null` 或缺失字段；对应输出 `type` 为 `null`、`outputs_data` 保留精确 `0x`，Witness 数组中的 `0x` 元素保持原位置，不因空值被过滤 | 空数组与空字节串被混为缺失值、无 Type Script 被伪造成空对象，或 Witness/Output Data 数组错位 | P1 |
| `V2-TX-RPC-09` | 在任一公开网络选择一个或多个已确认交易，使样本覆盖非零且高位标志不为零的 input `since`，以及超过 `2^53` Shannon 且不能由双精度整数精确表示的 output capacity，请求原始交易 | API `inputs[].since` 和 `outputs[].capacity` 均为 `0x` 十六进制字符串，解析为无符号整数后与 RPC 原值完全一致，不发生符号扩展、十进制浮点转换、一 Shannon 舍入或科学计数；找不到公开样本时记录为事实基准不可用 | 64 位 since 标志位或大容量在数据库和 JSON 转换中失真 | P0 |
| `V2-TX-RPC-10` | 在公开主网和测试网以样本集合覆盖 `dep_type=code`、`dep_type=dep_group`、至少两个 Header Dep 及至少两个不同 Witness 的已确认交易，请求原始交易 | 每个 Cell Dep 的 `dep_type` 和 OutPoint、每个 Header Dep Hash、每个 Witness 字节串均与 RPC 对应数组逐项一致；各数组长度及顺序完全相同，不按内部记录 ID、依赖 Cell 或内容重新排序 | 只支持一种 Cell Dep 类型，或多项依赖和 Witness 因无显式 index 排序而乱序 | P0 |
| `V2-TX-RPC-11` | 分别以非交易哈希字符串和一个格式正确但 Explorer 中不存在的交易哈希请求原始交易 | 待确认：两次均应返回明确的 HTTP `404` 契约并避免缓存不存在对象；当前 `find_transaction` 可返回 `nil` 且 `raw` 随后解引用，需确认实际错误状态与响应体后固化，任何情况下不得返回 HTTP `200` 伪造原始交易 | 不存在对象触发 HTTP 500、错误被缓存、或调用方把伪造空交易当成链上数据 | P1 |
| `V2-TX-RPC-12` | 在公开主网和测试网分别选择全为普通 Cell、至少有一个地址只出现在输入侧且另一个地址只出现在输出侧的已确认非 Cellbase 交易，请求容量变更明细 | `data` 地址集合等于 RPC 输入 previous output 与本交易输出 Lock Script 地址的并集；仅输入地址容量为对应输入容量之和的负数，仅输出地址容量为对应输出容量之和的正数；所有地址净额之和等于 RPC `Σoutputs-Σinputs`，即交易费的相反数 | 单边地址被漏掉、收付款符号颠倒、地址并集错误或手续费守恒被破坏 | P0 |
| `V2-TX-RPC-13` | 当任一公开网络存在某地址普通 Cell 净变化绝对值超过 `2^53` Shannon、且不能由双精度整数精确表示的已确认交易时请求容量变更明细 | 对应 transfer 的 `capacity` 解析为十进制后与 RPC 推导的 Shannon 整数差完全一致，不出现科学计数、二进制浮点尾差或一 Shannon 舍入；找不到公开样本时记录为事实基准不可用 | 大额聚合容量在减法或 JSON 序列化中静默失精 | P0 |
| `V2-TX-RPC-14` | 在公开主网和测试网分别选择输入和输出均只包含已识别非 `normal` Cell 的已确认非 Cellbase 交易，请求容量变更明细 | 返回 HTTP `200` 和 `data: []`；不为 DAO、UDT、NFT 等 Cell 的锁定容量生成 CKB `simple_transfer`，也不生成空地址或零值占位项 | 全特殊 Cell 交易被误报为普通 CKB 转账，或过滤后残留无效记录 | P1 |
| `V2-TX-RPC-15` | 分别以非交易哈希字符串和一个格式正确但 Explorer 中不存在的交易哈希请求容量变更明细 | 待确认：两次均应返回明确的 HTTP `404` 契约；当前 `find_transaction` 可返回 `nil` 且 `details` 随后调用 `display_inputs`，需确认实际错误状态与响应体后固化，任何情况下不得返回 HTTP `200` 和伪造的 `data: []` | 不存在对象触发 HTTP 500，或被误报为没有容量变更的有效交易 | P1 |
| `V2-TX-RPC-16` | 在任一公开网络的有界观测窗口内发现 Explorer 与同网络 RPC 均可查询的 pending 或 proposed 交易时请求原始交易，并在其转为 committed 后再次请求；观测期间任一侧缺少该交易时将事实基准标记为不可用 | 两次 API 原始交易均与对应时刻 RPC 的 `transaction` 逐字段一致；状态转换前后交易哈希和完整原始结构保持不变，不因尚未入块而返回空对象、遗漏 Witness 或在提交后残留不同缓存内容 | 原始交易接口只适用于已提交交易，或交易池到区块的状态转换导致结构字段、Witness 和缓存内容漂移 | P1 |
| `V2-TX-RPC-17` | 当任一公开网络存在包含长非空 Output Data 或长 Witness 字节串的已确认交易时请求原始交易；样本至少使目标字段明显长于普通脚本参数，找不到公开样本时将事实基准标记为不可用 | API 对应 `outputs_data` 和 `witnesses` 项与 RPC 字节串逐项完全一致，数组位置、`0x` 前缀、总十六进制长度、首尾字节及完整内容均不被截断、重编码或移动 | 较长链上字节字段在数据库存取、JSON 序列化或数组组装时被截断、编码改变或错位 | P1 |
| `V2-TX-RPC-18` | 在公开主网和测试网分别选择普通 Cell 与已识别非 `normal` Cell 相互转换的已确认交易，使至少一个地址在过滤后只剩普通输入、另一个地址只剩普通输出，请求容量变更明细 | 非 `normal` Cell 容量全部排除后，只有普通输入的地址返回对应容量之和的负数，只有普通输出的地址返回对应容量之和的正数；任一侧没有普通 Cell 时按零计算，不漏掉单边地址，也不把被过滤容量用于抵消 | 先按全部 Cell 聚合再过滤导致特殊 Cell 容量参与抵消，或过滤后单边普通容量因另一侧为空而被漏掉 | P0 |
| `V2-TX-RPC-19` | 在任一公开网络的有界观测窗口内发现 Explorer 与同网络 RPC 均可查询的 pending 或 proposed 非 Cellbase 交易时请求容量变更明细，并在其转为 committed 后再次请求；观测期间任一侧缺少交易或前序输出时将事实基准标记为不可用 | 每次响应都按对应时刻 RPC 交易、输入前序输出和 Explorer Cell 类型规则得到相同的地址集合及 Shannon 净额；交易结构未变化时提交前后结果保持一致，不因尚未入块而返回空结果，也不在提交后残留旧聚合值 | 容量明细只支持已提交交易，或交易池到区块的状态转换造成输入解析、Cell 类型或缓存净额漂移 | P1 |

## 本轮需要确认

- `V2-TX-RPC-03`：Cell Dep 的 Explorer-only `script` 扩展是否进入本轮 RPC 正确性范围；若进入，需要指定合约名称和脚本角色的稳定事实基准。
- `V2-TX-RPC-06`：普通输入输出完全抵消时，零容量净变化地址应保留还是省略。
- `V2-TX-RPC-07`：Cellbase 容量明细应保持当前空 `data`，还是表达矿工奖励容量变化并定义对应 transfer 语义。
- 请确认新增 `V2-TX-RPC-08` 至 `V2-TX-RPC-10` 可作为 raw 接口的空值语义、64 位整数边界及多依赖顺序评审依据；本轮只补充测试点，不进入自动化门禁。
- `V2-TX-RPC-11`：无效或不存在交易时应采用哪一种 404 响应体；当前源码缺少 `nil` 终止分支，需避免把潜在 HTTP 500 固化成正确契约。
- 请确认新增 `V2-TX-RPC-12` 至 `V2-TX-RPC-14` 可作为 details 接口的单边地址方向、超大净额和全非普通 Cell 空结果评审依据；本轮只补充测试点，不进入自动化门禁。
- `V2-TX-RPC-15`：无效或不存在交易时应采用哪一种 404 响应体；当前源码与 raw 共用缺少终止分支的查询逻辑，需避免潜在 HTTP 500。
- 请确认新增 `V2-TX-RPC-16`、`V2-TX-RPC-17` 可作为 raw 接口的交易池到已提交状态转换和长字节字段完整性评审依据；公开窗口内没有可复现样本时只记录事实基准不可用。本轮只补充测试点，不进入自动化门禁。
- 请确认新增 `V2-TX-RPC-18`、`V2-TX-RPC-19` 可作为 details 接口的普通与特殊 Cell 单边转换、交易池到已提交状态转换评审依据；公开窗口内没有可复现 pending/proposed 样本时只记录事实基准不可用。本轮只补充测试点，不进入自动化门禁。
