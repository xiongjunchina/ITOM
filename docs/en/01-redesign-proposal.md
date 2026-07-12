# New_AOM System Redesign Proposal

> English translation of [../01-系统改造建议.md](../01-系统改造建议.md). For the authoritative version, the Chinese source prevails.

> Simplified-rebuild design baseline derived from SN-AOM (/Users/xjun/Gitrepo/SN-AOM).
> Basis: 2026-07-09 product decision — retain domains 1/2/3/4/6/7+9, and remove domain 5 (Portfolio as a standalone domain) / 8 (Data Management) / 10 (Organizational Governance).
> Core goals: subtract functionality, drastically cut the number of on-screen input fields, and always auto-compute derived data.

---

## 1. New Domain Structure Overview (10 domains → 6 domains)

| New domain | Maps to SN-AOM | Treatment |
| --- | --- | --- |
| ① Overview / Dashboard | 3.1 Dashboard & Analytics | Rebuild: four panels — Service / Project / Requirement / Team — entirely in computed state |
| ② ITSM Service Management | 3.2 ITSM (10 sub-modules) | Keep 9 sub-modules, drop CSI; merge CMDB's 8 asset tables into 1 |
| ③ Project Management | 3.3 Project + the portfolio definition from 3.5 Portfolio | Rebuild as 5 tabs (was 11); demote Portfolio to a project grouping |
| ④ Requirement Management | 3.4 Requirements Engineering | Refactor into lightweight collaboration on a 4-stage lifecycle; add a hand-off-to-ITSM closed loop |
| ⑤ Process Engine | 3.6 Process Engine | Keep the three-layer structure + L1–L4 autonomy levels; drop document auto-generation and value streams |
| ⑥ Team Management | 3.7 Workforce + 3.9 Growth, merged | Refactor into 5 sub-modules: Performance / Growth Points / Position & Headcount / Training & Development / Team Culture |
| Supporting: Admin | 3.11 Admin | Keep a trimmed set: users/roles, personnel master data, state machine config, audit log |
| **Removed** | 3.5 Portfolio (stage gates / benefits / capability maps / roadmaps), 3.8 Data Management, 3.10 Organizational Governance, ITSM-CSI | Not built; historical data is retired along with the old system |

---

## 2. Per-Domain Redesign Proposals

### ① Overview / Dashboard

Old system: KPI overview + cross-domain activity feed + alerts + monthly trends + maturity assessment (Accenture 4-level model).

**New design**: a single page with four panels, all computed live on the server, **with no input entry points whatsoever**.

| Panel | Key metrics (computation source) |
| --- | --- |
| Service | Open ticket count, SLA attainment rate, change success rate, problem closure rate, contract-expiry alerts |
| Project | Active project count, health distribution, overdue milestones, budget execution rate |
| Requirement | Requirement count per stage (Registered / Analyzed / Implemented / Closed), average delivery lead time |
| Team | Member workload, performance-score Top/Bottom, growth-points leaderboard, training activity count, hiring progress |

**Cut**: maturity assessment (removed together with governance domain #10), and pre-computed tables such as `kpi_snapshot` / `*_monthly_stats` (replaced by live aggregation — the data volume is small, so there is no performance concern; this also incidentally fixes the old system's issue #85, where 20 serial queries were fired — the new version pulls all metrics in a single aggregation query).

### ② ITSM Service Management (9 sub-modules)

| Sub-module | Original table (field count) | Redesign proposal |
| --- | --- | --- |
| Ticket | `ticket`(51) | **Keep the single-table, multi-type design** (incident / service_request / change / problem share one table). Required fields on creation ≤ 8: title, type, priority, description, service item, assignee. SLA deadlines / code / response time are auto-generated. root_cause, closure_code, satisfaction, etc. move to later lifecycle stages for entry. |
| Change | `change` fields within `ticket` | Shown conditionally as a ticket type: the 3–4 fields for change window / rollback plan / risk assessment appear only when the change type is selected. |
| Problem | `problem`(11) | Keep the standalone table (already lightweight); it receives escalated tickets + problems carried over from requirements. |
| Service Catalog | `service_catalog`(13) + `service_item`(19) | Keep the two-tier structure and Gold/Silver/Bronze tiering; trim item fields to ~10 (keep SLA definitions). |
| CMDB | `application`(31) + 8 `asset_*` tables + `ci_relationship`(6) | **Merge the 8 asset tables into 1 `ci` table**: shared fields (name / category / status / owner / environment) + category-specific attributes in JSONB. application: 31 → ~12 fields. Keep `ci_relationship` (impact analysis depends on it). |
| SLA | `sla_policy`(18) + `sla_stats`(16) | Keep `sla_policy` in simplified form (P1–P4 response/resolution deadlines); **delete `sla_stats`** — attainment rates are computed live. |
| Vendor | `vendor`(9) | Kept as-is (already lightweight). |
| Contract | `contract`(11) | Kept as-is + auto-alert on expiry into the Dashboard. |
| Knowledge | `knowledge_article`(14) | Table unchanged; **the front-end form is cut from 38 Form.Items to 4**: title / body / tags / linked tickets. It receives requirement lessons captured on hand-off. |

**Cut**: CSI (`csi_improvement` 17, `improvement` 14), `itsm_governance_record`(20), `application_deployment_history` / `application_release_history`, `sla_stats`.

### ③ Project Management (5 tabs, was 11)

| Tab | Redesign proposal |
| --- | --- |
| Project Overview | Keep ~12 core fields of `project`'s 23 (code / name / PM / start-end / budget / health / status). **Add a lightweight `portfolio` table (~6 fields: name / description / owner / year) to carry the portfolio definition**; project hangs a portfolio_id to establish the association. Health is auto-computed, not entered. |
| Schedule Management | Gantt chart (rendered on the front end, no dedicated table) + WBS (`wbs_task` 19 → ~10: name / assignee / start-end / status / effort / parent task / dependencies) + milestones (`milestone` 8, kept). |
| Cost Management | Minimal budget/actual-cost entry (project level + optional WBS level); SPI/CPI auto-computed and displayed. **No full 8-metric EVM entry page.** |
| Risk Management | Keep `risk`(7) (already lightweight: probability/impact matrix + mitigation measures). |
| Document Management | A simple attachment table + **port `project_charter_import.py`** (uploading a charter auto-generates draft project / WBS / milestones / risks — the pillar feature of "enter less"). |

**Cut**: stakeholder matrix, baseline (`scope_baseline`), quality-metrics page, the three gate-review tables (`project_gate_*`), `project_monthly_stats`, `risk_snapshot`, `process_gate_signal`. The project detail page, formerly 51 Form.Items, is projected to drop to ~15.

### ④ Requirement Management (lightweight collaboration, 4-stage lifecycle)

The original `requirement` (41 fields) + 10 peripheral tables are refactored into progressive, stage-by-stage entry:

| Stage | What is entered | Notes |
| --- | --- | --- |
| 1. Registration | title / type / requester / owning business / description (**5–6 fields**) | 30-second registration |
| 2. Analysis | priority (MoSCoW) / solution / resource scheduling / acceptance criteria | Acceptance criteria reuse `acceptance_criterion`, simplified into a checklist JSON |
| 3. Implementation | task breakdown (new lightweight `requirement_task` table) / progress control / acceptance closure | Progress is auto-computed from task completion |
| 4. Close-out | **One-click hand-off**: legacy problems → ITSM `problem`; lessons captured → ITSM `knowledge_article` | New cross-domain linkage (absent in SN-AOM); the requirement context is carried automatically on hand-off |

**Cut**: version snapshots (`requirement_version`), multi-approver workflow (`requirement_approval`), traceability (`traceability`, downgraded to simple linked-project/ticket fields), elicitation sessions (`elicitation_session`), validation issues (`requirement_validation_issue`), `requirement_monthly_stats`.

### ⑤ Process Engine (keep the skeleton, cut the heavy machinery)

**Keep**: the three layers `process_definition` → `process_instance` → `process_task` + `process_step`, and the L1–L4 autonomy levels (an AOM signature feature; performance-management scoring rules may also use autonomy-level data in the future).

**Simplify**:

- Initially seed only the processes the new system actually uses (ticket handling, change approval, requirement delivery, project key milestones — about **6–8 processes vs. the original 36**).
- **Cut the 72 auto-generated document types** (the 3 tables `process_document_type` / `process_step_document` / `process_document_instance`).
- Cut value-stream orchestration (`value_stream_rule`) and `process_step_skill`.
- Downgrade auto-assignment from "n8n parsing by cell/skill/load" to "default role/person assignment configured per process step" (no dependency on n8n).

### ⑥ Team Management (new domain = Workforce + Growth, merged and refactored)

| Sub-module | Design | Handling of the old tables |
| --- | --- | --- |
| Performance Management | Add `performance_rule` (scoring rules; the rule content is defined by product later, and the engine aggregates data per the rules) + `performance_score` (period-scoring results, computed state). Data sources: tickets (resolution volume / SLA / satisfaction), projects (task completion / milestones), requirements (delivery lead time), **growth points (one of the input sources)**. | Delete `cell_performance`(20) / `kpi_snapshot` / `growth_monthly_stats` (all pre-computed tables). |
| Growth Points | Add `point_rule` (configurable point rules: event type → points) + `point_entry` (points ledger, **auto-generated by events across domains; users do not enter points**). Point sources: service contribution (ticket resolution / SLA attainment / satisfaction praise), project contribution (WBS task completion / milestone delivery), requirement development task completion, training contribution (presenting / organizing / attending), knowledge-base contribution (publishing / marked helpful), suggestions (submitting / adopted / liked). The leaderboard aggregates the ledger live, with no pre-computed table; admins can manually adjust points up or down (recorded through the ledger for traceability). | Replaces `growth_record`(27)'s manual-entry mode and the pre-computed leaderboard. |
| Position & Headcount | Keep `org_master`(13) as the personnel master-data core; add `position` (position definition / division of duties) and `hiring_need` (hiring needs and progress). | `skill` / `person_skill` kept in simplified form (needed for position duties); the `ops_resource` load table is deleted and replaced by computation. |
| Training & Development | Add `development_activity` (~10 fields: type [internal cross-training / external technical exchange / new-technology research] / topic / participants / date / output link); completing registration triggers training points. | Replaces `growth_record`(27). |
| Team Culture | Add `team_charter` single-page content management (vision / goals / code of conduct, rich text); add `idea` (suggestions: title / content, only 2 items to submit) + `idea_like` (like records, duplicate-proof); liking/adoption auto-triggers points. | `innovation_idea`(10) simplified and refactored into suggestions. |

**Cut**: the AI Agent registry (`agent`, **70 fields**, `agent_evaluation` 24), orchestration routing (`orchestration_rule`), escalation rules (`escalation_rule` / `escalation_log`), anomaly clustering / model feedback (`knowledge_feedback`), Cell organization (demoted to a `team` grouping field on org_master).

> ⚠️ Dependency note: the process engine's "auto-assignment / escalation" originally depended on the agent/cell/escalation machinery. After the simplification above (default role assignment), it can be safely cut; if AI Agents are to participate in workflows again in the future, add back a minimal agent registry then.

---

## 3. Data Model Scale Comparison

| | SN-AOM | New_AOM target |
| --- | --- | --- |
| Data tables | 106 | **~42** (ITSM 10, Project 7, Requirement 4, Process 4, Team 11, auth/master-data/state-machine/audit 6) |
| Derived statistics tables | ~15 (monthly_stats / sla_stats / kpi_snapshot / cell_performance / snapshot family) | **0** (all computed live) |
| Heaviest entry forms | Project 51 items / Knowledge 38 items / Ticket 26 items | Target: any creation form has **≤ 8 required items**, with advanced fields collapsed or staged |
| Ticket fields | 51 | ~8 required on creation, the rest staged/automatic across the lifecycle |
| Requirement fields | 41 + 10 peripheral tables | Registration 5–6, +4 at analysis stage, peripheral tables → 2 |

## 4. Reuse & Tech Stack

Reuse the SN-AOM tech stack (FastAPI + SQLAlchemy + React, to ease code porting). Assets ported directly:

1. `project_charter_import.py` — document-import auto-backfill (the "enter less" pillar).
2. GLID 26-character primary-key generation — reuse the same primary-key convention (keeps the team's habits; unrelated to migration).
3. The `workflow_status` / `workflow_transition` state machine — prevents illegal state jumps.
4. The unified response `{success, data, total, page}` convention.
5. The three-layer process-engine model (simplified seeding).

**Data migration: not performed.** All old data is discarded; New_AOM starts on an empty database, and business data is re-entered by users (2026-07 product decision).

**Not done initially**: n8n workflows, Feishu integration, MCP servers, GitHub integration (to be wired up later on demand via the shared sn_feishu / sn_maestro spine, aligned with SN-AOM epic #51).

### Notification Capability Reserved (designed for future Feishu integration)

There is no external notification channel initially, but the architecture reserves for one:

- **Domain-event outlet**: all key actions (ticket created / escalated / SLA imminent, approval request, milestone overdue, requirement hand-off) go through the single entry point `notification_service.notify(event)`; business code never sends notifications directly.
- **Channel-adapter pattern**: a `NotificationChannel` abstract interface + a `notification_outbox` table (events persisted, with event_type / payload / channel / status). Initially only `InAppChannel` is implemented (in-app messages / Dashboard alerts); later, adding a `FeishuChannel` adapter connects it with zero changes to the business layer.
- The event payload follows the old system's `fire_workflow_event()` structural convention, so it is ready to use out of the box when the sn_feishu spine is later connected.

## 5. Product Decision Log (confirmed 2026-07-09)

1. **Project management tabs** — "Schedule Management" appearing twice was a typo; finalized at 5 tabs: Project Overview / Schedule Management / Cost Management / Risk Management / Document Management.
2. **Performance scoring rules** — the framework is built to be "rule-configurable"; the concrete rules are defined by product later.
3. **Data migration** — not performed; a brand-new empty database, re-entered.
4. **Feishu** — not connected initially, but designed per the "Notification Capability Reserved" section above.
5. **Growth points** — kept and folded into the Team Management domain: point sources cover service contribution / project contribution / requirement development tasks / training contribution / knowledge-base contribution / suggestion likes; the points ledger is auto-generated by events across domains (rule-configurable) and serves as one of the input sources for performance evaluation.
