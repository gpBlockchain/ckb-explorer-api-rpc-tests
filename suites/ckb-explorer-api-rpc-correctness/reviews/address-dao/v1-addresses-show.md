# V1 地址详情 RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB Indexer、节点 RPC、地址编码规则及必要的 Bitcoin 地址映射事实为基准，核对 `GET /api/v1/addresses/:id` 的地址身份、当前链上状态和三个查询分支
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 CKB 地址、32 字节 Lock Script Hash 或当前网络的 Bitcoin 地址返回地址详情；CKB 地址与 Bitcoin 地址分支返回地址资源数组，Lock Script Hash 分支返回独立的 `lock_hash` 资源。
- 公开主网：Explorer `https://mainnet-api.explorer.nervos.org/api`；CKB RPC `https://mainnet.ckbapp.dev/`。
- 公开测试网：Explorer `https://testnet-api.explorer.nervos.org/api`；CKB RPC `https://testnet.ckbapp.dev/`。
- 输入：每个网络分别调用 Explorer `GET /api/v1/addresses/:id`；CKB 地址和 Lock Script Hash 由 CKB Script 编解码互证，当前 Cells 与交易使用同网络 Indexer `get_cells`、`get_transactions` 和节点 `get_transaction`，DAO 值使用区块头 `dao` 与规范 DAO 公式推导，Bitcoin 查询使用独立确认的 Bitcoin-to-CKB 地址映射。
- 取样：每个网络先校验 Explorer 与 RPC 创世区块哈希一致，并确认 Explorer tip 不高于 RPC 且最多落后 5 个区块；在同一稳定高度窗口完整翻页读取 Indexer 结果，按 Lock Script 精确匹配且不跨网络比较。比较期间若 tip、目标交易状态或同高度区块哈希改变，则该网络本次事实基准不可用。
- 成功结果：地址编码解析出的 Lock Script、Live Cell 集合、容量和计数与同网络事实基准一致；所有 CKB/Shannon、DAO、计数和 UDT 数量均用整数无损计算并按 API 的十进制字符串比较；Bitcoin 查询的成员集合与映射事实一致。
- 失败结果：指出网络、查询类型、地址或 Lock Script Hash、固定高度、API 值、Indexer/RPC 原值及推导值；单个公开 URL、Indexer/RPC 结果或映射事实不可用时只影响该网络的对应用例。
- 不负责：双 Explorer 环境兼容性、媒体类型和通用请求头、地址交易/DAO 交易/Live Cell 列表接口本身、pending/rejected 交易、UDT 名称/图标等站外元数据的真实性，以及 Bitcoin 链上资产归属；这些行为由通用契约或相邻专项评审负责。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `ADDRESS-RPC-01` | 在公开主网和测试网分别以一个有已确认链上活动的本网络 CKB 地址查询详情，并解析查询地址携带的 Lock Script | 响应仅有一个地址资源，`address_hash` 原样等于查询地址，`lock_script.args`、`code_hash`、`hash_type` 与解析结果一致，且该 Script 的规范哈希唯一对应本次查询的链上 Cells | 地址解析到错误 Script、网络编码被改写或同一请求返回其他地址的数据 | P0 |
| `ADDRESS-RPC-02` | 在公开主网和测试网分别把同一个 Lock Script 编码为当前网络可接受的短地址和完整地址，并依次查询 | 两次响应都定位同一 Lock Script 和同一组状态值；各自 `address_hash` 保留调用方传入的等价编码，余额、计数、DAO、UDT 和特殊地址结果不因编码形式改变 | 短地址与完整地址被拆成两个账户、命中不同缓存或返回不同链上状态 | P1 |
| `ADDRESS-RPC-03` | 在公开主网和测试网分别以一个已存在地址的 32 字节 Lock Script Hash 查询 | 返回单个 `type: "lock_hash"` 资源而不是地址数组；`lock_hash` 等于查询值，`address_hash` 是该 Script 的本网络地址，`lock_script` 与哈希原像一致，且 `lock_info` 按同一 Script 推导 | Lock Hash 被当作地址解析、返回错误响应分支或关联到哈希不匹配的 Script | P0 |
| `ADDRESS-RPC-04` | 在同一稳定链高度分别用 CKB 地址和对应 Lock Script Hash 查询同一账户，并核对两个分支的余额、占用余额、交易数、Live Cell 数和 DAO 数值 | 待确认：两个查询分支的同义状态字段是否必须完全一致；当前地址分支实时聚合 Cells/AccountBook，而 Lock Script Hash 分支返回持久化计数器，若允许短暂差异需明确最大延迟 | 同一账户因入口不同长期显示互相矛盾的余额和计数，或持久化计数器停止更新而未被发现 | P0 |
| `ADDRESS-RPC-05` | 在公开主网和测试网分别以一个已确认映射到多个 CKB 地址的本网络 Bitcoin 地址查询 | 响应成员集合与映射事实中的 CKB 地址集合完全相同且无遗漏、重复或额外成员；每项 `bitcoin_address_hash` 等于查询值，并各自保留对应 CKB Lock Script 和状态 | Bitcoin 地址只返回首个映射、重复地址、串入其他 Bitcoin 地址映射或把多个 CKB 地址错误合并 | P0 |
| `ADDRESS-RPC-06` | 当一个 Bitcoin 地址映射的 CKB 地址数超过 `page_size` 时，分别请求相邻页并重复请求同一页 | 待确认：Bitcoin 多映射结果应采用哪一稳定顺序并真正按 `page`/`page_size` 切片；当前实现只生成分页元数据而未对地址集合分页，可能使相邻页重复返回全量成员 | 大型映射无界返回、分页重复或漏项、数据库无序结果导致翻页漂移 | P1 |
| `ADDRESS-RPC-07` | 在公开主网和测试网分别查询一个格式和网络均有效但没有任何 CKB 映射的 Bitcoin 地址 | 待确认：应返回 `200` 和空 `data` 数组，还是与不存在的 CKB 地址统一返回 Address Not Found；当前实现返回空数组 | 同类不存在资源因地址制式不同产生未声明的状态码和响应形状差异 | P1 |
| `ADDRESS-RPC-08` | 在公开主网和测试网分别对包含多个不同容量 Live Cell 的 CKB 地址查询，并完整翻页读取同一 Lock Script 的 Indexer Live Cells | `balance` 等于全部 Live Cell `output.capacity` 十六进制值无损解码后的 Shannon 总和，`live_cells_count` 等于完整结果数；dead Cells 不计入两者 | 漏页、重复 Cell、把 dead Cell 计入余额、CKB/Shannon 单位混用或大整数精度丢失 | P0 |
| `ADDRESS-RPC-09` | 在公开主网和测试网分别对同时含无 Type/空 Data、含 Type Script、含非空 Data 的 Live Cells 地址查询占用余额 | 待确认：`balance_occupied` 应表示具备 Type Script 或非空 Data 的 Cells 的完整容量总和，还是这些 Cells 的 CKB 最小占用容量总和；当前模型采用前者并以 `type_hash`/`data_hash` 是否为空判定 | 占用容量定义不清、空 Data 被误判、将完整 Cell 容量与最小占用容量混为一谈 | P0 |
| `ADDRESS-RPC-10` | 在公开主网和测试网分别对同一 Lock Script 参与多笔已确认交易、且一笔交易含多个匹配 Cells 的地址查询 | `transactions_count` 等于 Indexer `get_transactions` 完整翻页后按交易哈希去重的已确认交易数，每笔交易只计一次，输入和输出侧活动都计入 | 同一交易按 Cells 重复计数、只统计收款或付款一侧、漏页或把其他 Lock Script 的交易计入 | P0 |
| `ADDRESS-RPC-11` | 在公开主网和测试网分别查询具有 Live DAO Deposit、已完成提现和可领取补偿的地址，并取得相关 RPC 交易、区块头 DAO 字段和 tip DAO | `dao_deposit` 等于 Live DAO Deposit Cells 的容量总和，`interest` 等于已实现补偿，`dao_compensation` 等于 `interest` 加按规范 DAO 公式计算的未领取补偿；所有值均以 Shannon 整数精确比较 | DAO 状态漏算、已领取与未领取补偿重复、区块 DAO 取错或金额浮点失真 | P0 |
| `ADDRESS-RPC-12` | 在公开主网和测试网分别查询含已消费和仍存活 DAO Deposit Cells 的地址，以容量加权计算每笔 CKByte 的锁定时长 | `average_deposit_time` 等于已消费 Cell 从存入到消费、Live Cell 从存入到观测时刻的容量加权平均天数并截断到 6 位小数；待确认：后台生成值允许落后观测时刻多久 | 平均存款时间未按容量加权、单位错误、四舍五入替代截断或后台结果长期不刷新 | P2 |
| `ADDRESS-RPC-13` | 在公开主网和测试网分别查询同时具有已发布和未发布 UDT Account、且已发布账户有 Live Cells 的地址 | `udt_accounts` 只包含已发布账户；每个已发布 Fungible UDT 的 `type_hash`、`udt_type_script` 与链上 Type Script 一致，`amount` 等于该地址同 Type Script Live Cells 数据解析后的整数总和，未发布账户不泄漏到数组 | 未发布资产被公开、Type Script 串号、已消费 Cell 仍计余额或 UDT 大整数精度丢失 | P1 |
| `ADDRESS-RPC-14` | 在每个网络分别查询一个配置中的特殊地址和一个普通地址 | 特殊地址的 `is_special` 为字符串 `"true"` 且 `special_address` 等于当前配置标签；普通地址的 `is_special` 为字符串 `"false"` 且不包含 `special_address` 字段 | 特殊地址标识丢失、普通地址误标或不同网络复用错误标签 | P1 |
| `ADDRESS-RPC-15` | 在公开主网和测试网分别查询格式非法的标识、格式有效但未收录的 CKB 地址，以及不存在的 32 字节 Lock Script Hash | 三类请求都返回 HTTP `404`，错误对象 `code` 为 `1010`、`status` 为 `404`、`title` 为 `Address Not Found`，且不返回空的成功地址资源 | 非法或不存在标识触发服务端异常、误报成功或被错误归类为其他资源错误 | P1 |
| `ADDRESS-RPC-16` | 在主网接口传入与某主网地址具有同一 Lock Script 的测试网 CKB 编码，并在测试网执行反向场景 | 待确认：接口应按 Lock Script 接受等价的异网络 HRP 并在 `address_hash` 中回显查询值，还是必须拒绝非当前网络 CKB 地址；当前查找逻辑未显式校验 HRP 所属网络 | 跨网络地址被静默接受造成转账误导，或等价 Script 因编码前缀被错误拆分 | P1 |
| `ADDRESS-RPC-17` | 在主网接口传入仅对 Bitcoin 测试网有效的地址，并在测试网接口传入仅对 Bitcoin 主网有效的地址 | 两个请求都返回 HTTP `404` 和 Address Not Found；不会命中当前网络的 Bitcoin-to-CKB 映射或返回其他网络成员 | Bitcoin 网络参数未校验导致跨网络地址映射和资产状态串线 | P1 |
| `ADDRESS-RPC-18` | 在任一网络选择 `balance`、`balance_occupied`、DAO 值、交易计数或已发布 UDT `amount` 至少一项大于 `2^53-1` 的地址 | 每个数值都等于整数事实基准并作为完整十进制字符串返回，不出现科学计数、舍入、截断、负数或浮点误差；无公开样本时该项事实基准不可用 | JavaScript 安全整数边界以上的容量、计数或代币数量静默失真 | P0 |
| `ADDRESS-RPC-19` | 某地址的已确认 Live Cell 状态变化且 Explorer 已同步到对应区块后，在变更前后重复查询地址详情 | 允许共享缓存先返回最多 10 秒新鲜旧响应并在随后最多 10 秒 stale-while-revalidate 窗口内完成刷新；窗口结束后的 `balance`、`balance_occupied`、`live_cells_count` 和 `transactions_count` 与新链状态一致 | 缓存长期返回旧余额、不同字段跨版本拼接或新状态永远不触发重验证 | P1 |
| `ADDRESS-RPC-20` | 在公开主网和测试网分别查询符合多签时间锁格式、可由当前 tip Epoch 判断锁定状态的地址 | `lock_info` 的锁定状态、目标 Epoch number/index 和预计解锁时间与 Lock Script args 及同网络 tip Epoch 推导值一致；普通 Lock Script 的 `lock_info` 为 `null` | Since 解码、Epoch 比例换算、网络脚本识别或锁定状态判断错误 | P2 |
| `ADDRESS-RPC-21` | 当存在可审计的矿工地址累计事实基准时，在对应网络查询该地址详情 | `mined_blocks_count` 等于规范链上 Cellbase miner Lock Script 解析后归属该地址的累计区块数，重组失效区块不计入；缺少可审计累计基准时记录为事实基准不可用 | 矿工归属错误、重组区块未回滚或累计计数停止更新 | P2 |
| `ADDRESS-RPC-22` | 在公开主网和测试网分别直接查询一个已由独立映射事实确认绑定 Bitcoin 地址的 CKB 地址，以及一个确认未绑定 Bitcoin 地址的 CKB 地址 | 已绑定地址资源的 `bitcoin_address_hash` 精确等于映射事实中的本网络 Bitcoin 地址，未绑定地址明确返回 `bitcoin_address_hash: null`；该字段不会改变 CKB `address_hash`、Lock Script 或链上状态字段，也不会串入其他地址的映射 | 只有 Bitcoin 地址反查分支能显示映射、直接查询 CKB 地址遗漏绑定关系，或复用错误映射导致跨地址、跨网络串线 | P1 |

## 本轮需要确认

- `ADDRESS-RPC-04`：Lock Script Hash 分支的持久化余额/计数是否必须与 CKB 地址分支的实时聚合值一致；若允许差异，请给出最大同步延迟。
- `ADDRESS-RPC-06`：Bitcoin 多映射的稳定排序键、分页切片语义，以及空页的预期结果；当前源码未对集合执行分页。
- `ADDRESS-RPC-07`：格式有效但无映射的 Bitcoin 地址应返回空成功结果还是 Address Not Found。
- `ADDRESS-RPC-09`：`balance_occupied` 的产品定义是完整容量总和还是 CKB 最小占用容量总和，以及空 Data Cell 的判定规则。
- `ADDRESS-RPC-12`：`average_deposit_time` 后台计算相对观测时间允许的最大陈旧窗口。
- `ADDRESS-RPC-16`：异网络 HRP 的 CKB 地址是否应按等价 Lock Script 接受，还是按网络边界拒绝。
- `ADDRESS-RPC-21`：公开环境缺少可审计的全链累计矿工基准时，是否保留为非持续执行用例。
- 请确认新增 `ADDRESS-RPC-22` 可作为直接查询 CKB 地址时验证 Bitcoin 映射字段及未绑定空值的评审依据；本轮只补充测试点，不进入自动化门禁。
