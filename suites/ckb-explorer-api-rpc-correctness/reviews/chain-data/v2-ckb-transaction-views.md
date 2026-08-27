# V2 CKB 交易展示视图 RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 交易、输入引用输出和区块经济状态为事实基准，核对 `details`、`display_inputs`、`display_outputs` 三个交易展示接口
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按交易哈希返回按地址和资产聚合的净变更，或分页返回可供 Explorer 展示的输入、输出 Cell。
- 输入：`GET /api/v2/ckb_transactions/:id/details`、`GET /api/v2/ckb_transactions/:id/display_inputs`、`GET /api/v2/ckb_transactions/:id/display_outputs`；辅助使用同网络 RPC `get_transaction`、`get_live_cell`、`get_block_median_time`、`get_block_economic_state`，并递归解析每个 input out-point 的上一交易输出。
- 取样：主网和测试网独立选择已确认交易，覆盖普通交易、Cellbase、UDT、DAO/NFT 和大整数边界；地址按对应网络规则由 Lock Script 生成。
- 成功结果：容量以 Shannon 整数、UDT 金额以前 16 字节小端无符号整数比较；输入输出的身份、顺序、分页、脚本、状态和奖励均与同网络 RPC 原始值或确定推导值一致。
- 失败结果：RPC 传输失败、上一交易缺失、目标状态在比较期间变化或观察到重组时，只将该网络标记为事实基准不可用；另一网络独立执行。
- 不负责：媒体类型、除目标交易不存在之外的通用错误对象、缓存头、UDT `symbol/decimal`、依赖 Explorer 数据库或外部聚合器的 NFT/CoTA 展示名称，以及一般分页参数类型契约。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `CKB-TX-VIEWS-RPC-01` | - [x] 在公开主网和测试网分别选择普通 Cell 覆盖同地址多输入/输出、地址同时或只在一侧出现的已确认非 Cellbase 交易，请求资产变更明细 | `data` 地址集合等于从 RPC Lock Script 生成的同网络地址集合；每个地址恰有一个 `cell_type=normal` 变更，`capacity` 精确等于该地址普通 Cell 的 `Σoutputs-Σinputs` Shannon，正负号、聚合和手续费守恒正确 | 输入引用或地址编码错误、同地址 Cell 漏算/重复、收付款方向颠倒 | P0 |
| `CKB-TX-VIEWS-RPC-02` | - [x] 在公开主网和测试网分别对已确认区块的 Cellbase 交易请求资产变更明细 | Cellbase 系统输入不作为真实资产来源；每个输出地址的普通 CKB 变更等于 RPC Cellbase 输出容量之和且为正，所有地址变更总和等于 RPC 全部 Cellbase 输出容量 | 虚构零哈希输入、漏掉矿工输出或错误扣减区块奖励 | P0 |
| `CKB-TX-VIEWS-RPC-03` | - [x] 在公开主网和测试网分别选择含 `udt`、`xudt`、`xudt_compatible` 或 `omiga_inscription` Cell 的已确认交易 | 每个 `(地址、type_hash、cell_type)` 只有一个聚合变更；`capacity` 等于对应 Cell 的输出减输入 Shannon，`udt_info.type_hash` 等于 Type Script Hash，`amount` 等于 Data 前 16 字节小端金额的输出减输入 | 不同代币合并、Type Script 分类错误、金额字节序或方向错误 | P0 |
| `CKB-TX-VIEWS-RPC-04` | - [x] 在每个网络选择普通 Cell 参与容量或聚合中间值超过 `2^53`、且净变更不能由双精度整数精确表示的已确认交易 | API `capacity` 解析为十进制后仍与 RPC 推导的 Shannon 整数完全一致，不出现科学计数或一 Shannon 舍入 | 当前浮点聚合路径使大额 CKB 资产变更静默失真 | P0 |
| `CKB-TX-VIEWS-RPC-05` | - [x] 在每个网络选择 UDT 输入、输出或聚合金额超过 `2^53`、且净变更不能由双精度整数精确表示的已确认交易 | `udt_info.amount` 精确表示 RPC Data 中的 128 位整数差，不丢失低位或出现错误小数尾数 | UDT 金额经浮点转换后精度损失或错误抵消 | P0 |
| `CKB-TX-VIEWS-RPC-06` | - [x] 在公开主网和测试网分别选择包含 Nervos DAO deposit 或 withdrawing Cell 的已确认交易 | 按地址和 `nervos_dao_deposit`、`nervos_dao_withdrawing` 分别聚合；每项 `capacity` 等于 RPC 对应 DAO Cell 的输出减输入 Shannon，两个阶段不互相合并 | DAO 阶段分类、地址归属或容量变更被错误合并 | P1 |
| `CKB-TX-VIEWS-RPC-07` | - [x] 选择包含可从链上识别的 NFT Cell 的已确认交易，核对 RPC 可直接证明的变更 | 每个地址、Cell 类型和 Type Script 的 `capacity` 等于 RPC 输出减输入 Shannon，`count` 等于输出 Cell 数减输入 Cell 数；仅比较能从 Type Script 或 Data 直接解码的 token 字段 | NFT 铸造、转移、销毁方向或数量错误，以及不同 Type Script 的 NFT 被合并 | P1 |
| `CKB-TX-VIEWS-RPC-08` | - [ ] 对包含 `cota_regular` Cell 的交易核对容量变更与 `cota_info` | 待确认：本套件只用 CKB RPC 核对地址、Cell 类型和容量，还是额外接入 CoTA Aggregator 核对 `token_id/count/name`；选定范围内字段须与对应事实基准一致 | 把外部聚合数据误当作 RPC 事实，或完全遗漏 CoTA 资产变更 | P1 |
| `CKB-TX-VIEWS-RPC-09` | - [ ] 某地址的同一资产输入与输出完全相等，净变更为零 | 待确认：响应应保留数值为零的 transfer，还是省略该项；主网和测试网采用同一约定 | 零变更噪声或静默过滤导致调用方误判参与地址 | P2 |
| `CKB-TX-VIEWS-RPC-10` | - [ ] 交易包含资产比较器尚未覆盖的 `omiga_inscription_info`、`unique_cell`、`stablepp_pool` 或 `ssri` Cell | 待确认：这些 Cell 的 CKB 容量或资产变更应返回，还是明确属于接口排除项 | 新 Cell 类型上线后资产明细静默不完整 | P1 |
| `CKB-TX-VIEWS-RPC-11` | - [x] 在主网和测试网分别选取已确认非 Cellbase 交易，通过 RPC 取得交易及每个输入引用的上一交易后请求输入展示 | `meta.total` 等于 RPC inputs 数；每项按 RPC 输入顺序对应同一 previous output，交易哈希、output index、容量、占用容量、同网络地址和区块 median time 均与 RPC 原值或确定推导值一致；RPC Type Script 非空时三个字段完全一致，为 `null` 时 API `type_script` 返回空字符串；`since.raw` 为 `0x` 加 16 位小写十六进制且解析后的 64 位整数等于 RPC input `since` | 输入错位、顺序颠倒、previous output 关联、地址、容量、Script、since 数值或固定宽度编码错误 | P0 |
| `CKB-TX-VIEWS-RPC-12` | - [x] 在主网和测试网分别选择至少两个输入的已确认非 Cellbase 交易，以 `page_size=1` 连续请求前两页 | 两页分别返回 RPC 第 1、2 个输入，无重复或缺失；`meta.total` 始终为 RPC 输入总数，页大小为 1 | 数据库 ID 分页与链上输入顺序不一致 | P1 |
| `CKB-TX-VIEWS-RPC-13` | - [x] 在主网和测试网分别选择已确认 Cellbase 交易请求输入展示 | 仅返回一个合成输入，`meta.total=1`；`from_cellbase=true`、`generated_tx_hash` 等于 RPC 交易哈希，奖励目标高度按提案窗口计算，普通 Cell 身份、容量和地址字段为空 | Cellbase 被当作普通输入，或奖励目标区块关联错误 | P1 |
| `CKB-TX-VIEWS-RPC-14` | - [x] 在公开主网和测试网分别对仅有一个合成输入的已确认 Cellbase 交易请求 `page=2&page_size=1` | 两个网络均继续返回唯一合成输入；`meta.total=1`、`meta.page_size=1`，合成输入身份与首页一致，不返回空数组或普通输入 | Cellbase 输入分页行为在网络间漂移，或越界页意外丢失、重复构造不同的合成输入 | P1 |
| `CKB-TX-VIEWS-RPC-15` | - [x] 在主网和测试网分别选取已确认非 Cellbase 交易，通过 RPC 取得完整交易后请求输出展示 | `meta.total` 等于 RPC outputs 数；每项按 RPC 数组顺序对应同一输出，交易哈希、output index、Shannon 容量、占用容量、同网络地址和 Type Script 与 RPC 原值或确定推导值一致 | 输出错位、容量精度、Script、Data 长度或地址编码错误 | P0 |
| `CKB-TX-VIEWS-RPC-16` | - [x] 在主网和测试网分别选择至少两个输出的已确认非 Cellbase 交易，以 `page_size=1` 连续请求前两页 | 两页分别返回 RPC 第 1、2 个输出，无重复或缺失；`meta.total` 始终为 RPC 输出总数，页大小为 1 | 数据库 ID 分页与链上输出顺序不一致 | P1 |
| `CKB-TX-VIEWS-RPC-17` | - [x] 在每个网络分别选择 RPC `get_live_cell` 证明为 Live 的输出和一个已被后续已确认交易消费的输出 | Live 输出 `status=live` 且 `consumed_tx_hash` 为空；已消费输出 `status=dead` 且消费哈希等于 RPC 中引用该 out-point 的交易；比较前后状态保持稳定 | Live/Dead 状态或消费交易关联错误 | P0 |
| `CKB-TX-VIEWS-RPC-18` | - [x] 在主网和测试网分别选择目标奖励区块和经济状态可由 RPC 取得的成熟 Cellbase 交易请求输出展示 | 输出身份、顺序、容量、占用容量和地址与 RPC 一致；目标高度按提案窗口计算，四个奖励分项分别等于 RPC miner reward 的 primary、secondary、proposal、committed，均以 Shannon 整数比较 | Cellbase 输出关联错误区块，或奖励分项错配、失精 | P0 |
| `CKB-TX-VIEWS-RPC-19` | - [x] 在主网和测试网分别选择至少两个输出的 Cellbase 交易，以 `page_size=1` 请求前两页 | 两页分别对应 RPC Cellbase outputs 第 1、2 项，无重复或缺失，`meta.total` 等于 RPC 输出总数 | Cellbase 专用数组按数据库 ID 而非链上 output index 错误分页 | P1 |
| `CKB-TX-VIEWS-RPC-20` | - [ ] 在公开主网和测试网分别对已确认普通交易和 Cellbase 交易请求超过最后一页的输出页 | 两类交易均返回 HTTP `200` 和空数组 `data: []`；`meta.total` 保留该交易的真实 RPC outputs 总数，`meta.page_size` 保留本次请求采用的页大小，不返回 404 或重复最后一页 | 普通关系分页与 Cellbase 数组分页在越界页产生不同响应、丢失总数或重复数据 | P1 |
| `CKB-TX-VIEWS-RPC-21` | - [ ] 在公开主网和测试网分别选择同一地址同时发生普通 Cell 和至少一种 UDT Cell 变更的已确认交易，请求资产变更明细 | `data` 中该地址只出现一次，其 `transfers` 同时保留独立的 `cell_type=normal` 项和按 `(type_hash, cell_type)` 区分的 UDT 项；各项容量及 UDT 金额分别等于 RPC 对应输出减输入的精确整数差，不互相覆盖或合并 | 合并多类资产时重复地址、后写资产覆盖先写资产，或把代币容量计入普通 CKB 变更 | P0 |
| `CKB-TX-VIEWS-RPC-22` | - [ ] 在公开主网和测试网分别选择某一 UDT 资产只存在于输出侧的铸造交易，以及只存在于输入侧的销毁交易，请求资产变更明细 | 铸造侧 `udt_info.amount` 等于 RPC 输出 Data 前 16 字节小端金额之和且为正，销毁侧等于输入金额相反数且为负；对应 `capacity` 也分别按输出减输入计算，缺失的一侧按零处理 | 单边资产因空输入或空输出被漏掉、方向反转、空值计算异常或错误抵消 | P0 |
| `CKB-TX-VIEWS-RPC-23` | - [ ] 分别以非交易哈希字符串和一个格式正确但 Explorer 中不存在的交易哈希请求资产变更明细 | 两次均返回 HTTP `404` 且响应体为空，不返回 HTTP `200` 空 `data`、V1 错误对象或服务端异常 | 畸形与不存在 ID 被误报为成功，或接口实际空体错误契约漂移 | P1 |
| `CKB-TX-VIEWS-RPC-24` | - [x] 在公开主网和测试网分别选择至少含两个普通输入、其中一个引用输出 Type Script 非空而另一个为 `null` 的已确认交易，请求输入展示 | 两个展示项按 RPC inputs 顺序分别绑定各自 previous out-point；非空项的 `type_script.args/code_hash/hash_type` 与 RPC 一致，无 Type Script 项返回空字符串，不会复用相邻输入脚本或返回脚本对象 | 多输入关联或序列化串扰导致 Type Script 错位、把相邻输入脚本错误赋给无脚本输入 | P1 |
| `CKB-TX-VIEWS-RPC-25` | - [x] 在公开主网和测试网分别选择至少一个 RPC input `since` 非零的已确认非 Cellbase 交易，请求包含该输入的展示页 | `since.raw` 为 `0x` 加 16 位小写十六进制，解析为无符号 64 位整数后与 RPC `since` 完全一致；`since.median_timestamp` 等于同网络 RPC 对消费区块取得的 median time，均不被截断、符号扩展或回退为零 | 非零绝对/相对 since 在十六进制填充、数据库转换或分页序列化时失真 | P1 |
| `CKB-TX-VIEWS-RPC-26` | - [x] 在公开主网和测试网分别选择消费 `udt`、`xudt` 或 `xudt_compatible` Cell 的已确认交易，请求包含该输入的展示页 | 展示项 previous out-point、`cell_type` 和 Type Script 与 RPC 一致；对应 `udt_info`、`xudt_info` 或 `xudt_compatible_info` 的 `amount` 等于 RPC previous output Data 前 16 字节小端无符号整数，`type_hash` 等于规范计算的 Type Script Hash，且 `extra_info` 中这些 RPC 可证明字段一致 | 输入扩展信息读取当前输出而非 previous output、UDT 金额字节序错误、类型分类或 Type Hash 错配 | P0 |
| `CKB-TX-VIEWS-RPC-27` | - [x] 分别以非交易哈希字符串和一个格式正确但 Explorer 中不存在的交易哈希请求输入展示 | 两次均返回 HTTP `404` 且响应体为空，不返回带 `meta.total=0` 的 HTTP `200`、V1 错误对象或服务端异常 | 畸形或不存在 ID 被误报为无输入的有效交易，或空体 404 契约漂移 | P1 |
| `CKB-TX-VIEWS-RPC-28` | - [ ] 在公开主网和测试网分别选择至少含两个输出、其中一个 RPC Type Script 非空而另一个为 `null` 的已确认非 Cellbase 交易，请求输出展示 | 两个展示项按 RPC outputs 顺序分别绑定各自 `cell_index`；非空项的 `type_script.args/code_hash/hash_type` 与 RPC 一致，无 Type Script 项明确返回 `type_script: null`，不会复用相邻输出脚本 | 多输出关联或序列化串扰导致 Type Script 错位、把无脚本输出伪造成有脚本 | P1 |
| `CKB-TX-VIEWS-RPC-29` | - [ ] 在公开主网和测试网分别选择产生 `udt`、`xudt` 或 `xudt_compatible` Cell 的已确认交易，请求包含该输出的展示页 | 展示项 out-point、`cell_type` 和 Type Script 与 RPC 一致；对应 `udt_info`、`xudt_info` 或 `xudt_compatible_info` 的 `amount` 等于 RPC `outputs_data[cell_index]` 前 16 字节小端无符号整数，`type_hash` 等于规范计算的 Type Script Hash，且 `extra_info` 中这些 RPC 可证明字段一致 | 输出扩展信息读取相邻 Cell Data、UDT 金额字节序错误、类型分类或 Type Hash 错配 | P0 |
| `CKB-TX-VIEWS-RPC-30` | - [ ] 当任一公开网络存在单个输出容量超过 `2^53` Shannon、且数值不能由双精度整数精确表示的已确认交易时请求输出展示 | 对应项 `capacity` 解析为十进制整数后与 RPC `outputs[cell_index].capacity` 完全一致，不出现科学计数、`.0` 舍入或一 Shannon 偏差；找不到公开样本时记录为事实基准不可用 | 大容量经过浮点或 JSON 数字转换后静默失精 | P0 |
| `CKB-TX-VIEWS-RPC-31` | - [ ] 分别以非交易哈希字符串和一个格式正确但 Explorer 中不存在的交易哈希请求输出展示 | 两次均返回 HTTP `404` 且响应体为空，不返回带 `meta.total=0` 的 HTTP `200`、V1 错误对象或服务端异常 | 畸形或不存在 ID 被误报为无输出的有效交易，或空体 404 契约漂移 | P1 |

## 本轮需要确认

- `CKB-TX-VIEWS-RPC-08`：是否为 CoTA 字段引入 Aggregator 作为第二事实基准。
- `CKB-TX-VIEWS-RPC-09`、`CKB-TX-VIEWS-RPC-10`：零净变更与当前比较器未覆盖 Cell 类型的业务语义。
- 请确认新增 `CKB-TX-VIEWS-RPC-21` 至 `CKB-TX-VIEWS-RPC-23` 可作为 details 接口的多资产合并、UDT 单边状态转换与实际空体 404 响应评审依据；本轮只补充测试点，不进入自动化门禁。
- 请确认新增 `CKB-TX-VIEWS-RPC-28` 至 `CKB-TX-VIEWS-RPC-31` 以及按当前实现明确越界页结果后的 `CKB-TX-VIEWS-RPC-20` 可作为 display_outputs 的脚本可空性、UDT 输出、大整数容量、实际空体 404 和越界分页评审依据；本轮只补充测试点，不进入自动化门禁。
- `page_size > 100` 在普通关系分页与 Cellbase 数组分页之间可能行为不同；应在通用 HTTP 契约中决定统一截断、拒绝或允许。
