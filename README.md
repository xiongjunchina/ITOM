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
   ├─ events/    事件总线 + 通知（站内 + 通用 ITOM 飞书可靠发件箱）
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

`push-images.sh` 只在本机执行镜像构建和推送，不启动应用；默认标签为 `git-<commit前12位>-linux-amd64`。发布构建通过已验证的 `mirror.gcr.io` 官方 Docker Library 缓存及固定摘要取得 Python、Node、Nginx 和 PostgreSQL 基础镜像，避免 Docker Hub 限流和可变标签漂移。脚本会把当前 Docker CLI context 的 daemon 地址显式传给 `skopeo`，因此兼容默认 Docker socket 以及 OrbStack、Colima、Rancher Desktop 等非默认 socket。前端保持两个副本，当前仅允许调度到节点 01/02：节点 02 的构建污点只由 ITOM 前端显式容忍，两副本以必需主机反亲和分布，避免节点 03 的已知运行异常；节点 01 或 02 不可用时保留另一个副本，不把两个副本静默堆叠到单节点。后端保持无节点硬绑定的单副本 `Recreate`，以适配 uploads PVC 的 RWO 约束；数据库 StatefulSet、PVC、Secret、上传和飞书配置均不属于应用重部署范围。`k8s-deploy.sh` 要求 rollout 成功，并逐一核对每个前端 Endpoint 的后端代理、实际镜像、外部 `/api/health` 与 MCP `initialize`。回滚时使用上一有效标签执行 `TAG=<previous-tag> ./k8s-deploy.sh`。`ALLOW_UNTRUSTED_TLS=1` 只允许临时诊断，不得作为正式验收结果。

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
- **权限三层**：① 功能矩阵（`role_permission` 表，模块 × 动作 view/create/edit/delete，`require_perm` 守卫，admin 隐式全权）；② 数据范围（业务代码内置，如 requester 仅见自己的服务请求；BDO 在网页需求模块可见本人需求及其被配置为业务 BDO 的服务域需求，Aily/MCP 仍仅见本人需求）；③ 流程权限（状态机 `allowed_roles` + 流程步骤 `default_role`）。
- **流程驱动状态**：现有 ITOM 仍按 M23–M31 自动同步；P2 已将服务请求的“IT 人员标记已解决”和“提交人确认关闭”拆开，未解决时重回处理中。重开后再次解决会采用本轮最新有效处理说明，避免向用户展示上一轮未生效的旧方案。只有提交人本人可通过网页或 Aily 确认，管理员不能代确认。事件仍为 IT 内部/监控来源，普通用户不能创建。
- **流程节点语义**：每个节点可配置为处理节点或审批节点，并分别配置处理人与知会人。审批节点支持详情右上角“同意/驳回”或流程图“完成此步骤”同意；同意理由可选，驳回理由必填并留痕。需求审批的驳回是可审计退回：默认最近已到达前序节点，也可选择任一已到达前序节点或“登记人补充”；不复活旧实例、不覆盖历史，关闭/取消/搁置仍是独立动作。其他单据保留各自状态机语义。任一当前待办的处理人或管理员可把该待办转派给另一名在岗且具有有效系统账号的人员；转派只更新当前任务处理人，不改变流程节点、单据状态或历史 RACI 快照，并记录原处理人、目标处理人、理由、审计和通知。流程已有实例后，节点顺序/类型、处理人、自治级别和 SLA 仍须另存新版本；仅知会人可直接维护，且只影响保存后首次激活的节点，既有任务继续使用创建时的 RACI 快照，已发通知不补发、不回写。WBS 任务完成度支持管理员/负责人直接录入 0–100% 整数；显式将父项设为 100% 会向下级联，子项修改后父项按直接子项平均值递归回算，项目进度仅按末级任务工期加权汇总。
- **流程单据回改窗口**：服务请求、事件、变更、问题、需求、项目和 Bug 均使用同一规则。当前节点处理人首次实际打开详情或执行处理时，系统写入“已查阅”事实；在此之前，首节点仅创建人可更正内容并删除，后续节点仅上一节点的实际处理人可更正内容。回改不能改派处理人或改动会改变流程路由的字段；管理员保留系统级编辑/删除权。清单浏览、通知、管理员仅查看详情以及管理员在未处理前的改派均不算下游查阅。历史待办默认不追溯获得该窗口。
- **全局表格交互**：所有超出内容区宽度的表格统一只提供一条由 ITOM 接管的底部悬浮横向滚动条，隐藏 Ant Design 额外生成但不可操作的重复滚动条；页面纵向滚动时表头保持悬浮，筛选、分页或数据量缩减后仍重新接管当前宽表，不能因行数变少而丢失横向访问。统一业务清单的每个可见表头分隔线支持鼠标拖拽和键盘左右键微调；鼠标靠近分隔线时显示调整光标，无需常驻醒目手柄，未预设宽度的字段也有默认可调宽度且变化会实际应用到表格布局。布局按当前账号、路由及列集合隔离保存，同页多张表不会相互覆盖。WBS 额外支持前三列冻结，需求总览额外冻结编号与标题两列。
- **列表分页与导出**：分页器的页大小为受控状态，统一支持 10/20/50/100 条；服务项等前端本地分页表格切换页大小不会被固定默认值覆盖，服务端分页列表同步传递 `page_size`。远端分页清单始终保留 API 返回的真实过滤后 `total`，不得以当前页加载条数覆盖，因而可继续翻到第 2 页及之后；服务请求导出由服务端导出当前授权范围内的全部筛选结果。
- **服务请求与 IT 需求补充附件**：网页“其他补充信息”支持点击上传或粘贴剪贴板中的图片/文件；每张单据最多 10 个图片、PDF 或常见办公文档（单个 50MB）。文件先归属于当前账号的 24 小时临时草稿区，只有服务请求或 IT 需求创建成功后才在同一事务绑定到正式单据；取消/过期草稿不可经通用下载或列表读取。
- **WBS 表格交互**：WBS 宽表支持 Excel 式冻结窗格（表头 + 左侧前三列）、底部悬浮横向滚动条、列宽与行高拖拽调整；完成度提供 0%/50%/100% 预设并支持自定义 0–100% 整数；父子任务进度自动级联/汇总；布局按项目保存在当前浏览器。
- **关闭策略**：服务请求/需求/项目登记人可主动关闭（理由必填≥5 字、审计留痕）；事件/变更/问题必须流程闭环；强制关闭仅系统管理员。
- **矩阵式组织**：横向业务域（服务线，新建时可从组织架构选择服务部门并覆盖下级部门；IT 侧负责人 BM 和服务团队取自管理员配置的“数字化团队范围”，业务 BDO 取自该服务部门范围内已启用且具有 `bdo` 角色的业务人员）× 纵向用户组（资源池，组授予角色）；一人多角色；admin 不可经组/规则授予。BM 负责 IT 侧评审与服务协同，业务 BDO 优先承接本域需求的业务验收与闭环，未配置时回退 BM。数字化团队范围是所选部门成员与单独指定人员的并集，可从 Test 等混合供应商组织中只纳入目标外包人员。IT 工作负责人、评审人和用户组人员通过 `/api/members?scope=it` 加载并由后端复核；登录账号关联人员面向全公司有效人员，不受该范围限制。无需求引用的业务域可由管理员删除；历史 `backup_owner_id` 仅为兼容保留，不参与新流程或绩效归属。
- **需求实现任务**：实现中需求允许同一需求登记多行任务；需求负责人可维护本需求任务，普通任务负责人只能更新自己的状态和实际工时，任务删除仍受全局需求/任务编辑权限控制。能力字段由后端返回并由写接口重新校验；本次兼容修复不改写存量需求、任务或数据库结构。
- **飞书为人员主数据 SoT**：`org_sync` 幂等应用组织快照（外部赢、消失→离职），本地仅可编辑岗位/技能/备注/部门类型；同步范围可配置（部门 open_department_id 列表或 0=全公司，M32），管理员可独立启停自动同步并选择每 1/6/12/24 小时执行。
- **示例数据**：`GlidBase.is_example`（列表置顶）；编辑、状态流转和业务操作仍只读，系统管理员可在列表页明确删除示例记录；默认不种，`SEED_EXAMPLES=1` 开启（测试用）。
- **考核周期**：季度制 `YYYY-Q1/Q2/Q3`，第四季度执行全年考核 `YYYY-All`（统计范围为本年度全年）。
- **帮助中心式用户操作手册**：当前手册重制期内，顶栏“操作手册”和 `/user-manual` 仅 `admin` 可见和访问；其他角色访问旧链接会回到自身首个授权页面。正式重做完成后再评估开放范围。中文权威版本为 `docs/用户操作手册.md`，英文译本为 `docs/en/user-operation-manual.md`。
- **矩阵角色人效评分**：人效总览使用当前矩阵角色结果（角色职责结果 80% + 团队贡献 20%），支持 ITSM/需求/项目/流程自动取数、负责人分级初评、CIO 终审、外部原数据录入和发布后个人结果隔离；同一角色可配置多名评审人及独立权重，评审结果按权重汇总。外部满意度仅按业务服务域录入，外部指标采用白名单校验；团队贡献维度、目标积分及内外部满意度比例由 CIO/管理员配置，并在考核周期生成规则快照。旧版岗位计分方案接口仅保留历史客户端兼容，不再作为总览数据源。
- **积分规则配置**：团队管理→活动积分→积分规则维护团队贡献活动的自动事件分值、启停状态、维度权重、目标积分和满意度组合；仅 admin/CIO 可修改。当前考核期的自动活动事件在积分榜、个人积分、团队总览和 Dashboard 中按当前规则实时计算（页面每 30 秒刷新，亦可手动刷新）；规则停用显示为 0。原始积分台账、历史周期和已发布/锁定人效保持不改写。团队管理→人效评分→计分规则只维护岗位角色档案、角色维度、取数口径和权重，不混入团队贡献活动。
- **双语**：语言存 `auth_user.preferences.language`（zh/en）；登录即应用，用户可自行切换；飞书开通时由管理员设默认语言。
- **Aily + MCP 正式基线**：P0 已完成 MCP 内嵌、首次注册协议发现、Aily JWT/Origin/租户/Agent 校验、精确 ITOM 用户映射与脱敏审计；P1 已实现普通业务用户创建 IT 服务请求、BDO 登记 IT 需求，以及实时服务项、动态表单、SLA、流程、派单、预览确认、幂等提交和本人查询；P2 已增加待确认列表、明确工单确认/重开和关闭评价 3 个工具。协议发现不执行工具；任何 `tools/call` 仍必须完整验签、授权并经过 ITOM 领域服务。
- **服务请求实施交付派单（M93）**：受理人完成服务请求首节点时，默认可选择“由我实施”，也可指定在岗 IT 同事或按实施规则自动分配。实施规则独立于原有受理派单，按服务项 → 服务目录 → 全局兜底解析；全局兜底仅系统管理员/CIO 可维护。`manual_queue` 会保留未指派的待认领任务，未命中任何实施规则时才回退下一流程节点默认角色。Aily/MCP 仍只创建正式服务请求，不接受实施人或内部路由字段；实施决定、命中规则和选择人均留审计。
- **任务管理（M82）**：开发任务包含“需求开发 / Bug 修复 / 项目开发”，另设“委派任务”。需求开发允许先登记不关联需求、后续再补充关联，Excel 模板与导入同样把关联需求编号作为可选项；项目开发要求关联项目、WBS 可选，用于补充项目 WBS 尚未细拆到开发活动的工作。开发任务清单统一显示“登记人”：网页直接登记取当前登录人员，需求转化取原需求登记人，项目/WBS 转化取项目经理，Bug 修复取 Bug 登记人；历史或系统管理员无人员映射时允许显示为空且仍可从账号审计追溯。委派任务与项目开发任务均保留不可覆盖的追加式进度时间线；任务指派时通知负责人，负责人更新进度时通知登记人，统一通过站内通知及已启用的飞书 Outbox 出口发送。Bug 支持编辑所属系统、编号进入详情和与流程单据一致的创建人回改/删除窗口，管理员保留全程删除权。所有任务写入继续由服务端 RBAC、记录范围、状态、审计和软删除校验，不改写存量任务。
- **任务与运维总览**：Dashboard 在有权限时展示 Bug、Bug 修复子任务、委派任务和需求开发任务的未完成数量；Bug 所属系统候选直接来自有效 CMDB 配置项，管理员在 CMDB 新建/编辑配置项时可维护产品经理，Bug 登记保存该人员快照。项目进度页在甘特图上方展示取自 WBS 一级任务的阶段进度线；Dashboard 与团队总览的积分排行统一只汇总 `team_contribution` 团队贡献流水并可展开来源明细，`role_result` 岗位结果积分不会再次进入活动积分，避免重复计算。
- **团队总览人员负载**：接口返回全部在岗 IT 成员的未完成工单、项目任务和需求任务负载；页面保持按合计降序，并在浏览器本地每页展示 20 人，支持翻页、搜索、排序和导出，工具栏总数与在岗成员范围一致。
- **CMDB 职责与培训活动**：所有配置项必须维护“技术负责人”，负责技术运行与维护；仅“应用”配置项额外维护“产品经理”，负责 Bug 确认和验证关闭，两者可为同一人但不互相替代。新建或编辑应用必须配置产品经理，历史非应用记录的旧值保持可追溯但不在页面展示。培训活动保存登记人；管理员、CIO 或登记人可修改/删除。参与人按真实部门树展示，勾选部门即可级联选择该部门全部 IT 成员，仍可逐人调整。整部门登记会冻结部门 ID、显示名与当时人员范围；清单显示部门名和范围外个别参与人，积分始终按冻结的人员 ID 计算，历史活动不会因后续调岗而重解释。变更主讲或参与人会在当前未发布、未锁定考核期撤销旧培训积分并按当前规则重算；历史/已发布/锁定周期禁止影响积分的改动或删除，非计分资料仍可编辑并审计。
- **创建单据指引与跨单据关联（阶段 A/B/C 已实现）**：普通业务用户仍只通过 Aily 创建服务请求；仅 BDO 可通过 Aily 登记 IT 需求。IT 员工和系统管理员网页提供轻量“创建单据指引”、六类单据的紧凑说明和案例库。临时问答不落库，服务端按真实创建权限返回可访问的目标入口；Aily/MCP 的范围、字段和权限不变。通用 `record_relation` 已提供 PostgreSQL 增量迁移、活动关系/幂等唯一约束、不可变审计、双方可见性裁剪及四类详情页双向读取展示，且不迁移、不覆盖既有专用关联。阶段 C 已提供“准备 → 补齐目标表单 → 创建并关联”的服务请求→事件、服务请求/事件→问题、事件/问题→变更、需求→项目四条路径：同一事务调用目标领域服务、启动目标流程、写入关联和审计；来源行锁与提交摘要保证重试不重复建目标，同键异参拒绝；原单据不改类型、不关闭。详见 [`docs/superpowers/specs/2026-07-31-it-staff-intake-and-record-relations-design.md`](docs/superpowers/specs/2026-07-31-it-staff-intake-and-record-relations-design.md)。
- **ITOM 网页智能体（设计已确认；WA0 Task 1–8 已实现）**：采用网页登录与 Aily MCP 身份隔离、下层领域能力统一的方案。当前已具备默认关闭的持久化与权限基础、固定能力注册/实时策略/递归脱敏、安全 OpenAI-compatible `/chat/completions` 模型网关、仅限 `admin_ai` 的模型/档案管理 API、当前登录用户的 bootstrap/创建/列表/详情/归档会话 API，以及通用 L3 服务端预览、本人确认/取消、幂等、锁行重授权和原子结果审计。会话读写始终按数据库 `auth_user_id` 限定，浏览器只能提交规范化站内 route、有限 page/entity/tab 和最多 20 个 GLID；客户端角色/权限、DOM/HTML、提示词、Cookie/头部、外部/协议相对/穿越式路径及额外字段均拒绝。运行时档案必须有完整 schema 标记快照、双语提示、合法能力/风险、健康兼容提供商并与活动行一致；会话保留期只从创建时捕获版本读取，0 永不因后续再发布变为可持久化，正值版本保持原决定和 `expires_at`，但当前档案撤销或不一致时停止新正文。页码限 1–10,000；`fallback_available` 只表示认证用户的权限感知“创建单据指引”可安全返回，不代表 WA1。归档会话在提交前会 `FOR UPDATE + populate_existing` 锁定并刷新所属会话行。L3 注册处理器必须同时提供 `authorize_preview`、`preview` 和 `authorize_record`；预览授权与预览只接收独立预览 Session 内重新加载的 actor 上下文和无 Session-like 属性的 `ReadOnlyActionData` 门面。该门面递归校验查询 AST，只允许单个直接映射表的显式标量列、同表安全条件/排序及编译期有界 limit/offset，结果为递归冻结的 `FrozenActionRecord`；实体/关系/eager、join/alias/subquery/CTE、聚合/窗口/函数、text/raw SQL、跨表表达式、任意层级行锁、动态/负数/超限分页和超限读取均失败关闭。参数只按注册 Pydantic 模型规范化，递归脱敏若会改变规范化值则整次拒绝，安全原值才参与摘要/持久化。幂等准备沿两条顺序执行：已有 key 先无锁探测，再按 `AiAction → active 会话` 顺序锁定/重检并比较摘要；新动作则在 preview 后先锁定/重检会话，再无锁复查 key，只有仍不存在才插入；命名唯一约束竞态会整笔 rollback 后以同样的 `AiAction → active 会话` 顺序恢复赢家。确认 Token 原文只返回一次且仅保存 SHA-256；确认先锁 `AiAction`，再锁定并刷新所属 active 会话，之后才进入 Task 4 治理锁序和完整运行档案证明。记录级再授权与 mutation 只接收 `ActionUnitOfWork.lock_one()/update_locked()`、`FrozenActionRecord` 快照和不暴露真实 ORM 身份的 `LockedActionRecord`；锁定句柄绑定签发它的精确 UoW、Session、外层事务和 savepoint，成功更新即消费旧句柄并返回合并全部变更的新句柄，伪造、跨 UoW/Session/事务、终止事务后或重复使用均拒绝。门面不提供原始事务控制、通用表写入口或 Session/Connection/Engine 暴露。成功领域写入、动作结果和通用审计同事务提交；处理器/审计失败只回滚嵌套 savepoint，并在保持动作行锁的外层事务写有界 `failed` 事实。处理器代码是受信任的进程内扩展代码，不是针对恶意 introspection/import hack 的沙箱；支持接口只保证正常用法下没有 Session 逃逸。消息 SSE/工具循环已由 Task 7 实现；管理 UI 已由 Task 8 实现；具体业务能力处理器仍待 WA1+；实施继续按 WA0 基础治理 → WA1 只读顾问 → WA2 业务闭环 → WA3 IT 员工写操作 → WA4 效果治理推进，详见 [`docs/superpowers/specs/2026-08-01-itom-web-agent-design.md`](docs/superpowers/specs/2026-08-01-itom-web-agent-design.md)。
- **Task 6 Fix Round 5 查询修饰门禁**：`ReadOnlyActionData` 与 `ActionUnitOfWork.lock_one()` 共用的查询校验在 SQL 执行前统一拒绝任何 SQLAlchemy prefix、suffix、statement hint 或 table hint；修饰字符串不解析、不设白名单，不能借此注入 `FOR UPDATE`、大 offset、`DISTINCT` 或方言 SQL。
- **Task 7 受控流式编排**：`POST /api/assistant/conversations/{id}/messages` 只产生 `meta|delta|message|action|error|done`，使用 `Cache-Control: no-store, private`、`Vary: Authorization`，每轮最多四次工具调用，并限制事件、Token、文本、工具及进入权威提交前的总预算。平台指令、已发布档案、授权能力 schema 与明确标注为不可信的页面/知识/业务/用户正文严格分层；泄漏检测的紧凑路径先在原始 code point 阶段只接纳 Unicode 字母/数字（`L*`/`N*`）并剔除名称/显式表中的 Hangul `FILLER`，随后才执行 NFKC/casefold 并再次只保留 `L*`/`N*`，所以原始 Mark、Control、Separator、Punctuation、Symbol（`M*`/`C*`/`Z*`/`P*`/`S*`）、零宽字符和兼容分解符号不能“洗成”字母切断指纹；全角合法字母/数字仍可归一。阈值仍为完整行至少 12 个规范化字符、长片段至少 24 个字符或两个 12–23 字符片段，短公共词不参与；WA0 不承诺完美识别所有视觉同形异码字符。L1/L2 工具只接收 `ReadOnlyActionData`、不可变 actor DTO 和合作式 deadline/cancellation context，在独立回滚 Session 的 PostgreSQL 只读事务及 `statement_timeout` 下由专用有界执行器运行；worker 为 1–32、排队为 0–256。每次工具调用先非阻塞预留容量，再创建能力发现/重授权 Session；满载时在任何该调用的权限查询、Session 或 handler 之前快速拒绝，校验失败、L3 prepare 或异常均释放预留。工具总 deadline 配置范围为 0.1–60 秒，数据库 statement timeout 为 10–59,000 毫秒且必须严格短于工具 deadline。原始 Session/ORM/Connection/Engine、事务控制、DML 和 ORM mutation 均不可达。L3 流内只调用 Task 6 `prepare_action()`，服务端生成 `server_preview/prepared_not_executed` 消息，绝不确认或执行；其他模型正文一律标为 `advisory/not_executed`，不作为 ITOM 状态或操作结果。流式路由认证只返回账号 ID 标量并在返回 `StreamingResponse` 前关闭 worker 自有 Session；开始/幂等、能力发现、原生降级、Gateway 提供商选择与审计、最终完成及失败清理等同步 SQLAlchemy 边界均使用有界 DB worker，在 worker 内创建/关闭短 Session，生产 assistant 路径不使用默认无界 executor。Provider DNS 通过专用有界 DNS/IO 执行器调用同步 `socket.getaddrinfo`，其准入与等待共用请求剩余 deadline；生产路径不调用 `loop.getaddrinfo`、`asyncio.to_thread` 或默认 executor，满载/超时失败关闭，同时保留 SSRF、DNS rebinding 与 TLS 主机绑定。`stream_turn()` 入口只生成一次 monotonic 绝对 deadline，fallback、start、provider/Gateway、每次 DB/工具和 finalization 的所有 pre-commit 工作共用剩余预算；业务 work deadline 提前预留最多 250ms（总预算的 25%）给失败占位清理，工具/provider/statement timeout 均取自身上限与本轮剩余预算的较小值。权威 commit 必须在 deadline 前、最终锁齐并再次检查取消后开始；一旦进入该原子提交阶段，调用方为保证数据库 `completed` 与客户端终态一致，会等待 commit 和 Session 收尾，可能小幅越过 deadline，而不会把已完成提交改报超时。客户端断开会停止协程等待和事件发送，并通知合作式 handler/最终事务取消；commit 前已观察取消则 rollback。Gateway 的取消审计使用既有有界 DB 执行器 best effort 后台提交，不阻塞断流；满载时不创建 Session 并只记录脱敏本地告警，正常成功/可处理错误仍等待审计落库后才输出结果。该护栏不承诺消除操作系统调度层的所有微小竞态，也不强杀 Python 线程；非合作式阻塞可能在后台继续到自身返回，但短 Session 最终始终 rollback/close，硬终止需进程隔离。已开始的 L3 prepare 最多形成到期前的 `prepared`，不会执行。原始正文和页面上下文只用于服务端密钥 HMAC 幂等摘要，持久化正文仍递归脱敏。管理 UI 已由 Task 8 实现；具体业务能力仍由 WA1+ 实施。
- **Task 7A 最终化权威修复**：最终化只在 `db.commit()` 成功返回后设置线程安全的 durable-success；其后的 Session close 异常仅记录脱敏异常类型，不重查数据库猜测事务结果，也不能把已持久化的 `completed` 改报 `error → done`。若 commit 已开始后观察到客户端断流，取消语义优先且不再发送后续 SSE 终态，即使清理同时失败；`db.commit()` 自身失败则不设置 durable-success，继续 rollback、失败占位清理和安全 `error → done`。该修复不新增能力、字段、迁移、配置或前端合同。
- **Task 8 WA0 前端**：业务门户与内部工作台顶栏均提供全局智能助手入口；抽屉在桌面为 480px、窄屏为全宽，页面上下文只由路由/标签/显式选中 GLID 白名单构造，不读取 DOM。POST-SSE 客户端以有限缓冲严格解析 `meta|delta|message|action|error|done`，拒绝未知事件、非法 JSON、截断和超限帧，并沿用 Token、`X-Lang` 与 401 退出行为。L3 结构化卡片只将服务端预览作为文本展示，提供确认、取消、过期、冲突、失败和成功终态；只有确认接口返回 `succeeded` 才显示权威成功。系统管理新增受 `admin_ai` 保护的 AI 智能体五页签控制台，提供商密钥保持只写且不回显。Task 8 不新增后端、数据库字段或具体领域能力，真实角色/断流/动作 IDC 证据仍由 Task 9 验收。
- **Task 8B 流式错误与 L3 确认桥修复**：浏览器只额外接受两种服务端合法错误序列：启动前 `error → done(error)` 和已发元数据后的 `meta → error → done(error)`；错误出现在 delta、action、message 之后，错误终态夹带成功数据，或任何截断/畸形组合仍失败关闭。幂等重放的 `meta → message → done(replay)` 可为 `advisory` 或 `server_preview`，但重放预览只具提示性，不携带 action 事件或确认 Token，也不能暗示可执行 mutation。首次同属主 L3 预览的 action SSE 由服务端窄投影一次性交付原始确认 Token；该短期能力凭证不进入模型、消息正文、持久化、日志、审计或 REST 响应，通用递归脱敏规则保持不变。仅同一属主的一次合法确认成功，重复、跨用户、过期、取消、脱敏占位或畸形凭证均失败关闭。
- **Task 8C WA0 确认兼容性与至多一次收口**：`confirmation_expires_at` 与 action SSE 的 `expires_at` 都把数据库中的 naive UTC 时间序列化为带 `Z` 的 RFC 3339 UTC 字符串；浏览器拒绝无时区期限，避免 Asia/Shanghai 等时区将新十分钟凭证误判过期。实时和重放 `server_preview.action_id` 均须符合 26 位 ULID；无效重放在解析和展示前失败关闭。通过属主/凭证/期限及运行时复核后，服务端先持久化不可重试的内部 `executing` 声明，再运行 handler；声明提交失败时不执行，之后 handler、审计或终态提交不确定时保留非确认态并只返回安全“结果待核实”，绝不恢复 `prepared`、重发 Token 或伪报成功。成功领域变更、`succeeded` 和审计仍保持同一事务；Task 9 IDC 验收范围不变。
- **Task 8C Round 1**：持有有效原始确认 Token 的实时 action SSE 必须同时带有可解析、非空且显式 `Z` 的期限，缺失、`null`、无偏移或畸形期限在创建 `prepared` 卡片前失败关闭；无 Token 的信息 action 不会因此变成 `prepared`。SQLite 的 handler savepoint 现先固定在 claim 后的外层写事务内，故 success 终态 commit 不确定时会回滚领域写入并保留 `executing`。客户端收到 `AI_ACTION_OUTCOME_UNKNOWN` 时清除 Token、停用双按钮并只显示“结果待核实”，绝不显示“尚未执行任何业务变更”；只有服务器返回 `succeeded` 才显示成功。
- **飞书业务用户免登**：已同步且不属于数字化/IT 范围的业务人员，在邮箱和冲突校验通过后可自动创建/绑定 requester 账号；IT 范围员工仍需管理员开通审批，初始化凭据只按部署配置加密保存，不进入日志或响应。
- **统一公网入口**：管理员在“系统管理 → 系统集成 → Aily Agent + MCP Server”维护 `public_base_url`；页面从同一根地址生成带末尾斜杠的 `/mcp/`、飞书登录回调和卡片回调地址。根地址只允许 `http/https + 域名或 IP + 可选端口`，禁止路径、参数、片段和 URL 凭据。当前 IDC 根地址为 `https://itom.snnc.cc:30443`。
- **服务闭环与主动消息**：P2 已把受理、解决、重开、关闭和评价事件接入可靠 Aily 机器人发件箱。统一通知现在按 ITOM 账号入队：账号尚未建立活动、已验证的 Aily 机器人身份时，发件箱保留 `pending`，记录 `AILY_IDENTITY_NOT_MAPPED`，映射补齐后由后台自动发送；Aily 未启用时不产生无效积压，机器人凭据或消息开关未就绪时不消耗重试次数。飞书 OAuth 验真并映射活动 ITOM 账号后，优先用 `tenant_key + user_id`、缺失时用 `tenant_key + union_id` 自动建立当前机器人应用的出站映射，无需逐人配置；第一个正常 OAuth 映射会形成经审计的唯一租户锚点，后台随后可用已同步人员的登录应用 `open_id` 查询租户级 `user_id`，按需自动补齐其他在岗账号并补送待发消息。Aily MCP 租户白名单只约束入站工具调用。不同应用的 `open_id` 不混用，停用、冲突、离职、未关联人员或多租户歧义映射不自动覆盖。机器人凭据、卡片回调 Verification Token 与 Encrypt Key 同时就绪后，解决通知/期限提醒显示“已解决并关闭、仍未解决”按钮，关单通知显示 1–5 星按钮；“仍未解决”会原地展开必填原因表单。普通对话仍只走 Aily + MCP；卡片按钮是唯一例外，由 ITOM 校验飞书签名、Bot App、回调租户及点击人身份后调用同一领域服务，继续执行本人范围、状态、RBAC、幂等和审计。真实联调表明 Aily JWT 的 `tenant_id` 与卡片回调 `tenant_key` 属于不同标识命名空间；二者不直接相等时，必须由点击人标识在允许的 Agent/Bot 应用范围内唯一锚定到已授权 Aily 租户的活动 ITOM 身份，未知或歧义身份一律拒绝。回调兼容真实 Aily 的 Go 风格时间戳，但不放宽签名或时效校验。`TK-202607-0005` 已通过“未解决 → 重新打开 → 再次解决并关闭 → 5 星评价”的真实飞书按钮 UAT。未就绪时自动回退纯文本。每张工单只有一条有效评价明细，标签/意见/来源可审计，兼容星级同步到 `ticket.satisfaction`。飞书服务台运行路径、配置、模型、页面和专用测试已全部移除，历史版由标签 `v1.0.0-feishu-helpdesk` 恢复。
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
M45–M46 是冻结版 Helpdesk 历史里程碑，仅保留在 `v1.0.0-feishu-helpdesk`。Aily-MCP 新开发线已完成 P0（移除 Helpdesk、协议/身份/消息）、P1（真实服务目录、动态表单、服务请求/BDO 需求登记、派单）和 P2（解决通知、确认/重开、评价闭环），P3 飞书审批按用户决定暂缓；IDC 发布加固继续执行。后续网页智能体独立使用 WA0–WA4 编号，避免与 Aily 阶段混淆；WA0 Task 1–8 的持久化、策略/脱敏、安全模型网关、模型/档案管理 API、本人网页会话生命周期、通用 L3 确认边界和受控 POST-SSE 编排已实现，Task 9 验收与 WA1+ 具体领域能力仍待实施。

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
   ├─ events/    event bus + notifier (in-app + generic reliable Aily-bot outbox)
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

# Strict app-only rollout: do not apply or wait for the PostgreSQL StatefulSet
SKIP_DATABASE=1 ./k8s-deploy.sh
```

`push-images.sh` builds and pushes images only; it does not start the application. Its default tag is `git-<first-12-commit-chars>-linux-amd64`. Release builds obtain Python, Node, Nginx, and PostgreSQL from the verified `mirror.gcr.io` Docker Library cache at pinned digests, avoiding Docker Hub rate limits and mutable-tag drift. The script explicitly passes the active Docker CLI context's daemon endpoint to `skopeo`, so the same release path works with the default Docker socket and non-default sockets provided by OrbStack, Colima, or Rancher Desktop. The two frontend replicas are currently eligible only for nodes 01/02: the build taint on node 02 is tolerated explicitly by ITOM frontend only, and required hostname anti-affinity keeps the replicas separate to avoid node 03's known runtime failures. Its controlled rolling update uses `maxSurge: 0` and `maxUnavailable: 1`, releasing an eligible host before creating its replacement; this prevents a rollout deadlock when only those two hosts are eligible. If node 01 or 02 is unavailable, the remaining replica is retained rather than silently stacking both replicas on one host. The backend remains a single unpinned `Recreate` Deployment because its uploads PVC is RWO. For an approved strict app-only recovery, `SKIP_DATABASE=1` skips both applying `10-postgres.yaml` and waiting for the PostgreSQL StatefulSet: it never deletes, restarts, or reschedules the database Pod/PVC, while the existing application Secrets, uploads, and Feishu configuration remain preserved. Schema-affecting releases must not use that mode and require the approved database checkpoint first. `k8s-deploy.sh` requires successful app rollouts and verifies every frontend endpoint's backend proxy, image identity, external `/api/health`, and MCP `initialize`. Roll back with `TAG=<previous-tag> ./k8s-deploy.sh`. `ALLOW_UNTRUSTED_TLS=1` is a temporary diagnostic override and never formal acceptance evidence.

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
- **Three permission layers**: (1) functional matrix (`role_permission` table, module × action view/create/edit/delete, guarded by `require_perm`; `admin` is implicitly all-powerful); (2) data scope (baked into business code: a `requester` sees only own service requests; the web Requirement module gives a BDO own requirements plus every requirement in domains where that person is the configured business BDO, while Aily/MCP remains owner-only); (3) process permissions (state-machine `allowed_roles` + process-step `default_role`).
- **Process-driven status**: current ITOM still follows M23–M31 automation. P2 now separates “resolved by IT” from “closed after requester confirmation” for service requests; rejection returns the request to processing. A resolution after reopen adopts the latest active handling note, rather than exposing the failed prior attempt as the current solution. Only the submitter can confirm through web or Aily; administrators cannot confirm on the submitter's behalf. Incidents remain IT/monitoring-originated and cannot be created by normal users.
- **Process-node semantics**: each node can be configured as processing or approval with separate handler and CC parties. Approval nodes support approve/reject from the detail-page actions or approve through the flow diagram; approval comments are optional, rejection reasons are mandatory and retained. The current pending handler or an administrator may reassign that task to another active, in-position person with an active ITOM account; reassignment changes neither node nor business state/RACI snapshot, and is audited and notified. Requirement rejection is an auditable return: it defaults to the nearest reached prior node, may select any reached prior node or Requester supplement, never resurrects an obsolete instance, and keeps Close/Cancel/On Hold separate. Other record types retain their own state-machine semantics. WBS task completion accepts an integer percentage from 0–100; explicitly setting a parent to 100% cascades to all descendants, child changes roll up as direct-child averages, and project progress is duration-weighted over leaf tasks only.
- **Workflow-record correction window**: service requests, incidents, changes, problems, requirements, projects, and Bugs share one rule. The first real detail open or handling action by the current handler writes a view fact; before that, the creator at the first node may correct content and delete, while at later nodes only the actual previous handler may correct content. A correction cannot reassign a handler or change a routing field; administrators retain system-level edit/delete authority. List/notification reads, an administrator's passive detail inspection, and a pre-handling administrator reassignment are not downstream views. Historical pending tasks do not gain the window retrospectively.
- **Global table interaction**: every table wider than the content area exposes only the ITOM-managed sticky bottom horizontal scrollbar; the duplicate Ant Design sticky scrollbar is hidden. The header remains visible during vertical page scrolling. Filtering, paging, or shrinking the result set reclaims the active wide table so horizontal access never disappears. Every visible header separator in shared business lists supports mouse dragging and keyboard arrow-key adjustment; the resize cursor appears only when the mouse approaches the separator, without a prominent permanent handle. Columns without a predefined width also receive a resizable default and changes take effect in the table layout. Layout is isolated by current account, route, and column set so multiple tables on one page cannot overwrite each other. The WBS table additionally freezes the first three columns; Requirement Overview freezes code and title.
- **Task management**: Requirement Development, Project Development, and Bug Fix lists expose a Registrar column. Directly registered work uses the current person; requirement conversion inherits the requirement requester; project/WBS conversion inherits the project manager; Bug Fix uses the Bug reporter. After a Bug record is created, its reporter or another authorized workflow editor can attach screenshots/logs through the guarded generic attachment route; viewers require `task_bug.view`, and failed individual files never roll back the Bug record.
- **List pagination and export**: page-size selectors are controlled state everywhere and consistently support 10/20/50/100 rows; local-paginated tables such as Service Items no longer reset a selected size to a hard-coded default, while server-paginated lists pass the selected `page_size` to the API and retain the server's full filtered `total`. Service-request export is server-side and includes every matching record in the current authorized scope.
- **Service-request and IT-requirement supplemental attachments**: the web form supports button upload or pasting clipboard images/files into Other supplemental information. Each record permits at most ten images, PDFs, or common office documents (50MB each). Files first belong to the current account's 24-hour draft area and bind atomically only after the service request or IT requirement is successfully created; cancelled or expired drafts cannot be listed or downloaded.
- **WBS table interaction**: the wide WBS table provides an Excel-style freeze pane (header plus the first three columns), one sticky bottom horizontal scrollbar, draggable column widths and row heights; completion offers 0%/50%/100% presets plus a custom integer from 0–100%; parent/child progress cascades and rolls up automatically; layout is saved per project in the current browser.
- **Closure policy**: submitters may close their own service requests / requirements / projects (reason ≥5 chars, audited); incidents/changes/problems must complete the flow; force close is admin-only.
- **Matrix organization**: horizontal business domains (served departments are selected from Org Structure with optional descendant coverage; the IT-side BM and service-team selectors use the administrator-defined digital-team scope, while the business BDO selector contains only active business users with the `bdo` role inside the served-department scope) × vertical user groups. The BM owns IT review and service coordination; the business BDO is assigned the domain's requirement acceptance and closure first, with the BM as fallback when no BDO is configured. The scope is the union of selected department members and individually selected people, allowing a mixed vendor organization to contribute only named contractors. IT operational owners, reviewers, and group selectors load `GET /api/members?scope=it` with server-side revalidation; login-account linking uses all valid company people and is not restricted by that scope. Administrators may delete domains that have no requirement references. The historic `backup_owner_id` is retained only for upgrade compatibility and is excluded from new workflow and performance attribution.
- **Feishu is the Source of Truth for people master data**: `org_sync` idempotently applies an org snapshot (external wins, missing → offboarded/inactive); locally only position/skills/remarks/dept-type are editable. Besides the remote sync scope, administrators can enable/disable scheduled sync and choose a 1/6/12/24-hour interval.
- **Aily + MCP baseline**: P0 implements embedded MCP and identity/audit foundations; P1 implements service-request intake for business users and IT-requirement intake for BDOs; P2 adds the pending-confirmation list, explicit-ticket confirmation/reopen, and closed-request rating tools. M93 separates acceptance from implementation-delivery dispatch: the first acceptance handler can implement personally, select an active IT colleague, or route automatically through service item → catalog fallback → global fallback; `manual_queue` stays claimable and only a no-match falls back to the workflow default role. Implementation rules live at ITSM → Service Catalog → Service Item → Form/Dispatch, while catalog and global fallbacks are maintained on the catalog card and Service Catalog header; the global fallback is admin/CIO-only. Discovery cannot execute tools; every `tools/call` still requires full authentication, authorization, own-record scope, and domain validation.
- **Record Creation Guide and cross-record relations (phases A/B/C implemented)**: normal business users continue to create only service requests through Aily, while only BDOs may register IT requirements there. IT staff and system administrators now have a lightweight **Record Creation Guide**, compact six-record explanations, and a case library. Temporary answers are not persisted and the server returns only target entries allowed by the account's real create permissions; Aily/MCP scope, fields, and permissions remain unchanged. Generic `record_relation` now has an additive PostgreSQL migration, active-relation/idempotency uniqueness, immutable audit, two-sided visibility filtering, and bidirectional detail-page reads for all four domains, without migrating or overwriting legacy dedicated links. Phase C now provides Prepare → complete target form → Create and link for service request → incident, service request/incident → problem, incident/problem → change, and requirement → project. One transaction invokes the target domain service, starts its workflow, writes the relation and audit; a source-row lock plus submission digest prevents target duplication on a retry and rejects same-key different input; the source is neither retyped nor closed. See the [design baseline](docs/en/superpowers/specs/2026-07-31-it-staff-intake-and-record-relations-design.md).
- **ITOM Web Agent (design approved; WA0 Tasks 1–8 implemented)**: web login and Aily MCP identity remain isolated while lower domain capabilities are shared. The current foundation includes disabled-by-default persistence and permissions, fixed capability registration/live policy/recursive redaction, a secure OpenAI-compatible `/chat/completions` gateway, `admin_ai`-only provider/profile administration APIs, owner-scoped bootstrap/create/list/get/archive conversations, and the generic L3 server-preview, owner-confirm/cancel, idempotency, row-lock reauthorization, and atomic result-audit boundary. Runtime profiles require a complete `schema_version` snapshot, bilingual prompts, valid capability/risk limits, a healthy compatible provider, and active-row agreement. Retention is read only from the captured immutable version: zero never becomes persistent after a later positive publication, while positive captured retention and `expires_at` remain stable; new bodies stop when the current profile is withdrawn or invalid. Archiving now `FOR UPDATE + populate_existing` locks and refreshes the owned conversation row before commit. Every L3 handler must implement `authorize_preview`, `preview`, and `authorize_record`; preview authorization and preview run only with a preview-local actor context and a `ReadOnlyActionData` facade that has no Session-like attributes. The facade recursively validates the query AST and accepts only explicit scalar columns from one direct mapped table, same-table safe predicates/order clauses, and compile-time bounded limit/offset, returning recursively frozen `FrozenActionRecord` snapshots. Entity/relationship/eager projection, joins, aliases, subqueries, CTEs, aggregates/windows/functions, text/raw SQL, cross-table expressions, row locks at any depth, dynamic/negative/excessive pagination, and over-limit reads all fail closed. Input is normalized only through the registered Pydantic model and is rejected if recursive redaction would change it; only unchanged safe input is hashed and persisted. Preparation now has two ordered paths: an existing key is probed without a lock, then replay/race recovery locks `AiAction` first and the owned active conversation second before digest comparison; a brand-new action previews first, locks/revalidates the conversation, rechecks the key without taking an action lock, and inserts only while still absent. Confirmation still locks `AiAction` first, then locks and refreshes the owned active conversation before entering the Task 4 governance/runtime proof. Record authorization and mutation receive only `ActionUnitOfWork.lock_one()/update_locked()`, immutable `FrozenActionRecord` snapshots, and an opaque `LockedActionRecord`. Each locked handle is bound to the exact issuing UoW, Session, outer transaction, and savepoint; a successful update consumes it and returns a replacement snapshot that includes all prior/current changes. Forged, cross-UoW/session/transaction, terminal-transaction, and repeated handles fail closed. The supported interface exposes no raw commit/rollback/begin/get_transaction/connection/bind surface or unrestricted generic table write path. Domain mutation, action success, and generic audit commit together. Handler/audit failure rolls back only a nested savepoint and writes a bounded `failed` fact in the still-row-locked outer transaction. Handler code is trusted in-process extension code, not a hostile-code sandbox; the supported interface only guarantees no normal Session escape. Task 7 now implements the guarded SSE/tool loop; the administration UI is implemented by Task 8; concrete business capability handlers remain WA1+ work. Delivery continues through WA0 foundation → WA1 read-only advisor → WA2 business loop → WA3 IT-staff writes → WA4 governance. See the [design baseline](docs/en/superpowers/specs/2026-08-01-itom-web-agent-design.md).
- **Task 6 Fix Round 5 query-modifier guard**: the query validator shared by `ReadOnlyActionData` and `ActionUnitOfWork.lock_one()` rejects every SQLAlchemy prefix, suffix, statement hint, or table hint before SQL execution. Modifier strings are neither parsed nor allowlisted and cannot inject `FOR UPDATE`, a large offset, `DISTINCT`, or dialect SQL.
- **Task 7 guarded streaming orchestration**: `POST /api/assistant/conversations/{id}/messages` emits only `meta|delta|message|action|error|done` with `Cache-Control: no-store, private` and `Vary: Authorization`, four tool rounds, and bounded event/token/text/tool plus pre-authority-commit budgets. Platform instruction, published profile, authorized capability schemas, and explicitly untrusted page/knowledge/business/user bodies remain separate. The compact leak path first admits only original Unicode letter/number (`L*`/`N*`) code points while removing named/explicit Hangul `FILLER` values, then applies NFKC/casefold and repeats the `L*`/`N*` filter. Original Mark, Control, Separator, Punctuation, Symbol (`M*`/`C*`/`Z*`/`P*`/`S*`), zero-width, and compatibility-decomposing symbols therefore cannot be washed into letters that split a fingerprint, while legitimate full-width letters/digits still normalize. Conservative thresholds remain 12+ for complete normalized lines, 24+ for strong fragments, or two distinct 12–23-character fragments; short common terms are excluded. WA0 does not promise perfect detection of every visually confusable but differently encoded character. L1/L2 handlers receive only `ReadOnlyActionData`, an immutable actor DTO, and a cooperative deadline/cancellation context. A dedicated bounded executor admits 1–32 workers plus 0–256 queued calls. Each tool call non-blockingly reserves capacity before capability discovery or reauthorization opens a Session; saturation rejects before that call performs a permission query, creates a Session, or runs a handler, and every validation/L3/error branch releases the permit. The tool deadline is constrained to 0.1–60 seconds; PostgreSQL `statement_timeout` is 10–59,000 ms and must be strictly shorter. Raw Session/ORM/Connection/Engine, transaction control, DML, and ORM mutation remain unreachable. L3 streaming calls Task 6 `prepare_action()` only and returns a server-authored `server_preview/prepared_not_executed` message. All other model prose is `advisory/not_executed`, never an authoritative ITOM result. Stream authentication returns only a scalar account ID and closes its worker-owned Session before `StreamingResponse`; start/idempotency, capability discovery, native fallback, Gateway provider selection/audit, final completion, and failure cleanup use bounded DB workers whose short Sessions are created and closed there, never the default unbounded executor or SSE event loop. Provider DNS calls synchronous `socket.getaddrinfo` only through a dedicated bounded DNS/IO executor whose admission and wait consume the request's remaining deadline; production does not use `loop.getaddrinfo`, `asyncio.to_thread`, or the default executor, and saturation/timeout fail closed while preserving SSRF, DNS-rebinding, and TLS-host binding. `stream_turn()` creates one monotonic absolute deadline. Fallback, start, provider/Gateway, every DB/tool call, and all finalization pre-commit work consume its remaining budget; a work deadline reserves at most 250ms (25% of the turn budget) for best-effort failed-placeholder cleanup. Tool/provider/statement timeouts take the smaller of their own cap and remaining turn time. Authority commit must begin before the deadline after final locks and one last cancellation check. Once that atomic commit phase begins, the caller waits for commit and Session cleanup to preserve durable `completed` versus client-terminal consistency, which may slightly exceed the deadline instead of reporting timeout after a successful commit. Disconnect stops coroutine waiting/event emission and signals cooperative handlers/finalization; an observed pre-commit cancellation rolls back. Gateway cancellation audit is bounded best effort in the existing DB executor and never delays disconnect; saturation opens no Session and records only a redacted local warning, while normal success/handled-error paths still wait for durable audit before exposing output. This is a cooperative guard, not a claim of zero scheduler-level race or force-killing Python threads: non-cooperative work may continue until return while its Session still closes, and hard termination requires process isolation. An already-started L3 prepare may only remain `prepared` until expiry and never executes. Raw normalized content/page context feeds a server-key HMAC idempotency digest while durable bodies remain redacted. Administration UI is implemented by Task 8; concrete business capabilities remain WA1+ work.
- **Task 7A finalization-authority repair**: finalization records thread-safe durable success only after `db.commit()` returns successfully. A later Session-close failure records only a redacted exception type, never re-queries the database to guess transaction outcome, and cannot turn an already durable `completed` row into `error → done`. If disconnect is observed after commit has started, cancellation wins and no later SSE terminal is emitted even when cleanup also fails; a failing `db.commit()` records no durable success and keeps rollback, failed-placeholder cleanup, and safe `error → done`. This repair adds no capability, field, migration, configuration, or frontend contract.
- **Task 8 WA0 frontend**: both the business portal and internal workbench expose a global assistant in the top bar. The drawer is 480px on desktop and full width on narrow screens; page context comes only from a route/tab/explicit-GLID allowlist and never from the DOM. A bounded POST-SSE client strictly accepts `meta|delta|message|action|error|done`, rejecting unknown events, invalid JSON, truncation, and oversized frames while preserving the existing Token, `X-Lang`, and 401 logout behavior. Structured L3 cards render server previews as text and expose confirmation, cancellation, expiry, conflict, failure, and success terminal states; only a `succeeded` confirmation response is authoritative success. System Administration adds an `admin_ai`-guarded five-tab AI Agent console, and provider secrets remain write-only and never prefilled. Task 8 adds no backend, persisted field, or concrete domain capability; Task 9 retains real-role/disconnect/action IDC evidence.
- **Task 8B stream-error and L3 confirmation bridge repair**: the browser additionally accepts only the two server-valid error sequences: pre-start `error → done(error)` and post-metadata `meta → error → done(error)`. An error after delta/action/message, a success payload mixed into an error terminal, and every malformed or truncated crossover still fail closed. Replayed `meta → message → done(replay)` may carry `advisory` or `server_preview` authority, but a replayed preview is informational only: it has no action event or confirmation token and implies no executable mutation. The first owner-scoped L3 preview action SSE uses a narrow server-owned projection to deliver the raw confirmation token once. This short-lived capability never enters model input, message text, persistence, logs, audit, or REST responses, and generic recursive redaction remains unchanged. Exactly one same-owner valid confirmation can succeed; repeated, cross-owner, expired, cancelled, redacted-placeholder, and malformed credentials fail closed.
- **Task 8C WA0 confirmation compatibility and at-most-once closure**: `confirmation_expires_at` and action-SSE `expires_at` serialize naive UTC storage as RFC 3339 UTC with `Z`; the browser rejects offset-free expiry so Asia/Shanghai and other zones cannot immediately expire a fresh ten-minute token. Both live and replayed `server_preview.action_id` values must be 26-character ULIDs and fail closed before parsing or presentation otherwise. After owner/token/expiry/runtime checks, a durable internal non-retryable `executing` claim commits before any handler; a failed claim runs no handler, and uncertain later handler/audit/final persistence retains the non-confirmable state and returns only safe outcome-unknown rather than restoring `prepared`, issuing a token, or claiming success. Domain mutation, `succeeded`, and audit remain one success transaction; Task 9 IDC acceptance is unchanged.
- **Task 8C Round 1**: a live action SSE carrying a valid raw confirmation token must also carry a non-null, parseable explicit-`Z` expiry; missing, `null`, offset-free, or malformed expiry fails closed before a `prepared` card exists, while a tokenless informational action never becomes `prepared`. SQLite now establishes an outer post-claim write transaction before the handler savepoint, so uncertain success-terminal commit rolls back the domain write and retains `executing`. `AI_ACTION_OUTCOME_UNKNOWN` clears the token, disables both controls, and shows result-pending verification rather than any no-change assertion; only server-returned `succeeded` shows success.
- **Single public endpoint**: administrators maintain `public_base_url` under System Management → System Integrations → Aily Agent + MCP Server. The page derives the trailing-slash `/mcp/` URL, Feishu login callback, and card callback from that root. Only `http/https + host or IP + optional port` is accepted; paths, query strings, fragments, and URL credentials are rejected. The current IDC root is `https://itom.snnc.cc:30443`.
- **Closure and proactive messaging**: acceptance, resolution, reopen, closure, and rating events write the reliable Aily-bot outbox. Once bot credentials plus the card-callback Verification Token and Encrypt Key are ready, resolution/reminder cards expose close/reopen buttons, unresolved opens a required reason form in place, and closure cards expose 1–5-star buttons. Ordinary conversation remains Aily + MCP only. Card buttons are the sole exception: ITOM verifies the Feishu signature, Bot App, callback tenant, and clicker identity, then calls the same domain services with own-record, state, RBAC, idempotency, and audit enforcement. Live integration shows that Aily JWT `tenant_id` and card-callback `tenant_key` occupy different identifier namespaces. When they do not match directly, the clicker must uniquely resolve, within allowed Agent/Bot apps, to an active ITOM identity under an authorized Aily tenant; unknown or ambiguous identities are denied. The callback also accepts the Go-style timestamp observed in real Aily traffic without weakening signature or freshness checks. `TK-202607-0005` passed the live Feishu-button sequence unresolved → reopen → resolve and close → five-star rating (historical evidence). A 2026-07-31 IDC recheck found that the public certificate for `itom.snnc.cc:30443` fails standard CA verification and no card-action POST reached the Ingress/backend logs; trusted TLS and a newly generated current-IDC ticket/card are required before current IDC button acceptance can be claimed. Incomplete configuration safely falls back to text. One effective rating row stores score/tags/comment/source with audit, while `ticket.satisfaction` remains the compatibility score. All Helpdesk runtime/configuration/models/pages/tests are removed; the historical version remains under `v1.0.0-feishu-helpdesk`.
- **Aily notification identity repair**: enabled integrations enqueue by ITOM account even when the Aily-bot identity is not mapped. Such rows remain `pending` with `AILY_IDENTITY_NOT_MAPPED` and are retried after a verified mapping is established; disabled integrations create no backlog, and different Feishu applications' `open_id` values are never mixed. A verified Feishu OAuth login automatically maps the current bot app by `tenant_key + user_id`, falling back to `union_id`, without requiring per-user enrollment in the inbound Aily MCP tenant allowlist. The first audited OAuth mapping becomes the unique tenant anchor; the worker can then use each active synchronized employee's login-app `open_id` only to query the tenant-level `user_id`, auto-map the remaining accounts on demand, and deliver waiting rows. Disabled, conflicting, offboarded, unlinked, or tenant-ambiguous identities remain blocked. Mapping audit actions are fixed, schema-bounded codes covered by a model-aware length test so an audit insert cannot regress Feishu OAuth sign-in on PostgreSQL.
- **Example data**: `GlidBase.is_example` (pinned to the top of lists); editing, workflow transitions, and business actions remain read-only, while administrators can explicitly delete examples from list pages; not seeded by default, enable with `SEED_EXAMPLES=1` (used by tests).
- **Assessment period**: quarterly `YYYY-Q1/Q2/Q3`; Q4 runs the full-year assessment `YYYY-All` (statistics cover the whole calendar year).
- **Point-rule configuration**: Team Management → Activity Points → Point Rules controls team-contribution event values, activation, dimension weights, targets, and satisfaction mix; only admin/CIO can edit. Automatic activity events in the current assessment period are resolved against the current rule in leaderboards, personal points, Team Overview, and Dashboard (the pages refresh every 30 seconds and can be refreshed manually); disabling a rule displays zero. The award-time ledger, historical periods, and published/locked performance remain unchanged. Team Management → Performance → Scoring Rules owns role profiles, role dimensions, source mappings, and weights, with no team-activity rules mixed in.
- **Team Overview workload**: the endpoint returns every active IT-team member's open ticket, project-task, and requirement-task workload. The page keeps total-descending order and applies local 20-row pagination with paging, search, sorting, and export; the toolbar count follows the same active IT-member scope as the onboard metric.
- **Help-center user manual**: during the current rewrite, the signed-in header exposes “User Manual” and `/user-manual` only to `admin`; other roles are redirected to their first authorized page. The scope will be reassessed after the formal rewrite. The authoritative Chinese version is `docs/用户操作手册.md` and the English mirror is `docs/en/user-operation-manual.md`.
- **In-app notifications**: the top-bar bell lists notifications visible to the current account; **Mark all as read** writes read receipts in bulk and **Clear read** soft-deletes that account's already-read notifications. Neither action changes source business records.
- **Bilingual**: language is stored in `auth_user.preferences.language` (zh/en); applied on login and switchable by the user; the admin sets the default during Feishu provisioning.
- **Feishu QR sign-in + provisioning approval**: approval generates a 12-character strong initial password and stores only encrypted recoverable ciphertext without sending it. An administrator may reveal it with the eye control or manually email it from user details; both actions are audited and the ciphertext is cleared after a change/reset.

### Recent workflow/list consistency delivery

- Requirement workflow detail now treats the active pending `ProcessTask` as the runtime source of truth. Historical scores remain visible as read-only evidence, but cannot make a requirement appear to be in evaluation after it has reached analysis, implementation, or acceptance; scoring is rejected outside the evaluation nodes.
- Personal Center includes a **Todos** tab backed by `GET /api/auth/me/todos`. It aggregates only tasks the current account may act on and links to the real entity/process detail route; it does not grant workflow permission.
- `SortableTable` supports per-user visible-column and width preferences through `PATCH /api/auth/me/preferences.table_views`; required identifiers/titles/action columns remain protected. Requirement Overview adds the requester column and keeps the left context available through horizontal scrolling.
- New requirement registration and its Excel template contain registration fields only. The legacy `department` field and old score/analysis import columns remain readable for compatibility, while new records no longer ask for channel department or downstream evaluation data.

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
M1–M37 remain the existing platform history. M45–M46 are frozen Helpdesk history only. The Aily-MCP line has completed P0 (remove Helpdesk; protocol, identity, messaging), P1 (live catalog, dynamic forms, requester service-request and BDO requirement intake, dispatch), and P2 (resolution notification, confirmation/reopen, rating loop); P3 Feishu Approval is deferred while IDC hardening continues. The later web-agent program uses independent WA0–WA4 identifiers to avoid confusion with Aily phases; WA0 Tasks 1–8 persistence, policy/redaction, secure model gateway, provider/profile administration APIs, owner-scoped web conversations, the generic confirmed L3 action boundary, and guarded POST-SSE orchestration are implemented, while Task 9 acceptance and WA1+ concrete domain capabilities remain pending.
Acceptance baseline: the matching section of `docs/03-PRD.md` plus each milestone's commit message; real code and the currently executed test evidence are the implementation source of truth.

Task 8C Round 2 补充 expiry contract：the shared browser parser accepts only explicit-`Z` timestamps that are both RFC 3339-shaped and calendar-valid; JavaScript-normalized invalid dates/times such as `2030-02-30T00:10:00Z` and `2030-01-01T24:00:00Z` fail closed, while valid leap days and fractional seconds remain accepted.
