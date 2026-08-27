# Fiber Channel 正确性用例评审

评审范围：核对已配置监控 Peer 的单个 Fiber Channel 详情及两端 Peer 关系
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 `channel_id` 返回从配置 Peer 的 Fiber RPC `list_channels` 同步得到的状态、余额和 local/remote Peer 信息。
- 输入：`GET /api/v2/fiber/channels/:channel_id` 的 Channel ID；事实基准为所属配置 Peer 的 Fiber RPC Channel 快照。
- 成功结果：Channel 身份、状态、余额、时间和两端 Peer 与同一上游记录一致，十六进制余额无损转换为整数。
- 失败结果：Channel 不存在时返回领域 not found；上游不可用时将事实基准标记为不可用而非数据差异。
- 不负责：Graph Channel funding outpoint、开关交易、全网拓扑、Peer 创建和通用 HTTP 契约。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `FIBER-CHANNEL-RPC-01` | - [x] 请求一个所属配置 Peer 已同步且上游仍存在的 Channel | `channel_id`、`state_name`、`state_flags` 与 Fiber RPC 完全一致；`local_balance`、`offered_tlc_balance`、`remote_balance`、`received_tlc_balance` 等于上游十六进制值无损解码结果，创建/更新/关闭时间对应同一 Channel | Channel 身份或状态错配、TLC 余额字段互换及大整数精度丢失 | P0 |
| `FIBER-CHANNEL-RPC-02` | - [x] 本地 Peer 和远端 Peer 都已登记，且两个 Peer 还有其他 Channel | `local_peer` 是同步该记录的所属 Peer，`remote_peer` 是上游 Channel 的 `peer_id` 对应 Peer；两端各自的名称和 RPC 地址正确，不受其他 Channel 影响 | local/remote 方向颠倒或按 Channel ID 串到其他 Peer | P0 |
| `FIBER-CHANNEL-RPC-03` | - [ ] 上游 Channel 的远端 Peer 尚未登记到 Explorer | 待确认：`remote_peer` 返回字段为空的对象、返回 `null`，还是把 Channel 视为关系不完整错误；无论选择哪种契约，Channel 自身身份、状态和余额仍保持可读取且不会创建虚假 Peer | 缺失远端 Peer 时响应形状漂移、详情整体崩溃或产生占位数据 | P1 |
| `FIBER-CHANNEL-RPC-04` | - [x] 请求不存在的 `channel_id`，随后请求一个存在的 Channel | 不存在项返回 Fiber Channel not found；失败查询不创建 Channel，后续存在项仍返回正确详情 | 未知 Channel 静默返回空对象或查询产生副作用 | P1 |
| `FIBER-CHANNEL-RPC-05` | - [ ] 上游更新 Channel 状态或余额后，在 Peer 同步窗口内和窗口后重复读取详情 | 待确认：采用与 Peer 相同的最大同步延迟；窗口后详情必须与同一上游 Channel 一致，上游不可用或同一 Channel 在两次取证间变化时本次 oracle 标记为不可用 | 永久陈旧 Channel 被判为正确或动态更新被误报 | P1 |

## 本轮需要确认

- `FIBER-CHANNEL-RPC-03`：未登记远端 Peer 的稳定响应表示。
- `FIBER-CHANNEL-RPC-05`：Channel 快照允许的最大同步延迟。
