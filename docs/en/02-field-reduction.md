# New_AOM Field Reduction List

> English translation of [../02-字段裁剪清单.md](../02-字段裁剪清单.md). For the authoritative version, the Chinese source prevails.

> Based on [01-redesign-proposal.md](01-redesign-proposal.md), this annotates the treatment of every field against the actual SN-AOM model.
> Field names / types / comments are all taken from `SN-AOM/mcp_servers/db/models/` (measured, not estimated).

**Treatment legend**:

- **Required** — a required field on the creation form
- **Optional** — an optional field on the creation form (collapsed under "More" by default)
- **Staged** — not on the creation form; entered in a later lifecycle stage (e.g. at resolution or closure)
- **Conditional** — shown only for a specific type (e.g. when the ticket is a change)
- **Automatic** — system-generated / computed / carried over, with no input entry point
- **Deleted** — the new system does not want this field

---

## 1. Ticket `ticket` (51 fields → 5 required on creation + 3 optional)

| Field | Description | Treatment | Notes |
| --- | --- | --- | --- |
| ticket_code | Ticket code | Automatic | Rule-generated |
| title | Title | **Required** | |
| description | Description | **Required** | |
| ticket_type | Type | **Required** | incident / service_request / change (problem uses its own table) |
| priority | Priority | **Required** | P1–P4 |
| service_item_id | Service item | **Required** | Dropdown; SLA / service line are carried over from it |
| assignee | Assignee | Optional | If empty, defaults to the assignment for the process step |
| application_id | Linked CI | Optional | |
| remarks | Remarks | Optional | |
| service_line | Service line | Automatic | Carried over from the service item |
| business_tier | Business tier | Deleted | Queryable from the service item / CI; not stored on the ticket |
| status | Status | Automatic | State-machine driven |
| submitter | Submitter | Automatic | The current logged-in user (editable) |
| submitter_dept | Submitting department | Automatic | Carried over from personnel master data |
| submitted_at / first_response_at / resolved_at / closed_at | Four timestamps | Automatic | Stamped on state transitions |
| sla_response_min / sla_resolution_hours | SLA targets | Automatic | Matched by the service item's SLA policy |
| actual_response_min / actual_resolution_hours | Actual elapsed time | Automatic | Computed from timestamps |
| sla_response_met / sla_resolution_met | SLA attainment | Automatic | Computed |
| first_time_fix | First-time fix | Automatic | Inferred from whether it was reopened |
| solution | Solution | Staged | Required at resolution |
| root_cause | Root cause | Staged | Optional at resolution (recurring problems should be moved to problem management) |
| closure_code | Closure code | Staged | Dropdown at closure |
| satisfaction | Satisfaction | Staged | Follow-up after closure, optional |
| resolution_category | Resolution category | Deleted | Duplicates closure_code |
| change_type | Change type | Conditional | change only: standard / normal / emergency |
| risk_level | Risk level | Conditional | change only |
| change_reason | Change reason | Conditional | change only |
| rollback_plan | Rollback plan | Conditional | change only |
| planned_start_at / planned_end_at | Change window | Conditional | change only |
| implementation_plan | Implementation plan | Conditional | change only, optional |
| change_requester | Change requester | Deleted | Duplicates submitter |
| approval_instance_id / approval_status | Approval | Automatic | Written by the change-approval flow |
| conflict_check_result | Conflict check | Deleted | |
| cab_reviewer / cab_decision | CAB review | Deleted | Folded into the approval record |
| pir_outcome | Post-implementation review | Deleted | Low-frequency machinery |
| cia_impact / annex_a_control / containment_status / evidence_preserved | ISO 27001 security-incident 4 fields | Deleted | Removed with the governance domain |
| linked_requirement_code | Linked requirement | Optional | Auto-written when a requirement is handed off |
| doc_link | Document link | Deleted | Carried via remarks/attachments |
| catalog_id | Catalog | Deleted | Derived from the service item |

**Result**: creating a ticket actually enters 5 items (3 items such as assignee are optional and collapsed); change-type tickets expand +6 conditional fields; resolution/closure each add 1–2 items. 17 automatic fields, 13 deleted.

## 2. Requirement `requirement` (41 fields → 4 at registration + 5 at analysis)

| Field | Description | Treatment | Notes |
| --- | --- | --- | --- |
| requirement_code | Code | Automatic | |
| name | Title | **Required** (registration) | |
| description | Description | **Required** (registration) | |
| req_type | Type | **Required** (registration) | Trimmed to 5: business / functional / data / integration / compliance |
| business_line | Owning business | **Required** (registration) | |
| requester | Requester | Automatic (registration) | Defaults to the current user, editable |
| source | Requirement source | Optional (registration) | |
| priority | MoSCoW priority | Staged (analysis) | |
| owner | Owner | Staged (analysis) | |
| target_date | Scheduled target date | Staged (analysis) | Resource scheduling |
| acceptance_criteria | Acceptance criteria | Staged (analysis) | Checklist-style JSON, aligned with the business |
| *(new)* solution | Solution | Staged (analysis) | Missing in the original table; added |
| status | Status | Automatic | Registration → Analysis → Implementation → Closed state machine |
| submitted_at | Registration time | Automatic | |
| actual_completion_date | Completion date | Automatic | Stamped at closure |
| business_value / technical_complexity / urgency | Three-dimension scoring | Deleted | The single MoSCoW priority is sufficient |
| weighted_score | Weighted score | Deleted | Removed with the three-dimension scoring |
| approved_at | Approval time | Deleted | No multi-approver flow |
| elicitation_method | Elicitation method | Deleted | Removed with elicitation sessions |
| baseline_version | Baseline version | Deleted | Removed with version snapshots |
| product_category / ai_data_subtype / model_datasource / quality_metrics / security_level / linked_agent_product / capability_domain | 7 fields for the old org's specialized taxonomy | Deleted | |
| bdo_owner / bdo_score / bdo_comment / bdo_reviewed_at / bdo_status | 5 BDO-review fields | Deleted | The review machinery is deleted wholesale |
| service_line | Service line | Deleted | Keeping the single service_item_code association is enough |
| service_item_code | Linked service item | Optional | |
| project_id | Linked project | Staged (implementation) | Attached at the implementation stage |
| initiative_id | Linked initiative | Deleted | The Portfolio domain is removed |
| change_ticket_id | Linked change ticket | Automatic | Written on hand-off/linkage |
| parent_requirement_id | Parent requirement | Optional | For requirement breakdown |
| doc_link | Document link | Optional | |
| remarks | Remarks | Optional | |

**Result**: registration has 4 required fields (requester is carried over automatically); the analysis stage adds 5; the implementation stage attaches a project + task breakdown (new table `requirement_task`: task name / assignee / planned date / status, with progress auto-rolled-up); the closure stage requires zero entry (one-click hand-off to problem/knowledge). 21 fields deleted.

## 3. Project `project` (23 fields → 4 required on creation + 3 optional)

| Field | Description | Treatment | Notes |
| --- | --- | --- | --- |
| project_code | Code | Automatic | |
| name | Name | **Required** | |
| pm | Project manager | **Required** | |
| planned_start / planned_end | Planned start-end | **Required** | |
| *(changed)* portfolio_id | Owning portfolio | Optional | Replaces initiative_id; hangs on the new lightweight portfolio table |
| description | Description | Optional | |
| budget_10k | Budget (10k) | Optional | Can also be added on the Cost page |
| status | Status | Automatic | State machine |
| actual_start / actual_end | Actual start-end | Automatic | Stamped on state transitions |
| actual_cost_10k | Actual cost | Automatic | Rolled up from cost details (details entered on the Cost page) |
| progress_pct | Progress | Automatic | Weighted roll-up of WBS task completion |
| health_status | Health | Automatic | Computed from progress deviation / milestone overdue / cost deviation rules |
| latest_update | Latest update | Staged | One-line weekly report, updated anytime on the detail page |
| linked_requirement_code | Linked requirement | Automatic | Back-written when attached during the requirement implementation stage |
| service_item_code | Linked service item | Optional | |
| service_line | Service line | Deleted | Carried over from the service item |
| methodology | Methodology | Deleted | The agile/waterfall tag provides no real management input |
| moscow_priority | MoSCoW | Deleted | Not needed at the project level |
| approval_instance_id / approval_status | Initiation approval | Deleted | No approval flow initially; add it with the notification capability when needed |
| doc_link | Document link | Deleted | Replaced by the Document Management page |

### 3a. WBS task `wbs_task` (19 fields → 4 entered + 3 optional)

| Field | Treatment | Notes |
| --- | --- | --- |
| task_name | **Required** | |
| assignee | **Required** | |
| start_date / end_date | **Required** | Gantt depends on them |
| description | Optional | |
| deliverable | Optional | Deliverable |
| predecessors | Optional | Gantt dependency lines |
| wbs_code | Automatic | Generated by tree level (formerly hand-typed 1.1.3) |
| status | Staged | Dropdown updated while in progress |
| progress_pct | Automatic | Mapped from status (Not started 0 / In progress 50 / Done 100); not entered separately |
| duration_days | Automatic | Computed from start-end dates |
| project_id / parent_task_id | Automatic | From page context |
| responsible_role | Deleted | assignee is enough |
| priority | Deleted | |
| story_points / effort_days | Deleted | Effort management not done |
| is_milestone | Deleted | Milestones have their own table |
| budget_weight | Deleted | SPI simplified to auto-compute by schedule weight |

Milestone `milestone`(8) and Risk `risk`(7) are already lightweight — all kept, with 3–4 items entered.

## 4. CMDB: `application`(31) + 8 `asset` tables → merged single table `ci` (12 fields)

| New `ci` table field | Treatment | Source / notes |
| --- | --- | --- |
| ci_code | Automatic | |
| name | **Required** | |
| category | **Required** | 9 categories: Application / Server / Cloud Resource / Network / Security / Collaboration / Endpoint / Infrastructure / Consulting |
| status | **Required** | Default "Running" |
| owner | **Required** | Corresponds to it_owner |
| environment | Optional | Production / Test / Development |
| business_owner / vendor_id / description / launch_date / remarks | Optional | vendor changed to a foreign key referencing the vendor table |
| attrs (JSONB) | Optional | Category-specific attributes: 5 fields such as tech_stack, deploy_mode, user_scale, purchase cost/depreciation, placed in as needed without taking a column |

**Deleted** (the 19 columns of the original `application`): name_en, business_domain, business_line, business_tier, lifecycle_strategy, delivery_model, deploy_mode†, tech_stack†, integrations, github_repo, annual_budget_10k, security_level, compliance_cert, user_scale†, last_review_date, business_lines, the 6 depreciation fields prefixed with `purchase_`† (those marked † are demoted into attrs JSONB and are no longer form fields). `ci_relationship`(6) is kept as-is to support impact analysis.

## 5. Service item `service_item` (19 → 10)

**Keep**: item_code (automatic), name (required), catalog_id (required, pick a catalog), service_type, owner, description, sla_response_hours, sla_resolution_hours, target_audience (optional), status (automatic).

**Delete**: name_en, backup_owner, delivery_method, service_hours, annual_volume (changed to live statistics), launch_date, last_review_date, business_lines, remarks.

`service_catalog`(13) keeps the Gold/Silver/Bronze tiering and likewise drops redundant fields like name_en.

## 6. Knowledge `knowledge_article` (14 fields, form 38 items → 4 items)

**Enter 4 items**: title, content, tags, linked_ticket_codes (optional).

**Automatic**: article_code, author, status, view_count, helpful_count. category is folded into tags.

**Delete**: review_due_at, reviewed_at, reviewer, review_status (the knowledge-review machinery is deleted).

## 7. Problem `problem` (11 fields, mostly kept)

**Create**: title (required), description (required), priority (required), service_line → changed to service_item_id (optional).
**Staged**: root_cause, workaround (filled after analysis).
**Automatic**: problem_code, status, linked_ticket_codes (written on ticket escalation / requirement hand-off), ticket_id.

## 8. Growth points: `growth_record`(27) + `innovation_idea`(10) → auto ledger + minimal suggestions

Problems with the old model: `growth_record` required members to manually declare 27 fields (problem description / solution / improvement ratio / reproducibility / word count / usefulness / novelty / demo-effect scoring / monthly / quarterly …), then go through review scoring — both entry and review are burdensome.

**New model: points are not entered; they are auto-generated by events across domains.**

### 8a. `point_rule` — point rules (admin-configured, ~6 fields)

| Field | Treatment | Notes |
| --- | --- | --- |
| rule_code / name | Configured | e.g. "Ticket resolved on time" |
| event_type | Configured | See the event list below |
| points | Configured | Point value (negative supported) |
| active | Configured | Enable/disable |

**Auto-triggered point events** (all point values configurable):

| Source | Event |
| --- | --- |
| Service contribution | Ticket resolved, both SLAs met, satisfaction praise, problem root cause identified |
| Project contribution | WBS task completed on time, milestone delivered |
| Requirement contribution | Requirement task completed, requirement fully closed |
| Training contribution | Presenting/organizing training, attending training |
| Knowledge contribution | Publishing a knowledge article, article marked "helpful" |
| Suggestions | Submitting a suggestion, suggestion liked, suggestion adopted |

### 8b. `point_entry` — points ledger (fully automatic, zero entry)

person / event_type / points / source_ref (the triggering entity's GLID) / earned_at / remark. Admin manual point adjustments also go through the ledger for traceability. The leaderboard, personal points, and monthly trends are all aggregated live from the ledger, with no pre-computed table; the points total is also one of the input sources for performance evaluation.

### 8c. `idea` — suggestions (replaces innovation_idea, 2 items entered)

| Field | Treatment | Notes |
| --- | --- | --- |
| title | **Required** | |
| description | **Required** | |
| idea_code / submitter / status / like_count | Automatic | status: Submitted / Adopted / Implemented, advanced by admin |
| category / business_case / expected_impact / pilot_results / champion | Deleted | The business-case machinery is cut; implementing an adopted suggestion goes through a requirement or project |

`idea_like` (idea_id + person, prevents duplicate likes) supports like-based points.

**All 27 `growth_record` fields deleted**: efficiency-case / knowledge-output content is instead carried by knowledge-base articles (publishing earns points), AI demos / technical research are carried by Training & Development's `development_activity`, and the review-scoring machinery (practicality / innovation / presentation_quality / grade / score / composite_score / review_status / approval) is no longer needed — point rules price contributions automatically.

---

## 9. Entry-Reduction Ledger

| Form | SN-AOM entry items | New_AOM required on creation | Notes |
| --- | --- | --- | --- |
| Ticket | 26 Form.Items | **5** | +3 optional; +6 conditional for changes |
| Requirement | 24 Form.Items | **4** (registration) | +5 more at analysis stage |
| Project | 51 Form.Items | **4** | +3 optional; or zero-typing via charter import |
| WBS task | ~12 | **4** | +3 optional |
| CI (original application 31 columns) | ~20 | **4** | Specific attributes go into JSONB, expanded on demand |
| Knowledge | 38 Form.Items | **2** (title + body) | +2 optional |
| Problem | ~10 | **3** | |
| Growth record | 27 manual declaration items | **0** | The points ledger is fully automatic; only suggestions require 2 items (title + content) |

All creation forms require ≤ 5 items, meeting the "≤ 8 required" target with room to spare.
