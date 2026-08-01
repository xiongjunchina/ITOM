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
- 部署：IDC Kubernetes（唯一运行/验收环境；Docker Compose 仅保留为明确授权的临时排障手段）
- 主键：26 位 ULID（GLID）；业务编号 `前缀-YYYYMM-序号`（TK/PB/KB/PJ/RQ/ID…）

### 架构简介
```
浏览器 SPA (React + AntD)
   │  /api/*（统一响应包 {success,data,error}）
   ▼
IDC Ingress :30443 → Nginx frontend:80 ── 静态托管 dist + 反代 /api、/mcp
   ▼
FastAPI（Kubernetes Service backend:6800，uvicorn）
   ├─ routers/   一域一文件（权限守卫 require_perm / 流程守卫）
   ├─ services/  领域逻辑（权限矩阵、流程引擎、SLA、评分、org_sync、seed、migrate）
   ├─ mcp/       Aily JWT、外部身份映射、Streamable HTTP 与工具审计
   ├─ events/    事件总线 + 通知（站内 + Aily 机器人可靠发件箱）
   └─ lifespan   启动顺序：建表 → 增量迁移 → 幂等种子 → MCP 会话 → 调度器
   ▼
PostgreSQL 16（StatefulSet + PVC 持久化）
```
关键机制：单据（工单/问题/需求/项目/Bug）创建即挂接流程实例，状态由流程编排自动同步（详见「关键概念」）；
权限=功能矩阵×数据范围×流程节点三层；飞书组织同步、扫码登录继续保留。现已封存的 `feature/aily-agent-mcp` 完成了 P0 底座和 P1 服务入口：清除服务台运行路径、内嵌 `/mcp`、Aily JWT 与精确身份映射、脱敏工具审计、真实服务项检索、版本化动态表单、预览确认/幂等提交、服务项流程与派单，以及独立 IT 需求登记和本人单据查询；当前 `feature/AI-agent-version` 继承这些能力并作为 Web Agent 后续唯一开发线。网页与 MCP 共用领域校验；ITOM 始终是服务目录、表单、流程和权限的唯一事实来源，详见 [`docs/10-Aily-MCP版本交接与决策上下文.md`](docs/10-Aily-MCP版本交接与决策上下文.md)。

### 临时本地隔离排障（默认不使用）

IDC 已成为唯一运行与验收环境。只有用户明确要求临时隔离排障时，才允许启动以下本地 Compose 环境；不得把它作为交付或 UAT 证据。

```bash
cd deploy && docker compose up --build
# 前端 http://localhost:8180   API 文档 http://localhost:8180/api/docs
# 初始管理员 admin / 密码见 deploy 环境变量 ADMIN_INIT_PASSWORD（默认 admin123）
# 全新数据库默认 SEED_INITIAL_CONFIG=1：自动初始化七条流程定义及当前登录页/Logo；已有品牌配置不会覆盖
```

### 自动化质量门禁

默认由 [`.github/workflows/quality-gate.yml`](.github/workflows/quality-gate.yml) 在 `feature/AI-agent-version`、`develop`、`main` 的推送和 Pull Request 上执行：

- Python 3.12 完整后端 `pytest`，使用测试夹具创建的临时 SQLite 数据库，不连接 IDC 业务库；
- Node.js 22 的 `npm ci`、TypeScript 检查和 Vite 生产构建；
- Kubernetes YAML、部署脚本语法、Git 差异空白检查；
- 实现/部署变化必须同时包含中文权威文档和 `docs/en` 英文镜像。

如需在提交前做本机快速检查，只运行原生测试/构建命令，不启动本地 ITOM 应用栈：

```bash
# 后端
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                       # 全量测试

# 前端
cd frontend && npm ci
npm run build                          # tsc --noEmit + vite build（提交前必须 0 错误）
```

### 生产部署

> IDC Kubernetes 是唯一运行、联调和验收环境，公网根地址为 `https://itom.snnc.cc:30443`。必须先提交完整代码/测试/文档并通过 GitHub Actions；发布脚本拒绝脏工作区，按 Git 提交生成不可变 linux/amd64 镜像标签，不启动本地 ITOM 应用环境。

```bash
# 1) 将 feature 分支推送到 GitHub，等待 ITOM Quality Gate 全绿
git push origin feature/AI-agent-version

# 2) 如有数据库结构变化，先完成批准的 IDC 集群内备份/检查点

# 3) 在干净提交上构建 linux/amd64 镜像并推送 Harbor
cd deploy/k8s
./push-images.sh

# 4) 部署同一 Git 提交派生的不可变标签并执行严格探针
./k8s-deploy.sh
```

`push-images.sh` 只在本机执行镜像构建和推送，不启动应用；默认标签为 `git-<commit前12位>-linux-amd64`。发布构建通过已验证的 `mirror.gcr.io` 官方 Docker Library 缓存及固定摘要取得 Python、Node、Nginx 和 PostgreSQL 基础镜像，避免 Docker Hub 限流和可变标签漂移。`k8s-deploy.sh` 保留现有 Secret/PVC/数据库/上传和飞书配置，要求 rollout 成功，并核对实际镜像、集群内前端代理、外部 `/api/health` 与 MCP `initialize`。回滚时使用上一有效标签执行 `TAG=<previous-tag> ./k8s-deploy.sh`。`ALLOW_UNTRUSTED_TLS=1` 只允许临时诊断，不得作为正式验收结果。

### 目录结构
```
backend/app/
  models/        SQLAlchemy 模型（support 身份/组织、itsm、project、requirement、team、process）
  routers/       FastAPI 路由（一个域一个文件）
  services/      领域逻辑（permissions 权限矩阵、task_management 任务管理、perf 人效引擎、points 积分、
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
docs/            中文设计文档（01-10）；docs/en/ 为英文译本
deploy/          docker-compose、Nginx、备份
```

### 关键概念
- **统一响应包**：`{success, data, total?, page?, error?}`；错误经 `AppError(code, message, status)` 返回中文提示。
- **权限三层**：① 功能矩阵（`role_permission` 表，模块 × 动作 view/create/edit/delete，`require_perm` 守卫，admin 隐式全权）；② 数据范围（业务代码内置，如 requester 仅见自己的服务请求、BDO 仅见自己登记的需求）；③ 流程权限（状态机 `allowed_roles` + 流程步骤 `default_role`）。
- **流程驱动状态**：现有 ITOM 仍按 M23–M31 自动同步；P2 已将服务请求的“IT 人员标记已解决”和“提交人确认关闭”拆开，未解决时重回处理中。重开后再次解决会采用本轮最新有效处理说明，避免向用户展示上一轮未生效的旧方案。只有提交人本人可通过网页或 Aily 确认，管理员不能代确认。事件仍为 IT 内部/监控来源，普通用户不能创建。
- **流程节点语义**：每个节点可配置为处理节点或审批节点，并分别配置处理人与知会人。审批节点支持详情右上角“同意/驳回”或流程图“完成此步骤”同意；同意理由可选，驳回理由必填并留痕。WBS 任务完成度支持管理员/负责人直接录入 0–100% 整数；显式将父项设为 100% 会向下级联，子项修改后父项按直接子项平均值递归回算，项目进度仅按末级任务工期加权汇总。
- **全局表格交互**：所有超出内容区宽度的表格统一提供一条底部悬浮横向滚动条，页面纵向滚动时表头保持悬浮；WBS 额外支持前三列冻结。
- **列表分页**：分页器的页大小为受控状态，统一支持 10/20/50/100 条；服务项等前端本地分页表格切换页大小不会被固定默认值覆盖，服务端分页列表同步传递 `page_size`。
- **WBS 表格交互**：WBS 宽表支持 Excel 式冻结窗格（表头 + 左侧前三列）、底部悬浮横向滚动条、列宽与行高拖拽调整；完成度提供 0%/50%/100% 预设并支持自定义 0–100% 整数；父子任务进度自动级联/汇总；布局按项目保存在当前浏览器。
- **关闭策略**：服务请求/需求/项目登记人可主动关闭（理由必填≥5 字、审计留痕）；事件/变更/问题必须流程闭环；强制关闭仅系统管理员。
- **矩阵式组织**：横向业务域（服务线，新建时可从组织架构选择服务部门并覆盖下级部门；负责人、备份负责人和服务团队取自管理员配置的“数字化团队范围”）× 纵向用户组（资源池，组授予角色）；一人多角色；admin 不可经组/规则授予。数字化团队范围是所选部门成员与单独指定人员的并集，可从 Test 等混合供应商组织中只纳入目标外包人员。IT 工作负责人、评审人和用户组人员通过 `/api/members?scope=it` 加载并由后端复核；登录账号关联人员面向全公司有效人员，不受该范围限制。无需求引用的业务域可由管理员删除。
- **需求实现任务**：实现中需求允许同一需求登记多行任务；需求负责人可维护本需求任务，普通任务负责人只能更新自己的状态和实际工时，任务删除仍受全局需求/任务编辑权限控制。能力字段由后端返回并由写接口重新校验；本次兼容修复不改写存量需求、任务或数据库结构。
- **飞书为人员主数据 SoT**：`org_sync` 幂等应用组织快照（外部赢、消失→离职），本地仅可编辑岗位/技能/备注/部门类型；同步范围可配置（部门 open_department_id 列表或 0=全公司，M32），管理员可独立启停自动同步并选择每 1/6/12/24 小时执行。
- **示例数据**：`GlidBase.is_example`（列表置顶）；编辑、状态流转和业务操作仍只读，系统管理员可在列表页明确删除示例记录；默认不种，`SEED_EXAMPLES=1` 开启（测试用）。
- **考核周期**：季度制 `YYYY-Q1/Q2/Q3`，第四季度执行全年考核 `YYYY-All`（统计范围为本年度全年）。
- **帮助中心式用户操作手册**：当前手册重制期内，顶栏“操作手册”和 `/user-manual` 仅 `admin` 可见和访问；其他角色访问旧链接会回到自身首个授权页面。正式重做完成后再评估开放范围。中文权威版本为 `docs/用户操作手册.md`，英文译本为 `docs/en/user-operation-manual.md`。
- **矩阵角色人效评分**：人效总览使用当前矩阵角色结果（角色职责结果 80% + 团队贡献 20%），支持 ITSM/需求/项目/流程自动取数、负责人分级初评、CIO 终审、外部原数据录入和发布后个人结果隔离；同一角色可配置多名评审人及独立权重，评审结果按权重汇总。外部满意度仅按业务服务域录入，外部指标采用白名单校验；团队贡献维度、目标积分及内外部满意度比例由 CIO/管理员配置，并在考核周期生成规则快照。旧版岗位计分方案接口仅保留历史客户端兼容，不再作为总览数据源。
- **积分规则配置**：团队管理→活动积分→积分规则维护团队贡献活动的自动事件分值、启停状态、维度权重、目标积分和满意度组合；仅 admin/CIO 可修改。当前考核期的自动活动事件在积分榜、个人积分、团队总览和 Dashboard 中按当前规则实时计算（页面每 30 秒刷新，亦可手动刷新）；规则停用显示为 0。原始积分台账、历史周期和已发布/锁定人效保持不改写。团队管理→人效评分→计分规则只维护岗位角色档案、角色维度、取数口径和权重，不混入团队贡献活动。
- **双语**：语言存 `auth_user.preferences.language`（zh/en）；登录即应用，用户可自行切换；飞书开通时由管理员设默认语言。
- **Aily + MCP 正式基线**：P0 已完成 MCP 内嵌、首次注册协议发现、Aily JWT/Origin/租户/Agent 校验、精确 ITOM 用户映射与脱敏审计；P1 已实现普通业务用户创建 IT 服务请求、BDO 登记 IT 需求，以及实时服务项、动态表单、SLA、流程、派单、预览确认、幂等提交和本人查询；P2 已增加待确认列表、明确工单确认/重开和关闭评价 3 个工具。协议发现不执行工具；任何 `tools/call` 仍必须完整验签、授权并经过 ITOM 领域服务。
- **任务管理（M82）**：新增“开发任务（需求开发/Bug 修复）”和“委派任务”入口，保留历史需求任务页面兼容重定向；Bug 支持产品经理确认、生成多行修复/测试任务、验证关闭和重开，委派任务支持登记、排期、执行、暂停、中止、关闭及按记录范围删除；Bug 修复和委派任务已接入按期交付绩效及幂等积分，团队贡献类别由服务端白名单校验。
- **任务与运维总览**：Dashboard 在有权限时展示 Bug、Bug 修复子任务、委派任务和需求开发任务的未完成数量；Bug 所属系统候选直接来自有效 CMDB 配置项，管理员在 CMDB 新建/编辑配置项时可维护产品经理，Bug 登记保存该人员快照。项目进度页在甘特图上方展示取自 WBS 一级任务的阶段进度线；Dashboard 与团队总览的积分排行统一只汇总 `team_contribution` 团队贡献流水并可展开来源明细，`role_result` 岗位结果积分不会再次进入活动积分，避免重复计算。
- **CMDB 职责与培训活动**：所有配置项必须维护“技术负责人”，负责技术运行与维护；仅“应用”配置项额外维护“产品经理”，负责 Bug 确认和验证关闭，两者可为同一人但不互相替代。新建或编辑应用必须配置产品经理，历史非应用记录的旧值保持可追溯但不在页面展示。培训活动保存登记人；管理员、CIO 或登记人可修改/删除。参与人按真实部门树展示，勾选部门即可级联选择该部门全部 IT 成员，仍可逐人调整。整部门登记会冻结部门 ID、显示名与当时人员范围；清单显示部门名和范围外个别参与人，积分始终按冻结的人员 ID 计算，历史活动不会因后续调岗而重解释。变更主讲或参与人会在当前未发布、未锁定考核期撤销旧培训积分并按当前规则重算；历史/已发布/锁定周期禁止影响积分的改动或删除，非计分资料仍可编辑并审计。
- **创建单据指引与跨单据关联（阶段 A/B/C 已实现）**：普通业务用户仍只通过 Aily 创建服务请求；仅 BDO 可通过 Aily 登记 IT 需求。IT 员工和系统管理员网页提供轻量“创建单据指引”、六类单据的紧凑说明和案例库。临时问答不落库，服务端按真实创建权限返回可访问的目标入口；Aily/MCP 的范围、字段和权限不变。通用 `record_relation` 已提供 PostgreSQL 增量迁移、活动关系/幂等唯一约束、不可变审计、双方可见性裁剪及四类详情页双向读取展示，且不迁移、不覆盖既有专用关联。阶段 C 已提供“准备 → 补齐目标表单 → 创建并关联”的服务请求→事件、服务请求/事件→问题、事件/问题→变更、需求→项目四条路径：同一事务调用目标领域服务、启动目标流程、写入关联和审计；来源行锁与提交摘要保证重试不重复建目标，同键异参拒绝；原单据不改类型、不关闭。详见 [`docs/superpowers/specs/2026-07-31-it-staff-intake-and-record-relations-design.md`](docs/superpowers/specs/2026-07-31-it-staff-intake-and-record-relations-design.md)。
- **ITOM 网页智能体（设计已确认；WA0 Task 1–4 已实现）**：采用网页登录与 Aily MCP 身份隔离、下层领域能力统一的方案。当前已具备默认关闭的持久化与权限基础、固定能力注册/实时策略/递归脱敏、安全 OpenAI-compatible `/chat/completions` 模型网关，以及仅限 `admin_ai` 的模型/档案管理 API。提供商密钥加密且只写，响应只返回 `has_secret`；安全探测复用请求级固定 IP 传输并原子保存真实健康状态。提供商创建、更新、删除、探测结果以及档案发布/回滚形成的活动引用均由 PostgreSQL 事务 advisory lock 跨 Pod 串行化，再按 ID 锁定提供商行，避免旧探测启用、主备环路、删除引用和多主竞态。四类固定档案只能收窄代码注册能力；草稿的名称、默认提供商、启用、保留期、风险、提示词和能力全部保存在版本草稿中，成功发布时才原子替换活动配置并生成不可变递增版本，回滚复制并重新应用历史快照。健康和动作审计只返回聚合/脱敏白名单；用量由 SQL 在默认 30 天、可选 1–90 天窗口内聚合。模型和提示词不授权，L3 写操作仍必须预览、明确确认、幂等和审计。管理 UI、网页会话、动作编排和业务处理器尚未实现；现有“创建单据指引”保留为模型故障降级。实施继续按 WA0 基础治理 → WA1 只读顾问 → WA2 业务闭环 → WA3 IT 员工写操作 → WA4 效果治理推进，详见 [`docs/superpowers/specs/2026-08-01-itom-web-agent-design.md`](docs/superpowers/specs/2026-08-01-itom-web-agent-design.md)。
- **飞书业务用户免登**：已同步且不属于数字化/IT 范围的业务人员，在邮箱和冲突校验通过后可自动创建/绑定 requester 账号；IT 范围员工仍需管理员开通审批，初始化凭据只按部署配置加密保存，不进入日志或响应。
- **统一公网入口**：管理员在“系统管理 → 系统集成 → Aily Agent + MCP Server”维护 `public_base_url`；页面从同一根地址生成带末尾斜杠的 `/mcp/`、飞书登录回调和卡片回调地址。根地址只允许 `http/https + 域名或 IP + 可选端口`，禁止路径、参数、片段和 URL 凭据。当前 IDC 根地址为 `https://itom.snnc.cc:30443`。
- **服务闭环与主动消息**：P2 已把受理、解决、重开、关闭和评价事件接入可靠 Aily 机器人发件箱，机器人配置未启用时保留待发记录且不消耗重试次数。机器人凭据、卡片回调 Verification Token 与 Encrypt Key 同时就绪后，解决通知/期限提醒显示“已解决并关闭、仍未解决”按钮，关单通知显示 1–5 星按钮；“仍未解决”会原地展开必填原因表单。普通对话仍只走 Aily + MCP；卡片按钮是唯一例外，由 ITOM 校验飞书签名、Bot App、回调租户及点击人身份后调用同一领域服务，继续执行本人范围、状态、RBAC、幂等和审计。真实联调表明 Aily JWT 的 `tenant_id` 与卡片回调 `tenant_key` 属于不同标识命名空间；二者不直接相等时，必须由点击人标识在允许的 Agent/Bot 应用范围内唯一锚定到已授权 Aily 租户的活动 ITOM 身份，未知或歧义身份一律拒绝。回调兼容真实 Aily 的 Go 风格时间戳，但不放宽签名或时效校验。`TK-202607-0005` 已通过“未解决 → 重新打开 → 再次解决并关闭 → 5 星评价”的真实飞书按钮 UAT。未就绪时自动回退纯文本。每张工单只有一条有效评价明细，标签/意见/来源可审计，兼容星级同步到 `ticket.satisfaction`。飞书服务台运行路径、配置、模型、页面和专用测试已全部移除，历史版由标签 `v1.0.0-feishu-helpdesk` 恢复。
- **站内通知**：顶栏铃铛显示当前账号可见通知；弹窗提供“一键已读”和“清除已读”，前者批量写入已读回执，后者软删除当前账号已读通知，均不修改源业务单据。
- **当前 IDC 卡片回调状态（2026-07-31）**：历史 `TK-202607-0005` 按钮闭环仍是已通过的 UAT 证据；当前 `itom.snnc.cc:30443` 公网证书无法通过标准 CA 校验，复核窗口没有 `card-actions` POST 到达入口日志。更换受信 TLS 并用当前 IDC 新工单生成新卡片前，不宣称“确认关闭”已恢复。
- **飞书扫码登录 + 开通审批**：管理员批准时生成 12 位高强度初始密码并加密保存，但不自动发信。管理员可在用户详情点击闭眼图标按需查看，或点击“邮件发送”手工投递；查看与发送均审计，用户改密/管理员重置后密文立即清除。

### 分支与协作
- `main`：稳定分支，受保护——只接受 Pull Request 合入，禁止直推（本地 pre-push 钩子拦截；紧急放行 `ALLOW_MAIN_PUSH=1 git push`）。
- `develop`：日常开发集成分支；功能开发从 `develop` 拉 `feature/<名称>` 分支，完成后 PR 合回。
- `release/feishu-helpdesk-v1` 与标签 `v1.0.0-feishu-helpdesk`：飞书服务台版本的冻结基线；标签固定在提交 `f13f702`，不得重写。
- `feature/aily-agent-mcp`：已封存的 Aily + MCP 开发线，只保留历史记录，不再接收提交。
- `feature/AI-agent-version`：继承 Aily + MCP 能力的 Web Agent 唯一开发线；方案背景、架构边界和新会话启动要求见 [`docs/10-Aily-MCP版本交接与决策上下文.md`](docs/10-Aily-MCP版本交接与决策上下文.md)，完成后由用户确认并通过 Pull Request 合入 `main`。
- **开发前同步门禁**：每次开始新的开发任务前，必须先检查工作区；有本地变更时先单独提交版本记录，再推送当前开发分支并确认本地 `HEAD` 与 GitHub 分支指针一致。同步失败或分支不一致时，停止编辑代码，不得把旧变更与新任务混在一起。
- 首次 clone 后启用钩子：`git config core.hooksPath scripts/git-hooks`。
- 提交前自检：后端 `pytest -q` 全绿、前端 `npm run build` 零错误；按改动影响同步更新 `README.md`、`docs/03–06` 及对应英文译本。
- **交付完成定义**：代码实现、测试与受影响说明文档必须相互一致；功能、接口、数据模型、配置、部署、权限或用户流程发生变化但文档未同步时，不得视为完整交付。仓库级执行规则见 [`AGENTS.md`](AGENTS.md)。

### 里程碑
M1 骨架+RBAC → M2 工单+SLA+流程引擎 → M2.5 自配置 → M3 CMDB/问题/供应商/合同/知识 → M3.5–3.10 身份治理/权限矩阵/组织树/飞书 SoT/批量导入 → M4 项目 → M5 需求 → M6 团队（活动积分/人效/培训/文化/流程监控/Dashboard）→ M7 双语 i18n + 飞书扫码登录开通审批 → M9 甘特图 → M10 需求六维评分+四象限 → M11 飞书组织同步+真实扫码 OAuth → M12–15 项目管理实战打磨（行内操作/章程结构化/级联删除/流程版本管理）→ M16 需求路由闭环（评审→方案评估→转开发/转项目→验收自动闭环）→ M17 导航二级菜单+权限模块按页拆分 → M18–25 流程权限体系（任务处理人守卫/待办通知/流程完成自动闭环/状态-流程双向同步/操作权跟随节点处理人/未指派认领）→ M26–28 交互与关闭策略定稿（原路返回/登记人关单+理由审计/强关仅 admin）→ M29 SLA 优先级定义（ITIL 初稿可编辑）+ 问题管理专业线流程 → M30–31 状态按钮白名单+列表「待我处理」列 → M32 飞书同步范围可配置（多部门/全公司）→ M33 用户调试版流程与权限固化为出厂默认 → M34–35 通知直达+异步全员组织同步 → M36–36.2 账号治理、飞书免登与个人中心 → **M37 个人设置（通知偏好、个人操作记录、飞书绑定管理、明暗主题与内容密度）**。
M45–M46 是冻结版 Helpdesk 历史里程碑，仅保留在 `v1.0.0-feishu-helpdesk`。Aily-MCP 新开发线已完成 P0（移除 Helpdesk、协议/身份/消息）、P1（真实服务目录、动态表单、服务请求/BDO 需求登记、派单）和 P2（解决通知、确认/重开、评价闭环），P3 飞书审批按用户决定暂缓；IDC 发布加固继续执行。后续网页智能体独立使用 WA0–WA4 编号，避免与 Aily 阶段混淆；WA0 Task 1–4 的持久化、策略/脱敏、安全模型网关和模型/档案管理 API 已实现，Task 5+ 仍待实施。

验收基准为 `docs/03-PRD.md` 对应章节 + 各里程碑提交说明；实现细节以代码与测试为准。

---

## English

### Tech stack
- Backend: FastAPI + SQLAlchemy 2.0 + PostgreSQL 16 (Python 3.12) + MCP Python SDK 1.29
- Frontend: React 18 + TypeScript + Ant Design v5 + Zustand + Vite
- Deploy: IDC Kubernetes (the sole runtime/acceptance environment; Docker Compose is retained only for explicitly approved temporary troubleshooting)
- Primary keys: 26-char ULID (GLID); business codes `PREFIX-YYYYMM-seq` (TK/PB/KB/PJ/RQ/ID…)

### Architecture at a glance
```
Browser SPA (React + AntD)
   │  /api/* (uniform envelope {success,data,error})
   ▼
IDC Ingress :30443 → Nginx frontend:80 ── serves dist + proxies /api and /mcp
   ▼
FastAPI (Kubernetes Service backend:6800, uvicorn)
   ├─ routers/   one file per domain (require_perm / process guards)
   ├─ services/  domain logic (permission matrix, process engine, SLA, scoring, org_sync, seed, migrate)
   ├─ mcp/       Aily JWT, external identity, Streamable HTTP, and tool audit
   ├─ events/    event bus + notifier (in-app + reliable Aily-bot outbox)
   └─ lifespan   startup: create tables → migrate → seed → MCP session → scheduler
   ▼
PostgreSQL 16 (StatefulSet + persistent PVC)
```
Key mechanics: every ticket/problem/requirement/project gets a process instance on creation and its
status is synced by orchestration (see Key concepts); permissions = functional matrix × data scope ×
process-step operator. Feishu org sync and QR sign-in remain. The now-archived `feature/aily-agent-mcp` implemented the P0 embedded-MCP/identity/audit/outbox foundation, P1 intake tools, and P2 requester confirmation/reopen/rating tools plus user-visible lifecycle messages. The current `feature/AI-agent-version` inherits those capabilities and is the sole Web Agent development line. Web and MCP use the same domain validation, while ITOM remains the sole source for catalog, forms, workflow, authorization, and ratings.

### Temporary isolated local troubleshooting (disabled by default)

IDC is the sole runtime and acceptance environment. Start the following Compose stack only when the user explicitly requests an isolated investigation; it is never delivery or UAT evidence.

```bash
cd deploy && docker compose up --build
# Web  http://localhost:8180   API docs http://localhost:8180/api/docs
# Bootstrap admin: admin / password from the deploy env var ADMIN_INIT_PASSWORD (default admin123)
# Fresh databases default to SEED_INITIAL_CONFIG=1, which initializes the seven workflows and the verified login/Logo branding; existing branding is never overwritten.
```

### Automated quality gate

By default, [`.github/workflows/quality-gate.yml`](.github/workflows/quality-gate.yml) runs on pushes and pull requests for `feature/AI-agent-version`, `develop`, and `main`:

- the complete Python 3.12 backend regression against the fixture-created temporary SQLite database, never the IDC business database;
- Node.js 22 `npm ci`, TypeScript checking, and the Vite production build;
- Kubernetes YAML, deployment-script syntax, and changed-line whitespace checks;
- a guard requiring authoritative Chinese documentation and a matching `docs/en` mirror for implementation or deployment changes.

Optional workstation preflight uses native test/build commands only and does not start a local ITOM runtime:

```bash
# Backend
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                       # full test suite

# Frontend
cd frontend && npm ci
npm run build                          # tsc --noEmit + vite build (must be 0 errors before commit)
```

### Production deployment

> IDC Kubernetes is the sole runtime, integration, and acceptance environment at `https://itom.snnc.cc:30443`. Commit the complete implementation, tests, and documentation and obtain a green GitHub Actions gate first. Release scripts reject a dirty worktree and derive immutable linux/amd64 image tags from the Git commit without starting a local ITOM runtime.

```bash
# 1) Push the feature branch and wait for ITOM Quality Gate to pass
git push origin feature/AI-agent-version

# 2) For schema changes, complete the approved in-cluster backup/checkpoint

# 3) Build linux/amd64 images from the clean commit and push to Harbor
cd deploy/k8s
./push-images.sh

# 4) Deploy the same immutable tag and run strict probes
./k8s-deploy.sh
```

`push-images.sh` builds and pushes images only; it does not start the application. Its default tag is `git-<first-12-commit-chars>-linux-amd64`. Release builds obtain Python, Node, Nginx, and PostgreSQL from the verified `mirror.gcr.io` Docker Library cache at pinned digests, avoiding Docker Hub rate limits and mutable-tag drift. `k8s-deploy.sh` preserves existing Secrets, PVCs, database, uploads, and Feishu configuration; requires successful rollouts; and verifies image identity, the in-cluster frontend proxy, external `/api/health`, and MCP `initialize`. Roll back with `TAG=<previous-tag> ./k8s-deploy.sh`. `ALLOW_UNTRUSTED_TLS=1` is a temporary diagnostic override and never formal acceptance evidence.

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
docs/            Chinese design docs (01-10); docs/en/ holds the English translations
deploy/          docker-compose, Nginx, backups
```

### Key concepts
- **Response envelope**: `{success, data, total?, page?, error?}`; errors are raised as `AppError(code, message, status)`.
- **Three permission layers**: (1) functional matrix (`role_permission` table, module × action view/create/edit/delete, guarded by `require_perm`; `admin` is implicitly all-powerful); (2) data scope (baked into business code, e.g. a `requester` sees only own service requests and a BDO sees only own requirements); (3) process permissions (state-machine `allowed_roles` + process-step `default_role`).
- **Process-driven status**: current ITOM still follows M23–M31 automation. P2 now separates “resolved by IT” from “closed after requester confirmation” for service requests; rejection returns the request to processing. A resolution after reopen adopts the latest active handling note, rather than exposing the failed prior attempt as the current solution. Only the submitter can confirm through web or Aily; administrators cannot confirm on the submitter's behalf. Incidents remain IT/monitoring-originated and cannot be created by normal users.
- **Process-node semantics**: each node can be configured as processing or approval with separate handler and CC parties. Approval nodes support approve/reject from the detail-page actions or approve through the flow diagram; approval comments are optional, rejection reasons are mandatory and retained. WBS task completion accepts an integer percentage from 0–100; explicitly setting a parent to 100% cascades to all descendants, child changes roll up as direct-child averages, and project progress is duration-weighted over leaf tasks only.
- **Global table interaction**: every table wider than the content area exposes one sticky bottom horizontal scrollbar and keeps its header visible during vertical page scrolling; the WBS table additionally freezes the first three columns.
- **List pagination**: page-size selectors are controlled state everywhere and consistently support 10/20/50/100 rows; local-paginated tables such as Service Items no longer reset a selected size to a hard-coded default, while server-paginated lists pass the selected `page_size` to the API.
- **WBS table interaction**: the wide WBS table provides an Excel-style freeze pane (header plus the first three columns), one sticky bottom horizontal scrollbar, draggable column widths and row heights; completion offers 0%/50%/100% presets plus a custom integer from 0–100%; parent/child progress cascades and rolls up automatically; layout is saved per project in the current browser.
- **Closure policy**: submitters may close their own service requests / requirements / projects (reason ≥5 chars, audited); incidents/changes/problems must complete the flow; force close is admin-only.
- **Matrix organization**: horizontal business domains (served departments are selected from Org Structure with optional descendant coverage; owner, backup owner, and service-team selectors use the administrator-defined digital-team scope) × vertical user groups. The scope is the union of selected department members and individually selected people, allowing a mixed vendor organization to contribute only named contractors. IT operational owners, reviewers, and group selectors load `GET /api/members?scope=it` with server-side revalidation; login-account linking uses all valid company people and is not restricted by that scope. Administrators may delete domains that have no requirement references.
- **Feishu is the Source of Truth for people master data**: `org_sync` idempotently applies an org snapshot (external wins, missing → offboarded/inactive); locally only position/skills/remarks/dept-type are editable. Besides the remote sync scope, administrators can enable/disable scheduled sync and choose a 1/6/12/24-hour interval.
- **Aily + MCP baseline**: P0 implements embedded MCP and identity/audit foundations; P1 implements service-request intake for business users and IT-requirement intake for BDOs; P2 adds the pending-confirmation list, explicit-ticket confirmation/reopen, and closed-request rating tools. Discovery cannot execute tools; every `tools/call` still requires full authentication, authorization, own-record scope, and domain validation.
- **Record Creation Guide and cross-record relations (phases A/B/C implemented)**: normal business users continue to create only service requests through Aily, while only BDOs may register IT requirements there. IT staff and system administrators now have a lightweight **Record Creation Guide**, compact six-record explanations, and a case library. Temporary answers are not persisted and the server returns only target entries allowed by the account's real create permissions; Aily/MCP scope, fields, and permissions remain unchanged. Generic `record_relation` now has an additive PostgreSQL migration, active-relation/idempotency uniqueness, immutable audit, two-sided visibility filtering, and bidirectional detail-page reads for all four domains, without migrating or overwriting legacy dedicated links. Phase C now provides Prepare → complete target form → Create and link for service request → incident, service request/incident → problem, incident/problem → change, and requirement → project. One transaction invokes the target domain service, starts its workflow, writes the relation and audit; a source-row lock plus submission digest prevents target duplication on a retry and rejects same-key different input; the source is neither retyped nor closed. See the [design baseline](docs/en/superpowers/specs/2026-07-31-it-staff-intake-and-record-relations-design.md).
- **ITOM Web Agent (design approved; WA0 Tasks 1–4 implemented)**: web login and Aily MCP identity remain isolated while lower domain capabilities are shared. The current foundation includes disabled-by-default persistence and permissions, fixed capability registration/live policy/recursive redaction, a secure OpenAI-compatible `/chat/completions` gateway, and `admin_ai`-only provider/profile administration APIs. Provider secrets are encrypted and write-only, responses expose `has_secret` only, and the request-pinned safety probe atomically records truthful health. Provider create/update/delete/probe-result changes and active references applied by profile publish/rollback are serialized across pods by one PostgreSQL transaction advisory lock, followed by deterministic provider-row locks, preventing stale enablement, fallback/delete races, and multiple primaries. Four fixed profiles may only narrow code-registered capabilities. Name, default provider, enablement, retention, risk, prompts, and capabilities remain in the draft version until successful publication atomically applies active settings and creates an immutable increasing version; rollback copies and reapplies a historical snapshot. Health and action-audit reads are aggregate/redacted allowlists, while usage is SQL-aggregated over a default 30-day, configurable 1–90-day window. Models/prompts never authorize; L3 writes still require preview, explicit confirmation, idempotency, and audit. The administration UI, web conversations, action orchestration, and domain handlers remain pending, while the current guide remains the model-outage fallback. Delivery continues through WA0 foundation → WA1 read-only advisor → WA2 business loop → WA3 IT-staff writes → WA4 governance. See the [design baseline](docs/en/superpowers/specs/2026-08-01-itom-web-agent-design.md).
- **Single public endpoint**: administrators maintain `public_base_url` under System Management → System Integrations → Aily Agent + MCP Server. The page derives the trailing-slash `/mcp/` URL, Feishu login callback, and card callback from that root. Only `http/https + host or IP + optional port` is accepted; paths, query strings, fragments, and URL credentials are rejected. The current IDC root is `https://itom.snnc.cc:30443`.
- **Closure and proactive messaging**: acceptance, resolution, reopen, closure, and rating events write the reliable Aily-bot outbox. Once bot credentials plus the card-callback Verification Token and Encrypt Key are ready, resolution/reminder cards expose close/reopen buttons, unresolved opens a required reason form in place, and closure cards expose 1–5-star buttons. Ordinary conversation remains Aily + MCP only. Card buttons are the sole exception: ITOM verifies the Feishu signature, Bot App, callback tenant, and clicker identity, then calls the same domain services with own-record, state, RBAC, idempotency, and audit enforcement. Live integration shows that Aily JWT `tenant_id` and card-callback `tenant_key` occupy different identifier namespaces. When they do not match directly, the clicker must uniquely resolve, within allowed Agent/Bot apps, to an active ITOM identity under an authorized Aily tenant; unknown or ambiguous identities are denied. The callback also accepts the Go-style timestamp observed in real Aily traffic without weakening signature or freshness checks. `TK-202607-0005` passed the live Feishu-button sequence unresolved → reopen → resolve and close → five-star rating (historical evidence). A 2026-07-31 IDC recheck found that the public certificate for `itom.snnc.cc:30443` fails standard CA verification and no card-action POST reached the Ingress/backend logs; trusted TLS and a newly generated current-IDC ticket/card are required before current IDC button acceptance can be claimed. Incomplete configuration safely falls back to text. One effective rating row stores score/tags/comment/source with audit, while `ticket.satisfaction` remains the compatibility score. All Helpdesk runtime/configuration/models/pages/tests are removed; the historical version remains under `v1.0.0-feishu-helpdesk`.
- **Example data**: `GlidBase.is_example` (pinned to the top of lists); editing, workflow transitions, and business actions remain read-only, while administrators can explicitly delete examples from list pages; not seeded by default, enable with `SEED_EXAMPLES=1` (used by tests).
- **Assessment period**: quarterly `YYYY-Q1/Q2/Q3`; Q4 runs the full-year assessment `YYYY-All` (statistics cover the whole calendar year).
- **Point-rule configuration**: Team Management → Activity Points → Point Rules controls team-contribution event values, activation, dimension weights, targets, and satisfaction mix; only admin/CIO can edit. Automatic activity events in the current assessment period are resolved against the current rule in leaderboards, personal points, Team Overview, and Dashboard (the pages refresh every 30 seconds and can be refreshed manually); disabling a rule displays zero. The award-time ledger, historical periods, and published/locked performance remain unchanged. Team Management → Performance → Scoring Rules owns role profiles, role dimensions, source mappings, and weights, with no team-activity rules mixed in.
- **Help-center user manual**: during the current rewrite, the signed-in header exposes “User Manual” and `/user-manual` only to `admin`; other roles are redirected to their first authorized page. The scope will be reassessed after the formal rewrite. The authoritative Chinese version is `docs/用户操作手册.md` and the English mirror is `docs/en/user-operation-manual.md`.
- **In-app notifications**: the top-bar bell lists notifications visible to the current account; **Mark all as read** writes read receipts in bulk and **Clear read** soft-deletes that account's already-read notifications. Neither action changes source business records.
- **Bilingual**: language is stored in `auth_user.preferences.language` (zh/en); applied on login and switchable by the user; the admin sets the default during Feishu provisioning.
- **Feishu QR sign-in + provisioning approval**: approval generates a 12-character strong initial password and stores only encrypted recoverable ciphertext without sending it. An administrator may reveal it with the eye control or manually email it from user details; both actions are audited and the ciphertext is cleared after a change/reset.

### Branching & collaboration
- `main`: stable, protected — merged via Pull Request only; direct pushes are blocked by a local pre-push hook (override with `ALLOW_MAIN_PUSH=1 git push` in emergencies).
- `develop`: day-to-day integration branch; cut `feature/<name>` branches from it and PR back.
- `release/feishu-helpdesk-v1` and `v1.0.0-feishu-helpdesk`: immutable frozen Helpdesk baseline at `f13f702`.
- `feature/aily-agent-mcp`: archived Aily + MCP development line retained for history only; it receives no new commits.
- `feature/AI-agent-version`: sole Web Agent development line inheriting the Aily + MCP capabilities; see the [final design baseline](docs/en/10-aily-mcp-handoff-and-decision-context.md) and merge to `main` only through a user-approved PR.
- **Pre-development synchronization gate**: before every new development task, inspect the worktree; commit any existing local changes as a separate version record, push the current development branch, and verify that local `HEAD` equals the GitHub branch tip. If synchronization fails or tips differ, stop before editing code and report the blocker; never mix the previous changes with the new task.
- After cloning, enable the hooks once: `git config core.hooksPath scripts/git-hooks`.
- Pre-commit checklist: backend `pytest -q` all green, frontend `npm run build` with zero errors, and affected sections in `README.md`, `docs/03–06`, and their English mirrors updated.
- **Definition of done**: implementation, tests, and affected documentation must agree. A behavior, API, data-model, configuration, deployment, permission, or workflow change without synchronized docs is not a complete delivery. See [`AGENTS.md`](AGENTS.md).

### Milestones
M1–M37 remain the existing platform history. M45–M46 are frozen Helpdesk history only. The Aily-MCP line has completed P0 (remove Helpdesk; protocol, identity, messaging), P1 (live catalog, dynamic forms, requester service-request and BDO requirement intake, dispatch), and P2 (resolution notification, confirmation/reopen, rating loop); P3 Feishu Approval is deferred while IDC hardening continues. The later web-agent program uses independent WA0–WA4 identifiers to avoid confusion with Aily phases; WA0 Tasks 1–4 persistence, policy/redaction, secure model gateway, and provider/profile administration APIs are implemented, while Task 5+ remains pending.
Acceptance baseline: the matching section of `docs/03-PRD.md` plus each milestone's commit message; real code and the currently executed test evidence are the implementation source of truth.
