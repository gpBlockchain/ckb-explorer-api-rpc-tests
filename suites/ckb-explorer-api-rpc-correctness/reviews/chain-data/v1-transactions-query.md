# V1 交易条件查询 RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB Indexer 与节点 RPC 为事实基准，核对 `POST /api/v1/transactions/query` 按地址返回的已提交交易集合、顺序、分页成员、列表详情和地址净容量变化，并确认省略地址时的产品行为
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 CKB 地址返回该地址参与的已提交交易列表及前 10 个输入输出预览；本评审只判断查询成员和标准链数据字段是否与同网络 Indexer/节点一致，并要求主网、测试网各自产生独立结论。
- 公开主网：Explorer `https://mainnet-api.explorer.nervos.org/api`；CKB RPC/Indexer `https://mainnet.ckbapp.dev/`。
- 公开测试网：Explorer `https://testnet-api.explorer.nervos.org/api`；CKB RPC/Indexer `https://testnet.ckbapp.dev/`。
- 输入：每个网络分别向 Explorer `POST /api/v1/transactions/query` 提交 JSON `address`，并按用例省略或传入 `page`、`page_size`；Indexer 使用该地址对应完整 Lock Script 调用 `get_transactions`，节点 RPC 使用 `get_transaction`、`get_block` 和输入引用的上一笔交易。
- 取样：每个网络先用高度 0 的哈希校验 Explorer/RPC 链身份，并确认 Explorer tip 不高于 RPC 且最多落后 5 个区块；完整集合与分页使用交易历史可穷尽且同时含正、负、零净容量变化的已确认地址，预览边界使用关联交易输入或输出超过 10 项的地址。Indexer 的输入/输出事件按交易哈希去重，一笔交易即使同一地址出现多次也只计一次；比较期间若 API 哈希序列、Indexer 游标结果或交易所属区块改变，则该网络本次样本按快照变化或重组处理，不作数据正确性结论。
- 成功结果：地址查询结果严格等于 Indexer 对完整 Lock Script 返回的唯一已提交交易集合，并按区块高度、区块内交易索引降序排列；分页是该序列的确定切片，行字段和预览可由节点 RPC 精确核对，`income` 按该地址当前交易输出容量减输入引用容量计算且以 Shannon 整数比较。
- 失败结果：指出网络、查询地址、页码、列表位置、交易哈希、Indexer 事件、RPC 状态与区块哈希、字段路径、API 值及推导后的期望值；单个公开 URL 超时、Indexer/RPC 缺少游标结果、交易、上一笔交易或区块时，只将该网络标记为事实基准不可用，不影响另一网络的结论。
- 不负责：双 Explorer 环境兼容性、媒体类型、无效或未收录地址的错误响应、分页参数格式及最大页限制、JSON:API 本地 `id`、`created_at`、`create_timestamp`、Cells 的数据库消费状态、Median Time、标签、Cell 类型以及 RGB/Bitcoin/UDT/DAO/NFT/Fiber 等协议扩展注解；这些行为由通用契约或协议专项评审负责。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `TX-QUERY-RPC-01` | - [x] 在公开主网和测试网分别选择交易历史可由 Indexer 完整穷尽的已确认地址，以足够大的 `page_size` 查询第一页 | API `transaction_hash` 集合严格等于 Indexer `get_transactions` 输入/输出事件按哈希去重后的完整集合；同一交易即使该地址出现在多个输入输出中也只返回一次，`meta.total` 等于唯一交易数量，没有地址无关、遗漏或重复交易 | 地址过滤失效、Indexer 事件被误当多笔交易、成员漏同步、重复返回或总数按 Cells 而非交易计数 | P0 |
| `TX-QUERY-RPC-02` | - [x] 在公开主网和测试网分别对同一已确认地址核对完整查询结果的先后顺序 | API 哈希序列严格等于 Indexer 事件按区块高度降序、同区块交易索引降序排列后首次出现的唯一交易序列；同一交易的多个输入输出事件不改变其列表位置 | 地址时间线反转、同区块顺序错误、按 IO 索引或哈希排序，或去重后顺序漂移 | P0 |
| `TX-QUERY-RPC-03` | - [x] 在公开主网和测试网分别对同一地址省略分页参数，并以 `page_size=3` 查询第 1、2 页 | 默认请求返回唯一交易序列前 10 项；显式第 1、2 页分别严格等于完整序列的前 3 项和后 3 项切片且互不重复；`meta.total` 保持唯一交易总数，`meta.page_size` 等于实际页大小，`meta.total_pages` 等于向上取整页数，最后不足一页时不补入其他交易 | 默认页大小错误、页偏移重叠或跳项、过滤后仍使用全网总数、总页数计算错误或尾页填入无关交易 | P1 |
| `TX-QUERY-RPC-04` | - [x] 在公开主网和测试网分别对地址查询第一页的每笔普通交易调用节点 RPC 并取得所属区块 | 每行 `transaction_hash`、`block_number`、`block_timestamp` 分别等于 RPC 交易哈希、状态区块高度和区块时间戳，RPC 状态为 `committed` 且区块内索引大于 0，`is_cellbase` 为 `false`；`display_inputs_count`、`display_outputs_count` 分别等于 RPC 输入和输出总数 | 行关联到错误交易或区块、混入未提交/Cellbase 交易、时间进制错误，或输入输出总数使用预览长度 | P0 |
| `TX-QUERY-RPC-05` | - [x] 在公开主网和测试网分别选择地址查询结果中含多个普通输入、且引用输出覆盖有无 Type Script 的交易 | `display_inputs` 按 RPC 输入顺序返回前 `min(10, inputs数量)` 项；每项引用交易哈希、输出索引、`since.raw`、容量、占用容量、对应网络地址及存在时的 `type_script` 等于输入和被引用 RPC 输出的确定值 | 输入预览乱序、引用解析错误、预览数量越界、容量精度丢失、地址跨网络编码或 Type Script 错位 | P1 |
| `TX-QUERY-RPC-06` | - [x] 在公开主网和测试网分别选择地址查询结果中含多个普通输出、且覆盖有无 Type Script 的交易 | `display_outputs` 按 RPC 输出索引返回前 `min(10, outputs数量)` 项；每项当前交易哈希、输出索引、容量、占用容量、对应网络地址及存在时的 `type_script` 等于同索引 RPC 输出和 `outputs_data` 的确定值 | 输出预览乱序或错配交易、预览数量越界、容量或数据占用计算错误、地址网络或 Type Script 映射错误 | P1 |
| `TX-QUERY-RPC-07` | - [x] 在公开主网和测试网分别以关联交易输入或输出数量超过 10 的地址查询包含该宽交易的页面 | 行内 `display_inputs_count`、`display_outputs_count` 保留完整 RPC 数量，但两个预览数组分别只返回前 `min(10, 实际数量)` 项；第 10 项仍对应 RPC 第 10 个输入引用或输出，之后项目不出现在预览中 | 预览数组未截断拖大响应、完整计数被错误截为 10、边界出现 9/11 项或截取错误的一端 | P1 |
| `TX-QUERY-RPC-08` | - [x] 在公开主网和测试网分别选择查询结果同时含正、负和零净变化的地址，并解析每笔交易中属于该地址 Lock Script 的全部输入输出 | 每行 `income` 等于当前 RPC 输出中属于查询地址的容量总和减去输入引用中属于该地址的容量总和；正值、负值和零值均保持符号，按 Shannon 整数精确比较且同一 Cell 只计一次 | 地址收支方向反转、只算输入或输出、多个同地址 Cells 漏算/重复、手续费影响丢失或大整数精度错误 | P0 |
| `TX-QUERY-RPC-09` | - [x] 在公开主网和测试网分别省略 `address` 调用查询接口 | 按控制器中已存在的无地址分支返回最近普通交易的第一页且 `income` 为空，不因序列化阶段访问空地址而返回 HTTP 500 | 无地址路径在生产环境固定 500、源码分支长期不可达，或调用方无法判断该接口是否支持全局查询 | P0 |

## 本轮需要确认

- 无；9 条用例及“保留源码已有全局查询分支”的预期均已确认。当前公开主网和测试网省略地址均返回 HTTP 500，自动化据此给出独立失败结果。
