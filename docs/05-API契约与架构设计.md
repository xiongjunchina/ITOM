# ITOM API 契约与架构设计

> 依据 [03-PRD.md](03-PRD.md)、[04-数据模型设计.md](04-数据模型设计.md)。

## 1. 系统架构

```text
┌──────────────┐     HTTPS      ┌─────────────────────────────┐      ┌────────────┐
│ React SPA    │ ─────────────▶ │ FastAPI 单体后端             │ ───▶ │ PostgreSQL │
│ (AntD)       │   JWT Bearer   │ routers → services → models │      └────────────┘
└──────────────┘                │        │                    │
                                │        ▼ 领域事件(进程内)     │
                                │  ┌─────────────────────┐    │
                                │  │ event_bus           │    │
                                │  │ ├─ point_engine     │──▶ point_entry
                                │  │ ├─ notifier         │──▶ notification_outbox → in_app
                                │  │ └─ process_engine   │──▶ process_instance/task
                                │  └─────────────────────┘    │
                                └─────────────────────────────┘
```

**关键决策**：

1. **单体后端**，按域分模块，不做微服务——单团队规模下微服务只增加复杂度。
2. **领域事件为进程内同步分发**（同一事务提交），三个订阅者：积分引擎、通知器、流程引擎。发件箱表是未来外部系统（飞书/n8n）的异步挂接点。
3. 前后端分离单仓库（monorepo），一次部署。

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

### 4.1b 飞书服务台交接与可靠同步（M45/M46）

```text
POST /api/integrations/feishu/helpdesk/events
    # 飞书事件 URL verification；校验管理员配置的 Verification Token
POST /api/integrations/feishu/helpdesk/card-callback
    # 飞书 2.0 动态卡片回调；token 可能在 header.token 或 event.token
    # event.action.value={action:create_service_request|create_requirement,ticket_id}
POST /api/integrations/feishu/helpdesk/cards
    # 兼容/兜底接口：受信任机器人调用，向工单 guest.open_id 发送分流选择卡片
POST /api/integrations/feishu/helpdesk/handoffs
    # 仅服务端/机器人调用；Header: X-Lark-Helpdesk-Authorization=base64(helpdesk_id:helpdesk_token)
    # body: {ticket_id, action: service_request|requirement}
GET /api/integrations/feishu/helpdesk/handoffs/{token}
    # 当前登录用户读取一次性交接上下文；必须与工单 guest 的 Feishu open_id 一致
    # issued 返回预填上下文；consumed 返回已关联 entity_type/entity_id，供前端幂等跳转
POST /api/integrations/feishu/helpdesk/handoffs/{token}/consume
    # 正常创建单据后消费，body: {entity_type: ticket|requirement, entity_id}；重复消费仍返回 409
POST /api/integrations/feishu/helpdesk/intakes/{intake_id}/handoff
    # 原会话稳定入口在用户登录后调用；body: {action: service_request|requirement}
    # 校验登录账号、待分流记录与实时工单 guest 的 open_id 后才签发短时令牌
GET /api/integrations/feishu/helpdesk/intakes
    # admin/CIO/IT 管理角色查看分流状态及入口投递渠道/时间/消息 ID
GET /api/integrations/feishu/helpdesk/sync-events
    # 查看事件入站队列的 processed/pending/failed 与重试次数
POST /api/admin/feishu-config/subscribe-helpdesk-events
    # 仅管理员；为当前配置的应用注册服务台事件流
```

主路径由原服务台会话中的 `/feishu/helpdesk/entry?intake=...&action=...` 稳定链接开始。该链接不含 open_id、服务台凭据或一次性令牌；公开入口只负责引导登录，随后调用 `POST /intakes/{intake_id}/handoff`。服务端重新读取工单并完成三方 open_id 比对后，才返回带短时令牌的 `entry_url`。`POST /handoffs`、`POST /cards` 和卡片回调保留给受信任中间层与独立机器人兜底。

交接读取采用幂等查看语义：首次打开且令牌为 `issued` 时返回预填字段；成功建单后令牌变为 `consumed`，同一 Feishu 身份再次读取时返回已关联单据并由前端直接跳转。身份不匹配仍返回 403，过期返回 410，`POST /consume` 的二次消费仍返回 409，从而兼顾重复打开体验与防重复建单。

服务台 Token 只在后端加密保存和调用；`handoff_token` 只保存哈希，原始工单快照仅包含预填字段。ITOM 兼容飞书工单详情的 `customized_fields`（`key_name`/`display_name`/`value`），将标题、紧急程度、服务类别、问题描述和其他补充信息映射到 `prefill`；接单客服同时兼容单个 `agent`、`service_agent`、`assignee` 和多人 `agents` 数组，数组场景使用首个客服 ID 建立关联并汇总客服姓名展示，以正确触发人工服务阶段。服务类别返回下拉选项内部 UUID 时，后端读取服务台字段配置的 `dropdown_options` 将其转换为显示名称。服务类别写入 `prefill.service_category`，服务请求页可按服务目录/服务项匹配；需求页只保留来源信息，不能自动填充 `business_domain_id`。
稳定入口的公网根地址优先取后端环境变量 `ITOM_PUBLIC_URL`，未配置时从完整的 `helpdesk_event_url` 提取协议与域名；本地通过 ngrok 或反向代理接入飞书时必须确保该根地址是员工可访问的 HTTPS 地址。稳定入口每次成功核验后会先使同一飞书工单此前未消费的令牌失效，再签发新令牌。兼容的动态卡片回调仍校验 Verification Token、卡片动作和点击人的 `event.operator.open_id`，并用回调事件 ID 做幂等。
服务请求创建接口保留询前单语义：`service_category` 保存 ITSM 服务目录名称，`other_info` 保存询前单其他补充信息；两者与 `remarks`（内部备注）分开。普通业务用户仅提交询前单字段，IT 内部角色/管理员可额外提交 `assignee` 与 `remarks`。服务类别不写入需求 `business_domain_id`。
可靠同步采用“事件入站 + 详情重读 + outbox 出站”三段式：`helpdesk.ticket.created_v1`、`helpdesk.ticket.updated_v1` 和 `helpdesk.ticket_message.created_v1` 先以唯一 `event_id` 入库，后台每 5 秒消费，按指数退避最多重试 8 次；消费时通过服务台 API 重读工单当前详情，创建/更新待分流记录，并在人工客服阶段入队一个 `routing_prompt`。出站先尝试通过服务台工单消息接口发送富文本链接，不兼容则立即降级为包含完整 URL 的文本；若返回 `99991672`/缺少 `helpdesk:all`，这是确定性的权限问题，不等待指数重试，立即改用应用机器人发送兜底卡片/文本；其他暂时性错误才保留两次重试，随后才使用独立应用机器人卡片。最终渠道、发送时间和飞书消息 ID 回写待分流记录或 outbox 供管理员审计。ITOM 单据只有在分流令牌消费后才与待分流记录关联；仅停留在“待分流”时，飞书关单或评价不会凭空生成正式 ITOM 单据。服务请求沿现有 `sr_flow` 三节点执行：受理确认 → 实施交付 → 用户确认关闭；无需新增“人工分流”节点。流程任务自动指派、流程内改派统一发布 `ticket.assigned`，改派同时更新工单展示字段与当前流程任务的权威处理人，并通知新处理人；若建单先于交接关联，消费交接令牌时会补发当前节点分派；最后一个 `requester` 节点完成时发布 `ticket.user_confirmed`，随后按既有状态机进入 `resolved`、`closed`。反向同步同样通过状态机完成：飞书 `status=51` 表示人工关闭，`status=50` 表示机器人关闭，`solve=2` 表示已解决；若详情事件表明用户已确认，ITOM 会完成当前 `requester` 任务；若飞书只发送已关闭状态，则 ITOM 沿可达闭环路径执行关单，不直接写状态，保留流程、审计和 SLA 记录。飞书没有独立的 rated 事件，评价通过工单更新/消息事件触发详情重读，再从满意度数字或“你的打分为：满意/一般/不满意”结果文案写入关联 `Ticket.satisfaction` 并发布 `ticket.satisfaction_rated`，不会把包含全部选项的评价提示误判为结果。内部备注、审批意见和未发布信息不出站；仅登记、分派、处理中、用户确认、已完成、关闭及评价确认等用户可见节点进入 outbox 并回写原会话。管理员须先在飞书开放平台配置公网回调地址、开通 `helpdesk:all`（用于原服务台会话消息）、添加上述三个服务台事件并发布应用，再在 ITOM 点击“订阅服务台事件”。订阅 API 的 `events` 请求体按飞书线上格式提交 `{type, subtype}` 对象数组，而不是完整事件 Key 字符串；字段校验失败时保留 `field_violations` 与 `log_id` 供排障。配置页会显示订阅成功/失败、入口渠道及最近错误，管理员可通过上述两个查询接口排查积压、失败和最后错误。

### 4.2 ITSM

```text
GET/POST /api/tickets | GET/PATCH /api/tickets/{id}
POST /api/tickets/{id}/transition        # 含审批(approve/reject)、解决、关闭、挂起、重开
POST /api/tickets/{id}/satisfaction      # requester 评价
POST /api/tickets/{id}/escalate-problem  # 一键升级为问题
POST /api/tickets/{id}/to-knowledge      # 一键沉淀知识(草稿)
GET/POST/PATCH /api/problems | POST /api/problems/{id}/transition
GET/POST/PATCH /api/catalogs | /api/service-items。目录列表返回 `item_count` 及按状态拆分的 `published_item_count`、`unpublished_item_count`；服务项 GET 支持 `catalog_id`、`q`（编号/名称/类型/服务对象/负责人关键字）、`status`（上架/下架，未传表示全部）、`sort_by` 与 `sort_dir` 参数，列表页据此实现筛选和排序。
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
| ticket.resolved | 解决 | →积分(工单解决)、→通知(提交人) |
| ticket.closed | 关闭 | →积分(SLA 双达成时加分) |
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

定时任务（后端内置 scheduler，每 15 分钟）：SLA 临期扫描、合同到期扫描、里程碑逾期扫描、合同状态推进。

## 6. 关键实现机制

1. **状态机**：`services/workflow.py` 统一入口 `transition(entity, to, fields, actor)` —— 查 workflow_transition 校验角色与合法性 → 校验该转换的必填阶段字段 → 更新 + 打点 → 发事件 → 写审计。所有单据共用。
2. **积分引擎幂等**：point_entry 建 UNIQUE(event_type, source_entity_type, source_entity_id, person)，同一单据同一事件不重复计分（重开再解决不二次得分）。
3. **计算列维护**：wbs_task/cost_entry/milestone 写操作后，service 层重算所属 project 的 progress_pct/actual_cost/health_status 写回（同事务）。WBS `progress` 接受 0-100 的整数百分比；流程步骤通过 `node_type=processing|approval` 区分处理/审批语义。审批任务可调用 `POST /api/process-tasks/{id}/approve`（理由可选）或 `POST /api/process-tasks/{id}/reject`（理由必填），完成入口仍支持流程图中的“完成此步骤”。
4. **章程导入两步**：解析接口只返回草稿 JSON + warnings（不落库）；前端展示确认页，用户修正后调创建接口落库。解析失败回退手工表单。
5. **SLA 计时**：挂起时累计 paused_minutes，达成判定 = (resolved_at − submitted_at − paused) ≤ 目标。
6. **矩阵角色人效评审**：系统先从 ITSM、需求、项目、流程和积分事件生成参考分；业务线负责人只能写入业务角色初评，专业线负责人只能写入专业角色初评，平台角色和各类负责人本人由 CIO 直接评分。后端按 `performance_role_assignment.review_scope` 做范围校验，不能只依赖前端隐藏按钮。
7. **外部原数据与发布隔离**：外部业务满意度先写入 `performance_external_input`，完成提交/核验/锁定后才参与折算；`performance_score_component` 保存系统参考分、阶段建议分和生效分，`/api/my/performance` 只返回已发布快照。
8. **积分分桶**：`point_rule`/`point_entry` 通过 `contribution_bucket=role_result|team_contribution` 区分岗位结果与团队贡献；已经进入角色结果指标的事实不得再次进入固定 20% 团队贡献。

## 7. 部署架构

```yaml
# deploy/docker-compose.yml 形态
services:
  db:        postgres:16  (volume + 每日 pg_dump 到宿主机备份目录)
  backend:   uvicorn, 依赖 db, 启动时 alembic upgrade + seed(幂等)；`SEED_INITIAL_CONFIG=1` 时在全新数据库初始化六条流程定义以及已验证的登录页/Logo 品牌配置，已有品牌草稿或发布版本不会覆盖
  frontend:  nginx 托管构建产物, /api 反代 backend
```

- 环境变量：`DATABASE_URL`、`JWT_SECRET`、`ADMIN_INIT_PASSWORD`、`TZ=Asia/Shanghai`。
- IDC Kubernetes 是当前唯一交付与验收环境：使用 `deploy/k8s/push-images.sh` 构建/推送镜像，再执行 `deploy/k8s/k8s-deploy.sh` 发布；发布后通过外部域名健康检查和实际页面验证。Docker Compose 仅保留为本地临时排障环境。
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

人员选择器统一约定：涉及业务负责人、项目经理/任务负责人、需求负责人/评审人/开发负责人、工单/问题/服务项/配置项/合同负责人、用户组负责人/成员及账号关联人员的前端下拉，统一调用 `GET /api/members?scope=it`。管理员配置任一数字化团队部门或指定人员后，相关写接口也通过 `require_it_member_if_configured`（批量成员使用同等校验）复核；未配置范围时兼容历史数据，但不改变 `scope=it` 的返回口径。

`PATCH /api/admin/users/{id}` 对可空字段采用显式 PATCH 语义：请求省略 `person_id` 时不改变关联人员，提交 `person_id: null` 时解除关联并在响应、审计及后续列表查询中立即体现。

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
