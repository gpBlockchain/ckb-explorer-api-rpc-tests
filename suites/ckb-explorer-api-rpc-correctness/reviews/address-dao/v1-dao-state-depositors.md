# V1 Nervos DAO 状态与存款人 RPC 正确性用例评审

评审范围：在公开主网和测试网分别核对 `GET /api/v1/contracts/:id`、`GET /api/v1/dao_depositors` 与 `GET /api/v1/dao_depositors/download_csv` 的 DAO 汇总状态、存款人排名和导出边界
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：返回固定合约 `nervos_dao` 的累计与最新日统计指标，列出当前 DAO 存款金额最高的 100 个地址，并按时间或区块边界导出 DAO 存款人容量。
- 输入：合约详情接收 `id=nervos_dao`；存款人列表无分页参数；CSV 接收 `start_date`、`end_date`、`start_number`、`end_number`。
- 取样与事实基准：主网和测试网分别用同网络 CKB Indexer 枚举 DAO 存款和取款 Cell，用节点 RPC 取交易、区块头、DAO 字段和经济状态；所有 CKB 金额以 Shannon 整数推导。
- 成功结果：合约汇总值及变化量与同一观测高度和日统计锚点一致；存款人列表和 CSV 与对应窗口的 DAO Cell 本金汇总一致。
- 失败结果：非 `nervos_dao` 合约名返回合约不存在错误；CSV 无数据时仍返回可解析表头；非法筛选边界的产品约定需本轮确认。
- 不负责：DAO 交易详情、地址专属活动、通用请求头、CSV 下载响应头和与链上事实无关的显示格式。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `DAO-STATE-RPC-01` | - [x] 在主网和测试网分别以同一已确认高度统计尚未进入取款阶段的 DAO 存款 Cell，请求 `GET /api/v1/contracts/nervos_dao` | API `total_deposit` 的 Shannon 整数精确等于所有未被取款请求消费的 DAO 存款 Cell capacity 之和，已进入取款阶段的本金不重复计入 | DAO 存款本金漏计、重复计入取款阶段 Cell 或金额精度丢失 | P0 |
| `DAO-STATE-RPC-02` | - [x] 在两个网络分别统计至少有一个未消费 DAO 存款事件的不同地址 | API `depositors_count` 等于未进入取款的已处理存款事件中的去重地址数，同一地址多个存款 Cell 只计一人 | 按 Cell 数而非地址数计算存款人，或取款后仍残留无存款地址 | P0 |
| `DAO-STATE-RPC-03` | - [x] 在两个网络分别汇总截至观测高度已完成利息领取的 DAO 交易 | API `claimed_compensation` 的 Shannon 整数等于所有已处理 `issue_interest` 事件值之和，每个事件值都与存款及取款区块 DAO 字段推导的利息一致 | 已领取利息累计漏失、重复或使用非精确整数计算 | P0 |
| `DAO-STATE-RPC-04` | - [x] 在两个网络分别对仍在存款阶段和已进入取款第一阶段但未最终领取的 DAO Cell 计算当前利息 | API `unclaimed_compensation` 的 Shannon 整数等于未完成取款阶段 Cell 的可领利息与按当前 tip DAO 值计算的未发起取款存款利息之和 | 未领利息漏计任一 DAO 阶段、使用过期 tip 或重复计入已领利息 | P0 |
| `DAO-STATE-RPC-05` | - [x] 在同一最新日统计锚点下请求 DAO 合约状态，并取当前累计值与该日统计的对应值 | `deposit_changes`、`depositor_changes`、`unclaimed_compensation_changes`、`claimed_compensation_changes` 分别精确等于当前值减最新日统计值，金额差全程保留 Shannon 精度 | 变化量使用不同时间锚点、减数方向相反或小数转换导致统计跳变 | P1 |
| `DAO-STATE-RPC-06` | - [x] 请求两个网络的 DAO 合约状态并取得同一最新日统计记录 | `average_deposit_time`、`mining_reward`、`deposit_compensation`、`treasury_amount` 均与最新日统计同名值一致，其中 CKB 金额值以 Shannon 字符串精确比较 | 合约详情混用过期日统计或金额序列化精度错误 | P1 |
| `DAO-STATE-RPC-07` | - [x] 在主网和测试网分别以当前分数 Epoch 为起点，按 2190 个 Epoch 一年和每 8760 个 Epoch 减半的发行参数重算 APC | API `estimated_apc` 等于按 DAO 模型重算并截断到 4 位小数的年化百分比，不因主网和测试网 Epoch 位置不同而交叉比较 | 减半周期、分数 Epoch 或截断规则错误使预估年化收益偏离 | P1 |
| `DAO-STATE-RPC-08` | - [x] 以 `nervos_dao` 以外的合约名请求 `GET /api/v1/contracts/:id` | 返回 HTTP 404 且 JSON:API 错误码为 `1021`、标题为 `Contract Not Found`，不返回 DAO 汇总快照 | 固定 DAO 合约路由对任意名称返回相同数据 | P1 |
| `DAO-STATE-RPC-09` | - [x] 在两个网络分别取有多个未发起取款 DAO 存款 Cell 的地址，请求 `GET /api/v1/dao_depositors` | 每个返回地址的 `dao_deposit` Shannon 整数等于其当前未发起取款的 DAO 存款 Cell capacity 之和，只包含金额大于 0 的存款人，`average_deposit_time` 为按每个 CKByte 锁定时长加权且截断到 3 位小数的天数 | 地址本金汇总错误、已取款地址残留或平均存款时间未按金额加权 | P0 |
| `DAO-STATE-RPC-10` | - [x] 当有超过 100 个当前 DAO 存款人时请求存款人列表，并在另一无存款人的可控观测窗口请求同一接口 | 有数据时最多返回 `dao_deposit` 最高的 100 个地址且金额递减，第 101 名不出现；无存款人时返回空 `data` 数组 | 排名上限失效、排序反向或无数据时复用过期排名 | P1 |
| `DAO-STATE-RPC-11` | - [ ] 存在多个 `dao_deposit` 完全相同且恰好跨越第 100 名边界的存款人时重复请求列表 | 待确认：同额存款人是否必须按地址或另一稳定键排序；当前实现只按 `dao_deposit` 降序，无法保证第 100 名边界成员稳定 | 同额边界在请求间抖动，导致某些存款人随机出现或消失 | P1 |
| `DAO-STATE-RPC-12` | - [x] 在两个网络分别不带边界导出 `GET /api/v1/dao_depositors/download_csv`，样本同时包含未发起取款的存款 Cell 和仍未最终领取的取款阶段 Cell | CSV 表头为 `Address,Capacity`；每个地址一行，容量等于其 Live 存款 Cell 本金加上 Live 取款阶段 Cell 所对应原存款 Cell 本金，同地址多 Cell 合并，CSV 展示容量转回 Shannon 后与 RPC 精确一致 | 存款人导出漏掉取款第一阶段本金、按 Cell 重复地址或丢失 Shannon 精度 | P0 |
| `DAO-STATE-RPC-13` | - [x] 导出包含恰好等于 `start_date`、`end_date` 及边界外 DAO 存款或取款 Cell 的时间窗口 | 起止毫秒时间戳均包含，只汇总区块时间位于闭区间内的目标 Cell，边界外 Cell 不影响任何地址的 CSV 容量 | 日期开闭边界错误或先全局汇总后过滤导致窗口金额失真 | P1 |
| `DAO-STATE-RPC-14` | - [x] 导出包含恰好位于 `start_number`、`end_number` 区块及边界外 DAO Cell 的高度窗口，并同时提交冲突的日期边界 | 起止高度转为对应区块时间戳后均包含，高度覆盖同侧日期参数，只汇总闭区间内的 DAO Cell 本金 | 高度映射错块、边界排除或参数优先级不一致 | P1 |
| `DAO-STATE-RPC-15` | - [x] 在过滤窗口内没有 DAO 存款或取款 Cell 时导出存款人 CSV | 返回仅包含 `Address,Capacity` 表头的可解析 CSV，不返回过期地址行 | 无数据时丢失表头或泄漏其他窗口数据 | P2 |
| `DAO-STATE-RPC-16` | - [ ] CSV 导出提交非数字日期、不存在的 `start_number` 或 `end_number`、起点大于终点的边界 | 待确认：这些无效边界应返回哪个 4xx 错误及错误对象；当前源码对非数字日期可抛出未包装异常，不存在高度可变成未设边界 | 无效筛选触发 500 或静默扩大导出范围 | P1 |

## 本轮需要确认

- `DAO-STATE-RPC-11`：同额存款人及第 100 名边界是否需要稳定二级排序键。
- `DAO-STATE-RPC-16`：无效日期、未知区块高度和反向边界的统一 4xx 错误约定。
