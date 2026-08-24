# Fiber 统计快照正确性用例评审

评审范围：核对 Fiber Graph 每日统计列表、indicator 时间序列、聚合公式、窗口和异常输入
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：返回最近 7 个完整 Fiber 统计快照，或按合法 indicator 返回最近 14 个时间点。
- 输入：`GET /api/v2/fiber/statistics`，以及 `GET /api/v2/fiber/statistics/:id` 的 `total_nodes`、`total_channels`、`total_capacity`、`created_at_unixtimestamp` indicator。
- 成功结果：快照按时间倒序，计数、容量、均值、中位数和流动性可由同日 Fiber Graph 与 CKB funding Cell 无损推导；indicator 只投影目标值和时间。
- 失败结果：无效 indicator 返回确定的领域参数错误；Fiber 或 CKB oracle 不可用时只标记对应日期的事实基准不可用。
- 不负责：Peer 本地 Channel 统计、Graph 列表自身筛选、通用缓存响应头和跨 Explorer 兼容性。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `FIBER-STATS-RPC-01` | 存在超过 7 个按日生成的统计快照时请求统计列表 | 仅返回 `created_at_unixtimestamp` 最新的 7 项并严格倒序，每项含节点数、Channel 数、总容量、容量/费率均值和中位数、流动性及时间，日期不重复 | 统计窗口错误、旧数据挤掉最新数据或顺序反转 | P0 |
| `FIBER-STATS-RPC-02` | 对一个稳定日期的 Fiber Graph 快照重算节点数、Channel 数和总容量 | `total_nodes` 等于当前未软删除 Graph Node 数，`total_channels` 等于当前未软删除 Graph Channel 数，`total_capacity` 等于这些 Channel 容量的 Shannon 整数和；API 十进制字符串与推导值精确一致 | 删除资源仍计入、Channel 漏计或大容量发生浮点精度损失 | P0 |
| `FIBER-STATS-RPC-03` | 稳定快照含奇数和偶数数量的不同 Channel 容量及双向费率，核对平均数与中位数 | 容量均值、容量中位数、双向费率均值和费率中位数按确认的舍入规则与 Graph 字段推导值一致；空集合不除零且返回稳定空值或零值契约 | 中位数索引错误、方向费率漏计、整数类型截断或空集合崩溃 | P1 |
| `FIBER-STATS-RPC-04` | 稳定快照同时包含开放 CKB Channel、多个 UDT Channel、关闭及软删除 Channel | `total_liquidity` 只统计当前开放关系，每个 Channel 恰好一次；CKB 以 Shannon、各 UDT 以链上最小单位按 type hash 聚合，amount/decimal 为无损字符串并带正确发布状态 | 同一 Channel 按两端 Node 重复计数、关闭流动性残留、资产串组或大整数失真 | P0 |
| `FIBER-STATS-RPC-05` | 分别以四个合法 indicator 请求超过 14 个快照的详情 | 每个响应只返回目标 indicator 和 `created_at_unixtimestamp` 的最近 14 项，按时间倒序且值为十进制字符串；同一时间点与统计列表中的对应字段一致 | indicator 投影混入其他字段、窗口错误或列表/详情值不一致 | P0 |
| `FIBER-STATS-RPC-06` | 请求未知、空白或仅 index 支持而详情未声明的 indicator | 待确认：统一返回结构化 V2 参数错误，还是保留当前未捕获 `ArgumentError` 行为；失败不生成、删除或修改任何统计快照 | 非法 indicator 触发 500、错误契约漂移或读取请求改变统计数据 | P1 |
| `FIBER-STATS-RPC-07` | 数据库为空或只有少于 7/14 个快照时分别请求列表和合法 indicator | 返回按时间倒序的全部现有项且不填充虚构日期；完全为空时 `data` 是空数组 | 数据不足时重复旧快照、补零伪造历史或空集合响应崩溃 | P2 |
| `FIBER-STATS-RPC-08` | 容量或费率均值/中位数产生非整数结果 | 待确认：API 保留精确小数、采用指定舍入规则，还是按当前整数列类型截断；确认后的列表与 indicator 详情不得通过二进制浮点产生平台相关结果 | 统计精度契约不明确导致跨环境差异或静默截断 | P1 |

## 本轮需要确认

- `FIBER-STATS-RPC-06`：无效 indicator 的稳定 V2 错误状态和错误对象。
- `FIBER-STATS-RPC-08`：非整数均值与中位数的精度及舍入规则。
