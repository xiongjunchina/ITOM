# ITOM API 契约与架构设计

> 依据 [03-PRD.md](03-PRD.md)、[04-数据模型设计.md](04-数据模型设计.md)。
> Aily + MCP 的 P0 协议/身份/机器人真实收件、P1 服务入口和 P2 服务闭环已在 `feature/aily-agent-mcp` 实现；P2 已通过真实 Aily 多角色对话、机器人收件及普通用户同单端到端验收。P2.1 已改为飞书新版 `card.action.trigger` 验签回调：Aily Workflow/Skill 因不能提供可信 `x-aily-jwt` 而不承担卡片写操作，真实“未解决 → 重开 → 再次解决并关闭 → 评价”按钮 UAT 已通过。P3 按用户决定暂缓。Helpdesk 路由只属于冻结标签 `v1.0.0-feishu-helpdesk`。

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

需求登记写入独立 `Requirement`，不创建 Ticket。普通员工复用现有 `requirements.create/view` 功能权限并强制本人数据范围；评审、评分、转项目和关闭继续由现有需求编辑权限及流程控制。

#### 禁止工具

首期不提供 `create_incident`、`create_change`、任意状态流转、任务改派/审批/完成、通用 SQL、数据库和任意 HTTP 工具。普通用户描述疑似大范围故障时仍创建服务请求并标记，事件由 IT 人员或监控专用接口创建。

#### 主动消息

MCP 不能在后台状态变化时主动唤醒 Aily。服务请求首次受理、解决、重开、关闭和保存评价时，ITOM 领域事件写入 `notification_outbox(channel=feishu_aily)`，后台工作器通过飞书机器人应用发送消息。机器人凭据、消息开关、卡片回调 Verification Token 与 Encrypt Key 同时就绪后，解决/确认期限提醒发送交互卡片（已解决并关闭、仍未解决），关单发送 1–5 星评价卡片；否则发送兼容纯文本。“仍未解决”第一次点击只把原卡片更新为必填原因表单，提交后才重开。

普通对话仍只走 Aily + MCP。卡片按钮是唯一例外：飞书开放平台向 `POST /api/integrations/feishu/card-actions` 推送新版 `card.action.trigger`，ITOM 在读取业务 JSON 前以 `X-Lark-Request-Timestamp`、`X-Lark-Request-Nonce`、Encrypt Key 和原始正文计算 SHA-256 签名，并限制 5 分钟时效；时间戳按官方 Unix 秒/毫秒格式校验，同时兼容真实 Aily 回调出现的带时区和 Go 单调时钟后缀的时间字符串，签名计算仍使用原始请求头字符串。启用加密时按 AES-256-CBC/PKCS#7 解密，再校验 Verification Token、Bot App ID、回调头与点击人中的 `tenant_key` 一致性，以及点击人的 `open_id/user_id/union_id` 显式映射。真实联调证明 Aily JWT 的 `tenant_id` 与卡片回调 `tenant_key` 属于不同标识命名空间，不能强制字符串相等：回调租户未直接命中 Aily 租户白名单时，点击人必须在允许的 Agent/Bot App 范围内唯一映射到“已授权 Aily 租户 + 活动 ITOM 账号”，未知、歧义、停用或无权限身份均拒绝；白名单为空也不允许回退授权。飞书保存 Webhook 地址时实测发送无签名头的加密 `url_verification` challenge；该只读握手仅在成功解密、类型严格为 challenge 且 Verification Token 匹配时放行，任何 `card.action.trigger` 仍必须具备完整有效签名。通过后只调用 `service_request_closure`，不直接写表；该服务继续执行 RBAC、提交人本人范围、流程状态、8–128 字符幂等键和审计。响应在飞书要求的 3 秒内返回 Toast 与更新后的卡片；立即更新使用新版固定结构 `card={"type":"raw","data":<完整卡片 JSON>}`，不能把原始卡片直接放在 `card` 下。无效签名使用 HTTP 401，业务拒绝使用错误 Toast 并保留原卡片。动作值只含公开工单号、动作、评分和幂等键，不含飞书身份、Token、密钥、ITOM 主键或内部处理字段。

协议依据：飞书开放平台[处理卡片回调](https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/handle-card-callbacks?lang=zh-CN)、[接收回调](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/receive-and-handle-callbacks?lang=zh-CN)及[输入框组件](https://open.feishu.cn/document/feishu-cards/card-components/interactive-components/input?lang=zh-CN)。实现固定使用新版 `card.action.trigger`，不兼容已废弃的旧版卡片回调。

发送使用事件级幂等键、指数退避和脱敏错误；机器人配置尚未启用或凭据不完整时保留 `pending` 且不消耗重试次数。每个账号选择最近使用的活动飞书身份作为接收人，内部备注、根因、审批意见和敏感字段不出站。管理员通过 `GET/PUT /api/admin/integrations/aily` 只写配置两个回调秘密；响应仅返回 `has_card_callback_verification_token`、`has_card_callback_encrypt_key` 和 `interactive_cards_ready`，绝不回显秘密。存量 PostgreSQL 由启动迁移幂等补列两个密文字段，不新增业务表。

飞书服务台的 `/api/integrations/feishu/helpdesk/*`、订阅、交接、事件队列和专用 outbox 已从新版本路由和运行时删除。存量 PostgreSQL 结构通过 `python -m app.scripts.migrate_aily_mcp` 默认预览，明确追加 `--confirm` 后才永久清理。

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
# P1：普通员工复用 requirements.create/view，并由服务层强制本人数据范围；不新增第二套需求实体
```

### 4.5 流程

```text
GET/POST/PATCH /api/admin/process-definitions (含 steps 嵌套；步骤有稳定 step_code，已有实例的节点/RACI/SLA 改动需另存新版本)
GET /api/process-instances?entity= | GET /api/process-monitor   # 卡点/超时聚合
POST /api/process-tasks/{id}/complete | /reassign
```

### 4.6 团队

```text
GET /api/team/overview                   # 负载/积分Top/培训数/招聘进度聚合
GET/POST/PATCH /api/positions | /api/hiring-needs；岗位与招聘需求另提供 `GET /api/positions/template`、`GET /api/positions/export`、`POST /api/positions/import`，以及对应的 `/api/hiring-needs/template`、`GET /api/hiring-needs/export`、`POST /api/hiring-needs/import` Excel 闭环。
GET/POST /api/trainings                  # 培训提升活动
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

### 4.7 Dashboard

```text
GET /api/dashboard    # 单接口返回四板块+告警区全部数据(一次聚合)
```

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
8. **积分分桶**：`point_rule`/`point_entry` 通过 `contribution_bucket=role_result|team_contribution` 区分岗位结果与团队贡献；已经进入角色结果指标的事实不得再次进入固定 20% 团队贡献。
9. **MCP 适配边界（P1 已实现）**：MCP 工具只调用领域服务；`x-aily-jwt` 经白名单和 `external_identity` 映射后生成请求级 `AuthUser` 上下文。任何业务校验不得复制到提示词作为唯一规则。
10. **确认与幂等（P1 已实现）**：预览写入 `mcp_operation_intent`，提交核对 token hash、用户、工具、过期时间和 idempotency key；payload digest 在准备阶段防止同键异内容，重复调用返回首次结果，不重复建单或启动流程。
11. **动态表单快照（P1 已实现）**：发布版本不可原地修改；创建时把版本、答案和 schema 快照写入工单。人员/部门选项在提交时二次校验。
12. **服务派单（P1 已实现）**：服务项规则 → 目录默认组 → 全局兜底组；组内轮询只选择启用且在岗并有活动账号的成员。没有可用规则时保留工单并产生未派单事件，禁止静默丢单。

## 7. 部署架构

```yaml
# deploy/docker-compose.yml 形态
services:
  db:        postgres:16  (volume + 每日 pg_dump 到宿主机备份目录)
  backend:   uvicorn, 依赖 db, 启动时 alembic upgrade + seed(幂等)；`SEED_INITIAL_CONFIG=1` 时在全新数据库初始化六条流程定义以及已验证的登录页/Logo 品牌配置，已有品牌草稿或发布版本不会覆盖
  frontend:  nginx 托管构建产物, /api 与 /mcp 反代 backend
```

- 环境变量：`DATABASE_URL`、`JWT_SECRET`、`ADMIN_INIT_PASSWORD`、`TZ=Asia/Shanghai`。
- 正式发布仍以 IDC Kubernetes 为最终验收环境：使用 `deploy/k8s/push-images.sh` 构建/推送镜像，再执行 `deploy/k8s/k8s-deploy.sh` 发布。当前 IDC 基础设施阻塞期间，用户已授权 Aily + MCP 使用本地 Docker 开发，并由 ngrok 暴露完整 `127.0.0.1:8180`；同一 HTTPS 根地址承载前端、`/api`、飞书 OAuth 回调和 `/mcp/`。
- `/mcp/` 必须保留流式响应并设置合理读超时；Aily 配置使用带末尾斜杠的规范地址，密钥只放请求头，不放 URL、日志或前端构建变量。
- 日志：结构化 JSON 到 stdout（docker logs 可查）。

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
| Aily-MCP P1（服务请求与 IT 需求真实 Aily 写入 UAT 均已完成） | 动态表单、搜索、确认提交、需求自助、派单 | 服务项表单/派单配置 | PRD §5/7 |
| Aily-MCP P2（代码/自动化、真实 Aily 对话闭环及机器人收件分别完成；普通用户同单端到端待验收） | 受理、解决通知、确认/重开、评价 | 工单详情 + 3 个闭环 MCP 工具 | PRD §5.1 |
| Aily-MCP P3 | 飞书审批、IDC 发布与真实 UAT | 审批与运维配置 | docs/10 §10 |

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
