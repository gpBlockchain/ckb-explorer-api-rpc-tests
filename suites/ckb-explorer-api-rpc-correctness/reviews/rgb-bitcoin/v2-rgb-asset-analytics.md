# V2 RGB 资产统计与持有人排名正确性用例评审

评审范围：核对 RGB++ 资产历史统计及 xUDT/xUDT-compatible 在 Bitcoin 映射地址和纯 CKB 地址间合并后的 Top Holders
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：返回按网络和 indicator 保存的 RGB++ 资产统计时间序列；对指定 xUDT 合并 Bitcoin 地址持仓和无 Bitcoin 映射的 CKB 地址持仓后返回前十名。
- 输入：`GET /api/v2/rgb_assets_statistics` 及 `network`、逗号分隔的 `indicators`；`GET /api/v2/rgb_top_holders/:id`；事实基准为同一统计截面的 CKB RPC/Indexer、Bitcoin 地址映射和索引快照。
- 成功结果：统计记录按时间升序并准确过滤；Top Holders 按整数 amount 降序合并两个网络来源，返回最多十名及五位小数占比。
- 失败结果：type hash 不存在或不是 xUDT/xUDT-compatible 时 Top Holders 返回 404；事实快照不可复算时 oracle 不可用。
- 不负责：代币名称、图标等展示元数据、后台调度时效、普通 sUDT 排名、缓存头和跨时间截面比较。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `RGB-ANALYTICS-RPC-01` | - [x] 不带过滤查询多个日期、network 和 indicator 的 RGB 资产统计 | 返回全部已保存记录，每项 indicator、value、network、created_at_unixtimestamp 与快照一致，value 和时间戳以精确十进制字符串返回，整体按时间戳升序 | 统计字段串位、精度丢失或图表时间顺序错误 | P0 |
| `RGB-ANALYTICS-RPC-02` | - [x] 分别使用单个 `network`、单个 indicator、逗号分隔多个 indicators 以及两种过滤组合查询 | 结果严格等于同时满足所给 network 和 indicator 集合的记录；省略某过滤时不限制该维度，时间顺序保持升序 | 过滤使用并集代替交集、逗号解析错误或过滤后顺序变化 | P1 |
| `RGB-ANALYTICS-RPC-03` | - [x] 在固定日末截面复算 `ft_count` 和 `dob_count` | `global/ft_count` 等于截至日末已索引 xUDT 与 xUDT-compatible 数量，`global/dob_count` 等于截至日末 Spore collection 数量；恰在下一毫秒出现的对象不计入 | 资产类别、截面边界或毫秒单位错误导致累计数漂移 | P0 |
| `RGB-ANALYTICS-RPC-04` | - [x] 在固定日末截面复算 Bitcoin 与 CKB 的 `transactions_count` | `btc/transactions_count` 等于 Bitcoin 交易时间不晚于日末的记录数；`ckb/transactions_count` 等于实现约定的 xUDT 相关交易数与 DOB transfer 交易数之和 | BTC/CKB 网络串位、未来交易提前计入或交易统计来源遗漏 | P0 |
| `RGB-ANALYTICS-RPC-05` | - [ ] 同一 CKB 交易既关联 xUDT 又关联 DOB transfer | 待确认：`ckb/transactions_count` 应按唯一交易计 1 次，还是按两个资产集合各计 1 次；选定语义需在统计接口保持稳定 | 名为交易数的指标因跨资产重叠被不可预期地重复计数 | P1 |
| `RGB-ANALYTICS-RPC-06` | - [x] 在固定截面复算 BTC 与 CKB `holders_count`，覆盖一个 Bitcoin 地址映射多个持仓 CKB 地址、一个 CKB 地址多种已发布资产及零余额账户 | BTC 持有人按有正余额且属于目标资产类型的映射后 Bitcoin 地址去重；CKB 持有人按正余额 CKB 地址去重；同一地址的多资产不重复，零余额不计入 | 持有人按账户行数重复、映射地址未合并或零余额被计入 | P0 |
| `RGB-ANALYTICS-RPC-07` | - [x] 使用不存在的 type hash、sUDT type hash 或其他非 xUDT 类型请求 Top Holders | 返回 404 且不返回其他代币的持有人数据 | 类型校验缺失导致 sUDT 混入 RGB 排名或未知哈希命中错误对象 | P1 |
| `RGB-ANALYTICS-RPC-08` | - [x] 一个 Bitcoin 地址映射多个持有同一目标 xUDT 的 CKB 地址，且每个账户 amount 均为正 | Top Holders 中该 Bitcoin 地址仅出现一次，network 为 `btc`，amount 等于所有映射 CKB UDT 账户的整数和 | Bitcoin 所有者被拆成多名持有人、余额漏加或重复 | P0 |
| `RGB-ANALYTICS-RPC-09` | - [x] 目标 xUDT 同时由 Bitcoin 映射 CKB 地址和没有 Bitcoin 映射的普通 CKB 地址持有 | 已映射 CKB 地址只进入对应 Bitcoin 地址聚合，不再以 CKB 地址重复出现；未映射账户以 CKB 地址返回且 network 为 `ckb` | 同一余额跨 BTC/CKB 两侧重复排名，或普通 CKB 持有人被错误排除 | P0 |
| `RGB-ANALYTICS-RPC-10` | - [x] BTC 与 CKB 两侧合计超过十名正余额持有人，金额顺序交错 | 先在各侧取得候选持有人后按全量 amount 合并降序，返回全局前 10 名而不是两侧各自前十的简单拼接顺序；每个地址至多出现一次 | 网络分组顺序覆盖真实余额排名，或返回超过十名 | P0 |
| `RGB-ANALYTICS-RPC-11` | - [x] 候选持有人 amount 超过 `2^53`，且第 10、11 名或相邻名次的差额小于双精度可分辨范围 | amount 保持整数原始单位，排名按精确整数比较后取前十，低位差异不因浮点转换丢失 | 大额 xUDT 使用浮点排序导致错误持有人进入或跌出 Top 10 | P0 |
| `RGB-ANALYTICS-RPC-12` | - [x] 核对普通余额、总供应量为零保护及需要舍入的持仓占比 | `position_ratio` 使用该地址精确 amount 除以目标 UDT total_amount，并按五位小数稳定格式化；total_amount 为零时占比为 `0` | 占比使用错误分母、整数截断、舍入漂移或除零 | P1 |
| `RGB-ANALYTICS-RPC-13` | - [x] 目标 xUDT 没有任何正余额账户 | 返回空 `data` 数组，不返回零余额持有人或占位排名 | 已清空资产仍显示历史持有人 | P2 |
| `RGB-ANALYTICS-RPC-14` | - [ ] 多个候选持有人 amount 相同且并列跨越第 10 名边界 | 待确认：相同 amount 应使用哪一个稳定次级排序键决定成员与顺序；重复请求和主/测试网各自结果必须稳定 | 并列余额因数据库返回顺序变化导致 Top 10 抖动 | P1 |
| `RGB-ANALYTICS-RPC-15` | - [x] 独立统计快照、CKB RPC/Indexer 或 Bitcoin 地址映射 oracle 在核对期间不可用或截面不一致 | 将受影响网络和统计截面标记为 oracle 不可用，不把跨截面差异判成 API 错误；另一网络独立执行 | 上游延迟或快照漂移产生虚假统计与排名回归 | P1 |

## 本轮需要确认

- `RGB-ANALYTICS-RPC-05`：同时属于 xUDT 与 DOB 的一笔 CKB 交易应计一次还是按两个集合各计一次；当前实现为两集合数量相加。
- `RGB-ANALYTICS-RPC-14`：Top 10 同额持有人的稳定次级排序键。
