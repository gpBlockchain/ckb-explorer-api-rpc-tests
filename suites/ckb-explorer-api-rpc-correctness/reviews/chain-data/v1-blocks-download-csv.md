# V1 区块 CSV RPC 正确性用例评审

评审范围：在公开主网和测试网分别以同网络 CKB RPC 为事实基准，核对 `GET /api/v1/blocks/download_csv` 的区块筛选、行选择顺序、500 行上限和六列 CSV 数据
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：将满足高度和毫秒时间戳过滤条件的区块导出为 CSV；本评审只判断 CSV 中的区块集合和列值是否与同一 CKB 网络一致，并要求主网、测试网各自产生独立结论。
- 公开主网：Explorer `https://mainnet-api.explorer.nervos.org/api`；CKB RPC `https://mainnet.ckbapp.dev/`。
- 公开测试网：Explorer `https://testnet-api.explorer.nervos.org/api`；CKB RPC `https://testnet.ckbapp.dev/`。
- 输入：每个网络分别调用 Explorer `GET /api/v1/blocks/download_csv`，按用例传入十进制 `start_number`、`end_number`、`start_date`、`end_date`；RPC 使用 `get_block_by_number` 和 `get_block_economic_state` 取得规范链区块及成熟奖励。
- 取样：每个网络先用高度 0 的区块详情和 RPC 区块哈希校验链身份；筛选用例选取边界可由 RPC 明确定位的已确认区块，列值用例包含普通交易、非零成熟奖励和非空 Cellbase witness。比较期间若同一高度的 RPC 哈希改变，则该网络本次样本按重组处理，不作数据正确性结论。
- 成功结果：CSV 表头和每行列数稳定；匹配不超过 500 个区块时返回完整集合，超过 500 个时先保留高度最小的 500 个区块，最终均按高度降序排列；RPC 十六进制整数无损转换，奖励由 Shannon 精确换算为 CKB，矿工地址按对应网络编码，UTC 日期由毫秒时间戳确定转换。
- 失败结果：指出网络、过滤条件、CSV 行号、区块高度、列名、CSV 值、RPC 原值、转换或推导后的期望值及差异；单个公开 URL 超时、返回错误、缺少目标区块或经济状态时，只将该网络标记为事实基准不可用，不影响另一网络的结论，也不把它判成 CSV 数据错误。
- 不负责：双 Explorer 环境兼容性、媒体类型、Content-Disposition、文件名、通用 CSV 转义、无效参数错误契约、缓存，以及未出现在 CSV 中的区块详情字段；这些行为由 HTTP API 通用契约或相邻 Chain Data 评审负责。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `BLOCKS-CSV-RPC-01` | 在公开主网和测试网分别下载至少含一行数据的区块 CSV | 表头严格等于 `Blockno,Transactions,UnixTimestamp,Reward(CKB),Miner,date(UTC)`，其后每个数据行均恰好有六列且各列位于对应表头之下 | 表头改名、列错位或列数漂移导致调用方按错误含义解析数据 | P0 |
| `BLOCKS-CSV-RPC-02` | 在公开主网和测试网分别以两个已确认区块高度作为 `start_number` 和 `end_number` 下载一个不超过 500 个区块的闭区间 | CSV 高度序列严格等于同网络 RPC 中该闭区间的全部高度按降序排列，上下界各出现一次，没有区间外、遗漏或重复行 | 高度边界被排除、单侧过滤失效、排序反转或区块重复/漏导出 | P0 |
| `BLOCKS-CSV-RPC-03` | 在公开主网和测试网分别以两个已确认区块的 RPC 毫秒时间戳作为 `start_date` 和 `end_date` 下载一个不超过 500 个区块的时间闭区间 | CSV 行集合严格等于同网络 RPC 中 `header.timestamp` 位于闭区间内的全部规范链区块并按高度降序排列，时间上下界对应行均被包含 | 时间单位错误、边界使用开区间、按创建时间而非链上时间过滤或排序错误 | P0 |
| `BLOCKS-CSV-RPC-04` | 在公开主网和测试网分别同时传入部分重叠的高度闭区间与毫秒时间闭区间 | CSV 行集合严格等于同时满足两组 RPC 条件的区块交集并按高度降序排列，不返回只满足其中一组条件的区块 | 多种过滤条件按并集生效、某一组条件被忽略或组合后顺序改变 | P1 |
| `BLOCKS-CSV-RPC-05` | 在公开主网和测试网分别传入没有任何规范链区块同时满足的高度与时间条件 | CSV 只包含固定表头且没有数据行 | 空结果被填入区间外区块、残留上次结果或输出无法解析的空文件 | P1 |
| `BLOCKS-CSV-RPC-06` | 在公开主网和测试网分别不传过滤条件，并以 `start_number=100`、`end_number=700` 查询包含 601 个区块的闭区间 | 两种请求均先保留匹配集合中高度最小的 500 个区块，再按高度降序输出；默认请求严格返回 `499` 至 `0`，范围请求严格返回 `599` 至 `100` | 500 行上限失效、从匹配集合的错误一端截取、边界偏移或最终输出顺序变为升序 | P1 |
| `BLOCKS-CSV-RPC-07` | 在公开主网和测试网分别下载包含 Cellbase 和普通交易的已确认区块，并逐行取得同高度 RPC 区块 | 每行 `Blockno`、`Transactions`、`UnixTimestamp` 分别等于 RPC `header.number`、`transactions` 数量和 `header.timestamp`；`date(UTC)` 等于毫秒时间戳截到整秒后按 UTC 格式化的 `YYYY-MM-DD HH:MM:SS` | CSV 行关联到错误区块、漏计 Cellbase、时间进制/单位错误或 UTC 日期舍入及时区错误 | P0 |
| `BLOCKS-CSV-RPC-08` | 在公开主网和测试网分别下载 `get_block_economic_state` 已可用且主次奖励非零的成熟区块 | 将 `Reward(CKB)` 作为十进制定点数解析并乘以 `100000000` 后，严格等于同网络 RPC `miner_reward.primary + miner_reward.secondary` 的 Shannon 整数值，全程不使用浮点数 | 奖励尚未成熟、遗漏主次发行、CKB/Shannon 换算或小数精度错误 | P0 |
| `BLOCKS-CSV-RPC-09` | 在公开主网和测试网分别下载 Cellbase witness 非空的已确认区块 | 从 RPC 第一笔交易首个 witness 解码 Cellbase Lock Script，并按对应网络编码所得地址与该行 `Miner` 完全相同 | Cellbase witness 解码、Lock Script 提取或主网/测试网地址编码错误导致矿工身份错误 | P1 |

## 本轮需要确认

- 无；9 条用例均已确认，超过 500 个匹配区块时保留高度最小的 500 个，再按高度降序排列。
