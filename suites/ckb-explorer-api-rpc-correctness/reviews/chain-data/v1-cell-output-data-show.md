# V1 Cell Output Data RPC 正确性 用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 交易输出为事实基准，核对 `GET /api/v1/cell_output_data/:id` 的原始 Data、输出索引、已消费输出、64000 字节边界与接口特有错误。
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 Explorer `CellOutput.id` 返回指定输出的原始 Cell Data，并拒绝大于 64000 字节的下载。
- 输入：`GET /api/v1/cell_output_data/:id`；输出 ID 从交易展示取得，事实基准使用同网络 RPC `get_transaction` 按 `cell_index` 定位 `outputs_data[]`。
- 成功结果：不超过 64000 字节时，`data.attributes.data` 与 RPC 同索引完整十六进制字节串一致，空 Data 精确表示为 `0x`，输出被消费后仍可查询。
- 失败结果：字母形式非整数 ID 返回 `422/1015`，不存在的整数 ID 返回 `404/1016`，超过 64000 字节返回 `400/1022`。
- RPC 传输失败、目标交易或引用输出缺失、比较期间发生重组时，只将该网络标记为事实基准不可用；另一个网络独立得出结论。
- 不负责：通用媒体类型与请求头，以及 pending/rejected Cell 的瞬时行为。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `CELL-CONTENT-RPC-11` | - [x] 在公开主网和测试网分别选择 RPC `outputs_data[cell_index]` 非空且解码后不超过 64000 字节的已确认输出，以对应 Explorer 输出 ID 调用 Data 接口 | API 返回的完整 Data 与 RPC 同索引十六进制字符串和字节内容一致 | Output Data 错位、被截断、损坏或回退为空值 | P0 |
| `CELL-CONTENT-RPC-12` | - [x] 在公开主网和测试网分别选择 RPC `outputs_data[cell_index]` 为 `0x` 的已确认输出调用 Data 接口 | API 明确返回 `data.attributes.data: "0x"`，而不是 `null`、缺失字段或其他输出的数据 | 空字节串在存储或序列化时被误当成缺失数据 | P1 |
| `CELL-CONTENT-RPC-13` | - [x] 当任一公开网络存在 RPC Output Data 解码后恰好为 64000 字节的已确认输出时调用 Data 接口 | API 成功返回与 RPC 一致的完整数据，不触发超限错误；找不到公开样本时记录为事实基准不可用 | 严格 `>` 边界被实现为 `>=`，使合法边界数据不可下载 | P2 |
| `CELL-CONTENT-RPC-14` | - [x] 当任一公开网络存在 RPC Output Data 解码后大于 64000 字节的已确认输出时调用 Data 接口 | API 返回 HTTP `400`；响应 JSON 根数组仅有一项，其 `code` 为 `1022`、`status` 为 `400`、`title` 为 `Output Data is Too Large`、`detail` 为 `You can download output data up to 64 KB`，且不返回截断或部分数据；找不到公开样本时记录为事实基准不可用 | 大数据绕过限制、返回截断内容或超限错误结构漂移 | P1 |
| `CELL-CONTENT-RPC-29` | - [x] 在公开主网和测试网分别选择一笔至少含两个输出、且对应 RPC `outputs_data` 为两个不同且均不超过 64000 字节内容的已确认交易，以各自展示输出 ID 请求 Output Data | 两次 `data.attributes.data` 分别与 RPC 同一 `cell_index` 的 `outputs_data[]` 完整十六进制字节串一致，且两次结果不同，不会固定返回首个输出或相邻输出的数据 | 多输出交易按错误索引、关联键或缓存键返回其他 Cell 的 Data | P1 |
| `CELL-CONTENT-RPC-37` | - [x] 在公开主网和测试网分别选择 Explorer 标记为 dead、Data 不超过 64000 字节的已消费输出，按原始交易哈希和 output index 取得 RPC 交易后调用 Output Data | `data.attributes.data` 仍与原始 RPC 输出同索引的完整 `outputs_data` 一致，不被消费交易内容改写 | Cell 被消费后原始 Data 丢失，或接口错误地只支持 Live Cell | P1 |
| `CELL-CONTENT-RPC-30` | - [x] 在公开主网和测试网分别以不含点号的字母形式非整数 `id` 请求 Output Data | 返回 HTTP `422`；响应 JSON 根数组仅有一项，其 `code` 为 `1015`、`status` 为 `422`、`title` 为 `URI parameters is invalid`，`detail` 为 `URI parameters should be a integer` | 字母形式非整数 ID 进入数据库查询、触发服务端异常或错误复用 Cell Input 的错误码 | P1 |
| `CELL-CONTENT-RPC-31` | - [x] 在公开主网和测试网分别以确认不存在的整数 `id` 请求 Output Data | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1016`、`status` 为 `404`、`title` 为 `Cell Output Not Found`，`detail` 为 `No cell output records found by given id` | 不存在的输出被误报为空 Data 的成功响应，或返回错误的资源语义 | P1 |
| `CELL-CONTENT-RPC-40` | - [x] 在公开主网和测试网分别将 Data 不超过 64000 字节的已确认输出整数 `CellOutput.id` 追加 `.5` format 后缀后请求 Output Data | Rails 按点号前的整数定位同一输出；返回 HTTP `200`，`data.attributes.data` 与不带后缀请求及 RPC 同索引 `outputs_data` 的完整十六进制字节串一致 | 把允许的 format 后缀误判为非法 ID，或带后缀查询到其他输出并返回错误 Cell Data | P1 |

## 本轮需要确认

- 无。
