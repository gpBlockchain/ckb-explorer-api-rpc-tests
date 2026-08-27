# V1 Cell Output Lock Script RPC 正确性 用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 交易输出为事实基准，核对 `GET /api/v1/cell_output_lock_scripts/:id` 的 Lock Script、输出索引、已消费输出、Cellbase 输出与接口特有错误。
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 Explorer `CellOutput.id` 返回指定输出的 Lock Script。
- 输入：`GET /api/v1/cell_output_lock_scripts/:id`；输出 ID 从交易展示取得，事实基准使用同网络 RPC `get_transaction` 按 `cell_index` 定位 `outputs[]`。
- 成功结果：`args`、`code_hash`、`hash_type` 与 RPC 同索引输出的 `lock` 逐字节一致，输出被消费后仍可查询。
- 失败结果：字母形式非整数 ID 返回 `422/1015`，不存在的整数 ID 返回 `404/1016`。
- RPC 传输失败、目标交易或引用输出缺失、比较期间发生重组时，只将该网络标记为事实基准不可用；另一个网络独立得出结论。
- 不负责：通用媒体类型与请求头、`verified_script_name`/`tags` 元数据准确性，以及 pending/rejected Cell 的瞬时行为。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `CELL-CONTENT-RPC-08` | - [x] 在公开主网和测试网分别选择含至少两个不同 Lock Script 输出的已确认交易，从展示输出取得非零 `cell_index` 的输出 ID 后调用 Lock Script 接口 | API 的 `args`、`code_hash`、`hash_type` 与 RPC `outputs[cell_index].lock` 一致，且该内部 ID 绑定到选定输出位置 | 输出 ID 错绑到同交易其他 Cell，或 Lock Script 内容损坏 | P0 |
| `CELL-CONTENT-RPC-15` | - [x] 在公开主网和测试网分别选择 Explorer 标记为 dead 的已消费输出，按原始交易哈希和 output index 取得 RPC 交易后调用 Output Lock Script | API 的 `args`、`code_hash`、`hash_type` 仍与原始 RPC 输出的 Lock Script 一致，不被消费交易内容改写 | Cell 被消费后原始 Lock Script 丢失，或接口错误地只支持 Live Cell | P1 |
| `CELL-CONTENT-RPC-23` | - [x] 在公开主网和测试网分别以不含点号的字母形式非整数 `id` 请求 Output Lock Script | 返回 HTTP `422`；响应 JSON 根数组仅有一项，其 `code` 为 `1015`、`status` 为 `422`、`title` 为 `URI parameters is invalid`，`detail` 为 `URI parameters should be a integer` | 字母形式非整数 ID 进入数据库查询、触发服务端异常或错误复用 Cell Input 的错误码 | P1 |
| `CELL-CONTENT-RPC-24` | - [x] 在公开主网和测试网分别以确认不存在的整数 `id` 请求 Output Lock Script | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1016`、`status` 为 `404`、`title` 为 `Cell Output Not Found`，`detail` 为 `No cell output records found by given id` | 不存在的输出被误报成功，或错误返回 Cell Input、参数校验、服务端异常语义 | P1 |
| `CELL-CONTENT-RPC-25` | - [x] 在公开主网和测试网分别从已确认 Cellbase 交易展示输出取得一个 Cell Output ID，并调用 Output Lock Script | API 的 `args`、`code_hash`、`hash_type` 与 RPC Cellbase 交易同一 `cell_index` 的 `outputs[].lock` 逐字段一致，且展示输出 ID、`generated_tx_hash`、`cell_index` 共同定位同一 Cell | Cellbase 独立展示分支暴露错误输出 ID，或奖励输出被关联到其他 Cell 的 Lock Script | P1 |
| `CELL-CONTENT-RPC-38` | - [x] 在公开主网和测试网分别将已确认输出的整数 `CellOutput.id` 追加 `.5` format 后缀后请求 Output Lock Script | Rails 按点号前的整数定位同一输出；返回 HTTP `200`，`args`、`code_hash`、`hash_type` 与不带后缀请求及对应 RPC 输出的 Lock Script 一致 | 把允许的 format 后缀误判为非法 ID，或带后缀查询到其他输出并返回错误 Lock Script | P1 |

## 本轮需要确认

- 无。
