# ITOM API Contract & Architecture Design

> English translation of [../05-API契约与架构设计.md](../05-API契约与架构设计.md). For the authoritative version, the Chinese source prevails.

> Based on [03-PRD.md](03-PRD.md), [04-data-model.md](04-data-model.md).

## 1. System Architecture

```text
┌──────────────┐     HTTPS      ┌─────────────────────────────┐      ┌────────────┐
│ React SPA    │ ─────────────▶ │ FastAPI monolith backend    │ ───▶ │ PostgreSQL │
│ (AntD)       │   JWT Bearer   │ routers → services → models │      └────────────┘
└──────────────┘                │        │                    │
                                │        ▼ domain events (in-process)
                                │  ┌─────────────────────┐    │
                                │  │ event_bus           │    │
                                │  │ ├─ point_engine     │──▶ point_entry
                                │  │ ├─ notifier         │──▶ notification_outbox → in_app
                                │  │ └─ process_engine   │──▶ process_instance/task
                                │  └─────────────────────┘    │
                                └─────────────────────────────┘
```

**Key decisions**:

1. **Monolith backend**, modularized by domain, no microservices — at a single-team scale, microservices only add complexity.
2. **Domain events are dispatched in-process synchronously** (within the same transaction commit), with three subscribers: the point engine, the notifier, and the process engine. The outbox table is the asynchronous hook for future external systems (Feishu/n8n).
3. Decoupled front end and back end in a single repository (monorepo), deployed as one unit.

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

## 4. Route Inventory (by domain)

### 4.1 Authentication & Support

```text
POST /api/auth/login | GET /api/auth/me
GET /api/auth/me/profile | PATCH /api/auth/me/preferences
POST /api/auth/me/password | GET /api/auth/me/audit-logs
GET /api/auth/me/feishu-binding/authorize-url
POST/DELETE /api/auth/me/feishu-binding
GET /api/auth/feishu/client-config | POST /api/auth/feishu/app-login
GET/POST/PATCH/DELETE /api/admin/users   # admin; delete soft-deletes the account and unlinks the person
GET/POST/PATCH /api/members              # personnel master data
GET /api/admin/master-data?category=     # dictionary (read-only for all, writable by admin)
GET/PUT /api/admin/workflow-config       # state machine
GET /api/admin/audit-logs
GET /api/notifications | POST /api/notifications/{id}/read | POST /api/notifications/read-all | POST /api/notifications/clear-read   # in-app notifications, bulk read, and read cleanup
POST /api/attachments (multipart) | GET /api/attachments?entity=
```

Profile constraints: preference PATCH updates only submitted keys; theme is `light|dark|system` and density is `default|compact`. Passwords require at least eight characters with letters and digits, and an existing deliberate password requires a valid `current_password`. Feishu unbinding requires a local password; personal audit logs return only records whose actor is the current account.

### 4.1a Organization Sync (M35)

```text
POST /api/admin/org-sync                 # starts in background; returns {started:true}
POST /api/admin/org-sync {sync:true}     # blocking mode for tests/scripts
GET /api/admin/feishu-config             # last_sync_stats.status: running|done|failed
```

A repeated trigger while running returns HTTP 409 / `SYNC_RUNNING`. The UI polls every three seconds for up to ten minutes. Completion or failure sends an in-app notification to the initiator, and the background worker uses an independent database session.

### 4.1b Feishu Helpdesk handoff and reliable synchronization (M45/M46)

```text
POST /api/integrations/feishu/helpdesk/events
    # Feishu event URL verification; checks the configured Verification Token
POST /api/integrations/feishu/helpdesk/card-callback
    # Feishu 2.0 interactive-card callback; token may be in header.token or event.token
    # event.action.value={action:create_service_request|create_requirement,ticket_id}
POST /api/integrations/feishu/helpdesk/cards
    # compatibility/fallback endpoint; trusted bot caller sends a card to guest.open_id
POST /api/integrations/feishu/helpdesk/handoffs
    # trusted server/bot only; X-Lark-Helpdesk-Authorization=base64(helpdesk_id:helpdesk_token)
    # body: {ticket_id, action: service_request|requirement}
GET /api/integrations/feishu/helpdesk/handoffs/{token}
    # authenticated user reads the one-time context; Feishu guest open_id must match
    # issued returns prefill context; consumed returns linked entity_type/entity_id for idempotent navigation
POST /api/integrations/feishu/helpdesk/handoffs/{token}/consume
    # called after creation; body: {entity_type: ticket|requirement, entity_id}; duplicate consumption remains HTTP 409
POST /api/integrations/feishu/helpdesk/intakes/{intake_id}/handoff
    # authenticated stable-entry exchange; body: {action: service_request|requirement}
    # issues a token only after account, intake guest, and fresh ticket guest open IDs match
GET /api/integrations/feishu/helpdesk/intakes
    # admin/CIO/IT managers inspect intake state and entry delivery channel/time/message ID
GET /api/integrations/feishu/helpdesk/sync-events
    # inspect processed/pending/failed inbound events and retry counts
POST /api/admin/feishu-config/subscribe-helpdesk-events
    # admin-only; registers the configured app for Helpdesk events
```

The primary path starts from `/feishu/helpdesk/entry?intake=...&action=...` in the original Helpdesk conversation. This stable URL contains no open_id, Helpdesk credential, or one-time token. The public entry sends unauthenticated users through login and then calls `POST /intakes/{intake_id}/handoff`; only a fresh ticket read and three-way open_id match returns a token-bearing `entry_url`. `POST /handoffs`, `POST /cards`, and card callbacks remain available for trusted middleware and independent-bot fallback.

Handoff reads are idempotent: an `issued` token returns its prefill context; after creation changes it to `consumed`, the same Feishu identity receives the linked entity and the frontend redirects there. Identity mismatch remains HTTP 403, expiration remains HTTP 410, and a second `POST /consume` remains HTTP 409, preserving duplicate-creation protection without treating a reopened link as an error.

The Helpdesk token is encrypted and used only by the backend. Only a hash of `handoff_token` is stored, and the snapshot contains prefill fields only. ITOM supports the Helpdesk ticket-detail `customized_fields` shape (`key_name`/`display_name`/`value`) and maps title, urgency, service category, problem description, and supplemental information into `prefill`. Assigned agents may be returned as `agent`, `service_agent`, `assignee`, or an `agents` array; for an array ITOM uses the first agent ID for linkage and joins the names for display, allowing the human-service stage to be detected. When the service category is returned as a dropdown option UUID, the backend reads the Helpdesk field metadata and converts `dropdown_options` to the display label. `prefill.service_category` is used for ITSM catalog/item context; the requirement page preserves it as source metadata and never fills `business_domain_id` automatically.
The public root comes from `ITOM_PUBLIC_URL` when set, otherwise from the scheme and host of the complete `helpdesk_event_url`. It must be an employee-reachable HTTPS root when local Docker is exposed through ngrok or a reverse proxy. Each successful stable-entry exchange expires older unconsumed tokens for the same Helpdesk ticket before issuing a fresh one. Compatible interactive-card callbacks still validate the Verification Token, action, and `event.operator.open_id`, and use callback event IDs for idempotency.
The service-request creation API preserves the pre-consultation semantics: `service_category` stores the ITSM catalog name and `other_info` stores the pre-consultation supplemental information; both remain separate from internal `remarks`. Regular business users submit only the pre-consultation fields, while IT staff/administrators may additionally submit `assignee` and `remarks`. Service category is never written to requirement `business_domain_id`.
Reliable synchronization uses three stages: inbound event queue, fresh Helpdesk-detail read, and outbound outbox. `helpdesk.ticket.created_v1`, `helpdesk.ticket.updated_v1`, and `helpdesk.ticket_message.created_v1` are persisted by unique `event_id`; a five-second worker consumes them with exponential backoff (up to eight attempts). Processing re-reads the current ticket, creates or updates the pending intake, and queues one `routing_prompt` once human service is detected. Delivery first attempts a rich post in the original Helpdesk conversation and immediately downgrades to full-URL text if rich content is unsupported. If the original conversation still fails through two retries, the third attempt sends the independent application-bot card. The selected channel, send time, and Feishu message ID are persisted on the intake for diagnostics. The ITOM record is linked only when the one-time handoff is consumed. Service requests retain the existing three-step `sr_flow` (intake confirmation → implementation and delivery → requester confirmation and closure); no separate ITOM routing step is introduced. Automatic task assignment and in-process reassignment publish `ticket.assigned`; handoff consumption replays the current assignment when the record was created before linkage. Completion of the final requester step publishes `ticket.user_confirmed`, after which the state machine emits `resolved` and `closed`. In the reverse direction, a Feishu user-confirmed detail event completes ITOM's pending requester task; a closed state follows the reachable closure path instead of directly writing status. Rating is refreshed from ticket details after an update event, updates `Ticket.satisfaction`, and emits `ticket.satisfaction_rated`. Internal notes, approval comments, and unpublished details never leave ITOM. Only user-visible milestones enter the outbox and are posted back into the original conversation. Before testing, an admin must configure the public callback URL, add the three Helpdesk events in Feishu and publish the app, then click “Subscribe Helpdesk events” in ITOM. Field-validation failures preserve `field_violations` and `log_id`; the configuration page exposes subscription state, entry channel, queue backlog, and last errors.

### 4.2 ITSM

```text
GET/POST /api/tickets | GET/PATCH /api/tickets/{id}
POST /api/tickets/{id}/transition        # includes approval (approve/reject), resolve, close, hold, reopen
POST /api/tickets/{id}/satisfaction      # requester rating
POST /api/tickets/{id}/escalate-problem  # one-click escalation to a problem
POST /api/tickets/{id}/to-knowledge      # one-click knowledge capture (draft)
GET/POST/PATCH /api/problems | POST /api/problems/{id}/transition
GET/POST/PATCH /api/catalogs | /api/service-items. The catalog list returns `item_count` plus `published_item_count` and `unpublished_item_count`; the service-item GET endpoint accepts `catalog_id`, `q` (code/name/type/audience/owner keyword), `status` (published/unpublished; omitted means all), `sort_by`, and `sort_dir` for list filtering and sorting.
GET/POST/PATCH /api/cis | GET /api/cis/{id}/impact          # impact analysis (upstream/downstream + linked tickets)
GET/POST/DELETE /api/ci-relationships
GET/PUT /api/admin/sla-policies | GET /api/sla/dashboard     # live attainment rate
GET/POST/PATCH /api/vendors | /api/contracts
GET/POST/PATCH /api/knowledge | POST /api/knowledge/{id}/vote
GET /api/knowledge/search?q=
```

### 4.3 Project

```text
GET/POST/PATCH /api/portfolios
GET/POST/PATCH /api/projects | POST /api/projects/{id}/transition
POST /api/projects/import-charter        # .docx parse → draft preview → confirm and persist (two steps)
GET/POST/PATCH/DELETE /api/projects/{id}/wbs | /milestones | /risks | /costs
GET /api/projects/{id}/gantt             # Gantt data (tasks + dependencies + milestones)
```

### 4.4 Requirement

```text
GET/POST /api/requirements | GET/PATCH /api/requirements/{id}
POST /api/requirements/{id}/transition   # Registration→Analysis→Implementation→Closure/On-Hold/Cancelled, carrying stage fields
GET/POST/PATCH /api/requirements/{id}/tasks
POST /api/requirements/{id}/close        # validate all acceptance criteria checked → may carry {legacy_problem, knowledge_draft}
```

### 4.5 Process

```text
GET/POST/PATCH /api/admin/process-definitions (nested steps with stable step_code; used-version node/RACI/SLA changes require a new version)
GET /api/process-instances?entity= | GET /api/process-monitor   # stuck/overdue aggregation
POST /api/process-tasks/{id}/complete | /reassign
```

### 4.6 Team

```text
GET /api/team/overview                   # load / points Top / training count / hiring progress aggregation
GET/POST/PATCH /api/positions | /api/hiring-needs; Excel template/export/import endpoints are also available at `/api/positions/{template,export,import}` and `/api/hiring-needs/{template,export,import}`.
GET/POST /api/trainings                  # training activities
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

### 4.7 Dashboard

```text
GET /api/dashboard    # a single endpoint returning all data for the four panels + alert area (one aggregation)
```

## 5. Domain Event List

Events are published by the service layer within the transaction; `→points` means it triggers point_engine scoring (the point value is looked up in point_rule), and `→notify` means it writes to the outbox.

| event_type | Trigger | Subscription |
| --- | --- | --- |
| ticket.created | Ticket created | →notify (assignee/it_ops), →process (create instance) |
| ticket.assigned | Assigned/reassigned | →notify |
| ticket.resolved | Resolved | →points (ticket resolved), →notify (submitter) |
| ticket.closed | Closed | →points (bonus when both SLAs met) |
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
| knowledge.published | Published | →points |
| knowledge.voted | Marked helpful | →points (author) |
| activity.registered | Training registered | →points (presenter/organizer/participant scored separately) |
| idea.submitted / liked / adopted | Suggestion | →points; adopted→notify (submitter) |
| performance.review_submitted | Manager/CIO review submitted | →notify (next stage), →audit |
| performance.published / unlocked | Performance published/new version created | →notify (evaluated employee), →audit |

Scheduled tasks (a backend-built-in scheduler, every 15 minutes): SLA-imminent scan, contract-expiry scan, milestone-overdue scan, contract-status advancement.

## 6. Key Implementation Mechanisms

1. **State machine**: `services/workflow.py` single entry point `transition(entity, to, fields, actor)` — look up workflow_transition to validate role and legality → validate the required staged fields for that transition → update + stamp → publish the event → write the audit. Shared by all records.
2. **Point-engine idempotency**: point_entry has UNIQUE(event_type, source_entity_type, source_entity_id, person), so the same record + same event does not score twice (reopening and re-resolving does not double-score).
3. **Computed-column maintenance**: after a wbs_task/cost_entry/milestone write, the service layer recomputes the owning project's progress_pct/actual_cost/health_status and writes them back (same transaction). WBS `progress` accepts an integer percentage from 0–100. Process steps use `node_type=processing|approval` to distinguish handling and approval semantics. Approval tasks expose `POST /api/process-tasks/{id}/approve` (optional comment) and `POST /api/process-tasks/{id}/reject` (required reason); the flow-diagram complete-step entry remains supported.
4. **Two-step charter import**: the parse endpoint only returns a draft JSON + warnings (no persistence); the front end shows a confirmation page, and after the user corrects it, the create endpoint persists it. A parse failure falls back to the manual form.
5. **SLA timing**: on-hold time accumulates into paused_minutes; the attainment check = (resolved_at − submitted_at − paused) ≤ target.
6. **Matrix-role performance review**: the system first generates reference scores from ITSM, requirements, projects, processes, and points events. Business-line leads can write only business-role proposals; professional-line leads can write only professional-role proposals; platform roles and leaders' own scores are entered directly by the CIO. The backend enforces `performance_role_assignment.review_scope`; UI hiding is not an authorization boundary.
7. **External-input and publication isolation**: external business satisfaction is stored in `performance_external_input` and must be submitted, verified, and locked before it affects scoring. `performance_score_component` keeps reference, stage proposal, and effective values separately. `/api/my/performance` returns published snapshots only.
8. **Point buckets**: `point_rule`/`point_entry` use `contribution_bucket=role_result|team_contribution` to separate role outcomes from the fixed 20% team-contribution score. A fact already used by a role metric cannot enter team contribution again.

## 7. Deployment Architecture

```yaml
# deploy/docker-compose.yml form
services:
  db:        postgres:16  (volume + daily pg_dump to a host backup directory)
  backend:   uvicorn, depends on db, runs alembic upgrade + seed (idempotent) on startup; with `SEED_INITIAL_CONFIG=1`, a fresh database also receives the six workflows and the verified login/Logo branding, while existing branding drafts/releases are preserved
  frontend:  nginx serving the build output, /api reverse-proxied to the backend
```

- Environment variables: `DATABASE_URL`, `JWT_SECRET`, `ADMIN_INIT_PASSWORD`, `TZ=Asia/Shanghai`.
- IDC Kubernetes is the sole delivery and acceptance environment: run `deploy/k8s/push-images.sh` followed by `deploy/k8s/k8s-deploy.sh`, then verify the external health endpoint and user-visible pages. Docker Compose is retained only for temporary local troubleshooting.
- Logging: structured JSON to stdout (viewable via docker logs).

## 8. Milestone Mapping (development order)

| Milestone | Backend | Frontend | Acceptance baseline |
| --- | --- | --- | --- |
| M1 Skeleton | core/auth/members/dictionary/state-machine/audit/event-bus skeleton/deployment | login, layout menu, empty Dashboard, System Management | PRD §2/3/10/11 |
| M2 Ticket | tickets/catalogs/service-items/sla + minimal process engine + scheduled scans | ticket list/detail/service catalog/SLA board | PRD §5.1/5.3/5.5 |
| M3 Rest of ITSM | problems/cis/vendors/contracts/knowledge | the corresponding 5 pages | PRD §5.2/5.4/5.6/5.7 |
| M4 Project | portfolios/projects/wbs/milestones/risks/costs/charter-import | project two tabs / detail 5 tabs / Gantt | PRD §6 |
| M5 Requirement | requirements/tasks/close hand-off | requirement kanban/detail | PRD §7 |
| M6 Team + Overview | points/ideas/activities/positions/performance/dashboard/process-monitoring | team 6 pages/Overview/process monitoring | PRD §4/8/9 |

## 8.1 Business-domain Service Department API (M41)

```text
GET /api/admin/departments
    # Reads organization departments; the UI filters active business departments and builds the tree
GET /api/admin/business-domains
    # Each domain includes departments[]: id/name/parent_id/active/include_children
PUT /api/admin/business-domains/{domain_id}/departments
    # body: { department_ids: string[], include_children: boolean }
POST /api/admin/business-domains
    # create body may include department_ids/include_children; owner_id/backup_owner_id must be digital-team members
PATCH /api/admin/business-domains/{domain_id}
    # update body may replace department_ids/include_children; owner scope is identical
PUT /api/admin/business-domains/{domain_id}/members
    # every service-team member must belong to the unified digital-team scope
```

The department write endpoint requires `admin_business_domains.edit`, deduplicates IDs, validates that every department exists, is active, and has type `business`, replaces the complete assignment, and writes the `set_departments` audit action. Create and update requests may submit the same department scope atomically. Owner, backup owner, and service team are all validated server-side through `it_member_ids`, preventing non-digital-team people from being written by bypassing the UI. `include_children=true` means the business scope includes every descendant, while persistence stores only explicitly selected roots so organization changes do not require mass relationship rewrites.

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

Person-selector contract: operational owner/assignee/reviewer/project-manager, service-item/CI/contract owner, user-group owner/member, and account-linking dropdowns load `GET /api/members?scope=it`. Once administrators configure any digital-team department or individual, corresponding write APIs re-check the same union scope with `require_it_member_if_configured` (including batch group members); before configuration, legacy records remain writable for compatibility while `scope=it` keeps its existing filtered semantics.

`PATCH /api/admin/users/{id}` uses explicit PATCH semantics for the nullable link: omitting `person_id` preserves the current person, while sending `person_id: null` unlinks it and immediately returns/persists the empty value for subsequent list reads and auditing.
M44: approval generates a 12-character password and stores encrypted ciphertext without sending. `GET /api/admin/users/{id}/initial-password` reveals it under authorization; `POST .../initial-password/email` sends it explicitly. Global SMTP/LDAP settings use `GET/PUT /api/admin/integrations/email|ldap`, with connection-test endpoints and masked secrets.
