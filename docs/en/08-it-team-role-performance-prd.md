# IT Team Role Performance Scoring PRD

> Version: v1.1
> Date: 2026-07-22
> Status: matrix-role performance solution development baseline
> Scope: Team Management → Performance, Activity Points, Learning & Growth (with **Training Development** and **Learning Tasks** tabs), Position & Headcount
> This PRD covers IT team members other than the CIO. Bonus and penalty adjustments remain separate.

## 1. Context and objectives

The IT team uses a matrix model: business service lines (market/sales, supply chain/production, product/R&D, and finance/corporate services) intersect with professional lines (product, development, operations, and PMO). Data governance, AI, security, architecture, and other platform capabilities serve multiple domains.

A person may hold both a business-line role and a professional-line role. Position-only scoring would overvalue one side and would not provide an appropriate evaluator for platform roles. The matrix-role model keeps existing ITSM, requirement, project, process, knowledge, and points evidence while adding staged human review and controlled external data entry.

Objectives:

1. Business-line and professional-line role scores together contribute 80%; team contribution is always 20%.
2. System calculations are the initial reference score, not an untraceable replacement for management judgment.
3. Business-line leads and professional-line leads may adjust only the role scores within their assigned scope; the CIO performs final review and can directly score all leaders and platform roles.
4. External business satisfaction and other facts unavailable in the system can be entered, verified, locked, and audited before they are used by scoring rules.
5. Before publication, only authorized reviewers see score details. An evaluated employee sees only the published final result.

The CIO is not evaluated by this regular scorecard. The system keeps the existing points ledger and separate bonus/penalty mechanisms.

## 2. Core model

For each active IT member other than the CIO:

1. Business service-line role scores contribute part of the score.
2. Professional-line or platform role scores contribute part of the score.
3. Team contribution is calculated from contribution points and contributes a fixed 20%.

Business-line role weights plus professional-line role weights must equal 80%. Team contribution is always 20%. If a person has only one side, that side receives 80%. Multiple roles on the same side share that side's allocation.

```text
Regular score = Σ(role score × role weight) + team contribution score × 20%
Published score = regular score + bonus - penalty
```

Each role score is independently normalized to 0–100. A role's enabled dimension weights must total 100%. An inapplicable dimension may be excluded and the remaining dimensions normalized; a role with no applicable dimensions remains pending rather than silently becoming zero.

Periods remain `YYYY-Q1`, `YYYY-Q2`, `YYYY-Q3`, and `YYYY-All` (Q4 rolls into the annual period). Role, evaluator, and weight assignments are snapshotted per period.

## 3. Evaluators and review authority

- Ordinary business-line members: business-line lead 60% + supporting business partner 40%.
- Business-line lead: CIO 100%.
- Business partner: business-line lead 70% + CIO 30%.
- Product/development/operations members: the corresponding professional-line lead.
- The owner of the IT PM virtual team (the `it_pmo` role) reviews project managers; PMO itself is reviewed directly by the CIO.
- Product, development, operations, PMO, and generic professional-line leads: CIO.
- Data, AI, security, architecture, and other platform roles: CIO directly.
- Self-scoring is prohibited. Missing or conflicting evaluators require a CIO-designated substitute and an audit record.

Review authority is scoped separately from application permissions:

| Reviewer | Scope and edit authority |
|---|---|
| Business-line lead | Business-line role components for people in the assigned business domain/service line. |
| Professional-line lead | Professional-line role components for people in the assigned professional pool. |
| CIO | All role components, external-data results, final scores, leader scores, and platform-role dimensions. |
| Evaluated employee | Published final result only; no review details or edit access. |

The backend must enforce scope and field-level authorization. Hiding an edit control in the UI is not sufficient.

## 4. Review lifecycle and visibility

Periods use the following states:

`draft` → `auto_scored` → `external_input` → `manager_review` → `cio_review` → `published` → `locked`

- `auto_scored`: existing ITSM, requirement, project, process, knowledge, and points data produce reference scores.
- `external_input`: system-outside business facts are entered and verified.
- `manager_review`: business-line and professional-line leads submit scoped preliminary adjustments.
- `cio_review`: the CIO accepts or adjusts all results and directly fills platform-role dimensions that the system cannot measure.
- `published`: only the final result is exposed to the evaluated employee.
- `locked`: a correction creates a new version; the published version is never silently overwritten.

System reference score, current-stage proposal, effective score, adjustment reason, evidence, and reviewer are stored separately. Platform roles default to `review_mode=cio_direct`; they do not generate ordinary manager-review tasks. If a platform employee also has a business-line role, the two review chains remain independent.

## 5. Existing-source metric mapping

The first release should use current system data rather than introduce duplicate manual forms.

| Metric | Existing source | Use |
|---|---|---|
| `ticket_service` | Ticket assignee, SLA, resolution, satisfaction | Service request/incident SLA achievement and satisfaction. |
| `change_compliance` | Change fields and approval history | Approved, normally closed, non-cancelled/non-rolled-back changes. |
| `project_delivery` | WBS assignee, planned and completed dates | On-time completion of due WBS tasks. |
| `requirement_delivery` | Requirement-task assignee, planned and completed dates | On-time completion of due requirement tasks. |
| `bug_fix_delivery` | Bug-fix-task assignee, planned date, and close time | On-time closure rate for due Bug development/test child tasks; open or late tasks fail. |
| `delegated_work_delivery` | Work-task assignee, planned date, and close time | On-time closure rate for due delegated tasks; aborted or open tasks do not count as completed. |
| `domain_satisfaction` | Business-domain membership and ticket satisfaction | Internal ITSM satisfaction for the relevant business domain. |
| `knowledge_contrib` | Knowledge articles and votes | Standardized publication/usefulness score. |
| `process_task_timeliness` | Process task assignee, due/completed timestamps | On-time process-governance completion. |

Derived metrics can aggregate existing fields for owner/manager/team roles:

- `requirement_owner_delivery`: requirement owner, target date, and closure date;
- `project_manager_delivery`: project manager, milestones, risks, and project health;
- `domain_demand_outcome`: business domain, demand status, target date, and closure date;
- `team_service_outcome`: service results of the professional pool;
- `team_delivery_outcome`: requirement/WBS delivery results of the professional pool.

Recommended first-release combinations are:

| Role | Reference-score composition |
|---|---|
| `it_ops` | `ticket_service` 60% + `change_compliance` 30% + `domain_satisfaction` 10%. |
| `it_dev` | `requirement_delivery` 35% + `project_delivery` 25% + `bug_fix_delivery` 20% + `delegated_work_delivery` 10% + change quality 10%. |
| `it_pdm` | `requirement_owner_delivery` 45% + `domain_satisfaction` 30% + linked project result 25%. |
| `it_pm` | `project_manager_delivery` 55% + project WBS/milestones 25% + linked requirement closure 20%. |
| `it_pmo` | `process_task_timeliness` 40% + project governance 35% + requirement/project closure 25%. |
| `it_bp` | Requirement review/acceptance timeliness 40% + `domain_demand_outcome` 30% + external/internal satisfaction 30%. |
| `it_bm` | `domain_demand_outcome` 40% + external/internal satisfaction 30% + business-domain project health 30%. |
| Professional-line leads | `team_service_outcome`, `team_delivery_outcome`, and quality/governance; do not substitute personal task count for management results. |
| Platform roles | Existing facts are reference evidence; platform-specific professional dimensions are entered and finalized directly by the CIO. |

For data governance, AI, security, architecture, and similar platform roles, system facts remain useful evidence when the person participates in tickets, requirements, or projects. The CIO directly scores dimensions such as data standards, model safety, security governance, responsible AI, or architecture governance that current modules cannot measure.

Task-management performance boundary: Bug-fix child tasks and ordinary delegated work are job-result evidence, measured through `bug_fix_delivery` and `delegated_work_delivery` in the professional role. Fresh `it_dev` profiles use the 35%/25%/20%/10%/10% composition above. Existing configured profiles are not silently rebalanced; newly added dimensions receive zero weight for compatibility until the CIO/administrator enables them. A delegated task enters `team_contribution` only when it explicitly selects `performance_bucket=team_contribution` and its type is Technical Research, Cross-team Support, or Knowledge Sharing; the server rejects other categories.

## 6. Role scoring profiles

The default profiles remain 100 points, with editable weights that must total 100% per enabled profile. The role catalog includes `it_bm`, `it_bp`, `it_tm`, product, project, development, operations, security, data governance, AI, architecture, and other platform profiles. The detailed Chinese PRD is the normative dimension catalog; this English mirror preserves the same role and review rules.

The `it_tm` overlay is scored separately only when it represents genuine resource-pool leadership in addition to a functional leader role. It covers people/capability governance and must not duplicate functional delivery dimensions.

## 7. Team contribution score (fixed 20% of regular performance)

Team contribution is a 100-point score made of six dimensions:

| Dimension | Weight | Sources |
|---|---:|---|
| Special activity contribution | 20% | Activity campaigns and campaign tasks. |
| Learning and growth | 20% | Learning tasks, certifications, research, rotations, and labs. |
| Training and knowledge sharing | 15% | Training hosting/organization/participation and internal sharing. |
| Suggestions and process improvement | 15% | Suggestions submitted/liked/adopted and implemented improvements. |
| Knowledge assets and retrospectives | 15% | Knowledge articles, incident retrospectives, root-cause analysis, and runbooks. |
| Cross-team support and critical assistance | 15% | Major-incident support, cross-line work, mentoring, and critical assistance. |

```text
Dimension score = min(100, max(0, period points / configured target points × 100))
Team contribution = Σ(dimension score × dimension weight)
```

Targets are configurable by CIO, with role/family defaults and optional person overrides. A dimension with no contribution scores 0. No dimension uses team-maximum normalization. One event maps to one contribution dimension.

The points ledger must distinguish two buckets:

- `role_result`: ticket SLA, change compliance, requirement delivery, project milestones, and process-governance outcomes. These facts support role scores and do not enter the fixed 20% again.
- `team_contribution`: activities outside normal role results, learning, knowledge sharing, improvement, and cross-team support. These facts enter the fixed 20% only.

`PointRule` and `PointEntry` therefore require `contribution_bucket` and `contribution_dimension`. Existing ticket, requirement, and project events may remain in the ledger for traceability, but are `role_result` by default when they already drive a role metric. Bonus and penalty remain separate.

Bug-fix completion and delegated-task closure use `bug_fix_task_done` and `delegated_work_done` rules and are `role_result` by default. The same source record can create only one point entry. Only server-approved team-contribution task types use the corresponding team-contribution rule and dimension.

`bug_fix_delivery` and `delegated_work_delivery` use the assignee, planned completion date, and actual close date. An open task is excluded before its due date; a task still open at due date or aborted is included in the denominator but not the on-time numerator. Explicit Technical Research, Cross-team Support, and Knowledge Sharing delegated tasks map to `learning_growth`, `cross_team_support`, and `training_knowledge`, respectively.

### Learning and growth goals

The first implementation lets each employee maintain learning and growth goals for the selected review period: goal, target/acceptance description, actual completion percentage, evidence, and notes. The system averages the employee's goals for that period and writes an idempotent `learning_growth` points entry, capped at the configured 30-point dimension target. Administrators, the CIO, and the IT team lead can view team goals; a later acceptance workflow can be added without changing the stored goal or points history.

## 8. CIO configuration and review workbenches

Configuration supports role profiles, dimensions, weights, evidence rules, per-period role assignments, evaluator assignments, role-result source mappings, lifecycle states, snapshots, and audit logs. Team-contribution targets and point-rule mappings are maintained under Activity Points → Point Rules.

The “Performance → Scoring Rules” page owns role-result rules only: each role profile's dimension weights (100% within the role), system source mappings, process/RACI step mappings, and the current-period employee role matrix (business/professional roles total 80%). The fixed 20% team-contribution event rules, targets, and satisfaction mix are maintained under “Activity Points → Point Rules” and are not duplicated here. Administrators and the CIO can edit the corresponding rule page for pre-release validation.

The performance overview reads the matrix-role period result and does not fall back to or display the legacy `perf_scheme` default. To add a non-default rule, select **Add role rule** in Scoring Rules, then assign the role and its business/professional weight to an employee in the period detail; role weights must total 80% and team contribution remains fixed at 20%.

The current-period role matrix is aggregated to one row per employee; the employee detail page contains all role allocations and supports CIO/admin weight adjustments. Recompute generates defaults only for a new period or an explicit reset, and preserves manual period-weight overrides.

The staged review workbench must provide:

- an employee-level overview with one row per employee, summarizing role assignments, business/professional contributions, team contribution, regular score, and current total score;
- a dedicated employee detail page showing every role and dimension, including role weights, system reference scores, manager proposals, CIO final/adjusted scores, effective scores, and adjustment reasons. CIO/admin users can edit that employee’s role weights; scoped reviewers and CIO can edit permitted dimension scores;
- a business-line lead view limited to business-role components in the lead's scope;
- a professional-line lead view limited to professional-role components in the lead's scope;
- a CIO view of all roles, leader scores, external-data results, platform dimensions, and final scores;
- a side-by-side display of system reference score, current proposal, effective score, delta, reason, and evidence;
- no self-review task and no access to another reviewer's fields outside scope;
- CSV/Excel export for authorized reviewers.

The external-input page supports period, metric, target, evaluator name/department, raw score, raw scale, normalized score, comments, evidence references, inputter, and status (draft/submitted/verified/locked). External business satisfaction is stored separately from internal ITSM satisfaction. Locked facts can only be corrected through a new version.

The page also shows an indicator-definition list with code, source (system/external/derived/manual), collection method, calculation definition, and consuming roles. Only external raw facts such as external business satisfaction are entered there; the internal/external satisfaction metric is derived and must not be entered directly.

External business satisfaction is entered by business service domain, not by manually typing a person ID. The resulting score applies only to that domain's owner (including backup owner) and its IT BP, not to business-department members or other professional-line staff.

The employee result page exposes only the published role scores, team contribution, bonus, penalty, and final score. It must not expose reference scores, preliminary adjustments, CIO deltas, reviewer identities, or external comments.

## 9. Data model and API handoff

Suggested objects:

- `performance_period`: period, version, status, publish/lock metadata;
- `performance_role_profile` and `performance_role_dimension`: role profile and its 100-point dimensions;
- `performance_role_assignment`: period person-role snapshot, line type, weight, scope, evaluator, and `review_mode`;
- `performance_external_input`: external raw fact, evaluator, scale, evidence, normalized value, and lock state;
- `performance_score_component`: system score, business-lead score, professional-lead score, CIO score, effective score, reason, and evidence;
- When a role has multiple reviewers, each reviewer's score/reason/evidence is retained and the stage score is calculated using the period snapshot's `evaluator_weights`.
- `performance_review_action`: append-only review, submission, publish, unlock, and version actions;
- `performance_score`: published role, contribution, regular, and final score snapshot;
- `learning_growth_goal`: period-scoped employee goal, completion percentage, evidence, notes, and calculated points;
- `point_rule.contribution_bucket` and `point_entry.contribution_bucket` for role-result/team-contribution separation.

Existing `perf_scheme` may be migrated to role profiles or temporarily support `binding_type=role`. `perf_override` must not remain an unrestricted overwrite; migrate it to stage-aware score components or keep it read-only for history. `perf_adjustment` remains unchanged.

Suggested endpoints:

```text
GET/POST/PATCH /api/admin/performance/role-profiles
PUT /api/admin/performance/role-profiles/{id}/dimensions
GET/PUT /api/admin/performance/assignments?period=YYYY-Qn
GET /api/admin/performance/reviews?period=YYYY-Qn
GET /api/admin/performance/reviews/person/{person_id}?period=YYYY-Qn
PUT /api/admin/performance/reviews/{assignment_id}/components/{dimension_code}
GET/POST/PATCH /api/admin/performance/external-inputs
GET /api/admin/performance/external-inputs?period=YYYY-Qn
GET /api/admin/performance/metric-definitions
POST /api/admin/performance/{period}/recompute
POST /api/admin/performance/{period}/submit-manager-review
POST /api/admin/performance/{period}/submit-cio-review
POST /api/admin/performance/{period}/publish
POST /api/admin/performance/{period}/unlock
GET /api/my/performance?period=YYYY-Qn
GET/POST/PATCH/DELETE /api/team/learning-growth?period=YYYY-Qn&scope=mine|team
GET/PUT /api/admin/performance/contribution-rules
```

All writes must enforce IT-team scope, stage/field-level authorization, weight totals, external-input validation, audit logging, immutable published history, and idempotent point/recompute events. `/api/my/performance` must return published data only.

## 10. Acceptance criteria

1. Every active IT member other than the CIO receives scoring assignments from the period role snapshot; missing roles are explicit.
2. Every enabled role profile totals 100%; every person's business/professional weights total 80%; team contribution is fixed at 20%.
3. Business-line and professional-line leads can adjust only their assigned role scope and cannot self-score.
4. CIO can adjust all scores and directly score leaders and platform-role dimensions.
5. System reference scores, manager proposals, CIO decisions, and effective scores are separately traceable with reason and evidence.
6. External business satisfaction can be entered, verified, locked, versioned, and combined with internal ITSM satisfaction by rule.
7. Platform roles default to `review_mode=cio_direct` and do not create ordinary manager-review tasks.
8. Learning-task completion creates an idempotent `learning_growth` points entry and cannot be self-confirmed.
9. Team contribution is target-based rather than team-maximum-based, and role-result facts are not counted again in the fixed 20%.
10. Bonus and penalty remain separate from the three regular-score components.
11. Before publication, evaluated employees cannot access review details; after publication, they can access only their own final result.
12. Role changes, evaluator replacements, review actions, publication, unlocking, and republishing are auditable and historical periods are reproducible.
