# Fiber Peer 正确性用例评审

评审范围：核对已配置 Fiber RPC Peer 的登记、连接验证、Channel 同步、列表聚合和详情
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：登记可连接的 Fiber RPC Peer，异步同步其 `list_channels` 结果，并展示监控 Peer 及 Channel 摘要。
- 输入：`GET /api/v2/fiber/peers` 的分页，`POST /api/v2/fiber/peers` 的 `name`、`peer_id`、`rpc_listening_addr`，以及 `GET /api/v2/fiber/peers/:peer_id` 的 Peer ID；事实基准为该登记地址的 Fiber RPC `list_channels`。
- 成功结果：创建前连接验证成功，Peer 按 `peer_id` 幂等保存并触发一次同步；列表与详情中的 Peer、READY Channel 数和余额与上游快照一致。
- 失败结果：上游不可连接、参数无效或 Peer 不存在时返回领域错误，既有 Peer 与 Channel 状态不被部分覆盖。
- 不负责：全网 Graph Node/Channel、单个 Channel 完整余额详情、通用分页与 HTTP 错误格式。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `FIBER-PEER-RPC-01` | - [x] 对已完成同步的多个配置 Peer 请求列表，并分别从每个 Peer 的 Fiber RPC 读取 `list_channels` | 列表成员和 Peer 身份与配置一致；每个 Peer 的 `channels_count` 仅统计上游 `CHANNEL_READY` Channel，`total_local_balance` 等于这些 Channel 的十六进制本地余额无损解码之和，其他状态不计入 | Peer 漏同步、状态筛选错误或大余额转换失真 | P0 |
| `FIBER-PEER-RPC-02` | - [x] 按存在的 `peer_id` 请求详情，并与该 Peer 的 Fiber RPC Channel 快照比较 | 返回目标 Peer 的 ID、RPC 地址和时间字段；`fiber_channels` 中每个 Channel 的远端 peer ID、channel ID、状态名和 flags 与上游一致，不混入其他本地 Peer 的 Channel | Peer 查询串档或 Channel 归属错误 | P0 |
| `FIBER-PEER-RPC-03` | - [x] 提交可连接的 RPC 地址、新 `peer_id` 和名称创建 Peer | 服务先成功调用目标 RPC `list_channels`，再持久化一个 Peer、返回 204 并触发该 Peer 的一次异步 Channel 同步；同步完成后列表和详情反映上游 Channel | 未验证连接就写入、成功未触发同步或同步错误 Peer | P0 |
| `FIBER-PEER-RPC-04` | - [x] 对既有 `peer_id` 重复提交相同及新增 RPC 地址，并更新名称 | 始终只有一个 Peer；RPC 地址按原顺序合并去重、名称更新为最后一次成功值，每次成功创建请求至多触发一次目标 Peer 同步，既有 Channel 不因登记重复而复制 | 重复登记产生重复 Peer/地址/Channel 或覆盖已有可用地址 | P1 |
| `FIBER-PEER-RPC-05` | - [x] 提交缺失 `peer_id`、空或畸形 RPC 地址、连接超时、非 JSON 响应或返回 Fiber RPC error 的创建请求 | 返回 Fiber Peer 参数错误，不创建或修改 Peer，不触发同步任务，既有 Peer 和 Channel 快照保持原值 | 探测失败仍落库、异步任务访问无效目标或失败请求破坏现有监控 | P0 |
| `FIBER-PEER-RPC-06` | - [x] 请求不存在的 `peer_id`，随后请求一个存在的 Peer | 不存在项返回 Fiber Peer not found；后续存在项仍返回自身详情，失败查询不创建占位 Peer 或 Channel | 未知 Peer 被静默当作空结果或查询失败污染状态 | P1 |
| `FIBER-PEER-RPC-07` | - [ ] 上游 Fiber RPC 在 Explorer 最近一次同步后新增、更新或移除 Channel，再读取 Peer 列表和详情 | 待确认：允许的同步延迟及过期数据标识是什么；在确认窗口内 Explorer 可暂时保持旧快照，超过窗口后必须与同一上游 RPC 一致，上游传输失败只标记该 Peer oracle 不可用 | 无同步时效标准导致永久陈旧数据被当作正确，或瞬时上游变化被误判为索引错误 | P1 |

## 本轮需要确认

- `FIBER-PEER-RPC-07`：Peer/Channel 上游同步允许的最大延迟，以及响应是否需要暴露快照时间。
