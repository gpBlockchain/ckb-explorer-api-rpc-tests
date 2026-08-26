# 地址 DAO 活动 RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB Indexer、节点 RPC、DAO Type Script、DAO Cell Data、Header Dependency 和区块头为基准，核对 `GET /api/v1/address_dao_transactions/:id` 与带 `address` 的 `GET /api/v2/dao_events`
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：V1 按 CKB 地址或 Lock Script Hash 返回该地址参与的 Nervos DAO 交易列表；V2 按 `address` 返回当前 DAO 存款容量、容量加权平均存款天数及同一组 DAO 交易活动。
- DAO 事件判定：输出 DAO Type Script 且 Data 为 8 字节零值表示存款；消费 Deposit Cell 并生成 Data 指向存款区块号的 DAO Cell 表示取款第一阶段；消费 Withdrawing Cell、携带相应 Header Dependency 并释放本金加补偿表示利息领取。一个交易含多个同地址 DAO Cells 时仍按交易哈希去重。
- 分页与顺序：V1 接受 `page`、`page_size`，固定按区块时间倒序、同时间按交易索引倒序且不接受业务过滤或调用方排序；V2 接受 `page`、`page_size`，仅以 `address` 过滤且不提供公开排序参数。
- 事实基准：先校验 Explorer 与节点处于同网络，在稳定规范链窗口内用 Indexer 定位地址交易和 Cells，再以节点 `get_transaction`、`get_block`、输入引用交易与必要区块头复算；RPC/Indexer 缺失、同高度哈希变化或重组时该网络事实基准不可用。
- 数值：所有容量、补偿和计数以 Shannon 整数无损比较；`average_deposit_time` 按每笔 CKByte 的锁定毫秒数进行容量加权并换算为天后截断到 6 位小数。
- 不负责：全局 DAO 合约交易/统计、存款人排名、通用媒体类型、分页错误响应格式、RGB/Bitcoin/UDT 注解真实性，以及后台平均存款时间刷新调度本身。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `ADDR-DAO-RPC-01` | 在公开主网和测试网分别以一个产生 DAO Deposit Cell 的本网络 CKB 地址请求 `GET /api/v1/address_dao_transactions/:id` | 返回包含该存款交易且仅包含目标地址关联的 DAO 交易；交易哈希、区块高度、时间戳、输入/输出数量与 RPC 一致，输出预览包含目标地址、存款容量、DAO Type Script 和零值 Data 对应的 `nervos_dao_deposit` Cell | 普通转账被当 DAO 存款、DAO Type/Data 识别错误或交易链上字段串单 | P0 |
| `ADDR-DAO-RPC-02` | 同一地址完成存款、取款第一阶段和利息领取，查询 V1 DAO 交易列表 | 三阶段交易各出现一次；取款交易消费原 Deposit Cell 并生成 Data 指向原存款区块的 Withdrawing Cell，领取交易消费该 Cell、引用规定区块头并释放本金和按 DAO 公式计算的补偿 | DAO 生命周期缺阶段、把第一阶段当最终领取、Header Dependency 或补偿关联错位 | P0 |
| `ADDR-DAO-RPC-03` | 分别用同一 Lock Script 的 CKB 地址和 32 字节 Lock Script Hash 查询 V1 DAO 交易 | 两次响应的 DAO 交易集合、顺序、分页总数及逐笔链上字段完全一致 | 地址与 Lock Hash 解析到不同 DAO 账户或命中不同关联缓存 | P0 |
| `ADDR-DAO-RPC-04` | 一笔交易为同一地址产生或消费多个 DAO Cell，并同时含其他地址 DAO Cell | 目标地址关联交易按交易哈希只返回一次，输入/输出计数仍反映完整交易，其他地址独有 DAO 交易不出现 | 按 DAO Event/Cell 重复交易、为过滤地址裁剪原始交易结构或跨地址串单 | P0 |
| `ADDR-DAO-RPC-05` | 存款地址与取款交易输出地址不同，分别查询两个地址的 V1 DAO 活动 | 存款、取款第一阶段及领取事件归属于各阶段实际被消费 DAO Cell 的 Lock Script；任一地址仅返回自身关联事件，不因交易另一个输出地址而整体继承全部活动 | DAO 所有权按交易任意输出归属、换址提现造成活动串号 | P0 |
| `ADDR-DAO-RPC-06` | V1 地址包含跨多个区块且同区块含多笔 DAO 交易，请求默认页、相邻页和自定义 `page_size` | 默认每页 10 条，按区块时间倒序且同区块按交易索引倒序；相邻页成员不重不漏，`meta.total` 等于去重后的全部地址 DAO 交易数，越界页为空 | DAO 时间线乱序、同区块并列漂移、分页重复漏项或总数按事件而非交易计算 | P1 |
| `ADDR-DAO-RPC-07` | V1 返回一笔输入或输出超过 10 项的 DAO 交易 | `display_inputs_count`、`display_outputs_count` 等于完整 RPC 结构数量，预览各最多 10 项且保持 Cell 顺序；DAO 输入展示的存取起止区块、时间、补偿和锁定高度可由引用 Cell、Data、Header Dependency 与区块头推导 | 预览上限误改总数、DAO 补偿窗口错配或大交易响应无界 | P1 |
| `ADDR-DAO-RPC-08` | V1 查询已存在但无 DAO 交易的地址、格式非法标识及格式有效但未收录地址 | 已存在空地址成功返回 `data=[]` 和总数 0；格式非法返回 Address Hash Invalid，格式有效但未收录返回 Address Not Found，均不包含其他地址活动 | 空 DAO 历史误报不存在、错误类型混淆或缓存泄漏其他地址交易 | P1 |
| `ADDR-DAO-RPC-09` | V1 目标 DAO Cell 容量、本金加补偿或相关整数超过 `2^53-1` Shannon | 交易预览中的容量、补偿及区块字段均按完整十进制整数与 RPC/DAO 公式一致，不出现浮点舍入、科学计数或负数溢出 | 大额 DAO 存款和补偿在序列化或推导中失真 | P0 |
| `ADDR-DAO-RPC-10` | DAO 交易所在区块发生重组或 RPC/Indexer 暂缺目标交易、引用 Cell、区块头 | 重组观测期间或任一必要事实缺失时仅把该网络该轮事实基准标为不可用；Explorer 同步新规范链后列表移除旧交易并纳入新交易，另一个网络结果不受影响 | 把重组/节点缺失当 API 数据错误，或 DAO Event 回滚后仍残留旧活动 | P1 |
| `ADDR-DAO-RPC-11` | 以存在三阶段 DAO 历史且仍有 Live DAO Deposit 的 CKB 地址请求带 `address` 的 `GET /api/v2/dao_events` | `data.address` 对应该 Lock Script 的当前网络地址，`activities` 的交易集合与同地址 V1 列表及链上三阶段事实一致；每项哈希、区块字段、完整输入输出及 DAO Cell 展示值均可由 RPC 推导，且不含 `is_cellbase` 和 `income` | V1/V2 使用不同 DAO 事件集合、V2 丢阶段或泄漏未约定字段 | P0 |
| `ADDR-DAO-RPC-12` | 分别以 CKB 地址和对应 `0x` Lock Script Hash 作为 V2 `address` 参数查询 | 两次响应定位同一地址记录，`deposit_capacity`、`average_deposit_time`、活动集合和 `meta.total` 一致 | V2 地址转换不接受 Lock Hash、两种入口命中不同账户或返回不同汇总 | P1 |
| `ADDR-DAO-RPC-13` | V2 查询一个含多个 Live Deposit Cells、已消费 Deposit Cell 和已完成领取历史的地址 | `deposit_capacity` 等于当前仍处于 DAO 存款状态的 Live Deposit Cell 容量总和，已进入取款阶段或已领取的本金不再计入；数值以完整十进制 Shannon 字符串返回 | 当前存款混入历史本金、重复累计多阶段 Cell 或汇总缓存未更新 | P0 |
| `ADDR-DAO-RPC-14` | V2 查询同时含已消费与 Live Deposit Cells 的地址，并固定可审计的观测时刻 | `average_deposit_time` 等于各 Deposit Cell 容量乘其存入至消费或观测时刻的毫秒数之和，再除以总存款容量和每日毫秒数并截断到 6 位小数；待确认：后台生成值相对观测时刻允许落后多久 | 未按容量加权、已消费 Cell 用当前时刻、单位/截断错误或后台长期陈旧 | P2 |
| `ADDR-DAO-RPC-15` | V2 请求默认页、相邻页、自定义 `page_size` 和越界页 | 默认活动页大小 10；相邻页活动不重不漏，`meta.total` 等于去重后的全部地址 DAO 交易数，`meta.page_size` 等于请求采用值，越界页 `activities=[]` 但地址汇总保持不变 | V2 分页改变汇总值、总数按当前页、页大小元数据错误或空页丢地址 | P1 |
| `ADDR-DAO-RPC-16` | V2 查询具有同时间或跨区块 DAO 交易的地址并重复翻页 | 待确认：V2 DAO 活动应采用与 V1 相同的区块时间/交易索引倒序，还是定义另一公开稳定排序；当前查询未声明数据库排序，无法保证重复分页无漂移 | 无序关联导致跨页重复漏项、V1/V2 时间线相反或不同数据库计划改变结果 | P1 |
| `ADDR-DAO-RPC-17` | 一笔交易为同一地址产生多个 DAO Event，另有其他地址独有 DAO 交易，查询 V2 | `activities` 按交易哈希去重且只含目标地址关联交易，`meta.total` 与去重交易数一致；其他地址独有活动和汇总值不进入响应 | V2 按 Event 重复交易、总数膨胀或跨地址汇总串号 | P0 |
| `ADDR-DAO-RPC-18` | V2 查询已存在但从未参与 DAO 的地址 | 返回该地址身份，`deposit_capacity="0"`、`average_deposit_time` 为零值、`activities=[]`、`meta.total=0`，不会误用全局 DAO 数据 | 空历史被误报 404、返回 null 破坏数值契约或泄漏全局活动 | P1 |
| `ADDR-DAO-RPC-19` | V2 缺少 `address`、传入格式非法地址或格式有效但未收录的地址/Lock Hash | 三类请求都返回 HTTP `404` 且无成功 `data`；不会触发 500、回退到全局 DAO Events 或返回相邻地址 | 缺少过滤条件泄漏全局活动、非法解析崩溃或不存在地址误报成功 | P1 |
| `ADDR-DAO-RPC-20` | V2 地址当前 DAO 存款容量或任一活动 Cell 容量/补偿超过 `2^53-1` Shannon | `deposit_capacity` 和活动内数值均与 RPC/DAO 公式的完整整数一致并以无损十进制表示，分页和 V1/V2 对照不改变精度 | V2 汇总字符串与活动数值精度不一致或大整数静默舍入 | P0 |
| `ADDR-DAO-RPC-21` | 地址新增存款、进入取款阶段、完成领取或所在区块重组，且 Explorer 已同步到稳定规范链后重复查询 V1/V2 | 两个接口最终反映同一规范 DAO 时间线：新增事件出现、重组事件消失，V2 当前存款随存款增加并在第一阶段消费后减少，平均时间按下一次后台刷新更新；观测到链变化时该轮事实基准不可用 | V1/V2 状态转换不同步、DAO 存款长期不变或重组 Event 未回滚 | P1 |
| `ADDR-DAO-RPC-22` | 在稳定且足以产生不同分页结果的 V1 地址 DAO 交易集合上，于同一小时结果缓存期内交错请求不同 `page`、`page_size` 组合，并重复其中一个完全相同的 URL | 每个响应的交易切片、`meta.current_page`、`meta.page_size` 和分页链接只对应本次参数；完全相同的 URL 可以复用缓存，不同页码或页长不得因底层记录集合相同而共享其他请求的序列化结果 | 结果缓存键只包含查询记录而忽略分页参数，导致不同页码、页长返回错误成员、元数据或分页链接 | P1 |

## 本轮需要确认

- `ADDR-DAO-RPC-14`：V2 `average_deposit_time` 后台值相对本次观测时刻允许的最大陈旧窗口。
- `ADDR-DAO-RPC-16`：V2 DAO 活动的正式稳定排序键；是否必须与 V1 的区块时间、交易索引倒序一致。
- 请确认新增 `ADDR-DAO-RPC-22` 可作为 V1 地址 DAO 交易在一小时结果缓存期内隔离不同分页查询的评审依据；本轮只补充测试点，不进入自动化门禁。
