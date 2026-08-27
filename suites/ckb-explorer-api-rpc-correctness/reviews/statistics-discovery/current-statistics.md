# Current Statistics 测试评审

评审范围：`GET /api/v1/statistics`、`GET /api/v1/statistics/:id`、`GET /api/v1/statistic_info_charts`、`GET /api/v2/statistics/transaction_fees`、`GET /api/v2/statistics/contract_resource_distributed`。

源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：返回当前链统计、单指标、统计图表、交易费率和 Active 合约资源分布，并以 Explorer 已索引状态复算链上量。
- 输入：单指标通过 `statistics/:id` 选择；合约分布可传逗号分隔的 `code_hashes`，实际按 Type Hash 精确过滤；其余接口无业务查询参数。
- 成功结果：当前统计与固定 Tip 快照及既定窗口公式一致；`statistics` 使用 15 秒缓存，难度图使用 10 分钟缓存，Hash Rate 图读取按截止块保存的缓存；费率按 `transaction_fee / bytes`，合约容量从 Shannon 转为 CKB 并截断 8 位。
- 失败结果：非法单指标返回明确的 422；需要实时节点信息时仅与 Explorer 配置的同一 CKB RPC 实例比较，RPC 传输失败、结果缺失或快照重组按不可用判定源处理。
- 不负责：历史 Daily/Epoch 统计、外部市场价格、任意公共 CKB 节点的实例专属状态，以及合约业务语义本身。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `CURRENT-STATS-RPC-01` | - [x] 请求当前统计首页并固定同一 Tip 快照 | `tip_block_number`、Epoch 编号、长度和索引与已索引 Tip 一致，当前难度与该 Epoch 链上难度一致 | 首页混用不同 Tip 或 Epoch 字段错位 | P0 |
| `CURRENT-STATS-RPC-02` | - [x] 以最近配置区块窗口复算平均出块时间、最近 900 块含 Uncle 难度的 Hash Rate 与预计 Epoch 时间 | 三项等于相同快照和公式的复算结果，并分别按接口精度截断 | 时间单位、Uncle 难度或预计时间公式错误 | P0 |
| `CURRENT-STATS-RPC-03` | - [x] 复算最近 24 小时交易数与最近 100 块的每分钟交易数 | 24 小时计数只含窗口内交易；每分钟值等于窗口交易总数除以首尾块时间差分钟并截断 3 位 | 时间窗边界、分母单位或累计范围错误 | P0 |
| `CURRENT-STATS-RPC-04` | - [x] 当前未重组与已记录重组开始时间两种状态 | `reorg_started_at` 分别为空值或准确时间，其他统计不因标志变化被清空 | 重组监控状态残留或污染统计首页 | P1 |
| `CURRENT-STATS-RPC-05` | - [x] 分别请求 Tip、平均出块时间、当前难度与 Hash Rate 单指标 | 单指标值及时间戳语义与同一时刻统计首页对应字段一致 | 单指标分支与首页使用不同算法或单位 | P0 |
| `CURRENT-STATS-RPC-06` | - [x] 请求 `blockchain_info` 单指标 | 返回 Explorer 配置节点的链信息；已知旧节点告警消息被过滤，其余字段与同一节点 RPC 一致 | 将实例状态当作全网共识或漏过滤兼容告警 | P1 |
| `CURRENT-STATS-RPC-07` | - [x] 请求地址余额排名与启用 Miner Ranking 事件后的矿工排名 | 地址排名仅含正余额可见地址、最多 50 项且按余额降序；矿工排名按固定历史窗口 Base Reward 汇总并最多返回配置项数 | 排名包含隐藏或零余额地址、窗口漂移或排序反转 | P1 |
| `CURRENT-STATS-RPC-08` | - [x] 请求 `maintenance_info` 与 `flush_cache_info` | 返回当前运行时缓存记录的维护和刷新状态，不伪装成链上统计 | 将运维缓存状态错误解释为 CKB RPC 结果 | P2 |
| `CURRENT-STATS-RPC-09` | - [x] 请求不受支持的统计单指标 | 返回 HTTP 422 与错误码 `1019`，不回退为统计首页 | 非法指标被接受或返回无关统计 | P1 |
| `CURRENT-STATS-RPC-10` | - [x] 请求难度与 Uncle Rate 图表并按 Epoch 复算 | 难度点集合包含每个 Epoch 首块和每 100 块采样点，Uncle Rate 按 Epoch 升序且等于各 Epoch 的 Uncle 数除以区块数 | 抽样点遗漏、Uncle 分母错误或 Epoch 顺序反转 | P1 |
| `CURRENT-STATS-RPC-11` | - [x] 在 Hash Rate 图表缓存分别指向已有和缺失截止块时请求接口 | 命中时仅返回缓存对应截止块的去重序列，未命中时返回空数组；不同截止块缓存互不串值 | 图表缓存键碰撞、重复点或用旧数据冒充当前结果 | P1 |
| `CURRENT-STATS-RPC-12` | - [x] 请求交易费统计并复算最近 10,000 笔已提交交易 | 每项费率等于整数手续费除以交易字节数，含正确时间与确认时长；集合不超出最近 10,000 笔 | 手续费单位、字节分母或确认时间错误 | P0 |
| `CURRENT-STATS-RPC-13` | - [x] 复算最多 100 笔 Pending 交易与最近 20 个 UTC 日的费率 | Pending 零字节记录被排除、缺失字节数从节点补齐；日均值按 UTC 日和有效交易数计算 | 除零、Pending 字节数陈旧或本地时区分桶 | P0 |
| `CURRENT-STATS-RPC-14` | - [x] 请求未带过滤条件的合约资源分布 | 仅返回地址数、引用 Cell 容量和交易数均非零的 Active 合约；交易数、24 小时交易数、地址数可从当前索引复算 | 非 Active 合约混入或关联计数失真 | P1 |
| `CURRENT-STATS-RPC-15` | - [x] 以一个或多个 `code_hashes` 查询合约资源分布 | 仅返回其 Type Hash 精确命中的 Active 合约，无命中时返回空数组；`ckb_amount` 等于 Shannon 容量除以 `10^8` 并截断 8 位 | 参数名与实际 Type Hash 过滤错配、模糊命中或容量单位错误 | P1 |

## 本轮需要确认

- 无。
