# ITOM Data Model Design

> English translation of [../04-数据模型设计.md](../04-数据模型设计.md). For the authoritative version, the Chinese source prevails.

> Based on PRD v1.2 and the approved Aily + MCP baseline. P2 code maps **81 tables**: Support 29, ITSM 16, Project 6, Requirement 4, Process 4, Team 22. P0 removed four Helpdesk tables and added four MCP support tables; P1 added form-version and dispatch-rule tables; P2 adds one ticket-rating detail table.
> Compared with SN-AOM's 106 tables, there are no manually maintained statistics tables. Process, performance, and configuration snapshots exist only for auditable, reproducible history.
> This document groups core contracts and does not relist every auxiliary/compatibility table. Aily/MCP support, dynamic-form, dispatch, and rating-detail models are implemented. Database facts must be checked against real models and migrations.

> M93 implementation-delivery routing adds only nullable/defaulted columns to existing `service_dispatch_rule` and `ticket` tables. It creates/deletes no business table and never backfills, migrates, or rewrites existing records; `business_initial_password` is deployment configuration, not a persisted business field.

## 0. Global Conventions

- Primary key: `id CHAR(26)` GLID, system-generated; not listed per-table below.
- Every table has `created_at` / `updated_at` (maintained automatically by the service layer); business-record tables have an `is_deleted BOOLEAN DEFAULT FALSE` soft-delete flag; not listed per-table below.
- Personnel references: uniformly store `org_member.id` (foreign key), displaying the name on the page.
- Business codes (`*_code`): `prefix-YYYYMM-sequence`, generated on creation, with a unique index.
- Fields marked **[C]** (computed) are system-computed/stamp-maintained with no input endpoint; tables marked **[cfg]** are maintained by admin only.

---

## 1. Support Domain (current 30)

### 1.1 auth_user — login account

| Field | Type | Description |
| --- | --- | --- |
| username | VARCHAR(64) UNIQUE | Login name |
| password_hash | VARCHAR(255) | bcrypt |
| person_id | FK→org_member | Links any company person (requester may have none; not limited by the digital-team scope) |
| roles | JSONB | Array of roles, e.g. `["it_dev","manager"]` (one person, many roles) |
| auth_source | VARCHAR(16) | local/ad/feishu/sms/wechat |
| external_id | VARCHAR(128) | External authentication identity; Feishu uses open_id |
| preferences | JSONB | language, avatar, bio, notification categories, theme, density, dashboard widgets, etc. |
| is_active | BOOLEAN | |
| last_login_at | TIMESTAMP | [C] |
| password_set_at | TIMESTAMP | Last password setup |
| initial_password_ciphertext | TEXT | Fernet ciphertext for the M44 provisioning password; cleared after change/reset |
| initial_password_sent_at | TIMESTAMP | Last administrator-triggered initial-password email time |

Incremental contract: `auth_user.preferences` may contain a `table_views` object keyed by a stable list key. Each value stores a `visible` field list and `widths` map; the API bounds keys, counts, and widths, while protected identifier/title/action columns are always retained. No new business table or destructive migration is required.

Workflow runtime uses the newest non-deleted pending `process_task` as the current-node fact. `process_instance.current_step_seq`, `Requirement.status`, and stage timestamps are compatibility projections/read models; synchronization only moves a stage forward and never rewrites closed/cancelled/on-hold records, historical tasks, or scores. `Requirement.department` remains a legacy-compatible field, but new registration and its template do not require/export it. The import service distinguishes the new registration template from the legacy scored template by headers. Personal todos are calculated from active tasks and domain records on read rather than stored as a snapshot, so they cannot drift from workflow authorization.

**M36–M37 lifecycle semantics**: account deletion uses `GlidBase.is_deleted`, disables the account, clears `person_id`, and rewrites the username to release the original value; it never deletes `org_member`. Feishu unbinding clears account `external_id` and switches the source to local without changing `person_id`.

### 1.0 department / business_domain / provision_rule (added in M3.5)

- **department**: code UNIQUE, name, parent_id self-reference, dept_type (it/business/audit), external_source/external_id (reserved for Feishu/AD sync), sort, active. One person, one department; pure data.
- **business_domain**: code UNIQUE, name, description, owner_id FK org_member (the IT-side BM, a field not a role), business_bdo_id FK org_member (the business-side BDO), sort, active. `business_bdo_id` is the additive nullable M95 column and may reference only an active business person with the `bdo` role inside the domain's served-department scope. The historic `backup_owner_id` column remains without migration or reads/writes, so old IT backup-owner values are never misidentified as BDOs and existing data is preserved.
- **business_domain_department**: unique domain_id FK business_domain + department_id FK department, plus include_children. It records which organization departments a domain serves; only active business departments may be linked, while historical links remain when a department is later disabled.
- **provision_rule**: match_type (dept_type/department), match_value, default_roles JSONB, sort (lower matches first and stops), active. Takes effect only on first account provisioning.
- **org_member changes**: drop the dept/team text columns (migrated to the department table / user groups); add name_en, department_id FK, mobile, external_source, external_id.
- **auth_user changes**: add auth_source (local/ad/feishu/sms/wechat), external_id.
- **user_group changes**: add roles JSONB (group-granted roles; a person joining the group inherits them automatically).

### 1.1a role — role registry [cfg] (added 2026-07-10)

code UNIQUE, name, description, base_role (the built-in role code that a custom role inherits; empty for built-ins), is_builtin. The 17 built-in roles are seeded and their codes are read-only; `bdo` (Business Digital Owner) is a controlled business-user subset and the Requirement-module permission is granted to it rather than to `requester`. Custom roles inherit API permissions via base_role and can be referenced by workflow_transition.allowed_roles and process_step.default_role.

### 1.1b user_group / user_group_member — user groups (added 2026-07-10)

user_group: code UNIQUE, name, description. user_group_member: group_id + person_id UNIQUE composite. The authorization/assignment reference key is `group:<group-code>`.

### 1.2 org_member — personnel master data

| Field | Type | Description |
| --- | --- | --- |
| name | VARCHAR(64) | Required |
| dept | VARCHAR(64) | Department |
| team | VARCHAR(64) | Team grouping |
| position_id | FK→position | Position |
| status | VARCHAR(16) | Active / Departed |
| hire_date | DATE | |
| email | VARCHAR(128) | |
| feishu_user_id | VARCHAR(64) | Reserved, for Feishu integration |
| skills | JSONB | Array of skill tags |
| remarks | TEXT | |

### 1.3 workflow_status — status definitions [cfg]

entity_type (ticket/problem/requirement/project/wbs_task/idea/hiring_need), code, name, is_initial, is_terminal, sort.

### 1.4 workflow_transition — status transitions [cfg]

entity_type, from_code, to_code, allowed_roles JSONB. The backend validates before every status change.

### 1.5 master_data — data dictionary [cfg]

category (business line / closure code / requirement source / CI category extension-attribute definitions …), code, name, sort, active. The source of all dropdown items.

### 1.6 audit_log — audit log (append-only)

entity_type, entity_id, action (`VARCHAR(32)`), actor, summary JSONB (before/after values of changed fields), created_at. Service action codes must be constants covered by a pre-persistence length test. Aily notification identity mapping uses `auto_map_aily_identity` for verified OAuth mapping and `auto_map_aily_identity_org` for organization-assisted reconciliation, preventing an audit insert failure from rolling back an otherwise verified Feishu sign-in transaction.

### 1.7 notification_outbox — notification outbox

event_type, entity_type, entity_id, payload JSONB, channel (in_app/feishu_aily…), status (pending/sending/sent/failed), recipient type/ID, unique idempotency key, attempt count, next attempt, provider message ID, redacted last error, and sent time. The unified notification outlet writes a `feishu_aily` text row in the same business transaction by ITOM account and uses a stable digest of event, entity, and account for idempotency. If the account has no active verified Aily-bot identity, the payload carries only the internal `auth_user_id`, recipient fields remain empty, and the row stays `pending` with `last_error_redacted=AILY_IDENTITY_NOT_MAPPED`; the worker resolves the mapping immediately before send and fills the recipient only after it exists, without consuming retry attempts while waiting. A disabled Aily integration creates no new rows; incomplete message configuration leaves rows `pending`. `feishu_aily` payloads are either the legacy-compatible `{text}` form, `{message_type: interactive, card, fallback_text}`, or a user-scoped form with internal `auth_user_id`. Card callbacks carry only public ticket codes, actions, scores, and idempotency keys—never secrets, JWTs, internal primary keys, or sensitive payloads. This change adds no fields or migration.

### 1.8 in_app_notification — in-app notification

recipient FK→org_member, title, content, link (front-end route), read_at. The data source for the top-bar bell. `POST /api/notifications/read-all` bulk-updates `read_at` for unread rows addressed to the current account's person/account recipient IDs; `POST /api/notifications/clear-read` soft-deletes already-read rows for the same recipient IDs. Neither action changes source business records.

### 1.9 attachment — generic attachment

entity_type, entity_id, filename, storage_path, size, uploaded_by. Shared by contract attachments, project documents, original charter files, Bug evidence, and supplemental files for service requests and IT requirements. Bugs use `entity_type=bug`, `entity_id=bug.id`; committed service-request files use `entity_type=ticket`, `entity_id=ticket.id`; committed requirement files use `entity_type=requirement`, `entity_id=requirement.id`; no dedicated attachment table is introduced. Before creation, drafts use `entity_type=ticket_draft` or `requirement_draft`, with `entity_id=auth_user.id`; only the uploader may bind them in the same creation transaction or cancel them. Unbound drafts are soft-deleted and their stored files cleaned after 24 hours and cannot be listed or downloaded through generic routes. Requirement Other supplemental information uses the existing `requirement.remarks`; attachment metadata is not duplicated there. Bug evidence text remains in `bug.evidence`.

### 1.10 external_identity [implemented in P0]

provider, tenant_id, app_id, subject type (open_id/user_id/union_id), subject ID, nullable auth_user_id FK while pending, status (pending/active/disabled), verified time, and last-used time. Unique `(provider, tenant_id, app_id, subject_type, subject_id)`. A JWT-verified but unapproved tenant/user is recorded only as a pending candidate and receives no tool access; it becomes authorized only after an administrator selects an ITOM account and activates it. One account may have OAuth-app and Aily-bot identities; cross-app `open_id` equality is never assumed.

### 1.11 aily_integration_config [cfg][implemented in P0]

Singleton: enabled, MCP auth mode, encrypted MCP JWT secret, allowed tenant/agent/origin arrays, bot app ID, encrypted bot secret, API base, `public_base_url`, message enabled, encrypted card-callback Verification Token, encrypted card-callback Encrypt Key, last test status/time, and redacted error. `public_base_url` stores the administrator-entered external root (the current IDC example is `https://itom.snnc.cc:30443`) and accepts only a scheme, host/IP, and optional port; it must not contain `/mcp/` or a callback path. The admin page derives the MCP, Feishu login, and card-callback URLs from it. The two callback secrets must be configured together; if either is absent, proactive delivery stays text-only. MCP JWT Secret, Bot App Secret, Verification Token, and Encrypt Key are all Fernet-encrypted, and read APIs expose configured flags only. The old `card_action_skill_id` is no longer part of the runtime model or configuration contract; an as-yet physically retained legacy column in an existing database is never read.

### 1.12 mcp_tool_call [audit][implemented in P0]

Unique call_id, tool_name, tenant/agent, external subject as subject type plus SHA-256 (never the complete external user ID), auth_user_id, session-reference hash, request digest, result code, entity type/ID, duration, and time. It never stores JWTs, app secrets, full prompts, or sensitive form answers.

### 1.13 mcp_operation_intent [active in P1]

Unique intent_id, tool, auth_user_id, normalized payload, payload digest, token hash, idempotency key, status (prepared/executed/expired), expiry/consumption times, and result entity/snapshot. Unique `(auth_user_id, tool_name, idempotency_key)`; raw confirmation tokens are not stored.

### 1.13a record_relation — generic cross-record relation [phases B/C implemented]

`id`, `source_entity_type`, `source_entity_id`, `target_entity_type`, `target_entity_id`, `relation_type`, `reason`, `created_by FK→auth_user`, `idempotency_key`, `request_digest`, `created_at`, `deleted_at`, `deleted_by FK→auth_user`, and `delete_reason`. The domain service validates entity combinations and relation type against a server-side whitelist. The first phase permits only `service_request→incident(upgraded_to_incident)`, `service_request/incident→problem(root_cause_of)`, `incident/problem→change(remediated_by_change)`, and `requirement→project(converted_to_project)`; arbitrary client polymorphic pairs and self-links to the same record are rejected (a service-request ticket may still relate to an incident ticket). Phase C stores a digest of the Pydantic-normalized target form and relation reason in `request_digest`; while holding the source-row lock, it first checks the same actor/source/target-entity-type/idempotency key, returns the first target for the same digest, rejects a different digest, and only then lets the target domain service create the target and write the relation.

Active relations are unique on `(source_entity_type, source_entity_id, target_entity_type, target_entity_id, relation_type)`. The creator/source/target-type/idempotency-key combination is also unique; `request_digest` rejects a reused key with different parameters. Combined source/target indexes support bidirectional reads. The model has no cross-table polymorphic FKs: the read service rechecks entities and visibility, while the create service rechecks fields, permission, workflow, approval, and data scope in the same transaction that creates the target, relation, and audit. Existing `problem_ticket`, `Ticket.problem_id`, and historical requirement/project relations remain unchanged, with no migration, backfill, or overwrite; no unlink action is exposed in the first phase.

---

## 2. ITSM Domain (16 in P2)

### 2.1 service_catalog — service catalog [cfg]

code, name, tier (gold/silver/bronze), description, sort, status.

### 2.2 service_item — service item [cfg]

| Field | Type | Description |
| --- | --- | --- |
| item_code | UNIQUE | Automatic |
| name | VARCHAR(128) | Required |
| catalog_id | FK→service_catalog | Required |
| service_type | VARCHAR(32) | Dictionary |
| owner | FK→org_member | |
| description | TEXT | |
| sla_response_hours / sla_resolution_hours | FLOAT | Overrides the SLA policy default; nullable |
| target_audience | VARCHAR(128) | |
| search_keywords / search_synonyms | JSONB | Aily search terms [P1] |
| typical_scenarios / exclusion_scenarios | JSONB | Included/excluded scenarios [P1] |
| active_form_version_id | FK→service_item_form_version | Active published form [P1] |
| process_definition_id | FK→process_definition | Bound process [P1] |
| default_priority | VARCHAR(8) | Default P1–P4 urgency [P1] |
| status | VARCHAR(16) | Listed / Delisted |

### 2.3 ticket — single-table ticket; normal users create service_request only

| Group | Fields | Description |
| --- | --- | --- |
| Required on creation | title, ticket_type (incident/service_request/change), priority (P1-P4), description, service_item_id FK | The service-request UI presents priority as Urgency and selects service items under a category |
| Pre-consultation fields | service_category, other_info | Stores the ITSM catalog name and supplemental information separately from internal remarks |
| Optional on creation | assignee FK, ci_id FK, remarks | Assignee/remarks are exposed in Internal Handling Information to IT staff and administrators |
| Change conditional fields | change_type, risk_level, change_reason, rollback_plan, planned_start_at, planned_end_at, implementation_plan | change type only |
| Staged fields | solution, root_cause, closure_code, satisfaction (1-5) | at resolution/closure/follow-up |
| Approval [C] | approved_by, approved_at, approval_comment | written by change approval |
| Derived [C] | ticket_code, status, submitter, submitter_dept, service_line, submitted_at, first_response_at, resolved_at, closed_at, paused_minutes (on-hold accumulation, deducted from SLA), reopen_count, first_time_fix, sla_response_min, sla_resolution_hours, sla_response_met, sla_resolution_met | |
| Links | problem_id FK→problem (back-written after escalation), requirement_id FK→requirement, process_instance_id | |
| Dynamic form [P1] | request_data JSONB, request_form_version_id, request_form_snapshot JSONB | Answers and submission-time schema |
| Supplemental attachments [M108] | generic `attachment` rows with `entity_type=ticket` | The web form supplies current-account draft attachment IDs; the domain service rechecks ownership and binds them in the same transaction as ticket creation, workflow start, and audit. No attachment metadata is stored on `ticket` |
| Acceptance-dispatch/acceptance facts | dispatch_rule_id, dispatch_source, assigned_at, accepted_at | P1 records the first-task acceptance rule/source/dispatch; P2 stamps actual acceptance on first entry to processing |
| Implementation-delivery dispatch facts [M93] | implementation_assignee, implementation_rule_id, implementation_source, implementation_selected_by, implementation_selected_at | Written only when the first service-request acceptance task completes; distinguishes self, selected colleague, item/catalog/global automatic rule, manual queue, and workflow default role; never rewritten through upstream correction |
| Confirmation | confirmation_due_at, suspected_major_impact | P2 takes the deadline from the active requester-confirmation task; broad impact remains a service-request flag |

Indexes: status, assignee, service_item_id, submitted_at, (ticket_type, status).

Normal-user creation fixes `ticket_type=service_request`; MCP does not accept the field. Incidents are created only by IT staff or monitoring identities. `ticket.satisfaction` remains a compatibility score populated from the effective rating row.

### 2.13 service_item_form_version [cfg][implemented in P1]

service_item_id, version, status (draft/published/retired), schema JSONB, publisher/time, checksum. Schema covers field code/type/label, required/default, length/range/date/options, person/department scope, conditional rules, help text, and sensitivity. Unique `(service_item_id, version)`; referenced versions cannot be physically deleted.

### 2.14 service_dispatch_rule [cfg][implemented in P1]

name, scope_type (service_item/catalog/global), scope_id, **dispatch_stage (acceptance/implementation)**, target_type (group/member), target_id, strategy (round_robin/fixed/manual_queue), priority, active, fallback, last-assigned member/time. A service item does not duplicate a current-rule FK; resolution uses `dispatch_stage + scope_type + scope_id` in item → catalog → global order. Migration classifies historic rules as `acceptance` without changing historic tickets. `implementation` is resolved only at service-request acceptance handoff; `manual_queue` intentionally creates an unassigned process task for the next step's eligible role to claim rather than selecting a person through the default role. The two stages write separate ticket facts.

### 2.15 ticket_satisfaction [implemented in P2]

Unique ticket_id, database-checked score 1–5, tags, comment, source (web/aily/feishu_card), rater, rating time, and update time. One effective rating exists per ticket; a later rating updates the same row and writes `satisfaction_create/satisfaction_update` audit. The score is copied to `ticket.satisfaction` for existing reporting.

### 2.4 problem — problem

problem_code [C], title, description, priority, status [C], service_item_id FK optional, root_cause (staged), workaround (staged), source_ticket_id FK, source_requirement_id FK (written when a legacy requirement problem is handed off).

### 2.5 problem_ticket — problem-ticket link

problem_id + ticket_id, UNIQUE composite. Supports "multiple tickets with the same root cause attached."

### 2.6 ci — configuration item (merges the original 9 tables)

| Field | Type | Description |
| --- | --- | --- |
| ci_code | UNIQUE | Automatic |
| name | VARCHAR(128) | Required |
| category | VARCHAR(32) | Required, 9 categories (dictionary) |
| status | VARCHAR(16) | Required, default "Running" |
| owner | FK→org_member | Required; technical owner for operation and maintenance |
| environment | VARCHAR(16) | Production / Test / Development |
| business_owner | VARCHAR(64) | |
| vendor_id | FK→vendor | |
| description / launch_date / remarks | | |
| attrs | JSONB | Category-specific attributes (attribute names defined by master_data per category) |

`product_manager_id` FK identifies the **Application** product manager who confirms and verifies Bugs. It is distinct from the required all-category `owner` (technical owner), though both may be the same person. It is required when an Application is created or edited; a legacy non-Application value is retained for audit but hidden from the UI. Bug registration snapshots this person; later CI product-manager changes do not rewrite historical Bugs.

### 2.7 ci_relationship

source_ci_id, target_ci_id, relation_type (runs-on / depends-on / connects-to), UNIQUE(source, target, type).

### 2.8 sla_policy — SLA policy [cfg]

priority (P1-P4, UNIQUE), response_minutes, resolution_hours, active. Service-item fields can override.

### 2.9 vendor — vendor

code [C], name, contact, phone, email, service_scope, rating, status, remarks.

### 2.10 contract — contract

code [C], name, vendor_id FK, amount_10k, start_date, end_date, owner FK, status [C] (Active / Expiring / Expired, derived from dates), remarks. Attachments go through attachment.

### 2.11 knowledge_article — knowledge article

article_code [C], title, content (Markdown), tags JSONB, status (Draft / Published), author [C], view_count [C], helpful_count [C], linked_ticket_ids JSONB, source_requirement_id FK (written when requirement lessons are handed off).

### 2.12 knowledge_vote — knowledge vote (duplicate-proof)

article_id + person, UNIQUE composite. Triggers the "marked helpful" points.

---

## 3. Project Domain (6 tables)

### 3.1 portfolio — portfolio

code [C], name, owner FK, year, description, status.

### 3.2 project — project

| Group | Fields |
| --- | --- |
| Required on creation | name, pm FK, planned_start, planned_end; created_by FK (creator account, used for first-node correction/delete authorization) |
| Optional on creation | portfolio_id FK, description, budget_10k, service_item_id FK |
| Staged | latest_update (one-line update) |
| Derived [C] | project_code, status, actual_start, actual_end, progress_pct (WBS-weighted), health_status (green/yellow/red, per PRD 6.1 rules), actual_cost_10k (rolled up from cost_entry) |

> progress_pct / health_status / actual_cost_10k are **redundant computed columns**: on task/cost/milestone changes, the service layer recomputes and writes them back synchronously (to guarantee list-filtering performance); they are not user-maintained.

### 3.3 wbs_task — WBS task

project_id FK, parent_task_id FK self-reference, wbs_code [C] (generated from tree position), task_name, assignee FK, start_date, end_date, actual_start, actual_end, status, description, deliverable, predecessors JSONB (array of task ids), progress_pct (integer 0–100%; project roll-up is duration-weighted), sort, completed_at (the first time the task reached 100%; retained as an audit fact after a later completion correction). `actual_end` is a nullable actual-finish date and cannot be later than the submission date or earlier than `actual_start`; writing a valid `actual_end` makes the domain service set current progress to 100%. `completed_locked` and `structure_locked` are derived API flags rather than persisted fields: current `progress_pct >= 100` locks actual-date edits, deletion, add-child, and structural changes, while historical `completed_at` never creates a permanent lock. An authorized correction below 100% in a separate request reopens the task and clears `actual_end` while retaining `actual_start` and `completed_at`; the derived capabilities return immediately. Structural changes still enforce authorization, references, currently completed sibling/descendant protection, and cycle checks, then recalculate affected `parent_task_id`, sibling `sort`, and `wbs_code`. This rule adds no field or database migration.

### 3.4 milestone — milestone

project_id FK, name, target_date, actual_date, description, status [C] (Pending / Achieved / Overdue).

### 3.5 risk — risk

project_id FK, title, probability (High/Medium/Low), impact (High/Medium/Low), response_plan, owner FK, status (Open / Mitigated / Closed).

### 3.6 cost_entry — cost detail

project_id FK, wbs_task_id FK nullable, date, amount_10k, description, created_by [C].

---

## 4. Requirement and task domain (5 tables)

### 4.1 requirement — requirement

| Group | Fields |
| --- | --- |
| Required at registration | title, req_type (business/functional/data/integration/compliance), business_domain_id FK, description |
| Optional at registration | source, parent_requirement_id FK, department, expected_date, expected_effect, business_value_note |
| Evaluation stage | six D1–D6 scores, decision, solution_type, PRD/dev effort |
| Analysis stage | moscow, owner FK, target_date, solution, acceptance_criteria JSONB |
| Implementation stage | project_id FK (optional attachment), implementation_route (nullable route snapshot: In-house Dev / To Project; written when routing is executed and never backfilled into history) |
| Derived [C] | requirement_code, status (`registered` / **`supplementing`** / `evaluating` / `analyzing` / `implementing` / `closed`, etc.), requester/name, stage timestamps, closure_note; `supplementing` means explicitly returned to the original requester and is neither closed nor cancelled |

### 4.2 requirement_task — requirement task

Unique non-null `task_code` (`RT-YYYYMM-NNNN`), nullable `requirement_id` FK for register-before-link, nullable `registrar` FK for administrator accounts without a person, `name`, `description`, `assignee` FK, `plan_date`, `plan_effort`, `actual_effort`, `status` (Pending / In Progress / Done), `done_at` [C], and the base model's persisted `created_at` registration time. A direct registration stores the current actor's person; conversion from a requirement stores the original requirement requester's linked person rather than the converter. A standalone task can be linked later. Startup migration drops PostgreSQL's NOT NULL constraint on `requirement_id` and fills only missing historical task codes using the original `created_at` month and deterministic `created_at + id` order. It never overwrites, deletes, or rebuilds existing rows. Import adds no batch table and overwrites no existing task.

### 4.3 bug — defect record

`bug_code` [C], `title`, `description`, `priority`, `status`, `ci_id` FK (the selectable system comes from CMDB), `product_manager_id` FK (snapshotted system product manager), `dev_leader_id` FK, `reporter_id` (also the list's Registrar display), `source_type/source_id`, reproduction details, expected/actual results, environment, `evidence` text, resolution and verification notes, rejection reason, and reopen/close timestamps. Screenshot, log, and other binary evidence is related through generic `attachment(entity_type=bug, entity_id=bug.id)` without duplicating file metadata. Bugs use a dedicated process and do not reuse the ITIL `problem` table.

### 4.4 bug_fix_task — Bug repair task

Unique non-null `task_code` (`BT-YYYYMM-NNNN`), `bug_id` FK, `name`, `task_type` (development/testing/other), `description`, `assignee` FK, `plan_start`, `plan_date`, `plan_effort`, `actual_effort`, `status` (Registered / Scheduled / Executing / Paused / Closed), `done_at`, `completion_note`, and the base model's persisted `created_at` registration time. A Bug may have multiple development or testing rows; all required child tasks must be closed before product-manager verification. The parent Bug keeps its `BG-YYYYMM-NNNN` code and never shares a child code. Startup migration fills only missing historical child codes by original registration month and deterministic creation order, without changing parent-child relations or business fields.

### 4.5 work_task — delegated work task

`task_code` [C], `title`, `description`, `task_type`, `source_type/source_id`, `registrar` FK, `assignee` FK, `priority`, `plan_start`, `plan_date`, `plan_effort`, `actual_effort`, `status` (Registered / Scheduled / Executing / Paused / Closed / Aborted), `performance_bucket`, pause/abort reasons, completion note, and close time. Sources may be tickets, problems, incidents, Bugs, manual technical research, or other IT work.

Only the registrar may delete an unassigned task still in Registered status. After assignment and before closure, deletion is administrator-only. Deletion is soft and audited; administrators can edit, pause, abort, and close from the list.

### 4.6 project_development_task — project development task

Unique non-null `task_code` (`PT-YYYYMM-NNNN`), required `project_id` FK, optional `wbs_task_id` FK, `title`, `description`, `acceptance_criteria`, `task_type`, `registrar` FK, `assignee` FK, `priority`, `environment`, `version`, planned dates, planned/actual effort, `status` (Pending / In Progress / Done, the sole state authority), `completion_note`, `done_at`, and the base model's persisted `created_at` registration time. Direct registration stores the current actor; project/WBS conversion stores the project manager. The server validates that a selected WBS row belongs to the project. Non-administrators may delete only Pending rows; administrators retain audited deletion authority. Completion is not a second state field: reads derive it from `task_progress_entry`, returning 100% for Done and otherwise the newest non-null percentage capped at 99%.

### 4.7 task_progress_entry — append-only task progress

`task_kind`, `task_id`, nullable `author_id` FK, `author_name` snapshot, optional `progress_percent` (0–100), `status_snapshot`, `comment`, and `created_at`. It currently records delegated and project-development progress. There is no update/overwrite endpoint. Results use creation time plus the time-sortable GLID as a deterministic newest-first order, and each entry ID is the notification idempotency source so consecutive updates remain distinct. Regular Project Development entries are limited to 0–99%; only the explicit completion action creates 100% in the same transaction as Done status, the completion note, and completion time. No historical-row migration or rewrite is required.

> No separate table is needed for closure hand-off: `problem.source_requirement_id` and `knowledge_article.source_requirement_id` are queryable both ways.

---

## 5. Process Domain (4 tables)

### 5.1 process_definition — process definition [cfg]

code, name, entity_type, trigger_condition JSONB, version, active, description. The Aily + MCP target lets `service_item.process_definition_id` select a published process explicitly; unbound items fall back to entity type plus trigger condition.

### 5.2 process_step — process step [cfg]

definition_id FK, seq, step_code (stable code within a version), name, node_type (processing / approval), default_role (R; the Bug Development Fix node is intentionally empty and executes through repair-child assignees), cc_roles (I notification roles/groups), autonomy_level (L1-L4), sla_hours, description. Once instances exist, step code, node order/type, handler, autonomy level, and SLA cannot be changed in place; use a new version. `cc_roles` is the only non-blocking rule that may be maintained in place and applies only when a later node first activates. Existing tasks' `raci_snapshot.informed` values and sent notifications are never rewritten. Approval nodes support approve (optional comment) or reject (required reason); processing nodes advance through the complete-step action.

### 5.3 process_instance — process instance

definition_id FK, entity_type, entity_id (triggering record), status (In Progress / Completed / Terminated, plus requirement-specific `returned` while waiting for requester supplementation), current_step_seq [C], started_at, completed_at. Returning a requirement to a reached process node keeps the instance `running` and creates a new target-node task. Only Requester supplement uses `returned` without a synthetic task. Resubmission restores `running` on the same instance rather than creating another requirement or process instance.

### 5.4 process_task — process task

instance_id FK, step_id FK, definition_version, step_code_snapshot, raci_snapshot JSONB (R/A/C/I snapshot at task creation), assignee FK (resolved from default role, reassignable), status (Pending / In Progress / Done / Rejected / Skipped), started_at, due_at [C] (from the step SLA), `viewed_at`, `viewed_by` FK (the current handler's first actual-view fact), `upstream_correction_enabled` (true for new tasks; false by default for pre-upgrade pending tasks), completed_at, completed_by FK, comment. Reassignment is permitted only to an active, in-position organization member with an active ITOM account; it changes only `assignee`, keeps the node/state/RACI snapshot/history, and writes from/to/reason audit data plus a new-handler notification. `started_at` only records generation/dispatch and never substitutes for an actual view; snapshots plus the view fact keep workflow versions, performance extraction, and correction-window history auditable. Requirement rejection retains the original Rejected task, real actor, and target-bearing comment. A return to a reached prior node appends a new pending task for that step instead of soft-deleting history. Candidate targets are derived from non-deleted historical task `step_id` values in the same instance, so no target-snapshot table is added. Only the newest effective legacy requirement instance incorrectly terminated with `status=rejected` is repaired idempotently. Closed, cancelled, or on-hold requirements are skipped; older process instances are never resurrected, and historical tasks, scores, attachments, and audit are never overwritten.

---

## 6. Team Domain (10 tables)

### 6.1 position — position definition

position_code, name, position_family, service_domains JSONB, primary_roles JSONB, level_framework, location_scope, skills, duties TEXT, headcount INT (formal target), contractor_allowed, status, sort. Formal active count and gap are computed; gap = headcount − formal active count, excluding contractors/interns.

### 6.2 hiring_need — hiring need

position_id FK, level (senior/mid/junior), count, qualification, status (To Recruit / Interviewing / Onboarded / Cancelled), progress_note, closed_at. One position can have multiple needs by level or batch.

### 6.3 development_activity — training activity

activity_type (internal cross-training / external technical exchange / new-technology research), topic, activity_date, host_id FK (presenter/organizer), participant_ids JSONB (frozen array of org_member ids used for point recipients), participant_department_selections JSONB (`[{id,name,member_ids}]`, the selected full-department display and attendee snapshot), output_link, remarks, created_by FK→auth_user. The list prefers department snapshots plus individual participants outside those snapshots; points always use `participant_ids`, so later transfers, renames, or hires never reinterpret an activity. Existing activities are not backfilled with department snapshots and retain their original person-list presentation. Registration triggers host/participant training-point events; `created_by` is recorded from the current account and existing rows are idempotently backfilled from the earliest creation audit. Activity deletion and point recalculation use soft deletion, preserving sources, audit, and historical ledger rows.

### 6.4 team_charter — team culture

section (vision/goals/code_of_conduct, UNIQUE), content (rich text), updated_by [C].

### 6.5 idea — suggestion

idea_code [C], title, description, submitter [C], status (Submitted / Adopted / Implemented / Declined), like_count [C], adopted_by, adopted_at [C], linked_requirement_id FK (written when an adoption is converted to a requirement).

### 6.6 idea_like — suggestion like

idea_id + person, UNIQUE composite.

### 6.7 point_rule — point rule [cfg]

rule_code, name, event_type (UNIQUE, see the event list in doc 05), points INT (may be negative), contribution_bucket (`role_result` / `team_contribution`), contribution_dimension, target_scope JSONB, active, description. A source event belongs to one bucket only. Activity Points, personal points, and the team-overview leaderboard aggregate only `team_contribution`; role-result rows are not displayed a second time as activity points. During the current assessment period, automatic activity events use the current effective rule value and an inactive rule displays zero.

### 6.8 point_entry — points ledger (append-only)

person FK, event_type, points, rule_id FK, contribution_bucket, contribution_dimension, period, source_entity_type, source_entity_id, earned_at, remark, created_by, idempotency_key. Indexes: (person, period), (person, earned_at), event_type. `points` retains the award-time value and the ledger is append-only. Current-period activity reads may resolve the display value from the current effective rule, while historical periods and published/locked performance retain the original value without rewriting published results.

### 6.9 performance_period — performance period [computed]

period_code (for example `2026-Q3`), version, status (draft/auto_scored/external_input/manager_review/cio_review/published/locked), rule_snapshot JSONB, role_snapshot JSONB, published_at, locked_at, created_by, updated_by.

### 6.10 performance_role_profile / performance_role_dimension — role scoring profile [cfg]

Profile: role_code, name, line_type (business/professional/platform), review_mode (manager_review/cio_direct), description, active. Dimension: profile_id FK, dimension_code, name, weight, source_config JSONB, evidence_required, sort, active. Enabled dimensions must total 100%.

### 6.11 performance_role_assignment — period role snapshot [computed]

period_id FK, person FK, `role_code` (the implementation snapshot identifier), line_type, business_domain_id/professional_group_id, role_weight, evaluator_ids JSONB, `evaluator_weights` JSONB (sum 100), review_scope JSONB, review_mode, snapshot_detail JSONB. Published periods are not edited in place.

### 6.12 performance_external_input — external raw fact [input]

period_id FK, metric_code, target_type, target_id, evaluator_name, evaluator_department, raw_score, raw_scale, normalized_score [computed], comment, evidence_refs JSONB, inputter_id, status (draft/submitted/verified/locked), version, locked_at. External business satisfaction is separate from internal ITSM satisfaction; locked facts are corrected through a new version.

### 6.13 performance_score_component — score component [computed]

period_id FK, assignment_id FK, dimension_code, system_score [computed], business_manager_score, professional_manager_score, cio_score, `manager_scores` JSONB, `manager_reasons` JSONB, `manager_evidence_refs` JSONB, effective_score [computed], reason, evidence_refs JSONB, updated_at. Reviewer scores are stored independently and aggregated by the snapshot weights; reference, stage proposal, and effective values remain separate.

### 6.13a performance_contribution_config — team contribution rules [cfg]

Singleton configuration containing `weights` JSONB, `targets` JSONB, internal/external satisfaction weights, and `updated_by`. CIO/system administrators update it through `/api/admin/performance/contribution-rules`; recompute snapshots the values into `performance_period.rule_snapshot` so published periods remain reproducible.

### 6.14 performance_review_action — review action [audit]

period_id FK, assignment_id FK, actor_id, stage, action, before_value JSONB, after_value JSONB, reason, evidence_refs JSONB, created_at. Append-only for review, submission, return, publication, unlock, and version creation.

### 6.15 performance_score — published performance result [computed]

period_id FK, person FK, version, business_role_score, professional_role_score, team_contribution_score, regular_score, bonus, penalty, published_score, detail JSONB, published_at. Only published snapshots are exposed by `/api/my/performance`.

---

## 7. Core Relationship Diagram

```mermaid
erDiagram
    service_catalog ||--o{ service_item : "contains"
    service_item ||--o{ service_item_form_version : "form versions"
    service_item ||--o{ service_dispatch_rule : "logical scope_id"
    service_item ||--o{ ticket : "ticket basis / carries SLA"
    ticket ||--o| ticket_satisfaction : "effective rating"
    ticket }o--|| ci : "links"
    ci ||--o{ ci_relationship : "upstream/downstream"
    ticket }o--o{ problem : "problem_ticket"
    vendor ||--o{ contract : ""
    vendor ||--o{ ci : ""
    portfolio ||--o{ project : "groups"
    project ||--o{ wbs_task : ""
    project ||--o{ milestone : ""
    project ||--o{ risk : ""
    project ||--o{ cost_entry : ""
    requirement ||--o{ requirement_task : "task breakdown"
    requirement }o--|| project : "implementation attach"
    requirement ||--o{ problem : "legacy hand-off"
    requirement ||--o{ knowledge_article : "lessons captured"
    idea }o--|| requirement : "adoption→requirement"
    process_definition ||--o{ process_step : ""
    process_definition ||--o{ process_instance : ""
    process_instance ||--o{ process_task : ""
    org_member ||--o{ point_entry : "points ledger"
    org_member }o--|| position : "position"
    ticket ||--o{ point_entry : "event scoring (source)"
    auth_user ||--o{ external_identity : "external identity"
    auth_user ||--o{ mcp_operation_intent : "confirmation"
    auth_user ||--o{ mcp_tool_call : "tool audit"
```

## 8. Reconciliation Against the Design Principles

| Principle | How it is realized |
| --- | --- |
| No pre-computed tables | Not one of the 43 tables is a statistics/snapshot table; project's three computed columns and performance_score are "system-maintained computation results," not manual data |
| Minimal entry | Each table's "required on creation" group has ≤ 5 fields |
| Event-driven | notification_outbox + point_entry are written by the same domain-event outlet |
| Duplicate-proof | idea_like / knowledge_vote unique constraints |
| Aily/Feishu boundary | external_identity isolates app-scoped identities; notification_outbox delivers reliably; mcp_operation_intent enforces confirmation/idempotency |

## 9. UI Branding Configuration (M38)

`ui_branding_version` stores complete JSON configuration snapshots with `version`, `status` (`draft`/`published`), publisher and publish time. Publishing and rollback create a new immutable published version.

`ui_branding_asset` stores controlled brand images with kind, path, MIME type, byte size, dimensions and uploader. Only PNG/JPEG/WebP/ICO up to 5 MB and 4096×4096 are accepted; SVG and arbitrary HTML/CSS/JS or remote fonts are intentionally unsupported.
### Org governance settings (M42)

`org_settings` is a singleton containing `digital_team_department_ids`, `digital_team_member_ids`, descendant inclusion, and the Feishu scheduled-sync enablement, interval, and last-attempt timestamp. The effective digital team is the union of active people in the expanded department scope and active individually selected people; selecting an individual never includes their colleagues. The settings remain separate from credentials so the internal digital-team definition survives an organization-source change.

### System integration settings (M44)

`system_integration_config` stores global email and LDAP JSON settings. SMTP and LDAP bind passwords are Fernet-encrypted; read APIs expose only `has_secret`.

### 1.14 feishu_config and Helpdesk cleanup (Aily + MCP baseline)

`feishu_config` retains only Feishu OAuth, workplace login, organization sync, and generic app credentials. All `helpdesk_*` fields are removed. The Aily bot may be a different app, so its credentials and tenant/agent allowlists live in `aily_integration_config`; its `open_id` is never assumed equal to the login app's value.

Remove `feishu_helpdesk_handoff`, `feishu_helpdesk_intake`, `feishu_helpdesk_sync_event`, and `feishu_helpdesk_outbox`. The user confirmed there is no valuable production history to migrate or archive. The migration safely drops those dedicated tables/fields while the frozen Git tag remains recoverable.

### 1.15 Web-agent target models (WA0; design approved)

The web agent adds structures instead of reusing or rewriting `aily_integration_config`. WA0 now adds the following tables. Each inherits GLID, audit timestamps, and soft-delete fields; providers and profiles are disabled by default:

- `ai_provider_config`: unique `code`, provider type, model connection, encrypted API key, timeout/output limits, capability probe, primary/fallback, `enabled=false`, and `config_revision` starting at 1. Type, URL, model, a nonblank replacement secret, timeout, output limit, temperature, or fallback change increments the revision under the governance lock and invalidates the old probe. Probe state is queryable, but the revision is not derived from secret hashing and the secret never appears in ordinary reads.
- `ai_agent_profile` / `ai_agent_profile_version`: unique profile `code`, audience, currently active default provider, maximum risk level, enablement, and `retention_days`; profile retention has a database default of 30 days and a database `CHECK` constraint of 0–90 days. Versions are unique by `(profile_id, version)` and retain bilingual system instructions, enabled capabilities, knowledge scope, publisher, publication time, and `config_snapshot`. Every new draft, publication, and rollback copy stores all publication-controlled `name/default_provider_id/retention_days/enabled` fields with `schema_version=1`; draft PATCH changes the version snapshot only, while successful publish/rollback atomically applies the snapshot plus version risk to the active profile row. Runtime use additionally requires a complete snapshot, bilingual prompts, registered capability/risk limits, a recently healthy compatible provider, and agreement between the active row and newest version. Existing `{}`, missing-marker, or incomplete historical versions are unprovable and fail closed; runtime and rollback never fill them from the current active profile.
- `ai_conversation` / `ai_message`: the current web `auth_user`, profile/version, language, strictly allowlisted page context, lifecycle/archive status and time, `expires_at`, and redacted structured messages with role, token use, and latency. Every read and archive is constrained by `auth_user_id`; archive changes conversation visibility only. Ordinary-message retention is read only from the complete schema-marked snapshot of the `profile_version_id` captured at conversation creation, never from the active profile or `expires_at`: a captured zero remains nonpersistent after a positive republish, while a captured 1–90-day decision and stable creation-time `expires_at` remain immutable. New bodies still stop when the current profile is disabled, deleted, unpublished, audience-incompatible, or fails runtime validation. Task 7 adds no field or migration: a user message is first stored as `accepted`; only a fresh short transaction created in a bounded DB worker may lock in the fixed `AuthUser → AiConversation → current profile/version → AiMessage` order and make the recursively redacted structured body `completed`. `AuthUser` is first loaded with `FOR UPDATE + populate_existing` and checked for active/deleted after locking; the conversation must remain owned and active, the profile/version must remain the exact current publication, and the assistant placeholder must still be `streaming`. Finalization cooperatively checks disconnect/absolute-deadline cancellation after all locks and again before writing/committing `completed`; observed cancellation rolls back and leaves no completed state, without claiming elimination of every real-socket/thread-scheduling micro-race. One monotonic absolute deadline covers failed-placeholder cleanup and every pre-commit stage; stage timeouts are neither reset nor summed. Authority commit must begin before that deadline after the last cancellation check. Once commit begins, the caller waits for commit and Session cleanup to preserve database `completed` versus client-terminal consistency, so return may slightly exceed the deadline rather than misreport a durable completion as timeout. Model prose persists under `authority=advisory, operation_status=not_executed`; an L3 preparation persists under `authority=server_preview, operation_status=prepared_not_executed`; neither represents a committed business result. Provider errors, truncated protocols, disconnects, and partial deltas never become completed answers. Failure/cancellation may retain a bodyless nonsensitive state fact; retention zero stores only bodyless idempotency metadata and digests. `request_digest` is a server-key HMAC over normalized raw `content + page_context`; only the digest is stored, never the key or any new raw-body copy, while durable bodies remain redacted. The same `client_message_id` therefore replays equal raw input and conflicts even when different raw inputs redact to the same body. An L3 `prepared` action may survive a disconnect until expiry but is never auto-executed by streaming. This round still adds no table, field, index, or migration.
Task 7A changes none of those tables or status values; it repairs the finalization authority for `completed`. Thread-safe durable success is set only after `db.commit()` returns successfully. A later Session-close failure stores only a redacted exception type, cannot negate the persisted state, and never triggers a database re-query to guess transaction outcome. When disconnect is observed after commit has started, cancellation wins and no SSE terminal follows. A failing commit sets no durable success; rollback and the existing failed-placeholder cleanup safely converge the non-completed row to `failed`.
- `ai_action`: conversation, initiating account, capability, risk, a safe payload normalized by the registered Pydantic model and unchanged by sensitive-collision checking, stable SHA-256 digest, confirmation-token SHA-256, idempotency key, status, result, and related entity. SQLAlchemy metadata and PostgreSQL DDL use the same named uniqueness target, `uq_ai_action_user_capability_idempotency(auth_user_id, capability_code, idempotency_key)`. If recursive redaction would change normalized input, the request is rejected rather than storing or executing a redacted substitute. Task 6 adds no column or migration. First preparation stores `prepared` plus the server-handler preview only after the separate rollback-only preview Session has ended, and returns the raw token once. Same-key/same-digest reads existing `prepared/succeeded/failed/cancelled/expired` state; a different digest conflicts, and named-constraint race recovery reloads only its winner. Confirmation locks the row, proves that the owner conversation's captured profile remains the complete current publication with a healthy compatible provider, then rechecks capability and digest. One success transaction writes domain state, `succeeded`, `consumed_at`, redacted result/entity, and generic `audit_log`. Cancellation writes `cancelled`; expiry writes `expired`. Handler or success-audit failure rolls back only the nested savepoint and writes a bounded `failed` fact in the same still-row-locked outer transaction; failure-state commit failure is never reported as durable. `token_hash` may remain for irreversible security evidence but is never returned; raw tokens never enter messages, logs, or audit.

Task 8C changes no column or migration, but extends the state contract. `prepared` is the only confirmable/cancellable state. `executing` is an internal non-retryable claim committed after credential/runtime checks and before handler entry; it never represents business success. `succeeded` still appears only after the domain mutation, result, and audit commit together. An uncertain handler or final persistence outcome keeps `executing`, never restores `prepared`; a known failed execution writes `failed` only when that terminal commit succeeds. `expires_at` remains a naive UTC `TIMESTAMP` in storage, while every public `confirmation_expires_at`/`expires_at` wire value is explicit-`Z` RFC 3339 UTC.

Round 1 makes the post-claim outer write transaction explicit for SQLite before the handler nested savepoint: an uncertain or failed success-terminal commit rolls back the domain mutation, `succeeded`, and success audit while the durably claimed row remains `executing`; only a claim failure before handler entry may retain `prepared` and its original token for an honest retry.
- `ai_provider_call`: provider, conversation/message/profile version, model, purpose, input/output tokens, latency, result code, status, and redacted error metadata.

Capability handlers are code-registered. Database configuration may disable a registered capability but cannot invent an executable handler. Startup migration `ensure_assistant_schema()` runs only on PostgreSQL and performs only `CREATE TABLE IF NOT EXISTS`, missing-column additions (including `ai_provider_config.config_revision INTEGER NOT NULL DEFAULT 1` and `ai_agent_profile_version.config_snapshot JSONB NOT NULL DEFAULT '{}'`), `CREATE INDEX IF NOT EXISTS`, and an idempotently added retention `CHECK` constraint; SQLite tests continue to create tables through `Base.metadata.create_all()`. It does not backfill, recalculate, rewrite, or fabricate an existing `config_snapshot`, nor does it rewrite business records, process instances, Aily identities, or MCP audit. Legacy `{}` therefore remains intact and fails closed under the one-time compatibility limitation above. Conversation retention defaults to 30 days and is configurable from 0–90 days; archive or retention cleanup never deletes `ai_action` or other security/business audit. See [`docs/en/superpowers/specs/2026-08-01-itom-web-agent-design.md`](superpowers/specs/2026-08-01-itom-web-agent-design.md).

Task 8C Round 2 changes no column or migration; it clarifies that the public expiry browser contract is explicit-`Z` and calendar-valid, so normalized invalid date/time values cannot form a confirmable `prepared` state.
