# V1 Omiga 铭文生命周期 RPC 正确性用例评审

评审范围：核对 `GET /api/v1/omiga_inscriptions`、详情和交易 CSV 的铭文成员、rebase 前后代选择、字段、排序与链上交易推导值
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：列出当前 Omiga 铭文，按 UDT Hash 或 Info Type Hash 返回当前或已关闭阶段详情，并导出 mint/rebase 交易。
- 输入：`GET /api/v1/omiga_inscriptions` 使用 `page`、`page_size`、`sort`；`GET /api/v1/omiga_inscriptions/:id` 使用 `id` 和可选 `status=closed`；`GET /api/v1/omiga_inscriptions/download_csv` 还接受日期或区块高度上下界。
- 成功结果：生命周期成员和状态字段与 Omiga Info/UDT 链上 Cells 一致，详情选择最新有效阶段，CSV 交易和解析出的 mint amount 可由同网络 RPC/Indexer 复算。
- 失败结果：无效分页、Type Hash 或不存在的详情返回对应错误；动态链或数据解析事实缺失时仅标记相关结论不可用。
- 不负责：普通 xUDT 目录、通用 UDT CSV、元数据验证、地址维度交易及通用 HTTP/下载头契约。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `OMIGA-RPC-01` | - [x] 数据包含独立 minting 铭文以及 closed 前代和引用其 `udt_hash` 的 rebase_start 后代时请求列表 | 返回独立 minting 和当前 rebase_start 记录；被后代引用且已 closed 的前代不再作为当前成员，其他 Omiga 记录不受影响 | rebase 前后代同时展示或误删无关铭文 | P0 |
| `OMIGA-RPC-02` | - [x] 无 Omiga 记录或过滤后的当前集合为空时请求列表 | 返回空数组和正确分页 meta，不把空集合当成错误 | 空目录返回服务异常或残留旧记录 | P2 |
| `OMIGA-RPC-03` | - [x] 使用默认或显式分页，并按 `created_time`、`transactions`、`mint_status` 升降序请求列表 | 页成员与过滤后的稳定集合一致；前两个字段映射区块时间和 24 小时交易数，`mint_status` 使用 Info 状态排序，合法方向生效 | 生命周期过滤后分页总数或专用状态排序错误 | P1 |
| `OMIGA-RPC-04` | - [ ] `page`、`page_size` 无效，或 `sort` 使用未知字段和畸形表达式 | 分页返回对应参数错误；待确认：未知排序字段应返回 4xx 还是回退安全默认字段，不得成为自由 SQL 排序表达式 | 无效分页或未白名单排序触发 500 与 SQL 风险 | P1 |
| `OMIGA-RPC-05` | - [x] 以当前 UDT Hash 或其 Omiga Info Type Hash 查询详情，且存在多个匹配生命周期阶段 | 两种哈希都定位同一生命周期，并返回 `block_timestamp` 最新的当前阶段 | Info Hash 与 UDT Hash 分支返回不同铭文，或选到旧阶段 | P0 |
| `OMIGA-RPC-06` | - [x] 以 closed 阶段的 Info Type Hash 并传 `status=closed` 查询详情 | 只返回 `mint_status=closed` 且 Info Type Hash 精确匹配的前代 UDT，不返回最新 rebase 后代 | 历史详情被当前阶段替换 | P1 |
| `OMIGA-RPC-07` | - [x] 查询有效铭文详情并与链上 Info Cell 和 UDT Cell 数据核对 | 返回通用 UDT 字段以及 `mint_status`、`mint_limit`、`expected_supply`、`inscription_info_id`、`info_type_hash`、`pre_udt_hash`、`is_repeated_symbol`；金额和计数以无损十进制字符串表示 | 铭文参数关联错误 Info Cell 或大整数精度丢失 | P0 |
| `OMIGA-RPC-08` | - [x] 详情 ID 格式错误、任一查询分支无匹配记录，或 `status=closed` 对应记录并非 closed | 格式错误返回 Type Hash 参数错误；其余返回 UDT not-found，不返回其他阶段的近似匹配 | 畸形哈希触发异常或历史状态查询串到错误阶段 | P1 |
| `OMIGA-RPC-09` | - [x] 对当前或 closed 铭文使用日期/区块范围导出 CSV | 按与详情相同的阶段选择规则确定 UDT，上下界包含边界，关联交易按区块时间降序最多 500 笔；哈希、高度、毫秒时间戳和 UTC 日期与同网络 RPC 一致 | 导出阶段、范围、顺序或链上交易身份错误 | P0 |
| `OMIGA-RPC-10` | - [x] CSV 交易分别只有 Omiga 输出、同时有 Omiga 输入输出或没有可识别流转，并含大整数 mint limit | Method 分别为 `mint`、`rebase_mint`、`unknown`；Amount 从首个 Omiga 输出数据解析为原始 mint limit，保持任意精度整数 | 铭文动作分类反转、解析错误 Cell 或大数精度损失 | P0 |
| `OMIGA-RPC-11` | - [ ] CSV 的 ID 不存在、阶段不匹配，或匹配交易没有 Omiga 输出数据 | 待确认：应返回 UDT not-found 或可分类的数据错误且不生成部分 CSV；不得因空 UDT 或空输出访问产生服务端异常 | 缺失铭文或畸形链上数据导致 500 和半成品文件 | P1 |
| `OMIGA-RPC-12` | - [x] RPC/Indexer 缺少目标交易、Info Cell 数据无法取得或取样高度发生重组 | 只将依赖链上成员、状态或 CSV amount 的结论标记为事实基准不可用；数据库展示元数据单独报告，另一网络独立执行 | 外部事实缺失被误判为 Omiga API 错误 | P1 |

## 本轮需要确认

- `OMIGA-RPC-04`：Omiga `sort` 对未知字段当前直接传入排序表达式；需确认统一的安全错误或回退行为。
- `OMIGA-RPC-11`：CSV 目标或 Omiga 输出缺失时需要确认稳定错误类别。
