# V2 NFT 集合与持有人 RPC 正确性用例评审

评审范围：在公开主网和测试网分别核对 `GET /api/v2/nft/collections`、`GET /api/v2/nft/collections/:id` 和 `GET /api/v2/nft/collections/:collection_id/holders` 的链上集合身份、元数据、统计、过滤、排序、分页与持有人数量
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：集合列表和详情展示 m-NFT、NRC-721、Spore/DID 与 CoTA 集合，持有人接口按当前正常 Item 的 owner 地址分组计数。
- 输入：集合列表接受 `type`、`tags`、`union`、`sort`、`page`；详情接受数据库数字 ID 或 SN；持有人接受集合数字 ID 或 Type Script Hash，以及 `address_hash`、`sort`。
- 取样：主网和测试网独立选择已确认且 RPC/Indexer 可稳定取得的 m-NFT、NRC-721、Spore/DID 集合与交易；CoTA 样本另按本轮确认的外部事实基准处理。观测到重组、RPC/Indexer 缺失结果或 CoTA 聚合器不同步时，对应样本标记为事实基准不可用。
- 成功结果：链上集合身份、可解码元数据、活跃 Item 与持有人统计、过滤成员、排序和分页都与同网络 RPC、Indexer 及确定性协议解码结果一致。
- 失败结果：指出网络、集合 SN/Type Script、接口、字段或地址、API 值、原始链上值及推导值；资源缺失按接口当前错误契约返回，不串入其他集合数据。
- 不负责：双 Explorer 兼容性、媒体类型、缓存、远程图片或 URI 内容、RGB/Bitcoin 关联，以及 `created_at`、`updated_at` 等数据库本地字段。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `NFT-COLL-RPC-01` | 在公开主网和测试网分别从集合列表选择已确认的 m-NFT、NRC-721、Spore/DID 集合，再用列表返回的数字 ID 和 SN 查询详情 | 两种查询指向同一集合；`standard`、`sn`、Type Script、creator 地址和定义 Cell 时间戳分别与同网络链上 Type Script、Lock Script 和区块时间一致，非 CoTA 集合的 `sn` 等于 Type Script Hash | 集合关联到错误脚本、创建者、网络或定义 Cell，列表与详情身份漂移 | P0 |
| `NFT-COLL-RPC-02` | 对具有可解析 Class Cell 的 m-NFT 集合核对列表与详情元数据 | `name`、`description` 和 `icon_url` 等于同网络 RPC 返回的最新有效 m-NFT Class Cell Data 的协议解码值 | m-NFT Class Data 解码、版本选择或集合元数据同步错误 | P1 |
| `NFT-COLL-RPC-03` | 对具有 Factory Cell 的 NRC-721 集合核对列表与详情元数据 | `name`、`symbol` 和 `icon_url` 等于同网络 RPC Factory Cell Data 解码得到的名称、截取后的符号和 Base Token URI | NRC-721 Factory 关联或数据解码错误导致集合身份和展示信息失真 | P1 |
| `NFT-COLL-RPC-04` | 对有 Cluster 的 Spore/DID 集合核对列表与详情元数据 | 集合 SN、creator、名称和描述来自同网络对应 Cluster Type Script、Lock Script 与 Cluster Cell Data；Item 的 Cluster ID 不会关联到其他集合 | Spore Cluster 关联、Data 解码或 DID/Spore 集合归类错误 | P1 |
| `NFT-COLL-RPC-05` | 对同时包含正常 Item、已销毁 Item、重复 owner 和 24 小时内外转移的集合核对统计字段 | `items_count` 等于正常 Item 数，`holders_count` 等于正常 Item 的不同 owner 数，`h24_ckb_transactions_count` 等于最近 24 小时转移所涉及的不同已确认 CKB 交易数；已销毁 Item 不计入前两项 | 销毁资产仍计入供应量或持有人、同一交易被重复计数、24 小时边界错误 | P0 |
| `NFT-COLL-RPC-06` | 使用 `type` 分别查询 m-NFT、NRC-721、Spore 和 CoTA 集合 | 每次结果只包含 `standard` 等于请求值的集合，省略 `type` 时不因标准而漏掉已收录集合 | 标准过滤失效或跨标准集合混入结果 | P1 |
| `NFT-COLL-RPC-07` | 使用两个有效非 RGB 标签分别执行默认标签过滤和 `union=true` 过滤 | 默认结果仅包含同时具有全部请求标签的集合；union 结果包含至少具有一个请求标签的集合；返回集合自身的 `tags` 能证明成员关系 | 标签 AND/OR 语义颠倒、过滤条件丢失或错误集合入选 | P1 |
| `NFT-COLL-RPC-08` | `tags` 只含未知值，或有效标签与未知值混合 | 待确认：未知标签应被忽略并仅按有效标签过滤，还是返回空结果或参数错误；当前源码会移除未知标签，全部未知时等同未设置标签过滤 | 拼写错误静默扩大查询范围，或客户端升级后标签过滤语义突变 | P2 |
| `NFT-COLL-RPC-09` | 分别按 `transactions`、`holder`、`minted`、`timestamp` 使用 asc 和 desc 排序，并构造主排序值相同的集合 | 排序依次使用 24 小时交易数、持有人数、正常 Item 数和定义 Cell 时间戳；方向正确，并以 `block_timestamp desc` 稳定处理并列项 | 排序别名映射、方向或并列顺序错误导致翻页重复和漏项 | P1 |
| `NFT-COLL-RPC-10` | 省略 sort、使用未知 sort 字段，或提供非法排序方向 | 默认按 `id desc`；未知字段回退到 ID；非法或缺失方向按源码回退为 asc，且重复请求顺序稳定 | 非法排序触发 SQL 错误、无序结果或与当前回退契约漂移 | P2 |
| `NFT-COLL-RPC-11` | 对集合列表请求默认页、相邻页和超过末页的 page | 每页成员符合确定排序且相邻页无重复或遗漏，`pagination` 的页码、总页数、总数和实际成员数一致，超过末页返回空 data 而不复用末页 | 分页元数据错误、跨页重复漏项或 overflow 行为改变 | P1 |
| `NFT-COLL-RPC-12` | 对同一集合构造多个正常 Item 归属同一 owner、其他 owner 各有不同数量，并加入已销毁 Item | holders 的 `data` 以 owner 地址为键，每个值等于该 owner 当前正常 Item 数；同地址只出现一次，已销毁 Item 不增加数量 | 持有人重复、数量错误或销毁 Item 仍被计入 | P0 |
| `NFT-COLL-RPC-13` | 分别用集合数字 ID 和有效 Type Script Hash 查询 holders，并用已存在 owner 的地址过滤 | 两种集合标识得到相同持有人映射；设置 `address_hash` 后只返回该地址及其正常 Item 数 | 集合 ID 与脚本哈希定位不一致，或地址过滤跨 owner 泄漏数据 | P1 |
| `NFT-COLL-RPC-14` | holders 按 `quantity.asc` 和 `quantity.desc` 查询具有不同持有数量的地址 | 地址按计数升序或降序返回；重复请求保持相同数量与成员，未请求 quantity 排序时不伪造数量 | 聚合后排序字段错误或数量排序方向颠倒 | P2 |
| `NFT-COLL-RPC-15` | 查询不存在的集合数字 ID、SN 或 Type Script Hash | 集合详情返回 HTTP 404 且不返回其他集合；holders 返回 HTTP 404 和 V2 code `2001` 的 token collection not found 错误对象 | 缺失集合误命中、跨集合数据泄漏或错误契约漂移 | P1 |
| `NFT-COLL-RPC-16` | holders 使用格式错误、网络不匹配、格式合法但 Explorer 未收录的地址或 Lock Script Hash | 待确认：统一返回明确的地址参数错误，还是对合法但无持仓的地址返回空 data；当前地址查询路径对 Address 与 Lock Script Hash 的缺失处理并不一致 | 无效地址被误报为集合不存在、未知 Lock Hash 意外匹配空 owner，或同类输入返回不同错误 | P1 |
| `NFT-COLL-RPC-17` | 对 CoTA 集合核对定义信息、发行者、Item/holder 数与 24 小时交易数 | 待确认：测试环境是否配置同网络 CoTA Aggregator 作为 name、symbol、description、image、owner 和事件的事实基准；若未配置，只核对关联 CKB 交易与可见 Cell 锚点，并将其余字段标记为外部事实基准不可用 | 用节点 RPC 推断 SMT/聚合器专有状态产生错误结论，或 CoTA 同步中断长期未被发现 | P1 |

## 本轮需要确认

- `NFT-COLL-RPC-08`：未知 tags 是忽略、空结果还是参数错误。
- `NFT-COLL-RPC-16`：不存在或格式错误的 Address 与 Lock Script Hash 应统一报错还是返回空持仓。
- `NFT-COLL-RPC-17`：是否为 CoTA 字段提供同网络 Aggregator 事实基准；否则只核对链上锚点。
