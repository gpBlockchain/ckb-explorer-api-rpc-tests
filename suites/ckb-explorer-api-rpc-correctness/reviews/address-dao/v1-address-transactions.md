# V1 地址交易流 RPC 正确性用例评审

评审范围：在公开主网和测试网分别用同网络 CKB Indexer、节点 RPC、交易池查询及必要的 Bitcoin-to-CKB 映射事实，核对 `GET /api/v1/address_transactions/:id`、`GET /api/v1/address_transactions/download_csv` 和 `GET /api/v1/address_pending_transactions/:id`
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 CKB 地址、Lock Script Hash 或受支持的 Bitcoin 地址返回地址参与的已提交交易、导出地址交易 CSV，并返回地址参与的待处理交易。
- 输入与顺序：列表接受 `page`、`page_size`、`sort`；已提交列表默认倒序，待处理列表按内部交易序号排序。CSV 接受含端点的 `start_date`、`end_date`、`start_number`、`end_number` 过滤，不接受调用方分页或排序，固定最多导出 500 笔关联交易。
- 事实基准：已提交交易通过同网络 Indexer `get_transactions` 完整翻页后按交易哈希去重，再用节点 `get_transaction`、`get_block` 和输入引用交易核对；待处理交易在调用前后读取同一节点交易池，只有两次池成员及目标交易状态一致时才比较；Bitcoin 查询另以独立确认的地址映射为基准。
- 数值与动态状态：容量、手续费、`income` 和 UDT 数量均以整数无损解析，CKB 金额先以 Shannon 比较再按 CSV 规则转为 CKB；主网和测试网独立判定。RPC/Indexer 缺失、同高度哈希变化、交易重组或待处理池在观测窗口变化时，该网络对应事实基准不可用而不是 API 不一致。
- CSV 内容：精确核对固定 10 列表头及每一数据行；同一交易按涉及的 CKB/UDT 单位各一行，手续费只展示一次，UTC 时间由毫秒时间戳确定性换算。Token 名称只按 Explorer 已发布元数据验证展示映射，链上 Type Script 和整数数量仍由 RPC/Indexer 验证。
- 不负责：通用媒体类型、请求头、分页参数错误格式和 CSV 下载头，DAO 专属活动，RGB/Bitcoin/UDT 展示注解本身的可信度，数据库 `created_at`，以及交易池持续变化时的瞬时全序。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `ADDR-TX-RPC-01` | 在公开主网和测试网分别以一个参与多笔已提交普通交易的本网络 CKB 地址请求 `GET /api/v1/address_transactions/:id` | 返回交易哈希集合等于同一 Lock Script 在 Indexer 完整翻页所得交易集合按哈希去重后的已提交成员；每笔输入侧或输出侧参与均计入一次，pending、rejected 及其他地址交易不计入 | 地址交易漏项、同一交易按多个 Cell 重复、混入未提交状态或其他地址活动 | P0 |
| `ADDR-TX-RPC-02` | 分别用同一 Lock Script 的 CKB 地址和 32 字节 Lock Script Hash 查询已提交交易 | 两次响应的交易集合、顺序、分页总数和逐笔链上字段一致，且展示 Cell 中的地址保持各入口约定的等价地址表示 | 地址与 Lock Hash 入口定位不同账户、命中不同交易集合或改写展示地址 | P0 |
| `ADDR-TX-RPC-03` | 以一个已由独立事实基准确认映射到多个 CKB Lock Script 的 Bitcoin 地址查询已提交交易 | 返回集合等于全部映射 Lock Script 的关联交易并按交易唯一，`meta.total` 与映射后的关联记录数一致；不混入其他 Bitcoin 地址映射 | Bitcoin 映射只查首个地址、重复同一 CKB 交易或串入其他映射 | P1 |
| `ADDR-TX-RPC-04` | 查询一笔包含多个输入和输出、且目标地址同时出现在两侧的已提交交易 | `transaction_hash`、`block_number`、`block_timestamp`、`is_cellbase` 与 RPC 一致；`display_inputs_count` 和 `display_outputs_count` 等于完整原始结构数量，两个预览分别保持原始 Cell 顺序且最多 10 项，预览 Cell 的 out-point、容量、地址和类型脚本可由引用交易及本交易推导 | 预览计数被 10 项截断、输入引用错位、输出乱序或链上摘要字段串单 | P0 |
| `ADDR-TX-RPC-05` | 对目标地址在同一交易既支出又接收、并含大于 `2^53-1` Shannon 总额的已提交交易查询 | `income` 精确等于目标地址所有输出容量减所有输入引用容量的 Shannon 整数，结果不含其他地址容量且无浮点舍入、科学计数或符号反转 | 找零被当收入、跨地址容量串算或大整数净变化失真 | P0 |
| `ADDR-TX-RPC-06` | 请求默认页、相邻页及自定义 `page_size`，并在同一稳定高度重复其中一页 | 默认每页 10 条；各页成员不重不漏，`meta.total` 等于该地址全部已提交关联交易数，空的越界页返回空 `data`，重复页结果稳定 | 分页重复/漏项、总数使用全网交易数、页大小失效或空页报错 | P1 |
| `ADDR-TX-RPC-07` | 对跨多个区块且同区块含多笔交易的地址分别使用 `sort=time.desc` 与 `sort=time.asc` | `desc` 按区块高度倒序且同区块按交易索引倒序，`asc` 完全反向；相邻页沿同一全序切分且无并列漂移 | 排序参数仅改变数据库 ID、同区块顺序错误或翻页期间产生重复遗漏 | P1 |
| `ADDR-TX-RPC-08` | 分别查询一个已存在但无已提交交易的地址、格式非法的标识和格式有效但未收录的地址 | 已存在空地址返回成功且 `data=[]`、`meta.total=0`；非法或未收录标识返回 Address Not Found 错误且不泄漏其他地址数据 | 空集合误报不存在、非法输入触发服务端异常或缓存串号 | P1 |
| `ADDR-TX-RPC-09` | 选择两组共享同一笔交易但各自还含独有交易的地址分别查询 | 共享交易各出现一次，各自独有交易仅出现在所属地址响应，逐笔 `income` 只按当前查询地址计算 | 多对多关联造成跨地址串单或复用错误的净变化 | P0 |
| `ADDR-TX-RPC-10` | 某地址出现新确认交易或规范链重组且 Explorer 已完成同步后，在缓存窗口前后重复查询 | 允许 10 秒新鲜缓存及随后最多 5 秒 stale-while-revalidate；窗口结束后新增规范链交易出现、被重组交易消失且总数和分页重新一致，观测到重组中的比较标记为事实基准不可用 | 缓存长期保留旧交易、重组回滚不完整或分页总数与成员跨版本 | P1 |
| `ADDR-TX-RPC-11` | 对同时有关联已提交交易和 pending 交易、且已提交交易包含 CKB 转移的地址请求 `GET /api/v1/address_transactions/download_csv` | CSV 第一行严格为 `Txn hash,Blockno,UnixTimestamp,Token,Method,Token In,Token Out,Token Balance Change,TxnFee(CKB),date(UTC)`；数据成员只包含已提交地址交易，每笔 CKB 行的哈希、高度、毫秒时间戳、`CKB`、收付方向、目标地址输入/输出 CKB、绝对余额变化、由总输入减总输出得到的手续费及 UTC 时间均与 RPC 推导值逐列一致 | 只校验行数而漏掉 pending 混入、错列、单位错误、方向反转、手续费或时区错误 | P0 |
| `ADDR-TX-RPC-12` | 地址交易同时涉及已发布 UDT、未发布 UDT 与 CKB，下载 CSV 并按交易和 Type Script 分组核对每一行 | 每个交易/资产单位恰有一行；已发布 UDT 的 `Token` 使用登记 symbol，未发布 UDT 使用 `Unknown Token #` 加 type hash 后四位；Token In/Out/Balance Change 由 Cell Data 的无符号小端整数和 decimal 确定性转换，CKB 行展示手续费，其他行用 `/`，若交易没有 CKB 行则仅首个 Token 行展示手续费 | 多资产合并、代币 Type Script 串号、原始整数或 decimal 失真、手续费重复或丢失 | P0 |
| `ADDR-TX-RPC-13` | 分别只给 `start_date`、`end_date` 及同时给出二者，边界时间戳上各有一笔关联交易 | CSV 成员分别满足 `block_timestamp >= start_date`、`<= end_date` 和闭区间交集；恰在任一端点的交易保留，区间外及其他地址交易排除 | 毫秒/秒混用、端点开闭错误或日期过滤越界 | P1 |
| `ADDR-TX-RPC-14` | 分别只给 `start_number`、`end_number` 及同时给出二者，边界区块各有一笔关联交易 | CSV 成员分别满足 `block_number >= start_number`、`<= end_number` 和闭区间交集；端点交易保留且筛选后的每行仍与对应 RPC 交易一致 | 区块过滤方向反转、端点丢失或只过滤展示行未过滤交易 | P1 |
| `ADDR-TX-RPC-15` | 一个地址关联超过 500 笔已提交交易，分别下载无过滤和缩小过滤窗口的 CSV | 无过滤导出只取按区块高度、交易索引倒序的最近 500 笔关联交易并展开其资产行；过滤先应用闭区间再执行 500 笔上限，CSV 不受 `page`、`page_size` 或 `sort` 参数改变 | 导出无界耗尽资源、先截断再过滤漏数据或分页参数意外改变 CSV | P1 |
| `ADDR-TX-RPC-16` | 同一地址的一笔交易产生多个同资产输入/输出 Cell，另一地址参与同笔交易 | CSV 在目标地址范围内先按 CKB 或同一 UDT Type Script 汇总为一行，交易不会因多个 AccountBook/Cell 重复；另一地址的 Cell 金额不进入本地址行 | CSV 按 Cell 重复出行、跨地址汇总或余额变化重复累计 | P0 |
| `ADDR-TX-RPC-17` | 对已存在但过滤后无交易的地址下载 CSV，并对格式非法或未收录地址下载 | 空结果只返回固定表头且无数据行；非法或未收录地址返回 Address Not Found 错误而不是空的成功文件 | 空导出格式不稳定、错误地址生成误导文件或泄漏其他地址行 | P1 |
| `ADDR-TX-RPC-18` | CSV 中 CKB 容量、手续费或 UDT 原始数量至少一项超过 `2^53-1`，并包含高 decimal 或无已发布元数据的 UDT | 所有原始整数先无损聚合；CKB 精确按 `10^8` Shannon/CKB 转换，已知 decimal 按既定小数规则输出、未知 decimal 保留完整整数并标记 `(raw)`，不出现二进制浮点误差 | 大额容量/代币静默舍入、精度截断后余额不守恒或未知代币被错误缩放 | P0 |
| `ADDR-TX-RPC-19` | 以确认映射到一个或多个 CKB 地址的 Bitcoin 地址下载 CSV | 待确认：CSV 是否应合并全部映射地址的交易并按 Bitcoin 归属汇总，还是只支持 CKB 地址/Lock Script Hash 并明确报错；当前地址解析可返回多个映射但 CSV 行按 CKB `address_id` 集合汇总 | Bitcoin 地址导出结果被静默截成首个映射、跨映射重复或接口能力不一致 | P1 |
| `ADDR-TX-RPC-20` | 在交易池前后两次快照完全相同的有界窗口内，以 CKB 地址请求 `GET /api/v1/address_pending_transactions/:id` | 返回集合等于稳定池中输入引用或输出 Lock Script 匹配目标地址且 Explorer 已索引为 pending 的交易；每笔按哈希唯一，不含 committed、rejected 或其他地址交易；池快照、RPC 结果或状态变化时该网络事实基准不可用 | 用动态池直接判错、pending 集合漏项/重复或混入其他状态 | P0 |
| `ADDR-TX-RPC-21` | 分别用同一 Lock Script 的 CKB 地址和 32 字节 Lock Script Hash 查询稳定池中的待处理交易 | 两次响应返回相同交易集合、顺序和总数，展示 Cell 地址按等价地址规则一致；两次查询之间池变化则两项均标记事实基准不可用 | 地址与 Lock Hash 使用不同 pending 关联、缓存版本不一致或跨请求误判 | P1 |
| `ADDR-TX-RPC-22` | 稳定池中一笔交易含多个输入和输出且目标地址在两侧，查询其待处理列表 | `transaction_hash` 与池中原始交易一致，区块字段为空值表示尚未提交；输入/输出总数来自完整原始交易，预览保持顺序且各最多 10 项，输入 out-point 和容量由稳定池交易或节点可取的引用交易推导 | pending 交易伪造区块归属、预览错位或引用 Cell 缺失时返回其他交易数据 | P0 |
| `ADDR-TX-RPC-23` | 稳定池中目标地址的输入/输出容量总额超过 `2^53-1` Shannon | `income` 精确等于该 pending 交易对目标地址的输出容量减输入引用容量，使用完整有符号 Shannon 整数且不受其他地址找零影响 | pending 净变化大整数失真、找零串算或负值被截成零 | P0 |
| `ADDR-TX-RPC-24` | 对稳定池中的多笔地址交易请求默认页、相邻页和自定义 `page_size` | 默认每页 10 条，相邻页成员不重不漏，`meta.total` 等于该地址已索引 pending 关联数，越界页为空；任一比较期间池变化则事实基准不可用 | pending 分页总数使用全池数量、重复漏项或对动态变化做错误断言 | P1 |
| `ADDR-TX-RPC-25` | 稳定池包含目标地址和另一地址各自独有及共享交易，分别查询两个地址 | 共享交易在各自响应中各出现一次，独有交易只归属对应地址，每个响应的 `income` 按自身地址独立计算 | pending AccountBook 多对多关联串号、共享交易重复或复用错误收入 | P0 |
| `ADDR-TX-RPC-26` | 对同一稳定池分别使用默认排序、`sort=time.asc`、`sort=time.desc` 和未知排序键重复查询 | 待确认：pending 交易应以节点可验证的哪个字段建立稳定全序，以及未知排序键应拒绝还是回退；当前实现把 `time` 映射到通常为空的 `block_timestamp`，其他键映射内部 ID，无法从 RPC 独立证明并列顺序 | 依赖数据库内部 ID、空时间字段导致随机翻页或未知排序静默改变结果 | P1 |
| `ADDR-TX-RPC-27` | 分别查询已存在但无 pending 交易的地址、格式非法标识及格式有效但未收录地址 | 已存在空地址返回成功且 `data=[]`、`meta.total=0`；非法或未收录标识返回 Address Not Found 错误且不返回其他地址池成员 | 空交易池误报地址不存在、错误输入触发异常或 pending 数据泄漏 | P1 |
| `ADDR-TX-RPC-28` | 一笔地址交易从 pending 转为 committed，且 Explorer 已同步包含它的规范区块，在状态转换前后跨缓存窗口查询两个列表 | 稳定 pending 阶段只出现在 pending 列表；确认并经过最长 10 秒新鲜加 10 秒 stale-while-revalidate 窗口后从 pending 消失并出现在已提交列表，两个列表均不重复；重组或池变化时该轮事实基准不可用 | 同一交易长期同时显示两种状态、确认后仍滞留 pending 或从两端丢失 | P0 |
| `ADDR-TX-RPC-29` | 待处理池查询期间 RPC 传输失败、目标交易/输入引用暂不可取、前后池快照不同或观测到交易状态变化 | 该网络本次 pending 事实基准明确记为不可用并保留原因，另一个网络仍独立执行；不会把不可验证状态报告为 API 字段不一致 | 上游瞬时波动制造伪失败、一个网络故障掩盖另一个网络结果 | P1 |
| `ADDR-TX-RPC-30` | 以独立确认映射到多个 CKB Lock Script 的 Bitcoin 地址查询稳定池中的待处理交易 | 待确认：响应是否应合并全部映射 Lock Script 的 pending 交易、按哈希去重并把 `income` 汇总到 Bitcoin 地址，还是 pending 接口只正式支持 CKB 地址/Lock Script Hash；当前实现会查询多个映射但每笔 `income` 只取一个关联账户 | Bitcoin pending 只查首个映射、重复交易、随机选择一个地址净变化或接口能力不一致 | P1 |

## 本轮需要确认

- `ADDR-TX-RPC-19`：地址交易 CSV 对 Bitcoin 地址的正式契约，是合并全部映射 CKB 地址，还是只接受 CKB 地址/Lock Script Hash 并明确报错。
- `ADDR-TX-RPC-26`：地址 pending 列表的可公开验证稳定排序键，以及未知 `sort` 值的错误或回退语义。
- `ADDR-TX-RPC-30`：地址 pending 列表对 Bitcoin 多映射的正式契约，以及 `income` 是按各 CKB 地址分别表示还是按 Bitcoin 地址汇总。
