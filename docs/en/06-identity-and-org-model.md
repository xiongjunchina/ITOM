# User Identity & Organization Model Design (M3.5–M3.9 / M34–M37 / Aily-MCP)

> English translation of [../06-用户身份与组织模型设计.md](../06-用户身份与组织模型设计.md). For the authoritative version, the Chinese source prevails.

> Finalized on the 2026-07-10/11 product decisions. The design is benchmarked against ServiceNow's four-axis user / group / role / organization model.
> Three iron rules: **a user may always hold multiple roles and is never bound to one**; **membership is a field, not a role**; **roles are granted on groups first**.
> The 2026-07-29 Aily + MCP identity model is implemented in P0. P1/P2 business tools reuse existing feature permissions, enforce own-record scope, and pass automated protocol, permission, cross-user isolation, confirmation/reopen, and rating tests. The frozen Helpdesk identity path has been removed from the new branch runtime.

## 1. The Four-Axis Model & Page Positioning

| Concept | Table | Question it answers | Page | Permission semantics |
| --- | --- | --- | --- | --- |
| Account | `auth_user` | How you log in, and which roles you hold directly | User Management | Direct roles |
| Person | `org_member` | Who you are (Chinese/English name / department / position / contact / skills) | Personnel Master Data | **None** |
| Department | `department` | Where you sit in the company org structure (one person, one department; tree-shaped; types it/business/audit) | Department Management | **None** (used only as the basis for provisioning-rule matching) |
| User group | `user_group` | Who you work with, and who tickets get assigned to | User Groups | **Group-granted roles**: a person joining the group inherits them automatically |
| Role | `role` | What you can do in the system | Role Management | 17 built-in + custom (inheriting a built-in) |
| Business domain | `business_domain` | Which business line you serve and who owns it | Business Domain | **None** (owner is a field, not a role) |
| External identity | `external_identity` [implemented in P0] | Which ITOM account a Feishu tenant/app identity maps to | Aily/Feishu integration | **None** (identity mapping grants no role) |

**Effective roles = direct roles ∪ the roles granted by the groups you belong to ∪ the built-in roles inherited by your custom roles.** The `roles` in the login response are the effective roles (the front-end menu renders from them), and `direct_roles` are the direct roles.

## 2. Built-in Role: auditor (Auditor)

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
- **Automatic business-user provisioning**: during Feishu workplace login, when the person is already synced to ITOM, outside the digital/IT scope, has a valid email local part, and has no person/external-identity/username collision, ITOM idempotently creates or binds an account, uses the email prefix before `@` as the username, initializes the `requester` role, and activates login. The configured initial password is stored only in encrypted form and never logged or returned. IT-scope people continue through administrator approval and never receive business-user access through this branch. Until a synced department tree is classified, a path explicitly named Information Technology, Digitalization, Informatization, or IT is also treated as IT; failed safety checks fall back to the existing pending-approval flow.
- When an admin creates an account manually without selecting a role, the default is likewise taken from the rules (based on the associated person's department).

## 4. Source of Organization Data: Feishu is the Source of Truth (finalized M3.9)

**Company personnel master data is stored in Feishu, and Feishu is authoritative** (2026-07-11 product decision). This is implemented in three layers:

1. **The sync engine and Feishu provider are implemented** (`services/org_sync.py` / `services/feishu.py`): `apply_org_snapshot()` performs an idempotent upsert keyed by `(external_source, external_id)`; **the external side wins**; a two-pass process establishes department and supervisor relationships; externally missing people are marked departed and missing departments are deactivated, while local-only records are unaffected. `POST /api/admin/org-sync` returns 501 when Feishu is unconfigured.
2. **Synced records are locked locally**: a person's HR base fields (name / employee number / gender / date of birth / employment type / supervisor / office location / department / contact / hire date / status) and department structure fields are rejected for edits by the backend (SYNCED_READONLY); **locally, only the IT extensions are maintained** — a person's position/skills/remarks, and a department's it/business/audit classification. Feishu manages HR; ITOM manages the IT extensions.
3. **Manual entry during development is transitional**: the same set of fields, taken over by sync once connected.

**M35 asynchronous sync protocol**: the admin trigger starts a background thread with an independent database session and returns immediately. `feishu_config.last_sync_stats.status` records `running/done/failed`; a repeated trigger while running returns `SYNC_RUNNING`. The UI polls for status, and completion or failure sends an in-app notification to the initiating account/person.

## 4-A. Account Lifecycle and Personal Identity (M36–M37)

- `auth_user` and `org_member` have separate lifecycles. Deleting an account only soft-deletes, disables, and unlinks it; personnel master data and historical references remain. The built-in admin and current account cannot be deleted.
- Account provisioning is company-wide: user management and Feishu approval load people without `scope` and may link any non-deleted `org_member`. The digital-team scope applies only to IT operational owners, user groups, and performance subjects; it must not block a business user account. List responses provide readable person and department names instead of exposing the internal GLID as display text.
- User updates distinguish an omitted `person_id` from an explicit `person_id: null`: omission preserves the current link, while explicit null unlinks the account without deleting personnel master data, department placement, user-group membership, or historical business records.
- Browser QR login and Feishu workplace login share identity handling: an active bound account signs in directly, while a new identity enters the `login_request` approval flow.
- The Organization UI initially expands only the company and first-level department names for readability. Clicking a department name or its expand arrow recursively reveals child departments and then people. The backend retains the complete department/person tree for selectors, synchronization, data scope, and authorization; no existing organization data is deleted or truncated.
- A signed-in account may bind or rebind one Feishu open_id; the identity cannot be occupied by another active account. Unbinding requires a local password and does not unlink the person record.
- Aily no longer uses a Helpdesk guest identity or handoff token. MCP validates `x-aily-jwt`, then maps provider, tenant, app, subject type, and subject ID through `external_identity` to one active `auth_user`. Missing mapping, disabled accounts, or non-allowlisted tenants/agents are rejected.
- Existing `auth_user.external_id` remains for login/binding compatibility but cannot represent all identities from multiple apps. OAuth/org-sync and Aily-bot apps may produce different `open_id` values and therefore use separate verified identity rows.
- MCP secrets, bot secrets, and JWTs never appear in browser URLs, frontend state, prompts, tool results, or normal audit text. Proactive messages use only encrypted server-side credentials and verified recipient identities.
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
| IT operational person-selector scope | Project/requirement/ticket/problem/service-item/CI (technical owner and Application product manager)/contract/user-group selectors load `GET /api/members?scope=it`; account linking is excluded and must allow every non-deleted company person |
| Vertical · technical line (resource pool: a TM centrally manages personnel in a technical direction) | `user_group`: owner = TM (field) + roles group-granted roles (e.g. the development resource pool grants it_dev) + members |
| Professional identity | Roles: it_pdm/it_pm/it_dev/it_ops/is_mgr/it_bp + custom additions (data governance, AI, etc.) |
| Management layer | cio (IT Head) / it_bm / it_tm, three built-in roles (manager was removed on 2026-07-11) |
| One person, many roles | Guaranteed by the iron rule; permissions are the union of the held roles' matrices |

Performance review does not treat `auth_user` roles as the evaluator assignment. Each period creates a `performance_role_assignment` snapshot with the person's business/professional role, business-domain or professional-pool scope, evaluator, and `review_mode`. A business-line lead proposes only business-role scores in scope; a professional-line lead proposes only professional-role scores in scope. Platform roles default to `review_mode=cio_direct` and are scored directly by the CIO. No leader may self-score; the CIO finalizes leaders' own scores.

The built-in roles are finalized at **17**: admin, cio, it_bm, it_tm, it_pdm, it_pdm_leader, it_pm, it_pmo, it_dev, it_dev_leader, it_ops, it_op_leader, is_mgr, it_bp, auditor, bdo, requester (manager removed, no reason to exist). **Built-in role names/descriptions are editable** (code, inheritance relationship, and deletion are locked).

`bdo` = **Business Digital Owner**. Appointed by a business department, this business-side Business PO and Data Steward consolidates and filters front-line needs, defines business rules, holds the business UAT veto, drives adoption training, and stewards business terminology and data quality. BDO is a controlled subset of business users: its baseline grants service requests, knowledge lookup, and `requirements.create/view`; its data scope remains `requester == current auth_user.id`, and it gains no review, project, process, or IT-internal-task authority. A normal `requester` no longer has Requirement-module permission. Startup idempotently removes the legacy `requester → requirements` permission row without rewriting historical requirements.

## 7 (M3.6). Function Permission Matrix

- **Granularity**: all menu-aligned modules × actions (view — includes visibility and viewing / create / edit / delete). Stored as `role_permission` (role_code × module → actions).
- **Determination**: a user's permissions = the **union** of the matrices of direct roles ∪ group-granted roles; admin has implicit full authority, is not in the matrix, and is not configurable (to prevent lockout). The login response carries `permissions`, from which the front end renders menus/buttons, and the backend enforces `require_perm(module, action)`.
- **Boundaries** (three permission layers each own a segment, without redundancy):
  1. Function matrix: page visibility and create/edit/delete toggles (this section).
  2. Data scope: e.g. requester sees only their own tickets, and a knowledge draft is visible only to its author — built into the business code, not in the matrix.
  3. Process permissions: state-machine transition allowed_roles, process-step default_role — managed on the state-machine-config / process-definition pages.
- **Task-management permission modules**: `task_development` (development tasks), `task_bug` (Bug fixes), and `task_delegated` (delegated tasks) are separate from the legacy `req_tasks` (requirement implementation tasks). IT team members may register Bugs and delegated tasks by default; the development leader may maintain development, Bug, and delegated tasks; the product manager of the affected system receives the `task_bug` permission needed for Bug confirmation and verification. Record-level edit, assignment, and deletion remain guarded by the task service using reporter, assignee, process-node, and administrator scope; a front-end button or function-matrix entry alone is never sufficient.
- **Performance modules**: use separate modules for `performance_result` (result view), `performance_review` (staged review), `performance_external` (external raw input), and `performance_admin` (rules/period/publication). The function matrix controls page/actions; `performance_role_assignment.review_scope` then restricts business-domain, professional-pool, and editable line scope.
- **Performance visibility**: business/professional leads see reference scores and proposal fields only in their scope; the CIO sees all internal details and performs final review; evaluated employees have only `performance_result.view`, and the endpoint returns published final results only.
- **Performance field authority**: leads cannot edit raw team-contribution points, external raw facts, or the other line's components. Platform roles and leaders' own scores are entered directly by the CIO. Locked external facts are corrected by a new version only.
- **Point-rule authority**: team-contribution activity rules belong to the `ideas` Activity Points page; reads use `ideas.view`, while writes are hard-guarded to admin (implicit full authority) and CIO. Role-result rules belong to Team Management → Performance → Scoring Rules and use role profiles, dimensions, source mappings, and process/RACI step mappings. Current-period activity reads resolve automatic events against the latest effective team rule and a disabled rule displays zero; original `point_entry` rows, historical periods, and published/locked periods are not rewritten. Every change is audited against its own entity.
- **Training-activity record authority**: creation records `development_activity.created_by`. Editing or deleting a training activity is limited to admin, CIO, or its registrar and is rechecked against the record server-side; an existing row without a registrar that cannot be backfilled from creation audit is administrator/CIO-only. A host/participant change or deletion that changes training points is allowed only in the current unpublished, unlocked period; metadata-only edits remain audited.
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

After Aily + MCP confirmed submission, a service request enters the service item's bound process directly; ITOM does not add an Aily-routing step. IT completion moves only to `resolved`; the requester confirms through web or Aily before closure, or rejects to reopen. Rating is stored in `ticket_satisfaction` and copied to `Ticket.satisfaction` for compatibility.
| Change management | Change Enablement | Change request (it_ops) → Change approval (it_op_leader; CC it_bm) → Implementation & verification (it_ops) → Change retrospective/PIR (is_mgr; CC cio) |
| Problem analysis | Problem Management | Problem confirmation (professional-line owner, dynamically assigned, approval) → Root-cause analysis (handler selected by owner) → Resolution & verification (same handler) → Resolution confirmation & closure (professional-line owner, approval) |
| Bug fix | Bug Management | Register Bug (IT team member) → Bug confirmation (affected-system product manager, approval) → Generate fix tasks (development leader) → Development fix (assigned developer) → Verification & closure (affected-system product manager, approval) |
| Requirement delivery (pre-configured, attached in M5) | — | Requirement review (it_bm, approval) → Solution assessment & routing (it_pdm_leader, approval) → Delivery (it_dev_leader / project manager) → Acceptance & closure (it_bm, approval) |

| Project key milestones | Project Management | Project kickoff (it_pm, approval) → Execution monitoring (it_pm) → Closure retrospective (it_pmo, approval) |

Implementation-task permission supplement: after the workflow writes the requirement owner to `requirement.owner`, that owner may maintain multiple task rows while the requirement is `implementing`. This is a record-scope rule based on the document owner; it does not grant global `requirements.edit` or `req_tasks.edit`. Without global edit permission, a task assignee may update only the status and actual effort of their own task, while deletion still requires global Requirement/Task Tracking edit permission. The server evaluates the current account and live requirement status; front-end capability flags are not authorization.

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

## 11. Aily + MCP identity and normal-user permissions (P0/P1 implemented)

### 11.1 From Aily JWT to ITOM user

1. Nginx forwards `x-aily-jwt` to embedded MCP without logging the full value.
2. Aily reveals `identityJWTSecret` only after custom-MCP creation. First registration therefore allows only read-only protocol discovery such as `initialize` and `tools/list`, still requiring MCP to be enabled and Origin allowlisted; it cannot execute a tool.
3. `tools/call` validates configured HS256, `exp`, `tenant_id`, `agent_id`, and exact Origin. Aily documents the Feishu open ID as `user_id`, while the real tenant request observed on 2026-07-29 used `feishu_open_id`; the server accepts both and normalizes them to a string `open_id` subject.
4. If signature verification succeeds but the tenant or user has not been approved, the server records only a `status=pending` external-identity candidate and rejects tool execution. An administrator must select the ITOM account, allowlist the tenant, and activate the mapping.
5. The active external subject maps through `external_identity` to `auth_user`; IDs remain strings and security comparisons are constant-time where applicable.
6. Only active accounts continue; existing role matrix, data scope, and process guards then authorize the operation.
7. Every tool call writes a redacted `mcp_tool_call`. `get_current_user_context` returns verification/account status and a readable name only. P1 business tools return public business codes and user-visible summaries, never open_id, tenant_id, agent_id, or an internal ITOM primary key.

### 11.2 Business-user and BDO capability

- Search published service items eligible for the employee and retrieve their real forms.
- Create `service_request` and read own requests; P2 lists the user's pending confirmations, confirms or reopens an explicit own ticket, and rates an own closed request.
- A normal business user may create and read only own service requests. Only a BDO may register/read own IT requirements through existing `requirements.create/view`, with `requester == current auth_user.id` enforced by the service.
- Never create incidents/changes, read another user's records, or perform review, reassignment, approval, or internal process tasks.

The service-request tool does not accept `ticket_type`; requirement registration calls the separate Requirement domain service. UI hiding is not authorization: web APIs, MCP tools, and domain services enforce the same server-side boundary.

### 11.2a IT-staff web routing and transfer permission (phases A/B/C implemented)

“Record Creation Guide” is visible to IT staff and system administrators in the ITOM web experience, but not granted to normal business users. Routing recommendations are temporary, overrideable assistance and persist no answers. The server checks IT-staff-or-administrator eligibility plus at least one real target create permission, then filters each jump target by the current permissions; the flow cannot bypass target-record authorization. This web guide is separate from Aily MCP tools; Aily requirement tools are available only to BDOs and authorized IT roles.

Phase-B relation reads are trimmed by visibility of both source and target, and detail pages display only that safe result, so a related record cannot leak access to another record. Phase-C `prepare/submit` is implemented: an actor needs both source-record read scope and the target record's `create` permission; the server derives the target kind from its whitelist, checks idempotency key/request digest while holding the source-row lock, then lets the target domain service validate required fields, workflow node, approval, role, and data scope and writes the relation in the same transaction. System-level administrator authority does not replace a business submitter's service-request confirmation and does not change the Aily normal-user boundary.

### 11.2b Web-agent identity and capability trimming (WA0 Task 2 implemented)

The web agent accepts only the current ITOM login session, never client-supplied roles and never the Aily JWT. Each turn derives a one-request discoverable-capability list only from the active account, `effective_roles`, the feature matrix, and a published profile's capability codes and maximum risk. A normal requester is service-request-only; a BDO adds own IT requirements; IT staff receive internal guidance and progressively enabled actions under real authorization; administrators remain bound by business invariants such as submitter-only confirmation. Record data scope, state, ownership, and current process assignment are not discovery-time execution authorization; fixed handlers must re-authorize them when calling domain services.

A model profile controls wording, knowledge scope, disabled capabilities, and maximum risk only; it never authorizes. An L3 token binds the ITOM user, web conversation, capability, payload digest, and expiry and is re-authorized at confirmation. Users read only their own conversations; administrators see operational metrics and action audit by default, not complete transcripts. See [`docs/en/superpowers/specs/2026-08-01-itom-web-agent-design.md`](superpowers/specs/2026-08-01-itom-web-agent-design.md).

Task 2's `capabilities_for_user()` accepts no browser- or model-claimed role/audience. It reloads an active, non-deleted `AuthUser` solely by user ID, then calls the existing `effective_roles()`, `user_permissions()`, and `has_perm()`. A requester discovers only service-request scope; a BDO adds only requirement capability; direct and user-group-granted IT roles both resolve through the existing effective roles; an auditor-only account cannot discover L2/L3; and admin still discovers only registered non-L4 capabilities. An enabled published profile version may narrow discovery by explicit capability code and maximum risk; an incomplete published profile, disabled account, or account without roles fails closed. Handlers, internal role/permission details, and disabled capabilities never enter model schemas.

The fixed registry rejects duplicate capability codes, L3 without confirmation, every L4, a missing Pydantic input model, and a missing handler; input fields/aliases must also pass credential and authorization-internal segment checks that reject authorization context, permission scope/matrix, and role IDs. Exported field schemas remove `default/example(s)` metadata and values but retain legitimate same-named business fields inside `properties`. That registration check does not replace business execution checks: each future record-level handler must revalidate data scope, record state, ownership, and current workflow task before calling a domain service. Model input, `AiMessage.content` persistence, and ordinary log/audit summaries must use the same recursive deterministic redaction with shared mapping-key/text-assignment classification so passwords, tokens, secrets, cookies, authorization, API/access/private keys, Bearer/JWT text, and dynamic sensitive-form values never retain their raw value.

WA0 registers `admin_ai` (AI Agent) under System Administration. It is not added to the default matrices for requester, BDO, IT staff, or auditor; only `admin` reaches model and profile governance through the existing implicit full authority. This functional entry grants neither business data scope nor workflow authority, and cannot replace a business submitter's confirmation.

### 11.3 Confirmation, idempotency, and cross-ticket safety

Create/register mutations first create `mcp_operation_intent` and validate a confirmation token plus idempotency key at submission. Confirmation/reopen/rating is already an explicit user action, so it creates a same-transaction idempotency intent without issuing a second token. Every intent binds the ITOM user, tool, and normalized payload digest. An explicit ticket code is mandatory; when multiple tickets await confirmation, Aily asks the user to choose and never guesses the latest. Retries return the first result, while the same key with different parameters is rejected.

The final requester-confirmation task is submitter-only; even administrators cannot confirm for the submitter. Web, MCP, and Feishu card callbacks use the same domain semantics: confirmation closes, while rejection with a reason rewinds to the nearest real handling step. Proactive messages select the account's most recently used active Feishu identity and include user-visible progress only, never internal notes, root cause, or approval data. Ordinary conversation maps identity through Aily JWT and uses MCP; card buttons are the sole exception. ITOM first verifies the Feishu signature, age, Verification Token, and Bot App ID, and requires the callback header and `operator` to carry the same `tenant_key`. Aily JWT `tenant_id` and card-callback `tenant_key` are different identifier namespaces. When they do not match directly, `operator.open_id/user_id/union_id` must uniquely resolve, within the allowed bot/Agent application set, to an active `external_identity` under an authorized Aily tenant. The domain service finally verifies that the mapped account submitted the ticket. Unknown cross-namespace identities are denied directly; an unknown identity under a directly recognized tenant may be recorded as a pending candidate and is still denied. Mappings to different accounts are rejected as ambiguous. Card action values never carry Feishu identifiers, JWTs, ITOM internal primary keys, or internal handling fields.
The digital-team population is an explicit shared department-tree scope in `org_settings`, optionally including descendants. It is authoritative for team metrics and business-domain owner, backup-owner, and service-team selectors; the legacy `dept_type`/role heuristic is used only until an administrator configures the scope.
