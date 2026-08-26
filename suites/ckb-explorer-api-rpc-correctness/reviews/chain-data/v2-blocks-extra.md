# V2 区块扩展查询 RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 为事实基准，核对 `GET /api/v2/blocks/ckb_node_versions` 的节点版本分布和 `GET /api/v2/blocks/by_epoch` 的 Epoch 索引选块结果
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：`ckb_node_versions` 返回 Explorer tip 附近 Epoch 窗口内按 Cellbase 节点版本聚合的区块数量；`by_epoch` 返回指定 Epoch 中按区块高度升序排列的第 `epoch_index` 个区块。
- 输入：每个网络分别调用无业务参数的 `GET /api/v2/blocks/ckb_node_versions`；调用 `GET /api/v2/blocks/by_epoch` 时提交非负整数 `epoch_number` 和有效范围内的 `epoch_index`，辅助使用同网络 RPC `get_epoch_by_number` 与 `get_block_by_number`。
- 取样：节点版本分布以 Explorer tip 对应的 RPC 规范区块为锚点，遍历确认后的 Epoch 窗口；Epoch 选块使用 Explorer 已同步的完整历史 Epoch，并覆盖首项、中间项和末项。比较期间若同一高度的 RPC 哈希改变，则该网络的本次样本按重组处理，不作数据正确性结论。
- 成功结果：主网和测试网各自的节点版本计数与同网络 RPC Cellbase witness 推导结果精确一致；按 Epoch 查询返回的区块身份、Epoch 坐标及可直接验证字段与同网络 RPC 精确一致。
- 失败结果：指出网络、Epoch、索引或区块高度、API 值、RPC 原值、推导后的期望值及差异字段；RPC 传输失败、缺少结果或观察到重组时，只将对应网络标记为事实基准不可用，不把它判成 API 数据错误，也不影响另一网络的结论。
- 不负责：双 Explorer 环境兼容性、媒体类型、通用 V2 错误结构、非法参数的 HTTP 契约，以及 BlockSerializer 中需要额外经济状态、历史输入或 Explorer 统计表才能验证的派生字段。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `V2-NODE-VERSIONS-RPC-01` | 在公开主网和测试网分别确认 Explorer tip 与同网络 RPC 指向同一规范区块，解码 tip Epoch 为 `E`，遍历 `max(E-42, 0)..E` 内全部 RPC 规范区块并按每块 Cellbase 首个 witness 中当前支持格式的节点版本分组后调用节点版本分布接口 | 每个网络的 API `version → blocks_count` 映射与 RPC 推导结果完全相同；无法提取版本的区块计入唯一的 `others` 分组，计数总和等于该最多 43 个 Epoch 编号窗口内的规范区块总数，两个网络独立得出结论 | 窗口边界错误、漏块或重复计数、无版本区块丢失，以及跨网络混算 | P0 |
| `V2-BLOCK-BY-EPOCH-RPC-01` | 在公开主网和测试网分别选择一个 Explorer 已完整同步的历史 Epoch，通过同网络 RPC 取得 `start_number` 和 `length`，再以首项、一个中间项和末项索引调用按 Epoch 查询接口，并读取 RPC 高度 `start_number + epoch_index` 的规范区块 | 每个索引返回的 API `block_hash` 和 `number` 都指向对应 RPC 规范区块；`epoch`、`start_number`、`length`、`block_index_in_epoch` 分别等于目标 Epoch、RPC 起始高度、RPC 长度和请求索引；`timestamp`、`transactions_root`、`version`、`nonce` 与 RPC header 一致，`uncles_count`、`proposals_count`、`transactions_count` 分别等于 RPC 对应数组长度，两个网络独立得出结论 | Epoch 行偏移、首尾 off-by-one、索引缺口导致后续区块错位，以及返回正确高度但区块内容或 Epoch 坐标错误 | P0 |
| `V2-NODE-VERSIONS-RPC-02` | 在 tip Epoch `E>=43` 且比较窗口稳定时，分别枚举 RPC Epoch `E-43`、`E-42` 和 `E` 的规范区块，并以全窗口重算版本计数 | Epoch `E-42` 与 `E` 的全部区块均计入，`E-43` 的区块均排除；API 各版本计数及总和只对应闭区间 `E-42..E`，不存在把下界写成严格大于、少算当前 Epoch 或多取一个旧 Epoch | 42 的减法与闭区间组合造成 42/43 个 Epoch off-by-one | P0 |
| `V2-NODE-VERSIONS-RPC-03` | 在公开主网和测试网的窗口内存在至少两个可识别版本且存在无法提取版本的区块时调用节点版本分布接口 | `data` 中每个版本只出现一次，`blocks_count` 为正 JSON 整数；可识别版本按版本字符串字典升序排列，`others` 唯一且位于最后，所有项计数之和仍等于 RPC 窗口区块数 | 同一版本拆成多组、计数被序列化为字符串/null、SQL 分组顺序漂移或多个空版本分组 | P1 |
| `V2-NODE-VERSIONS-RPC-04` | Cellbase message 出现多位 major/patch、预发布或构建标识，例如 `10.12.13`、`0.103.10`、`0.103.0-rc1` | API 的版本键必须能从该区块 Cellbase 交易的 witness/message 对应上；同一批区块按链上 Cellbase 信息归组后，`version → blocks_count` 与 API 一致，不另行规定完整 semver 或正则截断的展示策略 | 版本分组与链上 Cellbase 交易信息错位，或把交易里没有的版本字符串当成分组键 | P1 |
| `V2-NODE-VERSIONS-RPC-05` | 在主网或测试网稳定跨入新 tip Epoch `E+1`，等待 Explorer 同步并确认无重组后，重新以 RPC 计算版本分布 | 新结果精确等于从旧窗口移除 Epoch `E-42` 全部规范区块并加入 Epoch `E+1` 已同步规范区块后的映射；不继续累计过期 Epoch，也不因新 Epoch 尚未完整而引入 RPC 尚不存在的区块 | 窗口锚点未随 tip 推进、旧 Epoch 永久残留或新 Epoch 重复累计 | P1 |
| `V2-BLOCK-BY-EPOCH-RPC-02` | 在公开主网和测试网分别读取 RPC Epoch `0` 的 `start_number` 和 `length`，以索引 `0` 与 `length-1` 调用按 Epoch 查询 | 两次分别返回 Genesis Epoch 的首块和末块，API `number=start_number+epoch_index`、`block_index_in_epoch=epoch_index`，区块哈希及 RPC 可验证 header/数组计数字段完全一致 | Epoch 0 被当成缺失参数或假值、Genesis 首尾索引 off-by-one | P1 |
| `V2-BLOCK-BY-EPOCH-RPC-03` | 在公开主网和测试网分别对当前尚在增长的 tip Epoch 请求索引 `0` 和 Explorer 已同步的最后一个索引，并用 RPC 包围确认 tip 未重组 | 两个索引均返回对应高度 `start_number+epoch_index` 的规范区块；返回的 `length` 保持 RPC Epoch 计划长度，最后已同步索引不被误当成 Epoch 末项，两个网络独立判定 | 把当前已同步块数误作 Epoch length、当前 Epoch 首项错位或遗漏最新已同步块 | P1 |
| `V2-BLOCK-BY-EPOCH-RPC-04` | 分别请求不存在的 Epoch、已完整 Epoch 的 `epoch_index=length` 与更大索引，以及当前 Epoch 中 RPC 已定义但 Explorer 尚未同步的索引 | 均返回 HTTP `200` 和 JSON:API `data: null`，不返回前一项、最后一项、其他 Epoch 的区块或服务端异常 | 越界索引被夹到有效范围、跨 Epoch 取块，或未同步位置被误报为已存在 | P1 |
| `V2-BLOCK-BY-EPOCH-RPC-05` | 对一个有效历史 Epoch 的有效索引检查 JSON:API 结构及 RPC 可验证字段类型 | 根对象只有一个 `data` 资源；`data.type` 为 `block`，`attributes.number/start_number/length/version/proposals_count/uncles_count/timestamp/transactions_count/epoch/block_index_in_epoch/nonce` 均为十进制字符串且解析值与 RPC 一致，Hash 字段保持 `0x` 十六进制 | V1/V2 序列化结构混用、整数被输出为浮点/科学计数或字段类型随数值变化 | P1 |
| `V2-BLOCK-BY-EPOCH-RPC-06` | `epoch_number` 或 `epoch_index` 缺失、为字母、小数或负数时调用按 Epoch 查询 | 待确认：统一返回明确的 4xx 参数错误，还是保留当前 `to_i`/数据库类型转换语义；选定后每类输入必须有固定状态和响应体，且负 offset、非法数值不得触发 HTTP 500 | 缺失或畸形参数被静默转换为 Epoch/索引 0、负 OFFSET 数据库异常，或小数被截断到其他区块 | P1 |
| `V2-BLOCK-BY-EPOCH-RPC-07` | RPC 证明目标 Epoch 完整，但 Explorer 在请求索引之前存在同步缺口而更高区块已经入库时调用按 Epoch 查询 | API 不得把按已存记录 offset 得到的后续区块冒充目标索引；在缺口修复前返回 HTTP `200` 和 `data: null`，修复后返回高度严格等于 `start_number+epoch_index` 的 RPC 规范区块 | 以数据库行偏移代替 Epoch 坐标，在缺块时把全部后续索引静默左移 | P0 |
| `V2-NODE-VERSIONS-RPC-06` | 当任一公开网络在最近 43 个 Epoch 编号窗口内发生可稳定观察的规范链重组时，记录重组前映射，等待 Explorer 完成回滚和新链同步，再用 RPC 新规范区块重新推导版本分布；无法观察重组时将事实基准标记为不可用 | 同步完成后的 API 映射只统计新规范链区块：被替换旧块对应版本计数全部移除，新规范块按其 Cellbase witness 版本加入，所有计数总和等于重组后窗口规范区块数；后续重复请求不再出现旧分支残留或双重计数 | 回滚仅替换区块主体但未更新节点版本统计，导致旧分支与新分支同时计数或旧版本长期残留 | P1 |
| `V2-BLOCK-BY-EPOCH-RPC-08` | 当任一公开网络发生可稳定观察的规范链重组且目标高度仍属于同一 Epoch 时，记录重组前指定 `epoch_number/epoch_index` 的结果，等待 Explorer 完成回滚和新链同步后再次查询，并用 RPC 新规范区块核对；重组进行中或未观察到样本时将事实基准标记为不可用 | 同一 Epoch 坐标在同步完成后返回新规范区块的哈希及对应 header/数组计数字段，`number=start_number+epoch_index` 保持不变；旧分支区块不再返回，也不会因旧记录和新记录并存而使 offset 指向相邻区块 | 重组后按 Epoch 查询仍命中旧分支，或旧新记录同时参与排序导致目标索引漂移 | P1 |

## 本轮需要确认

- `V2-BLOCK-BY-EPOCH-RPC-06`：`by_epoch` 的 `epoch_number` 或 `epoch_index` 缺失、非数字或为负数时，是统一返回结构化 4xx 参数错误，还是保留当前隐式转换或异常行为。
- `V2-NODE-VERSIONS-RPC-01` 至 `V2-NODE-VERSIONS-RPC-06` 已确认进入自动化；版本串以对应区块 Cellbase 交易信息为准。公开网络未观察到稳定重组时 `V2-NODE-VERSIONS-RPC-06` 记为事实基准不可用。
- 请确认新增 `V2-BLOCK-BY-EPOCH-RPC-02` 至 `V2-BLOCK-BY-EPOCH-RPC-07` 可作为 Genesis/当前 Epoch、越界空资源、字段类型、参数校验和同步缺口评审依据；本轮只补充测试点，不进入自动化门禁。
- 请确认新增 `V2-BLOCK-BY-EPOCH-RPC-08` 可作为同一 Epoch 坐标在规范链重组后替换旧区块并保持索引稳定的评审依据；公开网络未出现可稳定观察重组时只记录事实基准不可用。本轮只补充测试点，不进入自动化门禁。
