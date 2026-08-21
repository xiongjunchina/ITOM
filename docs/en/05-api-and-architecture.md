# ITOM API Contract & Architecture Design

> English translation of [../05-API契约与架构设计.md](../05-API契约与架构设计.md). For the authoritative version, the Chinese source prevails.

> Based on [03-PRD.md](03-PRD.md), [04-data-model.md](04-data-model.md).
> P0 protocol/identity/live bot receipt, P1 intake, and P2 service closure were implemented on the now-archived `feature/aily-agent-mcp` branch and are inherited by the current `feature/AI-agent-version` branch. P2 passed the real-Aily multi-role conversation, live bot receipt, and the normal-user same-ticket end-to-end run. P2.1 now uses Feishu's new signed `card.action.trigger` callback. The Aily Workflow/Skill path does not perform card mutations because it cannot provide a trusted `x-aily-jwt`; the historical unresolved → reopen → resolve and close → rate button loop has passed. The 2026-07-31 IDC certificate failure was remediated on 2026-08-10 with a trusted public chain for `itom.snnc.cc:30443`; standard TLS validation, browser access, and external MCP initialize now pass. A newly generated current-IDC ticket/card still needs a real-role signed-card click before “confirm closure” acceptance can be claimed. P3 Feishu Approval is deferred by user decision, while IDC release hardening and formal acceptance continue. Helpdesk routes belong only to the frozen `v1.0.0-feishu-helpdesk` baseline.

## 1. System Architecture

```text
Feishu user ⇄ Aily Agent ──HTTPStreaming + x-aily-jwt──▶ Nginx /mcp
                                                         │
Feishu user ──click bot card──▶ Feishu Open Platform ──signed callback──▶ Nginx /api/integrations/feishu/card-actions
                                                         │
React SPA ──JWT Bearer──▶ Nginx /api ────────────────────┤
                                                         ▼
                                        FastAPI monolith with embedded MCP
                                          routers/MCP → domain services
                                                         │
                                       RBAC / workflow / audit / PostgreSQL
                                                         │
                                        event bus → notification outbox
                                                         │
                                         Aily-bot Feishu message → user
```

**Key decisions**:

1. **Monolith backend**, modularized by domain, no microservices — at a single-team scale, microservices only add complexity.
2. **MCP is embedded in FastAPI** and reuses domain services, transactions, RBAC, workflow, and audit; tools never write tables directly.
3. **Domain events are dispatched in-process synchronously**; the reliable outbox asynchronously delivers in-app and Aily-bot messages.
4. Front end and back end remain in one monorepo. Nginx proxies both `/api/` and `/mcp`.

## 2. Repository Structure

```text
ITOM/
├── backend/
│   ├── app/
│   │   ├── core/          # config, GLID, security (JWT/bcrypt), dependency injection
│   │   ├── models/        # SQLAlchemy models (one file per domain: support/itsm/project/requirement/process/team)
│   │   ├── schemas/       # Pydantic request/response models
│   │   ├── routers/       # API routes (one file per domain)
│   │   ├── services/      # business-logic layer (state-machine validation, code generation, computed-column maintenance)
│   │   ├── events/        # event_bus + subscribers (points/notify/process)
│   │   └── main.py
│   ├── alembic/           # database migrations
│   ├── seeds/             # initial data (state machines, SLA policies, process definitions, point rules, dictionary)
│   └── tests/
├── frontend/
│   └── src/{api, components, pages, router.tsx, stores}
├── deploy/                # docker-compose.yml, Dockerfile×2, nginx.conf, IDC K8s manifests and release scripts
└── docs/                  # this design-document series
```

## 3. API Conventions

- **Authentication**: `POST /api/auth/login` → JWT (8h); all other endpoints use `Authorization: Bearer`.
- **RBAC**: routes declare the required roles, validated by dependency injection; data-level filtering (requester sees only their own records) is in the service layer.
- **Response envelope**: `{"success": true, "data": ..., "total": n, "page": p}`; errors `{"success": false, "error": {"code": "TICKET_INVALID_TRANSITION", "message": "..."}}`, with the HTTP 4xx/5xx kept in sync.
- **Pagination**: `?page=1&page_size=20` (default 20, max 200); filter parameters are per-resource; sorting `?order_by=-submitted_at`.
- **Unified state-transition pattern**: `POST /api/{resource}/{id}/transition` `{"to": "resolved", "fields": {...}}` — state-machine validation + the staged fields required by that transition (e.g. solution required at resolution) submitted in one call.
- OpenAPI docs are auto-generated at `/api/docs`.
- **MCP authentication**: Aily sends `x-aily-jwt`; MCP validates HS256, expiry, tenant/agent allowlists, and maps through `external_identity` to an active `AuthUser`.
- **MCP mutation**: `prepare_*` creates a short-lived operation intent; `submit_*` requires its confirmation token and an idempotency key. MCP returns structured MCP content, not a fake REST envelope.

## 4. Route Inventory (by domain)

### 4.1 Authentication & Support

```text
POST /api/auth/login | GET /api/auth/me
GET /api/auth/me/profile | PATCH /api/auth/me/preferences
POST /api/auth/me/password | GET /api/auth/me/audit-logs
GET /api/auth/me/todos
GET /api/auth/me/feishu-binding/authorize-url
POST/DELETE /api/auth/me/feishu-binding
GET /api/auth/feishu/client-config | POST /api/auth/feishu/app-login
GET/POST/PATCH/DELETE /api/admin/users   # admin; delete soft-deletes the account and unlinks the person
GET/POST/PATCH /api/members              # personnel master data
GET /api/admin/master-data?category=     # dictionary (read-only for all, writable by admin)
GET/PUT /api/admin/workflow-config       # state machine
GET /api/admin/audit-logs
GET /api/notifications | POST /api/notifications/{id}/read | POST /api/notifications/read-all | POST /api/notifications/clear-read   # in-app notifications, bulk read, and read cleanup
POST /api/attachments (multipart) | GET /api/attachments?entity= | GET /api/attachments/{id}/download
POST /api/attachments/ticket-drafts (multipart) | DELETE /api/attachments/ticket-drafts/{id}   # pre-creation service-request drafts
POST /api/attachments/requirement-drafts (multipart) | DELETE /api/attachments/requirement-drafts/{id}   # pre-registration IT-requirement drafts
```

Requirement list/detail responses expose the authoritative `Requirement` score projection (`d1_strategy` … `d6_speed`, `weighted_total`, and `quadrant`) even when legacy/imported rows have no `requirement_score` history. `POST /api/requirements/{id}/score` accepts Approved only with complete scores outside Re-evaluate; On Hold and Rejected remain valid decisions, with Rejected requiring a reason of at least five characters.

Profile constraints: preference PATCH updates only submitted keys; theme is `light|dark|system`, density is `default|compact`, and `table_views` is bounded to stable list keys, field names, and widths of 80–800px; protected identifier/title/action columns cannot be hidden. `GET /api/auth/me/todos` returns only active tasks the current account may handle under workflow authorization and controlled entity-detail links; it does not grant permission. Passwords require at least eight characters with letters and digits, and an existing deliberate password requires a valid `current_password`. Feishu unbinding requires a local password; personal audit logs return only records whose actor is the current account.

Before submitting a service request or IT requirement, the web form may send `file` to `POST /api/attachments/ticket-drafts` or `POST /api/attachments/requirement-drafts` (images, PDF, and common office files; 50MB per file and at most 10 per record). The response returns safe metadata only, and the browser sends its IDs as `attachment_ids` to `POST /api/tickets` or `POST /api/requirements`; a requirement may also submit `remarks` as Other supplemental information. The domain service accepts only non-deleted matching drafts uploaded by the current account and rebinds them to `entity_type=ticket` or `requirement` in the same transaction as record creation, workflow start, and audit; one invalid ID fails the whole creation transaction. Only the uploader may delete a draft; unbound drafts expire after 24 hours and neither draft type can be listed or downloaded through generic routes. Committed files inherit the relevant record's function permission, data scope, and, for extra uploads, workflow edit window. The `total` of every server-paginated response remains the full filtered count; the client must never replace it with current-page `items.length`.

### 4.1a Organization Sync (M35)

```text
POST /api/admin/org-sync                 # starts in background; returns {started:true}
POST /api/admin/org-sync {sync:true}     # blocking mode for tests/scripts
GET /api/admin/feishu-config             # last_sync_stats.status: running|done|failed
```

A repeated trigger while running returns HTTP 409 / `SYNC_RUNNING`. The UI polls every three seconds for up to ten minutes. Completion or failure sends an in-app notification to the initiator, and the background worker uses an independent database session.

### 4.1b Aily Agent + MCP (P0/P1/P2 implemented)

```text
GET/POST /mcp/
    # Implemented Streamable HTTP entry; exact allowlisted Origin is always required
    # Aily's custom-MCP request URL must retain the canonical trailing slash; omitting it fails save-time validation
    # read-only initialize/tools-list discovery can complete first registration before the JWT secret is copied back
    # tools/call requires a verifiable x-aily-jwt plus tenant/agent and identity mapping
    # Nginx disables buffering, uses a 300-second read timeout, and forwards auth/Origin

GET/PUT /api/admin/integrations/aily
    # admin; reads only configured flags; writes encrypted MCP JWT and bot credentials
GET/POST /api/admin/integrations/aily/identities
PATCH/DELETE /api/admin/integrations/aily/identities/{id}
    # exact provider+tenant+app+subject-type+subject-ID mapping to an ITOM account
POST /api/admin/integrations/aily/test-message
    # send a bot test message to a selected verified external identity

get_current_user_context
    # temporary P0 diagnostic: returns verification, account status, and readable account name only; no internal/external IDs; writes mcp_tool_call
```

MCP is mounted inside FastAPI and does not create a second business API. P0 uses MCP Python SDK 1.29 with stateless Streamable HTTP. First registration permits protocol discovery only; every `tools/call` still requires JWT, tenant/agent, external identity, and account status. P1/P2 tools handle protocol, identity context, structured I/O, and redacted audit only; intake, dispatch, workflow, requester confirmation/reopen, and rating use the same ITOM domain services as the web application.

#### Service-request tools

```text
search_service_items
get_service_item_form
prepare_service_request
submit_service_request
get_my_service_request
list_my_service_requests
```

The six tools above are implemented in P1. The following closure tools are implemented in P2:

```text
get_my_pending_confirmations
confirm_service_request_resolution(ticket_code, resolved, idempotency_key, feedback="")
rate_service_request(ticket_code, score, idempotency_key, tags=[], comment="")
```

- Search returns only published service items eligible for the current user.
- Form retrieval returns the published schema, SLA, process summary, and public instructions.
- Prepare performs authoritative ITOM validation and returns normalized data, missing/errors, SLA, process, expected support group, and a short-lived operation intent without creating a ticket.
- Submit does not accept `ticket_type`; the server fixes it to `service_request` and validates user, intent, form version, and idempotency key.
- Pending confirmations list only the current user's `resolved` requests and return public ticket code/title/item/solution/deadline without root cause, internal notes, or approval data.
- Resolution confirmation requires an explicit ticket code and the submitter. True completes the requester task and closes; false requires feedback, rewinds to the nearest real handling step, increments reopen count, and notifies the handler. Rewind soft-deletes obsolete tasks at and after the target; the next resolution refreshes `ticket.solution` from the latest non-deleted completed task. Web confirmation uses the same semantics, and administrators cannot confirm for the submitter.
- Rating is submitter-only for a closed request: score 1–5, at most five 32-character tags, and an optional 500-character comment. A later rating updates the one effective row and remains audited.
- Direct confirmation/reopen/rating actions require an 8–128-character idempotency key. Same payload replays the first result; a different payload returns `IDEMPOTENCY_CONFLICT`. These are already explicit user actions and do not issue a second confirmation token.

#### IT-requirement tools

```text
get_it_requirement_form
prepare_it_requirement
register_it_requirement
get_my_it_requirement
list_my_it_requirements
```

Registration creates a separate `Requirement`, never a Ticket. The request may include existing `remarks` as Other supplemental information and up to 10 current-account `requirement_draft` attachment IDs; the service rechecks ownership, count, and non-deleted state while binding attachments in the same transaction as the requirement, workflow, and audit. Normal business users have no Requirement-module permission; only BDOs and authorized IT roles reuse `requirements.create/view` with enforced own-record scope. The domain service also checks the BDO/IT role boundary, so a historical or manually added requester permission row cannot bypass it; review, scoring, project conversion, and closure retain existing edit/process permissions.

#### Requirement implementation-task APIs

```text
POST /api/requirements/{requirement_id}/tasks
POST /api/requirements/tasks                       # standalone development task
PATCH /api/requirements/tasks/{task_id}
DELETE /api/requirements/tasks/{task_id}
DELETE /api/requirements/tasks/batch-delete
GET /api/requirements/tasks/active
```

The path-scoped `POST` may register multiple rows for an implementing requirement. `POST /api/requirements/tasks` creates a standalone row with `requirement_id=null`; `PATCH` may later add or change the relationship. A supplied requirement must be in Implementation, non-example, and have a frozen `implementation_route` other than Convert to Project; a plain `project_id` only records an association and is not routing proof. Full-field maintenance, own-assignee update restrictions, state-aware deletion, and server-side authorization remain in force; existing IDs and soft-deleted rows are preserved. Frontend candidates and bulk import use this same route rule, while requirement detail loads assignee candidates from `can_manage_tasks` rather than workflow-record `can_edit`.

Requirement list/detail `d1_strategy`…`d6_speed`, `weighted_total`, and `quadrant` are authoritative projections of the main Requirement scoring fields. `POST /api/requirements/{id}/score` requires complete non-Re-evaluate scoring for Approved. A Rejected decision requires a reason of at least five characters and may carry `return_to_seq`, selected from detail `process.return_targets`: a prior actually reached process node or `0` for Requester supplement. Omitting it chooses the nearest prior node; a first approval with no process predecessor defaults to `0`. The server atomically records the rejected task, returns the instance, and projects the domain status; rejection must never be persisted as Close or Cancel.

Requirement detail returns `process.return_targets` only for the current approval task, as `{seq,name,kind}`, plus `process.return_info` for the latest reason, time, and real actor. Returning to a process node keeps the instance `running` and appends a new target-node task. Choosing `seq=0` sets the instance to `returned` and requirement to `supplementing`, limits correction to the requester/administrator, and returns `can_resubmit=true`. `POST /api/requirements/{id}/resubmit` accepts no client-selected handler or target; it reactivates the first review task on the same instance and restores `evaluating`. Future or never-reached targets, an actor who is not the current task handler, insufficient reason, wrong state, or non-requester resubmission fail closed.

`POST /api/requirements/{id}/to-dev` uses an empty payload (legacy clients may send `owner_id`, but a value that differs from Requirement Scoring Rules `review_assignees.dev_leader` returns `DEV_LEADER_FIXED`). The configured active IT development lead must exist; a missing or invalid setting returns `DEV_LEADER_NOT_CONFIGURED`. Both route endpoints may handle only the current “Solution assessment & routing” task, otherwise return `PROCESS_STEP_MISMATCH`, and advance only to “Delivery”. Before an in-house-dev Delivery task can complete, the process engine requires at least one non-deleted `requirement_task`; it does not apply that check to project routes or legacy records without an `implementation_route` snapshot.

#### Task-management APIs (M82)

The frontend routes are `/task-management/development` and `/task-management/delegated`; `tab=requirement|bug|project` selects the Development Tasks view without changing backend resources. Historical requirement-task routes still redirect to Requirement Development.

```text
GET /api/requirements/tasks/template
POST /api/requirements/tasks/import

GET/POST/PATCH /api/task-management/bugs
GET /api/task-management/bugs/{id}
DELETE /api/task-management/bugs/batch-delete
GET /api/task-management/reference/cis              # read-only CMDB system candidates for Bug registration
POST /api/task-management/bugs/{id}/confirm
POST /api/task-management/bugs/{id}/reject-confirm
POST /api/task-management/bugs/{id}/fix-tasks
PATCH /api/task-management/bug-fix-tasks/{id}
POST /api/task-management/bugs/{id}/verify
POST /api/task-management/bugs/{id}/reopen

GET/POST/PATCH /api/task-management/work-tasks
GET /api/task-management/work-tasks/{id}
POST /api/task-management/work-tasks/{id}/progress
POST /api/task-management/work-tasks/{id}/transition
DELETE /api/task-management/work-tasks/{id}
DELETE /api/task-management/work-tasks/batch-delete

GET /api/task-management/reference/projects
GET /api/task-management/reference/projects/{project_id}/wbs
GET/POST/PATCH /api/task-management/project-tasks
GET /api/task-management/project-tasks/{id}
POST /api/task-management/project-tasks/{id}/progress
DELETE /api/task-management/project-tasks/{id}
DELETE /api/task-management/project-tasks/batch-delete
```

The same requirement in Implementation may repeatedly call `POST` to register multiple task rows. Every built-in IT role receives `view/create/edit` on `task_development` and may therefore maintain full development-task fields on an implementing requirement. The requirement owner retains compatible record-scope maintenance; an assignee without maintenance may update only their own `status` and `actual_effort`. Deletion is a server-side status rule rather than a matrix `delete` grant: an IT user with development-task maintenance may soft-delete a task that is not In Progress, while an In Progress task is deletable by the system administrator only. List responses return `can_manage_tasks`, `can_edit`, and `can_delete`; detail task rows return `can_delete`. The server never relies on a front-end button and rechecks requirement stage, owner scope, example-data protection, and permission for every write.

`GET /api/requirements/tasks/template` returns a Development Tasks worksheet whose requirement-code column is optional. `POST /api/requirements/tasks/import` accepts multipart `file` up to 5MB: a blank code creates a standalone task, while a supplied code is validated as a real, non-example requirement in Implementation whose frozen route is not Convert to Project; a normal `project_id` association is accepted. Active IT assignees are exact-name matched. Valid rows write audit and assignment notifications; `{created, failed}` remains append-only and never updates or de-duplicates existing rows.

Development-task read contracts consistently return persisted identifiers and registration timestamps: Requirement Development rows expose RT `task_code` plus `created_at`; Project Development exposes PT `task_code` plus `created_at`; Bug parent rows expose BG `bug_code` plus `created_at`; and each nested `fix_tasks` child exposes BT `task_code` plus `created_at`. The browser sorts these returned business fields locally rather than displaying page-relative row numbers. Startup migration fills only missing RT/BT values using the original `created_at` month and deterministic `created_at + id` order, then applies unique non-null constraints without modifying any other historical field.

Bug APIs snapshot `ci.product_manager_id`; clients cannot choose an approver. During the shared upstream correction window, `PATCH` may change `ci_id` and refresh the validated product-manager snapshot. `DELETE /bugs/{id}` follows workflow-record deletion rules: the creator is allowed only before the next node is viewed/handled, while administrators remain allowed; active workflow tasks are finalized and soft-deleted with the record. Bug codes and Detail buttons both open `GET /bugs/{id}`. Delegated and Project Development progress is append-only. A project is mandatory and WBS is optional but, when supplied, must belong to that project. Project progress accepts optional `complete` (default `false`): ordinary calls allow only 0–99% and start a Pending task; `complete=true` requires a non-empty comment and atomically writes Done, 100%, the completion note, and completion time. Normal `PATCH` cannot first set Done or reopen a Done task. Responses expose derived `completion_percent` and `capabilities.complete`; text notes remain in the append-only detail timeline. Capability flags remain advisory and every write is reauthorized server-side.

Task notification events use `notifier.notify()`: initial assignment or reassignment targets the assignee; progress/status/actual-effort/completion updates by someone other than the registrar target the registrar. The same business transaction creates the in-app notification and `notification_outbox(channel=feishu_aily)` row. Outbox identity/tenant/Bot controls remain authoritative and an unmapped identity stays pending rather than sending to an unknown recipient. Each progress-entry ID is the idempotency source, so consecutive updates remain distinct.

`GET /api/task-management/reference/cis` returns only non-deleted, non-retired CMDB configuration items and readable product-manager information for the Bug form's “Affected system” field. It does not create a second system dictionary or grant CMDB write access. CMDB `owner` is the required technical owner for every CI; only an Application's `product_manager_id` is its Bug-confirmation and verification product manager. They may be the same person but are not duplicate fields. The backend rejects creating or editing an Application without a product manager. A legacy Application missing the value returns `PRODUCT_MANAGER_REQUIRED` on Bug registration; configure it and retry, then the registration snapshots that person.

`GET /api/itsm-import/ci/template` returns the CMDB Excel template and `POST /api/itsm-import/ci` appends rows independently. **Technical owner name** maps to `owner`, while **Application product manager name** maps to `product_manager_id`; the latter may be filled only for, and is required by, an Application. Both names exactly match active system members. A missing or unknown Application product manager, or a product-manager value on a non-Application row, is returned as a row error; import never updates existing CIs or migrates historical data.

`DELETE /api/tickets/{id}` first finalizes and soft-deletes every active process instance and unfinished task for the ticket after the existing record-level delete authorization, then soft-deletes the ticket and writes its audit record. A later `GET /api/tickets/{id}` for a previously existing, soft-deleted ticket returns HTTP 404 with `TICKET_DELETED` and “The ticket was withdrawn or deleted and its detail is unavailable”; a never-existing ID still returns `NOT_FOUND`. No deleted fields are returned. This gives in-app and Feishu/Aily historical links an accurate outcome; already-delivered external messages cannot be recalled.

Performance and point events: closing a Bug fix child task publishes `bug_fix_task.completed`; closing a delegated task publishes `work_task.closed`. Point subscribers write idempotently by source record and rule. Bug-fix and ordinary delegated work use job-result rules by default. A delegated task may write to `learning_growth`, `cross_team_support`, or `training_knowledge` only when the server accepts its team-contribution type and `performance_bucket=team_contribution`. Delivery metrics use the assignee, planned date, and actual close date; an open task is not failed before its due date.

#### Controlled list batch deletion

```text
DELETE /api/tickets/batch-delete | /api/requirements/batch-delete
DELETE /api/problems/batch-delete
DELETE /api/requirements/tasks/batch-delete
DELETE /api/task-management/bugs/batch-delete | /work-tasks/batch-delete | /project-tasks/batch-delete
DELETE /api/trainings/batch-delete
DELETE /api/projects/{project_id}/wbs/batch-delete
DELETE /api/cis/batch-delete | /api/ci-relationships/batch-delete
DELETE /api/catalogs/batch-delete | /api/service-items/batch-delete
```

Every batch-delete endpoint accepts `{ids: [...]}` (1–100 records) and returns `{deleted_ids, rejected:[{id, code, message}]}`. Each item runs in an isolated nested transaction and reuses the original single-record deletion checks for authorization, state, references/dependencies, and audit. Only actually deleted records are committed, while rejected records do not block the remaining items. WBS batch deletion processes the deepest selected tasks first and the single-delete guard continues to reject completed tasks. Catalog deletion does not cascade: a catalog still containing service items and a service item still referenced by an active ticket are rejected with their original business error codes.

A list displays its batch toolbar only when rows are selected and derives available actions from the page's existing capabilities and the selected records' states. Row-level Action columns render localized Tooltip/`aria-label` icon buttons, and the shared table constrains those columns to the minimum usable width; oversized persisted action-column preferences must not keep meaningless blank space. Batch toolbar buttons retain explicit text labels. WBS uses its dedicated table enhancer for checkbox/select-all, disabling rows whose current completion is 100%, one fixed browser-native bottom scrollbar, and the in-table native fallback; the global horizontal-scroll enhancer must not attach a duplicate control to this table. Its Phase and Action columns have dedicated compact widths. WBS capabilities are derived from current completion, while `completed_at` remains only a first-completion audit fact. After completion is corrected from 100% to a lower value, the frontend must await reload of the WBS list, milestone tracking, and project detail before enabling delete, add-child, and structural controls from the refreshed capabilities.

#### Forbidden tools

V1 does not provide incident/change creation, arbitrary transitions, reassignment/approval/task completion, generic SQL/database access, or general HTTP. A suspected broad outage still creates a service request flag; IT staff or monitoring creates the incident.

#### Proactive messaging

MCP cannot wake Aily on a background transition. ITOM notifications entering `notifier.notify()` write a `notification_outbox(channel=feishu_aily)` text row by ITOM account in the original business transaction. A stable event/entity/account digest provides idempotency. If the account has no active verified Aily-bot identity, the row remains `pending` with internal `auth_user_id` and `AILY_IDENTITY_NOT_MAPPED`; the worker resolves the identity immediately before sending and waits without consuming retry attempts, never sending to an unknown recipient. Once the Feishu login callback is verified and resolves to an active ITOM account, it automatically persists a current-bot-app identity from OAuth `tenant_key` and the cross-app-stable `user_id`, with `union_id` as the fallback, and records a dedicated audit event. When exactly one active audited `tenant_key` exists for the current `bot_app_id`, it becomes the worker's sole trusted tenant anchor. For another unmapped account, reconciliation is allowed only when it is linked to an active Feishu-synchronized `org_member`: the login-app `open_id` is used to query that one directory user, while the returned tenant-level `user_id` (or `union_id` fallback) becomes the bot-app recipient mapping. The login-app `open_id` itself is never sent to the bot API. A missing or ambiguous anchor, inactive account/person, missing person link, explicit disable, or identity conflict keeps the row pending; lookup errors do not consume message-send attempts. The Aily JWT `tenant_id` allowlist remains an inbound MCP contract and does not gate this outbound mapping. Outbound resolution prefers the current `bot_app_id` mapping; legacy manual/Aily identities remain constrained by the original tenant allowlist. A disabled Aily integration creates no new outbox rows, while incomplete bot configuration leaves rows pending. First acceptance, resolution, reopen, closure, and rating-save events still use dedicated subscriptions for interactive cards or text fallback; generic delivery skips `ticket.resolved` so a resolution card is not duplicated. The first unresolved click only replaces the card with a required reason form, and submission then reopens the request.

Ordinary conversation remains Aily + MCP only. Card buttons are the sole exception: Feishu posts the new `card.action.trigger` to `POST /api/integrations/feishu/card-actions`. Before parsing business JSON, ITOM computes the SHA-256 signature from `X-Lark-Request-Timestamp`, `X-Lark-Request-Nonce`, Encrypt Key, and the raw body, and enforces a five-minute age limit. Timestamps use the official Unix-seconds/milliseconds format, while the implementation also accepts the timezone-bearing Go monotonic-clock string observed in real Aily callbacks; signature calculation still uses the original header string. Encrypted bodies use AES-256-CBC/PKCS#7. ITOM then verifies the Verification Token, Bot App ID, consistency between the header and clicker's `tenant_key`, and an explicit `open_id/user_id/union_id` mapping for the clicker. Live integration proves that Aily JWT `tenant_id` and card-callback `tenant_key` are different identifier namespaces and cannot be forced to string equality. If the callback tenant does not directly match the Aily tenant allowlist, the clicker must uniquely map, within allowed Agent/Bot apps, to an active ITOM account under an authorized Aily tenant. Unknown, ambiguous, disabled, or unauthorized identities are denied, and an empty allowlist never grants fallback access. Live setup also showed that Feishu sends an encrypted `url_verification` challenge without signature headers when saving a Webhook URL. That read-only handshake is accepted only after successful decryption, an exact challenge type check, and Verification Token matching; every `card.action.trigger` still requires a complete valid signature. The callback calls `service_request_closure` only and never writes tables directly, preserving RBAC, requester-only scope, workflow state, 8–128-character idempotency, and audit. It returns a Toast and updated card within Feishu's three-second limit. Immediate updates use the required new-callback envelope, `card={"type":"raw","data":<complete card JSON>}`; raw card JSON must never be placed directly under `card`. Invalid signatures receive HTTP 401; business denial returns an error Toast and leaves the card unchanged. Action values carry public ticket code, action, score, and idempotency key only—never identity, tokens, secrets, internal IDs, or internal handling data.

Protocol references: Feishu Open Platform's [handling card callbacks](https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/handle-card-callbacks?lang=zh-CN), [receiving callbacks](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/receive-and-handle-callbacks?lang=zh-CN), and [input component](https://open.feishu.cn/document/feishu-cards/card-components/interactive-components/input?lang=zh-CN). The implementation accepts the new `card.action.trigger` only and does not support the deprecated legacy card callback.

Delivery keeps event/entity/account idempotency, retry/backoff, and redacted errors. Missing identity mappings remain observable as pending rows and are re-evaluated at send time; the most recently used active Feishu identity is selected only after the account mapping is verified. Disabled integrations create no new rows, while incomplete bot configuration preserves pending rows without consuming attempts. Internal notes, root cause, approval details, and sensitive fields never leave ITOM. Administrators use the existing `GET/PUT /api/admin/integrations/aily` configuration for the message switch, bot credentials, tenant allowlist, and public base URL; secrets remain write-only and no new API or database migration is required.

All `/api/integrations/feishu/helpdesk/*` routes, subscriptions, handoffs, queues, and Helpdesk-specific outbox have been removed from the new runtime. Existing PostgreSQL structures are previewed by `python -m app.scripts.migrate_aily_mcp` and are permanently removed only with explicit `--confirm`.

### 4.1c IT-staff routing and cross-record relations (phases A/B/C implemented)

The following contracts serve only the IT-staff web experience and add no Aily/MCP tool. Routing, guidance, scope-constrained relation reads, and create-target-and-relate endpoints are live:

```text
POST /api/staff-intake/recommend
    # live: IT staff; temporary answers → recommendation, rationale, counterexample, target entry filtered by real create permission; no persistence
GET  /api/it-document-guide
    # live: signed-in user; one-line guidance and case library for six records; server returns IT-staff capability switch
POST /api/record-relations/prepare
    # live: source record + relation_type; validates source read/target create and returns safe prefill/required target fields
POST /api/record-relations/submit
    # live: target form + relation_type + reason + idempotency_key; source lock + submission digest prevent duplication, then target domain service creates the target, starts its workflow, writes relation and audit
GET  /api/records/{entity_type}/{entity_id}/relations
    # live: after source visibility is checked, returns only counterparts also visible to the current user; it does not leak an invisible record's existence, code, or title
```

`prepare` and `submit` accept only the four server-whitelisted source/target combinations. `submit` does not accept a client-selected target entity type; the server derives it from the source record and `relation_type`, verifies source data scope plus target `create` permission, then invokes the ticket, problem, or project domain service. A retry using the same actor/source/target-kind/idempotency key and normalized request returns the first target; same-key different input returns `IDEMPOTENCY_CONFLICT` (409).

`recommend` questions and answers are not persisted. Active source/target/relation uniqueness plus creator/source/target-type/idempotency-key uniqueness are enforced; a request digest rejects a reused key with different parameters. `prepare/submit` do not write domain tables directly; `submit` invokes the incident, problem, change, project, or other target domain service for its own fields, status, workflow, approval, RBAC, audit, and event publishing. A server whitelist controls first-phase relation types. Idempotent retries return the first result and never alter the source record's type, status, or workflow.

### 4.1d ITOM web agent (WA0–WA4; design approved)

The web agent uses the existing ITOM Bearer login and an independent `/api/assistant` entrance; it does not self-connect through Aily `/mcp/`. The two channels share only domain services, permission, forms, workflow, confirmation, idempotency, and audit. Target APIs are:

```text
GET/POST /api/assistant/conversations
GET      /api/assistant/conversations/{id}
POST     /api/assistant/conversations/{id}/messages    # SSE
POST     /api/assistant/actions/{id}/confirm|cancel
POST     /api/assistant/conversations/{id}/archive
GET      /api/assistant/bootstrap

GET/POST       /api/admin/ai/providers
PATCH/DELETE   /api/admin/ai/providers/{id}
POST           /api/admin/ai/providers/{id}/test
GET/PATCH      /api/admin/ai/profiles/{code}/draft
POST           /api/admin/ai/profiles/{code}/publish|rollback
GET            /api/admin/ai/health|usage?days=1..90|action-audits
```

The model receives only code-registered capabilities available to the current user. An L3 action first issues a single-use token bound to user, conversation, capability, normalized payload digest, and expiry; confirmation rechecks account, permission, data scope, record state, and workflow assignment. Only a domain service may return success. Provider reads expose `has_secret` only. See [`docs/en/superpowers/specs/2026-08-01-itom-web-agent-design.md`](superpowers/specs/2026-08-01-itom-web-agent-design.md).

WA0 Tasks 1–2 implement the persistence foundation plus the server-side policy/redaction kernel. Only a fixed code registry may register capabilities; registration rejects duplicate codes, L3 without confirmation, every L4 capability, non-Pydantic input, and a missing handler. Input-model fields and aliases are checked by credential and authorization-internal name segments across the field name, plain aliases, `validation_alias`/`serialization_alias`, every string segment of an `AliasPath`, and every alternative path of `AliasChoices`; this rejects `authorization/auth` context, permission scopes/matrices, roles/role IDs, and credential variants without rejecting ordinary business neighbours by incidental substring. Any `dict`/`Mapping`, including nested or list-contained mappings, and any schema that can export arbitrary-key `additionalProperties` fail closed before registration and export; input objects must instead use a finite, explicit Pydantic field contract. Model schemas omit handlers, internal role/permission matrices, and disabled capabilities; they recursively remove field-schema `default/example(s)` metadata and values while retaining legitimate `properties` names of `default`, `example`, and `examples`. Every discovery reloads the active account, effective roles, feature permissions, and published-profile capability-code/maximum-risk limits from the database; a profile can narrow by code and risk only, never create a handler or grant authority. Record data scope, state, ownership, and workflow assignment remain execution-time checks in future domain handlers, so discovery is never execution authorization. Model input, message persistence, and ordinary log summaries share deterministic recursive redaction with one credential-name classification for mapping keys and text assignments: case-insensitive sensitive keys, dynamic-form `sensitive=true` fields, Cookie/Authorization headers, Bearer/JWT values, and password/token/secret/API access/private-key assignments become `[REDACTED]`. This task does not implement provider calls, `/api/assistant` routers, UI, or business capability handlers.

WA0 Task 3 implements the provider-neutral `ModelProvider` contract, an OpenAI-compatible `/chat/completions` adapter, and `AssistantGateway`. `AI_PROVIDER_ALLOWED_HOSTS` must contain comma-separated exact hosts or explicit `*.controlled-suffix` entries; an empty allowlist fails closed. Base URLs require HTTPS and reject URL credentials, query, fragment, and path escape. Paths are decoded to stability within eight rounds and 2,048 characters; residual, cycling/ambiguous percent encoding and decoded separators, backslashes, or dot segments are rejected. DNS is resolved immediately before every real request, and loopback, private, link-local, multicast, unspecified, reserved, and metadata-class addresses are denied. Production DNS calls synchronous `socket.getaddrinfo` only through a dedicated bounded DNS/IO executor whose admission and wait consume the `ChatRequest` absolute deadline/remaining budget; it never uses `loop.getaddrinfo`, `asyncio.to_thread`, or the default executor. DNS saturation and timeout fail closed. Production then creates a request-specific connection pool that dials only the literal IP set validated for that request while retaining the original allowlisted host for HTTP origin/Host, TLS SNI, and certificate hostname verification. Environment proxies and redirects are disabled. Only `httpx.MockTransport` may be injected for tests; ordinary injected clients are rejected. `AI_PROVIDER_CONNECT_TIMEOUT_SECONDS` defaults to 5 and `AI_PROVIDER_READ_TIMEOUT_SECONDS` defaults to 60.

The current IDC deployment manifest sets `AI_PROVIDER_ALLOWED_HOSTS=dashscope.aliyuncs.com` for DashScope validation. This permits connections to that controlled host only; it does not store, read, or enable any API key. An administrator can enter an API key only on ITOM's model-provider page, where it is stored encrypted. Initial configuration and configuration or credential changes require a manual security probe; enabled providers with unchanged configuration are re-probed by the backend every 10 minutes within the 15-minute validity window, and a failed refresh disables the provider and records a redacted system-triggered audit fact. Changing provider still requires a matching allowlist update and backend redeployment.

`probe()` independently and exactly checks an authenticated basic response, a stream with valid `[DONE]` terminal semantics, one `tool_choice`-forced offered tool name with valid arguments, and JSON satisfying the requested strict schema's constant/required/no-additional-fields constraints. A provider that ignores a feature receives false for that feature only; authentication, connection, timeout, or upstream-service failure still fails the probe. L2/L3 require `supports_streaming`, `supports_tools`, and `supports_json_schema`, plus enabled, recent-success, same-policy primary/fallback status. Streaming accepts only validated SSE deltas, complete JSON-object tool arguments, usage, supported `stop/tool_calls` terminal reasons, and final `[DONE]`; receipt of `[DONE]` stops reading and closes the response immediately. Unknown events, malformed JSON, truncation, or missing terminal semantics fail closed. Fallback is forbidden after any primary output begins.

`ChatRequest.purpose` accepts only the server-owned `ProviderPurpose` enum and stores its canonical code within the 32-character column. Raw strings, unknown, oversized, or potentially secret-bearing purpose text are rejected before provider construction, egress, or audit. Each real attempt writes only provider, model, canonical purpose, tokens, latency, result code, status, and redacted error to `ai_provider_call`; prompts, response bodies, and secrets are never stored. Audits use independent `SessionLocal` transactions and never commit or roll back the caller session. Failure-audit persistence errors are contained without blocking safe fallback; cancellation-audit errors never mask cancellation; a success `done` event is emitted only after the audit commits, otherwise the gateway raises redacted `GATEWAY_AUDIT_FAILED` without claiming completion. Task 3 adds no admin API, `/api/assistant` router, UI, conversation/action orchestration, or business handler.

WA0 Task 4 implements the `/api/admin/ai` administration API. Every endpoint independently declares the real server-side `require_perm("admin_ai", ...)`; browser-supplied role claims never authorize it. Provider create, read, update, soft delete, and probe reuse Task 3's HTTPS, host allowlist, DNS address-class, and request-pinned transport checks. An unprobed or stale provider cannot be enabled. Provider type, URL, model, a nonblank replacement secret, timeout, output limit, temperature, or fallback change increments `config_revision` under the governance lock, invalidates the prior probe, and disables the provider; the revision neither hashes nor records plaintext secret material. `api_key` is accepted only on writes: a nonblank value is encrypted byte-for-byte, while an omitted or all-whitespace update preserves existing ciphertext. Responses expose `has_secret` only, never plaintext or ciphertext.

`POST /providers/{id}/test` reuses Task 3's exact authentication-basic → stream-terminal → forced-tool → strict-JSON-Schema sequence in three phases. Phase A is a short transaction that acquires the PostgreSQL transaction-scoped advisory lock dedicated to AI provider governance, refreshes and `FOR UPDATE`s provider rows in deterministic ID order, validates the target, snapshots its encrypted (never plaintext or hashed) configuration and `config_revision`, and commits. Phase B performs and closes the asynchronous network probe with no database transaction, advisory lock, or row lock. Phase C reacquires the same short-transaction locks and atomically persists `probe_status`, boolean capabilities, `last_probed_at`, and redacted audit only when the provider still exists and the revision matches. A changed/deleted configuration discards the old result and returns 409 `AI_PROVIDER_PROBE_STALE`; it never overwrites newer unverified/failed state. A genuine probe failure persists truthful failure and revokes enablement. Create, update, delete, both A/C probe transactions, and provider references applied by profile publish/rollback share this cross-pod lock. No synchronous lock spans an asynchronous network wait, while enablement, fallback cycles, single-primary promotion, and delete/reference checks remain revalidated under lock rather than an in-process mutex.

Profile codes are fixed to `requester`, `bdo`, `it_staff`, and `admin`, with server-fixed audiences `requester`, `bdo`, `it`, and `admin`. Draft updates carry an `expected_updated_at` optimistic token. Database content may select only capability codes already present in the process registry, and capability audience, risk, and knowledge scope cannot exceed server-owned audience allowlists. `name/default_provider_id/enabled/retention_days` plus prompts, capabilities, knowledge scope, and risk remain in the version=0 draft. Every new draft, publication, and rollback-copy `config_snapshot` has explicit `schema_version=1` plus all four active fields; PATCH never changes active `ai_agent_profile` fields. Publication carries `expected_draft_updated_at` and validates bilingual system instructions, non-L4 risk, registered capabilities, knowledge scope, an enabled recently healthy default provider, and tools/JSON-Schema compatibility for L2/L3. Only successful validation atomically applies active profile fields and inserts an immutable monotonically increasing `ai_agent_profile_version`. Runtime reuses that proof: complete snapshot, bilingual prompts, capability/risk limits, healthy compatible provider, newest version, and active-row agreement must all hold; `enabled_capabilities` and `knowledge_scope` must retain their raw valid-list shape, and a missing, `null`, or otherwise malformed value is never normalized to an empty list and fails closed. Rollback carries the source version and `expected_latest_version`, copies only a provably complete historical active-settings snapshot into a new published version, and atomically applies it without updating or deleting history. A pre-migration `{}`, missing marker, or incomplete source returns 409 `AI_PROFILE_LEGACY_SNAPSHOT_UNAVAILABLE`; active profile and all version bytes remain unchanged, and the server never guesses history from current active settings. Complete newer snapshots remain rollback-capable. Stale drafts or concurrent versions return 409; a rejected publish changes neither the active profile nor existing published bytes and creates no partial version.

`GET /health` returns provider/profile counts only. `GET /usage?days=N` uses database aggregates for calls, tokens, latency, provider, and result code; `days` defaults to 30 and accepts only 1–90, and the query does not load full call rows or message/error fields. `GET /action-audits` returns only action code, risk, status, result entity, and timestamps. None returns prompts, message bodies, full conversations, plaintext/ciphertext secrets, confirmation tokens/hashes, normalized payloads, result payloads, or provider error bodies.

WA0 Task 5 implements `GET /api/assistant/bootstrap`, `POST/GET /api/assistant/conversations`, `GET /api/assistant/conversations/{id}`, and `POST /api/assistant/conversations/{id}/archive` for the current login account. The fixed bootstrap allowlist is only `enabled`, profile code/version, `max_risk`, `suggested_prompts`, `retention_days`, and `fallback_available`; an unpublished, disabled, deleted, audience-incompatible, or runtime-unprovable profile returns `enabled=false` without exposing an internal reason, capability matrix, disabled capability, provider configuration, secret, or handler. `fallback_available` is true only when the existing authenticated `GET /api/it-document-guide` can safely produce its permission-aware `documents[].can_create/target_path` payload; it does not claim WA1 capability. In one transaction, creation first takes the same PostgreSQL governance advisory/provider-row locks as Task 4 publication/withdrawal, then in that order reloads and `FOR UPDATE` locks the target active profile, validates runtime state, inserts the conversation, and commits; SQLite preserves the same service-call and reload order for deterministic tests. Creation accepts only `language` and an extra-forbid `page_context`: route is a normalized local path, page/entity/tab are bounded safe identifiers, and `selected_ids` contains at most 20 unique GLIDs; roles, permissions, DOM/HTML, prompts, cookies, headers, external/protocol-relative/traversal-like paths, and all other fields receive 422. Create/list/get/archive all filter by authenticated database `auth_user_id`; an unowned conversation consistently returns `AI_CONVERSATION_NOT_FOUND` 404 and leaks neither total, detail, nor archive state. Listings default to active owner conversations; `include_archived=true` returns only that owner's archived rows, with stable `created_at DESC, id DESC` pagination; `page` is limited to 1–10,000 (`page_size` remains 1–200). Ordinary-message retention is read only from the complete schema-marked captured version, never from the live profile or `expires_at`: a captured zero never writes a body after a later positive publication; a captured 1–90-day decision and creation-time `expires_at` remain immutable, while new bodies stop if the current profile becomes disabled, deleted, unpublished, audience-incompatible, or runtime-invalid. Every persisted message is recursively redacted. Archive now `FOR UPDATE + populate_existing` locks and refreshes the owned conversation row before setting `archived_at/status`, and still never deletes `ai_action` or security/business audit. SQLite covers deterministic barriers using real Task 4 publication/withdrawal and the post-lock reload contract; this round did not run PostgreSQL two-session row-lock contention. Task 9 IDC acceptance must run that two-session barrier between creation/ordinary-message persistence and real publication/withdrawal, including 0→positive and positive→0 retention results. Task 5 adds no message SSE, tool loop, L3 action, domain handler, UI, deployment, or WA1 work.

WA0 Task 6 implements `prepare_action(db, actor, conversation_id, capability_code, payload, idempotency_key)`, `confirm_action(...)`, and `cancel_action(...)`, plus `POST /api/assistant/actions/{id}/confirm` (body contains only `confirmation_token`) and `POST /api/assistant/actions/{id}/cancel`. Preparation resolves capability, risk, input model, and fixed handler from the registry; L3 registration requires callable `authorize_preview()`, `preview()`, and `authorize_record()`. Registered Pydantic rules such as `extra=forbid` reject client-supplied SLA, queue, role, handler, or final-state claims. If recursive redaction changes normalized input, preparation returns uniform `AI_ACTION_PAYLOAD_INVALID`, does not store or execute a substitute, does not hash the redacted form, and does not consume the idempotency key. Only unchanged safe normalized input receives the stable SHA-256. `AiAction` idempotency is account + capability + key, with the same SQLAlchemy/PostgreSQL name `uq_ai_action_user_capability_idempotency`. Same-key/same-digest returns the first state without another token, while a different digest returns 409. Race recovery catches only that named constraint, rolls back, row-locks/reloads the winner, and propagates any other `IntegrityError`. Preparation first opens an independent `SessionLocal` transaction and runs `authorize_preview()` before any record metadata can be returned; `preview()` must then return exact `status=prepared`. `authorize_preview()` and `preview()` receive only a preview-local actor context plus `ReadOnlyActionData`, which has no Session-like attributes, accepts only explicit bounded SQLAlchemy `Select` scalar projections, returns recursively frozen `FrozenActionRecord` snapshots, and rejects entity/relationship/eager results, every row lock, text/DML, excessive offsets, and over-limit reads. PostgreSQL executes `SET TRANSACTION READ ONLY` before handler access. The preview facade and dirty/new/deleted guard reject ORM/DML mutation, textual transaction statements, flush, commit, rollback, and transaction-object access. Success or failure rolls back and closes the preview transaction before action persistence begins. Preparation then follows two ordered paths: an existing key is first probed without a lock, then replay/race recovery locks `AiAction` first and the owned active conversation second before digest comparison; a brand-new action locks/revalidates the owned active conversation, rechecks the same key without taking an action lock, and inserts only while it is still absent.

WA0 Task 7 adds `POST /api/assistant/conversations/{id}/messages` (SSE) and `AssistantOrchestrator.stream_turn()`. The request accepts only `content`, `client_message_id`, and Task 5's allowlisted `page_context`. This stream route uses a separate asynchronous scalar-auth dependency: a shared bounded DB worker creates/rolls back/closes its short Session and returns only an active account ID, so the `StreamingResponse` lifetime retains no request Session or ORM. Start/idempotency, capability discovery, native fallback, Gateway provider selection/audit, each tool, L3 preparation, final persistence, and failure cleanup use separate short Sessions. All synchronous SQLAlchemy I/O/lock waits execute in bounded workers whose Sessions are created/closed there; production assistant paths use neither `asyncio.to_thread` nor the default unbounded executor and do not block the async SSE loop. Saturation fails closed at its boundary; a successful provider call whose audit cannot be persisted does not emit a success terminal. `_TurnState` contains scalar snapshots only and never retains ORM across provider awaits. Event types are fixed to `meta|delta|message|action|error|done`; each `data` value is one-line JSON. Headers are `Cache-Control: no-store, private`, `Vary: Authorization`, and `X-Accel-Buffering: no`. A normal path has exactly one `done`, and no success event may follow `error`.

Platform security instruction, immutable published profile, per-call authorized capability schemas, and explicitly untrusted knowledge/business/page-context/user bodies remain separate layers; browser-claimed role, permission, and tool result never become authority. The semantic form applies Unicode NFKC/casefold while preserving useful boundaries. The compact form first admits only original `L*`/`N*` code points and removes named/explicit Hangul `FILLER` values, then applies NFKC/casefold and repeats the `L*`/`N*` filter. Original `M*`/`C*`/`Z*`/`P*`/`S*`, zero-width, and compatibility-decomposing symbols cannot be washed into letters before matching, while legitimate full-width letters/digits still normalize. WA0 does not promise perfect detection of all visually confusable differently encoded characters. Complete normalized lines of at least 12 characters, strong fragments of at least 24 characters, or two distinct 12–23-character fragments fail closed; empty and short common terms do not participate, and the output budget bounds work. Every tool call resolves a fixed registry code and re-authorizes through the registered Pydantic input model. Model-supplied handler/risk/role/result, unknown or disabled code, invalid arguments, equal repeated calls, and more than four rounds fail closed. L1/L2 handlers receive no SQLAlchemy Session, ORM `AuthUser`, Connection, or Engine; they receive Task 6 `ReadOnlyActionData`, immutable `ActionActorContext`, and a cooperative `CapabilityExecutionContext` only. A dedicated bounded executor accepts 1–32 workers and 0–256 queued calls. Each tool call reserves capacity before capability discovery/reauthorization; saturation causes no permission query, Session creation, or handler call, and all validation/L3/error paths release the permit. `stream_turn()` creates one monotonic absolute deadline: fallback, start/idempotency, Gateway/provider, every DB/tool call, and all finalization pre-commit work share its remaining budget. A work deadline reserves at most 250ms (25% of the turn budget) for failed-placeholder cleanup. Total tool deadline is restricted to 0.1–60 seconds; PostgreSQL `statement_timeout` is 10–59,000 ms and must be strictly shorter. Actual tool/provider/statement timeouts take the smaller of their own cap and remaining turn time. Authority commit must begin before the deadline after final locks and one last cancellation check. Once it begins, the caller waits for commit and Session cleanup to preserve durable `completed` versus client-terminal consistency, which may slightly exceed the deadline instead of reporting timeout after a successful commit. PostgreSQL executes `SET TRANSACTION READ ONLY` before any read, then the tool Session always rolls back/closes. The facade denies commit/flush/rollback/add/delete/merge/query/raw SQL/Core DML/ORM mutation. Disconnect/deadline makes the event loop stop waiting immediately, emits no more events, and signals cooperative cancellation. A synchronous Python thread cannot be safely force-killed: a non-cooperative block may continue in the background until it returns, but its Session still closes; hard termination would require process isolation. Gateway cancellation audit is nonblocking bounded best effort in the DB executor: saturation creates no Session, failures produce redacted local warnings, and cancellation propagates immediately. Normal success and handled-error paths still await durable audit before exposing output. L3 may finish as `prepared` until expiry but can never execute a mutation. Event, text, token, tool, and all pre-commit time are constrained by the one absolute budget; stage budgets are never summed and misreported as a hard bound for the entire return path.

Task 7A separates thread-safe commit-started state from durable commit success. Durable success is set only after `db.commit()` returns successfully. A later Session-close exception records only a redacted exception type, never re-queries the database to guess transaction outcome, and does not enter the safe-error SSE branch; a connected client keeps the established `meta → delta/action → message → done` order. If disconnect is observed after commit has started, cancellation wins and no later SSE terminal is emitted even when cleanup also fails. A failing `db.commit()` sets no durable success, rolls back, runs failed-placeholder cleanup, and emits safe `error → done`.

During streaming, L3 may call Task 6 `prepare_action()` only and emit server action ID, risk, preview, one-time confirmation token, and expiry; it never confirms or executes. Its final message is server-rendered as `authority=server_preview, operation_status=prepared_not_executed`, and model success prose is discarded. Without a committed server result, normal model prose is persisted only as non-authoritative `authority=advisory, operation_status=not_executed`; it is not an ITOM success or status result. Provider outage, timeout, malformed/truncated protocol, illegal tool output, or disconnect stops waiting and returns a uniform non-leaking error. The deterministic native fallback is the first current-account `can_create` target computed by `it_document_guide.guide_payload()`, or `/` when none is authorized. Connectivity is rechecked after `_run_turn`; finalization then uses a worker-owned short transaction and fixed account/conversation/profile/placeholder lock order, checking cooperative cancellation after all locks and again before writing/committing `completed`. An observed disconnect rolls back. This guard does not claim zero real-socket/thread-scheduling race or force-kill a worker. Archive, account disablement, profile withdrawal/replacement, missing placeholder, or status conflict fails closed with no success message/done. Only a redacted final message may persist under captured retention; partial deltas, provider errors, and secrets never become completed answers, while retention zero stores bodyless idempotency metadata. `request_digest` is a server-key HMAC over normalized raw `content + page_context`; an equal raw request safely replays the same `client_message_id`, while a raw mismatch conflicts even if redaction produces the same body. SQLite automation verifies query order, lock markers, and cooperative cancellation guards; real PostgreSQL lock waits and real ASGI disconnect remain Task 9 evidence.

Authentication/request-schema/routing failures before endpoint acceptance still use ordinary HTTP errors such as 401/403/422. Once accepted and streaming starts, owner, idempotency, and runtime failures remain HTTP 200 and are expressed as SSE `error→done`, rather than switching to HTTP 404/409. Real PostgreSQL two-Session evidence for same-key single message group/single provider call, read-only rejection and lock waits, plus real ASGI disconnect evidence, is explicitly deferred to Task 9; local SQLite/ASGI automation is not that evidence.

Confirm/cancel query only the authenticated owner's `AiAction` under `FOR UPDATE`; another user's ID gets the same 404. After verifying `prepared`, ten-minute expiry, and token SHA-256, confirmation first `FOR UPDATE + populate_existing` locks and refreshes the owned active conversation; if archive won first, confirmation fails closed before any runtime governance lock and persists bounded `failed` on the same action row. Only then does one outer transaction follow the Task 4 PostgreSQL advisory → provider-row → profile-row governance order. Task 5 `_active_profile(..., lock_runtime_profile=True)` plus complete `runtime_published_profile()` proof must show that the conversation-bound profile/version remains the active newest publication and that snapshot, bilingual prompts, capability/risk/knowledge limits, active-row agreement, and default-provider enablement/recent health/tools-plus-JSON-Schema compatibility all remain valid. It then reloads database account, direct/group role permission, and registered capability. The fixed handler's `authorize_record()` and mutation receive only `ActionUnitOfWork.lock_one()/update_locked()`, immutable `FrozenActionRecord` snapshots, and an opaque `LockedActionRecord` that keeps real ORM identity module-private; the supported interface exposes no raw commit/rollback/begin/get_transaction/connection/bind surface or unrestricted generic table write path. A handler executes only inside the caller transaction and cannot commit, roll back, or flush independently. The domain handler, valid `CapabilityResult(status="succeeded")`, action state/entity, and generic `audit_log` run inside a nested savepoint; the outer transaction commits them once after complete success. A handler or success-audit exception rolls back only that savepoint and retains the action row lock. The same locked row is then committed as bounded redacted `failed`, so a waiting confirmer observes terminal failure and never re-enters the handler. If failure-state persistence/commit fails, the outer transaction rolls back and surfaces `AI_ACTION_FAILURE_PERSISTENCE_FAILED`; no durable terminal state is claimed. A wrong token leaves `prepared` for a legitimate owner retry. Cancelled, expired, succeeded, or failed actions cannot be confirmed again. Raw token, sensitive normalized payload, provider secret, handler exception, and credential assignments returned in a success result never enter durable result, logs, audit, or error text. Handler code is trusted in-process extension code, not a hostile-code sandbox; the supported interface only guarantees no normal Session escape. Task 6 adds no message SSE/tool loop, concrete business capability, UI, deployment, or WA1. SQLite automation proves only service/guard/lock order, archive-vs-prepare/archive-vs-confirm ordering, rollback outcomes, named-race injection, and savepoint semantics; it is not PostgreSQL runtime proof. Task 9 IDC must preserve real two-Session PostgreSQL evidence for read-only preview and rejected writes, same/different-payload prepare races with one winner and no 500/token reissue, archive-vs-prepare/archive-vs-confirm ordering, handler/audit confirmation failure with the waiter seeing `failed` and exactly one handler call, and failure-state commit faults never being reported as durable.

Fix Round 4 further fixes the handler data-port contract. `ReadOnlyActionData` recursively allowlists the complete SQLAlchemy AST and accepts only explicit direct scalar columns from one direct mapped table, same-table safe comparison/boolean predicates and ordering, and compile-time nonnegative limit/offset within server bounds. Nested selects/CTEs/row locks at any depth, joins/aliases, entities/relationships, aggregates/windows/functions, text/raw SQL, cross-table references, and dynamic/negative/excessive pagination are rejected; execution still fetches at most max + 1 rows to detect overflow. A `LockedActionRecord` is bound through module-private state to its issuing UoW token, Session, outer transaction, and current savepoint identity. `update_locked()` accepts only an unconsumed real locked handle in that exact live scope and originally selected non-primary-key scalar fields, consumes it on success, and returns a replacement handle with a merged snapshot. Forged, cross-UoW even on the same Session, cross-Session/outer-transaction/savepoint, terminal-transaction, and repeated handles fail closed.

Fix Round 5 closes SQLAlchemy raw query modifiers. Before any SQL execution, `_projection_metadata()` uniformly returns the port violation whenever `_prefixes`, `_suffixes`, `_statement_hints`, or `_hints` is nonempty; modifier strings are neither parsed nor allowlisted. Consequently `prefix_with()`, `suffix_with()`, `with_statement_hint()`, and `with_hint()` cannot inject `FOR UPDATE`, a large offset, `DISTINCT`, or other dialect SQL. `ReadOnlyActionData` and `ActionUnitOfWork.lock_one()`, which share this validator, apply the same fail-closed contract.

WA0 Task 8 adds only the frontend consumption layer and does not change the backend contracts above. `frontend/src/api/assistant.ts` uses native `fetch` for POST-SSE with the Bearer token and `X-Lang`, then fails closed through bounded frame/buffer sizes, an exact event allowlist, one-object JSON, and complete terminal validation; 401 reuses the existing logout/login redirect. Page context comes from an explicit route table plus bounded tab/GLID parameters; unknown paths fall back to `/`, and DOM, HTML, forms, cookies, storage, and URL credentials are never read. The business portal and internal workbench mount the same global drawer. Messages, previews, and audit values render only as React text with no raw HTML. L3 cards call only Task 6 confirm/cancel APIs, prevent duplicate clicks, expire on the server deadline, and treat only a confirmation response with `status=succeeded` as authoritative success. `/admin/ai-assistant` exposes a five-tab console behind the `admin_ai:view` route/menu guard; edit/delete controls also check their frontend actions, while each backend endpoint's `require_perm` remains the final authority. Provider forms never read or prefill a secret and write one only when the user enters a nonblank replacement. This task adds no backend route, model, migration, configuration, or concrete domain capability.

Independent Task 8B makes the SSE consumer state machine and L3 credential projection explicit. A valid error stream is exactly `error → done(error)` or `meta → error → done(error)`. The client fails closed if delta/action/message precedes the error, `done(error)` contains success data, a nonmatching event follows the error, or anything follows a terminal. A replay is exactly `meta → message → done(replay)` and its message may be `advisory/not_executed` or `server_preview/prepared_not_executed`. The preview form replays safe explanatory text only, must have no action/delta/confirmation token, and never creates an actionable card. The first L3 prepare action event no longer sends its full object through generic `redact_for_message()`. A dedicated server projection emits only a generically redacted `preview` plus exact `action_id`, `risk=L3`, raw one-time `confirmation_token`, and `expires_at`; missing, oversized, wrong-risk, or `[REDACTED]` token values are rejected before emission. This exception is limited to the owner-scoped action SSE transport. Generic redaction remains unchanged, only SHA-256 is stored, and the credential enters no message, persisted body/result, log, audit, provider/model, or confirmation REST response. Confirm continues to enforce owner, prepared state, expiry, SHA-256, and one-time consumption; replay, repeat, cross-owner, expired, cancelled, redacted-placeholder, and malformed credentials cannot execute a handler.

Task 8C fixes the WA0 action wire contract and execution claim. `confirmation_expires_at` and action-SSE `expires_at` are RFC 3339 UTC strings with `Z`; the client accepts only that form and rejects offset-free or malformed expiry. `server_preview.action_id` uses the same ULID grammar in live action and replay completed-message paths, so invalid replay does not render. The confirm API completes owner, token, expiry, and runtime proof, then commits a durable `executing` claim before the handler. Only a successful claim may run the handler. The success transaction still atomically writes domain mutation, `succeeded`, and audit; a known failure can persist `failed`, while any uncertain post-claim handler/final persistence result responds `AI_ACTION_OUTCOME_UNKNOWN` and keeps the action non-confirmable rather than exposing success or a new confirmation/cancellation path. This task adds no route, migration, Aily/MCP change, or IDC acceptance conclusion.

Round 1 tightens a live action SSE: when it carries a valid raw `confirmation_token`, a usable `confirmation_expires_at`/`expires_at` must be present, non-`null`, parseable RFC 3339 UTC with `Z`; otherwise the stream validator fails closed with `AI_ASSISTANT_STREAM_PAYLOAD` before delivering the action to presentation. A tokenless action may remain informational but cannot become `prepared` through missing expiry. From confirm response to card, `AI_ACTION_OUTCOME_UNKNOWN` maps to `executing` and carries no displayed success conclusion.

### 4.2 ITSM

```text
GET/POST /api/tickets | GET /api/tickets/export | GET/PATCH /api/tickets/{id}
POST /api/tickets/{id}/transition        # includes approval (approve/reject), resolve, close, hold, reopen
POST /api/tickets/{id}/satisfaction      # requester rating
POST /api/tickets/{id}/escalate-problem  # one-click escalation to a problem
POST /api/tickets/{id}/to-knowledge      # one-click knowledge capture (draft)
GET/POST/PATCH /api/problems | POST /api/problems/{id}/transition
GET/POST/PATCH /api/catalogs | /api/service-items. The catalog list returns `item_count` plus `published_item_count` and `unpublished_item_count`; the service-item GET endpoint accepts `catalog_id`, `q` (code/name/type/audience/owner keyword), `status` (published/unpublished; omitted means all), `sort_by`, and `sort_dir` for list filtering and sorting.
GET /api/service-items/{id}/form                # P1 active form visible to the requester
GET/POST /api/service-items/{id}/form-versions | POST /api/service-items/{id}/form-versions/{version}/publish   # P1
GET/PUT /api/service-items/{id}/dispatch-rule  # P1 item rule; runtime also resolves catalog/global fallback
GET/PUT/DELETE /api/service-items/{id}/implementation-dispatch-rule  # M93 service-item implementation-delivery rule; GET can identify catalog/global inheritance
GET/PUT/DELETE /api/catalogs/{id}/implementation-dispatch-rule       # M93 catalog implementation-delivery fallback
GET/PUT/DELETE /api/service-dispatch/implementation-fallback         # M93 global implementation-delivery fallback, admin/CIO only
POST /api/tickets/{id}/accept                  # target; actual acceptance timestamp and response SLA
POST /api/tickets/{id}/confirm-resolution      # target; requester close or reopen, shared by web and MCP
POST /api/integrations/feishu/card-actions     # P2.1; signed Feishu callback, no ITOM Bearer token
GET/POST/PATCH /api/cis | GET /api/cis/{id}/impact          # impact analysis (upstream/downstream + linked tickets)
GET /api/itsm-import/ci/template | POST /api/itsm-import/ci # CMDB Excel template and row-by-row append import
GET/POST/DELETE /api/ci-relationships
GET/PUT /api/admin/sla-policies | GET /api/sla/dashboard     # live attainment rate
GET/POST/PATCH /api/vendors | /api/contracts
GET/POST/PATCH /api/knowledge | POST /api/knowledge/{id}/vote
GET /api/knowledge/search?q=
```

`GET /api/tickets/export` accepts the same filters and data scope as the ticket list and exports **all** matching records in the current authorized scope, not just the current page. Its default sort matches the list.

### 4.3 Project

```text
GET/POST/PATCH /api/portfolios
GET/POST/PATCH /api/projects | POST /api/projects/{id}/transition
POST /api/projects/import-charter        # .docx parse → draft preview → confirm and persist (two steps)
GET/POST/PATCH/DELETE /api/projects/{id}/wbs | /milestones | /risks | /costs
POST /api/wbs/{task_id}/move             # {parent_task_id?, before_task_id?}; only an unstarted subtree may change hierarchy or sibling order
GET /api/projects/{id}/gantt             # Gantt data (tasks + dependencies + milestones)
```

### 4.4 Requirement

```text
GET/POST /api/requirements | GET/PATCH /api/requirements/{id}
GET /api/requirements/template | POST /api/requirements/import
POST /api/requirements/{id}/transition   # Registration→Analysis→Implementation→Closure/On-Hold/Cancelled, carrying stage fields
POST /api/requirements/{id}/to-dev       # {}; fixed Requirement Scoring Rules dev_leader and an in-house-dev route snapshot
POST /api/requirements/{id}/to-project   # {pm_id}; persists a project-route snapshot
GET/POST/PATCH /api/requirements/{id}/tasks
POST /api/requirements/{id}/close        # validate all acceptance criteria checked → may carry {legacy_problem, knowledge_draft}
# P1: Aily/MCP keeps BDO requirement scope owner-only; the authenticated ITOM web module additionally permits requirements in domains where the person is configured as business BDO; no second requirement entity
```

### 4.5 Process

```text
GET/POST/PATCH /api/admin/process-definitions (nested steps with stable step_code; a used version may maintain only cc_roles in place for future node activations, while node/RACI/SLA changes require a new version)
GET /api/process-instances?entity= | GET /api/process-monitor   # stuck/overdue aggregation
POST /api/process-tasks/{id}/complete
GET /api/process-tasks/{id}/reassign-candidates
POST /api/process-tasks/{id}/reassign       # {assignee, reason?}
POST /api/process-tasks/{id}/view       # current handler records first detail view; idempotently returns viewed_at/viewed_by
```

Requirement template contract: `GET /requirements/template` exports registration fields only. `POST /requirements/import` detects the new registration template or the legacy scored template by headers. The new template cannot write scores, decisions, PRD/development effort, or channel department; legacy templates remain import-compatible with row-level errors.

Process-detail contract: `process.current_step_seq/current_step_code/current_step_name` is derived directly from the newest pending `ProcessTask`, and each step returns its newest non-deleted task. The business stage is a forward-only compatibility projection. After implementation/acceptance, scoring returns `EVAL_STAGE_CLOSED`; an old status or historical score cannot bypass the workflow.

The stable display order for process definitions is ITSM (Service Request) → ITSM (Change) → ITSM (Incident) → ITSM (Problem) → Project → Requirement → Bug Management. The backend normalizes ordering by trigger entity and the UI keeps the same grouping order as the left navigation; it must not depend on database row order.

Workflow-record detail and list rows return `can_edit`, `can_delete`, `workflow_edit_mode`, and `workflow_edit_locked_reason` only as UI capability hints; `PATCH/DELETE` re-run domain workflow authorization. The current handler's first view is persisted by `POST /api/process-tasks/{id}/view`, complete, approve, or reject; list/notification reads do not call this endpoint. An administrator's passive detail inspection and administrator reassignment create no view fact; reassignment only changes `assignee`. Before downstream first view, the first-node creator may edit/delete and a later node's actual previous completer may edit only. A correction carrying routing fields returns `WORKFLOW_CORRECTION_FIELD_FORBIDDEN`; an unavailable window returns `WORKFLOW_EDIT_LOCKED` or `WORKFLOW_DELETE_LOCKED`. New tasks enable the window by default, while pending tasks that existed before the database upgrade remain disabled so no historical permission is broadened retroactively.

Current-task reassignment is a generic workflow capability rather than a record-type transition. The current pending handler or administrator may first read candidates and then select another active, in-position organization member with an active, non-deleted ITOM account. The server rechecks task status, operator, and target at write time. A successful reassignment preserves node, business state, due time, RACI snapshot, and history, audits old/new handler plus the optional reason, and notifies the new handler through the existing notification/outbox path.

Requirement list/detail/attachment/relation reads share one web data-scope policy: business users see own records; a BDO additionally sees every requirement whose business domain points to that person's `business_bdo_id`; IT-authorized roles retain their existing scope. `scope=mine` always narrows to the requester. This web policy never expands Aily/MCP owner-only requirement tools. Requirement Development, Project Development, and Bug list responses also return a readable registrar name derived from the stored registrar, project manager, or Bug reporter according to the creation source.

### 4.6 Team

```text
GET /api/team/overview                   # all active IT-member workload (project tasks = open WBS + open Project Development; web local 20-row pagination) / points Top / training count / hiring progress aggregation
GET/POST/PATCH /api/positions | /api/hiring-needs; Excel template/export/import endpoints are also available at `/api/positions/{template,export,import}` and `/api/hiring-needs/{template,export,import}`.
GET/POST/PATCH/DELETE /api/trainings     # training activities; PATCH/DELETE only admin/CIO/registrar
GET/PUT /api/team-charter
GET/POST /api/ideas | POST /api/ideas/{id}/like | /adopt | /to-requirement
GET /api/points/leaderboard?period= | GET /api/points/mine | GET /api/points/entries?person=
GET /api/point-rules                    # Activity Points team-contribution event rules (ideas.view)
GET /api/point-rules/team-config         # Activity Points dimension weights/targets/satisfaction mix
PUT /api/point-rules/team-config         # save team-contribution configuration (admin/CIO)
GET/PATCH /api/admin/point-rules         # legacy team-contribution endpoint (admin/CIO; role_result rejected)
# legacy PATCH /api/point-rules/{code} remains for compatibility but also requires the admin/CIO role
GET /api/team/performance/overview?period=YYYY-Qn|All  # current matrix-role performance overview (role result 80% + team contribution 20%)
# GET /api/team/performance remains for legacy clients and is not the current overview data source
POST /api/points/adjust                  # admin manual point adjustment (remark required)
GET/POST/PATCH /api/admin/performance/role-profiles
PUT /api/admin/performance/role-profiles/{id}/dimensions
GET/PUT /api/admin/performance/assignments?period=YYYY-Qn
GET /api/admin/performance/reviews?period=YYYY-Qn
PUT /api/admin/performance/reviews/{assignment_id}/components/{dimension_code}
GET/POST/PATCH /api/admin/performance/external-inputs
GET /api/admin/performance/external-inputs?period=YYYY-Qn
POST /api/admin/performance/{period}/recompute
POST /api/admin/performance/{period}/submit-manager-review
POST /api/admin/performance/{period}/submit-cio-review
POST /api/admin/performance/{period}/publish
POST /api/admin/performance/{period}/unlock
GET /api/my/performance?period=YYYY-Qn
GET/POST/PATCH/DELETE /api/team/learning-growth?period=YYYY-Qn&scope=mine|team
GET/PUT /api/admin/performance/contribution-rules # legacy compatibility endpoint; canonical team config is /api/point-rules/team-config
```

`POST/PATCH /api/trainings` accepts `participant_ids` plus optional `participant_department_ids`. The latter represents full-department attendance: the server validates the department and its currently active IT-team members, expands and freezes `participant_ids`, and stores a department ID, display name, and attendee-scope snapshot. Omitting the field on `PATCH` preserves the existing snapshot for old-client compatibility; an explicit `[]` clears the department-display semantics but does not remove the supplied people. `GET /api/trainings` returns `participant_ids`, compatibility field `participant_names`, list-summary fields `participant_departments` / `participant_individual_names`, and `can_manage` for the current account. Creation writes `created_by`; migration backfills it from the earliest `development_activity.create` audit record. `PATCH` and `DELETE` are record-scoped rather than generic activity-edit operations: only administrator, CIO, or registrar may act, with server-side rechecks. A host/participant change soft-deletes the activity's current-period `training_host` / `training_attend` entries and re-awards from current rules; deletion retracts those entries. Point-affecting edits and deletion in historical, published, or locked periods return `TRAINING_POINTS_LOCKED`; non-point metadata remains editable and audited.

The `points` value from `/api/points/leaderboard` aggregates `contribution_bucket=team_contribution` entries for the period. In the current assessment period, automatic activity events resolve against the current effective `point_rule`, and a disabled rule displays zero; other entries retain their original algebraic value. `/api/points/mine`, the Team Overview leaderboard, and the Dashboard people-points ranking use the same current-period semantics, and the response may include a `breakdown` grouped by `source_type`. Original `point_entry.points`, historical periods, and published/locked performance are never rewritten. `role_result` rows remain in the ledger for role scoring and audit but are excluded from Activity Points reads. This is distinct from the role/target/weight-normalized result shown by Performance.

### 4.7 Dashboard

```text
GET /api/dashboard    # a single endpoint returning all data for the four panels + alert area (one aggregation)
```

When the account has task-module view permission, the response also contains a read-only `task` aggregate with `open_total`, `open_bugs`, `open_bug_fix_tasks`, `open_delegated_tasks`, and `open_requirement_tasks`. These are live counts of non-terminal tasks and do not change existing Dashboard fields.

## 5. Domain Event List

Events are published by the service layer within the transaction; `→points` means it triggers point_engine scoring (the point value is looked up in point_rule), and `→notify` means it writes to the outbox.

| event_type | Trigger | Subscription |
| --- | --- | --- |
| ticket.created | Ticket created | →notify (assignee/it_ops), →process (create instance) |
| ticket.assigned | Assigned/reassigned | →notify |
| ticket.accepted | Service request first enters processing | →Aily outbox (submitter) |
| ticket.resolved | Resolved | →points (ticket resolved), →notify (submitter) |
| ticket.user_confirmed / ticket.reopened | Requester confirms / rejects resolution | →audit, →notify (handler) |
| ticket.closed | Closed | →points (bonus when both SLAs met) |
| ticket.satisfaction_saved | Rating created or updated | →Aily outbox (submitter) |
| ticket.satisfaction_rated | Rated ≥ 4 stars | →points |
| ticket.sla_warning | Over 80% of SLA (scheduled scan) | →notify (escalation) |
| change.approval_requested / approved / rejected | Change approval | →notify |
| problem.root_cause_found | Root cause identified (root_cause filled in) | →points |
| contract.expiring | 90 days before expiry (scheduled scan) | →notify |
| wbs_task.completed_on_time | Task completed on time | →points |
| milestone.achieved / overdue | Milestone achieved/overdue (scheduled scan) | →points / →notify |
| requirement.stage_changed | Four-stage transition | →notify |
| requirement.task_completed | Requirement task completed | →points |
| requirement.closed | Requirement closed | →points |
| bug.registered / confirmed | Bug registered / product-manager confirmation | →notify, →process |
| bug.fix_tasks_created | Bug development/test child tasks generated | →notify |
| bug.ready_for_verification | All Bug child tasks closed | →notify, →process |
| bug.reopened / closed | Bug verification rejected/reopened or verified closed | →audit, →notify, →points (future metric) |
| work_task.created / closed | Delegated task registered/closed | →notify, →points (future metric) |
| knowledge.published | Published | →points |
| knowledge.voted | Marked helpful | →points (author) |
| activity.registered | Training registered | →points (presenter/organizer/participant scored separately) |
| idea.submitted / liked / adopted | Suggestion | →points; adopted→notify (submitter) |
| performance.review_submitted | Manager/CIO review submitted | →notify (next stage), →audit |
| performance.published / unlocked | Performance published/new version created | →notify (evaluated employee), →audit |

Scheduled tasks cover SLA, contracts, milestones, one reminder at 80% of the requester-confirmation window, and Aily outbox delivery/exponential retry; the Helpdesk scanner is removed. P2 sends immediately on entry to pending confirmation, while `confirmation_due_at` comes from the final requester task SLA. Each post-reopen confirmation cycle uses its own reminder idempotency key.

## 6. Key Implementation Mechanisms

1. **State machine**: `services/workflow.py` single entry point `transition(entity, to, fields, actor)` — look up workflow_transition to validate role and legality → validate the required staged fields for that transition → update + stamp → publish the event → write the audit. Shared by all records.
2. **Point-engine idempotency**: point_entry has UNIQUE(event_type, source_entity_type, source_entity_id, person), so the same record + same event does not score twice (reopening and re-resolving does not double-score).
3. **Computed-column maintenance**: after a wbs_task/cost_entry/milestone write, the service layer recomputes the owning project's progress_pct/actual_cost/health_status and writes them back (same transaction). WBS `progress` accepts an integer percentage from 0–100. Process steps use `node_type=processing|approval` to distinguish handling and approval semantics. Approval tasks expose `POST /api/process-tasks/{id}/approve` (optional comment) and `POST /api/process-tasks/{id}/reject` (required reason). Requirement rejection additionally accepts `target_seq`, which must be a reached prior target returned by the instance detail; omission chooses the nearest prior node and `0` means Requester supplement. Non-requirement entities retain their existing terminal or specialized return semantics. The flow-diagram complete-step entry remains supported.
4. **Two-step charter import**: the parse endpoint only returns a draft JSON + warnings (no persistence); the front end shows a confirmation page, and after the user corrects it, the create endpoint persists it. A parse failure falls back to the manual form.
5. **SLA timing**: on-hold time accumulates into paused_minutes; the attainment check = (resolved_at − submitted_at − paused) ≤ target.
6. **Matrix-role performance review**: the system first generates reference scores from ITSM, requirements, projects, processes, and points events. Business-line leads can write only business-role proposals; professional-line leads can write only professional-role proposals; platform roles and leaders' own scores are entered directly by the CIO. The backend enforces `performance_role_assignment.review_scope`; UI hiding is not an authorization boundary.
7. **External-input and publication isolation**: external business satisfaction is stored in `performance_external_input` and must be submitted, verified, and locked before it affects scoring. `performance_score_component` keeps reference, stage proposal, and effective values separately. `/api/my/performance` returns published snapshots only.
8. **Point buckets**: `point_rule`/`point_entry` use `contribution_bucket=role_result|team_contribution` to separate role outcomes from the fixed 20% team-contribution score. A fact already used by a role metric cannot enter team contribution again. Activity Points read APIs aggregate only `team_contribution`.
9. **MCP boundary (implemented in P1)**: tools call domain services only. `x-aily-jwt` passes allowlist and `external_identity` mapping before creating request-scoped `AuthUser` context. Prompts are never the sole business validator.
10. **Confirmation/idempotency (implemented in P1)**: preview stores `mcp_operation_intent`; submission validates token hash, user, tool, expiry, and idempotency key. Payload digest prevents key reuse with different content; retries return the first result.
11. **Form snapshots (implemented in P1)**: published versions are immutable; ticket creation stores version, answers, and schema. Person/department choices are revalidated at submit time.
12. **Dispatch (P1, M93 extension)**: ticket creation still resolves the acceptance rule through service item → catalog default → global fallback. At the first service-request acceptance completion only, the current handler (or an administrator) may select `implementation_mode=self|member|auto`; a named assignee must be an enabled IT member with an active account. `auto` resolves the independent implementation-delivery rule through service item → catalog fallback → global fallback. Round-robin selects only enabled, active members with an active account. `manual_queue` intentionally creates an unassigned implementation task for an eligible next-step user to claim; only no matched implementation rule falls back to that workflow step's default role. ITOM records the selected target, selector, timestamp, source, and rule. Aily/MCP never accepts implementation selection, and no dispatch choice bypasses workflow authorization, RBAC, audit, or idempotency.

## 7. Deployment Architecture

```yaml
# Default delivery path
GitHub Actions:
  backend:   Python 3.12 + temporary SQLite, complete pytest
  frontend:  Node.js 22, npm ci + TypeScript + Vite production build
  contract:  deployment YAML/script/diff checks + bilingual documentation guard
Harbor:
  backend:   git-<commit>-linux-amd64
  frontend:  git-<commit>-linux-amd64
IDC Kubernetes:
  db:        PostgreSQL 16 + persistent volume
  backend:   uvicorn, incremental migration + idempotent seed on startup
  frontend:  nginx serving the build output and proxying /api and /mcp; two replicas limited to nodes 01/02 and required to span hosts
```

- Environment variables: `DATABASE_URL`, `JWT_SECRET`, `ADMIN_INIT_PASSWORD`, `TZ=Asia/Shanghai`.
- IDC Kubernetes is the sole runtime, integration, and acceptance environment. Starting a local application stack, database, Compose, port 8180, or ngrok is prohibited by default. It is allowed only for an explicitly requested isolated investigation and never counts as delivery acceptance.
- `.github/workflows/quality-gate.yml` runs the complete backend regression, frontend production build, deployment-file checks, and bilingual documentation guard for pushes and pull requests on feature/develop/main. Test fixtures use temporary SQLite and never the IDC business database.
- Before commit, `scripts/change-scope.sh` fail-safely classifies changes relative to an explicit base as `none|docs|backend|frontend|all`; `scripts/fast-check.sh` runs the applicable pytest, frontend contract tests, and production build. Shared or unknown paths become `all`, and this fast feedback never replaces GitHub Actions or IDC acceptance. After a green gate, `deploy/k8s/push-images.sh` accepts only a clean commit and defaults to `BUILD_SCOPE=all`; a reviewed release may explicitly build and push only backend or frontend. Builds retain pinned base digests and linux/amd64 verification. PostgreSQL mirroring now runs only with `MIRROR_POSTGRES=1`, rather than on every application release.
- Every coding task must confirm a `production-fix|feature-local|code-candidate` route before modification and create a local lifecycle record through `scripts/task-lifecycle.py --track`. `production-fix` defaults to real IDC fault evidence without a local application runtime; `feature-local` may use the repository-defined isolated Docker stack and test database to reach `local_candidate_ready`, but production data, credentials, Secrets, OAuth/Aily applications, and callbacks are forbidden locally; `code-candidate` starts no application runtime and cannot enter IDC states. Focused real-target acceptance gates formal documentation and commit, and a second failure of the same target requires root-cause review. Every IDC write also requires a separate post-CI presentation of the commit, immutable tag, affected objects, database impact, disruption, rollback, and acceptance method, followed by explicit user authorization recorded through `approve-idc`.
- `deploy/k8s/k8s-deploy.sh` defaults to a full same-tag deployment while preserving existing Secrets, PVCs, database, uploads, and Feishu configuration. `DEPLOY_SCOPE=backend|frontend` requires `SKIP_DATABASE=1`; it does not apply the Namespace, Secrets, Ingress, PostgreSQL, or the unselected Deployment, and updates and verifies only the selected component. Shared-manifest or schema changes must not use component scope. Full and component releases retain strict rollout, Ready Endpoint, image identity, every frontend endpoint's backend proxy, external `/api/health`, and MCP `initialize` checks. Existing scheduling, anti-affinity, RWO, and database-protection rules remain unchanged.
- Administrators persist the external entry point in `public_base_url`, including the scheme, domain/IP, and optional service port; the same root serves the web app, `/api`, Feishu OAuth callback, and `/mcp/`. The current root is `https://itom.snnc.cc:30443`. FortiGate keeps TLS passthrough from `183.60.58.58:30443` to the Ingress VIP `10.60.65.220:443`; it does not terminate TLS.
- The `itom` namespace Ingress binds exact TLS hosts separately for `itom.prod.sn.local` and `itom.snnc.cc`. The public host always references the `kubernetes.io/tls` Secret `itom-snnc-cc-tls`: `tls.crt` must contain the full public-CA chain beginning with the leaf certificate and a SAN for `itom.snnc.cc`; `tls.key` may be created only in the controlled cluster Secret and must never be committed, logged, or echoed. Before apply, the deployment script verifies that this Secret exists and has the correct type. IDC release validation must not use `ALLOW_UNTRUSTED_TLS`, `curl -k`, or any other certificate-verification bypass.
- `/mcp/` preserves streaming and a suitable read timeout. Aily uses the canonical URL with its trailing slash. Secrets belong in headers, never URLs, logs, or frontend build variables.
- Logging: structured JSON to stdout through the Kubernetes logging path.

## 8. Milestone Mapping (development order)

| Milestone | Backend | Frontend | Acceptance baseline |
| --- | --- | --- | --- |
| M1 Skeleton | core/auth/members/dictionary/state-machine/audit/event-bus skeleton/deployment | login, layout menu, empty Dashboard, System Management | PRD §2/3/10/11 |
| M2 Ticket | tickets/catalogs/service-items/sla + minimal process engine + scheduled scans | ticket list/detail/service catalog/SLA board | PRD §5.1/5.3/5.5 |
| M3 Rest of ITSM | problems/cis/vendors/contracts/knowledge | the corresponding 5 pages | PRD §5.2/5.4/5.6/5.7 |
| M4 Project | portfolios/projects/wbs/milestones/risks/costs/charter-import | project two tabs / detail 5 tabs / Gantt | PRD §6 |
| M5 Requirement | requirements/tasks/close hand-off | requirement kanban/detail | PRD §7 |
| M6 Team + Overview | points/ideas/activities/positions/performance/dashboard/process-monitoring | team 6 pages/Overview/process monitoring | PRD §4/8/9 |
| Aily-MCP P0 (code/automation/real identity path and live bot receipt complete) | remove Helpdesk, mount MCP, identity/audit/message | Nginx `/mcp`, Aily config | docs/10 §10 |
| Aily-MCP P1 (real Aily write UAT complete for service requests and IT requirements) | dynamic forms, search, confirmed submit, BDO requirement registration, dispatch | service-item form/dispatch config | PRD §5/7 |
| Aily-MCP P2 (normal-user text same-ticket loop and P2.1 live signed-button loop both passed) | acceptance, resolution message, confirm/reopen, rating | ticket detail + three closure MCP tools | PRD §5.1 |
| Aily-MCP P3 / release hardening | Feishu Approval deferred; trusted IDC TLS deployed, with security/performance/recovery and current-version real-role UAT pending | approval/operations config | docs/10 §10 |
| Web Agent WA0 (Tasks 1–8 implemented; Task 9 acceptance pending) / WA1–WA4 | WA0 persistence, fixed capability registry, live role policy, recursive redaction, secure OpenAI-compatible model gateway, provider/profile administration APIs, owned web-conversation lifecycle, generic L3 server preview/confirmation boundary, guarded POST-SSE/tool loop, global assistant, structured action cards, and AI Agent administration UI; concrete domain capabilities remain WA1+ | Task 9 real PostgreSQL/ASGI/IDC evidence and later domain capabilities | web-agent design baseline |

## 8.1 Business-domain Service Department API (M41)

```text
GET /api/admin/departments
    # Reads organization departments; the UI filters active business departments and builds the tree
GET /api/admin/business-domains
    # Each domain includes departments[]: id/name/parent_id/active/include_children and business_bdo_id/business_bdo_name
GET /api/admin/business-domains/bdo-candidates
    # Returns only active accounts with an effective BDO role and an active business department
PUT /api/admin/business-domains/{domain_id}/departments
    # body: { department_ids: string[], include_children: boolean }
POST /api/admin/business-domains
    # create body may include department_ids/include_children; owner_id must be a digital-team member; business_bdo_id is optional
PATCH /api/admin/business-domains/{domain_id}
    # update body may replace department_ids/include_children; a business_bdo_id must remain in the effective served-department scope
PUT /api/admin/business-domains/{domain_id}/members
    # every service-team member must belong to the unified digital-team scope
```

The department write endpoint requires `admin_business_domains.edit`, deduplicates IDs, validates that every department exists, is active, and has type `business`, replaces the complete assignment, and writes the `set_departments` audit action. Create and update requests may submit the same department scope atomically. The IT-side BM and service team are validated server-side through `it_member_ids`; a business BDO must have an active account, an effective `bdo` role, and a business department in the domain's served-department scope (including descendants when `include_children=true`). Changing served departments revalidates the saved BDO, so an out-of-scope definition cannot remain. `include_children=true` means the business scope includes every descendant, while persistence stores only explicitly selected roots so organization changes do not require mass relationship rewrites. The historic `backup_owner_id` is compatibility-only and is excluded from new write contracts, routing, and performance attribution.

## 9. UI Branding API (M38)

```text
GET  /api/public/ui-branding
GET  /api/public/ui-branding/assets/{asset_id}
GET  /api/admin/ui-branding
PUT  /api/admin/ui-branding/draft
POST /api/admin/ui-branding/assets?kind=
POST /api/admin/ui-branding/publish
GET  /api/admin/ui-branding/history
POST /api/admin/ui-branding/rollback/{version}
POST /api/admin/ui-branding/reset
```

Public reads need no session. Admin endpoints require `admin_ui_branding`; all writes are audited. The client merges missing data with built-in defaults so a missing or failed branding configuration can never lock users out of login.
M42 adds `GET/PATCH /api/admin/org-settings` for the digital-team scope and Feishu scheduled-sync policy. The scope payload contains `digital_team_department_ids`, `digital_team_member_ids`, and `digital_team_include_children`; the server validates and deduplicates both entity types, then uses their union. `DELETE /api/admin/business-domains/{id}` returns `DOMAIN_IN_USE` (409) while an active requirement references the domain. The scheduler checks due state every 15 minutes and reuses `org_sync.run_sync` for execution.

Person selectors use two scopes. IT operational owner/assignee/reviewer/project-manager, service-item/CI/contract owner, and user-group owner/member selectors load `GET /api/members?scope=it`, with write APIs re-checking a configured digital-team scope. User management and Feishu provisioning link company-wide accounts and therefore load `GET /api/members` without `scope`; the server validates only that the person exists and is not deleted and must not apply the digital-team restriction.

`GET /api/admin/users` returns `person_id`, `person_name`, and `person_department_name`; clients display the readable name rather than an internal GLID. `PATCH /api/admin/users/{id}` uses explicit PATCH semantics for the nullable link: omitting `person_id` preserves the current person, while sending `person_id: null` unlinks it and immediately returns/persists the empty value for subsequent list reads and auditing.
M44: approval generates a 12-character password and stores encrypted ciphertext without sending. `GET /api/admin/users/{id}/initial-password` reveals it under authorization; `POST .../initial-password/email` sends it explicitly. Global SMTP/LDAP settings use `GET/PUT /api/admin/integrations/email|ldap`, with connection-test endpoints and masked secrets.

Task 8C Round 2: after explicit-`Z` and RFC 3339 shape checks, the shared action-SSE expiry parser validates calendar semantics. It rejects JavaScript-normalized values such as `2030-02-30T00:10:00Z` and `2030-01-01T24:00:00Z`, while preserving valid leap days and fractional seconds. No backend, route, database, deployment, or Aily/MCP semantics change.
