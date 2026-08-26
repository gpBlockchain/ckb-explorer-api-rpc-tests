# V1 Nervos DAO 交易 RPC 正确性用例评审

评审范围：在公开主网和测试网分别核对 `GET /api/v1/contract_transactions/:id`、`GET /api/v1/contract_transactions/download_csv` 与 `GET /api/v1/dao_contract_transactions/:id` 的全局 Nervos DAO 交易、三阶段行为和导出边界
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按固定合约名 `nervos_dao` 返回全局已提交 DAO 交易列表，按交易哈希返回单笔 DAO 交易详情，并按 DAO 事件导出 CSV。
- 输入：列表接收 `id=nervos_dao`、`tx_hash`、`address_hash`、`page`、`page_size`；详情接收 CKB 交易哈希；CSV 接收 `start_date`、`end_date`、`start_number`、`end_number`。
- 取样与事实基准：主网和测试网分别用同网络 CKB Indexer 发现 DAO Cell 及参与交易，再用节点 RPC `get_transaction`、`get_block`、`get_header` 和输入引用的上一笔交易核对；金额全程以 Shannon 整数计算，CSV 展示值转回 Shannon 后比较。
- 成功结果：列表、详情和 CSV 都与同网络规范链上的 DAO 存款、取款请求和利息领取交易一致，并给出可复核的哈希、out-point、区块和金额差异。
- 失败结果：非 `nervos_dao` 合约名返回合约不存在错误；非法交易哈希、不存在或非 DAO 交易、非法分页参数返回对应错误对象。
- 不负责：DAO 汇总状态、存款人排名、地址专属 DAO 活动、通用请求头和 CSV 下载响应头。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `DAO-TX-RPC-01` | 在公开主网和测试网分别根据 DAO Type Script 及其输入引用找到同一已确认窗口内的 DAO 与普通交易，请求 `GET /api/v1/contract_transactions/nervos_dao` | 每个网络的列表只包含输入或输出涉及 DAO 存款或取款 Cell 的已提交交易，与 RPC 推导集合去重后一致，普通交易不出现 | DAO 标签漏标、误标或重复关联导致全局列表缺失或混入非 DAO 交易 | P0 |
| `DAO-TX-RPC-02` | 对包含多页 DAO 交易的主网和测试网分别使用默认分页、指定 `page`、指定 `page_size` 及组合分页请求全局列表 | 默认每页 10 条，各页按区块时间降序且同时间按内部交易顺序降序，页间无重复无遗漏，`meta.total` 等于同窗口 DAO 交易总数，越界页返回空数组 | 排序抖动、分页错位或总数失真使 DAO 历史重复或缺页 | P1 |
| `DAO-TX-RPC-03` | 在两个网络分别取已知 DAO 交易哈希和已知非 DAO 交易哈希，使用 `tx_hash` 筛选全局列表 | DAO 哈希只返回唯一对应交易且其展示字段与 RPC 一致，非 DAO 哈希返回空列表 | 哈希筛选未作用或绕过 DAO 成员限定 | P1 |
| `DAO-TX-RPC-04` | 在两个网络分别选择参与 DAO 交易和不参与该 DAO 交易的地址，使用 `address_hash` 筛选全局列表 | 结果只包含同时属于全局 DAO 集合且该地址在输入或输出参与的交易，不参与时返回空列表 | 地址过滤按错账本、只查输入或只查输出 | P1 |
| `DAO-TX-RPC-05` | 在主网和测试网分别选择创建 DAO 存款 Cell 的已确认交易，请求 `GET /api/v1/dao_contract_transactions/:id` | 详情中的交易哈希、版本、witnesses、Cell/Header Dependencies、区块归属、输入输出和手续费与 RPC 一致；DAO 输出 Data 表示存款阶段，存款事件金额精确等于该输出 capacity 的 Shannon 整数 | 存款交易被当成普通交易或存款本金发生单位、精度错误 | P0 |
| `DAO-TX-RPC-06` | 在两个网络分别选择消费 DAO 存款 Cell 并产生取款阶段 Cell 的已确认交易，请求 DAO 交易详情 | 详情与 RPC 原始交易一致，输入 out-point 指向原存款 Cell，对应输出 Data 记录存款区块参数，取款请求事件金额精确等于被消费存款 Cell 的 Shannon capacity | DAO 第一阶段取款被漏识别、out-point 错绑或本金被按取款输出错算 | P0 |
| `DAO-TX-RPC-07` | 在两个网络分别选择消费 DAO 取款阶段 Cell 并返回可用 CKB 的已确认交易，请求 DAO 交易详情 | 详情与 RPC 原始交易一致，Header Dependency 指向存款区块，以存款和取款区块 DAO 字段推导的利息 Shannon 整数等于利息领取事件值 | Header Dependency 错配、DAO 利息公式或整数除法错误使领取金额失真 | P0 |
| `DAO-TX-RPC-08` | 以 `nervos_dao` 以外的合约名请求全局 DAO 交易列表 | 返回 HTTP 404 且 JSON:API 错误码为 `1021`、标题为 `Contract Not Found`，不返回其他合约或 DAO 数据 | 通用合约名路径误暴露 DAO 数据或返回误导性空成功 | P1 |
| `DAO-TX-RPC-09` | 分别以非法交易哈希、合法但不存在的哈希和已存在的普通非 DAO 交易哈希请求 DAO 交易详情 | 非法哈希返回 HTTP 422 和错误码 `1005`；不存在或非 DAO 交易均返回 HTTP 404 和错误码 `1006`，不泄漏普通交易详情 | 参数校验失效或 DAO 专属路由接受非 DAO 交易 | P1 |
| `DAO-TX-RPC-10` | 对全局 DAO 交易列表分别提交小于 1、非整数的 `page` 或 `page_size`，以及两者同时非法 | 返回 HTTP 400；`page` 错误码为 `1007`，`page_size` 错误码为 `1008`，同时非法时两个错误都出现且不执行列表查询 | 非法分页值被默认转换后返回错页或引发服务器异常 | P1 |
| `DAO-TX-RPC-11` | 在两个网络分别导出同时包含存款、取款请求和利息领取事件的 `GET /api/v1/contract_transactions/download_csv` | CSV 表头为 `Txn hash,Address,Blockno,UnixTimestamp,Method,Amount,Token,TxnFee(CKB),date(UTC)`；三阶段方法分别为 `Deposit`、`Withdraw Request`、`Withdraw Finalization`，每个 DAO 事件一行，交易、地址和区块与 RPC 一致，`Amount` 和手续费转回 Shannon 后精确等于链上值 | DAO 事件合并或拆分错误、方法名错配、用浮点转换导致金额或手续费丢失 Shannon | P0 |
| `DAO-TX-RPC-12` | 导出包含恰好等于 `start_date`、恰好等于 `end_date` 以及各自边界外 DAO 事件的时间窗口 | 两个时间边界均包含，只导出区块毫秒时间戳位于闭区间内的已提交 DAO 事件，边界外事件不出现 | 日期边界开闭区间错误造成导出少一天或多一天 | P1 |
| `DAO-TX-RPC-13` | 导出包含恰好位于 `start_number`、`end_number` 区块及边界外 DAO 事件的高度窗口，并同时提交与高度冲突的日期参数 | 区块高度先转为对应区块时间戳，高度参数覆盖同侧日期参数，起止区块均包含，只导出该闭区间内的 DAO 事件 | 高度和日期优先级不稳定或边界映射到错误区块时间 | P1 |
| `DAO-TX-RPC-14` | 在过滤窗口内没有 DAO 事件时导出 CSV | 返回仅包含一行固定表头的可解析 CSV，不伪造数据行也不返回空文件 | 无数据导出缺表头或复用旧缓存行 | P2 |
| `DAO-TX-RPC-15` | 对包含多个区块且单笔交易可包含多个 DAO 事件的窗口重复导出 CSV | 待确认：CSV 数据行是否必须按区块时间降序、同交易内按 DAO 事件稳定顺序输出；源码批处理未提供可依赖的最终次序 | 运行间导出顺序漂移使审计比对和增量处理不稳定 | P1 |
| `DAO-TX-RPC-16` | 在同源交易池中稳定观察一笔已被 Explorer 解析为 DAO 的 pending 或 proposed 交易，以其哈希请求详情，并在其转为 committed 或 rejected 后再次请求；池或状态变化中的观测标记为事实基准不可用 | 待确认：详情接口应仅接受 committed DAO 交易并在其他状态返回交易不存在，还是按当前查找逻辑返回 pending/proposed/rejected 详情及准确 `tx_status`；一旦确定，提交前后的响应状态、区块字段和原始交易结构必须与对应 RPC 状态一致，rejected 不得伪装成 committed | DAO 详情与全局 committed 列表状态口径不一致，或交易池到确认/拒绝转换后返回陈旧状态和伪造区块归属 | P1 |

## 本轮需要确认

- `DAO-TX-RPC-15`：CSV 是否承诺按区块时间降序以及同交易内的稳定事件顺序。
- `DAO-TX-RPC-16`：DAO 交易详情是 committed-only，还是允许返回 pending/proposed/rejected DAO 交易及其真实状态。
- 其余用例的预期可由当前路由、DAO 事件处理、序列化器和 CSV 导出实现确定。
