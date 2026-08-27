# V2 已验证脚本目录 RPC 正确性用例评审

评审范围：在公开主网和测试网分别核对 `GET /api/v2/scripts` 与 `GET /api/v2/scripts/general_info` 的脚本身份、部署证据、筛选排序和可重算汇总字段
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：列出 Explorer 已验证且部署 Cell 仍存活的脚本，并按 `code_hash` 和 `hash_type` 返回单个或多个登记脚本的详细链上证据及汇总值。
- 输入：目录接收 `script_type`、`notes`、`sort`、`page`、`page_size`；详情接收 `code_hash` 和 `hash_type`，其中 `type` 按 Type Hash 查询，`data`、`data1`、`data2` 按 Data Hash 查询。
- 取样与事实基准：主网和测试网分别通过已登记脚本的部署 out-point 调用同网络 RPC `get_transaction`、`get_live_cell` 和 CKB Indexer `get_cells`、`get_transactions`，重算 Type/Data Hash、容量、交易数和引用 Cell 汇总。
- 成功结果：所有可由链上数据证明的脚本身份、部署 Cell、合约 Cell、状态、容量和计数都与 RPC/Indexer 一致；人工维护元数据只验证关联稳定。
- 失败结果：详情的缺失或不支持的 `hash_type`、未知 `code_hash` 返回 HTTP 404 且无脚本数据。
- 不负责：脚本关联交易、部署/Referring Cells 列表、人工元数据内容真伪、通用 HTTP 和分页错误格式。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `SCRIPT-CATALOG-RPC-01` | - [x] 在主网和测试网分别请求 `GET /api/v2/scripts`，并核对已登记脚本的验证标记与部署 Cell 存活状态 | 目录只包含 Explorer 标记为已验证且关联部署 Cell 在同网络仍为 Live 的脚本，未验证脚本和部署 Cell 已 Dead 的脚本不出现 | 目录混入未验证或已失效部署，使调用方把旧代码 Cell 当成当前可用脚本 | P0 |
| `SCRIPT-CATALOG-RPC-02` | - [x] 在两个网络分别选择以 Type Hash 标识的脚本，从目录取其 `type_hash`、`hash_type`、`dep_type` 和部署 out-point | `type_hash` 精确等于对部署 Cell Type Script 按 CKB 规范序列化后计算的 Script Hash，`hash_type` 为 `type`，`dep_type` 与交易 Cell Dependency 中的类型一致 | Type Script 哈希算法、网络或 Dependency 类型错配 | P0 |
| `SCRIPT-CATALOG-RPC-03` | - [x] 在两个网络分别选择以 Data Hash 标识的 `data`、`data1` 或 `data2` 脚本，取其 `data_hash`、`hash_type`、`dep_type` 和部署 out-point | `data_hash` 精确等于同网络部署 Cell Output Data 的 CKB Data Hash，返回的 `hash_type` 保留脚本登记值，`dep_type` 与 Cell Dependency 一致 | Data Hash 指向错误 Cell、丢失 `data1/data2` 语义或 Dep Type 错配 | P0 |
| `SCRIPT-CATALOG-RPC-04` | - [x] 对同时包含 Lock Script、Type Script 以及双重用途登记的目录分别使用 `script_type=lock`、`script_type=type` 和同时包含两者的参数 | `lock` 结果每项 `is_lock_script=true`，`type` 结果每项 `is_type_script=true`，同时请求两者时只返回两个标记都为 true 的交集 | 脚本类型筛选反向、被当成并集或单一脚本误分类 | P1 |
| `SCRIPT-CATALOG-RPC-05` | - [x] 目录同时存在 Zero Lock、已废弃、含 RFC、含网站和开源链接的脚本，分别和组合使用 `notes` | 单一 note 只返回具有对应元数据标记的脚本；多个 notes 按并集返回，成员去重，不同网络分别给出结论 | note 组合被错当交集、条件未生效或同一脚本重复出现 | P1 |
| `SCRIPT-CATALOG-RPC-06` | - [x] 对拥有不同部署时间和 Referring Cell 总容量的脚本，分别省略 `sort`、使用 `timestamp.asc/desc` 和 `capacity.asc/desc` | 默认按部署时间升序；`timestamp` 按部署毫秒时间戳排序，`capacity` 按 Referring Cells 的 Shannon 总容量排序，升降序方向正确 | 排序别名映射错字段、容量按字符串排序或默认方向漂移 | P1 |
| `SCRIPT-CATALOG-RPC-07` | - [x] 在两个网络分别对排序后超过一页的脚本目录使用默认分页、指定 `page_size` 和越界 `page` | 默认每页 10 条，页间成员无重复无遗漏，`meta.total` 等于筛选后总数，`meta.page_size` 等于请求值，越界页返回空数组 | 先分页后筛选、总数未随条件变化或页间成员漂移 | P1 |
| `SCRIPT-CATALOG-RPC-08` | - [x] 在两个网络分别以有效 Type Hash 或 Data Hash 请求 `GET /api/v2/scripts/general_info` | 每个结果的 `script_out_point` 指向对应实际合约 Cell，部署 Cell 的 `capacity_of_deployed_cells` Shannon 容量与 RPC 一致，`dep_type`、`is_lock_script`、`is_type_script`、`is_zero_lock` 与选定登记和链上使用一致 | 代码哈希命中错误合约、部署 out-point 错绑或容量失真 | P0 |
| `SCRIPT-CATALOG-RPC-09` | - [x] 对存在多笔 Cell Dependency 交易和多个 Live Referring Cells 的已登记脚本请求 general info | `count_of_transactions` 等于关联交易数，`count_of_referring_cells` 等于引用该 Code Hash 的 Live Cells 数，`capacity_of_referring_cells` 的 Shannon 整数等于这些 Cells capacity 之和 | 合约关联重复计数、混入 Dead Cells 或容量汇总丢失精度 | P0 |
| `SCRIPT-CATALOG-RPC-10` | - [x] 同一 `code_hash` 的脚本包含人工维护的名称、描述、RFC、网站、源码链接、废弃与验证标记，分别请求目录和 general info | 各元数据字段始终关联到同一 `code_hash/hash_type` 记录，目录摘要与 general info 重叠字段一致；仅验证关联与一致性，不以 RPC 判定链接或文案真伪 | 元数据串到其他脚本或目录与详情指向不同登记 | P2 |
| `SCRIPT-CATALOG-RPC-11` | - [x] 查询一个登记仍存在但部署 Cell 已被消费的脚本，同时请求目录和 general info | 该脚本不出现在只包含 Live 部署的目录中；按其有效 `code_hash/hash_type` 请求 general info 仍返回登记且 `is_deployed_cell_dead=true` | 部署 Cell 被消费后仍当作当前目录成员，或详情丢失历史状态 | P1 |
| `SCRIPT-CATALOG-RPC-12` | - [x] 对 general info 省略 `hash_type`、使用不支持的 `hash_type` 或在已支持 Hash Type 下提交合法格式但未登记的非空 Code Hash | 返回 HTTP 404 且响应不包含脚本数据，不回退到全部目录或其他 Hash Type | Hash Type 被静默改写或未知 Code Hash 命中错记录 | P1 |
| `SCRIPT-CATALOG-RPC-13` | - [ ] 对 general info 使用已支持的 `hash_type` 但省略 `code_hash` | 待确认：应返回哪个 4xx 错误；当前实现会按空 Type/Data Hash 查询，可能命中其他类型登记而暴露无关脚本 | 缺失 Code Hash 反而返回多个无关登记 | P0 |

## 本轮需要确认

- `SCRIPT-CATALOG-RPC-13`：已提交支持的 Hash Type 但缺失 Code Hash 时的统一 4xx 错误约定。
- 人工维护元数据的内容真伪已明确排除，仅评审与脚本身份的关联一致性。
