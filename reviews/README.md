# 测试领域与评审文档

目标源码：`https://github.com/nervosnetwork/ckb-explorer.git`，当前分析版本 `develop@0495ecd00a839f7618bad752f5ad92071124a991`。
执行方式：兼容性套件向基准环境和候选环境发送同一确定性请求，比较可观察的 HTTP 行为；机器可执行的 153 条路由清单保存在套件配置中，不在评审文档重复维护。

| 测试领域 | 责任与边界 | 入口 | 可观察结果 | 评审文档 |
| --- | --- | --- | --- | --- |
| HTTP API 通用契约 | 比较所有接口共有的路由、媒体类型、错误、分页、CSV、缓存和差异报告规则；不判断具体业务数据是否正确 | `/api/v1/*`、`/api/v2/*`、基准与候选 URL | 状态、选定响应头、数据类型和值、顺序、分页、逐字段差异 | `suites/ckb-explorer-api-rpc-compatibility/reviews/http-api-contract.md` |
| 链数据 | 区块、交易、Cell 与待处理池；不负责地址聚合、代币解释或 DAO 账务 | 区块、交易、Cell 子资源与 pending 路由 | 区块/交易身份、确认状态、Cell 内容、原始数据、分页和 CSV | `suites/ckb-explorer-api-rpc-compatibility/reviews/chain-data.md` |
| 地址与 DAO | 地址余额、Cell、历史和 DAO 生命周期；不负责代币元数据或 Portfolio 所有权 | 地址、地址交易、DAO 交易、存款人和事件路由 | 地址身份、容量、Cell 集合、DAO 记录、分页、总量和导出行 | `suites/ckb-explorer-api-rpc-compatibility/reviews/address-and-dao.md` |
| 同质化代币 | UDT、xUDT、铭文的发现、元数据、持仓和活动；不负责 NFT 与 RGB++ | UDT/xUDT/fungible/inscription、持仓、验证与小时统计路由 | 代币身份与元数据、供应量、持仓、活动、过滤、排序、分页和 CSV | `suites/ckb-explorer-api-rpc-compatibility/reviews/fungible-tokens.md` |
| NFT 与 RGB++ | NFT、CoTA、Bitcoin 绑定与 RGB++ 资产；不负责普通 CKB 转账和同质化代币元数据 | NFT、CoTA、DAS、Bitcoin、RGB 相关路由 | 集合/物品/转移身份、所有权、Bitcoin 关联、RGB Cell、统计和导出 | `suites/ckb-explorer-api-rpc-compatibility/reviews/nft-rgb.md` |
| 合约与脚本 | 已知合约/脚本及其部署、引用和交易关系；不负责 DAO 和通用交易渲染 | contracts、contract_transactions、scripts 路由 | 脚本标识、合约分类、关联交易/Cell、过滤、排序、分页和 CSV | `suites/ckb-explorer-api-rpc-compatibility/reviews/contracts-and-scripts.md` |
| 发现与统计 | 搜索建议、网络、市场、货币与时间序列聚合；不负责地址/代币/Fiber 专属统计 | suggest、statistics、nets、market、distribution、monitor 路由 | 实体建议、指标、时间桶、图表序列、网络/市场快照和空结果 | `suites/ckb-explorer-api-rpc-compatibility/reviews/discovery-and-statistics.md` |
| Portfolio | 用户认证以及自有地址组合的维护与查询；不负责公共地址接口 | session、user、addresses、statistics、accounts、transactions 路由 | 认证错误、用户/地址状态变化、余额、账户/交易集合、授权边界和 CSV | `suites/ckb-explorer-api-rpc-compatibility/reviews/portfolio.md` |
| Fiber | Peer、Channel、图拓扑、图交易和统计；不负责 CKB 节点网络统计或无 HTTP 观测的同步内部状态 | `/api/v2/fiber/*` | Peer/Channel/Node 标识与属性、拓扑、过滤、分页、统计和写入校验错误 | `suites/ckb-explorer-api-rpc-compatibility/reviews/fiber.md` |
