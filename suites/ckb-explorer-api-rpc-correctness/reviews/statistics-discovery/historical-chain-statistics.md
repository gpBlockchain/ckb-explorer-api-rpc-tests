# Historical Chain Statistics 测试评审

评审范围：`GET /api/v1/daily_statistics/:id`、`GET /api/v1/block_statistics/:id`、`GET /api/v1/epoch_statistics/:id`、`GET /api/v1/distribution_data/:id`、`GET /api/v2/monitors/daily_statistics`。

源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：读取 Explorer 后台任务按已索引链状态生成的 Daily、Block、Epoch 和分布历史，并报告 Daily 任务是否按日更新。
- 输入：各 `:id` 选择一个指标或以连字符组合受支持指标；Epoch 统计可传 `limit`；Miner Address Distribution 可在指标名中携带 Checkpoint 天数。
- 成功结果：选定封闭日、Epoch 或区块快照后，历史值可按相同边界复算；Daily 缓存 1 天并按记录版本和指标隔离，Epoch `limit` 选取最新 N 条后仍升序输出。
- 失败结果：非法指标返回明确的 422；RPC 传输失败、结果缺失或复算窗口重组时按不可用判定源处理，Daily 生成停滞由监控状态明确报告。
- 不负责：实时首页统计、供给模型和外部统计源；标注为 `unused` 的 `block_statistics` 是否继续作为公开兼容面留待本轮确认。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `HIST-STATS-RPC-01` | - [x] 请求任一有效 Daily 指标的完整历史序列 | 只返回所选指标及公共时间字段，记录按 `created_at_unixtimestamp` 严格升序 | 指标串值、历史倒序或时间字段丢失 | P0 |
| `HIST-STATS-RPC-02` | - [x] 对封闭自然日复算交易数、累计地址数、Live Cell 与 Dead Cell 数 | 当日交易数仅含日窗口，地址和 Cell 指标与截止日快照及其累计语义一致 | 日窗偏移或把累计量误算为日增量 | P0 |
| `HIST-STATS-RPC-03` | - [x] 对封闭自然日复算平均 Hash Rate、平均难度、Uncle Rate 与总手续费 | 各值使用当日区块、Uncle 和交易的对应公式；手续费保持 Shannon 精确整数语义 | 难度权重、Uncle 分母或手续费单位错误 | P0 |
| `HIST-STATS-RPC-04` | - [x] 复算 DAO 存款、存款人、占用容量、锁定容量、流通量、Treasury 与流动性指标 | 各容量类指标与同一日末状态及既定供给关系一致，不混用 CKB 与 Shannon | 日末状态错位、DAO 去重错误或容量单位漂移 | P0 |
| `HIST-STATS-RPC-05` | - [x] 请求 HODL Wave、Holder Count 与活跃地址合约分布 | 分桶总量与对应日快照总体一致，桶间不重复，Holder 和活跃地址计数可从索引复算 | 分桶边界重叠、漏桶或重复计数 | P1 |
| `HIST-STATS-RPC-06` | - [x] 用连字符组合两个有效 Daily 指标并在缓存期内重复请求，再更新记录版本后请求 | 组合响应同时含两项且顺序一致；同版本重复结果稳定，版本变化后不沿用旧缓存 | 组合指标互相覆盖或缓存未按指标和版本隔离 | P1 |
| `HIST-STATS-RPC-07` | - [x] 请求不受支持的 Daily 指标 | 返回 HTTP 422 与错误码 `1024`，不回退为默认指标 | 非法 Daily 指标泄露其他统计 | P1 |
| `HIST-STATS-RPC-08` | - [ ] 请求 `block_statistics` 的 Difficulty、Hash Rate、Live Cell 或 Dead Cell 序列 | 待确认：该 `unused` 路由是继续返回 Epoch 大于 2 且按记录升序的兼容数据，还是从公开测试范围移除 | 未确认弃用状态导致测试固化废弃行为或遗漏兼容承诺 | P1 |
| `HIST-STATS-RPC-09` | - [x] 请求 Epoch Difficulty、Uncle Rate、Hash Rate、Epoch Time 或 Epoch Length 并按链数据复算 | 值与每个 Epoch 首尾区块、区块和 Uncle 数、难度及时长一致，结果按 Epoch 升序 | Epoch 边界、时长单位或 Uncle 统计错误 | P0 |
| `HIST-STATS-RPC-10` | - [x] 以 `limit=N` 请求 Epoch 指标，覆盖 `N=1` 与多个记录 | 仅选最新 N 个 Epoch，最终仍按 Epoch 升序；未带 `limit` 时返回全部可用 Epoch | `limit` 取最早记录、少一条或反向排序 | P1 |
| `HIST-STATS-RPC-11` | - [x] 请求 Epoch 统计的公共最大区块、最大交易与时间字段 | 每个 Epoch 的最大值来自该 Epoch 内真实记录且公共字段不因所选指标改变 | 最大值跨 Epoch 串值或指标分支漏公共字段 | P1 |
| `HIST-STATS-RPC-12` | - [x] 请求 Address Balance、Block Time、Epoch Time、Epoch Length 或 Nodes Distribution，或用连字符组合其中多个指标 | 返回最新 Daily 记录中的对应分布，组合结果各字段独立且时间戳指向同一最新记录 | 读取旧记录、组合字段覆盖或时间点不一致 | P1 |
| `HIST-STATS-RPC-13` | - [x] 请求 `distribution_data/average_block_time` | 返回完整 Rolling Average Block Time 序列及当前指标标识，保留序列原有顺序 | 特殊分支误读 Daily 快照或改变序列顺序 | P1 |
| `HIST-STATS-RPC-14` | - [x] 请求 `miner_address_distribution7` 与 `miner_address_distribution90` | 分别统计当前时刻前 7 日和 90 日区块，按 Miner Hash 聚合并以出块数降序返回主要项、其余合并为 `other`；各项之和等于窗口区块数 | Checkpoint 混用、矿工漏聚合或 `other` 计数错误 | P1 |
| `HIST-STATS-RPC-15` | - [ ] 请求形如 `miner_address_distribution30` 的未实现 Checkpoint | 待确认：限制为仅接受 7/90 并返回 HTTP 422，或为任意通过校验的天数实现确定响应 | 正则校验接受参数但业务分支返回空值 | P1 |
| `HIST-STATS-RPC-16` | - [x] 请求其他不受支持的 Distribution 或 Epoch 指标 | 返回 HTTP 422 与错误码 `1024`，不返回近似指标 | 非法指标被静默接受 | P1 |
| `HIST-STATS-RPC-17` | - [x] 最新 Daily 记录日期等于应用时区的昨日时请求监控接口 | 返回 `status=ok` | 统计已按时生成却触发错误告警 | P0 |
| `HIST-STATS-RPC-18` | - [x] 最新 Daily 记录存在但日期不是昨日时请求监控接口 | 返回 `status=error`，不把陈旧统计报告为正常 | Daily 任务停滞未被监控发现 | P0 |

## 本轮需要确认

- `HIST-STATS-RPC-08`：标注为 `unused` 的 `/api/v1/block_statistics/:id` 是保留兼容行为，还是从公开测试范围移除。
- `HIST-STATS-RPC-15`：Miner Address Distribution 的合法 Checkpoint 是否仅限 7 日和 90 日；若是，其他数字应采用哪种错误响应。
