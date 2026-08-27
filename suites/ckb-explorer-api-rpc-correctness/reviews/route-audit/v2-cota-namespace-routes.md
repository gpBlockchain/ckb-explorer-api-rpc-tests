# V2 CoTA Namespace 路由审计用例评审

评审范围：核对 `/api/v2/nft/cota` 下 7 个路由所期待的 Controller 常量与源码实际 CoTA Controller Namespace
源码版本：`develop@0495ecd00a839f7618bad752f5ad92071124a991`

## 接口说明

- 接口作用：确认嵌套 `nft/cota` URL 能否解析并分发到已实现的 CoTA Action。
- 输入：逐个请求 7 个 `[NAMESPACE_MISMATCH]` 入口，并核对 Rails 路由期待常量与源码实际常量。
- 成功结果：路由 Namespace 与 Controller Namespace 统一后，各入口到达预期 Action；修正前明确记录缺失常量而不是把失败误判成业务空结果。
- 失败结果：报告 verb、path、期待常量、实际常量和外部响应；业务结果由后续 CoTA Aggregator 专项评审。
- 不负责：CoTA Class/Token/Issuer/Transaction 的数据正确性、Aggregator 可用性、通用错误对象及 NFT 非 CoTA 接口。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `ROUTE-COTA-01` | - [ ] 请求 `GET /api/v2/nft/cota/nft_classes` | 待确认：移动 Controller 或调整路由 Namespace；当前路由期待 `Api::V2::NFT::Cota::NFTClassesController#index`，但源码仅定义 `Api::V2::Cota::NFTClassesController#index`，已实现 Action 不可达 | CoTA Class 列表永久停在常量解析层 | P0 |
| `ROUTE-COTA-02` | - [ ] 请求 `GET /api/v2/nft/cota/nft_classes/:nft_class_id/tokens` | 待确认：统一 Namespace 后到达 Tokens `index`；当前期待 `Api::V2::NFT::Cota::TokensController#index`，实际实现位于 `Api::V2::Cota::TokensController#index` | CoTA Token 列表被误报为空或通用路由错误 | P0 |
| `ROUTE-COTA-03` | - [ ] 请求 `GET /api/v2/nft/cota/nft_classes/:nft_class_id/tokens/:id/claimed` | 待确认：统一 Namespace 后到达 Tokens `claimed`；当前期待 `Api::V2::NFT::Cota::TokensController#claimed`，实际 Action 位于少一层 `NFT` 的 Namespace | Token 领取状态接口因 Controller 常量错误不可达 | P0 |
| `ROUTE-COTA-04` | - [ ] 请求 `GET /api/v2/nft/cota/nft_classes/:nft_class_id/tokens/:id/sender` | 待确认：统一 Namespace 后到达 Tokens `sender`；当前期待 `Api::V2::NFT::Cota::TokensController#sender`，实际 Action 位于 `Api::V2::Cota::TokensController` | Token 发送者查询在业务逻辑前失败 | P0 |
| `ROUTE-COTA-05` | - [ ] 请求 `GET /api/v2/nft/cota/transactions` | 待确认：统一 Namespace 后到达 `Api::V2::Cota::TransactionsController#index`；当前路由寻找不存在的 `Api::V2::NFT::Cota::TransactionsController` | CoTA 交易历史入口完全不可用 | P0 |
| `ROUTE-COTA-06` | - [ ] 请求 `GET /api/v2/nft/cota/issuers/:id` | 待确认：统一 Namespace 后到达 `Api::V2::Cota::IssuersController#show`；当前路由期待多一层 `NFT` 的缺失 Controller | Issuer 详情因命名空间漂移不可达 | P0 |
| `ROUTE-COTA-07` | - [ ] 请求 `GET /api/v2/nft/cota/issuers/:id/minted` | 待确认：统一 Namespace 后到达 `Api::V2::Cota::IssuersController#minted`；当前路由期待不存在的 `Api::V2::NFT::Cota::IssuersController` | Issuer 铸造记录在分发前失败 | P0 |

## 本轮需要确认

- `ROUTE-COTA-01`、`ROUTE-COTA-02`、`ROUTE-COTA-03`、`ROUTE-COTA-04`、`ROUTE-COTA-05`、`ROUTE-COTA-06`、`ROUTE-COTA-07`：选择把源码 Controller 移入 `Api::V2::NFT::Cota`，或把 URL 路由显式指向现有 `Api::V2::Cota`。
- Namespace 修正后，`NFTClassesController#index` 的空 Action 和 `TokensController#index` 的未初始化结果仍需作为业务实现问题单独评审。
- 修正前外部 HTTP 状态取决于环境异常处理；修正后的成功和业务错误契约需由 CoTA 数据领域定义。
