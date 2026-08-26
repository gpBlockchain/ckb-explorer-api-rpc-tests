# V2 UDT 时序统计 RPC 正确性用例评审

评审范围：核对 `GET /api/v2/udt_hourly_statistics` 的跨 UDT 时间桶汇总及 `GET /api/v2/udt_hourly_statistics/:id` 的单 UDT 序列
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按持久化时间戳汇总全部 UDT 的交易数与持有人数，并返回指定已发布 UDT 的 amount、交易数和持有人数历史。
- 输入：全局列表无业务参数；详情路径使用 UDT Type Hash。
- 成功结果：聚合和单 UDT 行与固定统计截面的链上交易、Cell 原始金额及持仓分配可复算值一致，金额和计数保持任意精度十进制表示。
- 失败结果：不存在或未发布的 Type Hash 返回资源不存在；RPC、Indexer、Bitcoin 映射或统计截面无法对齐时仅标记外部事实不可用。
- 不负责：实时 UDT 目录、百分比变化、元数据更新、后台调度可靠性及通用缓存契约。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `UDT-HOURLY-RPC-01` | 多个 UDT 在相同和不同 `created_at_unixtimestamp` 有统计记录时请求全局列表 | 相同时间戳的 `ckb_transactions_count` 和 `holders_count` 分别求和后只返回一行，时间戳按降序排列；全局行不包含 amount | 时间桶未合并、跨字段混加或顺序错误 | P0 |
| `UDT-HOURLY-RPC-02` | 全局统计中的交易数、持有人数和时间戳超过 JavaScript 安全整数范围 | 三个字段都以完整十进制字符串返回，不经过浮点转换或科学计数法 | 聚合大整数在 JSON 客户端侧失真 | P0 |
| `UDT-HOURLY-RPC-03` | 已发布 UDT 在多个时间戳有统计记录时按 Type Hash 查询详情 | 只返回该 UDT 的记录，按时间戳升序；每行包含 `ckb_transactions_count`、`amount`、`holders_count`、`created_at_unixtimestamp` 的十进制字符串 | 详情混入其他 UDT、顺序反转或字段缺失 | P0 |
| `UDT-HOURLY-RPC-04` | 固定统计截面上用同网络 RPC/Indexer 复算一个受支持 UDT 的统计 | `ckb_transactions_count` 等于该 UDT 全部关联交易数，`amount` 等于关联交易所消费 UDT 原始金额总和与所生成原始金额总和的较大值，`holders_count` 等于 CKB 与 Bitcoin 分配持有人数之和；所有运算使用整数 | 统计被误当成小时增量、净发行量或浮点金额 | P0 |
| `UDT-HOURLY-RPC-05` | 已发布 UDT 的 Explorer 元数据创建时间晚于其已有统计桶，且该 UDT 已存在统计记录 | 返回该 UDT 已有的实际统计序列，不因元数据 `created_at` 晚于统计桶而强制返回空数组；记录仍按 Type Hash 隔离并按时间升序 | 把元数据创建时间误当成统计起点，错误丢弃更早的链上统计 | P2 |
| `UDT-HOURLY-RPC-06` | Type Hash 不存在、目标 UDT 未发布或格式畸形时查询详情 | 不存在和未发布返回资源不存在；待确认：格式畸形是否使用统一 Type Hash 参数错误，还是与不存在记录相同处理 | 无效 ID 触发 500 或错误公开未发布统计 | P1 |
| `UDT-HOURLY-RPC-07` | 连续执行统计生成后检查相邻 `created_at_unixtimestamp` | 待确认：接口名称为 hourly，但当前生成器从上一条记录增加 1 天并写入当天零点；需确认产品期望是逐小时还是逐日序列，确认后所有时间桶遵循同一间隔 | 调用方按小时解释实际按日数据，导致图表和增量错误 | P0 |
| `UDT-HOURLY-RPC-08` | 链数据、Bitcoin 映射、持仓分配或统计生成时点无法与 API 截面对齐 | 只将相应 amount、交易数或持有人数结论标记为事实基准不可用，并保留 API 内部聚合和排序检查；主网与测试网独立处理 | 不同时间截面或外部数据缺失制造错误差异 | P1 |

## 本轮需要确认

- `UDT-HOURLY-RPC-06`：统计序列应按小时还是按日生成；当前 worker 使用上一时间戳加 1 天并写入当天零点。
- `UDT-HOURLY-RPC-07`：畸形详情 Type Hash 是否需要 V1 相同的参数错误，还是统一按资源不存在处理。
