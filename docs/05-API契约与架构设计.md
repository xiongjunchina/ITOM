# ITOM API 契约与架构设计

> 依据 [03-PRD.md](03-PRD.md)、[04-数据模型设计.md](04-数据模型设计.md)。
> Aily + MCP 的 P0 协议/身份/机器人真实收件、P1 服务入口和 P2 服务闭环已在现已封存的 `feature/aily-agent-mcp` 实现并由当前 `feature/AI-agent-version` 继承；P2 已通过真实 Aily 多角色对话、机器人收件及普通用户同单端到端验收。P2.1 已改为飞书新版 `card.action.trigger` 验签回调：Aily Workflow/Skill 因不能提供可信 `x-aily-jwt` 而不承担卡片写操作，历史真实“未解决 → 重开 → 再次解决并关闭 → 评价”按钮 UAT 已通过。2026-07-31 IDC 复核发现 `itom.snnc.cc:30443` 公网证书无法通过标准 CA 校验且当前卡片 POST 未到达入口日志，因此当前 IDC 的“确认关闭”仍待受信 TLS 和新工单卡片复验。P3 飞书审批按用户决定暂缓，IDC 发布加固与正式验收继续进行。Helpdesk 路由只属于冻结标签 `v1.0.0-feishu-helpdesk`。

## 1. 系统架构

```text
飞书用户 ⇄ Aily Agent ──HTTPStreaming + x-aily-jwt──▶ Nginx /mcp
                                                       │
飞书用户 ──点击机器人卡片──▶ 飞书开放平台 ──签名回调──▶ Nginx /api/integrations/feishu/card-actions
                                                       │
React SPA ──JWT Bearer──▶ Nginx /api ──────────────────┤
                                                       ▼
                                         FastAPI 单体后端（内嵌 MCP）
                                           routers/MCP → domain services
                                                       │
                                       RBAC / workflow / audit / PostgreSQL
                                                       │
                                         event_bus → notification_outbox
                                                       │
                                         Aily 机器人飞书消息 → 用户
```

**关键决策**：

1. **单体后端**，按域分模块，不做微服务——单团队规模下微服务只增加复杂度。
2. **MCP 内嵌 FastAPI**，复用同一领域服务、数据库事务、RBAC、流程和审计；MCP 工具不得直接写表。
3. **领域事件为进程内同步分发**（同一事务提交）；可靠发件箱异步投递站内通知和 Aily 机器人消息。
4. 前后端分离单仓库（monorepo），一次部署。Nginx 同时代理 `/api/` 和 `/mcp`。

## 2. 仓库结构

```text
ITOM/
├── backend/
│   ├── app/
│   │   ├── core/          # 配置、GLID、安全(JWT/bcrypt)、依赖注入
│   │   ├── models/        # SQLAlchemy 模型（按域分文件：support/itsm/project/requirement/process/team）
│   │   ├── schemas/       # Pydantic 请求/响应模型
│   │   ├── routers/       # API 路由（按域分文件）
│   │   ├── services/      # 业务逻辑层（状态机校验、编号生成、计算列维护）
│   │   ├── events/        # event_bus + 订阅者（points/notify/process）
│   │   └── main.py
│   ├── alembic/           # 数据库迁移
│   ├── seeds/             # 初始数据（状态机、SLA 策略、流程定义、积分规则、字典）
│   └── tests/
├── frontend/
│   └── src/{api, components, pages, router.tsx, stores}
├── deploy/                # docker-compose.yml、Dockerfile×2、nginx.conf、IDC K8s 清单与发布脚本
└── docs/                  # 本系列设计文档
```

## 3. API 约定

- **认证**：`POST /api/auth/login` → JWT（8h）；其余接口 `Authorization: Bearer`。
- **RBAC**：路由声明所需角色，依赖注入校验；数据级过滤（requester 只见自己的单据）在 service 层。
- **响应包**：`{"success": true, "data": ..., "total": n, "page": p}`；错误 `{"success": false, "error": {"code": "TICKET_INVALID_TRANSITION", "message": "..."}}`，HTTP 4xx/5xx 同步。
- **分页**：`?page=1&page_size=20`（默认 20，上限 200）；筛选参数各资源自定义；排序 `?order_by=-submitted_at`。
- **状态流转统一模式**：`POST /api/{resource}/{id}/transition` `{"to": "resolved", "fields": {...}}`——状态机校验 + 该转换要求的阶段字段（如解决时必填 solution）一次提交。
- OpenAPI 文档自动生成于 `/api/docs`。
- **MCP 认证**：Aily 请求使用 `x-aily-jwt`；MCP 校验 HS256、有效期、租户/Agent 白名单并通过 `external_identity` 映射活动 `AuthUser`。MCP 入口不接受 ITOM Bearer Token 替代 Aily 身份。
- **MCP 写操作**：`prepare_*` 生成短期确认意图；`submit_*` 必须携带确认凭证和幂等键。工具结果继续使用 MCP 结构化内容，不伪装为 REST 响应包。

## 4. 路由清单（按域）

### 4.1 认证与支撑

```text
POST /api/auth/login | GET /api/auth/me
GET /api/auth/me/profile | PATCH /api/auth/me/preferences
POST /api/auth/me/password | GET /api/auth/me/audit-logs
GET /api/auth/me/feishu-binding/authorize-url
POST/DELETE /api/auth/me/feishu-binding
GET /api/auth/feishu/client-config | POST /api/auth/feishu/app-login
GET/POST/PATCH/DELETE /api/admin/users   # admin；删除为账号软删+解绑人员
GET/POST/PATCH /api/members              # 人员主数据
GET /api/admin/master-data?category=     # 字典（全员只读，admin 可写）
GET/PUT /api/admin/workflow-config       # 状态机
GET /api/admin/audit-logs
GET /api/notifications | POST /api/notifications/{id}/read | POST /api/notifications/read-all | POST /api/notifications/clear-read   # 站内通知、批量已读与已读清理
POST /api/attachments (multipart) | GET /api/attachments?entity=
```

个人接口约束：`PATCH /me/preferences` 只更新显式提交的键；主题为 `light|dark|system`，密度为 `default|compact`。`POST /me/password` 的新密码至少 8 位且包含字母和数字；已有人工密码时必须提供正确的 `current_password`。飞书解绑要求账号已经设置本地密码；个人审计接口只返回当前账号作为 actor 的记录。

### 4.1a 组织同步（M35）

```text
POST /api/admin/org-sync                 # 默认后台启动，返回 {started:true}
POST /api/admin/org-sync {sync:true}     # 测试/脚本同步等待，直接返回统计
GET /api/admin/feishu-config             # last_sync_stats.status: running|done|failed
```

后台同步运行期间重复触发返回 HTTP 409 / `SYNC_RUNNING`。前端每 3 秒读取 `last_sync_stats`，最长等待 10 分钟；完成或失败后向触发人发送站内通知。后台任务使用独立数据库会话，不能复用请求会话。

### 4.1b Aily Agent + MCP（P0/P1/P2 已实现）

```text
GET/POST /mcp/
    # P0 已实现的 Streamable HTTP 主入口；Origin 必须命中白名单
    # Aily 自定义 MCP 配置必须填写带末尾斜杠的规范地址；省略斜杠会在保存校验阶段失败
    # initialize/tools/list 等只读协议发现允许在尚未回填 JWT Secret 时完成首次注册
    # tools/call 必须携带可验签 x-aily-jwt，并通过租户/Agent/身份映射
    # Nginx 关闭缓冲、保留 300 秒读超时并透传鉴权/Origin；密钥不进入 URL

GET/PUT /api/admin/integrations/aily
    # admin；读取只返回 has_secret，保存 MCP JWT Secret 与机器人凭据时加密
GET/POST /api/admin/integrations/aily/identities
PATCH/DELETE /api/admin/integrations/aily/identities/{id}
    # admin；按 provider+tenant+app+subject_type+subject_id 精确映射 ITOM 账号
POST /api/admin/integrations/aily/test-message
    # admin；向选定且已验证的外部身份发送机器人测试消息

get_current_user_context
    # P0 临时 MCP 联调工具：只返回验证成功、账号状态和可读账号名；不返回内外部 ID，并写 mcp_tool_call
```

MCP Server 作为 FastAPI 后端模块挂载，不建立第二套业务 API。P0 使用 MCP Python SDK 1.29 的无状态 Streamable HTTP；每次 FastAPI 生命周期创建独立会话管理器。Aily 首次保存自定义 MCP 后才展示 `identityJWTSecret`，因此注册阶段只允许协议发现方法，任何 `tools/call` 仍必须完成 JWT、租户/Agent、身份映射和账号状态校验。P1/P2 工具层只负责协议、身份上下文、结构化输入/输出和脱敏审计；服务项检索、表单校验、建单、派单、流程、用户确认/重开与评价均调用与网页相同的 ITOM 领域服务。

#### 服务请求工具

```text
search_service_items
get_service_item_form
prepare_service_request
submit_service_request
get_my_service_request
list_my_service_requests
```

以上 6 个服务请求工具已在 P1 实现。以下闭环工具已在 P2 实现：

```text
get_my_pending_confirmations
confirm_service_request_resolution(ticket_code, resolved, idempotency_key, feedback="")
rate_service_request(ticket_code, score, idempotency_key, tags=[], comment="")
```

- `search_service_items` 只返回已上架且当前用户可申请的真实服务项；候选结果包含稳定 ID、名称、目录、简述和匹配理由，不返回内部派单细节。
- `get_service_item_form` 返回发布表单版本、字段 JSON Schema、SLA、流程摘要和公开说明。
- `prepare_service_request` 调用 ITOM 权威校验，返回规范化数据、缺失/错误字段、SLA、流程、预计支持组和短期确认意图；不落正式工单。
- `submit_service_request` 不接受 `ticket_type`，服务端固定创建 `service_request`；确认意图、当前用户、表单版本和幂等键必须一致。
- `get_my_pending_confirmations` 只列当前账号本人、状态为 `resolved` 的服务请求；返回公开工单编号、标题、服务项、解决说明和确认期限，不返回根因、内部备注或审批信息。
- `confirm_service_request_resolution` 必须携带明确 `ticket_code`；只允许提交人处理其 `resolved` 工单。`resolved=true` 完成最终用户确认任务并关闭；`false` 要求反馈原因，退回最近实际处理节点、增加重开次数并通知处理人。回退会软删除本轮目标节点及之后的旧任务；再次解决时从最新未删除的已完成任务刷新 `ticket.solution`。网页最终确认节点使用同一语义，管理员不能代替提交人确认。
- `rate_service_request` 只允许提交人评价已关闭工单，评分 1–5，最多 5 个不超过 32 字的标签，意见最多 500 字。同一工单更新唯一评价行并保留审计。
- 三个直接用户动作都要求 8–128 字符幂等键；相同用户/工具/键和相同载荷返回首次结果，载荷不同时返回 `IDEMPOTENCY_CONFLICT`。它们本身已是用户明确动作，不再签发第二个确认令牌。

#### IT 需求工具

```text
get_it_requirement_form
prepare_it_requirement
register_it_requirement
get_my_it_requirement
list_my_it_requirements
```

需求登记写入独立 `Requirement`，不创建 Ticket。普通业务用户不拥有需求模块权限；仅 BDO 和授权 IT 角色复用现有 `requirements.create/view`，并强制本人数据范围。领域服务还会校验 BDO/IT 角色边界，防止历史或手工追加的 `requester` 权限行绕过限制；评审、评分、转项目和关闭继续由现有需求编辑权限及流程控制。

#### 需求实现任务接口

```text
POST /api/requirements/{requirement_id}/tasks
PATCH /api/requirements/tasks/{task_id}
DELETE /api/requirements/tasks/{task_id}
GET /api/requirements/tasks/active
```

同一实现中需求可重复调用 `POST` 登记多行任务。需求负责人或拥有 `requirements.edit` / `req_tasks.edit` 的账号可以维护任务完整字段；任务负责人在无全局编辑权限时只能更新自己任务的 `status` 和 `actual_effort`。删除仍仅开放给全局需求/任务编辑权限，需求负责人身份不会自动获得删除权。列表和详情响应分别返回 `can_manage_tasks`、`can_delete_tasks` 能力标记，服务端不依赖前端按钮，写接口每次重新校验需求阶段、负责人范围、示例数据保护和权限。该接口变更不涉及数据库迁移，存量任务按原主键和软删除状态继续可读。

#### 任务管理接口（M82）

前端入口为 `/task-management/development` 与 `/task-management/delegated`；开发任务页的 `tab=requirement|bug` 只改变视图，不改变后端资源。历史需求任务路由重定向到需求开发标签，保证既有书签和数据兼容。

```text
GET/POST/PATCH /api/task-management/bugs
GET /api/task-management/bugs/{id}
GET /api/task-management/reference/cis              # Bug 所属系统候选；只读 CMDB 配置项
POST /api/task-management/bugs/{id}/confirm
POST /api/task-management/bugs/{id}/reject-confirm
POST /api/task-management/bugs/{id}/fix-tasks
PATCH /api/task-management/bug-fix-tasks/{id}
POST /api/task-management/bugs/{id}/verify
POST /api/task-management/bugs/{id}/reopen

GET/POST/PATCH /api/task-management/work-tasks
GET /api/task-management/work-tasks/{id}
POST /api/task-management/work-tasks/{id}/transition
DELETE /api/task-management/work-tasks/{id}
```

Bug 接口固定使用 `ci.product_manager_id` 的登记时快照，不接受客户端指定审批人；登记会启动 `bug_flow` 并自动完成登记节点，确认、生成多行修复任务、子任务全部关闭后的验证关闭均由对应流程处理人执行。验证不通过和重新打开必须带原因，并保留审计。委派任务使用 `登记 → 排期 → 执行 → 关闭`，另含 `暂停/中止`；登记且未分配时登记人可软删除，已分配任务在关闭前仅管理员可删除。所有列表响应都返回 `capabilities`，但后端每次按当前用户、状态、负责人和管理员身份重新校验。

`GET /api/task-management/reference/cis` 只返回未删除、未退役的 CMDB 配置项及其产品经理可读信息，供 Bug 登记页选择“所属系统”；它不维护第二套系统字典，也不放宽 `cmdb.view` 之外的写权限。CMDB 的 `owner` 是全部配置项均必填的技术负责人；仅“应用”类别的 `product_manager_id` 是 Bug 确认和验证关闭的产品经理，二者可为同一人但不是重复字段。后端拒绝新建或编辑时缺少产品经理的应用；历史应用缺值的 Bug 登记返回 `PRODUCT_MANAGER_REQUIRED`，补配后重新登记即可，登记成功后保存快照。

绩效与积分事件：Bug 修复子任务关闭发布 `bug_fix_task.completed`，委派任务关闭发布 `work_task.closed`。积分订阅按来源单据和规则幂等写入；Bug 修复与普通委派任务默认使用岗位结果规则，委派任务只有在服务端校验通过的团队贡献类型和 `performance_bucket=team_contribution` 下，才写入 `learning_growth`、`cross_team_support` 或 `training_knowledge`。交付指标按负责人、计划完成日期和实际关闭日期计算，未到期未关闭不提前计为失败。

#### 禁止工具

首期不提供 `create_incident`、`create_change`、任意状态流转、任务改派/审批/完成、通用 SQL、数据库和任意 HTTP 工具。普通用户描述疑似大范围故障时仍创建服务请求并标记，事件由 IT 人员或监控专用接口创建。

#### 主动消息

MCP 不能在后台状态变化时主动唤醒 Aily。服务请求首次受理、解决、重开、关闭和保存评价时，ITOM 领域事件写入 `notification_outbox(channel=feishu_aily)`，后台工作器通过飞书机器人应用发送消息。机器人凭据、消息开关、卡片回调 Verification Token 与 Encrypt Key 同时就绪后，解决/确认期限提醒发送交互卡片（已解决并关闭、仍未解决），关单发送 1–5 星评价卡片；否则发送兼容纯文本。“仍未解决”第一次点击只把原卡片更新为必填原因表单，提交后才重开。

普通对话仍只走 Aily + MCP。卡片按钮是唯一例外：飞书开放平台向 `POST /api/integrations/feishu/card-actions` 推送新版 `card.action.trigger`，ITOM 在读取业务 JSON 前以 `X-Lark-Request-Timestamp`、`X-Lark-Request-Nonce`、Encrypt Key 和原始正文计算 SHA-256 签名，并限制 5 分钟时效；时间戳按官方 Unix 秒/毫秒格式校验，同时兼容真实 Aily 回调出现的带时区和 Go 单调时钟后缀的时间字符串，签名计算仍使用原始请求头字符串。启用加密时按 AES-256-CBC/PKCS#7 解密，再校验 Verification Token、Bot App ID、回调头与点击人中的 `tenant_key` 一致性，以及点击人的 `open_id/user_id/union_id` 显式映射。真实联调证明 Aily JWT 的 `tenant_id` 与卡片回调 `tenant_key` 属于不同标识命名空间，不能强制字符串相等：回调租户未直接命中 Aily 租户白名单时，点击人必须在允许的 Agent/Bot App 范围内唯一映射到“已授权 Aily 租户 + 活动 ITOM 账号”，未知、歧义、停用或无权限身份均拒绝；白名单为空也不允许回退授权。飞书保存 Webhook 地址时实测发送无签名头的加密 `url_verification` challenge；该只读握手仅在成功解密、类型严格为 challenge 且 Verification Token 匹配时放行，任何 `card.action.trigger` 仍必须具备完整有效签名。通过后只调用 `service_request_closure`，不直接写表；该服务继续执行 RBAC、提交人本人范围、流程状态、8–128 字符幂等键和审计。响应在飞书要求的 3 秒内返回 Toast 与更新后的卡片；立即更新使用新版固定结构 `card={"type":"raw","data":<完整卡片 JSON>}`，不能把原始卡片直接放在 `card` 下。无效签名使用 HTTP 401，业务拒绝使用错误 Toast 并保留原卡片。动作值只含公开工单号、动作、评分和幂等键，不含飞书身份、Token、密钥、ITOM 主键或内部处理字段。

协议依据：飞书开放平台[处理卡片回调](https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/handle-card-callbacks?lang=zh-CN)、[接收回调](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/receive-and-handle-callbacks?lang=zh-CN)及[输入框组件](https://open.feishu.cn/document/feishu-cards/card-components/interactive-components/input?lang=zh-CN)。实现固定使用新版 `card.action.trigger`，不兼容已废弃的旧版卡片回调。

发送使用事件级幂等键、指数退避和脱敏错误；机器人配置尚未启用或凭据不完整时保留 `pending` 且不消耗重试次数。每个账号选择最近使用的活动飞书身份作为接收人，内部备注、根因、审批意见和敏感字段不出站。管理员通过 `GET/PUT /api/admin/integrations/aily` 只写配置两个回调秘密；响应仅返回 `has_card_callback_verification_token`、`has_card_callback_encrypt_key` 和 `interactive_cards_ready`，绝不回显秘密。存量 PostgreSQL 由启动迁移幂等补列两个密文字段，不新增业务表。

飞书服务台的 `/api/integrations/feishu/helpdesk/*`、订阅、交接、事件队列和专用 outbox 已从新版本路由和运行时删除。存量 PostgreSQL 结构通过 `python -m app.scripts.migrate_aily_mcp` 默认预览，明确追加 `--confirm` 后才永久清理。

### 4.1c IT 员工分流与跨单据关联（阶段 A/B/C 已实现）

以下契约只服务 IT 员工网页，不增加 Aily/MCP 工具。分流、说明、受范围约束的关联读取和创建目标并关联接口均已上线：

```text
POST /api/staff-intake/recommend
    # 已实现：IT 员工；临时问题→推荐单据类型、理由、反例、按真实创建权限过滤的目标入口；不落库
GET  /api/it-document-guide
    # 已实现：已登录用户；六类单据的一行说明和案例库；服务端返回 IT 员工能力开关
POST /api/record-relations/prepare
    # 已实现：源单据 + relation_type；复核源查看/目标创建权限，返回安全预填和目标必填字段
POST /api/record-relations/submit
    # 已实现：目标表单 + relation_type + reason + idempotency_key；来源锁 + 提交摘要防重，调用目标领域服务创建目标、启动流程、写关系和审计
GET  /api/records/{entity_type}/{entity_id}/relations
    # 已实现：当前用户可见源记录后，只返回其同时有权查看的关联对端；不泄露不可见单据的关系、编号或标题
```

`prepare` 与 `submit` 仅接受服务端白名单的四类来源/目标组合。`submit` 不接受客户端指定目标实体类型；服务端从来源记录和 `relation_type` 推导目标类型，先复核来源数据范围和目标 `create` 权限，再调用工单、问题或项目领域服务。重复调用同一操作者/来源/目标类型/幂等键且规范化请求一致时返回首次目标；同键异参返回 `IDEMPOTENCY_CONFLICT`（409）。

`recommend` 的问题和答案不得持久化。活动关系已建立来源/目标/关系类型唯一约束，并对创建人、来源、目标类型、幂等键建立唯一约束；同键异参由请求摘要拒绝。`prepare/submit` 不直接写领域表；`submit` 已通过事件、问题、变更或项目等领域服务完成各自的字段、状态、流程、审批、RBAC、审计和事件发布。允许的首期关系类型由服务端白名单控制；任何重复提交按幂等键返回首次结果，不得改变源单据类型、状态或流程。

### 4.1d ITOM 网页智能体（WA0–WA4，设计已确认）

网页智能体使用现有 ITOM Bearer 登录身份和独立 `/api/assistant` 入口，不调用 Aily `/mcp/` 进行自连接；两种渠道只在领域服务、权限、表单、流程、确认、幂等和审计层复用。目标接口如下：

```text
GET/POST /api/assistant/conversations
GET      /api/assistant/conversations/{id}
POST     /api/assistant/conversations/{id}/messages    # SSE
POST     /api/assistant/actions/{id}/confirm|cancel
POST     /api/assistant/conversations/{id}/archive
GET      /api/assistant/bootstrap

GET/POST       /api/admin/ai/providers
PATCH/DELETE   /api/admin/ai/providers/{id}
POST           /api/admin/ai/providers/{id}/test
GET/PATCH      /api/admin/ai/profiles/{code}/draft
POST           /api/admin/ai/profiles/{code}/publish|rollback
GET            /api/admin/ai/health|usage?days=1..90|action-audits
```

模型只收到当前用户可用的代码注册能力。L3 动作先生成绑定用户、会话、能力、规范化参数摘要和有效期的单次确认凭证，确认时再次校验账号、权限、数据范围、记录状态和流程任务；成功结果只能来自领域服务。读取模型配置只返回 `has_secret`。详细架构、安全和降级见 [`docs/superpowers/specs/2026-08-01-itom-web-agent-design.md`](superpowers/specs/2026-08-01-itom-web-agent-design.md)。

WA0 Task 1–2 已实现持久化基础及服务器内的策略/脱敏内核：能力只能由代码中的固定注册表登记；注册拒绝重复代码、无确认的 L3、全部 L4、非 Pydantic 输入和缺失处理器。输入模型字段及别名按凭据和授权内部名称的分段语义校验，检查字段名、普通别名、`validation_alias`/`serialization_alias`、`AliasPath` 的每个字符串段和 `AliasChoices` 的全部替代路径；拒绝 `authorization/auth` 上下文、权限范围/矩阵、角色/角色 ID 与凭据变体；普通业务近邻字段不因偶然子串被拒绝。任意 `dict`/`Mapping`（含嵌套或列表项）及其可导出任意键的 `additionalProperties` schema 都在注册和导出前失败关闭，输入对象必须使用有限的显式 Pydantic 字段契约。返回模型的 schema 不含处理器、内部角色/权限矩阵或已禁用能力，并递归删除字段 schema 的 `default/example(s)` 元数据和值；`properties` 映射中合法名为 `default`、`example`、`examples` 的字段仍保留。每次发现均从数据库重新读取活动账号、有效角色、功能权限和已发布档案的能力代码/最高风险限制；档案只能按代码和风险收紧，不能创建处理器或授予权限。记录数据范围、状态、所有权和流程任务仍必须在未来的领域处理器执行时再次校验，发现能力本身不构成执行授权。入模、消息持久化和普通日志摘要均使用同一递归、确定性脱敏，mapping 键与文本赋值共用凭据名称分类：敏感键（不分大小写）、动态表单 `sensitive=true` 字段、Cookie/Authorization 头、Bearer、JWT 和密码/Token/Secret/API access/private key 等赋值均替换为 `[REDACTED]`。本任务未实现提供商调用、`/api/assistant` 路由、UI 或业务能力处理器。

WA0 Task 3 已实现提供商中立的 `ModelProvider` 契约、OpenAI-compatible `/chat/completions` 适配器和 `AssistantGateway`。`AI_PROVIDER_ALLOWED_HOSTS` 必须配置逗号分隔的精确主机或显式 `*.受控后缀`；空白名单失败关闭。Base URL 只允许 HTTPS，禁止 URL 凭据、查询、片段和路径逃逸；路径按最多 8 轮、长度最多 2048 字符解码至稳定状态，残留、循环/歧义百分号编码及解码后分隔符、反斜杠或点段均拒绝。每个真实请求在发送前重新解析 DNS，并拒绝 loopback、private、link-local、multicast、unspecified、reserved 和 metadata 类地址；生产传输为该请求建立独立连接池，只向当次通过校验的字面 IP 集合拨号，HTTP origin/Host、TLS SNI 和证书主机校验仍使用原始白名单主机。环境代理和重定向均禁用；只有测试可注入 `httpx.MockTransport`，普通注入客户端拒绝。连接/读取超时分别由 `AI_PROVIDER_CONNECT_TIMEOUT_SECONDS`（默认 5）与 `AI_PROVIDER_READ_TIMEOUT_SECONDS`（默认 60）控制。

`probe()` 依次独立执行并精确校验：认证基础响应、带合法 `[DONE]` 终止语义的流式响应、`tool_choice` 强制的唯一已提供工具名及合法参数、符合请求中 strict schema 常量/必填/禁额外字段约束的 JSON；提供商忽略某项时仅该能力标记为 false，认证、连接、超时或上游服务故障仍使探测失败。L2/L3 必须同时具备 `supports_streaming`、`supports_tools` 和 `supports_json_schema`，并满足启用、近期探测成功及同策略主/备条件。流式响应只接受可验证的 SSE delta、完整 JSON 对象工具参数、usage、受支持的 `stop/tool_calls` 终止原因和最终 `[DONE]`，见到 `[DONE]` 即停止读取并关闭响应；未知事件、非法 JSON、截断或缺失终止语义均失败关闭。主模型任何输出开始后失败不得切换备用。

`ChatRequest.purpose` 只接受服务端 `ProviderPurpose` 枚举并以最长 32 字符的规范代码存储；原始字符串、未知、超长或可能携密的用途在构造提供商、出站和审计前拒绝。每次真实尝试只向 `ai_provider_call` 写提供商、模型、规范用途、Token、耗时、结果码、状态和脱敏错误，不保存 prompt、响应正文或密钥。审计使用独立 `SessionLocal` 事务，绝不提交/回滚调用方会话；失败尝试的审计写入失败被隔离且不阻断安全回退，取消时审计失败不掩盖取消，成功尝试仅在审计提交后发送 `done`，审计失败返回脱敏 `GATEWAY_AUDIT_FAILED` 而不宣称完成。Task 3 不增加管理 API、`/api/assistant` 路由、UI、会话/动作编排或业务处理器。

WA0 Task 4 已实现 `/api/admin/ai` 管理 API，全部端点逐一声明真实服务端 `require_perm("admin_ai", ...)`，浏览器自报角色不参与授权。提供商创建、查询、更新、软删除与探测复用 Task 3 的 HTTPS、主机白名单、DNS 地址分类及请求级固定 IP 传输；未探测或探测已过期的提供商不能启用。提供商类型、URL、模型、非空新密钥、超时、输出限制、温度或备用关系变化会在治理锁内递增 `config_revision`、使旧探测失效并自动停用；修订号不散列或记录明文密钥。`api_key` 只在写请求中接收，非空值逐字节加密，省略或全空白更新保留旧密文；任何响应只返回 `has_secret`，不返回明文或密文。

`POST /providers/{id}/test` 原样复用 Task 3 的“认证基础 → 流式终止 → 强制工具 → strict JSON Schema”顺序，并严格分为三阶段：A 短事务取得专用于 AI provider governance 的 PostgreSQL transaction-scoped advisory lock，按 provider ID 排序 `FOR UPDATE`、刷新/校验并复制密文但不含明文/散列的配置快照及 `config_revision` 后提交；B 在不持有任何数据库事务、advisory lock 或行锁时执行异步网络探测及关闭传输；C 再用同一短事务锁刷新当前提供商，只有未删除且修订号不变才原子写 `probe_status`、布尔能力、`last_probed_at` 和脱敏审计。配置已变化或删除时丢弃结果并返回 409 `AI_PROVIDER_PROBE_STALE`，绝不覆盖较新的未验证/失败状态；探测本身失败则保存真实失败并撤销启用。创建、更新、删除、A/C 探测短事务，以及发布/回滚活动档案对提供商的引用均共用该跨 Pod 锁；同步锁从不跨异步网络等待，且主备环路、唯一主模型、启用门禁和删除引用均在锁内重新校验，不依赖进程内锁。

档案 code 固定为 `requester`、`bdo`、`it_staff`、`admin`，受众分别固定为 `requester`、`bdo`、`it`、`admin`。草稿更新携带 `expected_updated_at` 乐观锁；数据库只能选择进程内注册表已有的能力 code，且能力受众、风险、知识范围均不得超出服务端受众白名单。`name/default_provider_id/enabled/retention_days` 与提示词、能力、知识范围、风险全部保存在 version=0 草稿；所有新草稿、发布版本和回滚副本的 `config_snapshot` 都含显式 `schema_version=1` 及完整四个活动字段，PATCH 不修改 `ai_agent_profile` 当前活动字段。发布必须携带 `expected_draft_updated_at`，并同时通过中英文系统指令、非 L4 风险、注册能力、知识范围、启用且近期健康的默认提供商和 L2/L3 工具/JSON Schema 兼容性校验；只有验证成功后才在同一事务中应用活动档案字段并新增不可变、单调递增的 `ai_agent_profile_version`。运行时复用同一完整性校验：完整快照、双语提示、能力/风险、健康兼容提供商、最新版本及活动档案行必须一致；`enabled_capabilities` 与 `knowledge_scope` 必须保留原始的合法 list 形状，缺失、`null` 或其他畸形值绝不归一化为空列表，否则失败关闭。回滚请求携带来源版本与 `expected_latest_version`，只把可证明完整的历史快照复制为新发布版本并原子应用，从不修改或删除历史。迁移前 `{}`、无 schema 标记或缺字段版本返回 409 `AI_PROFILE_LEGACY_SNAPSHOT_UNAVAILABLE`，活动档案和全部版本字节保持不变，服务端绝不从当前活动档案猜测历史；完整的新版本仍可复制式回滚。过期草稿或并发版本返回 409；失败发布不改变当前活动档案、既有发布版本或生成半成品版本。

`GET /health` 只返回提供商/档案计数；`GET /usage?days=N` 由数据库聚合调用、Token、耗时及按提供商/结果码分组，`days` 默认 30 且只允许 1–90，不加载调用整行或消息/错误字段；`GET /action-audits` 只返回动作 code、风险、状态、结果实体与时间。三者均不返回 Prompt、消息正文、完整会话、密钥、确认 token/hash、规范化载荷、结果载荷或提供商错误正文。

WA0 Task 5 已实现当前登录用户的 `GET /api/assistant/bootstrap`、`POST/GET /api/assistant/conversations`、`GET /api/assistant/conversations/{id}` 和 `POST /api/assistant/conversations/{id}/archive`。`bootstrap` 的固定白名单只有 `enabled`、档案 code/version、`max_risk`、`suggested_prompts`、`retention_days` 和 `fallback_available`；档案未发布/停用/删除、受众不一致或运行时完整性无法证明时返回 `enabled=false`，不泄露内部原因、能力矩阵、禁用能力、提供商配置、密钥或处理器。`fallback_available` 仅在认证用户的既有 `GET /api/it-document-guide` 可安全产生权限感知的 `documents[].can_create/target_path` 指南载荷时为真；它不承诺 WA1 能力。创建在同一事务中先取得与 Task 4 发布/撤回相同的 PostgreSQL 治理 advisory/provider 行锁，再按该顺序 `FOR UPDATE` 重载目标活动档案、运行时校验、插入会话并提交；SQLite 保持相同服务调用和重载顺序以支持确定性测试。创建请求只接受 `language` 和 extra-forbid 的 `page_context`：route 必须是规范化本地路径，page/entity/tab 是有限安全标识，`selected_ids` 只能是最多 20 个不重复 GLID；角色、权限、DOM/HTML、提示词、Cookie、头、外部/协议相对/穿越式路径和其他字段全部 422。创建、列表、详情和归档均以认证后的数据库 `auth_user_id` 过滤；非归属会话统一返回 `AI_CONVERSATION_NOT_FOUND` 404，不通过 total、详情或归档状态泄露其他用户。列表默认只返回 active 会话，`include_archived=true` 仅显示本人已归档会话，按 `created_at DESC, id DESC` 稳定分页，`page` 只允许 1–10,000（`page_size` 为 1–200）。普通消息保留期只能读取会话创建时捕获版本的完整 schema 标记快照，不能由活动档案或 `expires_at` 推断：捕获为 0 时永不写正文，后续正值再发布也不能改变；捕获为 1–90 时保留其不可变决定和创建时 `expires_at`，但当前档案停用、删除、未发布、受众不一致或运行时校验失败时不写新正文；所有写入前递归脱敏。归档在提交 `archived_at/status` 前会 `FOR UPDATE + populate_existing` 锁定并刷新所属会话行，且绝不删除 `ai_action` 或安全/业务审计。SQLite 覆盖真实 Task 4 发布/撤回的确定性屏障和锁后重载契约；尚未在本轮执行 PostgreSQL 双会话行锁竞争，Task 9 IDC 验收必须执行创建/普通消息与真实发布/撤回竞争的两会话屏障（包括 0→正值及正值→0 保留结果）。Task 5 不包含消息 SSE、工具循环、L3 动作、业务处理器、UI、部署或 WA1 工作。

WA0 Task 6 已实现 `prepare_action(db, actor, conversation_id, capability_code, payload, idempotency_key)`、`confirm_action(...)` 和 `cancel_action(...)`，并开放 `POST /api/assistant/actions/{id}/confirm`（请求体只含 `confirmation_token`）与 `POST /api/assistant/actions/{id}/cancel`。准备阶段按注册定义取得能力、风险、输入模型和固定 handler；L3 注册时强制 handler 同时具备 `authorize_preview()`、`preview()` 和 `authorize_record()`。Pydantic `extra=forbid` 等注册模型规则拒绝客户端附加 SLA、队列、角色、处理器或最终状态；规范化后递归脱敏若发生任何变化，则统一 `AI_ACTION_PAYLOAD_INVALID`，不保存/执行脱敏替代值、不计算其摘要，也不占用幂等键。安全规范化原值计算稳定 SHA-256。`AiAction` 幂等唯一范围为账号 + 能力 + key，SQLAlchemy/PostgreSQL 统一命名 `uq_ai_action_user_capability_idempotency`；同键同摘要返回首个状态且不重新签发 Token，同键异摘要返回 409，竞态只捕获该命名约束、回滚后锁定重载赢家，其他 `IntegrityError` 原样传播。准备先在独立 `SessionLocal` 事务调用 `authorize_preview()`，通过后才可读取/返回记录元数据并要求 `preview()` 精确返回 `status=prepared`；`authorize_preview/preview` 只接收独立预览 Session 内加载的 actor 上下文和 `ReadOnlyActionData` 门面，后者只允许受限 SELECT 物化读取，不暴露原始 Session/Connection/事务面。PostgreSQL 在 handler 访问前执行 `SET TRANSACTION READ ONLY`。预览门面与 dirty/new/deleted 检查共同拒绝 ORM/DML 写入、textual SQL、flush、commit、rollback 和事务对象面；只有预览事务 rollback/close 结束后才进入动作持久化事务。随后准备会先 `FOR UPDATE + populate_existing` 锁定并刷新所属 active 会话，重检归属、状态和 profile/version 绑定，再处理动作插入或幂等赢家返回。

确认/取消只按当前认证账号查询并 `FOR UPDATE` 锁定 `AiAction`，他人动作统一 404。确认校验 `prepared`、十分钟期限和 Token SHA-256 后，会先在同一外层事务 `FOR UPDATE + populate_existing` 锁定并刷新所属 active 会话；会话已归档时在治理锁之前失败关闭并把同一动作行提交为有界 `failed`。只有会话仍 active 时，才按 Task 4 的 PostgreSQL advisory → provider 行 → profile 行顺序取得治理锁，并通过 Task 5 `_active_profile(..., lock_runtime_profile=True)` 和完整 `runtime_published_profile()` 证明：会话绑定的 profile/profile_version 仍是当前活动且最新发布版本，快照、双语提示、能力/风险/知识范围、活动行一致性及默认提供商启用/近期健康/工具与 JSON Schema 兼容仍全部有效。随后重新读取数据库账号、角色/组权限和注册能力，并在领域 mutation 前立即通过 `ActionUnitOfWork` 门面调用 `authorize_record()` 复核数据范围、记录状态、所有权和流程任务。handler 只能在调用方事务内执行，不能自行 commit/rollback/flush，也不能取得原始 begin/get_transaction/connection/bind 面。领域 handler、有效 `CapabilityResult(status="succeeded")`、动作状态/实体和通用 `audit_log` 位于嵌套 savepoint；全部成功后由外层事务一次提交。处理器或成功审计异常只回滚 savepoint，不释放已持有的动作行锁；同一锁定行随后由外层事务提交有界、脱敏 `failed`，等待确认者只会读到终态而不会再次进入 handler。失败状态 persistence/commit 自身失败时回滚外层并显式返回 `AI_ACTION_FAILURE_PERSISTENCE_FAILED`，不吞错、不宣称持久终态。错误 Token 保持 `prepared` 供合法本人重试；取消、过期、成功、失败均不可再次确认。原始 Token、敏感规范化载荷、provider secret、handler 异常和成功结果中的凭据赋值不进入数据库结果、日志、审计或错误正文。Task 6 不含消息 SSE/工具循环、具体业务 capability、UI、部署或 WA1。SQLite 自动化只证明 service/guard/锁序、归档与 prepare/confirm 竞争、回滚结果、命名竞态注入和 savepoint 语义，不等价于 PostgreSQL 运行证据。Task 9 IDC 必须以真实 PostgreSQL 两个 Session 留存：预览事务只读及写入失败；同键同参/异参准备竞态只有一个赢家且无 500/Token 重发；归档与 prepare/confirm 竞争的真实等待与失败关闭；确认 handler 或审计失败时等待者在动作行锁后读到 `failed` 且 handler 恰好执行一次；失败状态提交故障不得伪称已持久化。

### 4.2 ITSM

```text
GET/POST /api/tickets | GET/PATCH /api/tickets/{id}
POST /api/tickets/{id}/transition        # 含审批(approve/reject)、解决、关闭、挂起、重开
POST /api/tickets/{id}/satisfaction      # requester 评价
POST /api/tickets/{id}/escalate-problem  # 一键升级为问题
POST /api/tickets/{id}/to-knowledge      # 一键沉淀知识(草稿)
GET/POST/PATCH /api/problems | POST /api/problems/{id}/transition
GET/POST/PATCH /api/catalogs | /api/service-items。目录列表返回 `item_count` 及按状态拆分的 `published_item_count`、`unpublished_item_count`；服务项 GET 支持 `catalog_id`、`q`（编号/名称/类型/服务对象/负责人关键字）、`status`（上架/下架，未传表示全部）、`sort_by` 与 `sort_dir` 参数，列表页据此实现筛选和排序。
GET /api/service-items/{id}/form                # P1：当前用户可申请的已发布表单
GET/POST /api/service-items/{id}/form-versions | POST /api/service-items/{id}/form-versions/{version}/publish   # P1：动态表单版本
GET/PUT /api/service-items/{id}/dispatch-rule  # P1：服务项派单规则；运行时仍支持目录/全局兜底
POST /api/tickets/{id}/accept                  # 目标：实际受理打点，响应 SLA 以此为准
POST /api/tickets/{id}/confirm-resolution      # 目标：提交人确认关闭或未解决重开；网页与 MCP 共用服务
POST /api/integrations/feishu/card-actions     # P2.1：飞书新版验签卡片回调；无需 ITOM Bearer Token
GET/POST/PATCH /api/cis | GET /api/cis/{id}/impact          # 影响分析(上下游+关联工单)
GET/POST/DELETE /api/ci-relationships
GET/PUT /api/admin/sla-policies | GET /api/sla/dashboard     # 实时达成率
GET/POST/PATCH /api/vendors | /api/contracts
GET/POST/PATCH /api/knowledge | POST /api/knowledge/{id}/vote
GET /api/knowledge/search?q=
```

### 4.3 项目

```text
GET/POST/PATCH /api/portfolios
GET/POST/PATCH /api/projects | POST /api/projects/{id}/transition
POST /api/projects/import-charter        # .docx 解析 → 草稿预览 → 确认落库(两步)
GET/POST/PATCH/DELETE /api/projects/{id}/wbs | /milestones | /risks | /costs
GET /api/projects/{id}/gantt             # 甘特数据(任务+依赖+里程碑)
```

### 4.4 需求

```text
GET/POST /api/requirements | GET/PATCH /api/requirements/{id}
POST /api/requirements/{id}/transition   # 登记→分析→实现→关闭/搁置/取消，携带阶段字段
GET/POST/PATCH /api/requirements/{id}/tasks
POST /api/requirements/{id}/close        # 校验验收标准全勾 → 可带 {legacy_problem, knowledge_draft}
# P1：仅 BDO/授权 IT 角色复用 requirements.create/view，并由服务层强制本人数据范围；不新增第二套需求实体
```

### 4.5 流程

```text
GET/POST/PATCH /api/admin/process-definitions (含 steps 嵌套；步骤有稳定 step_code，已有实例的节点/RACI/SLA 改动需另存新版本)
GET /api/process-instances?entity= | GET /api/process-monitor   # 卡点/超时聚合
POST /api/process-tasks/{id}/complete | /reassign
```

流程定义列表的稳定展示顺序为：ITSM（服务请求）→ ITSM（变更）→ ITSM（事件）→ ITSM（问题）→ 项目 → 需求 → Bug 管理；后端按触发实体归一排序，前端分组与左侧菜单保持一致，不能依赖数据库返回顺序。

### 4.6 团队

```text
GET /api/team/overview                   # 负载/积分Top/培训数/招聘进度聚合
GET/POST/PATCH /api/positions | /api/hiring-needs；岗位与招聘需求另提供 `GET /api/positions/template`、`GET /api/positions/export`、`POST /api/positions/import`，以及对应的 `/api/hiring-needs/template`、`GET /api/hiring-needs/export`、`POST /api/hiring-needs/import` Excel 闭环。
GET/POST/PATCH/DELETE /api/trainings     # 培训提升活动；PATCH/DELETE 仅 admin/CIO/登记人
GET/PUT /api/team-charter
GET/POST /api/ideas | POST /api/ideas/{id}/like | /adopt | /to-requirement
GET /api/points/leaderboard?period= | GET /api/points/mine | GET /api/points/entries?person=
GET/POST/PATCH/DELETE /api/team/learning-growth?period=YYYY-Qn&scope=mine|team
    # 员工维护本期学习成长目标；完成比例按同周期目标等权平均折算 learning_growth 积分并写入 point_entry
GET /api/point-rules                    # 活动积分页读取团队贡献事件规则（按 ideas.view）
GET /api/point-rules/team-config         # 活动积分→积分规则读取团队贡献维度权重/目标/满意度组合
PUT /api/point-rules/team-config         # 活动积分→积分规则保存（admin/CIO）
GET/PATCH /api/admin/point-rules         # 兼容旧客户端的团队贡献事件规则接口（admin/CIO；不接受 role_result）
# 旧 PATCH /api/point-rules/{code} 保留兼容，但同样只允许修改 team_contribution
GET /api/team/performance/overview?period=YYYY-Qn|All  # 当前矩阵角色人效总览（角色职责 80% + 团队贡献 20%）
# GET /api/team/performance 保留旧版岗位方案结果，仅供历史客户端兼容，不作为当前总览数据源
POST /api/points/adjust                  # 管理员手工调分(必填 remark)
GET/POST/PATCH /api/admin/performance/role-profiles
PUT /api/admin/performance/role-profiles/{id}/dimensions
GET/PUT /api/admin/performance/assignments?period=YYYY-Qn
GET /api/admin/performance/reviews?period=YYYY-Qn
PUT /api/admin/performance/reviews/{assignment_id}/components/{dimension_code}
GET/POST/PATCH /api/admin/performance/external-inputs
GET /api/admin/performance/metric-definitions
GET /api/admin/performance/external-inputs?period=YYYY-Qn
POST /api/admin/performance/{period}/recompute
POST /api/admin/performance/{period}/submit-manager-review
POST /api/admin/performance/{period}/submit-cio-review
POST /api/admin/performance/{period}/publish
POST /api/admin/performance/{period}/unlock
GET /api/my/performance?period=YYYY-Qn
GET/POST/PATCH/DELETE /api/team/learning-growth?period=YYYY-Qn&scope=mine|team
GET/PUT /api/admin/performance/contribution-rules # 兼容旧客户端；团队贡献权重、目标及满意度组合的规范入口是 /api/point-rules/team-config
```

`POST/PATCH /api/trainings` 接受 `participant_ids`，以及可选的 `participant_department_ids`。后者仅用于“整部门参与”：服务端校验部门及其当时在岗 IT 团队成员，展开并冻结 `participant_ids`，同时保存部门 ID、显示名和人员范围快照。若 `PATCH` 省略该字段，保留现有部门快照以兼容旧客户端；显式 `[]` 清除部门显示语义但不自动删除已传的人员。`GET /api/trainings` 返回 `participant_ids`、兼容字段 `participant_names`、清单摘要 `participant_departments` / `participant_individual_names` 与当前账号的 `can_manage`。创建时服务端写入 `created_by`；存量记录在迁移时从最早 `development_activity.create` 审计记录回填。`PATCH` 和 `DELETE` 不依赖通用活动编辑权限：仅管理员、CIO 或登记人可操作，后端逐次复核。主讲或参与人变化会在当前未发布、未锁定周期软删除原活动的 `training_host` / `training_attend` 流水并按当前规则重算；删除亦撤销这两类流水。历史、已发布或锁定周期的计分改动和删除返回 `TRAINING_POINTS_LOCKED`，但不改变积分对象的资料可继续编辑并审计。

`/api/points/leaderboard` 的 `points` 聚合该周期 `contribution_bucket=team_contribution` 流水；当前考核期内，自动活动事件按当前有效 `point_rule` 分值计算，规则停用显示为 0，其他流水保留原始代数值。`/api/points/mine`、`/api/team/overview` 和 Dashboard 人员积分排行采用同一当前期口径，响应可带 `breakdown` 按 `source_type` 汇总来源。原始 `point_entry.points`、历史周期和已发布/锁定绩效不被改写。`role_result` 岗位结果流水不进入这些活动积分读接口，但仍保留在台账中供人效角色结果和审计使用。它与人效页经过角色、目标和权重折算后的结果不是同一指标。

### 4.7 Dashboard

```text
GET /api/dashboard    # 单接口返回四板块+告警区全部数据(一次聚合)
```

当账号具有任务模块查看权限时，响应额外包含 `task` 聚合块：`open_total`、`open_bugs`、`open_bug_fix_tasks`、`open_delegated_tasks` 和 `open_requirement_tasks`。该块只读、按当前非终态任务实时统计，不改变原有 Dashboard 字段。

## 5. 领域事件清单

事件由 service 层在事务内发布；`→积分` 表示触发 point_engine 计分（分值查 point_rule），`→通知` 表示写发件箱。

| event_type | 触发时机 | 订阅 |
| --- | --- | --- |
| ticket.created | 建单 | →通知(受理人/it_ops)、→流程(创建实例) |
| ticket.assigned | 指派/改派 | →通知 |
| ticket.accepted | 服务请求首次进入处理中 | →Aily 发件箱(提交人) |
| ticket.resolved | 解决 | →积分(工单解决)、→通知(提交人) |
| ticket.user_confirmed / ticket.reopened | 用户确认解决 / 未解决重开 | →审计、→通知(处理人) |
| ticket.closed | 关闭 | →积分(SLA 双达成时加分) |
| ticket.satisfaction_saved | 评价新增或更新 | →Aily 发件箱(提交人) |
| ticket.satisfaction_rated | 评价 ≥4 星 | →积分 |
| ticket.sla_warning | 超 SLA 80%（定时任务扫描） | →通知(升级) |
| change.approval_requested / approved / rejected | 变更审批 | →通知 |
| problem.root_cause_found | 根因定位（填入 root_cause） | →积分 |
| contract.expiring | 到期前 90 天（定时扫描） | →通知 |
| wbs_task.completed_on_time | 任务按期完成 | →积分 |
| milestone.achieved / overdue | 里程碑达成/逾期（定时扫描） | →积分 / →通知 |
| requirement.stage_changed | 四阶段流转 | →通知 |
| requirement.task_completed | 需求任务完成 | →积分 |
| requirement.closed | 需求关闭 | →积分 |
| bug.registered / confirmed | Bug 登记/产品经理确认 | →通知、→流程 |
| bug.fix_tasks_created | 生成 Bug 开发/测试子任务 | →通知 |
| bug.ready_for_verification | 全部 Bug 子任务关闭 | →通知、→流程 |
| bug.reopened / closed | Bug 验证不通过/重新打开或验证关闭 | →审计、→通知、→积分（后续指标） |
| work_task.created / closed | 委派任务登记/关闭 | →通知、→积分（后续指标） |
| knowledge.published | 发表 | →积分 |
| knowledge.voted | 被点有用 | →积分(作者) |
| activity.registered | 培训登记 | →积分(主讲/组织/参与分别计) |
| idea.submitted / liked / adopted | 建言 | →积分、adopted→通知(提出人) |
| performance.review_submitted | 负责人初评/CIO终审提交 | →通知(下一评审阶段)、→审计 |
| performance.published / unlocked | 绩效发布/生成新版本 | →通知(被评价者)、→审计 |

定时任务（后端内置 scheduler）：SLA 临期扫描、合同到期扫描、里程碑逾期扫描、合同状态推进、待用户确认期限 80% 单次提醒，以及 Aily 通知 outbox 消费/指数退避；不再运行 Helpdesk 扫描器。P2 在进入待确认时立即发送解决通知，`confirmation_due_at` 来自最终用户确认任务的 SLA 截止时间；每次重开后的新确认周期使用独立幂等提醒键。

## 6. 关键实现机制

1. **状态机**：`services/workflow.py` 统一入口 `transition(entity, to, fields, actor)` —— 查 workflow_transition 校验角色与合法性 → 校验该转换的必填阶段字段 → 更新 + 打点 → 发事件 → 写审计。所有单据共用。
2. **积分引擎幂等**：point_entry 建 UNIQUE(event_type, source_entity_type, source_entity_id, person)，同一单据同一事件不重复计分（重开再解决不二次得分）。
3. **计算列维护**：wbs_task/cost_entry/milestone 写操作后，service 层重算所属 project 的 progress_pct/actual_cost/health_status 写回（同事务）。WBS `progress` 接受 0-100 的整数百分比；流程步骤通过 `node_type=processing|approval` 区分处理/审批语义。审批任务可调用 `POST /api/process-tasks/{id}/approve`（理由可选）或 `POST /api/process-tasks/{id}/reject`（理由必填），完成入口仍支持流程图中的“完成此步骤”。
4. **章程导入两步**：解析接口只返回草稿 JSON + warnings（不落库）；前端展示确认页，用户修正后调创建接口落库。解析失败回退手工表单。
5. **SLA 计时**：挂起时累计 paused_minutes，达成判定 = (resolved_at − submitted_at − paused) ≤ 目标。
6. **矩阵角色人效评审**：系统先从 ITSM、需求、项目、流程和积分事件生成参考分；业务线负责人只能写入业务角色初评，专业线负责人只能写入专业角色初评，平台角色和各类负责人本人由 CIO 直接评分。后端按 `performance_role_assignment.review_scope` 做范围校验，不能只依赖前端隐藏按钮。
7. **外部原数据与发布隔离**：外部业务满意度先写入 `performance_external_input`，完成提交/核验/锁定后才参与折算；`performance_score_component` 保存系统参考分、阶段建议分和生效分，`/api/my/performance` 只返回已发布快照。
8. **积分分桶**：`point_rule`/`point_entry` 通过 `contribution_bucket=role_result|team_contribution` 区分岗位结果与团队贡献；已经进入角色结果指标的事实不得再次进入固定 20% 团队贡献。活动积分相关读接口只聚合 `team_contribution`，避免把角色结果重复计算为活动积分。
9. **MCP 适配边界（P1 已实现）**：MCP 工具只调用领域服务；`x-aily-jwt` 经白名单和 `external_identity` 映射后生成请求级 `AuthUser` 上下文。任何业务校验不得复制到提示词作为唯一规则。
10. **确认与幂等（P1 已实现）**：预览写入 `mcp_operation_intent`，提交核对 token hash、用户、工具、过期时间和 idempotency key；payload digest 在准备阶段防止同键异内容，重复调用返回首次结果，不重复建单或启动流程。
11. **动态表单快照（P1 已实现）**：发布版本不可原地修改；创建时把版本、答案和 schema 快照写入工单。人员/部门选项在提交时二次校验。
12. **服务派单（P1 已实现）**：服务项规则 → 目录默认组 → 全局兜底组；组内轮询只选择启用且在岗并有活动账号的成员。没有可用规则时保留工单并产生未派单事件，禁止静默丢单。

## 7. 部署架构

```yaml
# 默认交付链路
GitHub Actions:
  backend:   Python 3.12 + 临时 SQLite，完整 pytest
  frontend:  Node.js 22，npm ci + TypeScript + Vite 生产构建
  contract:  部署 YAML/脚本/差异检查 + 中英文文档交付守卫
Harbor:
  backend:   git-<commit>-linux-amd64
  frontend:  git-<commit>-linux-amd64
IDC Kubernetes:
  db:        PostgreSQL 16 + 持久卷
  backend:   uvicorn，启动时增量迁移 + 幂等 seed
  frontend:  nginx 托管构建产物，反代 /api 与 /mcp
```

- 环境变量：`DATABASE_URL`、`JWT_SECRET`、`ADMIN_INIT_PASSWORD`、`TZ=Asia/Shanghai`。
- IDC Kubernetes 是唯一运行、联调和验收环境；默认禁止在本地启动应用栈、数据库、Compose、8180 或 ngrok。只有用户明确要求临时隔离排障时才允许例外，且结果不属于交付验收。
- `.github/workflows/quality-gate.yml` 在 feature/develop/main 的推送和 PR 上运行完整后端回归、前端生产构建、部署文件检查及中英文文档交付守卫。测试夹具使用临时 SQLite，不连接 IDC 业务数据库。
- 质量门禁通过后，`deploy/k8s/push-images.sh` 只接受干净提交，使用已验证的 `mirror.gcr.io` 官方 Docker Library 缓存与固定摘要取得 Python/Node/Nginx/PostgreSQL 基础镜像，构建并校验 linux/amd64，以 `git-<commit前12位>-linux-amd64` 为默认不可变标签后推送 Harbor；镜像构建不启动本地 ITOM，也不依赖 Docker Hub 匿名限流。
- `deploy/k8s/k8s-deploy.sh` 部署同一标签并保留既有 Secret、PVC、数据库、上传和飞书配置。脚本对 rollout、Ready Endpoint、实际镜像、集群内前端代理、外部 `/api/health` 与 MCP `initialize` 采用失败即停止；涉及数据库结构的版本在部署前必须执行批准的集群内备份/检查点。
- 公网入口由管理员在“Aily Agent + MCP Server”的 `public_base_url` 字段维护，支持域名/IP 和非 443 服务端口；同一根地址承载前端、`/api`、飞书 OAuth 回调和 `/mcp/`。当前地址为 `https://itom.snnc.cc:30443`。
- `/mcp/` 必须保留流式响应并设置合理读超时；Aily 配置使用带末尾斜杠的规范地址，密钥只放请求头，不放 URL、日志或前端构建变量。
- 日志：结构化 JSON 到 stdout（由 Kubernetes 日志链路查询）。

## 8. 里程碑映射（开发顺序）

| 里程碑 | 后端 | 前端 | 验收基准 |
| --- | --- | --- | --- |
| M1 骨架 | core/auth/members/字典/状态机/审计/事件总线骨架/部署 | 登录、布局菜单、空 Dashboard、系统管理 | PRD §2/3/10/11 |
| M2 工单 | tickets/catalogs/service-items/sla + 流程引擎最小版 + 定时扫描 | 工单列表/详情/服务目录/SLA 看板 | PRD §5.1/5.3/5.5 |
| M3 ITSM 余下 | problems/cis/vendors/contracts/knowledge | 对应 5 页 | PRD §5.2/5.4/5.6/5.7 |
| M4 项目 | portfolios/projects/wbs/milestones/risks/costs/charter-import | 项目两标签页/详情 5 tab/甘特 | PRD §6 |
| M5 需求 | requirements/tasks/close 转出 | 需求看板/详情 | PRD §7 |
| M6 团队+总览 | points/ideas/activities/positions/performance/learning-growth/dashboard/流程监控 | 团队页/总览/流程监控 | PRD §4/8/9 |
| Aily-MCP P0（代码/自动化/真实身份及机器人真实收件已完成） | 删除 Helpdesk、MCP 挂载、身份/审计/消息 | Nginx `/mcp`、Aily 配置 | docs/10 §10 |
| Aily-MCP P1（服务请求与 IT 需求真实 Aily 写入 UAT 均已完成） | 动态表单、搜索、确认提交、BDO 需求登记、派单 | 服务项表单/派单配置 | PRD §5/7 |
| Aily-MCP P2（普通用户文本同单闭环及 P2.1 真实验签按钮闭环均已完成） | 受理、解决通知、确认/重开、评价 | 工单详情 + 3 个闭环 MCP 工具 | PRD §5.1 |
| Aily-MCP P3 / 发布加固 | 飞书审批暂缓；IDC 可信 TLS、安全/性能/恢复与真实角色 UAT | 审批与运维配置 | docs/10 §10 |
| 网页智能体 WA0（Task 1–6 已实现；Task 7+ 待实施）/WA1–WA4 | WA0 持久化、固定能力注册、实时角色策略、递归脱敏、安全 OpenAI-compatible 模型网关、模型/档案管理 API、本人网页会话生命周期及通用 L3 服务端预览/确认/幂等/重授权/原子审计；SSE/工具循环和具体领域能力待实施 | 全局助手、结构化卡片、AI 智能体管理 UI 待实施 | 网页智能体设计基线 |

## 8.1 业务域服务部门 API（M41）

```text
GET /api/admin/departments
    # 读取组织架构部门；前端筛选 active=true 且 dept_type=business 并构造部门树
GET /api/admin/business-domains
    # 每个业务域返回 departments[]：id/name/parent_id/active/include_children
PUT /api/admin/business-domains/{domain_id}/departments
    # body: { department_ids: string[], include_children: boolean }
POST /api/admin/business-domains
    # 新建 body 可直接带 department_ids/include_children；owner_id/backup_owner_id 仅允许数字化团队成员
PATCH /api/admin/business-domains/{domain_id}
    # 编辑 body 可同步替换 department_ids/include_children；负责人范围同上
PUT /api/admin/business-domains/{domain_id}/members
    # 服务团队成员必须属于统一数字化团队口径
```

部门维护写接口要求 `admin_business_domains.edit` 权限，对部门 ID 去重并校验部门存在、启用且类型为 business；采用全量替换语义并写审计动作 `set_departments`。新建与编辑业务域也可在同一请求中提交部门范围。负责人、备份负责人和服务团队在服务端统一通过 `it_member_ids` 校验，不允许全公司其他人员绕过前端写入。`include_children=true` 表示服务范围在业务语义上覆盖所选节点全部后代，但持久层只保存显式选择的根节点，避免组织调整时批量重写关系。

M42 新增 `GET/PATCH /api/admin/org-settings`，管理数字化团队范围和飞书自动同步策略。范围请求包含 `digital_team_department_ids`、`digital_team_member_ids` 与 `digital_team_include_children`；服务端分别校验有效部门和人员并去重，实际口径取部门成员与指定人员并集。新增 `DELETE /api/admin/business-domains/{id}`，存在未删除需求引用时返回 `DOMAIN_IN_USE`（409）。定时器每 15 分钟检查一次是否到达管理员配置的同步周期，实际同步仍复用 `org_sync.run_sync`。

人员选择器分为两个口径：涉及业务负责人、项目经理/任务负责人、需求负责人/评审人/开发负责人、工单/问题/服务项/配置项/合同负责人及用户组负责人/成员的 IT 工作选择器调用 `GET /api/members?scope=it`，配置数字化团队范围后由写接口再次校验。用户管理和飞书开通审批的“关联人员”面向全公司账号，调用不带 `scope` 的 `GET /api/members`；服务端只校验人员存在且未删除，不得套用数字化团队限制。

`GET /api/admin/users` 的每行同时返回 `person_id`、`person_name` 和 `person_department_name`，前端必须优先显示可读姓名，不能回退展示内部 GLID。`PATCH /api/admin/users/{id}` 对可空字段采用显式 PATCH 语义：请求省略 `person_id` 时不改变关联人员，提交 `person_id: null` 时解除关联并在响应、审计及后续列表查询中立即体现。

## 9. UI 品牌配置 API（M38）

```text
GET  /api/public/ui-branding                         # 无需登录；最新发布配置，未发布时返回内置默认
GET  /api/public/ui-branding/assets/{asset_id}       # 公开读取已上传品牌图片
GET  /api/admin/ui-branding                          # 草稿与当前发布版
PUT  /api/admin/ui-branding/draft                    # 保存完整草稿
POST /api/admin/ui-branding/assets?kind=             # 上传受控图片
POST /api/admin/ui-branding/publish                  # 草稿发布为新版本
GET  /api/admin/ui-branding/history                  # 发布历史
POST /api/admin/ui-branding/rollback/{version}       # 以历史配置生成新的发布版本
POST /api/admin/ui-branding/reset                    # 草稿恢复内置默认
```

除两个 public 读取端点外均要求 `admin_ui_branding` 权限，写操作进入 `audit_log`。前端启动先读取公开配置；接口失败、无发布版本或字段缺失时逐字段合并内置默认值，确保品牌配置故障不会阻断登录。
M44：审批接口生成 12 位密码并保存加密密文，不发信。`GET /api/admin/users/{id}/initial-password` 鉴权解密查看；`POST .../initial-password/email` 手工发送。`GET/PUT /api/admin/integrations/email|ldap` 管理全局配置，`POST .../test` 执行连接测试。敏感配置只返回 `has_secret`，不回显密钥。
