# V2 NFT Item RPC 正确性用例评审

评审范围：在公开主网和测试网分别核对 `GET /api/v2/nft/collections/:collection_id/items`、`GET /api/v2/nft/collections/:collection_id/items/:id` 和 `GET /api/v2/nft/items` 的 Item 成员、链上状态、owner、过滤、排序、分页及 Token ID 查询语义
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：集合级和全局列表返回当前正常 NFT Item，详情按集合与 Token ID 返回 Item、当前 Cell、Type Script、owner 和集合信息。
- 输入：集合由数字 ID 或 SN 定位；列表接受 `owner`、`standard`、`token_id`、`page`；详情 Token ID 接受十进制或 `0x` 十六进制表示。
- 取样：主网和测试网独立选择 m-NFT、NRC-721、Spore/DID 的 mint、transfer 和 destruction 链上样本，并以同网络 RPC/Indexer 解析当前或最后一个 NFT Cell；CoTA 样本另按本轮确认的 Aggregator 事实基准处理。
- 成功结果：列表成员、Token ID、collection、owner、status、Cell OutPoint/Data 和 Type Script 与链上状态及协议解码一致，过滤和分页不会跨集合或漏掉符合条件的正常 Item。
- 失败结果：指出网络、集合、Token ID、接口、字段、API 值、链上值和推导过程；缺失父资源或 Item 返回 404 且不命中 Token ID 相同的其他集合。
- 不负责：双 Explorer 兼容性、媒体类型、远程 metadata/icon 内容，以及 `created_at`、`updated_at` 的链上真实性。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `NFT-ITEM-RPC-01` | 在公开主网和测试网分别从集合列表和全局列表选择正常的 m-NFT、NRC-721、Spore/DID Item，并读取详情 | Item 的 collection、standard、owner、Cell `tx_hash/cell_index/data/status` 和 Type Script 与同网络 RPC/Indexer 的当前 NFT Cell 一致；详情和列表指向同一链上 Item | Item 关联到错误集合、owner、OutPoint、Data 或 Type Script | P0 |
| `NFT-ITEM-RPC-02` | 分别选择 m-NFT、NRC-721、Spore 和 DID Item 核对 Token ID | m-NFT Token ID 由 Token Type Script 参数对应字段无损解码，NRC-721 Token ID 由 Factory 参数中的 token id 解码，Spore/DID Token ID 由 Type Script args 解码；API 十进制字符串与大整数精确一致 | 不同 NFT 标准使用错误切片、进制或浮点转换导致 Token ID 碰撞或截断 | P0 |
| `NFT-ITEM-RPC-03` | 依次观察同一 Item 的 mint、普通转移和 destruction 状态 | mint 后 owner 为输出 Lock Script 地址且状态 normal；转移后 owner 和当前 Cell 更新为最新输出；destruction 后状态 burnt，且不再出现在正常 Item 列表 | owner 未随转移更新、旧 Cell 被当作当前 Cell或销毁资产仍显示为可持有 | P0 |
| `NFT-ITEM-RPC-04` | 集合同时含多个正常 Item 和已销毁 Item，查询集合 Item 列表 | data 精确包含该集合所有正常 Item，排除已销毁 Item；每项嵌套 collection 与父集合一致，其他集合 Item 不会混入 | 集合范围失效、销毁 Item 混入或嵌套集合信息错误 | P0 |
| `NFT-ITEM-RPC-05` | 多个集合和标准同时存在时查询全局 Item 列表 | data 包含各集合当前正常 Item 且排除全部 burnt Item；每项仍携带正确 collection 和 standard | 全局列表漏标准、重复 Item 或返回已销毁资产 | P0 |
| `NFT-ITEM-RPC-06` | 分别用集合数字 ID 和 SN 请求集合列表，并用两种标识定位同一详情样本 | 两种集合标识得到相同成员；详情中的 collection、Token ID 和链上 Cell 相同 | SN 与数据库 ID 指向不同集合或详情查到错误 Item | P1 |
| `NFT-ITEM-RPC-07` | 在全局或集合列表分别使用 owner、standard、token_id，并使用可同时满足的组合过滤 | 每个过滤条件只保留链上 owner、集合 standard 和 Token ID 匹配的正常 Item，组合条件取交集且不改变字段正确性 | 过滤条件被忽略、使用并集或跨标准/owner 泄漏 Item | P1 |
| `NFT-ITEM-RPC-08` | 使用超过 64 位的大 Token ID 构造乱序 Item 并重复查询 | 列表始终按 Token ID 数值升序，超大值不经浮点转换、不截断，分页前后顺序稳定 | 大整数排序按字符串或浮点执行，造成错序和精度丢失 | P1 |
| `NFT-ITEM-RPC-09` | 对集合与全局 Item 列表请求默认页、相邻页和超过末页的 page | 相邻页按 Token ID 顺序连续且无重复遗漏，`pagination` 的页码、总页数、总数和实际 data 数一致，超过末页返回空 data | 分页边界重复漏项、集合和全局总数混用或 overflow 返回旧页 | P1 |
| `NFT-ITEM-RPC-10` | 对同一 Spore/DID Item 分别用十进制 Token ID 和等值 `0x` 十六进制 Token ID 请求详情 | 两次响应指向同一 Item，Token ID 精确相等，前导零不改变数值身份 | 十六进制未解析、前导零形成不同 Item 或大整数转换错误 | P0 |
| `NFT-ITEM-RPC-11` | 两个集合具有相同 Token ID，分别查询详情并交叉使用另一集合父路径 | 每个父路径只返回自身集合 Item；不存在于该集合的 Token ID 返回 HTTP 404，不会命中其他集合同 ID Item | 嵌套父资源隔离失效导致跨集合 Item 泄漏 | P0 |
| `NFT-ITEM-RPC-12` | 直接请求已销毁 Item 的详情 | 待确认：保持当前源码行为返回 burnt Item 及最后链上 Cell，还是与只展示 normal 的列表一致返回 404 | 列表与详情状态语义不一致，客户端把已销毁 Item 当作当前资产 | P1 |
| `NFT-ITEM-RPC-13` | 对 CoTA Item 核对 Token ID、owner、状态、集合和交易锚点 | 待确认：是否配置同网络 CoTA Aggregator 作为 SMT Token ID、owner 和状态事实基准；若未配置，只核对关联 CKB 交易锚点，并将 Aggregator 专有字段标记为事实基准不可用 | 用普通 Cell 模型错误推导 CoTA 状态，或 Aggregator 漏同步未被发现 | P1 |
| `NFT-ITEM-RPC-14` | 请求不存在的集合 ID/SN 或集合内不存在的 Token ID | 返回 HTTP 404 且无其他集合或 Token ID 的 Item 数据；列表和详情的缺失父资源结果不携带成功数据 | 缺失资源误命中、空父集合跨范围查询或错误对象中泄漏数据 | P1 |
| `NFT-ITEM-RPC-15` | Item 详情使用 `0x` 开头但含非十六进制字符、空值或超长 Token ID | 待确认：统一返回参数错误或 404，且不得把畸形十六进制解析为 Token ID 0；当前源码直接调用字符串 hex 转换 | 畸形 ID 意外命中 Token 0、触发内部错误或不同格式产生不同状态 | P1 |
| `NFT-ITEM-RPC-16` | Item 列表的 owner 使用格式错误、网络不匹配或格式合法但 Explorer 未收录的地址 | 待确认：无持仓的合法地址返回空 data，格式或网络错误返回明确 4xx；当前地址查找对未收录 Address 与 Lock Script Hash 的处理不一致 | 未知 owner 匹配空 owner、跨网络地址被接受或查询崩溃 | P1 |

## 本轮需要确认

- `NFT-ITEM-RPC-12`：burnt Item 详情继续可见还是与正常列表一致返回 404。
- `NFT-ITEM-RPC-13`：是否接入 CoTA Aggregator 作为 Item 状态事实基准。
- `NFT-ITEM-RPC-15`：畸形十六进制 Token ID 的统一 4xx/404 契约。
- `NFT-ITEM-RPC-16`：未收录 owner 与格式/网络错误 owner 的区分方式。
