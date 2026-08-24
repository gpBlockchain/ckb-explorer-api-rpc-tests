# V2 脚本链上关联 RPC 正确性用例评审

评审范围：在公开主网和测试网分别核对 `GET /api/v2/scripts/ckb_transactions`、`GET /api/v2/scripts/deployed_cells` 与 `GET /api/v2/scripts/referring_cells` 的合约 Cell Dependency、部署 Cell、Referring Cells、过滤分页和 Zero Lock 特殊分支
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 `code_hash/hash_type` 返回使用对应合约 Cell Dependency 的 CKB 交易、脚本部署 Cells 以及 Lock/Type Script Code Hash 引用该脚本的 Live Cells。
- 输入：三个接口均接收 `code_hash`、`hash_type`、`page`、`page_size`；交易接收 `restrict`；Referring Cells 接收 `args`、`address_hash`。
- 取样与事实基准：主网和测试网分别从已登记脚本的部署与实际合约 out-point 出发，用 CKB RPC `get_transaction`、`get_live_cell` 和 Indexer `get_cells`、`get_transactions` 核对；`restrict=true` 需要额外执行轨迹才能独立证明脚本实际被运行。
- 成功结果：交易的 Cell Dependencies、部署 out-point 和 Referring Cell 成员与同网络链上数据一致，容量以 Shannon 整数比较，主网和测试网分别给出结论。
- 失败结果：未知 Code Hash、缺失或不支持的 Hash Type 返回 HTTP 404；未匹配 `args` 和非法地址的预期错误需本轮确认。
- 不负责：脚本目录和人工元数据、地址详情、代币扩展解析、通用 HTTP 错误格式。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `SCRIPT-REL-RPC-01` | 对三个脚本关联接口分别使用 Type Hash 与 `hash_type=type`，以及 Data Hash 与 `hash_type=data/data1/data2` | Type Hash 只选中 `type_hash` 匹配的登记，Data 类 Hash 只选中 `data_hash` 匹配的登记，三个接口均基于同一组选中合约，不跨 Hash Type 混入其他脚本 | Code Hash 查询分支反向或三个关联视图使用不同合约集合 | P0 |
| `SCRIPT-REL-RPC-02` | 在两个网络分别选择具有多个实际合约 Cell out-point 和多笔 Cell Dependency 交易的登记脚本，请求 `GET /api/v2/scripts/ckb_transactions` 且省略 `restrict` | 返回的每笔交易在 RPC `cell_deps` 中至少有一个 out-point 指向选定脚本的实际合约 Cell，所有具有该依赖的可观测交易都出现 | 交易按部署 Cell 而非实际 dep-group/code Cell 关联，或遗漏合约升级后的新 out-point | P0 |
| `SCRIPT-REL-RPC-03` | 对包含 `code` 和 `dep_group` Cell Dependency 的脚本交易请求关联交易列表 | 每笔交易的 `cell_deps` out-point、`dep_type`、脚本 Code Hash、Hash Type 和 Lock/Type 用途与 RPC Dependency 及选定登记一致 | Dep Type 丢失、dep-group 被当作普通 code Cell 或依赖被注解到错脚本 | P0 |
| `SCRIPT-REL-RPC-04` | 在主网和测试网分别对选中关联交易的完整响应字段与同网络 RPC 交易和区块比较 | `tx_hash`、区块高度与时间戳、手续费、Cell/Header Dependencies、witnesses、输入输出、存活 Cell 变化、容量参与值、字节数和交易状态与 RPC 或可验证推导值一致 | 关联成员正确但展示了其他交易的字段或容量数值失真 | P0 |
| `SCRIPT-REL-RPC-05` | 对超过一页的脚本关联交易使用默认分页、指定 `page_size` 和越界 `page` | 交易按区块高度降序、同区块按交易索引降序，页间无重复无遗漏，`meta.total` 和 `meta.page_size` 正确，越界页返回空数组 | 依赖 join 改变顺序、分页计数被 join 行数放大或页间成员漂移 | P1 |
| `SCRIPT-REL-RPC-06` | 同一脚本的关联交易同时包含实际使用和仅声明但未执行的 Cell Dependency，分别省略 `restrict` 和使用 `restrict=true` | 待确认：省略 `restrict` 时返回全部声明依赖的交易；`restrict=true` 是否承诺只返回执行轨迹证明脚本实际被调用的交易，标准 CKB RPC 不暴露此 `is_used` 分类 | 把声明依赖误称为实际执行，或在无独立事实基准时得出错误正确性结论 | P0 |
| `SCRIPT-REL-RPC-07` | 同一交易同时依赖选定 Code Hash 关联的多个实际合约 Cells | 待确认：关联交易列表是否必须按交易哈希去重；当前 join 查询未显式 `distinct`，可能为同一交易返回多行 | 重复交易放大总数、挤占分页并使用户误判脚本活跃度 | P1 |
| `SCRIPT-REL-RPC-08` | 在两个网络分别对具有正常部署 Cell 的脚本请求 `GET /api/v2/scripts/deployed_cells` | 每个返回 Cell 的 `tx_hash` 和 `cell_index` 指向选定合约登记的部署 out-point，capacity、状态、区块、占用容量、Type Hash、DAO 字段和关联脚本标识与 RPC/Indexer 一致，金额以 Shannon 精确比较 | 部署记录指向错误 out-point、返回其他脚本的 Cell 或金额失真 | P0 |
| `SCRIPT-REL-RPC-09` | 同一 Code Hash 匹配多个登记且部署 Cells 超过一页时，对 deployed cells 使用指定 `page`、`page_size` 和越界页 | 每个选中登记只返回其部署 Cell，页间无重复无遗漏，`meta.total` 和 `meta.page_size` 与选中数量及请求一致，越界页为空 | Code Hash 多登记分页丢 Cell、总数错计或页间重复 | P1 |
| `SCRIPT-REL-RPC-10` | 在两个网络分别为标记 `is_lock_script=true` 的登记请求 `GET /api/v2/scripts/referring_cells` | 只返回 Lock Script `code_hash` 等于选定合约 Type Hash 或 Data Hash 且当前为 Live 的 Cells，每个 out-point、capacity、脚本和数据与 RPC/Indexer 一致 | Lock Script 查询误用 Type Script 列、混入其他 Code Hash 或 Dead Cells | P0 |
| `SCRIPT-REL-RPC-11` | 在两个网络分别为标记 `is_type_script=true` 的登记请求 referring cells | 只返回 Type Script `code_hash` 等于选定合约 Type Hash 或 Data Hash 且当前为 Live 的 Cells，无 Type Script、其他 Code Hash 和 Dead Cells 不出现 | Type Script 关联误查 Lock Script、对空 Type 解引用或状态过滤失效 | P0 |
| `SCRIPT-REL-RPC-12` | 对超过一页且具有不同区块时间和输出索引的 Referring Cells 使用默认分页、指定 `page_size` 和越界页 | 结果按区块时间降序、同时间按 `cell_index` 降序，在全局查询上限内页间无重复无遗漏，`meta.total`、`meta.page_size` 和越界空页正确 | 先分页后排序、页间抖动或总数忽略全局上限 | P1 |
| `SCRIPT-REL-RPC-13` | 对选定脚本的 Referring Cells 提交一个已存在 Type Script `args` 的 `args` 参数 | 待确认：`args` 是对原 Referring Cell 集合做交集过滤，还是按当前实现将任意具有该 Type Script Args 的 Cell 与原集合做并集 | 名为过滤的参数扩大成员范围，混入与选定 Code Hash 无关的 Cells | P0 |
| `SCRIPT-REL-RPC-14` | 对包含多地址 Referring Cells 的脚本使用有效 CKB 地址或 Lock Script Hash 作为 `address_hash` | 结果只包含选定脚本原始 Referring Cell 集合中归属该 Lock Script 的 Cells，每个成员的 Lock Script Hash 与查询地址解析值一致 | 地址过滤未限定原脚本集合、地址解析到错网络或只比较显示字符串 | P1 |
| `SCRIPT-REL-RPC-15` | Referring Cells 提交不存在的 Type Script `args`、非法地址或不存在的合法地址 | 待确认：各类无匹配过滤应返回空列表还是明确 4xx 错误；当前实现可对空 Type Script 或 NullAddress 调用不存在的方法并引发 500 | 无数据的正常过滤变成服务器异常，或不同无匹配输入行为不一致 | P1 |
| `SCRIPT-REL-RPC-16` | 以 Zero Lock Code Hash 请求脚本关联交易 | 返回输入或输出归属 Zero Lock 地址账本的交易，按内部交易顺序降序分页，每笔交易的 Zero Lock Cell 成员可由 RPC 脚本证明 | Zero Lock 无真实部署 Cell 时落入普通 Dependency 分支而返回空或无关交易 | P1 |
| `SCRIPT-REL-RPC-17` | 以 Zero Lock Code Hash 请求 deployed cells | 返回 `deployed_cells` 空数组、`meta.total=0` 且 `meta.page_size` 等于请求值，不伪造 Zero Lock 部署 out-point | 为协议级 Zero Lock 伪造合约 Cell 或进入空对象序列化异常 | P1 |
| `SCRIPT-REL-RPC-18` | 以 Zero Lock Code Hash 请求 referring cells | 只返回 Lock Script Code Hash 为全零且当前 Live 的 Cells，所有 out-point、capacity 和脚本字段与 RPC/Indexer 一致 | Zero Lock Referring Cells 被部署 Cell 特殊分支一并清空或混入普通脚本 | P1 |
| `SCRIPT-REL-RPC-19` | 对三个脚本关联接口省略 `hash_type`、使用不支持的 `hash_type` 或在支持的 Hash Type 下提交未登记的非空 Code Hash | 三个接口均返回 HTTP 404 且无关联数据，不回退到所有脚本、Zero Lock 或空成功数组 | Hash Type 被静默改写或未知 Code Hash 静默命中错脚本 | P1 |
| `SCRIPT-REL-RPC-20` | 对三个脚本关联接口使用已支持的 `hash_type` 但省略 `code_hash` | 待确认：三个接口应返回哪个统一 4xx 错误；当前实现可按空 Type/Data Hash 命中无关登记并暴露其交易和 Cells | 缺失 Code Hash 扩大查询范围并泄漏无关链上关联 | P0 |

## 本轮需要确认

- `SCRIPT-REL-RPC-06`：`restrict=true` 是否必须由独立执行轨迹证明实际使用；若公开事实基准不可用，该用例应作为残余风险而非依赖标记自证。
- `SCRIPT-REL-RPC-07`：同一交易命中多个合约 Cell Dependency 时是否按交易去重。
- `SCRIPT-REL-RPC-13`：`args` 是交集过滤还是与原 Referring Cell 集合做并集。
- `SCRIPT-REL-RPC-15`：未匹配 Args、非法地址和未知地址的空列表或 4xx 约定。
- `SCRIPT-REL-RPC-20`：已提交支持的 Hash Type 但缺失 Code Hash 时的统一 4xx 错误约定。
