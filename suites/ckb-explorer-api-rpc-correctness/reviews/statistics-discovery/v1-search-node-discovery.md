# V1 Search & Node Discovery 测试评审

评审范围：`GET /api/v1/external/stats/:id`、`GET /api/v1/suggest_queries`、`GET /api/v1/nets`、`GET /api/v1/nets/:id`。

源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：查询 Explorer 已索引 Tip、识别搜索词对应对象，并发现当前 Explorer 实例配置的 CKB 节点信息；不依赖第三方统计源。
- 输入：`external/stats/:id` 仅定义 `tip_block_number`；`suggest_queries` 接受 `q` 与 `filter_by`，其中 `filter_by=0` 进入聚合分支；`nets/:id` 支持 `addresses`、`node_id`、`version` 与 `local_node_info`。
- 成功结果：搜索结果按输入类别返回对应链上或索引对象；节点字段与 Explorer 配置的同一 CKB RPC 实例一致，并允许 `local_node_info` 在 4 小时缓存期内保持快照。
- 失败结果：搜索无匹配返回明确的 404，非法节点字段返回明确的 422；配置节点 RPC 不可用或响应缺失时按不可用判定源处理。
- 不负责：UDT、NFT、Bitcoin 与 Fiber 搜索结果的领域正确性，以及任意其他同网络公共节点与当前实例之间的版本、Node ID 或监听地址一致性。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `DISCOVERY-RPC-01` | 请求 `external/stats/tip_block_number` | 返回十进制字符串，数值等于 Explorer 当前已索引最新区块号 | 轻量 Tip 接口返回旧值、错误类型或误接第三方数据 | P0 |
| `DISCOVERY-RPC-02` | 请求 `external/stats` 的非 `tip_block_number` 标识 | 响应体不包含统计结果，也不把未知标识回退为 Tip | 未知标识静默返回错误指标 | P1 |
| `DISCOVERY-RPC-03` | `suggest_queries` 以区块高度或完整区块哈希查询 | 返回唯一对应区块，区块号与哈希可由 CKB RPC 相互校验 | 数字或区块哈希被错误分类 | P0 |
| `DISCOVERY-RPC-04` | `suggest_queries` 以完整 CKB 交易哈希查询 | 返回唯一对应 CKB 交易且哈希与 CKB RPC 一致 | 交易哈希命中错误对象或跨类别串值 | P0 |
| `DISCOVERY-RPC-05` | `suggest_queries` 以完整地址、短地址、Lock Hash 或受支持脚本标识查询 | 返回与该标识对应的地址或脚本对象，完整地址与短地址规范化后指向同一 Lock Script | 地址规范化或脚本识别产生错误结果 | P1 |
| `DISCOVERY-RPC-06` | 使用 `filter_by=0` 搜索至少可命中两个受本领域支持类别的非数字查询 | 返回所有受支持命中且无重复对象；数字查询仍只返回对应区块 | 聚合分支漏项、重复或错误扩大数字查询 | P1 |
| `DISCOVERY-RPC-07` | 查询不存在对象，或在聚合分支提交长度小于 2 的查询 | 返回 HTTP 404 与错误码 `1018`，不返回近似对象 | 无匹配时伪造结果或短查询引发全量扫描 | P1 |
| `DISCOVERY-RPC-08` | 请求 `nets` 列表 | 返回配置节点的 `addresses`、`node_id`、`version` 完整信息，三项与同一实例的 `local_node_info` RPC 完全一致 | 将实例专属节点信息与任意公共节点混比 | P0 |
| `DISCOVERY-RPC-09` | 分别请求 `nets/addresses`、`nets/node_id`、`nets/version` 与 `nets/local_node_info` | 单字段结果等于完整节点信息中的对应字段，`local_node_info` 包含全部三项 | 选择器映射错误或列表与详情不一致 | P1 |
| `DISCOVERY-RPC-10` | 请求不受支持的 `nets/:id` | 返回 HTTP 422 与错误码 `1020`，不泄露缓存中的其他节点字段 | 非法选择器被接受或回退为完整节点信息 | P1 |
| `DISCOVERY-RPC-11` | 在同一实例的 `local_node_info` 四小时缓存有效期内重复请求，并在缓存过期后再次请求 | 有效期内各节点详情选择器读取同一快照；过期后的首次读取以配置节点 RPC 新结果刷新，字段不混用新旧快照 | 缓存未命中导致实例状态抖动、永久陈旧或字段跨快照拼接 | P2 |

## 本轮需要确认

- 无。
