# 任务管理重构设计规格

> 状态：已获用户确认，作为方案 A 的实现基线
> 日期：2026-07-31
> 适用分支：`feature/aily-agent-mcp`

## 1. 目标

在不破坏现有需求、问题、绩效和历史数据的前提下，把任务能力重构为统一的“任务管理”一级菜单，并覆盖三类不同语义的工作：

```text
任务管理
├── 开发任务
│   ├── 需求开发
│   └── Bug 修复
└── 委派任务
```

需求开发继续承载 IT 需求分解出的开发任务；Bug 修复承载缺陷确认、开发和验证闭环；委派任务承载工单、问题、事件、技术研究及其他非项目级工作。

## 2. 不变约束

- `requirement_task` 继续作为需求开发任务的历史事实表，不重建、不覆盖、不删除存量数据。
- 既有 `/requirements/tasks`、`/requirements/tasks/active` 接口和 `req_tasks` 权限编码保留兼容。
- ITIL `Problem` 继续表示问题管理，不把 Bug 强行改造成 Problem；现有问题流程和历史实例不迁移。
- 所有新实体使用 `GlidBase.is_deleted` 软删除；已分配任务不能由普通用户删除。
- 流程推进、权限、审计、幂等和绩效事件均由后端领域服务负责，前端按钮不构成授权。
- 绩效历史流水和已发布周期只读；新增事件只能影响新的取数结果或后续考核周期。

## 3. 领域模型

### 3.1 需求开发

保留现有 `RequirementTask` 字段和状态，前端将其展示为“开发任务 → 需求开发”标签页。新入口可以增加兼容适配字段，但不改变原任务主键、需求关联、负责人、计划日期、计划/实际工天及完成事件。

### 3.2 Bug 修复

新增 `Bug`：

- `bug_code`、`title`、`description`、`priority`、`status`；
- `ci_id` 关联所属系统，`product_manager_id` 保存登记时解析出的系统产品经理快照；
- `reporter_id`、`dev_leader_id`、`source_type`、`source_id`；
- 复现条件、期望结果、实际结果、环境、证据、解决说明、验证说明；
- `closed_at`、`reopened_at` 和标准软删除字段。

新增 `BugFixTask`：

- `bug_id`、`name`、`task_type`（开发/测试/其他）、`description`；
- `assignee`、`plan_start`、`plan_date`、`plan_effort`、`actual_effort`；
- `status`（登记/排期/执行/暂停/关闭）、`done_at`、`completion_note`；
- 所有任务允许多行，开发负责人在“生成修复任务”节点维护，指派人员只维护自己的执行字段。

Bug 流程固定为：

```text
登记 Bug（IT 团队成员，执行）
→ Bug 确认（系统产品经理，审批）
→ 生成修复任务（开发负责人，执行）
→ 开发修复（子任务负责人，执行；全部必需子任务关闭后才可推进）
→ 验证关闭（系统产品经理，审批）
```

系统产品经理由 `ci.product_manager_id` 解析并在 Bug 上形成快照；系统产品经理变更不改写历史 Bug。确认驳回、重新打开和验证不通过均写审计并保留原因。

### 3.3 委派任务

新增 `WorkTask`：

- `task_code`、`title`、`description`、`task_type`；
- `source_type/source_id`，支持 manual、ticket、problem、incident、bug、other；
- `registrar`、`assignee`、`priority`、`plan_start`、`plan_date`、`plan_effort`、`actual_effort`；
- `status`（登记/排期/执行/暂停/关闭/中止）；
- `pause_reason`、`abort_reason`、`completion_note`、`closed_at`。

权限规则：登记状态且尚未分配时，登记人可以删除；一旦分配，在关闭前只有管理员可以删除；管理员可以在清单页编辑、暂停、中止、关闭。删除始终是软删除并写审计。

## 4. 菜单、路由和权限

- 一级菜单改为“任务管理”。
- 二级页面为“开发任务”和“委派任务”。
- 开发任务页使用 `tab=requirement|bug`，不再提供需求/ Bug 混合汇总页。
- 旧 `/requirements/tasks` 重定向到开发任务的需求开发标签页；旧 API 保留。
- 新增独立权限模块时保留 `req_tasks` 兼容，并增加 `task_development`、`task_bug`、`task_delegated`；数据范围与流程节点在后端判定。

## 5. 绩效与积分

- 需求开发：沿用 `requirement_delivery` 和 `requirement_task_done`，继续归入 `role_result`。
- Bug 修复：新增 `bug_fix_delivery` 结果指标，按计划到期的 Bug 修复/测试子任务按期完成率取数；产品经理确认/验证和开发负责人任务规划继续使用流程及时性证据，不把同一事实重复计入团队贡献。
- 委派任务：默认按岗位职责结果取数，新增 `delegated_work_delivery`；只有明确标记为跨团队支援或创新研究，并完成验收证据的任务，才允许映射到 `team_contribution`。
- 计划工时仅作为任务权重和审计事实，不直接兑换绩效；完成、按期、验证通过和重开由领域事件及幂等积分规则记录。
- 历史 `point_entry`、已发布 `performance_period` 不回算、不覆盖。

## 6. 兼容与迁移

- 采用新增表、可空字段和幂等启动迁移；禁止删除既有业务表和历史列。
- `ci.product_manager_id` 只新增可空列，已有 CI 不因迁移失败而不可读。
- 新流程定义使用新版本编码；现有 `problem_flow`、`requirement_flow` 实例继续沿用原流程快照。
- 新列表默认排除软删除数据，同时保留管理员审计和历史查询能力。
- 每个阶段完成后先跑自动化测试，再提交、推送、构建并部署 IDC；不以本地 Docker 作为验收环境。

## 7. 验收范围

1. 存量需求任务仍可在新“需求开发”标签页看到、编辑、完成和计入原有绩效。
2. IT 团队成员可登记 Bug；系统产品经理确认后，开发负责人可生成多条修复/测试任务。
3. Bug 子任务支持排期、执行、暂停、关闭，全部必要子任务完成后产品经理可验证关闭。
4. Bug 驳回、验证不通过、重新打开均有原因和审计记录。
5. 委派任务支持登记、排期、执行、暂停、中止、关闭、搜索、编辑和权限控制。
6. 普通用户不能删除已分配任务；管理员能在清单页执行管理操作。
7. 历史需求、问题、积分、绩效和流程实例数据数量及关键展示不减少。
8. 中英文权威文档、后端测试、前端构建和 IDC UAT 结果一致。
