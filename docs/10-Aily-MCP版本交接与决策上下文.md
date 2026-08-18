# ITOM 飞书 Aily Agent + MCP Server 正式设计基线

> 状态：**正式设计基线；P0/P1 已完成；P2 文本与验签卡片按钮的真实同单端到端 UAT 均已通过；P3 飞书审批暂缓，IDC 可信 TLS 已部署并完成协议验收，安全/性能/恢复与当前版本真实角色正式 UAT 待完成**
> 确认日期：2026-07-29
> 权威语言：中文；英文镜像见 `docs/en/10-aily-mcp-handoff-and-decision-context.md`

## 1. 文档用途与状态口径

本文最初形成于现已封存的 `feature/aily-agent-mcp` 开发线；当前 `feature/AI-agent-version` 继承其 Aily + MCP 能力并作为 Web Agent 后续唯一开发线。本文记录已经由用户确认的目标、边界、工具范围、数据设计、阶段和验收标准。后续实现不得重新使用飞书服务台方案，也不得把 Aily、MCP 或飞书平台变成第二套 ITOM 业务系统。

本文同时记录目标契约与实际状态。当前分支已实现 P0 的协议/身份/消息底座、P1 的服务请求与 IT 需求入口，以及 P2 的受理/待确认打点、3 个闭环 MCP 工具、网页/MCP 共用确认语义、可靠用户消息和评价明细；P2 的真实对话闭环、机器人收件、普通用户同单文本闭环和验签卡片按钮闭环均已通过。当前通用通知出口也已把进入 `notifier.notify()` 的 ITOM 通知接入飞书文本可靠发件箱，复用既有身份映射、偏好过滤、幂等、重试和后台发送器；服务请求解决通知仍由专用交互卡片链路负责。P3 飞书审批按用户决定暂缓；IDC 已恢复并完成当前版本部署、公网协议探针及可信 TLS 协议验收，安全/性能/恢复和当前版本真实角色正式 UAT 仍待完成。能力状态必须继续以当前分支的真实模型、路由、测试和 Git 记录为准。

新会话开始前必须完整阅读 `AGENTS.md`、本文、`docs/03-PRD.md`、`docs/04-数据模型设计.md`、`docs/05-API契约与架构设计.md` 和 `docs/06-用户身份与组织模型设计.md`，并检查真实代码和 Git 状态。

## 2. 版本与工作区基线

| 对象 | 当前值 | 约束 |
|---|---|---|
| 冻结提交 | `f13f702` | 飞书服务台版本历史基线 |
| 历史标签 | `v1.0.0-feishu-helpdesk` | 不可重写，是恢复冻结版的权威引用 |
| 历史分支 | `release/feishu-helpdesk-v1` | 仅用于查看或维护历史版本 |
| 稳定分支 | `main` | 只接受用户确认的 Pull Request |
| 已封存开发分支 | `feature/aily-agent-mcp` | 保留 Aily + MCP 历史记录，不再接收提交 |
| 当前开发分支 | `feature/AI-agent-version` | 继承 Aily + MCP 能力的 Web Agent 唯一开发线 |
| 冻结工作区 | `/Users/xjun/Gitrepo/ITOM` | 不用于新版本开发 |
| 新版本工作区 | `/Users/xjun/Gitrepo/ITOM-Aily-MCP` | 所有新版本工作均在此进行 |

冻结提交已有后端测试与前端构建证据，但真实飞书服务台联调曾暴露权限、事件、消息会话和字段载荷差异。新版本不继承服务台链路，只复用这些失败经验形成的身份、幂等、重试、审计和真实 UAT 要求。

## 3. 已确认的产品目标

普通员工在飞书中向 Aily 描述诉求，Aily 只分流到两种普通用户可创建的业务单据：

1. **IT 服务请求**：已有 IT 能力的故障、申请、安装、配置、权限或使用协助。
2. **IT 需求**：新系统、新功能、新数据/集成或当前服务目录无法覆盖的新能力。

普通员工不能通过 Aily 创建 IT 事件或 IT 变更。

### 3.1 IT 服务请求

单个用户的软件打不开、电脑或打印机故障、网络访问异常、账号权限、安装配置和使用咨询均属于 `service_request`。Aily 必须实时查询 ITOM 中已上架且当前用户可申请的真实服务项，不得在提示词或 MCP 代码中维护固定服务清单。

目标交互：

1. 用户描述诉求。
2. MCP 搜索当前用户可申请的服务项；无法唯一判断时 Aily 展示候选项供用户选择。
3. MCP 返回所选服务项的当前表单版本。
4. Aily 从原始描述中预填可确定字段，只追问缺失的必填字段。
5. ITOM 统一执行类型、长度、选项、日期、人员/部门范围和权限校验。
6. Aily 展示规范化内容、SLA、实际流程、是否审批和预计支持组。
7. 用户确认后，MCP 携带确认凭证和幂等键创建 `Ticket(ticket_type=service_request)`。
8. ITOM 按服务项规则派单，IT 人员受理、处理并标记已解决。
9. ITOM 主动通知用户；用户确认解决后关闭，未解决则退回处理中。
10. 关闭后 Aily 请求评价，评价写回对应 ITOM 工单。

IT 人员“标记已解决”不等于关闭。服务请求必须形成“用户提出 → 建单 → 派单 → 受理 → 解决 → 通知 → 用户确认/重开 → 关闭 → 评价”的闭环。

### 3.2 IT 需求

IT 需求写入独立的 `Requirement` 实体，不是 `Ticket.ticket_type`。Aily 通过 MCP 读取 ITOM 的真实需求登记表单，收集标题、需求类型、业务域、描述及可选的期望日期、期望效果和业务价值，展示预览并在确认后登记，随后进入 ITOM 需求管理流程。

普通员工获得受限的“登记和查看本人需求”能力，不因此获得需求评估、指派、评分、转项目或关闭权限。

### 3.3 IT 事件

IT 事件专指网络、服务器、应用等影响范围较大的故障，只允许 IT 人员在 ITOM 中登记，或由监控系统使用专用集成身份和幂等接口创建。第一版不提供面向普通用户的 `create_incident` MCP 工具。

普通员工描述疑似大范围故障时，Aily 仍创建其本人的服务请求并标记“疑似大范围影响”；IT 人员确认后可关联已有事件或创建事件。普通用户和 Aily 不直接认定事件。

### 3.4 IT 员工网页分流不改变 Aily 边界（阶段 A/B/C 已实现）

IT 员工和系统管理员已获得网页“创建单据指引”轻量分流和跨单据关系能力；它只服务内部人员的 ITIL 判断，不对普通业务用户增加网页选择负担。Aily 中普通业务用户仍只创建服务请求，业务部门指定的 BDO 可登记 IT 需求；Aily 不执行服务请求→事件、服务请求/事件→问题、事件/问题→变更或需求→项目的转单。任何后续 MCP 范围扩展必须重新确认架构、权限、审计和用户体验。

### 3.5 ITOM 网页智能体（设计已确认；WA0 Task 1–8 已实现）

Task 5 会话运行时只接受可证明完整的 schema 标记版本快照、双语提示、合法能力/风险、健康兼容提供商及与活动行一致的最新发布版本；`enabled_capabilities` 和 `knowledge_scope` 必须是原始合法 list，缺失、`null` 或畸形值不归一化为空列表；未发布、停用、删除或不一致均失败关闭。创建会话在同一事务先取得与 Task 4 发布/撤回相同的 PostgreSQL 治理锁，再 `FOR UPDATE` 重载目标档案、验证、插入和提交，SQLite 保留相同调用顺序作确定性测试。普通消息保留期只从创建时捕获的版本读取，绝不由活动档案或 `expires_at` 推断：捕获为 0 时后续正值再发布也不保存正文，捕获为 1–90 时保持原决定和创建时 `expires_at`，但当前档案撤销或受众不一致时停止新正文。所有正文先递归脱敏。`fallback_available` 只反映认证用户既有、权限感知“创建单据指引”的安全载荷可用性，不代表 WA1；列表页码限制为 1–10,000。PostgreSQL 双会话竞争留待 Task 9 IDC 验收，本轮未执行。

Task 6 建立了通用 L3 动作边界：注册的固定 handler 必须实现 `authorize_preview/preview/authorize_record`。规范化输入若会被递归脱敏改变则统一拒绝，只有安全原值参与摘要和持久化。记录级预览授权先于元数据；预览使用独立、最终 rollback/close 的 Session，`authorize_preview/preview` 只接收独立 Session 内重新加载的 actor 上下文与 `ReadOnlyActionData` 门面。该门面不暴露 Session-like 属性，只接受显式、有界的 SQLAlchemy `Select` 标量投影，返回递归冻结的 `FrozenActionRecord`，并统一拒绝实体/关系结果、eager 结果、所有行锁、text/DML、过大 offset 与超限读取。PostgreSQL 在 handler 访问前设事务只读，ORM/DML 写入、textual SQL 事务语句及 flush/commit/rollback 均失败关闭，结果状态必须精确为 `prepared`。准备存在两条顺序化路径：已有 key 先无锁探测，再按 `AiAction → active 会话` 顺序锁定/重检并比较摘要；新动作则在 preview 后先锁定并刷新所属 active 会话，再无锁复查同 key，只有仍不存在才插入；命名唯一约束竞态会整笔 rollback 后以同样的 `AiAction → active 会话` 顺序恢复赢家。确认凭证只存 SHA-256、十分钟过期且一次消费；确认先 `FOR UPDATE` 锁动作，再锁定并刷新所属 active 会话，之后才沿 Task 4 governance/provider/profile 锁序完成 Task 5 的完整运行档案证明，确认会话捕获版本仍为当前发布版本且提供商仍启用、健康、兼容，随后仅通过 `ActionUnitOfWork.lock_one()/update_locked()`、`FrozenActionRecord` 快照和不暴露真实 ORM 身份的 `LockedActionRecord` 重算账号/角色/组权限/能力并调用记录级再授权。成功业务变更、`AiAction` 结果及通用审计在嵌套 savepoint 后由外层事务一次提交；处理器/审计失败只回滚 savepoint，保持动作行锁并把同一行提交为有界 `failed`，其 persistence 失败显式报错。处理器代码是受信任的进程内扩展代码，不是针对恶意 introspection/import hack 的沙箱；支持接口只保证正常用法下没有 Session 逃逸。取消、确认和重放均受所属用户和终态约束。SQLite 已覆盖确定性调用顺序、归档与 prepare/confirm 竞争、回滚结果、竞态注入和 savepoint，不构成 PostgreSQL 运行证明；Task 9 IDC 仍须留存只读预览、同/异载荷准备竞态、归档竞争以及确认失败等待者不重复执行 handler 的真实双会话证据。

Fix Round 4 已把 Task 6 支持接口进一步固定为可验证的查询与 mutation 范围：`ReadOnlyActionData` 递归校验完整 SQLAlchemy AST，只允许单表直接标量列、同表安全条件/排序和编译期有界分页，拒绝任意层级子查询/CTE/行锁、join/alias、实体/关系、聚合/窗口/函数、text/raw SQL、跨表引用及动态/负数/超限分页；`LockedActionRecord` 绑定精确签发 UoW、Session、外层事务和 savepoint，成功更新即消费旧句柄并返回合并快照的新句柄。伪造、跨范围、事务结束后或重复使用均失败关闭。此轮没有新增具体业务能力或数据库字段，PostgreSQL 双会话运行证明仍归 Task 9 IDC 验收。

Fix Round 5 封闭了 SQLAlchemy 不进入 visitor AST 的原始查询修饰入口：`_prefixes/_suffixes/_statement_hints/_hints` 任一非空即在执行前拒绝，字符串不解析、不设白名单；只读预览和 mutation `lock_one()` 共用此门禁。该修复不新增能力、字段或迁移，也不改变 Task 9 PostgreSQL/IDC 延后证据范围。

网页智能体采用双入口、统一能力内核：网页使用当前 ITOM 登录会话，Aily 保持现有 JWT/MCP 身份，两者只复用下层领域服务和业务约束。WA0 Task 1–8 已实现默认关闭的持久化与 `admin_ai` 权限基础、固定能力注册/请求级策略/递归脱敏、安全 OpenAI-compatible 模型网关、仅限 `admin_ai` 的提供商/四类固定档案管理 API、当前登录用户的会话 API、L3 预览/确认/取消通用动作边界，以及事件固定为 `meta|delta|message|action|error|done` 的受控 POST-SSE/工具循环。Task 7 Fix Round 1 把运行时收紧为标量 turn 快照和分段短事务：L1/L2 只取得只读门面与不可变 actor，L3 只产生服务端“待确认、未执行”预览，普通模型 prose 只作为 `advisory/not_executed`，请求幂等摘要使用服务端密钥 HMAC。Fix Round 2 进一步完成四项收口：提示泄漏检测使用 NFKC/casefold、清除 format/零宽字符并同时比较语义文本与去标点紧凑文本；最终事务先锁定刷新账号并锁后校验，再按会话/档案/占位顺序完成；L1/L2 改为专用有界执行器和合作式取消，满载在工具 Session 创建前拒绝；工具/数据库 deadline 与 worker/queue 均有安全配置范围和关系校验。断流/deadline 立即停止等待和发事件，但不承诺强杀任意 Python 同步线程，非合作式阻塞可能后台运行至返回且 Session 最终关闭；任意硬终止需要进程隔离。会话和动作均按数据库 `auth_user_id` 隔离，模型、提示词和客户端声明不是授权来源；每次工具调用按固定 code 重新授权。已有的提供商安全、档案发布、会话归属/保留、递归脱敏、审计原子性和失败关闭契约继续有效。管理员 UI 已由 Task 8 实现；具体业务处理器仍待 WA1+ 实现。普通业务用户网页智能体仍只处理本人服务请求，BDO 增加本人 IT 需求；IT 员工按实际权限和流程任务获得全模块指导及分阶段写操作。现有“创建单据指引”由真实权限计算可用路径，仍是模型不可用时的确定性降级。真实 PostgreSQL 双 Session、账号/会话/档案锁等待、非合作式线程与真实 ASGI 断流证据留待 Task 9。正式设计见 [`docs/superpowers/specs/2026-08-01-itom-web-agent-design.md`](superpowers/specs/2026-08-01-itom-web-agent-design.md)。

Task 7 Fix Round 3 在不扩大业务能力的前提下关闭四项运行时缺口：泄漏紧凑指纹在 NFKC/casefold 后只保留 Unicode `L*`/`N*`，因此 `M*`/`C*`/`Z*`/`P*`/`S*` 插入均不能切断匹配；工具调用先预留有界容量，再进行能力发现/重授权，满载不创建 Session、不查权限、不运行 handler；开始/幂等、能力发现、原生降级、Gateway 选择/审计、最终化和失败清理的同步数据库边界全部移出 async SSE 事件循环；最终化在 provider 返回后及锁齐账号/会话/档案/占位后、写 `completed`/commit 前合作式检查断流并在已观察取消时 rollback。该护栏不宣称强杀线程或消除真实 socket/锁调度的全部微小竞态，Task 9 仍须提供真实 PostgreSQL/ASGI 证据。

Task 7 Fix Round 4 修正前三项剩余审查结论且不进入 Task 8：泄漏紧凑路径改为先按原始 code point 只接纳 `L*`/`N*` 并排除命名/显式 Hangul `FILLER`，再 NFKC/casefold 和二次 `L*`/`N*` 过滤，防止原始 Mn/Sc/So 等兼容分解后“洗成”字母；视觉同形异码不在 WA0 完美检测承诺内。所有 assistant 同步 DB offload 统一使用有界执行器，消息流鉴权只返回账号 ID 标量并在 `StreamingResponse` 前关闭 worker Session，Gateway 选择/审计也不使用默认 executor。`stream_turn()` 入口只生成一个 monotonic deadline，fallback/start/provider/Gateway/DB/tool/finalization 共享剩余预算，并预留最多 250ms（25%）做失败占位清理；工具、provider、statement timeout 取自身上限与剩余预算的较小值。Round 5 进一步明确该预算严格覆盖 pre-commit 工作，而权威 commit 后收尾以终态一致性优先。真实 PostgreSQL 锁等待、双 Session 幂等和真实 ASGI 断流仍按 Task 9 留证。

Task 7 Fix Round 5 关闭最后三项独立审查缺口且仍不进入 Task 8：生产 Provider DNS 改为专用有界 DNS/IO executor 内同步 `socket.getaddrinfo`，容量准入与等待共享请求 absolute deadline，禁止 `loop.getaddrinfo`、`asyncio.to_thread` 和默认 executor；SSRF、DNS rebinding 与 TLS 原主机绑定保持不变。断流取消审计经既有有界 DB executor 非阻塞 reserve 后后台 best effort 执行，取消立即传播，满载不创建 Session，异常只产生脱敏本地告警；正常成功/可处理错误仍等待审计持久化。单一 absolute deadline 严格覆盖所有 pre-commit 工作；最终锁齐且 deadline 前最后检查通过后进入权威 commit，调用方会等待 commit 与 Session 收尾以保持 durable `completed` 和客户端终态一致，因此该收尾可能小幅越过 deadline，不再把整个返回路径描述为绝对硬上限。真实 PostgreSQL commit/断流临界竞态、真实 ASGI socket 和双 Session 幂等继续留 Task 9。

Task 7A 在不扩大 WA0 或进入 Task 8 的前提下修复最终化权威：线程安全 durable-success 只在 `db.commit()` 成功返回后设置；之后的 Session close 异常只记录脱敏异常类型，不重查数据库猜测事务结果，也不能把 durable `completed` 改报 `error → done`。commit 已开始后观察到断流时取消语义优先且不再发送后续 SSE 终态，即使清理同时失败；commit 自身失败不设置 durable-success，继续 rollback、失败占位清理和安全错误路径。真实 PostgreSQL commit/断流临界竞态与真实 ASGI socket 证据仍由 Task 9 留存。

Task 8 已完成 WA0 前端消费层：业务门户与内部工作台顶栏共享全局启动器，响应式抽屉调用既有 bootstrap/会话/POST-SSE/动作 API；严格有界解析器只接受固定事件并拒绝未知、畸形、截断、错误后成功及超限数据。页面上下文只来自路由/标签/显式 GLID 白名单，不抓取 DOM；输出和服务端预览只按文本渲染。L3 卡片覆盖确认、取消、过期、冲突、失败和成功终态，仅服务端确认结果 `succeeded` 为权威成功，确认 Token 不展示且终态清除。系统管理新增 `admin_ai` 守卫的提供商、四类固定档案、健康、用量和动作审计五页签控制台，密钥只写不回填。该任务未修改后端、持久化模型、具体领域能力或部署；Task 9 仍负责真实 PostgreSQL/ASGI/IDC 角色与动作证据，WA1+ 仍负责具体业务 capability。

独立 Task 8B 已修复 Task 8 前端与既有 L3 后端之间的确认桥，且不重开 Task 8 五轮审查、不扩大 WA0。严格状态机现精确接受启动前 `error → done(error)`、元数据后 `meta → error → done(error)`，以及 `advisory` 或 `server_preview` 的 `meta → message → done(replay)`；错误出现在 delta/action/message 后、错误终态混入成功载荷、重放预览夹带 action/delta/Token 或其他畸形交叉序列均失败关闭。重放的服务端预览只作信息展示，不产生卡片或可执行含义。首次同属主 L3 action SSE 通过服务端固定窄投影交付一次原始确认 Token 和安全预览；通用脱敏规则不变，Token 仍只存 SHA-256，且不进入模型、message、持久化、日志、审计或 REST 响应。同一属主恰好一次合法确认成功，重复、跨属主、过期、取消、脱敏占位与畸形凭证全部失败关闭。Task 8B 未新增字段、迁移、业务 capability、部署或 IDC 证据；Task 9 延后范围不变。

Task 8C 修复 WA0 确认传输/状态边界而不新增业务 capability、迁移、部署或 Aily/MCP 变更。`AiAction.expires_at` 仍为 naive UTC 存储，但公开 `confirmation_expires_at` 和 action SSE `expires_at` 统一输出带 `Z` 的 RFC 3339 UTC；浏览器拒绝无时区日期。live/replay `server_preview.action_id` 都按相同 ULID 语法失败关闭。确认在既有属主、凭证、期限、会话/档案/能力重授权完成后，先提交内部非可确认、非可取消且不可重试的 `executing` 声明；只有成功声明后才调用 handler。已知 handler/审计失败仍可写 `failed`，而声明后的 handler 或终态持久化不确定时保留非确认态并返回安全 outcome-unknown，绝不恢复 `prepared`、再发 Token 或未经成功事务就报告业务成功。成功领域变更、`succeeded` 结果和审计仍同事务；Task 9 的真实 PostgreSQL/ASGI/IDC 证据仍待完成。

Task 8C Round 1 闭合三项审查结论：含有效原始 Token 的 live action SSE 必须以非空、可解析、显式 `Z` 期限绑定确认，缺失/`null`/无偏移/畸形期限在创建卡片前失败关闭；Token 缺失的 action 仍仅为不可确认信息。SQLite 在 handler savepoint 前建立 claim 后外层写事务，因此 success terminal commit 失败时领域写、成功结果和审计回滚，数据库保留不可重试 `executing`；claim commit 失败则 handler 不启动且原 `prepared` Token 可供诚实重试。浏览器收到 `AI_ACTION_OUTCOME_UNKNOWN` 时只显示“结果待核实”、清除 Token 并停用确认/取消，绝不显示“尚未执行”或成功断言。Task 9 真实 PostgreSQL/ASGI/IDC 证据仍待完成。

## 4. 已确认的架构

采用**方案 A：MCP Server 内嵌现有 FastAPI 后端**。

```text
飞书用户 ⇄ Aily Agent
                │  HTTPStreaming / x-aily-jwt
                ▼
   IDC Ingress :30443 /mcp/
                ▼
       FastAPI 内嵌 MCP Server
                ▼
       ITOM 领域服务 / RBAC / 流程 / 审计
                ▼
              PostgreSQL

ITOM 领域事件 → 可靠通知发件箱 → Aily 机器人飞书消息 → 用户
用户回复 → Aily → MCP → ITOM 确认、重开或评价
```

IDC Kubernetes 是唯一生产交付和最终验收环境，当前公网根地址为 `https://itom.snnc.cc:30443`，同时承载 ITOM 前端、`/api`、飞书 OAuth 回调和 `/mcp/`。管理员通过 `public_base_url` 维护该根地址并由页面生成各入口。当前 IDC 前端仅限节点 01/02：节点 02 的构建污点只由 ITOM 前端显式容忍，两个前端副本以必需主机反亲和分布；节点 03 不再承载 ITOM 前端。前端滚动更新采用 `maxSurge: 0` 与 `maxUnavailable: 1`，在仅有节点 01/02 可运行时先释放旧副本占用的节点，再创建替换副本，避免默认超额副本与强制反亲和导致发布卡住。后端固定节点 02，数据库 StatefulSet/PVC 与备份 Job 不属于应用重部署范围。经批准的非数据库应用恢复使用 `SKIP_DATABASE=1 ./k8s-deploy.sh`，明确跳过 PostgreSQL 清单 apply 与 StatefulSet 等待，不删除、重启或重新调度数据库 Pod/PVC；涉及结构迁移的版本不得使用该模式。仓库 Compose 仅可在确认 `feature-local` 路线或另行批准临时隔离排障后启动，且不得包含生产数据、凭据、Secret、OAuth/Aily 应用、回调或集成；本地业务 UAT 只证明候选版本，不能替代 IDC 正式验收，ngrok 仍须另行批准。

提交前可按指定基线运行 `scripts/fast-check.sh` 获得后端、前端或文档范围的快速反馈；共享/未知路径失败安全地升级为全量检查。提交仍先由 `.github/workflows/quality-gate.yml` 在隔离测试数据库上完成后端完整回归、前端契约测试与生产构建、部署文件及中英文文档交付检查。通过后，`push-images.sh` 从干净提交构建 Git SHA 不可变 linux/amd64 镜像并推送 Harbor；默认全量，经范围复核可只发布 backend 或 frontend，PostgreSQL 镜像仅显式请求时同步。组件级 `k8s-deploy.sh` 强制跳过数据库并保留共享资源和未选中 Deployment；全量和组件模式都严格验证 rollout、实际镜像、内外健康链路和 MCP `initialize`。真实 Aily、飞书回调、身份、权限和业务流程只在 IDC 验收。

所有编码任务在修改前先确认 `production-fix|feature-local|code-candidate` 路线，并使用 `scripts/task-lifecycle.py --track` 建立生命周期证据。生产修复以 IDC 真实事实为基线；新功能可在不含任何生产数据、凭据、Secret、OAuth/Aily 应用或回调的本地隔离 Docker 环境形成候选；代码候选不启动应用。定向目标验证通过后才同步正式文档和提交；冻结候选只运行一次完整 CI。任何 IDC 写入都必须在 CI 后另行展示精确提交、不可变标签、变更对象、数据影响、中断、回滚及验收方案，并记录用户 `approve-idc` 明确批准；本地候选和 CI 均不构成生产交付。

### 4.1 职责边界

| 组件 | 负责 | 禁止 |
|---|---|---|
| Aily | 意图理解、候选呈现、字段追问、预览、确认、结果解释 | 编造服务项/SLA/流程、保存业务状态、自行授权 |
| MCP Server | 工具发现、认证、身份映射、参数规范化、调用领域服务、结构化错误和审计 | 直接写业务表、绕过 RBAC/状态机、暴露密钥或通用 HTTP/SQL |
| ITOM | 服务目录、表单、SLA、派单、流程、权限、单据、评价和审计的唯一事实来源 | 把授权或最终业务状态交给大模型 |
| 飞书平台 | Aily 会话、身份与组织、机器人消息、静态知识、后续审批 | 将外部载荷直接视为可信业务事实 |

网页智能体新增网页会话适配器、模型网关、能力注册、编排和安全知识检索，但不改变上述职责：网页身份与 Aily 身份隔离，模型不直接写表，所有结果仍由 ITOM 领域服务、RBAC、数据范围、流程、确认、幂等和审计决定。

静态 IT 知识由 Aily 对接飞书知识库，首期 MCP 不重复提供知识检索。飞书审批保留在第三阶段接入，审批结果仍由 ITOM 流程校验和落库。

### 4.2 主动通知边界

MCP 是 Aily 主动调用 ITOM 的工具通道，后台工单状态变化不会仅因 MCP 存在而自动唤醒 Aily。因此主动通知使用可靠发件箱和飞书机器人消息 API；用户回复后再由 Aily 调 MCP 完成确认、重开和评价。新版本不使用飞书服务台。

## 5. 服务目录、表单、流程和派单

### 5.1 服务项

服务项在现有名称、目录、说明、SLA、负责人和服务对象之外，目标增加：

- 搜索关键词、同义表达、典型场景和排除场景；
- 当前启用表单版本；
- 绑定流程定义；
- 派单规则；
- 是否需要审批和默认优先级规则。

### 5.2 动态表单

表单必须版本化。P1 当前支持文本、长文本、单选、多选、数字、日期/日期时间、人员、部门和布尔项；附件及资产/配置项字段在后续阶段扩展。字段可配置必填、长度/数值范围、选项、日期范围、人员/部门范围、条件显示/必填和帮助文字。

工单保存表单版本、答案及定义快照；服务项后续改版不得改变历史工单解释。网页创建和 MCP 创建共用同一表单解析与校验服务。

### 5.3 流程与状态

服务项直接绑定流程，而不是仅按 `ticket_type` 选择流程。工单主状态保持：

```text
new → processing → resolved → closed
                    └─ 用户未解决 → processing
```

用户可见阶段为“已提交 → 已派单 → 已受理 → 处理中 → 待用户确认 → 已关闭 → 已评价”。派单、受理和评价用时间字段/事件表达，不强行扩展为全部主状态。

响应 SLA 以实际受理时间为准，解决 SLA 以进入 `resolved` 为准；等待用户确认不继续消耗解决 SLA。重开次数必须审计。

### 5.4 派单

派单顺序固定为：

1. 服务项专属规则；
2. 服务目录默认支持组；
3. 全局 IT 服务兜底组；
4. 仍无可用人员时保留工单并告警，禁止静默丢单。

组内首期采用可审计轮询，只选择在岗、启用且属于目标组的人员；允许有权限的 IT 人员改派。必须记录命中的规则、派单来源、派单时间和实际受理时间。

## 6. 身份、安全、确认与审计

1. Aily 通过 `x-aily-jwt` 传递身份上下文；首次注册时只允许启用状态下、Origin 命中的只读协议发现，因为 `identityJWTSecret` 在创建完成后才展示。任何工具执行仍须校验 HS256 签名、有效期、必要字段和白名单；用户字段兼容文档中的 `user_id` 与真实请求中的 `feishu_open_id`。
2. 外部身份按提供方、租户、应用、标识类型和外部 ID 映射到活动 ITOM 账号；验签成功但尚未批准的身份只登记为 `pending` 候选，不自动授权。
3. 不假设不同飞书应用的 `open_id` 相同；OAuth 应用和 Aily 机器人身份分别保存映射。
4. 所有用户级工具使用映射后的 `AuthUser` 执行现有 RBAC、数据范围和流程校验。
5. 写工具采用“预览 → 用户确认 → 确认凭证 + 幂等键提交”；凭证绑定用户、工具、规范化参数摘要和过期时间。
6. 工具审计记录用户、租户、Aily Agent、工具、调用 ID、参数摘要、结果、业务对象、耗时和时间，不记录密钥或完整敏感载荷。
7. App Secret、MCP JWT Secret 和机器人凭据不得进入 URL、提示词、工具结果、日志、提交或测试夹具。

## 7. 首期 MCP 工具契约

### 7.1 服务请求

- `search_service_items`
- `get_service_item_form`
- `prepare_service_request`
- `submit_service_request`
- `get_my_service_request`
- `list_my_service_requests`

以上 6 个服务请求工具已在 P1 实现；以下 3 个闭环工具在 P2 实现：

- `get_my_pending_confirmations`
- `confirm_service_request_resolution`
- `rate_service_request`

### 7.2 IT 需求

- `get_it_requirement_form`
- `prepare_it_requirement`
- `register_it_requirement`
- `get_my_it_requirement`
- `list_my_it_requirements`

首期不开放 `create_incident`、`create_change`、任意状态流转、改派/审批/处理步骤、通用 SQL、数据库和任意 HTTP 工具。IT 人员继续在 ITOM 网页处理工单与需求。

## 8. 目标数据变更

### 8.1 删除的飞书服务台数据

代码模型已删除 `feishu_helpdesk_handoff`、`feishu_helpdesk_intake`、`feishu_helpdesk_sync_event`、`feishu_helpdesk_outbox` 及 `feishu_config` 中全部 Helpdesk 字段。用户确认当前无有价值的生产历史数据，不做迁移或归档；存量 PostgreSQL 使用 `python -m app.scripts.migrate_aily_mcp` 先预览，追加 `--confirm` 后执行永久清理。

### 8.2 新增支撑模型

- `external_identity`：多应用、多租户外部身份映射；
- `aily_integration_config`：Aily/MCP 与机器人消息配置，密钥加密保存；
- `mcp_tool_call`：工具调用审计；
- `mcp_operation_intent`：写操作预览、确认凭证、幂等与执行结果。

扩展 `notification_outbox`，增加接收人、幂等键、重试计数、下次重试、提供方消息 ID、错误摘要和发送时间。

### 8.3 新增 ITSM 模型

- `service_item_form_version`：服务项表单版本和 JSON Schema [P1 已实现]；
- `service_dispatch_rule`：服务项/目录/全局派单规则；P1 的受理派单规则与 M93 的实施交付派单规则通过 `dispatch_stage=acceptance|implementation` 隔离 [P1/M93 已实现]；
- `ticket_satisfaction`：评分、标签、意见、来源和审计时间，每张工单一条有效评价 [P2 已实现]。

P1 扩展 `service_item` 保存搜索元数据、活动表单、绑定流程和默认优先级；派单规则通过 `scope_type + scope_id + dispatch_stage` 分层解析。P1 扩展 `ticket` 保存表单答案/快照、派单事实和疑似大范围影响标记；M93 追加实施交付人、命中的实施规则、派单来源、选择人及选择时间，均为只读审计事实。P2 在首次进入处理中时写 `accepted_at`，在进入最终用户确认节点时从流程任务 SLA 写 `confirmation_due_at`。`ticket.satisfaction` 由有效评价记录同步回填，兼容既有统计。

## 9. 飞书服务台移除范围

P0 已删除服务台路由、服务、后台扫描任务、事件订阅、模型、配置、管理界面、前端交接页面/路由、服务请求/需求页面中的 handoff 逻辑和专用测试；现行文档只保留冻结基线与显式清理说明。

保留飞书 OAuth、工作台免登、组织同步、通讯录、通用 `FeishuClient` 和机器人消息能力。冻结版仍可从标签 `v1.0.0-feishu-helpdesk` 恢复。

## 10. 分阶段实施与验收

### 阶段 0：协议与基础链路

**当前状态：代码、自动化验证、真实 Aily 租户经 ngrok 调用 `/mcp/` 的身份链路及机器人真实收件验证均已完成。**

- 清除 Helpdesk 运行路径和数据模型；
- 内嵌 MCP，Nginx 暴露 `/mcp`；
- 建立 Aily JWT、身份映射、工具审计和机器人主动消息；
- 本地 Docker + ngrok 真实验证。

已验证：Aily 自定义 MCP 已按 Streamable HTTP 指向 ngrok 暴露、带末尾斜杠的 `/mcp/`；实测省略末尾斜杠会在 Aily 保存阶段提示配置校验失败。P0 智能体配置已发布给当前测试账号；首次注册的协议发现可在尚未取得 Aily JWT Secret 时通过，但 `tools/call` 仍拒绝缺失 JWT、未映射用户、错误租户和错误 Origin。真实 Aily JWT 已完成签名、租户、Agent 和 `feishu_open_id` 校验，待确认身份可由 ITOM 管理员映射并启用；`get_current_user_context` 能映射正确账号并写脱敏审计，最终 Aily 回复只包含验证结果、账号状态和可读账号名，不返回 open_id、tenant_id、agent_id 或 ITOM 内部主键。机器人凭据、可靠发件箱、幂等键、飞书发送结果及普通用户客户端真实收件均已验证；仓库无 Helpdesk 运行入口。

2026-07-29 本地验收快照：后端完整回归 `260 passed`；P0 MCP 定向测试 `8 passed`；前端生产镜像构建成功；Docker Compose 的数据库、后端和 8180 前端均正常；模型元数据为 78 张表，数据库中 Helpdesk 表和字段均为 `NONE`；本地及 ngrok 公网 `/api/health` 返回 HTTP 200；真实 Aily 预览调用 `/mcp` 完成身份映射并通过无系统标识泄露检查。当前身份映射仅用于本地开发联调，正式环境必须重新绑定真实 ITOM 账号。该快照不替代 P1–P3 多角色业务闭环和 IDC 验收。

2026-07-29 飞书侧清理确认：管理员已在开放平台删除旧服务台事件订阅和卡片回调并发布新应用版本。后端最后一次收到旧 `/api/integrations/feishu/helpdesk/events` 请求的时间为 21:59:24（该已移除路由按预期返回 404）；截至 22:22:20 未再出现旧 `/helpdesk/events` 或 `/helpdesk/card-callback` 请求。同期 `/mcp/` 调用正常，前端代理 `/api/health` 返回成功，说明外部清理未影响 Aily MCP 和现有 ITOM 运行链路；飞书登录、通讯录和审批不在本次删除范围，仍按各自阶段验收。

### 阶段 1：服务请求与需求登记

**当前状态：代码、自动化 MCP/API 验收、前端生产构建，以及真实 Aily 的服务请求和 IT 需求“取表单 → 预览 → 明确确认 → 写入 → 本人查询”UAT 均已完成。**

- 动态表单、服务项搜索、流程/派单绑定；
- 服务请求搜索、取表单、预览、确认和提交；
- IT 需求表单、预览、登记和本人查询；
- 普通用户不能创建 IT 事件。

2026-07-29 P1 本地验收快照：后端完整回归 `267 passed`，P1 Streamable HTTP 定向测试 `5 passed`，前端生产构建成功；Docker Compose 增量迁移成功，模型元数据和 PostgreSQL 均为 80 张表，32 个现有服务项均已绑定已发布表单和 `sr_flow`，8180 本地及 ngrok 公网 `/api/health` 均返回 HTTP 200。Aily 重新保存规范 `/mcp/` 地址后发现 12 个工具，并真实调用服务项搜索、表单读取、预览和确认提交；测试单 `TK-202607-0001` 以 `service_request`、P3、待受理状态唯一创建，表单版本/定义快照及运行中流程实例均已保存。当前无显式派单规则，因此该单按设计进入未分配的人工兜底队列。管理员随后配置有效业务域 `bsz_sc`（供应链服务域），Aily 再次读取真实需求表单后仅返回该域，并完成 IT 需求预览和明确确认；`RQ-202607-0001` 以“功能”类型、`evaluating`（评估中）状态唯一写入 `Requirement`，启动运行中的 `requirement_flow`，首个“需求评审（业务域负责人）”任务已生成并指派。创建审计和已消费的幂等意图均可反查，同标题 `ticket` 数为 0；`get_my_it_requirement` 再次返回相同标题、业务域和状态。由此确认普通用户需求不会误落为 `service_request`，P1 两类入口的真实 Aily 写入 UAT 均已完成。

验收：结果来自真实服务目录；可申请范围和表单校验生效；重复提交只产生一张单据；服务请求进入正确流程并派单；需求进入需求模块。

2026-07-29 P1 自动化快照：完整后端回归 `267 passed`；P1 真实 Streamable HTTP MCP 契约测试 `5 passed`，覆盖工具发现、服务对象隔离、网页/MCP 共用动态表单校验、短期确认凭证、重复提交、流程绑定、派单、需求流程和跨用户拒绝；前端 TypeScript + Vite 生产镜像构建成功；模型元数据为 80 张表。该快照与上述真实 Aily 证据互补，但不替代 P2 多角色闭环或 IDC 最终验收。

### 阶段 2：服务闭环

**当前状态：P2 文本交互闭环已完成代码、自动化、前端构建、本地 Docker/ngrok、真实 Aily 多角色对话、普通用户身份、机器人真实收件及普通用户同单端到端验收。P2.1 已确认改用飞书新版 `card.action.trigger` 验签回调：普通对话仍只走 MCP，卡片按钮作为唯一例外由 ITOM 校验签名和点击人身份后调用同一领域服务。签名/解密、未解决原因表单、跨用户拒绝、重开、关闭、评价和幂等已纳入自动化；真实验签按钮闭环已通过。**

- `accepted_at` 与 `confirmation_due_at` 已由实际流程节点打点；IT 完成只进入 `resolved`，提交人确认后才关闭；
- 已实现 `get_my_pending_confirmations`、`confirm_service_request_resolution`、`rate_service_request`，全部要求本人范围和明确工单编号；
- 未解决携带原因回退最近处理节点；旧任务软删除保留审计，再次解决以本轮最新有效处理说明刷新用户可见 `solution`；网页与 MCP 语义一致，管理员不能代提交人确认；
- 受理、解决、重开、关闭和评价写可靠 Aily 发件箱；确认期限使用到 80% 时每周期提醒一次；未启用机器人时保留待发记录，不消耗重试；
- 机器人凭据、Verification Token 与 Encrypt Key 同时就绪后，解决/提醒改发“已解决并关闭、仍未解决”交互卡片，关闭改发 1–5 星卡片；未就绪时安全回退纯文本。“仍未解决”先展开必填原因表单，所有卡片动作经飞书验签、点击人映射和 ITOM 同一领域规则；
- `ticket_satisfaction` 每单一条有效记录，保存评分、标签、意见、来源和审计，兼容星级同步到工单；
- 直接确认/重开/评价使用同事务幂等意图，相同载荷安全重放，同键不同载荷拒绝。

2026-07-29 P2 自动化快照：完整后端回归 `270 passed`；P1+P2 定向回归 `8 passed`（其中 P2 `3 passed`），覆盖工具发现、受理/解决时间、待确认列表、80% 期限提醒幂等、跨用户拒绝、明确工单重开、流程回退与最新解决说明、重复调用、关闭、评价新增/更新、同键冲突、网页/MCP 同语义、管理员不可代确认、发件箱事件数量及内部信息不外发；前端 TypeScript + Vite 生产镜像构建成功；本地 Docker 模型元数据和 PostgreSQL 均为 81 张表并包含 `ticket_satisfaction`，8180 本地及 ngrok 公网健康检查通过，公网 `/mcp/` 返回 15 个工具。

2026-07-29 P2 真实 Aily 对话 UAT：Aily 重新读取并展示 15 个工具；`get_my_pending_confirmations` 先返回空列表，在 IT 角色通过应用流程入口完成受理和解决后，真实返回 `TK-202607-0001`、解决说明和确认期限。用户随后经 Aily 调 `confirm_service_request_resolution(resolved=false)` 将工单重开为 `processing`、重开次数 1；IT 再处理后，经 Aily 确认已解决并关闭，最后由 `rate_service_request` 保存 5 星、“响应及时/解决专业”和文字意见。ITOM 最终记录为 `closed`、一条 `ticket_satisfaction(source=aily)`，受理/解决/重开/关闭/评价事件均进入可靠发件箱。回归单 `TK-202607-0002` 进一步验证重开前“第一轮处理”已被排除，Aily 只返回“第二轮处理：补充内网路由策略，内部系统访问恢复”，随后关闭和评价成功。IT 处理角色为 `it_op1`。

同日已将真实 Aily 外部身份从本地 `admin` 改绑到普通用户 `xiongjun`；刷新智能体后，`get_current_user_context` 真实返回可读账号名“熊军”和活动状态，ITOM 持久化映射、最近使用时间与 MCP `OK` 审计一致。该身份的接收标识为 Aily 智能体作用域 `open_id`，不假定与 ITOM 登录应用的 `open_id` 相同。机器人 `message_enabled=false` 且尚未配置与该身份作用域匹配的应用凭据，因此主动消息仍保持 `pending`，未宣称已真实送达；最终验收仍需完成机器人凭据、收件身份及消息送达验证。

2026-07-30 主动消息联调：已配置 Aily 绑定飞书应用的机器人凭据，并通过飞书租户令牌接口验证；启用前将 15 条历史未发送 P2 UAT 消息软删除并写审计，避免集中误发。随后启用主动消息，向 `xiongjun` 对应活动身份发送唯一一条受控测试消息；飞书接口返回消息 ID，ITOM 发件箱记录为 `sent`、最近测试状态为 `success` 且无脱敏错误，用户已确认飞书客户端实际收到消息。机器人真实收件验收通过；该证据不替代普通用户同一张业务工单从创建到评价的最终闭环验收。

2026-07-30 普通用户同单闭环：`xiongjun` 通过真实 Aily 创建 `TK-202607-0003`（局域网-无线，MacBook 无法连接公司 Wi-Fi，P2）。IT 人员完成受理、处理和解决后，`ticket.accepted`、`ticket.resolved` 均由机器人实际送达；普通用户随后在 Aily 确认解决关闭并提交 5 星评价。ITOM 最终状态为 `closed`，有效评价 `score=5/source=aily`，MCP 审计记录 `confirm_service_request_resolution` 与 `rate_service_request` 均成功。由此 P2 文本交互的普通用户端到端验收完成。

2026-07-30 P2.1 首次方案及否决证据：服务端曾按 Aily `trigger_skill` 契约生成按钮，线上 Skill `1.0.2` 和真实 `skill_*` 已配置，并向 `TK-202607-0004` 发送双按钮卡片。`xiongjun` 点击“仍未解决”后，Aily 没有追问原因。进一步创建 Workflow 并检查 ngrok/后端真实请求，确认 Workflow 自定义 MCP 请求既没有 `x-aily-jwt`，调试态也没有可授权的用户头；请求被 ITOM 正确拒绝为 403，而 Workflow 仍可能生成原始函数调用文本或错误成功文案。该路径不能证明点击人身份，故不得放宽 MCP JWT，也不再作为卡片写操作方案。Workflow 草稿未发布，旧 Skill 可保留作历史证据但不属于运行时依赖。

2026-07-30 P2.1 正式替代方案：仅卡片按钮改走飞书开放平台新版 `card.action.trigger` Webhook，地址为 `/api/integrations/feishu/card-actions`。服务端对业务回调以原始正文完成 SHA-256 验签和 5 分钟时效校验，支持 AES-256-CBC/PKCS#7 解密，随后校验 Verification Token、Bot App ID、租户白名单及点击人的显式外部身份映射。真实配置证明飞书保存 Webhook 地址时发送无签名头的加密 `url_verification`；该只读 challenge 只在成功解密、类型精确匹配且 Verification Token 正确时返回，绝不放宽 `card.action.trigger` 验签。“仍未解决”第一次点击返回必填原因表单，提交后与关闭/1–5 星评价一样调用既有 `service_request_closure`；RBAC、本人范围、流程状态、幂等和审计均未绕过。配置模型以两个加密字段替代 `card_action_skill_id`，管理 API 仅回显配置状态。定向自动化已覆盖无签名加密 challenge、业务回调缺失/无效签名、跨用户拒绝、缺失原因、重开及重放、关闭及重放、评价来源。
2026-07-30 P2.1 按钮联调修复：真实 Aily 卡片点击请求带有完整签名，但 `X-Lark-Request-Timestamp` 使用了带时区和 Go 单调时钟后缀的时间字符串；此前仅接受 Unix 数字导致 ITOM 返回 `FEISHU_CARD_SIGNATURE_INVALID`，飞书客户端显示 `200671`。现已兼容该实际格式并继续执行 5 分钟时效校验，签名计算和业务验签边界未放宽；新增回归覆盖该时间格式。
2026-07-30 P2.1 租户标识联调修复：时间戳修复后，真实“仍未解决”点击已进入 ITOM 并通过签名、Bot App 和回调内租户一致性校验，但业务 Toast 显示“卡片回调租户尚未获 ITOM 授权”。脱敏诊断确认回调 `tenant_key` 与 Aily JWT `tenant_id` 不同，而同一点击人的 `open_id` 能唯一映射到已授权 Aily 租户下的活动账号 `xiongjun`；这证明两个字段属于不同标识命名空间。服务端不再要求二者字符串相等：回调租户未直接命中白名单时，必须由点击人标识在允许的 Agent/Bot App 范围内唯一锚定到已授权 Aily 租户的活动 ITOM 身份。签名、Verification Token、Bot App、回调内租户一致性、本人范围、RBAC、状态、幂等与审计均保持不变；未知跨命名空间点击人仍拒绝。定向回归已覆盖不同 `tenant_key` 的合法映射和未映射拒绝。
2026-07-30 P2.1 响应协议联调修复：租户标识修复后，真实点击已完成 ITOM 授权和业务处理，后端在 3 秒内返回 HTTP 200 与完整原因表单，但飞书客户端显示 `200672`。ngrok 原始响应证明服务端把卡片 JSON 直接放在 `card` 字段；飞书新版 `card.action.trigger` 的立即更新响应要求 `card.type=raw` 且完整卡片位于 `card.data`。现已统一包装原因表单、重开结果、关闭结果和评价结果，并新增响应结构断言；业务错误仍只返回 Toast、保留原卡片。定向测试 `5 passed`、全量后端测试 `276 passed`；部署后经 ngrok 发送加密、验签、跨租户命名空间但合法点击人映射的只读原因表单探针，1.392 秒返回 HTTP 200，且 `card.type=raw`、`card.data`、必填输入框和 `form_submit` 均通过断言，`TK-202607-0005` 当时仍为 `resolved/reopen_count=0`。

2026-07-30 P2.1 最终真实按钮 UAT：普通用户 `xiongjun` 在飞书客户端对 `TK-202607-0005` 完成“仍未解决 → 填写原因并重新打开 → IT 再次解决 → 已解决并关闭 → 5 星评价”。用户确认前端全链路已测通；ITOM 数据复核为 `status=closed`、`reopen_count=1`、`ticket.satisfaction=5`，且唯一有效评价明细为 `score=5/source=feishu_card`。至此 P2.1 真实验签卡片闭环通过。

2026-07-30 IDC 平台链路快照：当前 Aily + MCP 镜像已通过仓库 Kubernetes 流程部署，后端 1/1、前端 2/2 副本可用；公网 `https://itom.snnc.cc:30443/mcp/` 的真实 MCP `initialize` 返回 HTTP 200，飞书开放平台向 `https://itom.snnc.cc:30443/api/integrations/feishu/card-actions` 发送的加密 `url_verification` challenge 也返回 HTTP 200，配置已成功保存并发布。该证据证明 IDC 公网路由、MCP 协议入口和卡片回调 challenge 链路可用，不等同于正式发布验收；当前公网证书仍需替换为受信 CA 证书，安全、性能、故障恢复和 IDC 真实角色业务 UAT 仍须单独完成。

2026-07-30 公网根地址配置回归：后端完整测试 `277 passed`；`public_base_url` 定向契约测试 `1 passed`，覆盖末尾斜杠规范化、路径/查询参数/片段/URL 凭据/非法协议/越界端口拒绝、失败不覆盖已保存值和清空配置；前端 linux/amd64 生产镜像完成 `tsc --noEmit` 与 Vite 构建。`git diff --check`、Kubernetes YAML 解析和部署脚本语法检查均通过。

2026-07-31 本次问题复核与修复：Dashboard 的 `/api/dashboard` 原先聚合人员积分时遗漏 `contribution_bucket=team_contribution`，因此会把项目经理里程碑等 `role_result` 流水与团队贡献相加；团队总览已使用正确分桶，造成两页显示不一致。已在 Dashboard 查询补齐同一分桶条件，并在 `test_activity_points_exclude_role_result_entries` 增加 Dashboard 回归断言，验证 `role_result=50`、`team_contribution=7` 时两处均只显示 7。该修复不改数据模型、不改存量流水。

同日 IDC 回调复核：`https://itom.snnc.cc:30443/api/health` 在标准证书校验下因 `unable to get local issuer certificate` 失败，关闭证书校验后返回 HTTP 200；Backend/Frontend Ingress 日志在复核窗口内没有收到 `card-actions` POST，当前 IDC 数据库也没有旧截图中的 `TK-202607-0004/0005`。因此 Aily 显示的 `200080` 当前不能归因于 `service_request_closure` 业务逻辑；首先必须为 `itom.snnc.cc:30443` 配置公网受信 CA 证书，再用当前 IDC 新建工单生成的新卡片复验。旧 `TK-202607-0005` 的按钮闭环仍是历史 UAT 证据，不代表当前 IDC 卡片链路已恢复。

2026-08-06 通知身份修复：排查 `TK-202608-0036` 发现站内通知已写入，但旧版通用通知出口因为熊军只有 ITOM 登录应用的 `AuthUser.external_id`、没有 Aily 机器人应用的已验证身份映射而静默跳过飞书发件箱。现改为在 Aily 已启用时按 ITOM 账号入队：身份未映射时保留 `pending`，写入脱敏原因 `AILY_IDENTITY_NOT_MAPPED`，后台发送前重新解析身份，映射补齐后自动投递；身份等待不消耗重试次数，也不向未知收件人发送。飞书 OAuth 的 `tenant_key + union_id` 只有在租户白名单、机器人应用配置一致且属于同一开发者范围时才自动建立映射，不混用不同应用的 `open_id`，停用或冲突映射不自动覆盖。Aily 未启用时不新增积压。由于 `TK-202608-0036` 在修复前没有飞书发件箱记录，不自动补发；部署后熊军需要重新通过飞书登录一次建立映射，再用新的受控指派通知完成 IDC 验收。

2026-08-11 飞书主动通知身份自动映射修正：真实 IDC 数据显示 28 个活动飞书登录账号中只有熊军存在出站映射；胡书豪等人的 `work_task.assigned` 已正确进入发件箱，却停留在 `pending / AILY_IDENTITY_NOT_MAPPED`。这些用户当天已完成飞书 OAuth 登录，证明旧实现把 OAuth `tenant_key` 错误拿去匹配 Aily MCP JWT `tenant_id` 白名单，导致自动映射被静默跳过。正式口径拆分为两个信任边界：MCP 租户白名单仅用于入站工具调用；已配置飞书登录应用验真的 OAuth 回调在成功映射活动 ITOM 账号后，优先以 `tenant_key + user_id`、缺失时以 `tenant_key + union_id` 自动建立当前 `bot_app_id` 的出站映射。机器人出站解析优先使用该应用映射，历史人工/Aily 映射仍受原租户白名单约束；跨应用 `open_id`、停用映射、冲突账号和未知身份仍不放行。已有账号无需管理员逐个加入租户白名单或手工绑定，在修复部署后的下一次正常飞书登录会自动建立映射，原有身份等待发件箱随后由后台重试投递。

2026-08-11 飞书主动通知批量自动补齐：只读核查证明现有通讯录 `find_by_department` 已返回 `open_id`、`user_id` 与 `union_id`，但登录应用和机器人应用均未开通 `tenant:tenant:readonly`，不能依赖“获取企业信息”接口直接启动历史批量回填。实现采用最小权限路径：首个修复部署后正常 OAuth 登录建立并审计当前机器人应用的唯一 `tenant_key` 锚点；后台发送其他未映射账号的待发消息时，只对“活动账号 + 在岗飞书同步人员”使用其登录应用 `open_id` 查询单个通讯录用户，并把返回的租户级 `user_id`（缺失时 `union_id`）保存为当前机器人应用身份后投递。其他员工无需逐人重新登录或管理员逐项绑定。锚点缺失/歧义、离职/未关联人员、显式停用、冲突身份和通讯录查询失败均保持 `pending`；查询失败不消耗消息发送重试次数，且登录应用 `open_id` 从不直接发送给机器人应用。

2026-08-12 飞书 OAuth 登录回归修复：IDC 实时日志证明授权地址、应用令牌、OIDC 令牌和用户信息接口均成功，失败发生在 ITOM 把已验真的登录身份与通知映射审计同事务提交时。原动作名超过 `audit_log.action VARCHAR(32)`，PostgreSQL 拒绝插入并回滚整个登录事务；SQLite 回归未执行该长度约束。现将 OAuth 自动映射和组织补齐动作编码固定为 `auto_map_aily_identity`、`auto_map_aily_identity_org`，可信锚点查询复用同一组常量，并增加直接读取 SQLAlchemy 列长度的边界测试。本修复不迁移数据库、不改变身份信任边界，也不触碰已有账号、映射、通知发件箱或业务数据。

2026-08-10 IDC 公网可信 TLS：将 `*.snnc.cc` 的公开 CA 完整证书链和匹配私钥作为 `itom/itom-snnc-cc-tls`（`kubernetes.io/tls`）创建，Ingress 为 `itom.snnc.cc` 绑定精确 TLS host；FortiGate 保持 `183.60.58.58:30443 → 10.60.65.220:443` TLS 直通，DNS 与 `public_base_url=https://itom.snnc.cc:30443` 均未改变。公网 `curl`、`openssl s_client -verify_return_error -verify_hostname` 和浏览器现有登录会话均不跳过证书校验地通过；服务器发送 3 张 DigiCert 链证书，SAN 覆盖 `*.snnc.cc`。外部 `/mcp/` `initialize` 返回协议与 `serverInfo`。飞书开放平台已显示相同 HTTPS 回调地址、已订阅新版 `card.action.trigger` 且应用已发布；重新保存未改变的地址未报错，但未产生新的 challenge 访问日志。为避免变更生产业务单据，本轮未创建新工单或点击签名卡片；当前 IDC 的真实角色卡片点击仍须作为独立业务 UAT 完成，不能由历史卡片证据替代。

2026-08-10 IDC 前端调度收口：三节点均 Ready、可调度且没有压力/污点；node02 是正常生产候选节点，不再按历史 build-executor 角色排除。`itom-frontend` 的目标模板显式声明空 `nodeName`，以清除人工恢复留下的 node01 固定绑定，并通过节点 01/02 选择器和硬主机反亲和使两个副本跨节点。后端保持无节点硬绑定的单副本 `Recreate`，数据库 StatefulSet、PVC、Secret 与业务数据不在本次应用发布范围。该策略不改变业务、身份、数据或 TLS 契约。

验收：以业务用户、IT 人员完成“诉求 → 建单 → 派单 → 受理 → 解决 → 通知 → 确认/重开 → 关闭 → 评价”真实闭环，多张待确认单据不串单，内部信息不外发。

### 阶段 3：飞书审批（暂缓）与发布加固

- 指定 ITOM 审批节点接入飞书审批并做双向幂等（按用户决定暂缓，不阻塞当前发布加固）；
- IDC 公网入口已替换为受信 TLS；继续完成安全、性能、故障恢复和当前版本真实角色 UAT；
- 从 `feature/AI-agent-version` 发起用户确认的 PR 合入 `main`。

### 项目组合治理边界（2026-08-18）

项目组合治理本期只增加 ITOM 网页与领域 API，仍以项目、WBS、风险、成本、权限和审计为事实来源。它不修改 Aily JWT、MCP transport、身份映射、回调、通知或 Web Agent 能力注册；没有新增组合读取或写入工具。`PortfolioGovernance` 页面只把受控 `page=portfolio_detail` 与组合 GLID 放入既有网页上下文白名单，不读取 DOM，也不授予任何动作。未来若要让 Aily/MCP 或 Web Agent 操作组合，必须另行完成能力风险分级、领域服务封装、记录级重授权、L3 预览确认、幂等与真实角色验收，不能直接复用本期网页 API 作为隐式工具权限。

## 11. 完成交付标准

每次改动必须同时完成实现、测试、中文权威文档和 `docs/en` 英文镜像；feature 分支先通过 GitHub Actions 的相关单元、API/MCP 集成、身份权限、幂等重试测试、前端生产构建和仓库契约检查。自动化测试不得连接 IDC 业务数据库。只有已确认的 `feature-local` 路线可启动仓库定义的本地隔离应用与测试数据库；`production-fix` 和 `code-candidate` 默认不启动。发布必须来自干净提交、使用 Git SHA 不可变 linux/amd64 镜像，并在单独获得精确发布批准后于 IDC 完成 rollout、镜像、健康链路、MCP 和真实角色验收。

不得把 CI 全绿、镜像构建成功、`/api/health`、MCP 初始化、单次工具成功或模拟载荷测试当作完整业务验收。验收证据必须覆盖真实身份和多角色业务闭环。

## 12. 维护要求

本文件是当前正式设计基线。任何改变产品分流、工具契约、身份、安全、数据模型、消息通道、部署或验收口径的决策，都必须在同一改动中同步本文、`docs/03–06`、README 和英文镜像。每阶段实现后，文档必须从“目标/待实现”更新为实际能力和验证证据。

Task 8C Round 2 证据补充：共享前端 expiry parser 现拒绝显式 `Z` 形状下仍会被 JavaScript 规范化的非法日/月/小时；合法闰日与小数秒 UTC 保持兼容。本轮无后端、数据库、部署、Aily/MCP 或 IDC 变化。
