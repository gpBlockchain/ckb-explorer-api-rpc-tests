# V1 地址 Cell RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB Indexer、节点 RPC、Lock Script 地址规则及预先核实的合约部署 OutPoint 为基准，核对 `GET /api/v1/address_live_cells/:id` 与 `GET /api/v1/address_deployed_cells/:id` 的成员、链上字段、过滤、分页和排序
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 CKB 地址或 32 字节 Lock Script Hash 分页返回当前 Live Cells，或返回由 Explorer 合约登记记录标识的部署 Cells；Live Cells 还支持 Bitcoin 绑定状态及 `fiber`、`multisig`、`deployment` 标签过滤。
- 公开主网：Explorer `https://mainnet-api.explorer.nervos.org/api`；CKB RPC `https://mainnet.ckbapp.dev/`。
- 公开测试网：Explorer `https://testnet-api.explorer.nervos.org/api`；CKB RPC `https://testnet.ckbapp.dev/`。
- 输入：每个网络分别以 CKB 地址和对应 Lock Script Hash 调用两个接口；Indexer `get_cells` 按完整 Lock Script 取得 Live Cells，节点 `get_transaction`、`get_live_cell` 和区块查询核对 OutPoint、输出、数据、状态及区块字段；部署成员使用预先核实的已登记合约部署 OutPoint，Bitcoin 绑定过滤仅使用独立确认的映射事实。
- 取样：每个网络先校验 Explorer 与 RPC 创世区块哈希一致，并确认 Explorer tip 不高于 RPC 且最多落后 5 个区块；在同一稳定高度完整翻页，样本覆盖空数据、无 Type Script、多个相同时间戳、超大容量、已消费 Cell、不同地址、三种标签及多个部署 OutPoint。比较期间若 tip、目标交易状态或同高度区块哈希改变，则该网络本次事实基准不可用。
- 成功结果：成员集合按当前状态或登记部署关系精确筛选；每项 OutPoint、区块、容量、占用容量、Lock/Type Script、Type Hash 和原始 Data 均与同网络 RPC 及整数推导值一致，主网与测试网独立产生结论。
- 失败结果：指出网络、接口、查询标识、过滤条件、固定高度、OutPoint、字段、API 值、RPC 原值及推导值；RPC 传输失败、缺少目标交易或区块、或观测到重组时，仅将对应网络事实基准标记为不可用。
- 不负责：双 Explorer 环境兼容性、媒体类型、通用分页或排序错误格式、已消费 Cells 的通用历史查询、代币名称和图标等扩展元数据真伪、Bitcoin `bound_status` 映射来源，以及合约登记信息本身的可信度；这些行为由相邻专项评审或独立事实基准负责。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `ADDR-CELL-RPC-01` | - [x] 在公开主网和测试网分别选择含多个不同结构 Live Cell 的 CKB 地址，完整翻页调用 Live Cells 接口并按该地址的完整 Lock Script 查询同网络 Indexer | API 的 OutPoint 集合与 Indexer Live Cell 集合完全相同且无重复；每项 `tx_hash`、`cell_index`、`block_number`、`block_timestamp`、`capacity`、`occupied_capacity`、`lock_script`、`type_script`、`type_hash` 和 `data` 均与节点交易、区块及 Molecule 占用字节数推导值一致 | Live Cell 漏项、重复、OutPoint 错配、脚本或 Data 失真、区块归属错误及占用容量算法错误 | P0 |
| `ADDR-CELL-RPC-02` | - [x] 在每个网络分别以 CKB 地址和对应 32 字节 Lock Script Hash 查询 Live Cells，同时准备另一个地址具有相邻区块中的 Cells | 两种等价查询返回同一 OutPoint 集合和字段值，且只包含目标 Lock Script 的 Cells，不混入另一地址或相似 Script 的 Cells | 地址与 Lock Hash 分支关联不一致、仅按部分 Script 匹配或跨地址泄漏 Cells | P0 |
| `ADDR-CELL-RPC-03` | - [x] 在稳定观测窗口选择同一地址的 Live、已消费、pending 和 rejected 输出，并以 Indexer `get_cells` 与节点 `get_live_cell` 确认状态后请求 Live Cells | 只返回节点与 Indexer 均确认仍为 live 的已提交输出；已消费、pending 和 rejected 输出均不在成员中 | 把历史或未上链输出当作可花费 Cell，造成余额、资产或后续交易构造错误 | P0 |
| `ADDR-CELL-RPC-04` | - [x] 查询一个 Explorer 已收录但在固定高度没有任何 Live Cell 的 CKB 地址或 Lock Script Hash | 返回 HTTP `200`、空 `data`，且分页元数据 `total=0`、`total_pages=0`，不返回其他地址的占位 Cell | 空地址被误报不存在、复用旧查询结果或返回错误分页总数 | P1 |
| `ADDR-CELL-RPC-05` | - [x] 在每个网络选择无 Type Script 且 Output Data 为空的普通 Live Cell | `type_script` 和 `type_hash` 为 `null`，`data` 精确为 `0x`，`cell_type` 为 `normal`，`extra_info` 的类型为 `ckb` 且容量与该 Cell 一致 | 空 Data 被序列化为缺失值、伪造空 Type Script、普通 Cell 错分为资产 Cell | P1 |
| `ADDR-CELL-RPC-06` | - [x] 在每个网络以链上 Script 和 Data 可独立识别的样本覆盖普通 Cell、DAO 存款与取款 Cell，以及 Data 至少 16 字节的标准 sUDT Cell | 每项 `cell_type` 分别符合相同网络的脚本哈希、Hash Type 和 Data 规则；未知 Type Script 仍归为 `normal`，不因代币展示元数据是否存在而改变分类 | Cell 类型识别使用错误网络配置、忽略 Data 边界或把未知协议误分类 | P1 |
| `ADDR-CELL-RPC-07` | - [x] 在任一网络选择 `capacity` 超过 `2^53-1` Shannon 且占用容量可从脚本和 Data 精确重算的 Live Cell | `capacity` 与 `occupied_capacity` 均以完整十进制字符串表达并等于 RPC 无符号整数及字节占用推导值，不出现科学计数、浮点尾差、一 Shannon 舍入或负数 | 大容量经过 JSON 或计算层后静默失精，导致钱包和资产展示错误 | P0 |
| `ADDR-CELL-RPC-08` | - [x] 对 Live Cell 数超过 `page_size` 的地址固定排序后请求全部相邻页及一个超过末页的页码 | 各页并集恰好等于未分页成员集合且页间无重复；`meta.total`、`page_size`、`total_pages` 与完整成员数一致，超过末页返回空 `data` 而不改变总数 | 分页漏项、跨页重复、过滤前后总数混用或末页边界错误 | P1 |
| `ADDR-CELL-RPC-09` | - [x] 对具有不同区块时间戳 Live Cells 的地址分别省略 `sort`、传 `block_timestamp.desc` 和传 `block_timestamp.asc` | 默认与显式降序均按 `block_timestamp` 从大到小，升序从小到大；两种方向的成员集合不变 | 默认方向反转、排序只作用于单页或排序改变过滤成员 | P1 |
| `ADDR-CELL-RPC-10` | - [ ] 当同一地址至少两个 Live Cells 或部署 Cells 具有相同 `block_timestamp` 且该时间戳跨越分页边界时，分别对两个接口重复完整翻页 | 待确认：同一时间戳内应使用哪一个稳定次级键排序，确保两个接口的重复请求及相邻页 OutPoint 不漂移；当前接口只按请求字段排序 | 相同时间戳下数据库无序导致翻页随机漏项或重复 | P1 |
| `ADDR-CELL-RPC-11` | - [x] 在每个网络对同时具有 Fiber Funding Lock 与其他 Lock 的地址传入 `tag=fiber` | 结果恰好是未过滤 Live 集合中 Lock Script `code_hash` 等于该网络 Fiber Funding Code Hash 的成员；每项包含 `fiber` 标签，其他 Cells 全部排除 | Fiber 标签使用错误网络脚本、过滤条件过宽或标签与成员条件不一致 | P1 |
| `ADDR-CELL-RPC-12` | - [x] 在每个网络对同时具有两种受支持多签 Lock 与普通 Lock 的地址传入 `tag=multisig` | 结果只包含经典多签 `code_hash` 加 `data1`，或新版多签 Cell Type Hash 加 `type` 的 Live Cells；每项包含 `multisig` 标签，错误 Hash Type 和普通 Lock 均排除 | 多签脚本只匹配 Code Hash 而忽略 Hash Type、漏掉新版多签或混入普通 Cells | P1 |
| `ADDR-CELL-RPC-13` | - [x] 对同时拥有已登记合约部署 Live Cell、已消费部署 Cell 和普通 Live Cell 的地址传入 `tag=deployment` | 结果恰好是未过滤 Live 集合与已登记合约部署 OutPoint 集合的交集；仅仍为 live 的部署 Cell 返回并带 `deployment` 标签，已消费部署 Cell 和未登记普通 Cell 排除 | 部署标签未与当前 live 状态取交集、历史部署混入或登记 OutPoint 关联错误 | P1 |
| `ADDR-CELL-RPC-14` | - [x] 对同一地址传入一个不受支持的非空 `tag` | 返回 HTTP `200`、空 `data` 和与空结果一致的分页元数据，不退化为未过滤的全部 Live Cells | 拼写错误或未知标签静默绕过过滤并泄漏全量结果 | P2 |
| `ADDR-CELL-RPC-15` | - [x] 使用独立确认的 Bitcoin Vout 映射样本，对同一 CKB 地址分别传入 `bound_status=bound`、`unbound`、`binding` 和 `normal` | 每次结果只包含映射到目标地址、状态等于请求值且 CKB Cell 仍为 live 的 OutPoints；四次结果互斥，合并后不超出该地址关联的全部 Bitcoin Vout Live Cells | Bitcoin 状态过滤串值、忽略 CKB 消费状态或关联到其他地址的 Vout | P1 |
| `ADDR-CELL-RPC-16` | - [x] 对同时具有多种 Bitcoin 绑定状态和多种标签的地址组合传入 `bound_status` 与 `tag` | 返回成员等于目标地址 Live Cells、所选 Bitcoin Vout 状态和所选标签条件三者的交集，分页元数据基于交集计算 | 多过滤器变为并集、后一个过滤器覆盖前一个或元数据仍使用过滤前总数 | P1 |
| `ADDR-CELL-RPC-17` | - [x] 在公开主网和测试网分别选择拥有多个已登记合约部署 OutPoint 的地址，完整翻页调用 Deployed Cells 并读取节点交易与区块 | API 成员集合等于预先核实的登记部署 OutPoints 中 Lock Script 属于目标地址的集合且无重复；每项 OutPoint、区块、容量、占用容量、Lock/Type Script、Type Hash 和 Data 与同网络 RPC 一致 | 部署 Cell 漏项、登记 OutPoint 错配、链上字段失真或同一部署重复返回 | P0 |
| `ADDR-CELL-RPC-18` | - [x] 在每个网络分别以部署地址和对应 Lock Script Hash 查询 Deployed Cells，并准备另一地址的登记部署 OutPoint | 两种等价查询返回同一部署 OutPoint 集合和字段值，只包含目标 Lock Script 所属的登记部署 Cell，不混入另一地址的部署 | 地址分支与 Lock Hash 分支结果分裂、部署归属按错误关联字段判断或跨地址泄漏 | P0 |
| `ADDR-CELL-RPC-19` | - [x] 已登记部署集合同时包含 `verified=true`、`verified=false` 或已标记 deprecated 的合约记录时查询对应地址 | 结果按登记部署 OutPoint 归属返回，不以 verified 或 deprecated 元数据筛除成员；每个返回成员都可在链上定位到原部署输出 | 把人工审核状态误作链上部署存在条件，导致登记部署 Cell 无故消失 | P2 |
| `ADDR-CELL-RPC-20` | - [ ] 某已登记合约的部署 Cell 从 live 变为已消费且 Explorer 已同步后，重复查询 Deployed Cells | 待确认：该接口应保留全部历史登记部署 OutPoints，还是只返回当前 live 的部署 Cells 并显式提供状态；当前实现保留已消费部署 Cell 但响应不含 `status` | 调用方把已消费部署 Cell 误当作 live 依赖，或历史部署在无契约说明时突然消失 | P0 |
| `ADDR-CELL-RPC-21` | - [x] 对部署 Cell 数超过 `page_size` 且时间戳不同的地址，分别按 `block_timestamp.asc`、`block_timestamp.desc` 完整翻页并请求末页后的空页 | 两种方向均返回相同的完整登记部署集合且顺序互逆；各页无重复，空页为 `data: []`，`meta.total`、`page_size` 和 `total_pages` 均按部署集合计算 | 部署列表排序方向错误、只排单页、跨页漏项或分页元数据使用 Live Cell 总数 | P1 |
| `ADDR-CELL-RPC-22` | - [x] 查询一个 Explorer 已收录但没有任何已登记合约部署 OutPoint 的 CKB 地址或 Lock Script Hash | 返回 HTTP `200`、空 `data`，且分页元数据 `total=0`、`total_pages=0`，不把该地址的普通或未登记 Live Cells 当作部署成员 | 无部署地址被误报不存在、普通 Live Cell 被当作部署 Cell 或空结果元数据错误 | P1 |
| `ADDR-CELL-RPC-23` | - [x] 分别以格式非法的标识和格式有效但 Explorer 未收录的 CKB 地址或 Lock Script Hash 请求两个接口 | 两个接口对两类输入均返回 HTTP `404`，错误对象 `code` 为 `1010`、`status` 为 `404`、`title` 为 `Address Not Found`，且不返回空成功 Cell 集合 | 无效或不存在地址触发服务端异常、两个接口错误语义分裂或把未知资源误报为空列表 | P1 |
| `ADDR-CELL-RPC-24` | - [x] 某地址新产生一个确认输出或现有 Live Cell 被消费，Explorer 已同步且规范链稳定后，在变更前后重复请求两个接口 | Live Cells 在共享缓存最长 60 秒新鲜期和随后 10 秒 stale-while-revalidate 窗口结束后收敛到新 Indexer 集合；Deployed Cells 的成员按 `ADDR-CELL-RPC-20` 确认的状态契约收敛，任何字段不跨新旧版本拼接 | 新增或消费后列表长期陈旧、CDN 缓存不刷新，或两个接口对同一 OutPoint 呈现矛盾状态 | P1 |

## 本轮需要确认

- `ADDR-CELL-RPC-10`：相同 `block_timestamp` 的 Cells 应采用哪一个稳定次级排序键，以保证跨页及重复请求不漂移。
- `ADDR-CELL-RPC-20`：Deployed Cells 应保留历史上全部已登记部署 OutPoints，还是只返回当前 live 的部署 Cells；若保留历史成员，是否需要在响应中新增可观测 `status`。
- 请确认 `ADDR-CELL-RPC-15` 与 `ADDR-CELL-RPC-16` 仅验证已独立确认的 Bitcoin Vout 映射上的过滤结果，不把 `bound_status` 映射来源纳入本轮 CKB RPC 正确性结论。
