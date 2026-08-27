# V1 UDT 元数据与邮箱验证更新正确性用例评审

评审范围：核对 `PATCH`/`PUT /api/v1/udts/:id` 与 `PATCH`/`PUT /api/v1/udt_verifications/:id` 的字段权限、验证码状态、邮件副作用和错误原子性
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：为 UDT 联系邮箱创建或刷新验证码并排队发送邮件，随后创建或更新 UDT 的公开展示元数据。
- 输入：Type Hash；验证接口可选 `locale`；元数据接口接受 `symbol`、`full_name`、`decimal`、`description`、`operator_website`、`icon_file`、`email` 和后续更新所需 `token`。
- 成功结果：PATCH 与 PUT 均路由到相同 update 行为；首次提交按 UDT 类型保存允许字段，已有邮箱的后续提交验证仍有效的验证码，并且验证记录、邮件任务和 UDT 状态可直接观测。
- 失败结果：目标、邮箱或验证码无效以及发送过频时返回对应错误，UDT 字段和验证码发送状态保持失败前值。
- 不负责：邮件提供商最终投递、链上代币身份和供应量、公开目录排序、交易历史及通用 HTTP 头契约。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `UDT-META-RPC-01` | - [ ] 邮箱尚为空的普通 sUDT 通过 `PATCH /api/v1/udts/:id` 提交合法完整元数据和邮箱 | 返回 `ok`；保存 Symbol、full name、decimal、描述、网站、图标和邮箱，并将 `published` 设为 true，不要求验证码 | PATCH 首次登记被错误要求验证码或字段未持久化 | P0 |
| `UDT-META-RPC-02` | - [ ] 邮箱尚为空的普通 sUDT 通过 `PUT /api/v1/udts/:id` 提交合法完整元数据和邮箱 | 返回 `ok`，产生与 PATCH 首次登记相同的字段值和发布状态 | PUT 与 PATCH 路由到相同行为却产生不同状态 | P0 |
| `UDT-META-RPC-03` | - [ ] 已有邮箱和有效验证记录的普通 UDT 通过 PATCH 携带匹配 token 更新元数据并传入不同邮箱 | 验证成功后只更新邮箱以外的允许字段，原邮箱保持不变，返回 `ok` | 验证后的更新意外变更归属邮箱 | P0 |
| `UDT-META-RPC-04` | - [ ] 已有邮箱和有效验证记录的普通 UDT 通过 PUT 携带匹配 token 更新元数据 | 产生与 PATCH 后续更新相同的允许字段结果，原邮箱保持不变并返回 `ok` | PUT 绕过验证码或与 PATCH 权限不一致 | P0 |
| `UDT-META-RPC-05` | - [ ] xUDT 或 xUDT-compatible 分别通过 PATCH 和 PUT 提交展示字段，同时夹带 Symbol、full name 与 decimal | 只更新描述、网站、图标和首次邮箱；Symbol、full name、decimal 与发布字段保持原值 | xUDT 的链派生核心身份被公开元数据接口改写 | P0 |
| `UDT-META-RPC-06` | - [ ] 普通 UDT 首次提交的邮箱缺失或格式错误，或 decimal 为负数、超过 39 或非数值 | 返回 UDT info 参数错误，整次更新不保存部分字段；decimal 的 0 和 39 边界可成功保存 | 无联系邮箱、非法精度或部分写入污染公开元数据 | P1 |
| `UDT-META-RPC-07` | - [ ] PATCH 或 PUT 只提交部分允许字段并省略已有字段 | 待确认：省略字段应保持原值，还是按当前 update 参数构造被写为 `nil`；两个动词确认后遵循同一约定 | PATCH 非预期清空字段，或 PUT/PATCH 的替换语义不明确 | P1 |
| `UDT-META-RPC-08` | - [ ] PATCH 或 PUT 使用不存在的 Type Hash | 返回 UDT not-found，且没有创建新 UDT 或验证记录 | 错误 Type Hash 隐式创建或改写其他 UDT | P1 |
| `UDT-META-RPC-09` | - [ ] 有联系邮箱的 UDT 首次通过 `PATCH /api/v1/udt_verifications/:id` 请求中文验证码 | 创建或刷新验证记录，保存请求 IP、六位十进制 token 和发送时间，以 `zh_CN` 排队一封包含该邮箱和 token 的邮件，并返回 `ok` | PATCH 未保存验证状态、语言或邮件参数 | P0 |
| `UDT-META-RPC-10` | - [ ] 有联系邮箱的 UDT 通过 `PUT /api/v1/udt_verifications/:id` 请求验证码，locale 缺失或不是 `zh_CN` | 创建或刷新与 PATCH 相同的验证状态，语言回退为 `en`，只排队一封邮件并返回 `ok` | PUT 行为漂移或未知 locale 产生未定义模板 | P0 |
| `UDT-META-RPC-11` | - [x] 验证接口的 Type Hash 不存在，或目标 UDT 没有联系邮箱 | 分别返回 UDT not-found 或 UDT no-contact-email；不创建验证记录也不排队邮件 | 给不存在或不可联系的代币发送验证码 | P1 |
| `UDT-META-RPC-12` | - [ ] 同一验证记录距上次发送不足 1 分钟时再次通过 PATCH 或 PUT 请求验证码 | 返回 token-sent-too-frequently；原 token、发送时间和 IP 保持不变，不新增邮件任务 | 重复请求绕过频率限制或使先前 token 意外失效 | P1 |
| `UDT-META-RPC-13` | - [ ] 已有邮箱的 UDT 更新时验证记录缺失，或 token 缺失、不匹配、距发送时间超过 10 分钟 | 分别返回 verification-not-found、token-required、token-not-match 或 token-expired；UDT 所有字段保持失败前值 | 无验证码、错误验证码或过期验证码仍能修改元数据 | P0 |
| `UDT-META-RPC-14` | - [ ] token 的发送时间恰好位于 10 分钟有效期边界，或输入含前导零 | 恰好位于边界仍有效，超过边界才过期；前导零按同一六位数值校验，不通过字符串或浮点比较 | 有效期边界抖动或验证码表示方式造成误拒绝 | P1 |
| `UDT-META-RPC-15` | - [ ] 邮件任务成功排队但外部邮件提供商状态不可读取 | 接口结论只证明验证记录持久化且 `deliver_later` 任务排队一次，不宣称收件人已经收到邮件 | 将异步排队误当成最终投递成功 | P2 |

## 本轮需要确认

- `UDT-META-RPC-07`：PATCH 与 PUT 省略字段时应保留旧值还是清空；当前控制器为两个动词构造同一组包含 `nil` 的属性。
- 邮件最终投递属于外部系统；本评审只观测任务排队、目标邮箱、token 和 locale。
