# IT 运营管理平台 / IT Operations Platform

> 项目代号 `ITOM`（曾用名 New_AOM，2026-07-14 更名；基于 SN-AOM 简化重构）。内部技术标识（数据库名 new_aom、日志前缀 aom.*、前端存储键 aom-*）沿用不变。中英双语文档；中文为准，English section below.

面向 IT 团队的轻量运营管理平台，覆盖 6 个域：**总览 / ITSM 服务 / 项目管理 / 需求管理 / 流程引擎 / 团队管理**。
核心设计原则：创建表单必填 ≤5、派生数据零录入（无预计算表）、事件驱动（积分 + 通知同一出口）。

A lightweight operations-management platform for IT teams, covering 6 domains:
**Dashboard / ITSM / Projects / Requirements / Process engine / Team management**.
Design principles: ≤5 required fields per create form, zero manual entry for derived data, event-driven (points + notifications share one outbox).

---

## 中文

### 技术栈
- 后端：FastAPI + SQLAlchemy 2.0 + PostgreSQL 16（Python 3.12）+ MCP Python SDK 1.29
- 前端：React 18 + TypeScript + Ant Design v5 + Zustand + Vite
- 部署：Docker Compose / IDC Kubernetes（Nginx 托管前端，同时反代 `/api` 与 `/mcp`）
- 主键：26 位 ULID（GLID）；业务编号 `前缀-YYYYMM-序号`（TK/PB/KB/PJ/RQ/ID…）

### 架构简介
```
浏览器 SPA (React + AntD)
   │  /api/*（统一响应包 {success,data,error}）
   ▼
Nginx（容器 frontend:80 → 宿主 8180）── 静态托管 dist + 反代 /api、/mcp
   ▼
FastAPI（容器 backend:6800，uvicorn）
   ├─ routers/   一域一文件（权限守卫 require_perm / 流程守卫）
   ├─ services/  领域逻辑（权限矩阵、流程引擎、SLA、评分、org_sync、seed、migrate）
   ├─ mcp/       Aily JWT、外部身份映射、Streamable HTTP 与工具审计
   ├─ events/    事件总线 + 通知（站内 + Aily 机器人可靠发件箱）
   └─ lifespan   启动顺序：建表 → 增量迁移 → 幂等种子 → MCP 会话 → 调度器
   ▼
PostgreSQL 16（容器 db，卷持久化）
```
关键机制：单据（工单/问题/需求/项目）创建即挂接流程实例，状态由流程编排自动同步（详见「关键概念」）；
权限=功能矩阵×数据范围×流程节点三层；飞书组织同步、扫码登录继续保留。`feature/aily-agent-mcp` 已完成 P0 底座：清除服务台运行路径、内嵌 `/mcp`、Aily JWT 与精确身份映射、脱敏工具审计和机器人可靠发件箱，并已通过真实 Aily + ngrok 身份调用。P1 的服务目录搜索、动态表单和正式建单工具尚未实现；ITOM 始终是服务目录、表单、流程和权限的唯一事实来源，详见 [`docs/10-Aily-MCP版本交接与决策上下文.md`](docs/10-Aily-MCP版本交接与决策上下文.md)。

### 本地启动（Docker）
```bash
cd deploy && docker compose up --build
# 前端 http://localhost:8180   API 文档 http://localhost:8180/api/docs
# 初始管理员 admin / 密码见 deploy 环境变量 ADMIN_INIT_PASSWORD（默认 admin123）
# 全新数据库默认 SEED_INITIAL_CONFIG=1：自动初始化六条流程定义及当前登录页/Logo；已有品牌配置不会覆盖
# Aily + MCP 开发期由 ngrok 暴露完整 127.0.0.1:8180；同一 HTTPS 根地址承载前端、/api、OAuth 回调和 /mcp
# 首次注册先启用 MCP 并配置 Origin；Aily 创建后再回填其 JWT Secret、租户/Agent 白名单和外部身份映射
# 存量冻结版数据库先预览清理：docker compose exec backend python -m app.scripts.migrate_aily_mcp
# 确认后执行：docker compose exec backend python -m app.scripts.migrate_aily_mcp --confirm
```

### 本地开发
```bash
# 后端
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 6800
pytest -q                       # 全量测试

# 前端
cd frontend && npm ci && npm run dev   # http://localhost:5180，/api 代理到 6800
npm run build                          # tsc --noEmit + vite build（提交前必须 0 错误）
```

### 生产部署

> 正式发布仍以 IDC Kubernetes 为最终验收环境。当前 IDC 基础设施阻塞期间，用户已明确授权 Aily + MCP 使用本地 Docker + ngrok 开发和真实租户联调；这不替代 IDC 恢复后的最终发布验收。
```bash
# 1) 准备环境变量（首次）
cd deploy && cp .env.example .env
vi .env   # 必改：DB_PASSWORD、JWT_SECRET、ADMIN_INIT_PASSWORD

# 2) 构建并启动（Nginx 8180 端口，可在 docker-compose.yml 调整映射）
docker compose up -d --build

# 3) 首次登录 admin/<ADMIN_INIT_PASSWORD> → 系统管理→系统集成 配置飞书、邮件与 AD/LDAP
```

邮件服务器与 AD/LDAP 均在“系统管理→系统集成”维护，敏感密码加密入库，不再依赖部署环境变量。
- **升级发布**：`git pull && docker compose up -d --build backend frontend`——启动时自动执行增量迁移与幂等种子，无需手工 SQL；数据库容器不重建。
- **备份**：`docker compose exec db pg_dump -U aom new_aom > backup_$(date +%F).sql`；恢复用 `psql -U aom new_aom < backup.sql`（先停 backend）。
- **数据卷**：PostgreSQL 数据在 compose 卷中，`docker compose down` 不加 `-v` 即保留。
- **反向代理接入**：如需域名+HTTPS，在宿主 Nginx/网关上反代 `8180` 即可；飞书扫码回调地址需同步在飞书后台登记新域名。

### 目录结构
```
backend/app/
  models/        SQLAlchemy 模型（support 身份/组织、itsm、project、requirement、team、process）
  routers/       FastAPI 路由（一个域一个文件）
  services/      领域逻辑（permissions 权限矩阵、perf 人效引擎、points 积分、
                 org_sync 飞书同步、seed* 种子、migrate 增量补列、excel_io 导入导出）
  events/        事件总线 bus + notifier（站内 + 发件箱，飞书通道未来挂接点）
  core/          security（JWT/bcrypt）、errors（AppError）、config
  main.py        应用装配 + lifespan（建表 → 迁移 → 种子 → 订阅 → 调度器）
frontend/src/
  pages/         按域分目录的页面
  components/     MainLayout、menu、可复用组件（FlowDiagram/GanttChart/WidgetBoard…）
  i18n/          自研轻量双语（store 语言状态 / dict 字典 / index useT / AppRoot locale）
  stores/        Zustand（auth）
  api/           axios 客户端（统一 envelope 解包）+ types
docs/            中文设计文档（01-09）；docs/en/ 为英文译本
deploy/          docker-compose、Nginx、备份
```

### 关键概念
- **统一响应包**：`{success, data, total?, page?, error?}`；错误经 `AppError(code, message, status)` 返回中文提示。
- **权限三层**：① 功能矩阵（`role_permission` 表，模块 × 动作 view/create/edit/delete，`require_perm` 守卫，admin 隐式全权）；② 数据范围（业务代码内置，如 requester 仅见自己的工单/需求）；③ 流程权限（状态机 `allowed_roles` + 流程步骤 `default_role`）。
- **流程驱动状态**：现有 ITOM 仍按 M23–M31 自动同步；P2 将服务请求的“IT 人员标记已解决”和“提交人确认关闭”拆开，未解决时重回处理中。事件仍为 IT 内部/监控来源，普通用户不能创建。
- **流程节点语义**：每个节点可配置为处理节点或审批节点，并分别配置处理人与知会人。审批节点支持详情右上角“同意/驳回”或流程图“完成此步骤”同意；同意理由可选，驳回理由必填并留痕。WBS 任务完成度支持管理员/负责人直接录入 0–100% 整数；显式将父项设为 100% 会向下级联，子项修改后父项按直接子项平均值递归回算，项目进度仅按末级任务工期加权汇总。
- **全局表格交互**：所有超出内容区宽度的表格统一提供一条底部悬浮横向滚动条，页面纵向滚动时表头保持悬浮；WBS 额外支持前三列冻结。
- **列表分页**：分页器的页大小为受控状态，统一支持 10/20/50/100 条；服务项等前端本地分页表格切换页大小不会被固定默认值覆盖，服务端分页列表同步传递 `page_size`。
- **WBS 表格交互**：WBS 宽表支持 Excel 式冻结窗格（表头 + 左侧前三列）、底部悬浮横向滚动条、列宽与行高拖拽调整；完成度提供 0%/50%/100% 预设并支持自定义 0–100% 整数；父子任务进度自动级联/汇总；布局按项目保存在当前浏览器。
- **关闭策略**：服务请求/需求/项目登记人可主动关闭（理由必填≥5 字、审计留痕）；事件/变更/问题必须流程闭环；强制关闭仅系统管理员。
- **矩阵式组织**：横向业务域（服务线，新建时可从组织架构选择服务部门并覆盖下级部门；负责人、备份负责人和服务团队取自管理员配置的“数字化团队范围”）× 纵向用户组（资源池，组授予角色）；一人多角色；admin 不可经组/规则授予。数字化团队范围是所选部门成员与单独指定人员的并集，可从 Test 等混合供应商组织中只纳入目标外包人员。所有业务人员下拉选择统一通过 `/api/members?scope=it` 加载，并由后端在已配置范围后复核。无需求引用的业务域可由管理员删除。
- **飞书为人员主数据 SoT**：`org_sync` 幂等应用组织快照（外部赢、消失→离职），本地仅可编辑岗位/技能/备注/部门类型；同步范围可配置（部门 open_department_id 列表或 0=全公司，M32），管理员可独立启停自动同步并选择每 1/6/12/24 小时执行。
- **示例数据**：`GlidBase.is_example`（列表置顶）；编辑、状态流转和业务操作仍只读，系统管理员可在列表页明确删除示例记录；默认不种，`SEED_EXAMPLES=1` 开启（测试用）。
- **考核周期**：季度制 `YYYY-Q1/Q2/Q3`，第四季度执行全年考核 `YYYY-All`（统计范围为本年度全年）。
- **帮助中心式用户操作手册**：右上角语言切换按钮左侧提供“操作手册”入口，采用搜索优先、按产品分类、热门/最近文档、文章内目录和相关文档的帮助中心结构；内容覆盖系统总体介绍、通用列表规则、全部业务/管理模块的运作逻辑、操作步骤、角色边界和常见问题。中文权威版本为 `docs/用户操作手册.md`，英文译本为 `docs/en/user-operation-manual.md`。
- **矩阵角色人效评分**：人效总览使用当前矩阵角色结果（角色职责结果 80% + 团队贡献 20%），支持 ITSM/需求/项目/流程自动取数、负责人分级初评、CIO 终审、外部原数据录入和发布后个人结果隔离；同一角色可配置多名评审人及独立权重，评审结果按权重汇总。外部满意度仅按业务服务域录入，外部指标采用白名单校验；团队贡献维度、目标积分及内外部满意度比例由 CIO/管理员配置，并在考核周期生成规则快照。旧版岗位计分方案接口仅保留历史客户端兼容，不再作为总览数据源。
- **积分规则配置**：团队管理→活动积分→积分规则维护团队贡献活动的自动事件分值、启停状态、维度权重、目标积分和满意度组合；仅 admin/CIO 可修改。团队管理→人效评分→计分规则只维护岗位角色档案、角色维度、取数口径和权重，不混入团队贡献活动。规则修改写入审计日志，仅影响后续事件/考核周期，历史积分台账和已发布周期不自动重算。
- **双语**：语言存 `auth_user.preferences.language`（zh/en）；登录即应用，用户可自行切换；飞书开通时由管理员设默认语言。
- **Aily + MCP 正式基线**：P0 已完成 MCP 内嵌、首次注册协议发现、Aily JWT/Origin/租户/Agent 校验、精确 ITOM 用户映射与脱敏审计。协议发现不执行工具；任何 `tools/call` 仍必须完整验签和授权。P1 再实现普通员工只创建 IT 服务请求或登记 IT 需求，以及实时服务项、动态表单、SLA、流程和派单。
- **服务闭环与主动消息**：P0 已实现可靠 outbox 和 Aily 机器人测试发送；P2 再接入解决通知、确认关闭、未解决重开和评价。飞书服务台运行路径、配置、模型、页面和专用测试已全部移除，历史版由标签 `v1.0.0-feishu-helpdesk` 恢复。
- **站内通知**：顶栏铃铛显示当前账号可见通知；弹窗提供“一键已读”和“清除已读”，前者批量写入已读回执，后者软删除当前账号已读通知，均不修改源业务单据。
- **飞书扫码登录 + 开通审批**：管理员批准时生成 12 位高强度初始密码并加密保存，但不自动发信。管理员可在用户详情点击闭眼图标按需查看，或点击“邮件发送”手工投递；查看与发送均审计，用户改密/管理员重置后密文立即清除。

### 分支与协作
- `main`：稳定分支，受保护——只接受 Pull Request 合入，禁止直推（本地 pre-push 钩子拦截；紧急放行 `ALLOW_MAIN_PUSH=1 git push`）。
- `develop`：日常开发集成分支；功能开发从 `develop` 拉 `feature/<名称>` 分支，完成后 PR 合回。
- `release/feishu-helpdesk-v1` 与标签 `v1.0.0-feishu-helpdesk`：飞书服务台版本的冻结基线；标签固定在提交 `f13f702`，不得重写。
- `feature/aily-agent-mcp`：基于上述冻结基线的新版本开发线；方案背景、架构边界和新会话启动要求见 [`docs/10-Aily-MCP版本交接与决策上下文.md`](docs/10-Aily-MCP版本交接与决策上下文.md)，完成后由用户确认并通过 Pull Request 合入 `main`。
- 首次 clone 后启用钩子：`git config core.hooksPath scripts/git-hooks`。
- 提交前自检：后端 `pytest -q` 全绿、前端 `npm run build` 零错误；按改动影响同步更新 `README.md`、`docs/03–06` 及对应英文译本。
- **交付完成定义**：代码实现、测试与受影响说明文档必须相互一致；功能、接口、数据模型、配置、部署、权限或用户流程发生变化但文档未同步时，不得视为完整交付。仓库级执行规则见 [`AGENTS.md`](AGENTS.md)。

### 里程碑
M1 骨架+RBAC → M2 工单+SLA+流程引擎 → M2.5 自配置 → M3 CMDB/问题/供应商/合同/知识 → M3.5–3.10 身份治理/权限矩阵/组织树/飞书 SoT/批量导入 → M4 项目 → M5 需求 → M6 团队（活动积分/人效/培训/文化/流程监控/Dashboard）→ M7 双语 i18n + 飞书扫码登录开通审批 → M9 甘特图 → M10 需求六维评分+四象限 → M11 飞书组织同步+真实扫码 OAuth → M12–15 项目管理实战打磨（行内操作/章程结构化/级联删除/流程版本管理）→ M16 需求路由闭环（评审→方案评估→转开发/转项目→验收自动闭环）→ M17 导航二级菜单+权限模块按页拆分 → M18–25 流程权限体系（任务处理人守卫/待办通知/流程完成自动闭环/状态-流程双向同步/操作权跟随节点处理人/未指派认领）→ M26–28 交互与关闭策略定稿（原路返回/登记人关单+理由审计/强关仅 admin）→ M29 SLA 优先级定义（ITIL 初稿可编辑）+ 问题管理专业线流程 → M30–31 状态按钮白名单+列表「待我处理」列 → M32 飞书同步范围可配置（多部门/全公司）→ M33 用户调试版流程与权限固化为出厂默认 → M34–35 通知直达+异步全员组织同步 → M36–36.2 账号治理、飞书免登与个人中心 → **M37 个人设置（通知偏好、个人操作记录、飞书绑定管理、明暗主题与内容密度）**。
M45–M46 是冻结版 Helpdesk 历史里程碑，仅保留在 `v1.0.0-feishu-helpdesk`。新开发线依次执行 Aily-MCP P0（移除 Helpdesk、协议/身份/消息）→ P1（真实服务目录、动态表单、服务请求/需求登记、派单）→ P2（解决通知、确认/重开、评价闭环）→ P3（飞书审批与 IDC 正式发布）。

验收基准为 `docs/03-PRD.md` 对应章节 + 各里程碑提交说明；实现细节以代码与测试为准。

---

## English

### Tech stack
- Backend: FastAPI + SQLAlchemy 2.0 + PostgreSQL 16 (Python 3.12) + MCP Python SDK 1.29
- Frontend: React 18 + TypeScript + Ant Design v5 + Zustand + Vite
- Deploy: Docker Compose / IDC Kubernetes (Nginx serves the SPA and proxies both `/api` and `/mcp`)
- Primary keys: 26-char ULID (GLID); business codes `PREFIX-YYYYMM-seq` (TK/PB/KB/PJ/RQ/ID…)

### Architecture at a glance
```
Browser SPA (React + AntD)
   │  /api/* (uniform envelope {success,data,error})
   ▼
Nginx (container frontend:80 → host 8180) ── serves dist + proxies /api and /mcp
   ▼
FastAPI (container backend:6800, uvicorn)
   ├─ routers/   one file per domain (require_perm / process guards)
   ├─ services/  domain logic (permission matrix, process engine, SLA, scoring, org_sync, seed, migrate)
   ├─ mcp/       Aily JWT, external identity, Streamable HTTP, and tool audit
   ├─ events/    event bus + notifier (in-app + reliable Aily-bot outbox)
   └─ lifespan   startup: create tables → migrate → seed → MCP session → scheduler
   ▼
PostgreSQL 16 (container db, persistent volume)
```
Key mechanics: every ticket/problem/requirement/project gets a process instance on creation and its
status is synced by orchestration (see Key concepts); permissions = functional matrix × data scope ×
process-step operator. Feishu org sync and QR sign-in remain. `feature/aily-agent-mcp` has implemented the P0 embedded-MCP, identity, audit, and bot-outbox foundation and passed a real Aily + ngrok identity call, while ITOM remains the sole source for catalog, forms, workflow, and authorization. P1 business tools are not implemented yet.

### Run locally (Docker)
```bash
cd deploy && docker compose up --build
# Web  http://localhost:8180   API docs http://localhost:8180/api/docs
# Bootstrap admin: admin / password from the deploy env var ADMIN_INIT_PASSWORD (default admin123)
# During Aily + MCP development, ngrok exposes the complete 127.0.0.1:8180 origin for the web app, /api, OAuth callback, and /mcp endpoint.
# For first registration, enable MCP with an Origin; after Aily creates it, copy back the JWT secret and configure tenant/agent allowlists and identity mappings.
# Preview frozen-schema cleanup: docker compose exec backend python -m app.scripts.migrate_aily_mcp
# Execute only after review: docker compose exec backend python -m app.scripts.migrate_aily_mcp --confirm
# Fresh databases default to SEED_INITIAL_CONFIG=1, which initializes the six workflows and the verified login/Logo branding; existing branding is never overwritten.
```

### Local development
```bash
# Backend
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 6800
pytest -q                       # full test suite

# Frontend
cd frontend && npm ci && npm run dev   # http://localhost:5180, /api proxied to 6800
npm run build                          # tsc --noEmit + vite build (must be 0 errors before commit)
```

### Production deployment

> IDC Kubernetes remains the final release-acceptance environment. While the current IDC infrastructure is blocked, the user explicitly authorizes local Docker + ngrok for Aily + MCP development and real-tenant integration; final IDC acceptance is still required after recovery.
```bash
# 1) Prepare env vars (first time)
cd deploy && cp .env.example .env
vi .env   # must change: DB_PASSWORD, JWT_SECRET, ADMIN_INIT_PASSWORD

# 2) Build & start (Nginx on port 8180; adjust the mapping in docker-compose.yml)
docker compose up -d --build

# 3) First login admin/<ADMIN_INIT_PASSWORD> → System Admin → System Integrations
```

Email and AD/LDAP settings are managed in System Admin → System Integrations; secrets are encrypted in the database rather than deployment environment variables.
- **Upgrade**: `git pull && docker compose up -d --build backend frontend` — incremental migration and
  idempotent seeding run automatically at startup; the db container is untouched.
- **Backup**: `docker compose exec db pg_dump -U aom new_aom > backup_$(date +%F).sql`; restore with
  `psql -U aom new_aom < backup.sql` (stop the backend first).
- **Data volume**: PostgreSQL data lives in a compose volume; `docker compose down` without `-v` keeps it.
- **Reverse proxy**: to add a domain + HTTPS, proxy host `8180` from your gateway; remember to register
  the new domain's Feishu callback URL in the Feishu console.

### Directory layout
```
backend/app/
  models/        SQLAlchemy models (support = identity/org, itsm, project, requirement, team, process)
  routers/       FastAPI routers (one file per domain)
  services/      Domain logic (permissions matrix, perf scoring engine, points ledger,
                 org_sync Feishu sync, seed* seeders, migrate column-backfill, excel_io import/export)
  events/        Event bus + notifier (in-app + outbox; the outbox is the Feishu-push hook point)
  core/          security (JWT/bcrypt), errors (AppError), config
  main.py        App wiring + lifespan (create tables → migrate → seed → subscribe → scheduler)
frontend/src/
  pages/         Pages grouped by domain
  components/     MainLayout, menu, reusable components (FlowDiagram/GanttChart/WidgetBoard…)
  i18n/          In-house lightweight bilingual (store = language state / dict / index useT / AppRoot locale)
  stores/        Zustand (auth)
  api/           axios client (unwraps the response envelope) + types
docs/            Chinese design docs (01-09); docs/en/ holds the English translations
deploy/          docker-compose, Nginx, backups
```

### Key concepts
- **Response envelope**: `{success, data, total?, page?, error?}`; errors are raised as `AppError(code, message, status)`.
- **Three permission layers**: (1) functional matrix (`role_permission` table, module × action view/create/edit/delete, guarded by `require_perm`; `admin` is implicitly all-powerful); (2) data scope (baked into business code, e.g. a `requester` only sees their own tickets/requirements); (3) process permissions (state-machine `allowed_roles` + process-step `default_role`).
- **Process-driven status**: current ITOM still follows M23–M31 automation. P2 separates “resolved by IT” from “closed after requester confirmation” for service requests; rejection returns the request to processing. Incidents remain IT/monitoring-originated and cannot be created by normal users.
- **Process-node semantics**: each node can be configured as processing or approval with separate handler and CC parties. Approval nodes support approve/reject from the detail-page actions or approve through the flow diagram; approval comments are optional, rejection reasons are mandatory and retained. WBS task completion accepts an integer percentage from 0–100; explicitly setting a parent to 100% cascades to all descendants, child changes roll up as direct-child averages, and project progress is duration-weighted over leaf tasks only.
- **Global table interaction**: every table wider than the content area exposes one sticky bottom horizontal scrollbar and keeps its header visible during vertical page scrolling; the WBS table additionally freezes the first three columns.
- **List pagination**: page-size selectors are controlled state everywhere and consistently support 10/20/50/100 rows; local-paginated tables such as Service Items no longer reset a selected size to a hard-coded default, while server-paginated lists pass the selected `page_size` to the API.
- **WBS table interaction**: the wide WBS table provides an Excel-style freeze pane (header plus the first three columns), one sticky bottom horizontal scrollbar, draggable column widths and row heights; completion offers 0%/50%/100% presets plus a custom integer from 0–100%; parent/child progress cascades and rolls up automatically; layout is saved per project in the current browser.
- **Closure policy**: submitters may close their own service requests / requirements / projects (reason ≥5 chars, audited); incidents/changes/problems must complete the flow; force close is admin-only.
- **Matrix organization**: horizontal business domains (served departments are selected from Org Structure with optional descendant coverage; owner, backup owner, and service-team selectors use the administrator-defined digital-team scope) × vertical user groups. The scope is the union of selected department members and individually selected people, allowing a mixed vendor organization to contribute only named contractors. All operational person selectors (projects, requirements, tickets, problems, service items, CIs, contracts, groups, and account linking) load `GET /api/members?scope=it`, with server-side revalidation after the scope is configured. Administrators may delete domains that have no requirement references.
- **Feishu is the Source of Truth for people master data**: `org_sync` idempotently applies an org snapshot (external wins, missing → offboarded/inactive); locally only position/skills/remarks/dept-type are editable. Besides the remote sync scope, administrators can enable/disable scheduled sync and choose a 1/6/12/24-hour interval.
- **Aily + MCP baseline**: P0 implements embedded MCP, first-registration protocol discovery, Aily JWT/origin/tenant/agent checks, exact ITOM-account mapping, and redacted audit. Discovery cannot execute tools; every `tools/call` still requires full authentication and authorization. P1 adds employee service-request/requirement tools backed by live catalog, forms, SLA, workflow, dispatch, and authorization.
- **Closure and proactive messaging**: P0 implements the reliable outbox and Aily-bot test delivery; P2 connects resolution updates, confirmation/reopen, and rating. All Helpdesk runtime/configuration/models/pages/tests are removed; the historical version remains under `v1.0.0-feishu-helpdesk`.
- **Example data**: `GlidBase.is_example` (pinned to the top of lists); editing, workflow transitions, and business actions remain read-only, while administrators can explicitly delete examples from list pages; not seeded by default, enable with `SEED_EXAMPLES=1` (used by tests).
- **Assessment period**: quarterly `YYYY-Q1/Q2/Q3`; Q4 runs the full-year assessment `YYYY-All` (statistics cover the whole calendar year).
- **Point-rule configuration**: Team Management → Activity Points → Point Rules controls team-contribution event values, activation, dimension weights, targets, and satisfaction mix; only admin/CIO can edit. Team Management → Performance → Scoring Rules owns role profiles, role dimensions, source mappings, and weights, with no team-activity rules mixed in. Changes are audited, affect future events/assessment periods, and never recalculate historical ledgers or published periods automatically.
- **Help-center user manual**: the signed-in header places a “User Manual” entry immediately to the left of the language switcher. It uses search-first navigation, product categories, popular/recent guides, article TOCs, and related documents while covering the system overview, all module procedures, role boundaries, and troubleshooting. The authoritative Chinese version is `docs/用户操作手册.md` and the English mirror is `docs/en/user-operation-manual.md`.
- **In-app notifications**: the top-bar bell lists notifications visible to the current account; **Mark all as read** writes read receipts in bulk and **Clear read** soft-deletes that account's already-read notifications. Neither action changes source business records.
- **Bilingual**: language is stored in `auth_user.preferences.language` (zh/en); applied on login and switchable by the user; the admin sets the default during Feishu provisioning.
- **Feishu QR sign-in + provisioning approval**: approval generates a 12-character strong initial password and stores only encrypted recoverable ciphertext without sending it. An administrator may reveal it with the eye control or manually email it from user details; both actions are audited and the ciphertext is cleared after a change/reset.

### Branching & collaboration
- `main`: stable, protected — merged via Pull Request only; direct pushes are blocked by a local pre-push hook (override with `ALLOW_MAIN_PUSH=1 git push` in emergencies).
- `develop`: day-to-day integration branch; cut `feature/<name>` branches from it and PR back.
- `release/feishu-helpdesk-v1` and `v1.0.0-feishu-helpdesk`: immutable frozen Helpdesk baseline at `f13f702`.
- `feature/aily-agent-mcp`: sole Aily + MCP development line; see the [final design baseline](docs/en/10-aily-mcp-handoff-and-decision-context.md) and merge to `main` only through a user-approved PR.
- After cloning, enable the hooks once: `git config core.hooksPath scripts/git-hooks`.
- Pre-commit checklist: backend `pytest -q` all green, frontend `npm run build` with zero errors, and affected sections in `README.md`, `docs/03–06`, and their English mirrors updated.
- **Definition of done**: implementation, tests, and affected documentation must agree. A behavior, API, data-model, configuration, deployment, permission, or workflow change without synchronized docs is not a complete delivery. See [`AGENTS.md`](AGENTS.md).

### Milestones
M1–M37 remain the existing platform history. M45–M46 are frozen Helpdesk history only. The new line proceeds through Aily-MCP P0 (remove Helpdesk; protocol, identity, messaging) → P1 (live catalog, dynamic forms, request/requirement intake, dispatch) → P2 (resolution notification, confirmation/reopen, rating loop) → P3 (Feishu Approval and IDC release).
Acceptance baseline: the matching section of `docs/03-PRD.md` plus each milestone's commit message; real code and the currently executed test evidence are the implementation source of truth.
