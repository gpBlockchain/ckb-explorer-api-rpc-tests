# V2 REST 生成路由审计用例评审

评审范围：核对 `config/routes/v2.rb` 中未限制 `resources` 所生成、但目标 Controller 未实现对应 Action 的 22 个公开入口
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：确认每个 URL/HTTP Method 是否被 Rails 路由识别、解析到哪个 Controller/Action，以及该 Action 是否实际可分发。
- 输入：逐个请求 22 个 `[ROUTE_ONLY]` 入口，同时用路由识别结果核对 Controller 与 Action。
- 成功结果：对每条入口明确记录“保留并实现”或“从公开路由删除”的产品决定；决定落地前按当前源码确认路由存在且目标 Action 缺失。
- 失败结果：若实际路由、目标 Action 或外部响应与评审记录不同，报告具体 verb、path、目标与外部状态；开发/生产异常中间件造成的状态差异不互相替代。
- 不负责：已实现的 `raw`、`details`、NFT GET 列表/详情业务值、通用错误对象格式和 CoTA Namespace 路由。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `ROUTE-REST-01` | - [ ] 请求 `GET /api/v2/ckb_transactions` | 待确认：应实现公开列表或删除该路由；当前路由识别为 `Api::V2::CkbTransactionsController#index`，但 Controller 未定义 `index`，请求在 Action 分发层失败而不是进入业务列表 | 调用方把已注册路由误认为可用列表，发布后持续收到 ActionNotFound | P1 |
| `ROUTE-REST-02` | - [ ] 请求 `GET /api/v2/ckb_transactions/:id` | 待确认：应实现公开详情或删除该路由；当前路由识别为 `Api::V2::CkbTransactionsController#show`，但 Controller 未定义 `show`，不会回退到 `details` | REST 详情与已实现的 `/details` 混淆，导致不可预测失败 | P1 |
| `ROUTE-REST-03` | - [ ] 请求 `GET /api/v2/transactions` | 待确认：应实现 REST 列表或限制 `resources`；当前解析到 `Api::V2::TransactionsController#index`，而该 Action 缺失 | 自动生成的列表入口暴露为不可用公开 API | P1 |
| `ROUTE-REST-04` | - [ ] 请求 `POST /api/v2/transactions` 并提交最小 JSON 请求体 | 待确认：应实现创建语义或删除写路由；当前解析到缺失的 `Api::V2::TransactionsController#create`，不会创建或改变交易记录 | 未设计的写入口被误用，未来意外继承通用创建行为 | P0 |
| `ROUTE-REST-05` | - [ ] 请求 `GET /api/v2/transactions/new` | 待确认：JSON API 是否需要该表单入口；当前解析到缺失的 `Api::V2::TransactionsController#new`，且不会被 `:id` 详情路由吞并 | Rails HTML 表单路由意外暴露在 API Namespace | P2 |
| `ROUTE-REST-06` | - [ ] 请求 `GET /api/v2/transactions/:id` | 待确认：应实现 REST 详情或删除；当前解析到缺失的 `Api::V2::TransactionsController#show`，不会自动调用 `/raw` 或 `/details` | 调用方误判三个相近交易详情入口等价 | P1 |
| `ROUTE-REST-07` | - [ ] 请求 `GET /api/v2/transactions/:id/edit` | 待确认：JSON API 是否需要编辑表单入口；当前解析到缺失的 `Api::V2::TransactionsController#edit` | Rails 编辑表单入口意外暴露且形成无意义攻击面 | P2 |
| `ROUTE-REST-08` | - [ ] 请求 `PATCH /api/v2/transactions/:id` 并提交任意可辨识字段 | 待确认：应实现更新授权与字段契约或删除；当前解析到缺失的 `Api::V2::TransactionsController#update`，交易记录不应发生变化 | 未授权或未设计的交易更新入口被意外启用 | P0 |
| `ROUTE-REST-09` | - [ ] 对同一交易请求 `PUT /api/v2/transactions/:id` | 待确认：应与 PATCH 共享明确更新契约或删除；当前同样解析到缺失的 `update`，交易记录不应发生变化 | PUT 与 PATCH 暴露状态不一致或绕过未来更新校验 | P0 |
| `ROUTE-REST-10` | - [ ] 请求 `DELETE /api/v2/transactions/:id` | 待确认：应实现受控删除或删除公开路由；当前解析到缺失的 `Api::V2::TransactionsController#destroy`，交易记录保持不变 | 未设计的销毁入口未来导致链上索引记录被删除 | P0 |
| `ROUTE-REST-11` | - [ ] 请求 `POST /api/v2/nft/collections` 并提交最小集合请求体 | 待确认：应实现创建权限与持久化语义或限制路由；当前解析到缺失的 `Api::V2::NFT::CollectionsController#create`，集合不应被创建 | 公开创建路由被误认为支持人工写入链上索引集合 | P0 |
| `ROUTE-REST-12` | - [ ] 请求 `GET /api/v2/nft/collections/new` | 待确认：API 是否需要新建表单入口；当前解析到缺失的 `Api::V2::NFT::CollectionsController#new` | HTML 风格表单路由混入 JSON API | P2 |
| `ROUTE-REST-13` | - [ ] 请求 `GET /api/v2/nft/collections/:id/edit` | 待确认：API 是否需要集合编辑表单入口；当前解析到缺失的 `Api::V2::NFT::CollectionsController#edit` | 客户端误判集合支持人工编辑 | P2 |
| `ROUTE-REST-14` | - [ ] 请求 `PATCH /api/v2/nft/collections/:id` 并修改一个字段 | 待确认：应定义授权更新或删除；当前解析到缺失的 `Api::V2::NFT::CollectionsController#update`，集合保持不变 | 未授权修改索引产生的 NFT 集合元数据 | P0 |
| `ROUTE-REST-15` | - [ ] 对同一集合请求 `PUT /api/v2/nft/collections/:id` | 待确认：应与 PATCH 采用相同授权契约或删除；当前解析到同一缺失 `update`，集合保持不变 | PUT 成为绕过 PATCH 校验的更新入口 | P0 |
| `ROUTE-REST-16` | - [ ] 请求 `DELETE /api/v2/nft/collections/:id` | 待确认：应实现受控删除或删除公开路由；当前解析到缺失的 `destroy`，集合及关联 Item 保持不变 | 链上索引集合被公开销毁或产生孤立 Item | P0 |
| `ROUTE-REST-17` | - [ ] 请求 `POST /api/v2/nft/collections/:collection_id/items` 并提交最小 Item 请求体 | 待确认：应实现父集合内创建权限或限制路由；当前解析到缺失的 `Api::V2::NFT::ItemsController#create`，Item 不应被创建 | 调用方通过自动生成路由伪造 NFT Item | P0 |
| `ROUTE-REST-18` | - [ ] 请求 `GET /api/v2/nft/collections/:collection_id/items/new` | 待确认：API 是否需要嵌套 Item 新建表单；当前解析到缺失的 `Api::V2::NFT::ItemsController#new` | HTML 表单入口在嵌套 API 路由中意外暴露 | P2 |
| `ROUTE-REST-19` | - [ ] 请求 `GET /api/v2/nft/collections/:collection_id/items/:id/edit` | 待确认：API 是否需要嵌套 Item 编辑表单；当前解析到缺失的 `Api::V2::NFT::ItemsController#edit` | 客户端误判链上 Item 可人工编辑 | P2 |
| `ROUTE-REST-20` | - [ ] 请求 `PATCH /api/v2/nft/collections/:collection_id/items/:id` 并修改一个字段 | 待确认：应定义父资源隔离与授权更新或删除；当前解析到缺失的 `Api::V2::NFT::ItemsController#update`，Item 保持不变 | 更新入口绕过父集合归属或篡改索引数据 | P0 |
| `ROUTE-REST-21` | - [ ] 对同一 Item 请求 `PUT /api/v2/nft/collections/:collection_id/items/:id` | 待确认：应与 PATCH 共享父资源和授权契约或删除；当前解析到同一缺失 `update`，Item 保持不变 | PUT 与 PATCH 处理不一致或形成校验绕过 | P0 |
| `ROUTE-REST-22` | - [ ] 请求 `DELETE /api/v2/nft/collections/:collection_id/items/:id` | 待确认：应实现受控删除并验证父集合，或删除公开路由；当前解析到缺失的 `destroy`，Item 保持不变 | 公开删除链上索引 Item 或跨集合删除 | P0 |

## 本轮需要确认

- `ROUTE-REST-01`、`ROUTE-REST-02`、`ROUTE-REST-03`、`ROUTE-REST-04`、`ROUTE-REST-05`、`ROUTE-REST-06`、`ROUTE-REST-07`、`ROUTE-REST-08`、`ROUTE-REST-09`、`ROUTE-REST-10`、`ROUTE-REST-11`、`ROUTE-REST-12`、`ROUTE-REST-13`、`ROUTE-REST-14`、`ROUTE-REST-15`、`ROUTE-REST-16`、`ROUTE-REST-17`、`ROUTE-REST-18`、`ROUTE-REST-19`、`ROUTE-REST-20`、`ROUTE-REST-21`、`ROUTE-REST-22`：逐个决定实现目标 Action，还是用 `only`/`except` 从公开路由删除。
- 外部 HTTP 状态和响应体受部署环境异常中间件影响；产品需为保留或退役入口确定稳定的调用方契约。
- 写路由在决定前必须保持无副作用；GET 表单路由需确认是否属于 JSON API 设计。
