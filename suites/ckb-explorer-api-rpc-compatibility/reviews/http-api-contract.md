# HTTP API 通用契约用例评审

评审范围：基准环境与候选环境之间共有的路由、媒体类型、表示、分页、CSV、缓存和差异报告行为
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：对同一确定性 HTTP 请求保留两侧原始观测，并判断候选环境是否保持基准环境的外部契约。
- 输入：方法、`/v1` 或 `/v2` 路径、查询、请求头、请求体、确定性 fixture 和逐接口比较规则。
- 成功结果：两侧状态、选定响应头、解码后的结构、类型、稳定值、顺序和分页语义一致。
- 失败结果：报告基准/候选侧、失败阶段、方法/路径和精确差异，同时对敏感信息脱敏。
- 不负责：区块、地址、代币、NFT、Portfolio、Fiber 等领域数据本身的业务正确性。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `TP-COMPATIBILITY-API-CONTRACT-001` | - [ ] 使用各自确定性 fixture 调用 124 个 ACTIVE 方法/路径，V1 请求携带规定媒体头 | 两侧均完成请求，接口分类状态、响应格式和路由含义一致 | 活跃路由缺失、接错控制器或部署不可达 | P0 |
| `TP-COMPATIBILITY-API-CONTRACT-002` | - [ ] 在不允许成功写入的条件下调用 22 个 ROUTE_ONLY 方法/路径 | 待确认：继续要求候选侧保持基准侧的原始失败状态与错误类别，还是把修复后的成功响应作为目标 | 把缺失动作误报为成功兼容，或修复路由后仍锁定旧故障 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-003` | - [ ] 使用确定性路径参数调用 7 个 CoTA 命名空间不匹配路由 | 待确认：继续要求两侧失败状态、内容类型和错误结构一致，还是把修复后的成功响应作为目标 | 命名空间回归未被发现，或修复后仍以旧故障验收 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-004` | - [ ] 请求未知路径，并对已知只读接口使用错误方法 | 两侧返回等价的外部错误，后续状态观测不发生变化 | 错误路由被意外接受或触发写入 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-005` | - [ ] V1 请求的 Accept 与 Content-Type 都精确为 `application/vnd.api+json` | 两侧都分发请求并返回相同类别的领域响应 | 合法 V1 客户端被媒体类型校验拦截 | P0 |
| `TP-COMPATIBILITY-API-CONTRACT-006` | - [ ] Accept 合法，仅缺失或破坏 V1 Content-Type | 两侧在领域处理前返回 HTTP 415，错误码和字段与 1001 契约一致 | 无效请求进入领域逻辑或两侧错误格式漂移 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-007` | - [ ] Content-Type 合法，仅缺失或破坏 V1 Accept | 两侧返回 HTTP 406，错误码和字段与 1002 契约一致 | 内容协商错误被忽略或两侧错误格式漂移 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-008` | - [ ] 发送双无效、重复、逗号拼接、大小写变化和带参数的 V1 媒体头 | 两侧选择同一首个校验错误，后续状态观测不发生变化 | 校验优先级漂移或边界头触发副作用 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-009` | - [ ] 比较代表性的 V1 集合与详情成功响应 | 仅归一化部署本地 JSON:API resource ID；媒体类型、resource type、attributes、relationships、links、meta、标量类型和业务值一致 | 把正常的数据库 ID 差异误报为故障，或同时漏掉业务字段漂移 | P0 |
| `TP-COMPATIBILITY-API-CONTRACT-010` | - [ ] 调用当前可构造的各类 V1 异常 fixture | 两侧 HTTP 状态以及错误 code、title、detail 一致 | 候选侧改变客户端依赖的错误契约 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-011` | - [ ] 分别查询格式错误和格式正确但不存在的 V1 标识 | 两类输入保持各自不同的基准状态与错误码，候选侧逐类匹配 | 无效输入与资源不存在被错误合并 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-012` | - [ ] 比较含 null、空集合、大十进制字符串、JSON 数字、布尔值和十六进制值的 V1 响应 | 两侧值和 JSON 标量类型精确一致，不发生强制转换、截断或大小写漂移 | 精度丢失或客户端类型契约破坏 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-013` | - [ ] 比较代表性的 V2 集合与详情成功响应 | 两侧键、嵌套结构、列表顺序、标量类型和稳定值一致 | V2 响应结构或值静默漂移 | P0 |
| `TP-COMPATIBILITY-API-CONTRACT-014` | - [ ] 提交当前可构造的 V2 ActiveInteraction 非法参数 | 两侧返回 HTTP 404，错误字段与 code 2000 契约一致 | 参数校验状态或错误结构漂移 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-015` | - [ ] 触发当前可构造的 V2 领域异常与认证异常 | 两侧 status、code、title、detail 一致，且不暴露 HTML 或内部堆栈 | 内部错误泄漏或客户端错误处理失效 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-016` | - [ ] 在能区分两者的 V2 接口上分别查询格式错误和不存在的标识 | 每类输入都匹配基准 4xx 状态和响应结构 | 无效标识与不存在资源语义混淆 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-017` | - [ ] 集合接口省略分页参数 | 两侧首页身份、元数据、链接和实际默认页大小一致 | 默认分页变化导致客户端漏数或重复拉取 | P0 |
| `TP-COMPATIBILITY-API-CONTRACT-018` | - [ ] 对确定且有序的数据连续请求相邻显式分页 | 两侧行、总数、总页数和链接一致，跨页无重复或遗漏身份 | 分页边界重复、漏项或统计错误 | P0 |
| `TP-COMPATIBILITY-API-CONTRACT-019` | - [ ] V1 page 或 page_size 使用非整数、零和负数 | 两侧返回等价 HTTP 400，并按基准选择 code 1007 或 1008 | 非法分页被接受或错误优先级漂移 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-020` | - [ ] 请求超范围页和过滤后为空的集合 | 两侧状态、空 data 结构、元数据和链接一致 | 空结果被误报为异常或分页元数据不一致 | P2 |
| `TP-COMPATIBILITY-API-CONTRACT-021` | - [ ] 重复执行支持的过滤与排序组合，包括唯一键和显式并列值 | 两侧过滤成员和有序身份在重复执行间一致 | 排序不稳定或过滤条件丢失 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-022` | - [ ] 发送不支持的排序键/方向和超大 page_size | 两侧状态、回退排序和实际上限一致 | 无界响应或不兼容的排序回退 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-023` | - [ ] 使用有效 fixture 调用每个 ACTIVE CSV 路由 | 两侧状态、CSV 媒体类型、attachment disposition 和文件名一致 | 导出接口返回错误格式或不可下载文件 | P0 |
| `TP-COMPATIBILITY-API-CONTRACT-024` | - [ ] 导出默认范围和显式有效日期/区块范围 | 两侧解码后的表头、行、单元格值和确定顺序一致 | 导出漏行、错列或排序漂移 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-025` | - [ ] 导出空范围、边界范围、无效标识以及反向/畸形范围 | 两侧产生相同错误或相同仅表头 CSV 结果 | 边界范围导致崩溃或两侧处理分歧 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-026` | - [ ] 导出包含 Unicode、逗号、引号、换行和类公式前缀的值 | 两侧载荷解码为相同的行列单元格，不发生结构注入或损坏 | 特殊字符破坏 CSV 结构或触发表格公式 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-027` | - [ ] 对稳定且可缓存的 fixture 先冷请求再重复热请求 | 两侧每次状态和正文一致，响应不会串到其他 fixture | 缓存污染或热请求返回陈旧资源 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-028` | - [ ] 重放响应中的 ETag 或 Last-Modified，并观察 Cache-Control | 两侧 freshness 指令、条件请求状态和空/非空正文语义一致 | 条件缓存契约改变导致无效传输或陈旧数据 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-029` | - [ ] 在热缓存中交替访问不同资源 ID、过滤条件和页码 | 每个响应始终匹配自身 fixture，不发生缓存键串扰 | 用户收到另一个资源或查询的缓存结果 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-030` | - [ ] 通过成对执行器运行一个确定性请求 | 结果含一个 request ID，并在归一化前完整保留基准与候选观测 | 原始证据丢失导致差异不可复核 | P0 |
| `TP-COMPATIBILITY-API-CONTRACT-031` | - [ ] 分别制造 JSON 值、类型、缺键、列表成员、列表顺序、HTTP 状态和选定响应头差异 | 每种漂移都失败，并指出精确 JSON 路径或响应头及两侧有类型的值 | 比较器漏报或只给出不可定位的总括错误 | P0 |
| `TP-COMPATIBILITY-API-CONTRACT-032` | - [ ] 同时包含已声明和未声明易变字段的响应进行比较 | 仅接口级白名单路径被归一化，每条规则出现在报告中，未声明差异失败 | 宽泛忽略规则掩盖真实兼容性回归 | P0 |
| `TP-COMPATIBILITY-API-CONTRACT-033` | - [ ] 比较发生重排或值变化的有序 JSON、白名单集合 JSON 和解码 CSV | 有序重排失败；仅获准路径的集合顺序差异通过；CSV 指出差异行列 | 错误比较模式掩盖顺序或单元格变化 | P1 |
| `TP-COMPATIBILITY-API-CONTRACT-034` | - [ ] 分别在两侧触发 DNS/连接、超时、HTTP、JSON 解码、CSV 解码和内容不一致 | 失败报告明确侧别、阶段、方法/路径和有界详情，并保留另一侧观测 | 网络故障、解码故障和内容回归被混为一类 | P0 |
| `TP-COMPATIBILITY-API-CONTRACT-035` | - [ ] 请求含 Authorization、Cookie、API-key 类头和敏感查询值 | 存储与控制台诊断遮蔽配置的秘密，同时保留可比较的头存在性和响应行为 | 报告或日志泄漏凭据 | P0 |
| `TP-COMPATIBILITY-API-CONTRACT-036` | - [ ] 配置瞬时传输失败后成功，并分别制造确定性 HTTP/内容不一致 | 仅传输失败在上限内重试且每次尝试可见；HTTP/内容不一致在首次成对观测后返回 | 重试掩盖稳定回归或造成重复请求 | P1 |

## 本轮需要确认

- `TP-COMPATIBILITY-API-CONTRACT-002`：22 个 ROUTE_ONLY 路由继续以基准故障行为为兼容目标，还是以修复成功为目标。
- `TP-COMPATIBILITY-API-CONTRACT-003`：7 个 CoTA 命名空间不匹配路由继续以基准故障行为为兼容目标，还是以修复成功为目标。
- 其余 34 条用例保留原有行为和优先级；请确认本表可作为后续自动化映射的唯一评审来源。
