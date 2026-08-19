# V1 输入 Cell Type Script RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 为事实基准，核对 `GET /api/v1/cell_input_type_scripts/:id` 返回的脚本是该普通输入引用的上一笔交易输出的 Type Script，以及引用输出无 Type Script 时的空数据响应，并评审该端点的参数与资源错误响应
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：按输入 Cell 标识返回其引用输出的 Type Script；引用输出没有 Type Script 时返回空数据；对非整数 ID、资源不存在与 Cellbase 无引用输出返回对应错误；链上字段正确性要求主网、测试网各自产生独立结论。
- 公开主网：Explorer `https://mainnet-api.explorer.nervos.org/api`；CKB RPC `https://mainnet.ckbapp.dev/`。
- 公开测试网：Explorer `https://testnet-api.explorer.nervos.org/api`；CKB RPC `https://testnet.ckbapp.dev/`。
- 输入：每个网络分别以已提交普通交易的输入标识调用 Explorer `GET /api/v1/cell_input_type_scripts/:id`；RPC 使用 `get_transaction` 取得消费交易、对应输入的 `previous_output` 及被引用交易输出。
- 标识语义：当前源码按 `CellInput.id` 查询，而交易详情 `display_inputs[].id` 序列化的是被引用 `CellOutput.id`；实测用 `display_inputs[].id` 请求本接口会命中无关的 `CellInput` 记录（引用输出带 Type Script 的输入返回了空数据），即公开响应不提供本接口要求的标识。自动化前需确认调用方可获取的公开 `:id` 及其到 RPC 交易输入的稳定映射。
- 取样：每个网络先用高度 0 的哈希校验 Explorer/RPC 链身份，并确认 Explorer tip 不高于 RPC 且最多落后 5 个区块；普通输入样本需能稳定定位到消费交易的 RPC 输入序号，其中一个样本输入的引用输出带 Type Script，一个样本交易至少含两个引用不同 Type Script 的输入，另取一个引用输出无 Type Script 的输入样本。比较期间若交易状态、所属区块哈希或同高度 RPC 区块哈希改变，则该网络本次样本按状态变化或重组处理，不作数据正确性结论。
- 成功结果：引用输出带 Type Script 时，Explorer 返回的 `code_hash`、`hash_type`、`args` 与对应 RPC 引用输出的 `type` 逐字段精确一致，`script_hash` 等于由该 RPC `type` 字段复算的脚本哈希，且不会串到同一交易的其他输入或其他交易；引用输出无 Type Script 时返回 HTTP `200` 且 `data` 为 `null`。
- 失败结果：链上字段差异指出网络、请求 `:id`、消费交易哈希、RPC 输入序号、引用 Out Point、字段路径、API 值和 RPC 期望值；预期错误场景指出请求参数或资源状态、实际状态与错误对象及期望值。公开 URL 超时或 RPC 缺少目标交易时，只将该网络标记为事实基准不可用，不影响另一网络的结论。
- 不负责：双 Explorer 环境兼容性、媒体类型请求头、通用 JSON:API 成功资源结构、Lock Script、Cell Data、缓存、`verified_script_name` 的业务分类准确性；这些行为由通用契约或对应领域评审负责。

## 接口用法

```bash
curl --request GET \
  --url "${EXPLORER_API_URL}/v1/cell_input_type_scripts/${CELL_INPUT_ID}" \
  --header 'Accept: application/vnd.api+json' \
  --header 'Content-Type: application/vnd.api+json'
```

- 主网 `EXPLORER_API_URL`：`https://mainnet-api.explorer.nervos.org/api`
- 测试网 `EXPLORER_API_URL`：`https://testnet-api.explorer.nervos.org/api`
- `CELL_INPUT_ID` 按当前实现为 Explorer 数据库中的 `CellInput.id`，不是交易哈希、RPC 输入序号或 Out Point 输出索引。
- 交易详情中的 `display_inputs[].id` 当前是引用 `CellOutput.id`，与接口当前查询的 `CellInput.id` 不是同一类标识。

### 输入参数

| 位置 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| HTTP 方法 | `GET` | 方法 | 是 | 只读取 Type Script，不传请求体 |
| Path | `id` | 整数 | 是 | 当前实现中的 `CellInput.id`；必须存在且该输入必须关联 `previous_cell_output` |
| Header | `Accept` | 字符串 | 是 | 精确传入 `application/vnd.api+json` |
| Header | `Content-Type` | 字符串 | 是 | 精确传入 `application/vnd.api+json`，GET 请求也要求该头 |
| Query | 无 | — | 否 | 该接口没有分页、过滤或展示开关 |
| Body | 无 | — | 否 | 不发送 JSON 请求体 |

### 成功输出

HTTP 状态为 `200`，媒体类型为 `application/vnd.api+json`，响应示例：

```json
{
  "data": {
    "id": "<TYPE_SCRIPT_ID>",
    "type": "type_script",
    "attributes": {
      "args": "0x<ARGS_HEX>",
      "code_hash": "0x<32_BYTE_CODE_HASH>",
      "hash_type": "type",
      "script_hash": "0x<32_BYTE_SCRIPT_HASH>",
      "verified_script_name": null
    }
  }
}
```

引用输出没有 Type Script 时，HTTP 状态仍为 `200`，响应体为 `{"data": null}`。

| JSON 路径 | 类型 | 含义 | RPC 对照 |
| --- | --- | --- | --- |
| `data.id` | 字符串 | Explorer 内部 `TypeScript.id`，不是请求中的 `CellInput.id` | 无直接 RPC 字段 |
| `data.type` | 字符串 | JSON:API 资源类型 `type_script` | 无直接 RPC 字段 |
| `data.attributes.args` | `0x` 十六进制字符串 | Type Script 参数字节 | 引用输出 `type.args` |
| `data.attributes.code_hash` | `0x` 前缀 32 字节十六进制字符串 | Type Script 的代码哈希 | 引用输出 `type.code_hash` |
| `data.attributes.hash_type` | 字符串 | CKB Script hash type，原样返回链上值 | 引用输出 `type.hash_type` |
| `data.attributes.script_hash` | `0x` 前缀 32 字节十六进制字符串 | Type Script 的脚本哈希 | 可由引用输出 `type` 的 `code_hash`、`hash_type`、`args` 复算 |
| `data.attributes.verified_script_name` | 字符串或 `null` | Explorer 识别到的已验证脚本名称 | RPC 不提供，由 Explorer 元数据推导 |

### 错误输出

| HTTP 状态 | 触发条件 | 错误代码 | 标题 |
| --- | --- | --- | --- |
| `404` | `id` 不存在，或 Cellbase 输入没有 `previous_cell_output` | `1014` | `Cell Input Not Found` |
| `422` | `id` 不是整数 | `1013` | `URI parameters is invalid` |
| `406` | `Accept` 不是 `application/vnd.api+json` | `1002` | `Not Acceptable` |
| `415` | `Content-Type` 不是 `application/vnd.api+json` | `1001` | `Unsupported Media Type` |

错误体的 JSON 根值为数组，每项包含 `title`、`detail`、`code` 和 `status`，例如：

```json
[
  {
    "title": "Cell Input Not Found",
    "detail": "No cell input records found by given id",
    "code": 1014,
    "status": 404
  }
]
```

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `CELL-INPUT-TYPE-RPC-01` | 在公开主网和测试网分别从一笔已提交普通交易选择一个可定位到 RPC 输入序号的输入，用调用方可获取的公开标识请求 Type Script | 待确认：`:id` 应使用由哪个公开响应提供的 `CellInput.id`，或接口是否应接受交易详情 `display_inputs[].id` 所表示的引用 `CellOutput.id`；确定后，该标识能唯一定位这个 RPC 输入且请求成功 | 公开调用方拿不到可用标识、将输出 ID 当成输入 ID 而命中无关记录，或自动化在不知道链上对应关系时比较了无关脚本 | P0 |
| `CELL-INPUT-TYPE-RPC-02` | 在公开主网和测试网分别以已确认映射、且引用输出带 Type Script 的普通输入标识查询 Type Script，并用 RPC `previous_output.tx_hash` 和输出索引取得被引用输出 | API `data.attributes.code_hash`、`hash_type`、`args` 与 RPC 引用输出的 `type` 同名字段完全相等，包括 `0x` 前缀、前导零和全部 args 字节，且 `data.attributes.script_hash` 等于由该 RPC `type` 字段复算的脚本哈希 | Type Script 关联错误，或 code hash、hash type、args 被截断、改写、进制转换与序列化失真，或脚本哈希与脚本本体不一致 | P0 |
| `CELL-INPUT-TYPE-RPC-03` | 在公开主网和测试网分别选择一笔至少含两个普通输入、且这两个引用输出使用不同 Type Script 的已提交交易，分别以两个输入标识查询 | 两次响应分别等于各自 RPC 输入引用输出的 `type`，且两组 `code_hash`、`hash_type`、`args` 组合不同，不会固定返回首个输入或同一 Type Script | 多输入交易按错误序号、关联键或缓存键返回其他输入的 Type Script | P1 |
| `CELL-INPUT-TYPE-RPC-04` | 在公开主网和测试网分别以字母或小数形式的非整数 `id` 请求 Type Script | 返回 HTTP `422`；响应 JSON 根数组仅有一项，其 `code` 为 `1013`、`status` 为 `422`、`title` 为 `URI parameters is invalid`，`detail` 说明 URI 参数应为整数 | 非整数 ID 进入数据库查询、触发服务端异常或返回模糊错误 | P1 |
| `CELL-INPUT-TYPE-RPC-05` | 在公开主网和测试网分别以确认不存在的整数 `id` 请求 Type Script | 返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1014`、`status` 为 `404`、`title` 为 `Cell Input Not Found`，`detail` 说明指定 ID 没有 Cell Input 记录 | 不存在资源被误报为成功、参数错误或服务端异常 | P1 |
| `CELL-INPUT-TYPE-RPC-06` | 在公开主网和测试网分别以一个真实 Cellbase 输入的 `CellInput.id` 请求 Type Script | 因 Cellbase 输入没有 `previous_cell_output`，返回 HTTP `404`；响应 JSON 根数组仅有一项，其 `code` 为 `1014`、`status` 为 `404`、`title` 为 `Cell Input Not Found`，`detail` 说明指定 ID 没有 Cell Input 记录 | Cellbase 被按普通输入解析、解引用空值异常或伪造 Type Script | P1 |
| `CELL-INPUT-TYPE-RPC-07` | 在公开主网和测试网分别以已确认映射、且引用输出无 Type Script 的普通输入标识请求 Type Script | 返回 HTTP `200`；响应体为 `{"data": null}`，不返回 `404`，也不伪造或沿用其他输入的 Type Script | 无 Type Script 的输入被当作资源不存在报错、解引用空值异常，或返回串户的 Type Script | P1 |

## 本轮需要确认

- 请确认 `CELL-INPUT-TYPE-RPC-01` 的 `:id` 产品语义：是否应直接接受交易详情 `display_inputs[].id` 中的引用 `CellOutput.id`；若仍使用 `CellInput.id`，请确认公开调用方从哪个响应获得该值及其对应的交易哈希和输入序号。该问题与 `v1-cell-input-lock-scripts-show.md` 的 `CELL-INPUT-LOCK-RPC-01` 相同，可一并决定。
- 请确认 `CELL-INPUT-TYPE-RPC-07` 的契约：引用输出无 Type Script 时返回 HTTP `200` 且 `data` 为 `null` 是当前实测行为（测试网实测），请确认这是预期行为而非应改为 `404`。
- 请确认 `CELL-INPUT-TYPE-RPC-02` 至 `CELL-INPUT-TYPE-RPC-06` 的场景、预期结果和优先级可作为标识语义确定后的自动化依据。
- 媒体类型请求头、通用 JSON:API 成功资源结构、Lock Script、Cell Data、缓存和 `verified_script_name` 继续由相邻评审覆盖，不在本表重复。
