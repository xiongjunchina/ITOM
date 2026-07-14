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
- **矩阵式组织**：横向业务域（服务线，owner=BM）× 纵向用户组（资源池，组授予角色）；一人多角色；admin 不可经组/规则授予。
- **飞书为人员主数据 SoT**：`org_sync` 幂等应用组织快照（外部赢、消失→离职），本地仅可编辑岗位/技能/备注/部门类型；凭据就绪前引擎待命。
- **示例数据**：`GlidBase.is_example`（列表置顶、后端只读）；默认不种，`SEED_EXAMPLES=1` 开启（测试用）。
- **考核周期**：季度制 `YYYY-Q1/Q2/Q3`，第四季度执行全年考核 `YYYY-All`（统计范围为本年度全年）。
- **双语**：语言存 `auth_user.preferences.language`（zh/en）；登录即应用，用户可自行切换；飞书开通时由管理员设默认语言。
- **飞书扫码登录 + 开通审批**：员工扫码通过身份校验后不立即登录，落 `login_request`（pending）；管理员配置用户名/角色/默认语言/关联人员并开通后，员工过渡页轮询到 approved 自动进入系统；通知走站内 + 发件箱。

### 里程碑
M1 骨架+RBAC → M2 工单+SLA+流程引擎 → M2.5 自配置 → M3 CMDB/问题/供应商/合同/知识 → M3.5–3.10 身份治理/权限矩阵/组织树/飞书 SoT/批量导入 → M4 项目 → M5 需求 → M6 团队（活动积分/人效/培训/文化/流程监控/Dashboard）→ M6.1–6.4 人效计分方案/删人/ITSM 拆分/拖拽 widget/季度考核 → **M7 双语 i18n + 飞书扫码登录开通审批**。
每里程碑打 git tag，验收基准为 `docs/03-PRD.md` 对应章节。

---

## English

### Tech stack
- Backend: FastAPI + SQLAlchemy 2.0 + PostgreSQL 16 (Python 3.11)
- Frontend: React 18 + TypeScript + Ant Design v5 + Zustand + Vite
- Deploy: Docker Compose (Nginx serves the SPA and reverse-proxies `/api`)
- Primary keys: 26-char ULID (GLID); business codes `PREFIX-YYYYMM-seq` (TK/PB/KB/PJ/RQ/ID…)

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
- **Matrix organization**: horizontal business domains (service lines, owner = BM) × vertical user groups (resource pools that grant roles); one person holds many roles; `admin` can never be granted via groups or provisioning rules.
- **Feishu is the Source of Truth for people master data**: `org_sync` idempotently applies an org snapshot (external wins, missing → offboarded/inactive); locally only position/skills/remarks/dept-type are editable. The engine stays idle until credentials are provided.
- **Example data**: `GlidBase.is_example` (pinned to the top of lists, read-only on the backend); not seeded by default, enable with `SEED_EXAMPLES=1` (used by tests).
- **Assessment period**: quarterly `YYYY-Q1/Q2/Q3`; Q4 runs the full-year assessment `YYYY-All` (statistics cover the whole calendar year).
- **Bilingual**: language is stored in `auth_user.preferences.language` (zh/en); applied on login and switchable by the user; the admin sets the default during Feishu provisioning.
- **Feishu QR sign-in + provisioning approval**: after an employee passes Feishu identity verification they are NOT logged in immediately; a `login_request` (pending) is recorded. Once an admin configures the username/roles/default language/linked person and approves, the employee's waiting page polls until `approved` and enters the system automatically. Notifications go through in-app + outbox.

### Milestones
M1 skeleton+RBAC → M2 tickets+SLA+process engine → M2.5 self-configuration → M3 CMDB/problems/vendors/contracts/knowledge → M3.5–3.10 identity governance / permission matrix / org tree / Feishu SoT / bulk import → M4 projects → M5 requirements → M6 team (activity points / performance / training / charter / process monitor / dashboard) → M6.1–6.4 performance scoring schemes / person deletion / ITSM split / draggable widgets / quarterly assessment → **M7 bilingual i18n + Feishu QR sign-in with provisioning approval**.
Each milestone is git-tagged; the acceptance baseline is the matching section of `docs/03-PRD.md`.
