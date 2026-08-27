# V1 UDT 发现、sUDT 目录与持仓分布 RPC 正确性用例评审

评审范围：核对 `GET /api/v1/udt_queries`、sUDT 列表与详情、UDT 交易 CSV 和持仓分布的产品行为及可由同网络链数据验证的结果
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按名称或 Symbol 搜索 UDT 记录，列出 sUDT，展示已发布 UDT 详情，导出指定 UDT 的交易变化，并返回按 Bitcoin 所有者与 Lock Script 合约划分的持有人数量。
- 输入：`GET /api/v1/udt_queries` 使用搜索参数 `q`；`GET /api/v1/udts` 使用 `page`、`page_size`、`sort`；`GET /api/v1/udts/:id` 与 `GET /api/v1/udts/:id/holder_allocation` 使用 Type Hash；`GET /api/v1/udts/download_csv` 使用 `id` 及可选 `start_date`、`end_date`、`start_number`、`end_number`。
- 成功结果：主网和测试网分别返回符合选择规则的唯一 UDT、可验证的 Type Script 和链上聚合值；CSV 与同网络已提交交易一致，金额以整数原始值推导后再按 decimal 展示。
- 失败结果：无效分页或 Type Hash、未发布或不存在的详情与导出目标返回对应错误；RPC、Indexer、Bitcoin 映射或合约分类事实缺失时只标记相关外部事实不可用。
- 不负责：xUDT 与统一同质化代币专用目录、Omiga 生命周期、元数据写入、独立 UDT 交易历史接口及通用 HTTP/CSV 下载头契约。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `UDT-CATALOG-RPC-01` | - [x] `q` 以不同大小写包含已存在 UDT 的 Symbol 或 full name 子串时调用搜索接口 | 返回 Symbol 或 full name 任一字段不区分大小写包含该子串的唯一记录，并且每条只暴露 `full_name`、`symbol`、`udt_type`、`type_hash`、`icon_file` | 搜索大小写敏感、只查一个字段或泄露不属于搜索结果的元数据 | P1 |
| `UDT-CATALOG-RPC-02` | - [x] `q` 不匹配任何记录，或同一记录的 Symbol 与 full name 同时匹配时调用搜索接口 | 不匹配时返回空数组；同时匹配时该 UDT 只出现一次 | 空搜索被当成错误或 OR 条件产生重复记录 | P2 |
| `UDT-CATALOG-RPC-03` | - [ ] 省略 `q` 或传入非字符串结构调用搜索接口 | 待确认：应返回明确的 4xx 查询参数错误，而不是服务端异常；失败不得改变 UDT 数据 | 缺失或畸形搜索参数触发 500 | P1 |
| `UDT-CATALOG-RPC-04` | - [x] 数据库同时存在 sUDT、xUDT、Omiga 等类型及已发布和未发布 sUDT 时调用 UDT 列表 | 列表只包含 `udt_type=sudt` 的记录；当前源码未按 `published` 过滤，因此已发布和未发布 sUDT 都属于列表成员 | 专用目录混入其他代币类型，或列表与源码发布过滤语义不一致 | P0 |
| `UDT-CATALOG-RPC-05` | - [x] 不传分页参数以及显式请求相邻页面或超大 `page_size` | 默认页最多 25 条，显式页面是同一稳定排序的连续切片且 meta 总数一致，`page_size` 最多受 UDT 的 100 条上限约束 | 默认页长漂移、翻页漏项重项或无界查询 | P1 |
| `UDT-CATALOG-RPC-06` | - [x] `page` 或 `page_size` 为零、负数、非整数或非数字 | 返回对应 page 或 page-size 参数错误；两个参数同时无效时错误对象同时包含两项且不执行目录查询 | 畸形分页导致错误切片或服务端异常 | P1 |
| `UDT-CATALOG-RPC-07` | - [x] 分别省略 `sort`，或使用 `transactions`、`created_time`、`addresses_count` 的升降序与非法方向 | 默认按内部 ID 降序；三个公开字段分别映射 24 小时交易数、创建区块时间和地址数；缺失或非法方向使用升序，主排序并列后按 full name、ID 升序稳定排序 | 排序映射、方向或并列规则错误导致目录和分页抖动 | P1 |
| `UDT-CATALOG-RPC-08` | - [x] 以已发布 UDT 的 Type Hash 查询详情，并用同网络 RPC/Indexer 定位对应 Type Script 与活跃代币 Cells | 返回同一 UDT 的 Type Hash、`args`、`code_hash`、`hash_type`、发行者地址、类型、发布状态及展示元数据；链相关身份与 RPC/Indexer 精确一致 | Type Hash 关联到错误脚本、网络或代币记录 | P0 |
| `UDT-CATALOG-RPC-09` | - [x] 详情中的 `total_amount`、地址数、持有人数、decimal 或 24 小时交易数超过 JavaScript 安全整数范围，且联系邮箱已设置 | 所有计数和金额字段按十进制字符串无损返回，decimal 也为字符串；邮箱只保留前两位及域名末两位，其余字符以星号遮蔽 | 大整数精度丢失或公开接口泄露完整邮箱 | P0 |
| `UDT-CATALOG-RPC-10` | - [x] Type Hash 格式错误、记录不存在或目标 UDT 未发布时查询详情 | 格式错误返回 Type Hash 参数错误；不存在和未发布均返回 UDT not-found，且不返回部分详情 | 畸形哈希造成服务异常或未发布元数据被公开 | P1 |
| `UDT-CATALOG-RPC-11` | - [x] 对已发布 UDT 按日期或区块高度上下界导出交易 CSV | 上下界均为包含边界；结果按区块时间降序取最多 500 笔关联交易，输出固定表头，并且每行交易哈希、高度、毫秒时间戳和 UTC 时间与同网络 RPC 区块一致 | CSV 过滤越界、顺序错误、超过上限或链上身份错配 | P0 |
| `UDT-CATALOG-RPC-12` | - [x] 一笔 UDT 交易包含多个地址及同地址多个输入输出时导出 CSV | 每个参与地址生成一行，同地址的输入和输出原始金额先分别求和，再以绝对净变化生成 Amount，并按流入、流出、铸造或销毁关系生成 Method；已发布 Token 列使用 Symbol | Cell 逐行重复、净额方向错误或金额先缩放再求和导致精度损失 | P0 |
| `UDT-CATALOG-RPC-13` | - [x] CSV 中 UDT decimal 为 0、常用值、超过 20 或金额极大/极小时 | 原始整数运算保持精确；展示金额按 decimal 转换，decimal 大于 20 时保留 20 位并带省略标记，极大或极小结果使用固定小数格式 | 大整数、超高精度或极小金额经浮点转换失真 | P1 |
| `UDT-CATALOG-RPC-14` | - [x] CSV 的 `id` 不存在、未发布或不能定位目标 UDT | 返回 UDT not-found，且响应中没有其他代币的交易行 | 无效导出目标产生空但成功的误导文件或越权导出未发布记录 | P1 |
| `UDT-CATALOG-RPC-15` | - [x] 已发布 UDT 同时存在 Bitcoin 所有者汇总和多个已知 Lock Script 合约持仓分配时查询 holder allocation | `btc_holder_count` 等于无合约汇总记录的值；每个合约条目返回合约名称、code hash、hash type 和去重 CKB holder 数；没有 Bitcoin 汇总时返回 0 | Bitcoin 与 CKB 持有人重复混算、合约脚本分类或默认零值错误 | P1 |
| `UDT-CATALOG-RPC-16` | - [x] Type Hash 格式错误、记录不存在或未发布时查询 holder allocation | 格式错误返回 Type Hash 参数错误；不存在和未发布返回 UDT not-found，不返回其他 UDT 的分配数据 | 无效查询泄露或串用其他代币的持仓统计 | P1 |
| `UDT-CATALOG-RPC-17` | - [x] CKB RPC/Indexer、Bitcoin 地址映射或合约分类源缺失，或链在取样期间重组 | 只将依赖该事实源的 Type Script、供应量或持仓结论标记为事实基准不可用；搜索与本地展示元数据不冒充 RPC 可验证事实，另一网络独立执行 | 外部映射或链状态缺失被误判为 API 数据错误 | P1 |

## 本轮需要确认

- `UDT-CATALOG-RPC-03`：搜索接口省略或传入非字符串 `q` 时，是否统一返回 4xx 查询参数错误。
- `GET /api/v1/udts` 当前包含未发布 sUDT；需确认这是否为公开目录的预期成员规则。
- Bitcoin 所有者映射与合约名称属于 Explorer 派生事实；若运行环境没有同一份映射数据，只核对可由链上 Lock Script 证明的部分。
