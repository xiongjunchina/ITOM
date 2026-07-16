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
- 后端：FastAPI + SQLAlchemy 2.0 + PostgreSQL 16（Python 3.11）
- 前端：React 18 + TypeScript + Ant Design v5 + Zustand + Vite
- 部署：Docker Compose（Nginx 托管前端 + 反代 `/api`）
- 主键：26 位 ULID（GLID）；业务编号 `前缀-YYYYMM-序号`（TK/PB/KB/PJ/RQ/ID…）

### 架构简介
```
浏览器 SPA (React + AntD)
   │  /api/*（统一响应包 {success,data,error}）
   ▼
Nginx（容器 frontend:80 → 宿主 8180）── 静态托管 dist + 反代 /api
   ▼
FastAPI（容器 backend:6800，uvicorn）
   ├─ routers/   一域一文件（权限守卫 require_perm / 流程守卫）
   ├─ services/  领域逻辑（权限矩阵、流程引擎、SLA、评分、org_sync、seed、migrate）
   ├─ events/    事件总线 + 通知（站内 + 发件箱 outbox，外部通道挂接点）
   └─ lifespan   启动顺序：建表 → 增量迁移 → 幂等种子 → 事件订阅 → 调度器
   ▼
PostgreSQL 16（容器 db，卷持久化）
```
关键机制：单据（工单/问题/需求/项目）创建即挂接流程实例，状态由流程编排自动同步（详见「关键概念」）；
权限=功能矩阵×数据范围×流程节点三层；飞书同一应用凭证驱动组织同步与扫码登录。

### 本地启动（Docker）
```bash
cd deploy && docker compose up --build
# 前端 http://localhost:8180   API 文档 http://localhost:8180/api/docs
# 初始管理员 admin / 密码见 deploy 环境变量 ADMIN_INIT_PASSWORD（默认 admin123）
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
```bash
# 1) 准备环境变量（首次）
cd deploy && cp .env.example .env
vi .env   # 必改：DB_PASSWORD、JWT_SECRET、ADMIN_INIT_PASSWORD

# 2) 构建并启动（Nginx 8180 端口，可在 docker-compose.yml 调整映射）
docker compose up -d --build

# 3) 首次登录 admin/<ADMIN_INIT_PASSWORD> → 系统管理→飞书集成 配置组织同步与扫码登录
```
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
docs/            中文设计文档（01-06）；docs/en/ 为英文译本
deploy/          docker-compose、Nginx、备份
```

### 关键概念
- **统一响应包**：`{success, data, total?, page?, error?}`；错误经 `AppError(code, message, status)` 返回中文提示。
- **权限三层**：① 功能矩阵（`role_permission` 表，模块 × 动作 view/create/edit/delete，`require_perm` 守卫，admin 隐式全权）；② 数据范围（业务代码内置，如 requester 仅见自己的工单/需求）；③ 流程权限（状态机 `allowed_roles` + 流程步骤 `default_role`）。
- **流程驱动状态（M23–M31 定稿）**：六类单据（服务请求/事件/变更/问题/需求/项目）状态由流程编排自动同步（首步完成→处理中打首响 SLA、末步→已解决、流程走完→自动关闭）；处理人只操作「完成此步骤」，手动状态按钮按白名单收敛（SR/事件=挂起恢复、问题=已知错误、变更=审批链、需求=无、强关仅 admin）；列表页「当前节点」列标识「待我处理」并一键进详情。
- **关闭策略**：服务请求/需求/项目登记人可主动关闭（理由必填≥5 字、审计留痕）；事件/变更/问题必须流程闭环；强制关闭仅系统管理员。
- **矩阵式组织**：横向业务域（服务线，owner=BM）× 纵向用户组（资源池，组授予角色）；一人多角色；admin 不可经组/规则授予。
- **飞书为人员主数据 SoT**：`org_sync` 幂等应用组织快照（外部赢、消失→离职），本地仅可编辑岗位/技能/备注/部门类型；同步范围可配置（部门 open_department_id 列表或 0=全公司，M32）。
- **示例数据**：`GlidBase.is_example`（列表置顶、后端只读）；默认不种，`SEED_EXAMPLES=1` 开启（测试用）。
- **考核周期**：季度制 `YYYY-Q1/Q2/Q3`，第四季度执行全年考核 `YYYY-All`（统计范围为本年度全年）。
- **双语**：语言存 `auth_user.preferences.language`（zh/en）；登录即应用，用户可自行切换；飞书开通时由管理员设默认语言。
- **飞书扫码登录 + 开通审批**：员工扫码通过身份校验后不立即登录，落 `login_request`（pending）；管理员配置用户名/角色/默认语言/关联人员并开通后，员工过渡页轮询到 approved 自动进入系统；通知走站内 + 发件箱。

### 分支与协作
- `main`：稳定分支，受保护——只接受 Pull Request 合入，禁止直推（本地 pre-push 钩子拦截；紧急放行 `ALLOW_MAIN_PUSH=1 git push`）。
- `develop`：日常开发集成分支；功能开发从 `develop` 拉 `feature/<名称>` 分支，完成后 PR 合回。
- 首次 clone 后启用钩子：`git config core.hooksPath scripts/git-hooks`。
- 提交前自检：后端 `pytest -q` 全绿、前端 `npm run build` 零错误。

### 里程碑
M1 骨架+RBAC → M2 工单+SLA+流程引擎 → M2.5 自配置 → M3 CMDB/问题/供应商/合同/知识 → M3.5–3.10 身份治理/权限矩阵/组织树/飞书 SoT/批量导入 → M4 项目 → M5 需求 → M6 团队（活动积分/人效/培训/文化/流程监控/Dashboard）→ M7 双语 i18n + 飞书扫码登录开通审批 → M9 甘特图 → M10 需求六维评分+四象限 → M11 飞书组织同步+真实扫码 OAuth → M12–15 项目管理实战打磨（行内操作/章程结构化/级联删除/流程版本管理）→ M16 需求路由闭环（评审→方案评估→转开发/转项目→验收自动闭环）→ M17 导航二级菜单+权限模块按页拆分 → M18–25 流程权限体系（任务处理人守卫/待办通知/流程完成自动闭环/状态-流程双向同步/操作权跟随节点处理人/未指派认领）→ M26–28 交互与关闭策略定稿（原路返回/登记人关单+理由审计/强关仅 admin）→ M29 SLA 优先级定义（ITIL 初稿可编辑）+ 问题管理专业线流程 → M30–31 状态按钮白名单+列表「待我处理」列 → M32 飞书同步范围可配置（多部门/全公司）→ **M33 用户调试版流程与权限固化为出厂默认**。
验收基准为 `docs/03-PRD.md` 对应章节 + 各里程碑提交说明；实现细节以代码与测试（197 例）为准。

---

## English

### Tech stack
- Backend: FastAPI + SQLAlchemy 2.0 + PostgreSQL 16 (Python 3.11)
- Frontend: React 18 + TypeScript + Ant Design v5 + Zustand + Vite
- Deploy: Docker Compose (Nginx serves the SPA and reverse-proxies `/api`)
- Primary keys: 26-char ULID (GLID); business codes `PREFIX-YYYYMM-seq` (TK/PB/KB/PJ/RQ/ID…)

### Architecture at a glance
```
Browser SPA (React + AntD)
   │  /api/* (uniform envelope {success,data,error})
   ▼
Nginx (container frontend:80 → host 8180) ── serves dist + proxies /api
   ▼
FastAPI (container backend:6800, uvicorn)
   ├─ routers/   one file per domain (require_perm / process guards)
   ├─ services/  domain logic (permission matrix, process engine, SLA, scoring, org_sync, seed, migrate)
   ├─ events/    event bus + notifier (in-app + outbox, external-channel hook point)
   └─ lifespan   startup: create tables → incremental migrate → idempotent seed → subscribe → scheduler
   ▼
PostgreSQL 16 (container db, persistent volume)
```
Key mechanics: every ticket/problem/requirement/project gets a process instance on creation and its
status is synced by orchestration (see Key concepts); permissions = functional matrix × data scope ×
process-step operator; one Feishu app credential drives both org sync and QR sign-in.

### Run locally (Docker)
```bash
cd deploy && docker compose up --build
# Web  http://localhost:8180   API docs http://localhost:8180/api/docs
# Bootstrap admin: admin / password from the deploy env var ADMIN_INIT_PASSWORD (default admin123)
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
```bash
# 1) Prepare env vars (first time)
cd deploy && cp .env.example .env
vi .env   # must change: DB_PASSWORD, JWT_SECRET, ADMIN_INIT_PASSWORD

# 2) Build & start (Nginx on port 8180; adjust the mapping in docker-compose.yml)
docker compose up -d --build

# 3) First login admin/<ADMIN_INIT_PASSWORD> → System Admin → Feishu Integration
```
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
docs/            Chinese design docs (01-06); docs/en/ holds the English translations
deploy/          docker-compose, Nginx, backups
```

### Key concepts
- **Response envelope**: `{success, data, total?, page?, error?}`; errors are raised as `AppError(code, message, status)`.
- **Three permission layers**: (1) functional matrix (`role_permission` table, module × action view/create/edit/delete, guarded by `require_perm`; `admin` is implicitly all-powerful); (2) data scope (baked into business code, e.g. a `requester` only sees their own tickets/requirements); (3) process permissions (state-machine `allowed_roles` + process-step `default_role`).
- **Process-driven status (finalized M23–M31)**: for all six flow-bound entities, ticket status is synced automatically by process orchestration (first step done → processing with first-response SLA, last step → resolved, flow complete → auto-closed). Operators only click "complete this step"; manual status buttons are reduced to a whitelist (SR/incident = pause/resume, problem = known-error, change = approval chain, requirement = none, force close = admin only). List pages show a "current step" column flagging "my turn" with a jump into the detail page.
- **Closure policy**: submitters may close their own service requests / requirements / projects (reason ≥5 chars, audited); incidents/changes/problems must complete the flow; force close is admin-only.
- **Matrix organization**: horizontal business domains (service lines, owner = BM) × vertical user groups (resource pools that grant roles); one person holds many roles; `admin` can never be granted via groups or provisioning rules.
- **Feishu is the Source of Truth for people master data**: `org_sync` idempotently applies an org snapshot (external wins, missing → offboarded/inactive); locally only position/skills/remarks/dept-type are editable. The sync scope is configurable (a list of department open_department_ids, or 0 = whole company, M32).
- **Example data**: `GlidBase.is_example` (pinned to the top of lists, read-only on the backend); not seeded by default, enable with `SEED_EXAMPLES=1` (used by tests).
- **Assessment period**: quarterly `YYYY-Q1/Q2/Q3`; Q4 runs the full-year assessment `YYYY-All` (statistics cover the whole calendar year).
- **Bilingual**: language is stored in `auth_user.preferences.language` (zh/en); applied on login and switchable by the user; the admin sets the default during Feishu provisioning.
- **Feishu QR sign-in + provisioning approval**: after an employee passes Feishu identity verification they are NOT logged in immediately; a `login_request` (pending) is recorded. Once an admin configures the username/roles/default language/linked person and approves, the employee's waiting page polls until `approved` and enters the system automatically. Notifications go through in-app + outbox.

### Branching & collaboration
- `main`: stable, protected — merged via Pull Request only; direct pushes are blocked by a local pre-push hook (override with `ALLOW_MAIN_PUSH=1 git push` in emergencies).
- `develop`: day-to-day integration branch; cut `feature/<name>` branches from it and PR back.
- After cloning, enable the hooks once: `git config core.hooksPath scripts/git-hooks`.
- Pre-commit checklist: backend `pytest -q` all green, frontend `npm run build` with zero errors.

### Milestones
M1 skeleton+RBAC → M2 tickets+SLA+process engine → M2.5 self-configuration → M3 CMDB/problems/vendors/contracts/knowledge → M3.5–3.10 identity governance / permission matrix / org tree / Feishu SoT / bulk import → M4 projects → M5 requirements → M6 team → M7 bilingual i18n + Feishu QR sign-in with provisioning approval → M9 Gantt → M10 six-dimension requirement scoring + quadrants → M11 Feishu org sync + real QR OAuth → M12–15 project-management polish → M16 requirement routing loop (review → solution assessment → to-dev/to-project → auto closure) → M17 second-level nav + per-page permission modules → M18–25 process permission system (task-operator guards, todo notifications, auto closure on flow completion, bidirectional status/flow sync, action rights follow the current step operator, claim-by-role for unassigned tasks) → M26–28 interaction & closure policy (history-aware back, submitter close with audited reason, force-close admin-only) → M29 editable ITIL priority definitions + problem flow by professional line → M30–31 status-button whitelist + "my turn" column on lists → M32 configurable Feishu sync scope (multi-department / whole company) → **M33 user-tuned flows & permissions baked in as factory defaults**.
Acceptance baseline: the matching section of `docs/03-PRD.md` plus each milestone's commit message; code and the 197-case test suite are the source of truth.
