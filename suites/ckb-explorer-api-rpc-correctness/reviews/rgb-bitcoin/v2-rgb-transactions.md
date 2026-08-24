# V2 RGB++ 交易跨链关联正确性用例评审

评审范围：核对 `rgb_digest` 单笔跨链摘要和 RGB++ 交易列表的 CKB/Bitcoin 关联、方向、排序与分页
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：把 CKB RGB++ 或 BTC Time Lock Cell 与 Bitcoin 交易、outpoint 和 OP_RETURN commitment 关联，并展示单笔摘要或 RGB++ 交易列表。
- 输入：`GET /api/v2/ckb_transactions/:id/rgb_digest`；`GET /api/v2/rgb_transactions` 及 `sort`、`leap_direction`、`page`、`page_size`；事实基准为同网络 CKB RPC、输入引用交易、Bitcoin RPC 和确定性 RGB++ commitment 算法。
- 成功结果：摘要返回 Bitcoin txid、确认数、commitment、验证结果、方向、步骤和 Bitcoin 地址资产变更；列表只包含 RGB++ 注解交易并返回稳定筛选、排序和分页结果。
- 失败结果：摘要交易哈希不存在时返回 404；CKB 重组或任一独立 RPC 缺少关联对象时该网络 oracle 不可用。
- 不负责：Bitcoin 地址持仓、全局 RGB 统计、通用分页错误格式、缓存头和非 RGB++ 交易详情。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `RGB-TX-RPC-01` | 在每个网络选择已建立 RGB++ CKB/Bitcoin 关联且 Bitcoin 交易包含对应 OP_RETURN 的已确认 CKB 交易，请求 `rgb_digest` | `txid` 等于 RGB++ Lock args 指向并由 Bitcoin RPC 证明的交易，`confirmations` 等于该 Bitcoin RPC 当前确认数，`commitment` 等于对应 OP_RETURN payload，方向和步骤与 CKB 输入输出 Lock 类型一致 | CKB 交易关联到错误 Bitcoin 交易、错误 vout 或错误确认状态 | P0 |
| `RGB-TX-RPC-02` | 对输入输出 Type Script Cell 数量不超过 255 且 OP_RETURN commitment 正确的 RGB++ 交易重算 commitment | 按 RGB++ 规则序列化 CKB 输入 outpoint、将输出 Lock args 中 txid 归零并包含 Output Data 后计算的双 SHA-256 结果与 OP_RETURN 完全相同，`commitment_verified` 为 `true` | 遗漏输入、输出或数据，字节序错误，或没有真正验证跨链承诺 | P0 |
| `RGB-TX-RPC-03` | 选择 OP_RETURN commitment 与从 CKB 虚拟交易重算值不同的已索引关联 | API 原样返回 Bitcoin OP_RETURN commitment，且 `commitment_verified` 为 `false`，不把不匹配覆盖成计算值 | 篡改或错误关联的跨链承诺被标记为已验证 | P0 |
| `RGB-TX-RPC-04` | CKB 交易存在，但没有同时找到关联 Bitcoin 交易和 OP_RETURN vout | 摘要仍返回该 CKB 交易可确定的方向、步骤和 transfers；`txid`、`confirmations`、`commitment`、`commitment_verified` 为空，不产生伪造 Bitcoin 身份 | 缺少跨链证据时返回上一次缓存或其他交易的 Bitcoin 数据 | P1 |
| `RGB-TX-RPC-05` | RGB++ 交易包含映射到 Bitcoin 地址的多个输入输出 Cell，也包含没有 Bitcoin 地址映射的普通 CKB 地址 | `transfers` 只列出具有 Bitcoin 地址映射的地址；每个 Bitcoin 地址下的 CKB、UDT、DAO 或 NFT 变更与同一 CKB 交易输入引用和输出推导值一致，未映射地址不混入 | 把 CKB 地址误当 Bitcoin 地址、漏算映射 Cell 或跨地址合并资产 | P0 |
| `RGB-TX-RPC-06` | 分别选择 RGB++→RGB++、RGB++→BTC Time、BTC Time 解锁、无 RGB++/BTC Time 关联输入→RGB++ 四类 CKB 输入输出组合 | 四类交易分别报告 `withinBTC/isomorphic`、`in/isomorphic`、`in/unlock`、`leapoutBTC/isomorphic`；列表和摘要对同一交易的方向、步骤一致 | 跨链流入、流出、Bitcoin 内转移和解锁流程被错误分类 | P0 |
| `RGB-TX-RPC-07` | 不带筛选调用 RGB 交易列表并用 CKB 链数据与 RGB++ Lock 规则重建候选交易 | 列表只包含带 RGB++ 注解的交易；每项 `tx_hash`、区块 ID/高度/时间、方向、步骤、RGB Cell 净变化和关联 Bitcoin txid 与事实基准一致，普通及仅 BTC Time 交易不混入 | 列表成员污染、交易摘要字段错配或 RGB Cell 数量重复计算 | P0 |
| `RGB-TX-RPC-08` | 分别以 `withinBTC`、`in`、`leapoutBTC` 请求 `leap_direction` 过滤 | 每次结果只含对应方向的 RGB++ 交易，成员并集与未过滤列表中的相应方向成员一致 | 方向过滤失效、枚举映射错误或过滤后仍混入其他流程 | P1 |
| `RGB-TX-RPC-09` | 对同一稳定样本分别使用 `number.asc/desc`、`confirmation.asc/desc` 和 `time.asc/desc` | `number` 与 `confirmation` 都按 CKB 区块高度排序，`time` 按 CKB 区块时间戳排序，升降序与参数一致；默认请求按 `number.desc` | 排序字段错接 Bitcoin 确认数、方向倒置或默认顺序变化 | P1 |
| `RGB-TX-RPC-10` | 对稳定 RGB++ 列表使用相邻页和不同合法 `page_size` | 各页成员按选定排序连续且不重复，`meta.total` 等于过滤后的总成员数，`meta.page_size` 等于实际页容量 | 分页跳项、重项、总数使用未过滤集合或页大小回显错误 | P1 |
| `RGB-TX-RPC-11` | 使用 Explorer 中不存在的 CKB 交易哈希请求 `rgb_digest` | 返回 404 且不返回其他交易的摘要或跨链字段 | 未知哈希命中错误缓存或泄漏其他交易关联 | P1 |
| `RGB-TX-RPC-12` | 核对期间 CKB 同高度哈希变化，或 CKB/Bitcoin RPC 缺少目标交易、引用输出或区块 | 将该网络对应样本标记为 oracle 不可用，不判定为 API 跨链字段不匹配；另一网络结果独立 | 重组、节点裁剪或上游短暂故障被误报为 RGB++ 数据回归 | P1 |

## 本轮需要确认

- 无；方向枚举、列表字段、commitment 算法和缺失关联的空字段均由当前实现明确规定。
