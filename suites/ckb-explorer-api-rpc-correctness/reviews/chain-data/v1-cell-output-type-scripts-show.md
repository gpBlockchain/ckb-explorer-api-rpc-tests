# V1 Cell Output Type Script RPC 正确性 用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 交易输出为事实基准，核对 `GET /api/v1/cell_output_type_scripts/:id` 的可空 Type Script、输出索引、已消费输出与接口特有错误。
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 Explorer `CellOutput.id` 返回指定输出的可空 Type Script。
- 输入：`GET /api/v1/cell_output_type_scripts/:id`；输出 ID 从交易展示取得，事实基准使用同网络 RPC `get_transaction` 按 `cell_index` 定位 `outputs[]`。
- 成功结果：存在 Type Script 时，`args`、`code_hash`、`hash_type` 与 RPC 一致，`script_hash` 等于 CKB 规范计算值；不存在时返回 `data: null`，输出被消费后仍保持原值。
- 失败结果：字母形式非整数 ID 返回 `422/1015`，不存在的整数 ID 返回 `404/1016`。
- RPC 传输失败、目标交易或引用输出缺失、比较期间发生重组时，只将该网络标记为事实基准不可用；另一个网络独立得出结论。
- 不负责：通用媒体类型与请求头、`verified_script_name` 元数据准确性，以及 pending/rejected Cell 的瞬时行为。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `CELL-CONTENT-RPC-09` | 在公开主网和测试网分别选择 RPC 输出 Type Script 非空的已确认输出，以对应 Explorer 输出 ID 调用 Type Script 接口 | API 的 `args`、`code_hash`、`hash_type` 与 RPC Type Script 一致，`script_hash` 等于规范计算结果 | Type Script 错绑、字段损坏或 Script Hash 错误 | P0 |
| `CELL-CONTENT-RPC-10` | 在公开主网和测试网分别选择 RPC 输出 Type Script 为 `null` 的已确认输出，以对应 Explorer 输出 ID 调用 Type Script 接口 | API 返回 JSON:API `data: null`，不伪造空 Script 或复用其他输出的 Type Script | 普通 Cell 被错误关联到 Type Script | P1 |
| `CELL-CONTENT-RPC-26` | 在公开主网和测试网分别选择一笔至少含两个输出、其中一个 RPC Type Script 非空而另一个为 `null` 的已确认交易，以各自展示输出 ID 请求 Output Type Script | 非空输出返回与 RPC 一致的 `args`、`code_hash`、`hash_type` 和规范计算的 `script_hash`，无 Type Script 输出返回 JSON:API `data: null`；两次结果分别绑定各自 `cell_index` | 多输出交易按错误索引、关联键或缓存键复用同一个 Type Script，导致有无 Type Script 状态串扰 | P1 |
| `CELL-CONTENT-RPC-36` | 在公开主网和测试网分别选择 Explorer 标记为 dead 的已消费输出，按原始交易哈希和 output index 取得 RPC 交易后调用 Output Type Script | RPC 原始输出存在 Type Script 时，API 的 `args`、`code_hash`、`hash_type`、`script_hash` 与其一致；不存在时返回 `data: null`，且不被消费交易内容改写 | Cell 被消费后原始 Type Script 丢失、空值改变，或接口错误地只支持 Live Cell | P1 |
| `CELL-CONTENT-RPC-27` | 在公开主网和测试网分别以不含点号的字母形式非整数 `id` 请求 Output Type Script | 返回 HTTP `422`；响应 JSON 根数组仅有一项，其 `code` 为 `1015`、`status` 为 `422`、`title` 为 `URI parameters is invalid`，`detail` 为 `URI parameters should be a integer` | 字母形式非整数 ID 进入数据库查询、触发服务端异常或错误复用 Cell Input 的错误码 | P1 |
| `CELL-CONTENT-RPC-28` | 在公开主网和测试网分别以确认不存在的整数 `id` 请求 Output Type Script | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1016`、`status` 为 `404`、`title` 为 `Cell Output Not Found`，`detail` 为 `No cell output records found by given id` | 不存在的输出被误报为无 Type Script 的成功 `data: null`，或返回错误的资源语义 | P1 |
| `CELL-CONTENT-RPC-39` | 在公开主网和测试网分别将已确认输出的整数 `CellOutput.id` 追加 `.5` format 后缀后请求 Output Type Script | Rails 按点号前的整数定位同一输出；存在 Type Script 时返回 HTTP `200` 且响应与不带后缀请求及 RPC Type Script 一致，不存在时两次请求均返回 `data: null` | 把允许的 format 后缀误判为非法 ID，或带后缀查询到其他输出并返回错误 Type Script | P1 |

## 本轮需要确认

- 无。
