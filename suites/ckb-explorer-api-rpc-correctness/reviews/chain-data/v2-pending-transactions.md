# V2 待处理交易列表与计数 RPC 正确性用例评审

评审范围：在公开主网和测试网分别核对 `GET /api/v2/pending_transactions` 的交易池成员、字段、分页和排序，以及 `GET /api/v2/pending_transactions/count` 的计数语义和两接口一致性
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：列表接口返回 Explorer 已索引且至少有一个已解析、非 Cellbase 前置输出的数据库 pending 交易；计数接口返回全部数据库 pending 交易数。本评审使用同网络 CKB RPC 交易池作为动态事实基准，并要求主网、测试网分别产生结论。
- 输入：列表接口接受 `page`、`page_size` 和 `sort`；`sort` 支持 `time`、`fee`、`capacity` 及 `asc`、`desc` 方向。事实基准使用同网络 CKB RPC `get_raw_tx_pool(true)` 和 `tx_pool_info`。
- 成功结果：在同源节点和稳定观测窗口内，列表成员及可验证字段与 RPC 交易池一致，分页和排序符合接口约定，列表资格总数不大于数据库 pending 总数；计数接口只统计 Explorer 数据库 `tx_status=pending`，不计 proposed、committed 或 rejected。
- 失败结果：指出网络、观测窗口、交易哈希、API 值、RPC 原值和解码后的期望值；若包围式 RPC 快照发生变化、RPC 结果缺失或并非 Explorer 的同源交易池，则该网络的事实基准不可用，不据此判定 API 数据错误。
- 不负责：双 Explorer 环境兼容性、通用 HTTP 媒体类型与错误结构、地址维度待处理交易、交易提交和交易池写操作，以及已确认交易详情。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `PENDING-RPC-01` | 在公开主网和测试网分别用同网络 CKB RPC `get_raw_tx_pool(true)` 包围一次列表观测，且目标交易在两次快照中保持为 pending 或 proposed | 每个 API `transaction_hash` 在稳定 RPC 交易池中恰好出现一次，API `transaction_fee` 等于对应 RPC `fee` 十六进制无损转换后的 Shannon 整数；主网、测试网分别给出结论 | 索引了错误网络、遗漏或重复待处理交易，或手续费进制和单位写错 | P0 |
| `PENDING-RPC-02` | 对 RPC 快照中保持稳定且被 API 返回的待处理交易读取列表项 | 列表项只包含 `transaction_hash`、`capacity_involved`、`transaction_fee`、`created_at`、`create_timestamp`；`create_timestamp` 等于 `created_at` 向下取整到毫秒的 Unix 时间，哈希和手续费与同一 RPC 交易一致 | 字段投影串行化漂移、秒和毫秒混淆，或把其他交易的属性拼到当前交易 | P0 |
| `PENDING-RPC-03` | 在待处理交易集合于观测前后保持不变时，不传 `page`、`page_size` 和 `sort` 请求列表 | 返回符合展示资格的唯一交易中按 Explorer 内部交易 ID 降序排列的前 10 条，`meta.page_size` 为 10，`meta.total` 为全部符合展示资格的唯一交易数；多输入交易不重复出现 | 默认排序方向或分页失效、总数按输入行重复计数，或默认列表不稳定 | P0 |
| `PENDING-RPC-04` | 在稳定集合上以同一排序分别请求 `page=1&page_size=5`、`page=2&page_size=5` 和 `page_size=1000` | 前两页与同一稳定全量顺序的连续切片一致且不重叠，所有页 `meta.total` 一致；待确认：超过模型上限的页长应统一截断到 100 并在 `meta.page_size` 报告 100，还是拒绝该参数 | 翻页漏项或重项、总数随页变化，或实际页长与元数据不一致 | P1 |
| `PENDING-RPC-05` | 在稳定集合含不同创建时间的交易时分别请求 `sort=time`、`sort=time.asc` 和 `sort=time.desc` | `time` 与 `time.asc` 都按 API `created_at` 升序，`time.desc` 按其降序；相同时间以内部交易 ID 降序稳定打破并列，空值始终位于末尾 | 时间排序方向、默认方向或并列顺序漂移导致分页抖动 | P1 |
| `PENDING-RPC-06` | 在稳定集合含不同 RPC 手续费的交易时分别请求 `sort=fee`、`sort=fee.asc` 和 `sort=fee.desc` | `fee` 与 `fee.asc` 都按已由 RPC 核对的 `transaction_fee` 升序，`fee.desc` 按其降序；并列按内部交易 ID 降序，空值始终位于末尾 | 手续费排序使用错误单位或字段，或并列项跨页重复和遗漏 | P1 |
| `PENDING-RPC-07` | 在稳定集合含可解析输入容量的待处理交易时请求默认列表以及 `sort=capacity.asc`、`sort=capacity.desc` | 待确认：`capacity_involved` 应保持 `null` 直到交易上链，还是应等于 RPC 原始交易所有输入容量之和；若要求后者，两种方向按该 Shannon 整数排序、并列按内部交易 ID 降序、空值末尾 | 接口长期返回空容量、容量计算错误，或容量排序名义可用但实际无效 | P1 |
| `PENDING-RPC-08` | 请求 `sort=time.abcd`、未知排序字段及大小写不同的合法方向 | 非法或缺失方向按升序处理，未知字段回退到内部交易 ID；合法 `ASC`、`DESC` 大小写不敏感，任何值都不会成为自由 SQL 排序表达式 | 畸形排序造成服务错误、非确定顺序，或排序参数进入 SQL | P2 |
| `PENDING-RPC-09` | 分别传入 `page` 或 `page_size` 为 0、负数、非数字和超大整数 | 待确认：这些值应返回明确的 4xx 参数错误，还是按受限默认值归一化；无论选择哪种约定，都不得返回 500、负 offset 或无界结果 | 畸形分页触发服务错误、资源放大，或不一致的空页行为 | P1 |
| `PENDING-RPC-10` | 在同源节点且交易池状态稳定的观测窗口内调用计数接口，并读取 RPC `tx_pool_info` 与 `get_raw_tx_pool(true)` 中彼此独立的 pending、proposed 集合 | API `data` 为 JSON 整数，精确等于 RPC pending 集合大小及 `tx_pool_info.pending` 十六进制计数的无损转换值；proposed 集合无论是否非空都不计入 | 把 proposed 合并进 pending 计数、十六进制计数转换错误，或响应把整数变成字符串/null | P0 |
| `PENDING-RPC-11` | 在缓存已刷新且稳定集合同时含符合展示资格和不符合展示资格的数据库 pending 交易时，成对调用列表与计数接口并逐项确认输入解析状态 | `list.meta.total` 不大于 `count.data`；`count.data-list.meta.total` 精确等于没有任何已解析、非 Cellbase previous output 的 pending 交易数，已解析输入数量不会造成重复计数 | 把列表资格总数和数据库 pending 总数混为一谈，或按 CellInput 行放大列表/计数差值 | P0 |
| `PENDING-RPC-12` | 同源 RPC 的 pending、proposed 均为空且 Explorer 缓存已刷新时调用列表和计数接口 | 列表返回 `data=[]`、`meta.total=0` 和请求采用的受限 `meta.page_size`，计数返回整数 `data=0` | 空池被当成错误、返回残留交易，或列表与计数的零值结构不一致 | P1 |
| `PENDING-RPC-13` | 任一网络的包围式 RPC 快照发生交易进入、离开或 pending/proposed 转换，或 RPC 方法和结果不可用 | 该网络本次依赖精确成员或计数的断言标记为事实基准不可用，不判为 API 数据错误；另一网络独立执行 | 交易池天然变化或 RPC 局部故障制造间歇性误报并连带污染另一网络 | P1 |
| `PENDING-RPC-14` | 在稳定交易池中分别观察一笔含多个输入且至少一个 previous output 已被 Explorer 解析的 pending 交易，以及一笔所有 previous output 均未解析的 pending 交易，并用输入展示结果辅助确认解析状态 | 前一交易在列表中恰好出现一次，即使只有部分输入已解析也不重复；后一交易不出现在任何列表页；`meta.total` 只统计至少有一个已解析、非 Cellbase previous output 的唯一 pending 交易 | 资格条件被错误实现为全部输入均须解析、任一输入即可重复加入，或未解析交易污染列表总数 | P0 |
| `PENDING-RPC-15` | 当任一公开网络的稳定 RPC 交易池中存在手续费超过 `2^53` Shannon 且不能由双精度整数精确表示的 pending 交易时，请求包含该交易的列表页及 `sort=fee.asc/desc` | `transaction_fee` 解析为十进制整数后与 RPC `fee` 十六进制值完全一致，不出现科学计数或一 Shannon 舍入；升序和降序均按该精确整数定位，找不到公开样本时记录为事实基准不可用 | 大额手续费经 JSON 或排序表达式转换后失精并排错位置 | P0 |
| `PENDING-RPC-16` | 在稳定且非空的符合展示资格集合上，以合法 `page_size` 请求严格超过最后一页的页码 | 返回 HTTP `200`、`data: []`；`meta.total` 仍等于同一快照的资格总数，`meta.page_size` 等于实际采用的页大小，不重复最后一页或返回 404 | 翻过末页后重复交易、丢失总数或把合法空页误报为错误 | P1 |
| `PENDING-RPC-17` | 观察一笔先稳定处于 pending、随后稳定进入 proposed、committed、rejected 或从节点交易池移除的交易，并在 Explorer 完成同步及约定缓存窗口结束后重新请求列表 | 交易只在数据库状态为 pending 且满足输入解析资格时出现；进入其他状态或被移除并同步后不再出现在任何列表页，`meta.total` 相应减少且其他交易顺序保持约定 | 已提议、已确认、已拒绝或已丢弃交易长期残留在 pending 列表及分页总数中 | P1 |
| `PENDING-RPC-18` | 在同源 RPC 和 Explorer 同步状态可稳定观察时，记录 count 后让一笔交易依次从 pending 转为 proposed、committed 或 rejected，并在每次 Explorer 状态同步完成后再次读取 count | 交易首次进入数据库 pending 时 `data` 增加 1；离开 pending 进入任一其他状态时减少 1，proposed 不维持计数；其他 pending 成员不变时差值必须恰为 1，不出现负数或重复递减 | 状态转换未更新计数、proposed 被继续计入、同一交易重复增减或计数漂移 | P0 |
| `PENDING-RPC-19` | 在一次 pending 成员增加或移除后立即成对轮询无公开缓存的 count 与带 `max-age=10, stale-while-revalidate=5` 的列表，并持续至缓存窗口结束 | count 在 Explorer 数据库状态同步后的首个请求即反映新整数；列表允许短时保持旧成员和 `meta.total`，但最迟在 15 秒缓存窗口结束后的首次刷新与 count 的资格关系重新一致，不得无限返回陈旧快照 | 即时计数与缓存列表短时差异被误判为永久错误，或列表缓存超过声明窗口长期不收敛 | P1 |

## 本轮需要确认

- 严格成员和计数相等是否只在 Explorer 与 RPC 使用同一节点时执行；公开默认网络对若不是同源交易池，应将依赖精确成员和数量的结论标记为事实基准不可用。
- `PENDING-RPC-07`：pending 交易的 `capacity_involved` 应保持 `null`，还是应等于所有输入容量之和。
- `PENDING-RPC-09`：非法分页参数应返回明确的 4xx，还是按受限默认值归一化。
- `PENDING-RPC-04`：`page_size` 超过 100 时应统一拒绝还是截断，并确保 `meta.page_size` 报告实际生效值；当前查询上限和控制器回显值可能不一致。
- 请确认新增 `PENDING-RPC-14` 至 `PENDING-RPC-17` 以及明确内部 ID 降序后的 `PENDING-RPC-03` 可作为列表资格边界、大额手续费、越界空页和状态退出评审依据；本轮只补充测试点，不进入自动化门禁。
- 请确认明确 pending-only 口径后的 `PENDING-RPC-10/11` 及新增 `PENDING-RPC-18/19` 可作为 count 的状态转换、列表资格差值与 15 秒缓存收敛评审依据；本轮只补充测试点，不进入自动化门禁。
