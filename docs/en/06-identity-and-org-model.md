# User Identity & Organization Model Design (M3.5–M3.9 / M34–M37)

> English translation of [../06-用户身份与组织模型设计.md](../06-用户身份与组织模型设计.md). For the authoritative version, the Chinese source prevails.

> Finalized on the 2026-07-10/11 product decisions. The design is benchmarked against ServiceNow's four-axis user / group / role / organization model.
> Three iron rules: **a user may always hold multiple roles and is never bound to one**; **membership is a field, not a role**; **roles are granted on groups first**.

## 1. The Four-Axis Model & Page Positioning

| Concept | Table | Question it answers | Page | Permission semantics |
| --- | --- | --- | --- | --- |
| Account | `auth_user` | How you log in, and which roles you hold directly | User Management | Direct roles |
| Person | `org_member` | Who you are (Chinese/English name / department / position / contact / skills) | Personnel Master Data | **None** |
| Department | `department` | Where you sit in the company org structure (one person, one department; tree-shaped; types it/business/audit) | Department Management | **None** (used only as the basis for provisioning-rule matching) |
| User group | `user_group` | Who you work with, and who tickets get assigned to | User Groups | **Group-granted roles**: a person joining the group inherits them automatically |
| Role | `role` | What you can do in the system | Role Management | 10 built-in + custom (inheriting a built-in) |
| Business domain | `business_domain` | Which business line you serve and who owns it | Business Domain | **None** (owner is a field, not a role) |

**Effective roles = direct roles ∪ the roles granted by the groups you belong to ∪ the built-in roles inherited by your custom roles.** The `roles` in the login response are the effective roles (the front-end menu renders from them), and `direct_roles` are the direct roles.

## 2. The 10th Built-in Role: auditor (Auditor)

- Permission boundary: **read-only across all modules + audit-log viewing**; cannot modify any record (enforced by a global read-only middleware, exceptions: login and notification handling, including the notification popover's Mark all as read and Clear read actions).
- Multi-role unrestricted: a user with auditor + it_ops can write normally (the read-only restriction applies only to users who hold *only* auditor).
- **Not auto-granted**: audit-department users are also provisioned as requester by default; auditor is granted manually by the admin (directly, or by adding the user to a group that carries the auditor role).

## 3. Account Provisioning (JIT Provisioning)

```text
Auth-source adapter (AuthProvider) → on success returns a user profile (ProvisionProfile)
  → provision_user(): find-or-create the account + personnel profile
      - First creation: assign default roles per the provisioning rules (provision_rule)
      - Subsequent logins: sync the profile only (name / department / contact); roles are never reset
```

- **Provisioning rules** (admin-configurable, first-login-only): match by department type (it/business/audit) or specific department → a list of default roles; a specific-department rule takes priority, lower `sort` first, and matching stops on the first hit. Seed default: all three department types → `requester`.
- **Auth sources**: `auth_user.auth_source` (local/ad/feishu/sms/wechat) + `external_id`. Local and Feishu are implemented: Feishu supports QR OAuth, workplace app login, first-time provisioning approval, and post-login binding/rebinding. AD/SMS/WeChat remain reserved adapters.
- When an admin creates an account manually without selecting a role, the default is likewise taken from the rules (based on the associated person's department).

## 4. Source of Organization Data: Feishu is the Source of Truth (finalized M3.9)

**Company personnel master data is stored in Feishu, and Feishu is authoritative** (2026-07-11 product decision). This is implemented in three layers:

1. **The sync engine and Feishu provider are implemented** (`services/org_sync.py` / `services/feishu.py`): `apply_org_snapshot()` performs an idempotent upsert keyed by `(external_source, external_id)`; **the external side wins**; a two-pass process establishes department and supervisor relationships; externally missing people are marked departed and missing departments are deactivated, while local-only records are unaffected. `POST /api/admin/org-sync` returns 501 when Feishu is unconfigured.
2. **Synced records are locked locally**: a person's HR base fields (name / employee number / gender / date of birth / employment type / supervisor / office location / department / contact / hire date / status) and department structure fields are rejected for edits by the backend (SYNCED_READONLY); **locally, only the IT extensions are maintained** — a person's position/skills/remarks, and a department's it/business/audit classification. Feishu manages HR; ITOM manages the IT extensions.
3. **Manual entry during development is transitional**: the same set of fields, taken over by sync once connected.

**M35 asynchronous sync protocol**: the admin trigger starts a background thread with an independent database session and returns immediately. `feishu_config.last_sync_stats.status` records `running/done/failed`; a repeated trigger while running returns `SYNC_RUNNING`. The UI polls for status, and completion or failure sends an in-app notification to the initiating account/person.

## 4-A. Account Lifecycle and Personal Identity (M36–M37)

- `auth_user` and `org_member` have separate lifecycles. Deleting an account only soft-deletes, disables, and unlinks it; personnel master data and historical references remain. The built-in admin and current account cannot be deleted.
- User updates distinguish an omitted `person_id` from an explicit `person_id: null`: omission preserves the current link, while explicit null unlinks the account without deleting personnel master data, department placement, user-group membership, or historical business records.
- Browser QR login and Feishu workplace login share identity handling: an active bound account signs in directly, while a new identity enters the `login_request` approval flow.
- A signed-in account may bind or rebind one Feishu open_id; the identity cannot be occupied by another active account. Unbinding requires a local password and does not unlink the person record.
- The Feishu Helpdesk handoff reuses `auth_user.external_id=open_id`: the stable link written to the original Helpdesk conversation contains only an intake ID and action, never an open_id or one-time token. After ITOM login, the backend compares the signed-in account, stored intake, and freshly read Helpdesk guest open IDs; only a three-way match issues a ten-minute token, and a repeated click expires any older unconsumed token. The service category is used only for ITSM catalog/item context, never inferred as a requirement business domain, and the token is consumed after creation.
- Reliable Helpdesk synchronization never puts identity in a browser URL: the server verifies the event token and idempotently queues events by `event_id`, while the pending intake stores guest/agent open IDs and a sanitized snapshot. The stable entry is delivered in the original Helpdesk conversation as rich post or fallback text; only repeated original-conversation failures use an independent application-bot card. Every path still requires the signed-in account's `external_id` to match the freshly read guest. Outbound updates contain only user-visible milestones, never internal notes or approval details.
- Since M44, approval generates a 12-character initial password and stores recoverable encrypted ciphertext without automatic delivery. Reveal and manual email actions are audited, and changing/resetting the password clears the ciphertext.
- `preferences` stores language, avatar, bio, notification categories, theme, and density. The personal audit view is isolated to the current account as actor.

**Field mapping (Feishu directory → org_member)**: name→name, en_name→name_en, employee_no→employee_no, gender→gender, employee_type→employment_type, leader_user_id→supervisor_id (resolved via external_id in the second pass), city→work_location, mobile/email mapped directly, department_ids[primary department]→department_id, open_id→external_id; department open_department_id→department.external_id, parent→parent_id. The company name is a local configuration (master_data sys_config/company_name).

## 5. Migration Record

M3.5 kicks off the migration (`services/migrate.py`, idempotent):

1. Add new columns to existing tables (create_all does not add columns): org_member 5 columns, auth_user 2 columns, user_group.roles.
2. `org_member.dept` (text) → find-or-create a `department` by name (name containing "IT" → type it) and backfill `department_id`, then drop the column.
3. `org_member.team` (text) → find-or-create a `user_group` and establish the membership relationship, then drop the column.

## 6 (M3.6). Matrix-Style IT Organization Mapping

How IT's internal matrix management (2026-07-11 product input) is expressed in the model:

| Organizational concept | System carrier |
| --- | --- |
| Horizontal · service line (business domain) | `business_domain`: owner/backup owner and service-team members use the `org_settings` digital-team union (department members plus individually selected people); `business_domain_department` stores the served organization scope |
| Operational person-selector scope | Project/requirement/ticket/problem/service-item/CI/contract/user-group/account-linking dropdowns load `GET /api/members?scope=it`; the scope can combine departments and specific people, so selecting one person from a mixed Test organization does not include their colleagues; write APIs re-check the configured union |
| Vertical · technical line (resource pool: a TM centrally manages personnel in a technical direction) | `user_group`: owner = TM (field) + roles group-granted roles (e.g. the development resource pool grants it_dev) + members |
| Professional identity | Roles: it_pdm/it_pm/it_dev/it_ops/is_mgr/it_bp + custom additions (data governance, AI, etc.) |
| Management layer | cio (IT Head) / it_bm / it_tm, three built-in roles (manager was removed on 2026-07-11) |
| One person, many roles | Guaranteed by the iron rule; permissions are the union of the held roles' matrices |

Performance review does not treat `auth_user` roles as the evaluator assignment. Each period creates a `performance_role_assignment` snapshot with the person's business/professional role, business-domain or professional-pool scope, evaluator, and `review_mode`. A business-line lead proposes only business-role scores in scope; a professional-line lead proposes only professional-role scores in scope. Platform roles default to `review_mode=cio_direct` and are scored directly by the CIO. No leader may self-score; the CIO finalizes leaders' own scores.

The built-in roles are finalized at **16**: admin, cio, it_bm, it_tm, it_pdm, it_pdm_leader, it_pm, it_pmo, it_dev, it_dev_leader, it_ops, it_op_leader, is_mgr, it_bp, auditor, requester (manager removed, no reason to exist). **Built-in role names/descriptions are editable** (code, inheritance relationship, and deletion are locked).

## 7 (M3.6). Function Permission Matrix

- **Granularity**: all menu-aligned modules × actions (view — includes visibility and viewing / create / edit / delete). Stored as `role_permission` (role_code × module → actions).
- **Determination**: a user's permissions = the **union** of the matrices of direct roles ∪ group-granted roles; admin has implicit full authority, is not in the matrix, and is not configurable (to prevent lockout). The login response carries `permissions`, from which the front end renders menus/buttons, and the backend enforces `require_perm(module, action)`.
- **Boundaries** (three permission layers each own a segment, without redundancy):
  1. Function matrix: page visibility and create/edit/delete toggles (this section).
  2. Data scope: e.g. requester sees only their own tickets, and a knowledge draft is visible only to its author — built into the business code, not in the matrix.
  3. Process permissions: state-machine transition allowed_roles, process-step default_role — managed on the state-machine-config / process-definition pages.
- **Performance modules**: use separate modules for `performance_result` (result view), `performance_review` (staged review), `performance_external` (external raw input), and `performance_admin` (rules/period/publication). The function matrix controls page/actions; `performance_role_assignment.review_scope` then restricts business-domain, professional-pool, and editable line scope.
- **Performance visibility**: business/professional leads see reference scores and proposal fields only in their scope; the CIO sees all internal details and performs final review; evaluated employees have only `performance_result.view`, and the endpoint returns published final results only.
- **Performance field authority**: leads cannot edit raw team-contribution points, external raw facts, or the other line's components. Platform roles and leaders' own scores are entered directly by the CIO. Locked external facts are corrected by a new version only.
- **Point-rule authority**: team-contribution activity rules belong to the `ideas` Activity Points page; reads use `ideas.view`, while writes are hard-guarded to admin (implicit full authority) and CIO. Role-result rules belong to Team Management → Performance → Scoring Rules and use role profiles, dimensions, source mappings, and process/RACI step mappings. The two ledgers and period snapshots remain separate; changes never recalculate historical `point_entry` rows or published periods, and each change is audited against its own entity.
- **Custom roles**: on creation, **copy** the matrix of the selected template role (base_role) as the initial value, then edit independently; base_role also retains the "process-reference inheritance matching" semantics (when a transition rule specifies it_ops, a custom role inheriting it_ops also matches).
- The default matrix is coded in `services/permissions.py` (DEFAULT_MATRIX), seeded only on first startup, after which the in-database configuration is authoritative.

## 8. Mapping of Old Concepts (to avoid further confusion)

- ~~Personnel Master Data.team~~ → user-group membership (the personnel page shows the belonging groups read-only)
- ~~Personnel Master Data.department text~~ → a reference to the department table
- ~~Roles can only be attached to accounts~~ → roles are granted on groups first, and a person joining the group inherits them automatically (ServiceNow best practice)
- Business-line dictionary (master_data.business_line) → later domains (Requirement/M5) switch to referencing the `business_domain` table

## 9 (M3.7). ITIL-Aligned Preset Processes v2 (reconfigured 2026-07-11)

| Process | ITIL practice | Steps → default role |
| --- | --- | --- |
| Incident handling | Incident Management | Intake & prioritization (it_op_leader, approval) → Diagnosis & handling (it_ops) → Resolution & user confirmation (it_ops, approval) → Closure & retrospective (it_op_leader) |
| Service-request delivery | Service Request Mgmt | Intake confirmation (it_ops) → Implementation & delivery (it_ops) → User confirmation & closure (requester, approval) |

After a Feishu Helpdesk handoff, a service request enters these three steps directly; ITOM does not add another human-routing step. Automatic assignment/reassignment represents the system-assigned point, the final requester step represents user confirmation and closure, the state machine then reaches resolved and closed, and the Feishu rating is written back to `Ticket.satisfaction`.
| Change management | Change Enablement | Change request (it_ops) → Change approval (it_op_leader; CC it_bm) → Implementation & verification (it_ops) → Change retrospective/PIR (is_mgr; CC cio) |
| Problem analysis | Problem Management | Problem confirmation (professional-line owner, dynamically assigned, approval) → Root-cause analysis (handler selected by owner) → Resolution & verification (same handler) → Resolution confirmation & closure (professional-line owner, approval) |
| Requirement delivery (pre-configured, attached in M5) | — | Requirement review (it_bm, approval) → Solution assessment & routing (it_pdm_leader, approval) → Delivery (it_dev_leader / project manager) → Acceptance & closure (it_bm, approval) |
| Project key milestones | Project Management | Project kickoff (it_pm, approval) → Execution monitoring (it_pm) → Closure retrospective (it_pmo, approval) |

Current published runtime: the change approval/rejection transition has `allowed_roles = [cio, it_tm, it_op_leader]`; the approval task defaults to `it_op_leader` and CCs `it_bm`; the PIR task is handled by `is_mgr` and CCs `cio`. Approval recipients are resolved dynamically from `allowed_roles` (including groups and inheritance). All of this remains adjustable on the state-machine-config / process-definition pages; the published runtime version takes precedence over code seeds.

## 10 (M3.8). Process-Node Standard: Handler / CC Party (mandatory for all subsequent process features)

Aligned with RACI: each process node has two kinds of participants, which the configuration page must support simultaneously and present intuitively via a **process diagram** —

| Participant | Field | Semantics | Behavior |
| --- | --- | --- | --- |
| **Handler** (R/A) | `process_step.default_role` (single value: role code or group:<group-code>) | Approve or execute | Produces a to-do task and blocks process advancement; auto-assignment resolution (assignee first → an active member within the role/group) |
| **CC party** (I) | `process_step.cc_roles` (list: role codes / group:<group-code>) | Notified only | Sends an in-app notification when the node activates (event `process.step_cc`, later synced to Feishu by the channel adapter); **produces no task, does not block the process**; automatically excludes anyone who is also the handler |

- Configuration validation: a CC key must be a valid role or user group, otherwise INVALID_STEPS.
- `process_step.node_type` makes the node semantics explicit: `processing` is an execution node completed from the flow diagram with a processing note; `approval` is an approval node that the handler can approve/reject from the detail-page actions, or approve through the diagram's “Complete step” action. Approval comments are optional; rejection reasons are mandatory and retained in the task audit trail, and the process instance becomes `rejected` (the problem-confirmation node keeps its specialized “return to reporter for more information” rule).
- The process-definition page shows a **process diagram** for each process (node cards: step name + handler in blue + CC in gray + autonomy level/SLA), with live preview in the editor.
- The record-detail process bar also shows the CC parties.
- Current runtime change-management process: Change request (it_ops) → Change approval (it_op_leader, CC it_bm) → Implementation & verification (it_ops) → Change retrospective/PIR (is_mgr, CC cio). Do not treat the old five-step “risk assessment → change approval” seed or its former CC relationships as the current process definition.
- Task creation also stores the process version, `step_code`, and RACI snapshot. Changing a handler or CC relationship requires a new process version, so historical tasks and performance extraction remain stable.
The digital-team population is an explicit shared department-tree scope in `org_settings`, optionally including descendants. It is authoritative for team metrics and business-domain owner, backup-owner, and service-team selectors; the legacy `dept_type`/role heuristic is used only until an administrator configures the scope.
