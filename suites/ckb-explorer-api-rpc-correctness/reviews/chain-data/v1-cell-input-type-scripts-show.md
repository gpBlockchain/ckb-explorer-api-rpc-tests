# V1 Cell Input Type Script RPC 正确性 用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 输入引用输出为事实基准，核对 `GET /api/v1/cell_input_type_scripts/:id` 的可空 Type Script、输入关联、Cellbase 与接口特有错误。
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 Explorer 内部 `CellInput.id` 返回普通输入所引用输出的可空 Type Script。
- 输入：`GET /api/v1/cell_input_type_scripts/:id`；事实基准使用同网络 RPC `get_transaction` 沿 `inputs[].previous_output` 定位上一输出。
- 成功结果：存在 Type Script 时，`args`、`code_hash`、`hash_type` 与 RPC 一致，`script_hash` 等于 CKB 规范计算值；不存在时返回 `data: null`。
- 失败结果：字母形式非整数 ID 返回 `422/1013`，不存在或 Cellbase 输入返回 `404/1014`。
- RPC 传输失败、目标交易或引用输出缺失、比较期间发生重组时，只将该网络标记为事实基准不可用；另一个网络独立得出结论。
- 不负责：通用媒体类型与请求头、`verified_script_name` 元数据准确性，以及 pending/rejected Cell 的瞬时行为。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `CELL-CONTENT-RPC-01` | 在公开主网和测试网分别取得已确认非 Cellbase 交易的展示输入，并把展示项 `id` 用作 Input Type Script 接口的路径 ID | 待确认：展示输入的 `id` 应能定位同一链上输入；若接口要求独立 `CellInput.id`，产品需提供调用方可获取且可与 consuming transaction/input index 绑定的公开方式 | 交易展示暴露上一输出 ID、接口却按 CellInput ID 查询，导致 404 或读取无关输入的 Type Script | P0 |
| `CELL-CONTENT-RPC-03` | 在公开主网和测试网分别对上一输出含 Type Script 的已确认非 Cellbase 输入调用 Type Script 接口 | API 的 `args`、`code_hash`、`hash_type` 与 RPC Type Script 一致，`script_hash` 等于该 RPC Script 按 CKB 规范序列化后计算的哈希 | Type Script 错配、字段丢失或 Script Hash 计算错误 | P0 |
| `CELL-CONTENT-RPC-04` | 在公开主网和测试网分别对上一输出不含 Type Script 的已确认非 Cellbase 输入调用 Type Script 接口 | RPC 上一输出 `type` 为 `null` 时，API 返回 JSON:API `data: null`，不伪造空 Script | 无 Type Script 的 Cell 被错误赋予脚本或复用其他输入的脚本 | P1 |
| `CELL-CONTENT-RPC-07` | 在公开主网和测试网分别以真实 Cellbase 输入的 `CellInput.id` 调用 Input Type Script | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1014`、`status` 为 `404`、`title` 为 `Cell Input Not Found`，`detail` 为 `No cell input records found by given id` | Cellbase 虚拟输入被错误关联到真实上一输出、解引用空值异常或伪造 Type Script | P1 |
| `CELL-CONTENT-RPC-16` | 在公开主网和测试网分别选择一笔至少含两个普通输入、且引用输出使用不同 Type Script 的已提交交易，分别以两个输入标识调用 Input Type Script 接口 | 两次响应分别等于各自 RPC input out-point 引用输出的 Type Script，且 `args`、`code_hash`、`hash_type`、`script_hash` 组合不同，不会固定返回首个输入或同一脚本 | 多输入交易按错误序号、关联键或缓存键返回其他输入的 Type Script | P1 |
| `CELL-CONTENT-RPC-17` | 在公开主网和测试网分别以不含点号的字母形式非整数 `id` 请求 Input Type Script | 返回 HTTP `422`；响应 JSON 根数组仅有一项，其 `code` 为 `1013`、`status` 为 `422`、`title` 为 `URI parameters is invalid`，`detail` 为 `URI parameters should be a integer` | 字母形式非整数 ID 进入数据库查询、触发服务端异常或返回模糊错误 | P1 |
| `CELL-CONTENT-RPC-18` | 在公开主网和测试网分别以确认不存在的整数 `id` 请求 Input Type Script | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1014`、`status` 为 `404`、`title` 为 `Cell Input Not Found`，`detail` 说明指定 ID 没有 Cell Input 记录 | 不存在资源被误报为成功、参数错误或服务端异常 | P1 |
| `CELL-CONTENT-RPC-32` | 在公开主网和测试网分别将已确认普通输入的整数 `CellInput.id` 追加 `.5` format 后缀后请求 Input Type Script | Rails 按点号前的整数定位同一输入；返回 HTTP `200`，响应与不带后缀请求及对应 RPC 引用输出的 Type Script 一致；若该引用输出没有 Type Script，则两次请求均返回 `data: null` | 把允许的 format 后缀误判为非法 ID，或带后缀查询到其他输入并返回错误 Type Script | P1 |

## 本轮需要确认

- `CELL-CONTENT-RPC-01`：公开调用方从哪个响应取得可与 consuming transaction/input index 绑定的内部 `CellInput.id`。
