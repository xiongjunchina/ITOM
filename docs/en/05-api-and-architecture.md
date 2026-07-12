# New_AOM API Contract & Architecture Design

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
New_AOM/
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
├── deploy/                # docker-compose.yml, Dockerfile×2, nginx.conf, K8s manifests (reserved)
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
GET/POST/PATCH /api/admin/users          # admin
GET/POST/PATCH /api/members              # personnel master data
GET /api/admin/master-data?category=     # dictionary (read-only for all, writable by admin)
GET/PUT /api/admin/workflow-config       # state machine
GET /api/admin/audit-logs
GET /api/notifications | POST /api/notifications/{id}/read   # in-app notifications
POST /api/attachments (multipart) | GET /api/attachments?entity=
```

### 4.2 ITSM

```text
GET/POST /api/tickets | GET/PATCH /api/tickets/{id}
POST /api/tickets/{id}/transition        # includes approval (approve/reject), resolve, close, hold, reopen
POST /api/tickets/{id}/satisfaction      # requester rating
POST /api/tickets/{id}/escalate-problem  # one-click escalation to a problem
POST /api/tickets/{id}/to-knowledge      # one-click knowledge capture (draft)
GET/POST/PATCH /api/problems | POST /api/problems/{id}/transition
GET/POST/PATCH /api/catalogs | /api/service-items
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
GET/POST/PATCH /api/admin/process-definitions (with nested steps)
GET /api/process-instances?entity= | GET /api/process-monitor   # stuck/overdue aggregation
POST /api/process-tasks/{id}/complete | /reassign
```

### 4.6 Team

```text
GET /api/team/overview                   # load / points Top / training count / hiring progress aggregation
GET/POST/PATCH /api/positions | /api/hiring-needs
GET/POST /api/activities                 # training activities
GET/PUT /api/team-charter
GET/POST /api/ideas | POST /api/ideas/{id}/like | /adopt | /to-requirement
GET /api/points/leaderboard?period= | GET /api/points/mine | GET /api/points/entries?person=
GET/POST/PATCH /api/admin/point-rules
POST /api/points/adjust                  # admin manual point adjustment (remark required)
GET/POST/PATCH /api/admin/performance-rules
GET /api/performance/scores?period= | POST /api/performance/recompute
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

Scheduled tasks (a backend-built-in scheduler, every 15 minutes): SLA-imminent scan, contract-expiry scan, milestone-overdue scan, contract-status advancement.

## 6. Key Implementation Mechanisms

1. **State machine**: `services/workflow.py` single entry point `transition(entity, to, fields, actor)` — look up workflow_transition to validate role and legality → validate the required staged fields for that transition → update + stamp → publish the event → write the audit. Shared by all records.
2. **Point-engine idempotency**: point_entry has UNIQUE(event_type, source_entity_type, source_entity_id, person), so the same record + same event does not score twice (reopening and re-resolving does not double-score).
3. **Computed-column maintenance**: after a wbs_task/cost_entry/milestone write, the service layer recomputes the owning project's progress_pct/actual_cost/health_status and writes them back (same transaction).
4. **Two-step charter import**: the parse endpoint only returns a draft JSON + warnings (no persistence); the front end shows a confirmation page, and after the user corrects it, the create endpoint persists it. A parse failure falls back to the manual form.
5. **SLA timing**: on-hold time accumulates into paused_minutes; the attainment check = (resolved_at − submitted_at − paused) ≤ target.

## 7. Deployment Architecture

```yaml
# deploy/docker-compose.yml form
services:
  db:        postgres:16  (volume + daily pg_dump to a host backup directory)
  backend:   uvicorn, depends on db, runs alembic upgrade + seed (idempotent) on startup
  frontend:  nginx serving the build output, /api reverse-proxied to the backend
```

- Environment variables: `DATABASE_URL`, `JWT_SECRET`, `ADMIN_INIT_PASSWORD`, `TZ=Asia/Shanghai`.
- Starts on single-machine Docker Compose; `deploy/k8s/` reserves the SN IDC cluster manifests (later, on demand).
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
