# V1 其余 Cell 输入输出内容 RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 交易及其引用输出为事实基准，核对输入 Cell 的 Type Script/Data 与输出 Cell 的 Lock Script/Type Script/Data；输入 Cell Lock Script 由独立评审负责
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按 Explorer 内部 Cell Input 或 Cell Output ID 返回对应链上 Cell 的 Lock Script、Type Script 或原始 Data。
- 输入：`GET /api/v1/cell_input_type_scripts/:id`、`GET /api/v1/cell_input_data/:id`、`GET /api/v1/cell_output_lock_scripts/:id`、`GET /api/v1/cell_output_type_scripts/:id`、`GET /api/v1/cell_output_data/:id`；事实基准使用同网络 RPC `get_transaction` 沿 input out-point 解析上一输出，或按当前交易的 output index 定位输出。
- 取样：主网和测试网独立选择已确认普通交易；输出 ID 可从交易展示结果取得，输入接口当前要求独立的内部 CellInput ID，其公开获取方式列为待确认。
- 成功结果：Script 的 `args`、`code_hash`、`hash_type` 与 RPC 原始值逐字节一致，Type Script Hash 按 CKB 规范计算，Data 与 RPC `outputs_data` 对应位置的完整十六进制字节串一致。
- 失败结果：RPC 传输失败、目标交易或上一输出缺失、比较期间发生重组时，只将该网络标记为事实基准不可用；另一个网络独立得出结论。
- 不负责：输入 Cell Lock Script、媒体类型、通用请求头、缓存、仅由 Explorer 元数据提供的 `verified_script_name`/`tags`，以及 pending/rejected Cell 的瞬时行为。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `CELL-CONTENT-RPC-01` | 在公开主网和测试网分别取得已确认非 Cellbase 交易的展示输入，并把展示项 `id` 用作 Input Type Script 与 Input Data 接口的路径 ID | 待确认：展示输入的 `id` 应能定位同一链上输入；若接口要求独立 CellInput ID，产品需提供调用方可获取且可与 consuming transaction/input index 绑定的公开方式 | 交易展示暴露上一输出 ID、接口却按 CellInput ID 查询，导致 404 或读取无关输入内容 | P0 |
| `CELL-CONTENT-RPC-03` | 在公开主网和测试网分别对上一输出含 Type Script 的已确认非 Cellbase 输入调用 Type Script 接口 | API 的 `args`、`code_hash`、`hash_type` 与 RPC Type Script 一致，`script_hash` 等于该 RPC Script 按 CKB 规范序列化后计算的哈希 | Type Script 错配、字段丢失或 Script Hash 计算错误 | P0 |
| `CELL-CONTENT-RPC-04` | 在公开主网和测试网分别对上一输出不含 Type Script 的已确认非 Cellbase 输入调用 Type Script 接口 | RPC 上一输出 `type` 为 `null` 时，API 返回 JSON:API `data: null`，不伪造空 Script | 无 Type Script 的 Cell 被错误赋予脚本或复用其他输入的脚本 | P1 |
| `CELL-CONTENT-RPC-05` | 在公开主网和测试网分别对上一输出含非空 Data 的已确认非 Cellbase 输入调用 Data 接口 | API `data.attributes.data` 与 RPC 上一交易 `outputs_data` 对应索引的完整 `0x` 十六进制字节串一致 | 输入 Data 被截断、取错 output index 或编码失真 | P0 |
| `CELL-CONTENT-RPC-06` | 在公开主网和测试网分别对上一输出 Data 为空的已确认非 Cellbase 输入调用 Data 接口 | RPC 对应 `outputs_data` 为 `0x` 时，API 也精确返回 `0x`，不返回 `null`、空字符串或 `0x0` | 空 Cell Data 的表示发生语义偏差 | P1 |
| `CELL-CONTENT-RPC-07` | 在公开主网和测试网分别以真实 Cellbase 输入的 `CellInput.id` 调用 Input Type Script 与 Input Data 接口 | 两个接口均返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1014`、`status` 为 `404`、`title` 为 `Cell Input Not Found`，`detail` 说明指定 ID 没有 Cell Input 记录 | Cellbase 虚拟输入被错误关联到真实上一输出、解引用空值异常或伪造 Script/Data | P1 |
| `CELL-CONTENT-RPC-08` | 在公开主网和测试网分别选择含至少两个不同 Lock Script 输出的已确认交易，从展示输出取得非零 `cell_index` 的输出 ID 后调用 Lock Script 接口 | API 的 `args`、`code_hash`、`hash_type` 与 RPC `outputs[cell_index].lock` 一致，且该内部 ID 绑定到选定输出位置 | 输出 ID 错绑到同交易其他 Cell，或 Lock Script 内容损坏 | P0 |
| `CELL-CONTENT-RPC-09` | 在公开主网和测试网分别选择 RPC 输出 Type Script 非空的已确认输出，以对应 Explorer 输出 ID 调用 Type Script 接口 | API 的 `args`、`code_hash`、`hash_type` 与 RPC Type Script 一致，`script_hash` 等于规范计算结果 | Type Script 错绑、字段损坏或 Script Hash 错误 | P0 |
| `CELL-CONTENT-RPC-10` | 在公开主网和测试网分别选择 RPC 输出 Type Script 为 `null` 的已确认输出，以对应 Explorer 输出 ID 调用 Type Script 接口 | API 返回 JSON:API `data: null`，不伪造空 Script 或复用其他输出的 Type Script | 普通 Cell 被错误关联到 Type Script | P1 |
| `CELL-CONTENT-RPC-11` | 在公开主网和测试网分别选择 RPC `outputs_data[cell_index]` 非空且解码后不超过 64000 字节的已确认输出，以对应 Explorer 输出 ID 调用 Data 接口 | API 返回的完整 Data 与 RPC 同索引十六进制字符串和字节内容一致 | Output Data 错位、被截断、损坏或回退为空值 | P0 |
| `CELL-CONTENT-RPC-12` | 在公开主网和测试网分别选择 RPC `outputs_data[cell_index]` 为 `0x` 的已确认输出调用 Data 接口 | API 明确返回 `data.attributes.data: "0x"`，而不是 `null`、缺失字段或其他输出的数据 | 空字节串在存储或序列化时被误当成缺失数据 | P1 |
| `CELL-CONTENT-RPC-13` | 当任一公开网络存在 RPC Output Data 解码后恰好为 64000 字节的已确认输出时调用 Data 接口 | API 成功返回与 RPC 一致的完整数据，不触发超限错误；找不到公开样本时记录为事实基准不可用 | 严格 `>` 边界被实现为 `>=`，使合法边界数据不可下载 | P2 |
| `CELL-CONTENT-RPC-14` | 当任一公开网络存在 RPC Output Data 解码后大于 64000 字节的已确认输出时调用 Data 接口 | API 返回 HTTP `400`；响应 JSON 根数组仅有一项，其 `code` 为 `1022`、`status` 为 `400`、`title` 为 `Output Data is Too Large`、`detail` 为 `You can download output data up to 64 KB`，且不返回截断或部分数据；找不到公开样本时记录为事实基准不可用 | 大数据绕过限制、返回截断内容或超限错误结构漂移 | P1 |
| `CELL-CONTENT-RPC-15` | 在公开主网和测试网分别选择 Explorer 标记为 dead、Data 不超过 64000 字节的已消费输出，按原始交易哈希和 output index 取得 RPC 交易后调用三个 Cell Output 接口 | Lock Script、可空 Type Script 和 Data 仍与原始 RPC 输出一致，不被消费交易内容改写 | Cell 被消费后原始 Script/Data 丢失，或接口错误地只支持 Live Cell | P1 |
| `CELL-CONTENT-RPC-16` | 在公开主网和测试网分别选择一笔至少含两个普通输入、且引用输出使用不同 Type Script 的已提交交易，分别以两个输入标识调用 Input Type Script 接口 | 两次响应分别等于各自 RPC input out-point 引用输出的 Type Script，且 `args`、`code_hash`、`hash_type`、`script_hash` 组合不同，不会固定返回首个输入或同一脚本 | 多输入交易按错误序号、关联键或缓存键返回其他输入的 Type Script | P1 |
| `CELL-CONTENT-RPC-17` | 在公开主网和测试网分别以字母或小数形式的非整数 `id` 请求 Input Type Script | 返回 HTTP `422`；响应 JSON 根数组仅有一项，其 `code` 为 `1013`、`status` 为 `422`、`title` 为 `URI parameters is invalid`，`detail` 说明 URI 参数应为整数 | 非整数 ID 进入数据库查询、触发服务端异常或返回模糊错误 | P1 |
| `CELL-CONTENT-RPC-18` | 在公开主网和测试网分别以确认不存在的整数 `id` 请求 Input Type Script | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1014`、`status` 为 `404`、`title` 为 `Cell Input Not Found`，`detail` 说明指定 ID 没有 Cell Input 记录 | 不存在资源被误报为成功、参数错误或服务端异常 | P1 |
| `CELL-CONTENT-RPC-19` | 在公开主网和测试网分别选择一笔至少含两个普通输入、且引用输出包含不同非空 Data 的已提交交易，分别以两个输入标识调用 Input Data 接口 | 两次 `data.attributes.data` 分别与各自 RPC input out-point 引用交易的 `outputs_data[output_index]` 完整字节串一致，且两次结果不同，不会固定返回首个输入或其他输出的数据 | 多输入交易按错误序号、关联键或缓存键返回其他输入的 Cell Data | P1 |
| `CELL-CONTENT-RPC-20` | 在公开主网和测试网分别以字母或小数形式的非整数 `id` 请求 Input Data | 返回 HTTP `422`；响应 JSON 根数组仅有一项，其 `code` 为 `1013`、`status` 为 `422`、`title` 为 `URI parameters is invalid`，`detail` 说明 URI 参数应为整数 | 非整数 ID 进入数据库查询、触发服务端异常或返回模糊错误 | P1 |
| `CELL-CONTENT-RPC-21` | 在公开主网和测试网分别以确认不存在的整数 `id` 请求 Input Data | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1014`、`status` 为 `404`、`title` 为 `Cell Input Not Found`，`detail` 说明指定 ID 没有 Cell Input 记录 | 不存在资源被误报为成功、参数错误或服务端异常 | P1 |
| `CELL-CONTENT-RPC-22` | 当任一公开网络存在引用输出 Data 解码后大于 64000 字节的已确认普通输入时调用 Input Data，并用同一 Cell Output ID 调用 Output Data | 待确认：Input Data 应像当前实现一样返回与 RPC 完全一致的完整字节串，还是与 Output Data 一致返回 HTTP `400` 和错误码 `1022`；两个入口的大小策略必须形成明确契约 | 同一链上 Data 因输入/输出入口不同产生未声明的下载限制差异，或大数据导致资源放大 | P1 |
| `CELL-CONTENT-RPC-23` | 在公开主网和测试网分别以字母或小数形式的非整数 `id` 请求 Output Lock Script | 返回 HTTP `422`；响应 JSON 根数组仅有一项，其 `code` 为 `1015`、`status` 为 `422`、`title` 为 `URI parameters is invalid`，`detail` 为 `URI parameters should be a integer` | 非整数 ID 进入数据库查询、触发服务端异常或错误复用 Cell Input 的错误码 | P1 |
| `CELL-CONTENT-RPC-24` | 在公开主网和测试网分别以确认不存在的整数 `id` 请求 Output Lock Script | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1016`、`status` 为 `404`、`title` 为 `Cell Output Not Found`，`detail` 为 `No cell output records found by given id` | 不存在的输出被误报成功，或错误返回 Cell Input、参数校验、服务端异常语义 | P1 |
| `CELL-CONTENT-RPC-25` | 在公开主网和测试网分别从已确认 Cellbase 交易展示输出取得一个 Cell Output ID，并调用 Output Lock Script | API 的 `args`、`code_hash`、`hash_type` 与 RPC Cellbase 交易同一 `cell_index` 的 `outputs[].lock` 逐字段一致，且展示输出 ID、`generated_tx_hash`、`cell_index` 共同定位同一 Cell | Cellbase 独立展示分支暴露错误输出 ID，或奖励输出被关联到其他 Cell 的 Lock Script | P1 |
| `CELL-CONTENT-RPC-26` | 在公开主网和测试网分别选择一笔至少含两个输出、其中一个 RPC Type Script 非空而另一个为 `null` 的已确认交易，以各自展示输出 ID 请求 Output Type Script | 非空输出返回与 RPC 一致的 `args`、`code_hash`、`hash_type` 和规范计算的 `script_hash`，无 Type Script 输出返回 JSON:API `data: null`；两次结果分别绑定各自 `cell_index` | 多输出交易按错误索引、关联键或缓存键复用同一个 Type Script，导致有无 Type Script 状态串扰 | P1 |
| `CELL-CONTENT-RPC-27` | 在公开主网和测试网分别以字母或小数形式的非整数 `id` 请求 Output Type Script | 返回 HTTP `422`；响应 JSON 根数组仅有一项，其 `code` 为 `1015`、`status` 为 `422`、`title` 为 `URI parameters is invalid`，`detail` 为 `URI parameters should be a integer` | 非整数 ID 进入数据库查询、触发服务端异常或错误复用 Cell Input 的错误码 | P1 |
| `CELL-CONTENT-RPC-28` | 在公开主网和测试网分别以确认不存在的整数 `id` 请求 Output Type Script | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1016`、`status` 为 `404`、`title` 为 `Cell Output Not Found`，`detail` 为 `No cell output records found by given id` | 不存在的输出被误报为无 Type Script 的成功 `data: null`，或返回错误的资源语义 | P1 |
| `CELL-CONTENT-RPC-29` | 在公开主网和测试网分别选择一笔至少含两个输出、且对应 RPC `outputs_data` 为两个不同且均不超过 64000 字节内容的已确认交易，以各自展示输出 ID 请求 Output Data | 两次 `data.attributes.data` 分别与 RPC 同一 `cell_index` 的 `outputs_data[]` 完整十六进制字节串一致，且两次结果不同，不会固定返回首个输出或相邻输出的数据 | 多输出交易按错误索引、关联键或缓存键返回其他 Cell 的 Data | P1 |
| `CELL-CONTENT-RPC-30` | 在公开主网和测试网分别以字母或小数形式的非整数 `id` 请求 Output Data | 返回 HTTP `422`；响应 JSON 根数组仅有一项，其 `code` 为 `1015`、`status` 为 `422`、`title` 为 `URI parameters is invalid`，`detail` 为 `URI parameters should be a integer` | 非整数 ID 进入数据库查询、触发服务端异常或错误复用 Cell Input 的错误码 | P1 |
| `CELL-CONTENT-RPC-31` | 在公开主网和测试网分别以确认不存在的整数 `id` 请求 Output Data | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1016`、`status` 为 `404`、`title` 为 `Cell Output Not Found`，`detail` 为 `No cell output records found by given id` | 不存在的输出被误报为空 Data 的成功响应，或返回错误的资源语义 | P1 |

## 本轮需要确认

- `CELL-CONTENT-RPC-01`：Input Type Script 与 Input Data 接口的公共调用方如何取得并验证内部 CellInput ID；当前交易展示项返回的是 previous Cell Output ID。
- 请确认新增 `CELL-CONTENT-RPC-16` 至 `CELL-CONTENT-RPC-18` 以及收窄后的 `CELL-CONTENT-RPC-07` 可作为 Input Type Script 的自动化依据。
- 请确认新增 `CELL-CONTENT-RPC-19` 至 `CELL-CONTENT-RPC-21` 可作为 Input Data 的多输入映射与错误响应自动化依据。
- `CELL-CONTENT-RPC-22`：Input Data 是否应沿用当前无 64000 字节上限的行为，还是与 Output Data 统一返回超限错误。
- 请确认新增 `CELL-CONTENT-RPC-23` 至 `CELL-CONTENT-RPC-25` 可作为 Output Lock Script 的错误响应与 Cellbase 输出关联评审依据；本轮按要求只补充测试点，不进入自动化门禁。
- 请确认新增 `CELL-CONTENT-RPC-26` 至 `CELL-CONTENT-RPC-28` 可作为 Output Type Script 的多输出隔离与真实错误响应评审依据；本轮按要求只补充测试点，不进入自动化门禁。
- 请确认新增 `CELL-CONTENT-RPC-29` 至 `CELL-CONTENT-RPC-31` 以及补全错误字段后的 `CELL-CONTENT-RPC-14` 可作为 Output Data 的多输出隔离、错误响应和超限契约评审依据；本轮按要求只补充测试点，不进入自动化门禁。
- `CELL-CONTENT-RPC-02` 已删除，其输入 Lock Script 行为由 `CELL-INPUT-LOCK-RPC-01` 至 `CELL-INPUT-LOCK-RPC-06` 独立覆盖。
- `CELL-CONTENT-RPC-13/14`：公开链找不到 64000 字节边界或超限样本时，自动化应记录事实基准不可用，还是把这两条保留为非持续执行用例。
- `verified_script_name`、Lock Script `tags` 由 Explorer 元数据产生，不纳入纯 CKB RPC 正确性结论。
