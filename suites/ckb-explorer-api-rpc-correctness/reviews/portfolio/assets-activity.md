# Portfolio 地址与资产数据正确性用例评审

评审范围：核对 JWT 用户的地址同步、CKB/DAO 统计、UDT/NFT 账户、已提交交易列表及 CSV 导出的链上正确性和用户隔离
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：维护当前用户跟踪的 CKB 地址集合，并从该集合返回容量与 DAO 汇总、代币账户、交易活动和导出文件。
- 输入：有效 Authorization JWT；`POST /api/v2/portfolio/addresses` 的 `addresses`，`GET /api/v2/portfolio/statistics` 的 `latest_address`，`GET /api/v2/portfolio/udt_accounts` 的 `cell_type`、`published`，`GET /api/v2/portfolio/ckb_transactions` 的地址/交易哈希/排序/分页，以及 `GET /api/v2/portfolio/ckb_transactions/download_csv` 的日期或区块范围。
- 成功结果：所有数据只来自 JWT 用户的地址集合；链上容量和交易值与同网络 CKB RPC/Indexer 一致，整数金额不经浮点转换，CSV 与同一过滤范围的用户交易一致。
- 失败结果：无效地址、最新地址不一致、越权地址过滤或非法查询返回领域错误，且地址集合及用户数据不发生部分变更。
- 不负责：登录与 JWT 签发、代币名称和图标等外部元数据的真实性、通用分页/缓存契约及 CSV 响应头。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `PORTFOLIO-ASSET-RPC-01` | 当前用户提交同网络多个有效 CKB 地址，其中包含重复地址，并再次提交相同集合 | 每次成功均返回 204；用户跟踪集合等于地址去重后的并集，重复提交不产生重复成员，也不会删除此前已跟踪地址 | 地址同步重复建档、重复计数或把增量同步误作全量替换 | P0 |
| `PORTFOLIO-ASSET-RPC-02` | 一个批次同时包含有效地址和无法解析或属于其他网络的地址 | 返回地址同步错误，批次中的有效地址也不加入用户集合，原有地址、统计和交易范围保持不变 | 部分批次写入造成用户资产范围处于不可预测状态 | P1 |
| `PORTFOLIO-ASSET-RPC-03` | 用户 A 与用户 B 分别同步不同地址，并各自调用统计、UDT 账户、交易列表和 CSV | 每个响应只含自身地址可推导的数据，A 的 JWT 不能读取或改变 B 的地址、余额、代币或交易 | Portfolio 多租户隔离失效导致资产和活动泄露 | P0 |
| `PORTFOLIO-ASSET-RPC-04` | 用户跟踪多个含 Live Cell、DAO 存款和补偿的地址，并以集合内最新地址调用统计接口 | `balance`、`balance_occupied`、`dao_deposit`、`interest` 分别等于同网络链数据对所有用户地址的整数和，`dao_compensation` 等于 `interest + unclaimed_compensation`；所有金额以十进制字符串返回且不丢失 Shannon 精度 | 聚合漏地址、DAO 补偿公式错误或大整数经浮点转换失真 | P0 |
| `PORTFOLIO-ASSET-RPC-05` | 统计请求的 `latest_address` 缺失、格式错误或不属于当前用户，随后用正确最新地址重试 | 先返回地址或同步差异错误并保持用户集合不变；差异错误指出服务端已同步的最后地址，使用正确地址后返回完整统计 | 客户端与服务端地址集合不一致时静默返回错误资产总额 | P1 |
| `PORTFOLIO-ASSET-RPC-06` | 用户多个地址持有同一已发布 sUDT 及其他已发布/未发布 sUDT，分别查询默认、`published=true` 和 `published=false` | 同一 `type_hash` 的账户合并为一项，`amount` 是各地址链上 UDT 数量的无损整数和，`decimal` 和 `amount` 为字符串；published 过滤只返回对应发布状态 | 同一代币重复展示、过滤失效或超过安全整数范围的代币数量失真 | P0 |
| `PORTFOLIO-ASSET-RPC-07` | 用户地址分别持有 mNFT、NRC-721、Spore 和 DID Cell，并以非 `sudt` 类型查询 UDT 账户 | 返回每个已发布 NFT 账户及其链上 token ID/type hash，按类型附带可用的 collection type hash 和展示数据；缺少可选 collection 元数据不会丢失账户身份 | NFT 类型分支漏项、把 token ID 当浮点数或可选元数据为空时整项崩溃 | P1 |
| `PORTFOLIO-ASSET-RPC-08` | 用户多个地址共同参与同一笔已提交普通交易，并包含其他地址或待处理交易，再请求默认交易列表 | 仅返回用户地址参与的 committed 交易，每个交易哈希只出现一次；`income` 等于该交易对用户全部跟踪地址的输入输出容量净和，按 Shannon 整数精确表示，非用户和非 committed 交易不进入列表 | 多地址交易重复、净变化只取一个地址、待处理或他人交易泄露 | P0 |
| `PORTFOLIO-ASSET-RPC-09` | 使用 `address_hash` 过滤当前用户地址和不属于当前用户的有效地址，并组合 `tx_hash`、排序及相邻分页 | 用户地址过滤后的成员、总数和顺序与同网络 CKB RPC/Indexer 推导集合一致且跨页无重漏；外部地址返回无数据或领域错误，不得越过 Portfolio 地址范围 | 地址过滤绕过用户边界、交易过滤失效或分页前重复 AccountBook 导致漏重 | P0 |
| `PORTFOLIO-ASSET-RPC-10` | 对包含区块边界、日期边界和超大 Shannon 数值的用户交易分别使用默认范围及有效日期/高度范围下载 CSV | CSV 仅含当前用户在闭合过滤范围内的交易，交易身份和稳定列值与同网络链数据一致，大整数容量与净变化以精确十进制文本输出，边界交易各出现一次 | CSV 泄露其他用户交易、范围 off-by-one、重复导出或表格数值精度丢失 | P0 |
| `PORTFOLIO-ASSET-RPC-11` | CSV 使用反向范围、畸形日期/高度或不相交范围，失败后再执行有效导出 | 无效范围返回确定的参数错误或空结果契约且不改变用户地址和交易状态，后续有效导出仍返回正确文件 | 导出错误触发状态变更、范围异常导致 500 或污染后续导出 | P1 |

## 本轮需要确认

- 无；越权 `address_hash` 过滤按用户隔离属性处理，预期不得查询 Portfolio 之外的有效地址。
