# V1 Cell Input Data RPC 正确性 用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 输入引用输出为事实基准，核对 `GET /api/v1/cell_input_data/:id` 的原始 Data、输入关联、Cellbase、大小策略与接口特有错误。
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 Explorer 内部 `CellInput.id` 返回普通输入所引用输出的原始 Cell Data。
- 输入：`GET /api/v1/cell_input_data/:id`；事实基准使用同网络 RPC `get_transaction` 沿 `inputs[].previous_output` 定位上一输出及对应 `outputs_data`。
- 成功结果：`data.attributes.data` 与 RPC 引用输出同索引的完整 `0x` 十六进制字节串一致，空 Data 精确表示为 `0x`。
- 失败结果：字母形式非整数 ID 返回 `422/1013`，不存在或 Cellbase 输入返回 `404/1014`。
- RPC 传输失败、目标交易或引用输出缺失、比较期间发生重组时，只将该网络标记为事实基准不可用；另一个网络独立得出结论。
- 不负责：通用媒体类型与请求头，以及 pending/rejected Cell 的瞬时行为。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `CELL-CONTENT-RPC-34` | - [x] 在公开主网和测试网分别取得已确认非 Cellbase 交易的展示输入，并把展示项 `id` 用作 Input Data 接口的路径 ID | 待确认：展示输入的 `id` 应能定位同一链上输入；若接口要求独立 `CellInput.id`，产品需提供调用方可获取且可与 consuming transaction/input index 绑定的公开方式 | 交易展示暴露上一输出 ID、接口却按 CellInput ID 查询，导致 404 或读取无关输入的 Cell Data | P0 |
| `CELL-CONTENT-RPC-05` | - [x] 在公开主网和测试网分别对上一输出含非空 Data 的已确认非 Cellbase 输入调用 Data 接口 | API `data.attributes.data` 与 RPC 上一交易 `outputs_data` 对应索引的完整 `0x` 十六进制字节串一致 | 输入 Data 被截断、取错 output index 或编码失真 | P0 |
| `CELL-CONTENT-RPC-06` | - [x] 在公开主网和测试网分别对上一输出 Data 为空的已确认非 Cellbase 输入调用 Data 接口 | RPC 对应 `outputs_data` 为 `0x` 时，API 也精确返回 `0x`，不返回 `null`、空字符串或 `0x0` | 空 Cell Data 的表示发生语义偏差 | P1 |
| `CELL-CONTENT-RPC-35` | - [x] 在公开主网和测试网分别以真实 Cellbase 输入的 `CellInput.id` 调用 Input Data | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1014`、`status` 为 `404`、`title` 为 `Cell Input Not Found`，`detail` 为 `No cell input records found by given id` | Cellbase 虚拟输入被错误关联到真实上一输出、解引用空值异常或伪造 Cell Data | P1 |
| `CELL-CONTENT-RPC-19` | - [x] 在公开主网和测试网分别选择一笔至少含两个普通输入、且引用输出包含不同非空 Data 的已提交交易，分别以两个输入标识调用 Input Data 接口 | 两次 `data.attributes.data` 分别与各自 RPC input out-point 引用交易的 `outputs_data[output_index]` 完整字节串一致，且两次结果不同，不会固定返回首个输入或其他输出的数据 | 多输入交易按错误序号、关联键或缓存键返回其他输入的 Cell Data | P1 |
| `CELL-CONTENT-RPC-20` | - [x] 在公开主网和测试网分别以不含点号的字母形式非整数 `id` 请求 Input Data | 返回 HTTP `422`；响应 JSON 根数组仅有一项，其 `code` 为 `1013`、`status` 为 `422`、`title` 为 `URI parameters is invalid`，`detail` 为 `URI parameters should be a integer` | 字母形式非整数 ID 进入数据库查询、触发服务端异常或返回模糊错误 | P1 |
| `CELL-CONTENT-RPC-21` | - [x] 在公开主网和测试网分别以确认不存在的整数 `id` 请求 Input Data | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1014`、`status` 为 `404`、`title` 为 `Cell Input Not Found`，`detail` 说明指定 ID 没有 Cell Input 记录 | 不存在资源被误报为成功、参数错误或服务端异常 | P1 |
| `CELL-CONTENT-RPC-22` | - [x] 当任一公开网络存在引用输出 Data 解码后大于 64000 字节的已确认普通输入时调用 Input Data，并用同一 Cell Output ID 调用 Output Data | 待确认：Input Data 应像当前实现一样返回与 RPC 完全一致的完整字节串，还是与 Output Data 一致返回 HTTP `400` 和错误码 `1022`；两个入口的大小策略必须形成明确契约 | 同一链上 Data 因输入/输出入口不同产生未声明的下载限制差异，或大数据导致资源放大 | P1 |
| `CELL-CONTENT-RPC-33` | - [x] 在公开主网和测试网分别将已确认普通输入的整数 `CellInput.id` 追加 `.5` format 后缀后请求 Input Data | Rails 按点号前的整数定位同一输入；返回 HTTP `200`，`data.attributes.data` 与不带后缀请求及 RPC input out-point 引用交易的 `outputs_data[output_index]` 完整十六进制字节串一致 | 把允许的 format 后缀误判为非法 ID，或带后缀查询到其他输入并返回错误 Cell Data | P1 |

## 本轮需要确认

- `CELL-CONTENT-RPC-34`：公开调用方从哪个响应取得可与 consuming transaction/input index 绑定的内部 `CellInput.id`。
- `CELL-CONTENT-RPC-22`：Input Data 对大于 64000 字节的引用输出沿用当前完整返回行为，还是与 Output Data 统一返回 `400/1022`。
