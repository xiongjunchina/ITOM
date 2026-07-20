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
├── deploy/                # docker-compose.yml、Dockerfile×2、nginx.conf、K8s 清单(预留)
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
GET /api/notifications | POST /api/notifications/{id}/read   # 站内通知
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

### 4.2 ITSM

```text
GET/POST /api/tickets | GET/PATCH /api/tickets/{id}
POST /api/tickets/{id}/transition        # 含审批(approve/reject)、解决、关闭、挂起、重开
POST /api/tickets/{id}/satisfaction      # requester 评价
POST /api/tickets/{id}/escalate-problem  # 一键升级为问题
POST /api/tickets/{id}/to-knowledge      # 一键沉淀知识(草稿)
GET/POST/PATCH /api/problems | POST /api/problems/{id}/transition
GET/POST/PATCH /api/catalogs | /api/service-items
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
GET/POST/PATCH /api/admin/process-definitions (含 steps 嵌套)
GET /api/process-instances?entity= | GET /api/process-monitor   # 卡点/超时聚合
POST /api/process-tasks/{id}/complete | /reassign
```

### 4.6 团队

```text
GET /api/team/overview                   # 负载/积分Top/培训数/招聘进度聚合
GET/POST/PATCH /api/positions | /api/hiring-needs
GET/POST /api/activities                 # 培训活动
GET/PUT /api/team-charter
GET/POST /api/ideas | POST /api/ideas/{id}/like | /adopt | /to-requirement
GET /api/points/leaderboard?period= | GET /api/points/mine | GET /api/points/entries?person=
GET/POST/PATCH /api/admin/point-rules
POST /api/points/adjust                  # 管理员手工调分(必填 remark)
GET/POST/PATCH /api/admin/performance-rules
GET /api/performance/scores?period= | POST /api/performance/recompute
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

定时任务（后端内置 scheduler，每 15 分钟）：SLA 临期扫描、合同到期扫描、里程碑逾期扫描、合同状态推进。

## 6. 关键实现机制

1. **状态机**：`services/workflow.py` 统一入口 `transition(entity, to, fields, actor)` —— 查 workflow_transition 校验角色与合法性 → 校验该转换的必填阶段字段 → 更新 + 打点 → 发事件 → 写审计。所有单据共用。
2. **积分引擎幂等**：point_entry 建 UNIQUE(event_type, source_entity_type, source_entity_id, person)，同一单据同一事件不重复计分（重开再解决不二次得分）。
3. **计算列维护**：wbs_task/cost_entry/milestone 写操作后，service 层重算所属 project 的 progress_pct/actual_cost/health_status 写回（同事务）。
4. **章程导入两步**：解析接口只返回草稿 JSON + warnings（不落库）；前端展示确认页，用户修正后调创建接口落库。解析失败回退手工表单。
5. **SLA 计时**：挂起时累计 paused_minutes，达成判定 = (resolved_at − submitted_at − paused) ≤ 目标。

## 7. 部署架构

```yaml
# deploy/docker-compose.yml 形态
services:
  db:        postgres:16  (volume + 每日 pg_dump 到宿主机备份目录)
  backend:   uvicorn, 依赖 db, 启动时 alembic upgrade + seed(幂等)
  frontend:  nginx 托管构建产物, /api 反代 backend
```

- 环境变量：`DATABASE_URL`、`JWT_SECRET`、`ADMIN_INIT_PASSWORD`、`TZ=Asia/Shanghai`。
- 单机 Docker Compose 起步；`deploy/k8s/` 预留 SN IDC 集群清单（后续按需）。
- 日志：结构化 JSON 到 stdout（docker logs 可查）。

## 8. 里程碑映射（开发顺序）

| 里程碑 | 后端 | 前端 | 验收基准 |
| --- | --- | --- | --- |
| M1 骨架 | core/auth/members/字典/状态机/审计/事件总线骨架/部署 | 登录、布局菜单、空 Dashboard、系统管理 | PRD §2/3/10/11 |
| M2 工单 | tickets/catalogs/service-items/sla + 流程引擎最小版 + 定时扫描 | 工单列表/详情/服务目录/SLA 看板 | PRD §5.1/5.3/5.5 |
| M3 ITSM 余下 | problems/cis/vendors/contracts/knowledge | 对应 5 页 | PRD §5.2/5.4/5.6/5.7 |
| M4 项目 | portfolios/projects/wbs/milestones/risks/costs/charter-import | 项目两标签页/详情 5 tab/甘特 | PRD §6 |
| M5 需求 | requirements/tasks/close 转出 | 需求看板/详情 | PRD §7 |
| M6 团队+总览 | points/ideas/activities/positions/performance/dashboard/流程监控 | 团队 6 页/总览/流程监控 | PRD §4/8/9 |

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

M42 新增 `GET/PATCH /api/admin/org-settings`，管理数字化团队部门范围和飞书自动同步策略；新增 `DELETE /api/admin/business-domains/{id}`，存在未删除需求引用时返回 `DOMAIN_IN_USE`（409）。定时器每 15 分钟检查一次是否到达管理员配置的同步周期，实际同步仍复用 `org_sync.run_sync`。

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
