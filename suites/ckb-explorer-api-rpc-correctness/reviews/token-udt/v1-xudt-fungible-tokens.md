# V1 xUDT 与统一同质化代币目录、导出和快照 RPC 正确性用例评审

评审范围：核对 xUDT 与 fungible-token 列表和详情、两个交易 CSV 入口及 xUDT 指定区块余额快照的成员、过滤和链上推导值
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：提供 xUDT/xUDT-compatible 专用目录、已发布同质化代币统一目录、详情与交易导出，并按指定区块重建已发布 xUDT 的持有人余额快照。
- 输入：`GET /api/v1/xudts` 与 `GET /api/v1/fungible_tokens` 使用 `type`、`symbol`、`tags`、`union`、`page`、`page_size`、`sort`；`GET /api/v1/xudts/:id` 与 `GET /api/v1/fungible_tokens/:id` 使用 Type Hash；`GET /api/v1/xudts/download_csv` 与 `GET /api/v1/fungible_tokens/download_csv` 使用 UDT ID 和日期/高度范围；`GET /api/v1/xudts/snapshot` 使用 `id`、`number`、`merge_with_owner`、`format`。
- 成功结果：目录成员和标签符合控制器范围，链相关 Type Script、SSRI OutPoint、交易和历史 live Cell 集合可由同网络 RPC/Indexer 验证；所有代币金额从整数原始值无损计算。
- 失败结果：分页、Type Hash、区块或快照依赖无效时返回对应错误；事实源缺失或取样发生重组时仅标记依赖链状态的结论不可用。
- 不负责：普通 sUDT 专用目录、Omiga 生命周期、元数据写入、地址维度交易视图以及通用 HTTP/下载头契约。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `XUDT-FT-RPC-01` | - [x] xUDT 和 xUDT-compatible 同时存在时省略 `type` 请求 xUDT 列表，再传 `type=xudt_compatible` | 默认列表只包含这两种类型；指定类型时只包含 xUDT-compatible，不混入 sUDT、SSRI 或 Omiga | 专用目录类型边界失效 | P0 |
| `XUDT-FT-RPC-02` | - [x] 传入不同大小写的完整 `symbol`，以及未知非空 `type` 值请求 xUDT 列表 | Symbol 使用不区分大小写的精确匹配；待确认：未知非空 `type` 应返回参数错误还是按当前实现等同 `xudt_compatible` | Symbol 被错误做模糊匹配，或未知类型静默改变成员范围 | P1 |
| `XUDT-FT-RPC-03` | - [x] `tags` 含多个合法标签且未传 `union`，随后传入 `union` | 未传 `union` 时记录必须包含全部合法标签；传 `union` 时包含任一合法标签即可；每条记录返回其完整 `xudt_tags` | 标签交集与并集语义反转或响应丢失标签 | P1 |
| `XUDT-FT-RPC-04` | - [x] `tags` 混合合法和非法值，或全部为非法值 | 非法值先被丢弃；仍有合法值时只按合法集合过滤，全部无效时不增加标签过滤条件 | 未知标签排空整个目录或绕过预期合法过滤 | P2 |
| `XUDT-FT-RPC-05` | - [x] xUDT 与 fungible-token 列表分别使用默认和显式分页及 `created_time`、`transactions`、`addresses_count` 排序 | 页成员、总数和最多 100 条上限一致；公开排序字段映射正确，非法或缺失方向使用升序，并列按 full name、ID 升序 | 两个共享目录的分页排序规则漂移 | P1 |
| `XUDT-FT-RPC-06` | - [x] xUDT 或 fungible-token 列表的 `page`、`page_size` 为零、负数或非整数 | 返回对应分页参数错误，不执行无界目录查询 | 畸形分页造成错误切片或资源放大 | P1 |
| `XUDT-FT-RPC-07` | - [x] 以已发布 xUDT 或 xUDT-compatible 的 Type Hash 查询 xUDT 详情 | 返回该记录的 Type Hash、Type Script、类型、元数据、无损字符串计数和完整标签；Type Script 与同网络链上代币脚本一致 | 详情关联错误代币、脚本或标签 | P0 |
| `XUDT-FT-RPC-08` | - [x] xUDT 详情使用畸形、不存在或未发布的 Type Hash | 畸形值返回 Type Hash 参数错误；不存在和未发布返回 UDT not-found | 无效详情查询泄露未发布元数据或触发服务异常 | P1 |
| `XUDT-FT-RPC-09` | - [x] 统一 fungible-token 列表同时存在已发布 sUDT、xUDT、xUDT-compatible、SSRI 和其他 UDT 类型 | 只返回已发布的 sUDT、xUDT、xUDT-compatible、SSRI；未发布记录和 Omiga、NFT 等其他类型不进入列表 | 统一目录漏掉 SSRI 或混入非同质化、未发布资产 | P0 |
| `XUDT-FT-RPC-10` | - [x] fungible-token 列表使用标签交集或 `union` 并集过滤 | 只对拥有 xUDT 标签关联的成员应用与 xUDT 列表相同的合法标签规则，分页 meta 与过滤后的唯一成员一致 | 统一目录标签过滤与 xUDT 目录不一致或 join 产生重复 | P1 |
| `XUDT-FT-RPC-11` | - [ ] 以已发布统一目录成员及已发布但不属于四种列表类型的 Type Hash 查询 fungible-token 详情 | 四种列表类型返回对应详情；待确认：详情是否也应限制为四种 fungible 类型，还是按当前实现返回任意已发布 UDT | 列表与详情的类型边界不一致 | P1 |
| `XUDT-FT-RPC-12` | - [x] 已发布 SSRI UDT 能匹配部署合约时查询 fungible-token 详情 | 除通用 UDT 字段外返回 `ssri_contract_outpoint`，其交易哈希和 Cell 索引等于同网络链上部署 Cell；无匹配合约时该字段为空 | SSRI 合约引用错误 Cell 或跨网络 OutPoint | P1 |
| `XUDT-FT-RPC-13` | - [x] 分别通过 xUDT 与 fungible-token CSV 入口导出同一已发布代币并使用日期或高度范围 | 两个入口使用相同的已提交交易成员、包含边界、时间降序、最多 500 笔和逐地址 UDT 净变化；xUDT 文件名与普通 UDT 文件名按各自入口返回 | 共享导出逻辑在两个路由产生不同交易或金额 | P0 |
| `XUDT-FT-RPC-14` | - [x] 对已发布 xUDT 和已存在区块高度请求 CSV 快照，快照高度前后分别有生成和消费该 Type Script Cell 的交易 | 只累计在目标区块时间之前已生成且在该时间之后才消费或仍未消费的 Cells，按 CKB 地址求和、排除零余额并按余额降序输出；交易与 Cell 生灭由同网络 RPC/Indexer 证明 | 使用当前余额代替历史余额、包含已消费 Cell 或漏掉边界 Cell | P0 |
| `XUDT-FT-RPC-15` | - [x] 同一 Bitcoin 所有者映射到多个 CKB 地址，分别设置 `merge_with_owner=false` 和 true 请求快照 | false 时每个 CKB 地址独立；true 时有 Bitcoin 映射的地址合并到 Bitcoin owner，无映射地址保持 CKB 地址，合并后再次求和且表头改为 Owner | RGB++ 所有者余额被拆分、重复或与普通地址混算 | P1 |
| `XUDT-FT-RPC-16` | - [x] 快照分别请求默认 CSV 与 `format=json`，并包含 decimal 缺失、decimal 超过 20 或超大整数余额 | CSV 和 JSON 包含同一有序行；字段为 Symbol、区块高度、毫秒时间戳、UTC 日期、地址或 owner、Amount；金额使用任意精度十进制转换，decimal 缺失时追加 `(raw)` | 两种格式成员漂移或快照金额发生浮点精度损失 | P0 |
| `XUDT-FT-RPC-17` | - [x] 快照的区块不存在、UDT 不存在、未发布、不是 xUDT 类型或数据库缺少对应 Type Script | 前四种情况返回 UDT not-found；待确认：缺少 Type Script 时也应返回可分类错误，而不是访问空对象产生服务端异常 | 无效快照目标返回误导性空文件或 500 | P1 |
| `XUDT-FT-RPC-18` | - [x] RPC/Indexer、Bitcoin 所有者映射、SSRI 合约索引不可用或目标高度在取样期间重组 | 只将受影响的脚本、OutPoint、交易导出或快照结论标记为事实基准不可用；元数据和标签不冒充链上事实，另一网络独立执行 | 外部派生数据或重组导致错误的 API 不一致结论 | P1 |

## 本轮需要确认

- `XUDT-FT-RPC-02`：xUDT 列表的未知非空 `type` 当前等同于 `xudt_compatible`；需确认是否应改为参数错误。
- `XUDT-FT-RPC-11`：fungible-token 详情当前可返回任意已发布 UDT，而列表只允许四种类型；需确认详情类型边界。
- `XUDT-FT-RPC-17`：快照能找到 UDT 但找不到对应 Type Script 时，需要确认稳定错误类别。
