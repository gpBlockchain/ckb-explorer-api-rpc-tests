# Economic Supply Models 测试评审

评审范围：`GET /api/v1/market_data`、`GET /api/v1/market_data/:id`、`GET /api/v1/monetary_data/:id`。

源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：计算链上 Total/Circulating Supply 与名义 APC、名义通胀、实际通胀序列，不提供第三方价格或行情。
- 输入：`market_data/:id` 支持 `total_supply`、`circulating_supply`；`monetary_data/:id` 支持默认指标及带年数的 `nominal_apcN`。
- 成功结果：供给先以 Shannon 精确整数计算，再以 CKB 十进制字符串返回；初始供给 336 亿 CKB、Burn Quota 84 亿 CKB，锁定份额为 17%、15%、14%、5%、2%；Monetary 序列以十亿 CKB 为尺度并截断 8 位；Market 响应缓存 30 分钟并声明 10 分钟后台刷新与错误复用窗口。
- 失败结果：非法 Market ID 当前返回 JSON `null`，非法 Monetary ID 返回明确的 422；接口没有 RPC 外部判定源，公式使用同一已索引 Tip 的 DAO 和锁定状态复算。
- 不负责：第三方市场价格、交易所流通定义及预测性宏观模型。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `ECON-RPC-01` | 请求 `market_data` 首页并分别请求 `total_supply` 与 `circulating_supply` | 首页恰含两项供给值，且每项与对应详情接口的十进制字符串完全一致 | 首页与详情公式、类型或缓存结果分叉 | P0 |
| `ECON-RPC-02` | 在首次 5 月释放时刻边界前后分别复算 Total Supply | 时间戳小于或等于该时刻时为 `c_i - 84亿CKB`，大于该时刻后为 `c_i - 84亿CKB - (s_i - 未生成DAO利息)`；全程以 Shannon 整数运算后转为 CKB | 解锁边界、DAO 利息符号或 Burn Quota 错误 | P0 |
| `ECON-RPC-03` | 以当前 DAO 数据和各锁定份额复算 Circulating Supply | 结果等于 `c_i - s_i - 84亿CKB - 生态锁定 - 团队锁定 - 私募锁定 - 创始伙伴锁定 - 基金会锁定 - 漏洞奖励锁定` | 漏减锁定份额、重复扣除或使用错误 DAO 字段 | P0 |
| `ECON-RPC-04` | 在各生态、团队、私募、创始伙伴与基金会释放日期边界前后复算锁定量 | 生态按其 17% 配额依次锁定 97%、75%、50%、0，团队按 15% 配额锁定 2/3、1/2、1/3、0，私募按 14% 配额锁定 1/3 后归零，创始伙伴按 5% 配额锁定 1、3/4、1/2、0，基金会 2% 配额在首次其他释放点归零 | 配额常量、阶段比例、日期边界或份额联动错误 | P0 |
| `ECON-RPC-05` | 选择会产生非整 CKB 的供给快照 | API 返回精确十进制字符串，等于 Shannon 结果除以 `10^8` 后截断 8 位，不四舍五入且不出现科学计数法 | 浮点精度丢失、四舍五入或单位放大 `10^8` 倍 | P0 |
| `ECON-RPC-06` | 请求不受支持的 `market_data/:id` | 当前行为返回 HTTP 200 与 JSON `null`，不回退为 Total Supply 或首页对象 | 非法 ID 静默命中默认供给指标 | P1 |
| `ECON-RPC-07` | 请求默认 `nominal_apc` 与 `nominal_apcN` 自定义年数 | 默认返回 240 个按月元素，自定义返回 `12×N` 个；Primary Supply 每 4 年减半、Secondary Supply 每年 13.44 亿 CKB，累计 APC 逐月按公式增长 | 月数、四年减半分组或 Secondary 常量错误 | P0 |
| `ECON-RPC-08` | 请求默认 Nominal Inflation 与 Real Inflation 序列 | 两者均返回 600 个按月十进制字符串；每月 Real Inflation 精确等于对应 Nominal Inflation 减去 Nominal APC，并截断 8 位 | 50 年窗口错长、数组错位或实际通胀公式错误 | P0 |
| `ECON-RPC-09` | 请求不受支持的 `monetary_data/:id` | 返回 HTTP 422 与错误码 `1024`，不返回空模型或默认序列 | 非法模型 ID 被接受或误用默认模型 | P1 |
| `ECON-RPC-10` | 请求 `nominal_apc0`、超大年数或含前导零的自定义年数 | 待确认：允许的年数上下界、规范化规则与越界错误响应；任何决定都应限制序列长度和计算成本 | 任意数字后缀产生空序列、超大响应或资源放大 | P1 |

## 本轮需要确认

- `ECON-RPC-10`：`nominal_apcN` 的合法年数范围、前导零规则和越界响应。
