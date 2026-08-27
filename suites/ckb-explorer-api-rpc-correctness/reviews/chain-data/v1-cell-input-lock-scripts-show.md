# V1 Cell Input Lock Script RPC 正确性 用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 输入引用输出为事实基准，核对 `GET /api/v1/cell_input_lock_scripts/:id` 的 Lock Script、输入关联、Cellbase 与接口特有错误。
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 Explorer 内部 `CellInput.id` 返回普通输入所引用输出的 Lock Script。
- 输入：`GET /api/v1/cell_input_lock_scripts/:id`；事实基准使用同网络 RPC `get_transaction` 沿 `inputs[].previous_output` 定位上一输出。
- 成功结果：`args`、`code_hash`、`hash_type` 与 RPC 引用输出的 `lock` 逐字节一致。
- 失败结果：字母形式非整数 ID 返回 `422/1013`，不存在或 Cellbase 输入返回 `404/1014`。
- RPC 传输失败、目标交易或引用输出缺失、比较期间发生重组时，只将该网络标记为事实基准不可用；另一个网络独立得出结论。
- 不负责：通用媒体类型与请求头、`verified_script_name`/`tags` 元数据准确性，以及 pending/rejected Cell 的瞬时行为。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `CELL-INPUT-LOCK-RPC-01` | - [x] 在公开主网和测试网分别从一笔已提交普通交易选择一个可定位到 RPC 输入序号的输入，用调用方可获取的公开标识请求 Lock Script | 待确认：`:id` 应使用由哪个公开响应提供的 `CellInput.id`，或接口是否应接受交易详情 `display_inputs[].id` 所表示的引用 `CellOutput.id`；确定后，该标识能唯一定位这个 RPC 输入且请求成功 | 公开调用方拿不到可用标识、将输出 ID 当成输入 ID，或自动化在不知道链上对应关系时比较了无关脚本 | P0 |
| `CELL-INPUT-LOCK-RPC-02` | - [x] 在公开主网和测试网分别以已确认映射的普通输入标识查询 Lock Script，并用 RPC `previous_output.tx_hash` 和输出索引取得被引用输出 | API `data.attributes.code_hash`、`hash_type`、`args` 与 RPC 引用输出的 `lock` 同名字段完全相等，包括 `0x` 前缀、前导零和全部 args 字节 | Lock Script 关联错误，或 code hash、hash type、args 被截断、改写、进制转换与序列化失真 | P0 |
| `CELL-INPUT-LOCK-RPC-03` | - [x] 在公开主网和测试网分别选择一笔至少含两个普通输入、且这两个引用输出使用不同 Lock Script 的已提交交易，分别以两个输入标识查询 | 两次响应分别等于各自 RPC 输入引用输出的 `lock`，且两组 `code_hash`、`hash_type`、`args` 组合不同，不会固定返回首个输入或同一 Lock Script | 多输入交易按错误序号、关联键或缓存键返回其他输入的 Lock Script | P1 |
| `CELL-INPUT-LOCK-RPC-04` | - [x] 在公开主网和测试网分别以不含点号的字母形式非整数 `id` 请求 Lock Script | 返回 HTTP `422`；响应 JSON 根数组仅有一项，其 `code` 为 `1013`、`status` 为 `422`、`title` 为 `URI parameters is invalid`，`detail` 说明 URI 参数应为整数 | 字母形式非整数 ID 进入数据库查询、触发服务端异常或返回模糊错误 | P1 |
| `CELL-INPUT-LOCK-RPC-05` | - [x] 在公开主网和测试网分别以确认不存在的整数 `id` 请求 Lock Script | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1014`、`status` 为 `404`、`title` 为 `Cell Input Not Found`，`detail` 说明指定 ID 没有 Cell Input 记录 | 不存在资源被误报为成功、参数错误或服务端异常 | P1 |
| `CELL-INPUT-LOCK-RPC-06` | - [x] 在公开主网和测试网分别以一个真实 Cellbase 输入的 `CellInput.id` 请求 Lock Script | 因 Cellbase 输入没有 `previous_cell_output`，返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1014`、`status` 为 `404`、`title` 为 `Cell Input Not Found`，`detail` 说明指定 ID 没有 Cell Input 记录 | Cellbase 被按普通输入解析、解引用空值异常或伪造 Lock Script | P1 |
| `CELL-INPUT-LOCK-RPC-07` | - [x] 在公开主网和测试网分别将已确认普通输入的整数 `CellInput.id` 追加 `.5` format 后缀后请求 Lock Script | Rails 将带点路径解析为原整数 `id` 加 format 后缀；返回 HTTP `200`，且 `code_hash`、`hash_type`、`args` 与不带后缀请求及对应 RPC 引用输出完全相等 | 把允许的 format 后缀误判为非法 ID，或带后缀查询到不同输入和错误 Lock Script | P1 |

## 本轮需要确认

- `CELL-INPUT-LOCK-RPC-01`：公开调用方从哪个响应取得可与 consuming transaction/input index 绑定的内部 `CellInput.id`。
