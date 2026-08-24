# Fiber 网络图谱正确性用例评审

评审范围：核对 Fiber Graph Node、Graph Channel、节点关联 Channel/交易、筛选关系及软删除历史，并用 Fiber RPC 与同网络 CKB 链数据交叉验证
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：展示从统一 Fiber 上游同步的网络节点和 Channel 图谱，并关联 CKB funding Cell、开放/关闭交易及地址。
- 输入：`GET /api/v2/fiber/graph_nodes`、`GET /api/v2/fiber/graph_nodes/addresses`、`GET /api/v2/fiber/graph_nodes/:node_id`、`GET /api/v2/fiber/graph_nodes/:node_id/graph_channels`、`GET /api/v2/fiber/graph_nodes/:node_id/transactions`、`GET /api/v2/fiber/graph_channels`，以及搜索、状态、地址、日期、资产、金额、排序和分页参数；oracle 为同一 Fiber RPC `graph_nodes`/`graph_channels` 与同网络 CKB RPC/Indexer。
- 成功结果：Node/Channel 身份和关系与稳定的 Fiber 上游快照一致，funding outpoint、容量、UDT 及开关交易与 CKB 链数据一致，软删除资源按接口职责可见。
- 失败结果：Node 不存在、参数非法或上游/CKB oracle 不可用时给出可定位结果，不改变已同步图谱状态。
- 不负责：人工配置 Peer 的本地 Channel 快照、聚合统计时间序列、通用分页和 HTTP 错误格式。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `FIBER-GRAPH-RPC-01` | 在稳定 Fiber Graph 快照上请求 Node 列表，并分别用精确 node name、peer ID 和 node ID 搜索 | 列表成员及搜索命中与 Fiber RPC `graph_nodes` 一致；每项名称、node/peer ID、地址、timestamp、chain hash、自动接收金额和 UDT 配置无损转换，分页不重不漏 | Graph Node 漏同步、搜索字段接错或大整数转换失真 | P0 |
| `FIBER-GRAPH-RPC-02` | 请求 Graph Node 地址集合，样本包含孤立节点、多个开放 Channel 的节点及已关闭 Channel | 仅当前未软删除 Node 出现在结果中；每个 Node 的地址来自 Fiber 上游，`connections` 是其当前未关闭且未软删除 Channel 的另一端 node ID 去重集合，孤立节点连接为空 | 把关闭/删除 Channel 当作活动连接、连接重复或方向遗漏 | P0 |
| `FIBER-GRAPH-RPC-03` | 按活动或已软删除 `node_id` 请求详情，并对活动 Node 与 Fiber 上游快照比较 | 活动和历史 Node 均可按 ID 定位；活动 Node 的身份、地址、链、时间、自动接收金额、开放 Channel 总容量、UDT 配置和连接关系正确，历史 Node 带删除时间且不伪造活动连接 | 软删除历史不可追溯、详情聚合包含已关闭 Channel或 Node 字段错配 | P0 |
| `FIBER-GRAPH-RPC-04` | 请求不存在的 `node_id` 的详情、关联 Channel 和关联交易，随后请求存在 Node | 三个不存在请求均返回 Fiber Graph Node not found 且不创建占位资源；存在 Node 的后续请求保持正常 | 成员子资源绕过 Node 存在性检查或失败请求污染图谱 | P1 |
| `FIBER-GRAPH-RPC-05` | 请求某 Node 的关联 Channel，样本同时含开放、已关闭及软删除 Channel | 返回两端任一为目标 Node 的历史全集；outpoint、两端 Node、方向更新、创建时间、费率、容量、UDT 与开关交易正确，软删除 Channel 保留历史身份和关闭证据 | 只匹配一个方向、关闭历史丢失或 Channel 关联到错误 Node | P0 |
| `FIBER-GRAPH-RPC-06` | 对 Node 关联 Channel 组合地址、open/closed 状态、日期、CKB 或 UDT type hash、最小/最大金额、排序和相邻分页 | 各过滤条件只保留同时满足条件的目标 Node Channel；CKB 用 capacity、UDT 用 funding Cell amount 比较，日期边界包含端点，排序与分页成员稳定；非法状态或反向日期返回参数错误且不改变图谱 | 资产单位混用、过滤条件丢失、边界 off-by-one 或非法参数触发不受控错误 | P1 |
| `FIBER-GRAPH-RPC-07` | 请求 Node 关联交易，样本含多个 Channel 的开放与关闭交易，并组合状态、地址、资产、金额、日期和升降序 | 每个开放/关闭事件各出现一次并标明 `is_open` 和是否 UDT；交易哈希、区块高度/时间及开关方向与同网络 CKB RPC 一致，过滤、排序和分页在事件集合上执行且无重漏 | 开关交易混淆、关闭时间取错、同一事件重复或过滤在错误层级执行 | P0 |
| `FIBER-GRAPH-RPC-08` | 请求全局 Graph Channel 列表，并分别使用 closed 状态和 funding 地址过滤 | 默认只列当前未软删除 Channel；closed 过滤只保留有关闭交易的成员，地址过滤只保留该 funding 地址的成员；返回 outpoint、两端、chain hash、更新时刻/费率、容量、UDT 和开关交易与 Fiber/CKB oracle 一致 | 全局列表泄漏软删除记录、地址归属错误或关闭状态过滤失效 | P0 |
| `FIBER-GRAPH-RPC-09` | 对全局 Graph Channel 列表提交 `status=open` | 待确认：`open` 是否应只返回无关闭交易的 Channel；源码当前仅特殊处理 `closed` 并会让 `open` 等同默认全集，确认后的行为在重复请求和分页间保持一致 | 客户端请求开放 Channel 却收到已关闭成员，或修复后仍锁定旧回退行为 | P1 |
| `FIBER-GRAPH-RPC-10` | Fiber 上游快照移除 Node/Channel 后完成一次同步，再读取列表、地址、详情和成员子资源 | Node 列表/详情保留带删除时间的历史 Node，地址集合排除已删除 Node；Node 关联 Channel 保留历史 Channel，全局 Channel 列表排除软删除 Channel，活动连接和容量不计已关闭或已删除关系 | 软删除在各接口语义不一致、历史丢失或删除资源继续污染活动聚合 | P1 |
| `FIBER-GRAPH-RPC-11` | 从 Fiber `channel_outpoint` 定位 CKB funding 输出，并检查已关闭 Channel 的消费交易 | outpoint 精确映射同网络 CKB 交易哈希和输出索引，Graph capacity 等于 funding Cell 容量，UDT type/amount 与输出一致；关闭交易确实消费该 Cell，链上对象缺失或重组时本次 CKB oracle 标记为不可用 | Fiber 图谱与错误链或错误 Cell 关联、容量/UDT 伪造及关闭交易误判 | P0 |

## 本轮需要确认

- `FIBER-GRAPH-RPC-09`：全局 `status=open` 是有效过滤条件还是按当前实现回退到默认全集。
