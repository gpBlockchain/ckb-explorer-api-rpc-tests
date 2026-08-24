# V2 NFT 转移与 CSV RPC 正确性用例评审

评审范围：在公开主网和测试网分别核对 `GET /api/v2/nft/collections/:collection_id/transfers`、`GET /api/v2/nft/collections/:collection_id/items/:item_id/transfers`、`GET /api/v2/nft/collections/:collection_id/items/:item_id/transfers/:id`、`GET /api/v2/nft/transfers`、`GET /api/v2/nft/transfers/download_csv` 和 `GET /api/v2/nft/transfers/:id` 的链上事件、父资源隔离、过滤、排序、分页、范围和行上限
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：六个 GET 入口展示集合、Item 或全局 NFT 转移历史和单条详情，并按集合导出带交易、动作、地址、手续费和 UTC 时间的 CSV。
- 输入：列表接受 collection、Item、`token_id`、`from`、`to`、`address_hash`、`transfer_action`、`tx_hash` 和 `page`；详情接受 transfer ID；CSV 接受 `collection_id`、起止毫秒时间戳和起止区块高度。
- 取样：主网和测试网独立选择链上可稳定重建的 m-NFT、NRC-721、Spore/DID mint、normal transfer 和 destruction 事件；同网络 RPC 用目标交易、输入引用的上一笔交易和所在区块推导事件。CoTA 事件另按本轮确认的 Aggregator 事实基准处理。
- 成功结果：每个链上 NFT 状态变化恰好映射为正确 action、from/to、Item 和 CKB 交易；父资源范围、过滤、分页和 CSV 范围不会漏项、重复或串入其他集合/Item。
- 失败结果：指出网络、集合、Item、transfer ID、交易哈希、字段或 CSV 行、API 值、RPC 原值与推导值；缺失或父资源不匹配不返回其他 NFT 的事件。
- 不负责：双 Explorer 兼容性、媒体类型、缓存、CSV 响应头与通用转义、远程 NFT 元数据内容，以及 DAS、Bitcoin 和 RGB 专项数据。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `NFT-TX-RPC-01` | 已确认交易消费一个 NFT Cell 并生成同一 Type Script 的新 NFT Cell，Lock Script owner 发生变化 | 转移记录 action 为 `normal`，from 等于输入 Cell Lock Script 地址，to 等于输出 Cell Lock Script 地址，Item/Token ID 和 transaction 哈希、区块高度、时间戳与同网络 RPC 一致，事件只出现一次 | 普通转移误判为 mint/burn、from/to 反转、Item 串线或重复事件 | P0 |
| `NFT-TX-RPC-02` | 已确认交易生成 NFT Cell 且没有同 Type Script 的 NFT 输入 | 转移记录 action 为 `mint`，from 为 null，to 为输出 owner，Item 和交易字段与 RPC 一致 | 铸造被误判为普通转移、虚构发送方或遗漏 mint 事件 | P0 |
| `NFT-TX-RPC-03` | 已确认交易消费 NFT Cell 且没有同 Type Script 的输出 | 转移记录 action 为 `destruction`，from 为输入 owner，to 为 null，Item 状态变为 burnt，交易字段与 RPC 一致 | 销毁事件遗漏、被误判为转移或销毁后 Item 仍保持 normal | P0 |
| `NFT-TX-RPC-04` | 一笔交易同时 mint、转移或销毁多个不同 Type Script 的 NFT Item | 每个 Item 按自身输入输出产生且仅产生一个正确事件，不同 Type Script、集合和 owner 不互相配对 | 批量交易中 NFT 事件被合并、交叉匹配、重复或漏记 | P1 |
| `NFT-TX-RPC-05` | 查询包含多个 Item 和三类 action 的集合转移列表 | data 精确包含该集合全部已收录转移且不含其他集合，按当前 `transaction_id desc` 规则稳定排序，每项链上字段正确 | 集合范围失效、转移漏同步或顺序不稳定导致翻页重复漏项 | P0 |
| `NFT-TX-RPC-06` | 查询跨集合和标准的全局转移列表 | data 包含全部已收录 NFT 转移且每项保持正确集合、Item、action、from/to 和交易身份，按当前 `transaction_id desc` 规则稳定排序 | 全局列表漏标准、重复事件或 Item/集合嵌套错误 | P0 |
| `NFT-TX-RPC-07` | 从全局列表取得 transfer ID 后调用 `GET /api/v2/nft/transfers/:id` | 详情与列表同一记录的 action、from、to、Item 当前信息和 transaction 字段完全一致，并可由同网络 RPC 证明事件 | 列表 ID 指向错误详情或详情链上字段漂移 | P0 |
| `NFT-TX-RPC-08` | 分别使用 `from`、`to`、`address_hash`、`transfer_action`、`tx_hash` 以及可同时满足的组合过滤全局或集合转移 | from/to 只匹配对应方向，address_hash 匹配任一方向，action 和交易哈希精确匹配，组合条件取交集且不改变事件字段 | 地址方向混淆、过滤条件被忽略或使用并集扩大结果 | P1 |
| `NFT-TX-RPC-09` | from、to 或 address_hash 使用格式合法但未收录的地址或 Lock Script Hash | 待确认：结果应为空还是返回地址不存在错误；不得因内部 nil 关联而匹配 mint 的空 from 或 destruction 的空 to，当前源码存在这种误匹配风险 | 未知地址返回无关 mint/burn 事件或过滤范围意外扩大 | P1 |
| `NFT-TX-RPC-10` | 集合转移列表分别使用集合数字 ID、SN 和不存在的集合标识 | 数字 ID 与 SN 得到相同集合事件；不存在集合按当前源码返回 HTTP 200 和空 data，不混入全局事件 | 集合定位不一致或缺失集合回退成全局查询 | P1 |
| `NFT-TX-RPC-11` | 集合同时含多个 Item，使用 collection_id 与 token_id 查询指定 Item 转移 | 只返回该集合内该 Token ID 的全部事件；不存在 Token ID 返回空 data，其他 Item 和其他集合同 Token ID 均不出现 | Token ID 过滤被忽略或跨集合匹配 | P1 |
| `NFT-TX-RPC-12` | 调用 `GET /api/v2/nft/collections/:collection_id/items/:item_id/transfers` 查询 Item 转移历史，并用不匹配的 collection_id 或 item_id 重放 | 只返回父集合中指定 Item 的事件；父集合与 Item 不匹配时返回空 data 或 404，绝不返回整个集合历史；当前源码未读取路由的 item_id | 嵌套 Item 转移列表越权扩展到整个集合或错误 Item | P0 |
| `NFT-TX-RPC-13` | 调用 Item 嵌套转移详情，并把有效 transfer ID 放入不匹配的 collection_id 或 item_id 路径 | 仅当 transfer 属于指定父集合和 Item 时返回详情；父资源不匹配返回 HTTP 404，当前源码只按 transfer ID 查找 | 嵌套详情忽略父资源导致跨集合或跨 Item 数据泄漏 | P0 |
| `NFT-TX-RPC-14` | 对集合级和全局转移列表请求默认页、相邻页和超过末页的 page | 相邻页按确定顺序连续且无重复遗漏，超过末页返回空 data；待确认：`pagination` 保持当前直接序列化 Pagy 对象的结构，还是与 collections/items 统一为 `pagy_metadata` 字段 | 翻页重复漏项、overflow 返回旧页或三类 NFT 列表分页结构不一致 | P1 |
| `NFT-TX-RPC-15` | 请求不存在的全局 transfer ID，或嵌套路径中不存在的 transfer ID | 返回 HTTP 404 且不返回任何其他事件或成功详情 | 缺失 ID 误命中、错误资源泄漏或内部异常暴露 | P1 |
| `NFT-TX-RPC-16` | 对 CoTA mint 和 transfer 事件核对 action、from/to、Item owner 与关联 CKB 交易 | 待确认：是否配置同网络 CoTA Aggregator 作为 SMT 事件事实基准；若未配置，只核对关联 CKB 交易锚点，并将 action、from/to 和 owner 标记为外部事实基准不可用 | 用普通 NFT Cell 输入输出错误推导 CoTA 事件，或 Aggregator 漏同步未被发现 | P1 |
| `NFT-TX-RPC-17` | 分别用集合数字 ID 和 SN 导出包含 mint、normal、destruction 的 NFT 转移 CSV | 两种标识导出相同集合事件；表头精确为 `Txn hash,Blockno,UnixTimestamp,NFT ID,Method,NFT From,NFT to,TxnFee(CKB),date(UTC)`，每个事件一行且不含其他集合 | CSV 集合范围、列映射、表头或事件行缺失错误 | P0 |
| `NFT-TX-RPC-18` | 核对 CSV 中三类 action、空地址、手续费和 UTC 日期 | normal、destruction、mint 分别映射为 `Transfer`、`Burn`、`Mint`；缺失 from/to 使用 `/`；手续费由 RPC 输入输出以 Shannon 精确推导后换算为 CKB，UTC 日期由毫秒时间戳确定转换 | 动作映射错误、空地址错位、手续费精度丢失或时间单位/时区错误 | P1 |
| `NFT-TX-RPC-19` | 使用等于边界交易时间戳或区块高度的 start/end 参数，并组合日期与区块范围导出 | 起止时间和高度均为闭区间，组合条件取交集；CSV 仅包含同时满足范围的集合事件，边界事件各出现一次 | 范围端点被排除、条件使用并集或边界事件重复 | P1 |
| `NFT-TX-RPC-20` | 集合有超过 500 条符合条件的转移记录时导出 CSV | 除表头外最多 500 行，选取 `token_transfers.id desc` 的最新 500 条且无重复，主网和测试网均使用配置上限 500 | 导出无界、取到最旧记录或批处理改变限制与顺序 | P1 |
| `NFT-TX-RPC-21` | CSV 的 collection_id 缺失或指向不存在集合 | 待确认：将 collection_id 明确定义为必填并返回稳定 4xx，还是支持无 collection_id 的全局导出；当前 exporter 会在缺失 collection 时访问空对象 | 全局命名路由因缺参触发内部错误，或意外导出所有集合 | P1 |
| `NFT-TX-RPC-22` | CSV 使用反向范围、无匹配范围以及不能解析为数字的时间或高度参数 | 无匹配或反向范围返回仅表头 CSV；待确认：畸形数值统一返回参数 4xx，还是沿用当前异常行为，且不得返回未过滤数据 | 非法范围绕过过滤、产生 500 或意外导出完整历史 | P1 |

## 本轮需要确认

- `NFT-TX-RPC-09`：不存在地址过滤应返回空结果还是地址错误，并明确不得匹配空 from/to。
- `NFT-TX-RPC-14`：Transfers 分页响应统一使用 `pagy_metadata`，还是保留当前 Pagy 对象结构。
- `NFT-TX-RPC-16`：是否接入 CoTA Aggregator 作为转移事件事实基准。
- `NFT-TX-RPC-21`：CSV collection_id 是必填参数还是支持全局导出。
- `NFT-TX-RPC-22`：畸形范围参数的稳定 4xx 契约。
