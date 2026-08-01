# ITOM Feishu Aily Agent + MCP Server Final Design Baseline

> Status: **formal baseline; P0/P1 complete; P2 live same-ticket end-to-end UAT has passed for both text and signed card buttons; P3 Feishu Approval is deferred, while IDC release hardening and formal acceptance remain**
> Approval date: 2026-07-29
> The Chinese document is authoritative. This file is its English mirror.

## 1. Purpose and status semantics

This baseline originated on the now-archived `feature/aily-agent-mcp` line. The current `feature/AI-agent-version` branch inherits its Aily + MCP capabilities and is the sole Web Agent development line. This document defines the approved goals, boundaries, tools, target data model, phases, and acceptance criteria. The implementation must not reintroduce Feishu Helpdesk or turn Aily, MCP, or Feishu into a second ITOM business system.

This document records both target contracts and actual status. The branch implements P0 protocol/identity/messaging foundations, P1 service-request and requirement intake, and P2 acceptance/confirmation timestamps, three closure MCP tools, shared web/MCP confirmation semantics, reliable user messages, and rating detail. The real-Aily conversational loop, live bot receipt, normal-user same-ticket text loop, and signed-card-button loop have all passed. P3 Feishu Approval is deferred by user decision. IDC is available and the current version plus public protocol probes are deployed, while trusted TLS, security/performance/recovery, and formal real-role UAT remain.

Before starting work, a new chat must read `AGENTS.md`, this document, `docs/03-PRD.md`, `docs/04-数据模型设计.md`, `docs/05-API契约与架构设计.md`, and `docs/06-用户身份与组织模型设计.md`, then inspect the real code and Git status.

## 2. Version and worktree baseline

| Object | Value | Constraint |
|---|---|---|
| Frozen commit | `f13f702` | Historical Feishu Helpdesk baseline |
| Historical tag | `v1.0.0-feishu-helpdesk` | Immutable recovery reference |
| Historical branch | `release/feishu-helpdesk-v1` | Historical inspection/maintenance only |
| Stable branch | `main` | Accepts only user-approved Pull Requests |
| Archived development branch | `feature/aily-agent-mcp` | Retains Aily + MCP history and receives no new commits |
| Current development branch | `feature/AI-agent-version` | Sole Web Agent line inheriting the Aily + MCP capabilities |
| Frozen worktree | `/Users/xjun/Gitrepo/ITOM` | Never used for the new version |
| New-version worktree | `/Users/xjun/Gitrepo/ITOM-Aily-MCP` | All new-version work happens here |

The frozen commit has backend-test and frontend-build evidence, but real Helpdesk integration exposed permission, event, conversation-channel, and payload differences. The new version does not retain that Helpdesk path; it retains the lessons about identity, idempotency, retries, auditability, and real UAT.

## 3. Approved product goal

A normal employee describes an IT need to Aily. Aily routes it to one of only two business records that a normal user may create:

1. **IT service request**: failure, request, installation, configuration, access, or assistance involving an existing IT capability.
2. **IT requirement**: a new system, feature, data/integration capability, or capability not covered by the service catalog.

Normal employees cannot create IT incidents or changes through Aily.

### 3.1 IT service request

A single user's software failure, device failure, network-access problem, account/access request, installation/configuration request, and usage question are all `service_request` records. Aily must search the live ITOM catalog for published service items that the current user may request. Neither prompts nor MCP code may contain a fixed service list.

Target flow:

1. The user describes the need.
2. MCP searches eligible service items; Aily asks the user to choose when the match is ambiguous.
3. MCP returns the active form version for the selected item.
4. Aily pre-fills facts supported by the original description and asks only for missing required fields.
5. ITOM performs authoritative type, length, option, date, people/department scope, and permission validation.
6. Aily previews normalized data, SLA, actual process, approval requirements, and expected support group.
7. After confirmation, MCP creates `Ticket(ticket_type=service_request)` with a confirmation intent and idempotency key.
8. ITOM dispatches the request; assigned IT staff accept, work, and mark it resolved.
9. ITOM proactively notifies the requester. Confirmation closes the request; rejection returns it to processing.
10. Aily asks for feedback after closure and writes the rating to the matching ITOM ticket.

“Marked resolved by IT” is not closure. The required loop is “request → record → dispatch → accept → resolve → notify → confirm/reopen → close → rate.”

### 3.2 IT requirement

An IT requirement is stored as a separate `Requirement`, not as a `Ticket.ticket_type`. Aily retrieves the real ITOM requirement-registration form, collects title, type, business domain, description, and optional target date/effect/value, previews the data, and registers it after confirmation. ITOM then starts the requirement-management process.

Normal employees receive a constrained “create and read my own requirements” permission. They do not gain requirement evaluation, assignment, scoring, project conversion, or closure permissions.

### 3.3 IT incident

An incident means a broad network, server, or application outage. Only IT staff may register one in ITOM, or a monitoring system may create one through a dedicated integration identity and idempotent API. V1 does not expose `create_incident` to normal users.

When a user describes a potentially broad outage, Aily still creates that user's service request and marks it as suspected major impact. IT staff decide whether to associate an existing incident or create a new one. Aily and normal users do not classify it directly as an incident.

### 3.4 IT-staff web routing does not change the Aily boundary (phases A/B/C implemented)

IT staff and system administrators now have a Web “Record Creation Guide” and cross-record relation capability. It supports internal ITIL judgment only and does not burden normal business users with web type selection. In Aily, a normal business user continues to create only service requests, while a department-appointed BDO may register IT requirements. Aily does not transfer service request → incident, service request/incident → problem, incident/problem → change, or requirement → project. Any future MCP scope expansion needs separate confirmation of architecture, permission, audit, and user experience.

### 3.5 ITOM web agent (design approved; WA0 Tasks 1–7 implemented)

Task 5 runtime accepts only a provably complete schema-marked version snapshot, bilingual prompts, valid capability/risk limits, a healthy compatible provider, and agreement with the newest active profile; `enabled_capabilities` and `knowledge_scope` must be raw valid lists, and a missing, `null`, or malformed value is not normalized to an empty list; unpublished, disabled, deleted, or inconsistent profiles fail closed. In one transaction, conversation creation first takes the same PostgreSQL governance lock as Task 4 publication/withdrawal, then reloads and `FOR UPDATE` locks the target profile, validates, inserts, and commits; SQLite preserves the same call order for deterministic tests. Ordinary-message retention comes only from the version captured at creation, never the live profile or `expires_at`: a captured zero remains nonpersistent after a later positive publication, while a captured 1–90-day decision and creation-time `expires_at` remain immutable, although new bodies stop when the current profile is withdrawn or audience-incompatible. Every body is recursively redacted first. `fallback_available` reflects only safe availability of the authenticated permission-aware Record Creation Guide, not WA1; pages are limited to 1–10,000. PostgreSQL two-session contention remains Task 9 IDC acceptance and was not run in this round.

Task 6 establishes the generic L3 action boundary: every fixed registered handler implements `authorize_preview`, `preview`, and `authorize_record`. Normalized input is rejected if recursive redaction would change it; only unchanged safe input is hashed or persisted. Non-leaking record authorization precedes metadata. Preview runs in an independent Session that is always rolled back and closed; `authorize_preview()` and `preview()` receive only a preview-local actor context plus `ReadOnlyActionData`, which has no Session-like attributes, accepts only explicit bounded SQLAlchemy `Select` scalar projections, returns recursively frozen `FrozenActionRecord` snapshots, and rejects entity/relationship/eager results, every row lock, text/DML, excessive offsets, and over-limit reads. PostgreSQL marks preview transaction-read-only before handler access, ORM/DML writes, textual transaction statements, and flush/commit/rollback fail closed, and preview status must be exactly `prepared`. Preparation then follows two ordered paths: an existing key is first probed without a lock, then replay/race recovery locks `AiAction` first and the owned active conversation second before digest comparison; a brand-new action locks/revalidates the conversation, rechecks the same key without taking an action lock, and inserts only while it is still absent. Idempotency is account + capability + key and recovers a race only through named constraint `uq_ai_action_user_capability_idempotency`, then row-locks its winner. Confirmation credentials store only SHA-256, expire after ten minutes, and are one-use. Confirmation first `FOR UPDATE` locks the action, then locks and refreshes the owned active conversation before the Task 4 governance/provider/profile lock order and Task 5 complete runtime proof verify that the conversation-captured version remains current and its provider remains enabled, healthy, and compatible. It then recomputes account, direct/group permission, and capability and calls record authorization only through `ActionUnitOfWork.lock_one()/update_locked()`, immutable `FrozenActionRecord` snapshots, and an opaque `LockedActionRecord` that keeps real ORM identity module-private. Successful domain change, `AiAction` result, and generic audit run in a nested savepoint and commit once through the outer transaction. Handler/audit failure rolls back only the savepoint, retains the action row lock, and commits bounded `failed` on the same row; persistence failure is surfaced. Handler code is trusted in-process extension code, not a hostile-code sandbox; the supported interface only guarantees no normal Session escape. Cancellation, confirmation, and replay remain constrained by ownership and terminal state. SQLite covers only deterministic call order, archive-vs-prepare/archive-vs-confirm ordering, rollback outcomes, injected races, and savepoint semantics; Task 9 IDC still requires genuine two-Session PostgreSQL evidence for read-only preview, same/different-payload prepare races, archive ordering, and a waiting confirmer after failure never executing the handler twice.

Fix Round 4 further fixes the Task 6 supported interface to verifiable query and mutation scopes. `ReadOnlyActionData` recursively validates the complete SQLAlchemy AST and accepts only direct scalar columns from one table, same-table safe predicates/order clauses, and compile-time bounded pagination; nested selects/CTEs/row locks at any depth, joins/aliases, entities/relationships, aggregates/windows/functions, text/raw SQL, cross-table references, and dynamic/negative/excessive pagination are rejected. A `LockedActionRecord` is bound to the exact issuing UoW, Session, outer transaction, and savepoint, and a successful update consumes the old handle and returns a replacement with a merged snapshot. Forged, cross-scope, terminal-transaction, and repeated handles fail closed. This round adds no concrete business capability or database field; PostgreSQL two-session runtime proof remains Task 9 IDC acceptance.

Fix Round 5 closes raw SQLAlchemy query modifiers that do not appear in the visitor AST. Any nonempty `_prefixes`, `_suffixes`, `_statement_hints`, or `_hints` is rejected before execution without parsing or a string allowlist; read-only preview and mutation `lock_one()` share this gate. The fix adds no capability, field, or migration and does not change the deferred Task 9 PostgreSQL/IDC evidence scope.

The web agent uses two entrances and one capability core: web uses the current ITOM login, Aily retains its JWT/MCP identity, and both reuse only lower-level domain services and business guards. WA0 Tasks 1–7 implement disabled-by-default persistence and `admin_ai` permission foundations, fixed capability registration/request-time policy/recursive redaction, the secure OpenAI-compatible model gateway, `admin_ai`-only provider/four-profile administration APIs, current-login conversation APIs, the generic L3 preview/confirm/cancel boundary, and a guarded POST-SSE/tool loop whose event set is `meta|delta|message|action|error|done`. Task 7 Fix Round 1 further narrows runtime state to scalar turn snapshots and separate short transactions. L1/L2 receives only a read-only facade plus immutable actor, with PostgreSQL transaction-read-only and statement timeout before reads. L3 produces a server-rendered pending/not-executed preview only, while normal model prose is `advisory/not_executed`, never an ITOM result. Request idempotency uses a server-key HMAC, and final persistence revalidates an active account, owned active conversation, exact current profile/version, and streaming placeholder in a fresh short transaction. Conversations and actions remain isolated by database `auth_user_id`; models, prompts, and client claims never authorize. Every tool call re-authorizes a fixed registry code. Prompt layers separate platform/profile authority from untrusted page, knowledge, business, and user bodies and reject stable line/sentence/fragment leakage. Disconnect immediately stops waiting and event emission but does not claim to force-kill arbitrary synchronous Python threads; L1/L2 is bounded by read-only database access and timeout, while L3 may at most retain prepared until expiry and never execute. Existing provider security, profile publication, conversation ownership/retention, recursive redaction, audit atomicity, and fail-closed contracts continue to apply. The administration UI and concrete business handlers remain Task 8+ work. A normal business user's web agent remains limited to own service requests; BDO adds own IT requirements; IT staff receive system-wide guidance and progressively enabled writes under actual permissions and process assignment. The existing Record Creation Guide computes an authorized path from current permissions and remains the deterministic fallback. Real PostgreSQL two-Session and real ASGI disconnect evidence remains Task 9. See [`docs/en/superpowers/specs/2026-08-01-itom-web-agent-design.md`](superpowers/specs/2026-08-01-itom-web-agent-design.md).

## 4. Approved architecture

Use **Approach A: embed the MCP Server in the existing FastAPI backend**.

```text
Feishu user ⇄ Aily Agent
                  │  HTTPStreaming / x-aily-jwt
                  ▼
     IDC Ingress :30443 /mcp/
                  ▼
        MCP embedded in FastAPI
                  ▼
       ITOM domain services / RBAC / workflow / audit
                  ▼
                PostgreSQL

ITOM domain event → reliable notification outbox → Aily-bot Feishu message → user
User reply → Aily → MCP → ITOM confirmation, reopen, or rating
```

IDC Kubernetes is the sole runtime, integration, and acceptance environment at the current public root `https://itom.snnc.cc:30443`, serving the frontend, `/api`, Feishu OAuth callback, and `/mcp/`. Administrators maintain the root through `public_base_url`, from which the page derives every public endpoint. Starting a local ITOM application stack, database, Docker Compose, port 8180, or ngrok is prohibited by default. It is allowed only when the user explicitly requests temporary isolated troubleshooting, and its results are never delivery evidence.

`.github/workflows/quality-gate.yml` first runs the complete backend regression against an isolated test database, frontend production build, deployment-file checks, and bilingual documentation guard. After it passes, `push-images.sh` builds Git-SHA-derived immutable linux/amd64 images from a clean commit and pushes them to Harbor; `k8s-deploy.sh` deploys the same tag and strictly verifies rollouts, actual image identities, internal/external health paths, and MCP `initialize`. Real Aily, callback, identity, authorization, and business-flow acceptance runs only in IDC.

### 4.1 Responsibility boundary

| Component | Responsible for | Forbidden |
|---|---|---|
| Aily | Intent understanding, candidate presentation, missing-field questions, preview, confirmation, result explanation | Inventing catalog/SLA/process, storing business state, authorizing operations |
| MCP Server | Tool discovery, authentication, identity mapping, normalization, domain-service calls, structured errors, audit | Direct table writes, bypassing RBAC/state machines, exposing secrets or general HTTP/SQL |
| ITOM | Sole source for catalog, forms, SLA, dispatch, workflow, permissions, records, ratings, and audit | Delegating authorization or final business state to an LLM |
| Feishu platform | Aily conversation, identity/organization, bot messaging, static knowledge, later approvals | Treating external payloads as trusted business facts |

The web agent adds a web-session adapter, model gateway, capability registry, orchestration, and safe knowledge retrieval without changing these responsibilities. Web identity remains isolated from Aily identity; models never write tables; ITOM domain services, RBAC, data scope, workflow, confirmation, idempotency, and audit remain authoritative.

Static IT knowledge is provided through Aily's Feishu knowledge-base integration, not duplicated by V1 MCP. Feishu Approval is deferred to phase 3; ITOM still validates and persists final workflow state.

### 4.2 Proactive-notification boundary

MCP is an Aily-initiated tool channel. A background ticket transition does not wake Aily merely because MCP exists. Proactive communication therefore uses the reliable outbox and Feishu bot messaging. The user's reply returns through Aily and MCP for confirmation, reopen, or rating. Feishu Helpdesk is not used.

## 5. Catalog, forms, workflow, and dispatch

### 5.1 Service item

In addition to current name, catalog, description, SLA, owner, and target audience, a service item gains:

- search keywords, synonyms, typical scenarios, and exclusions;
- active form version;
- bound process definition;
- dispatch rule;
- approval requirement and default-priority rule.

### 5.2 Dynamic form

Forms are versioned. P1 currently supports short/long text, single/multi-select, number, date/datetime, person, department, and boolean fields; attachment and asset/CI fields are later extensions. Rules include required status, length/range, options, date bounds, people/department scope, conditional visibility/requiredness, and help text.

The ticket stores the form version, answers, and schema snapshot. Later service-item changes must not rewrite historical meaning. Web and MCP creation share the same form parser and validator.

### 5.3 Workflow and state

The service item binds the process directly instead of choosing only by `ticket_type`.

```text
new → processing → resolved → closed
                    └─ requester rejects resolution → processing
```

User-facing phases are Submitted → Dispatched → Accepted → Processing → Awaiting confirmation → Closed → Rated. Dispatch, acceptance, and rating are events/timestamps rather than mandatory primary states.

Response SLA ends at actual acceptance. Resolution SLA ends at `resolved`; requester-confirmation waiting time does not consume resolution SLA. Reopens are audited.

### 5.4 Dispatch

Dispatch precedence is:

1. service-item rule;
2. catalog default support group;
3. global IT service fallback group;
4. if nobody is available, preserve the ticket and alert an administrator—never lose it silently.

V1 uses auditable round-robin within a group and selects only active, on-duty members of that group. Authorized IT staff may reassign. ITOM records the rule, source, dispatch time, and acceptance time.

## 6. Identity, security, confirmation, and audit

1. Aily sends identity context through `x-aily-jwt`. First registration permits only enabled, Origin-allowlisted, read-only protocol discovery because `identityJWTSecret` appears after creation; every tool execution still validates HS256, expiry, mandatory claims, and all allowlists. User identity accepts both the documented `user_id` and the real-request `feishu_open_id` claim.
2. External identities map to active ITOM accounts by provider, tenant, app, subject type, and subject ID. A JWT-verified but unapproved identity is only a pending candidate and is never auto-authorized.
3. OAuth-app and Aily-bot `open_id` values are stored separately; cross-app equality is never assumed.
4. Every user-scoped tool runs existing RBAC, data-scope, and workflow checks as the mapped `AuthUser`.
5. Mutations use preview → user confirmation → confirmation intent plus idempotency key. The intent binds user, tool, normalized parameter digest, and expiry.
6. Tool audit captures user, tenant, agent, tool, call ID, redacted parameter digest, result, entity, duration, and time without secrets or full sensitive payloads.
7. App Secret, MCP JWT Secret, and bot credentials never appear in URLs, prompts, tool results, logs, commits, or fixtures.

## 7. V1 MCP tools

### 7.1 Service request

- `search_service_items`
- `get_service_item_form`
- `prepare_service_request`
- `submit_service_request`
- `get_my_service_request`
- `list_my_service_requests`

The six tools above are implemented in P1; the following three closure tools are implemented in P2:

- `get_my_pending_confirmations`
- `confirm_service_request_resolution`
- `rate_service_request`

### 7.2 IT requirement

- `get_it_requirement_form`
- `prepare_it_requirement`
- `register_it_requirement`
- `get_my_it_requirement`
- `list_my_it_requirements`

V1 does not expose incident/change creation, arbitrary state transitions, reassignment/approval/task completion, generic SQL/database access, or general HTTP. IT staff continue to process work in the ITOM web application.

## 8. Target data changes

### 8.1 Removed Helpdesk data

The code model removes `feishu_helpdesk_handoff`, `feishu_helpdesk_intake`, `feishu_helpdesk_sync_event`, `feishu_helpdesk_outbox`, and all Helpdesk fields from `feishu_config`. The user confirmed that there is no valuable production history, so no archive is required. Existing PostgreSQL structures are previewed with `python -m app.scripts.migrate_aily_mcp` and permanently removed only with `--confirm`.

### 8.2 New support models

- `external_identity`: multi-app/multi-tenant identity mapping;
- `aily_integration_config`: encrypted Aily/MCP and bot messaging configuration;
- `mcp_tool_call`: tool-call audit;
- `mcp_operation_intent`: mutation preview, confirmation, idempotency, and execution result.

Extend `notification_outbox` with recipient, idempotency key, retry count, next retry, provider message ID, redacted error, and send timestamps.

### 8.3 New ITSM models

- `service_item_form_version`: versioned form and JSON Schema [implemented in P1];
- `service_dispatch_rule`: item/catalog/global dispatch rules [implemented in P1];
- `ticket_satisfaction`: one effective rating with score/tags/comment/source/audit [implemented in P2].

P1 extends `service_item` with search metadata, active form, bound process, and default priority. Dispatch resolves through `scope_type + scope_id`. P1 extends `ticket` with form answers/schema snapshot, dispatch facts, and suspected-major-impact. P2 stamps `accepted_at` on first processing entry and derives `confirmation_due_at` from the final requester task SLA. The effective rating also updates the compatibility `ticket.satisfaction` score.

## 9. Feishu Helpdesk removal

P0 removes Helpdesk routers, services, background scans, event subscriptions, models, configuration, admin UI, handoff pages/routes, handoff logic in ticket/requirement pages, and Helpdesk-only tests. Current docs retain only frozen-baseline and explicit-cleanup references.

Retain Feishu OAuth, workplace app login, organization sync, directory access, the generic `FeishuClient`, and bot-messaging capability. The frozen version remains recoverable from `v1.0.0-feishu-helpdesk`.

## 10. Implementation phases and acceptance

### Phase 0: protocol and foundation

**Current state: code, automated verification, the real Aily tenant identity path through ngrok `/mcp/`, and live bot-recipient verification are complete.**

- remove the Helpdesk runtime and data model;
- embed MCP and expose `/mcp` through Nginx;
- implement Aily JWT, identity mapping, tool audit, and proactive bot messaging;
- validate with local Docker, ngrok, and the real Aily tenant.

Verified: the Aily custom MCP uses Streamable HTTP and points to the canonical ngrok `/mcp/` URL with its trailing slash; live testing showed that omitting the slash fails Aily's save-time configuration validation. The P0 agent configuration is published to the current test account. First-registration discovery works before the Aily JWT secret is available, while `tools/call` still rejects missing JWT, unmapped users, wrong tenants, and wrong origins. A real Aily JWT passes signature, tenant, agent, and `feishu_open_id` validation; an observed pending identity can be approved and mapped by an ITOM administrator. `get_current_user_context` maps the correct account and writes redacted audit, while the final Aily response contains only verification result, account status, and a readable account name—never open_id, tenant_id, agent_id, or an internal ITOM primary key. Bot credentials, reliable outbox, idempotency, Feishu send result, and live receipt in the normal user's client are verified; no Helpdesk runtime entry remains.

Local acceptance snapshot on 2026-07-29: the full backend regression suite reported `260 passed`; the focused P0 MCP suite reported `8 passed`; the production frontend image built successfully; the Docker Compose database, backend, and port-8180 frontend were healthy; model metadata contained 78 tables while Helpdesk tables and columns both returned `NONE`; local and ngrok-public `/api/health` returned HTTP 200; and a real Aily preview call reached `/mcp`, mapped the identity, and passed the no-system-identifier disclosure check. The current identity mapping is for local development only and must be rebound to the real ITOM account in production. This snapshot does not replace P1–P3 multi-role business-flow or IDC acceptance.

Feishu-side cleanup confirmation on 2026-07-29: the administrator removed the legacy Helpdesk event subscriptions and card callback in the Open Platform console and published a new app version. The backend last received the retired `/api/integrations/feishu/helpdesk/events` request at 21:59:24, when the removed route correctly returned 404; as of 22:22:20, no further `/helpdesk/events` or `/helpdesk/card-callback` request appeared. `/mcp/` calls remained normal and the frontend-proxied `/api/health` path succeeded, confirming that the external cleanup did not disrupt Aily MCP or the active ITOM runtime. Feishu login, directory, and Approval were outside this deletion scope and remain subject to their own stage acceptance.

### Phase 1: request and requirement intake

**Current state: code, automated MCP/API acceptance, the production frontend build, and real Aily form → preview → explicit confirmation → write → own-record-query UAT are complete for both service requests and IT requirements.**

- dynamic forms, search metadata, process/dispatch binding;
- service-item search, form retrieval, preview, confirmation, and submission;
- requirement form, preview, registration, and own-record queries;
- normal users cannot create incidents.

P1 local acceptance snapshot on 2026-07-29: the full backend suite reported `267 passed`, the focused P1 Streamable HTTP suite reported `5 passed`, and the production frontend build succeeded. Docker Compose migrations completed; model metadata and PostgreSQL both contain 80 tables; all 32 existing service items have a published form and `sr_flow`; and local port 8180 plus ngrok-public `/api/health` both returned HTTP 200. After Aily re-saved the canonical `/mcp/` URL, it discovered 12 tools and made real search, form, preview, and confirmed-submit calls. Test ticket `TK-202607-0001` was created exactly once as a P3 `service_request` in New status with its form version/schema snapshot and a running process instance. Because no explicit dispatch rule exists, it correctly entered the unassigned manual fallback queue. An administrator then configured active domain `bsz_sc` (供应链服务域 / Supply Chain Service Domain). Aily re-read the live requirement form, returned only that domain, and completed preview plus explicit confirmation. `RQ-202607-0001` was created exactly once as a Function requirement in `evaluating` status, started a running `requirement_flow`, and generated/assigned its first “business-domain owner review” task. The creation audit and consumed idempotency intent are present, the same title produced zero `ticket` rows, and `get_my_it_requirement` returned the same title, domain, and status. This verifies that a normal-user requirement does not fall through to `service_request`; both P1 real-Aily write paths have passed UAT.

Acceptance: results come from the live catalog; audience/form validation works; retrying a confirmed submission creates one record; the request starts the right process and dispatch; the requirement enters requirement management.

P1 automated snapshot on 2026-07-29: full backend regression reported `267 passed`; five real Streamable HTTP MCP contract tests cover discovery, audience isolation, shared web/MCP form validation, short-lived confirmation, retries, process binding, dispatch, requirement workflow, and cross-user denial; the TypeScript/Vite production image built successfully; model metadata contains 80 tables. This complements the real Aily evidence above but does not replace P2 multi-role closure UAT or final IDC acceptance.

### Phase 2: service closure loop

**Current state: the P2 text-interaction loop has completed code, automation, the production frontend build, local Docker/ngrok, real-Aily multi-role conversation, normal-user identity, live bot receipt, and a normal-user same-ticket end-to-end run. P2.1 is now based on Feishu's new signed `card.action.trigger`: ordinary conversation remains MCP-only, while card buttons are the sole exception and ITOM verifies the signature and clicker identity before calling the same domain services. Automation covers signature/decryption, the unresolved-reason form, cross-user denial, reopen, close, rating, and idempotency. The live signed-button loop has passed.**

- actual acceptance and confirmation deadlines come from workflow execution;
- `get_my_pending_confirmations`, `confirm_service_request_resolution`, and `rate_service_request` enforce own-record scope and an explicit ticket code;
- unresolved feedback rewinds to the nearest handling step; obsolete tasks are soft-deleted for audit, and the next resolution refreshes the user-visible `solution` from the latest active handling note; web and MCP share semantics, and administrators cannot confirm for the submitter;
- acceptance, resolution, reopen, closure, and rating write the reliable Aily outbox; each confirmation cycle sends one reminder at 80% of its deadline window; disabled bot configuration preserves pending messages without consuming retries;
- when bot credentials, Verification Token, and Encrypt Key are ready, resolution/reminder notifications become close/reopen cards and closure becomes a 1–5-star card; incomplete configuration falls back to text. Unresolved first opens a required reason form, and every card action passes Feishu signature verification, clicker mapping, and the same ITOM domain rules;
- one effective `ticket_satisfaction` row stores score/tags/comment/source/audit and updates the compatibility score;
- direct confirmation/reopen/rating uses same-transaction idempotency: identical replay succeeds, while same-key/different-payload conflicts.

P2 automated snapshot on 2026-07-29: the full backend suite reports `270 passed`; focused P1+P2 regression reports `8 passed` (three P2 tests), covering discovery, acceptance/resolution timing, pending lists, idempotent 80% deadline reminders, cross-user denial, explicit-ticket reopen, workflow rewind and latest-solution refresh, replay, closure, rating create/update, key conflict, shared web/MCP semantics, no administrator proxy confirmation, outbox counts, and non-disclosure of internal information. The TypeScript/Vite production image builds successfully. Local Docker model metadata and PostgreSQL both contain 81 tables including `ticket_satisfaction`; local 8180 and ngrok-public health checks pass, and public `/mcp/` returns 15 tools.

P2 real-Aily conversational UAT on 2026-07-29: Aily reloaded and displayed 15 tools. `get_my_pending_confirmations` first returned an empty list, then returned `TK-202607-0001`, its solution, and confirmation deadline after the IT role accepted and resolved it through the application workflow. The user invoked `confirm_service_request_resolution(resolved=false)` through Aily, moving the ticket back to `processing` with reopen count 1. After another IT handling cycle, Aily confirmed resolution and closure, then `rate_service_request` saved five stars, the “Timely response / Professional resolution” tags, and a comment. ITOM ended with `closed`, one `ticket_satisfaction(source=aily)` row, and acceptance/resolution/reopen/closure/rating events in the reliable outbox. Regression ticket `TK-202607-0002` further proved that the pre-reopen “first handling” note was excluded: Aily returned only “second handling: internal routing added and access restored,” then closed and rated the ticket successfully. The IT handler is `it_op1`.

Later that day, the real Aily external identity was rebound from local `admin` to the normal user `xiongjun`. After the agent page was refreshed, a live `get_current_user_context` call returned the readable account name “熊军” and active status; the persisted mapping, last-used timestamp, and successful MCP audit agree. Its recipient identifier is an Aily-agent-scoped `open_id`, which is not assumed equal to the ITOM login application's `open_id`. The bot remains `message_enabled=false` without credentials proven to match that identity scope, so proactive rows remain `pending` and actual delivery is not claimed. Final acceptance still requires bot credential, recipient-identity, and delivery verification.

Proactive-message integration on 2026-07-30: credentials for the Feishu application bound to Aily passed the Feishu tenant-token call. Before enabling delivery, 15 historical unsent P2 UAT rows were soft-deleted with an audit record to prevent a bulk accidental send. Proactive messaging was then enabled and exactly one controlled test message was sent to the active identity mapped to `xiongjun`. Feishu returned a provider message ID; the ITOM outbox is `sent`, the latest test status is `success`, no redacted error remains, and the user confirmed that the message was visible in the Feishu client. Live bot receipt has passed; this evidence does not replace the final normal-user same-ticket business loop from creation through rating.

Normal-user same-ticket loop on 2026-07-30: `xiongjun` created `TK-202607-0003` through real Aily (Wireless LAN, “MacBook cannot connect to corporate Wi-Fi,” P2). After IT accepted, handled, and resolved it, both `ticket.accepted` and `ticket.resolved` were delivered by the bot. The normal user then confirmed resolution/closure through Aily and submitted five stars. ITOM ended at `closed` with one effective `score=5/source=aily` rating, while MCP audits for both `confirm_service_request_resolution` and `rate_service_request` succeeded. The P2 text-interaction normal-user end-to-end acceptance is therefore complete.

P2.1 first design and rejection evidence on 2026-07-30: the server initially generated buttons under Aily's `trigger_skill` contract, the online Skill reached `1.0.2`, its real `skill_*` was configured, and a close/reopen card was sent for `TK-202607-0004`. When `xiongjun` clicked unresolved, Aily did not ask for a reason. A follow-up Workflow plus real ngrok/backend inspection proved that Workflow custom-MCP requests contained no `x-aily-jwt` and, in debug, no authorizable user headers. ITOM correctly rejected them with 403, while the Workflow could still emit raw function-call text or an incorrect success message. Because this path cannot prove the clicker identity, MCP JWT was not weakened and the path is no longer used for card mutations. The Workflow draft was not published; the old Skill may remain as historical evidence but is not a runtime dependency.

P2.1 formal replacement on 2026-07-30: card buttons alone use Feishu Open Platform's new `card.action.trigger` Webhook at `/api/integrations/feishu/card-actions`. For business callbacks, the server verifies the SHA-256 signature over the raw body, enforces a five-minute age limit, decrypts AES-256-CBC/PKCS#7, then validates Verification Token, Bot App ID, tenant allowlist, and the clicker's explicit external-identity mapping. Live setup proved that Feishu sends an encrypted `url_verification` without signature headers while saving the Webhook URL. That read-only challenge is returned only after successful decryption, exact type matching, and Verification Token validation; `card.action.trigger` signature requirements are never relaxed. The first unresolved click returns a required reason form; submission, close, and 1–5-star rating all call the existing `service_request_closure`, preserving RBAC, own-record scope, workflow state, idempotency, and audit. Two encrypted configuration fields replace `card_action_skill_id`, and the admin API exposes configured flags only. Focused automation covers unsigned encrypted challenge, missing/invalid signatures for business callbacks, cross-user denial, missing reason, reopen and replay, close and replay, and rating source.
P2.1 button-integration fix on 2026-07-30: real Aily card-click requests carried a complete signature, but `X-Lark-Request-Timestamp` used a timezone-bearing Go monotonic-clock string; accepting only Unix numeric timestamps caused ITOM to return `FEISHU_CARD_SIGNATURE_INVALID`, which Feishu displayed as `200671`. The implementation now accepts that observed format while retaining the five-minute age check; signature calculation and business-authentication boundaries are unchanged, and a regression test covers the format.
P2.1 tenant-identifier integration fix on 2026-07-30: after the timestamp fix, a real unresolved click reached ITOM and passed signature, Bot App, and callback-internal tenant-consistency checks, but the business Toast said that the callback tenant was not authorized. Redacted diagnostics proved that callback `tenant_key` differed from Aily JWT `tenant_id`, while the same clicker's `open_id` uniquely mapped to the active `xiongjun` account under an authorized Aily tenant. These fields therefore occupy different identifier namespaces. The server no longer forces string equality: when the callback tenant does not directly match the allowlist, the clicker must uniquely anchor, within allowed Agent/Bot apps, to an active ITOM identity under an authorized Aily tenant. Signature, Verification Token, Bot App, callback-internal tenant consistency, own-record scope, RBAC, state, idempotency, and audit remain unchanged; an unknown cross-namespace clicker is still denied. Focused regression covers both an authorized mapping with a distinct `tenant_key` and rejection of an unmapped one.
P2.1 response-protocol integration fix on 2026-07-30: after the tenant-identifier fix, a real click completed ITOM authorization and business handling, and the backend returned HTTP 200 plus a complete reason form within three seconds, but Feishu displayed `200672`. The raw ngrok response proved that the server had placed card JSON directly under `card`; immediate updates for the new `card.action.trigger` contract require `card.type=raw` with the complete card under `card.data`. Reason-form, reopen-result, close-result, and rating-result responses now share that envelope and have explicit structural assertions. Business errors remain Toast-only and preserve the original card. Focused tests report `5 passed` and the full backend suite reports `276 passed`. After deployment, an encrypted, signed, cross-tenant-namespace but valid-clicker read-only reason-form probe traversed ngrok and returned HTTP 200 in 1.392 seconds; assertions passed for `card.type=raw`, `card.data`, the required input, and `form_submit`, while `TK-202607-0005` still had `resolved/reopen_count=0` at that point.

P2.1 final live-button UAT on 2026-07-30: normal user `xiongjun` completed “unresolved → enter reason and reopen → IT resolves again → resolved and close → five-star rating” for `TK-202607-0005` in the Feishu client. The user confirmed the client-side loop passed. ITOM data verification shows `status=closed`, `reopen_count=1`, `ticket.satisfaction=5`, and one effective rating row with `score=5/source=feishu_card`. The live signed-card P2.1 loop is therefore accepted.

IDC platform-path snapshot on 2026-07-30: the current Aily + MCP images were deployed through the repository Kubernetes flow with backend 1/1 and frontend 2/2 replicas available. A real MCP `initialize` at `https://itom.snnc.cc:30443/mcp/` returned HTTP 200, and Feishu Open Platform's encrypted `url_verification` challenge at `https://itom.snnc.cc:30443/api/integrations/feishu/card-actions` also returned HTTP 200; the callback configuration was saved and published. This proves the IDC public route, MCP protocol endpoint, and card-challenge path, not formal release acceptance. The public certificate still needs replacement by a trusted CA certificate, and security, performance, recovery, and IDC real-role business UAT remain separate acceptance work.

Public-base configuration regression on 2026-07-30: the complete backend suite reports `277 passed`. The focused `public_base_url` contract reports `1 passed`, covering trailing-slash normalization; rejection of paths, queries, fragments, URL credentials, invalid schemes, and out-of-range ports; preservation of the saved value after rejection; and clearing the configuration. The frontend linux/amd64 production image completed `tsc --noEmit` and the Vite build. `git diff --check`, Kubernetes YAML parsing, and deployment-script syntax checks all passed.

Problem review and fix on 2026-07-31: `/api/dashboard` had omitted `contribution_bucket=team_contribution` while aggregating people points, so project-manager milestone and other `role_result` ledger rows were added to team-contribution points; the team overview already used the correct bucket, producing different values. The Dashboard query now applies the same bucket condition, and `test_activity_points_exclude_role_result_entries` asserts that `role_result=50` plus `team_contribution=7` displays 7 in both views. No data-model or historical-ledger change is required.

IDC callback recheck on the same day: `https://itom.snnc.cc:30443/api/health` fails normal certificate verification with `unable to get local issuer certificate` and returns HTTP 200 only with verification disabled; no `card-actions` POST reached the backend/frontend ingress logs during the check, and the current IDC database does not contain the old screenshot tickets `TK-202607-0004/0005`. Therefore Aily's current `200080` cannot be attributed to `service_request_closure` business logic yet. A publicly trusted CA certificate for `itom.snnc.cc:30443` must be installed first, followed by a new current-IDC ticket/card retest. The old `TK-202607-0005` button loop remains historical UAT evidence and does not prove the current IDC card path is healthy.

Acceptance: a business user and IT staff complete request → dispatch → accept → resolve → notify → confirm/reopen → close → rate. Multiple pending confirmations do not cross-link, and internal information is not sent externally.

### Phase 3: Feishu Approval (deferred) and release hardening

- connect selected ITOM approval steps to Feishu Approval with bidirectional idempotency (deferred by user decision and not blocking current release hardening);
- install trusted TLS and complete IDC security, performance, recovery, and real-role UAT;
- open a user-approved PR from `feature/AI-agent-version` to `main`.

## 11. Definition of done

Each change includes implementation, tests, authoritative Chinese docs, and matching `docs/en` mirrors. The feature branch must first pass GitHub Actions for relevant unit, API/MCP integration, identity/permission, idempotency/retry tests, the production frontend build, and repository-contract checks. Automation never targets the IDC business database. No local application environment is started unless the user explicitly requests isolated troubleshooting. Releases come from clean commits, use Git-SHA-derived immutable linux/amd64 images, and complete rollout, image, health-path, MCP, and real-role acceptance in IDC.

A green CI run, successful image build, `/api/health`, MCP initialization, one successful tool call, or simulated payloads are not full business acceptance. Evidence must cover real identity and a multi-role business loop.

## 12. Maintenance

This file is the current final design baseline. Any decision changing routing, tool contracts, identity, security, data, messaging, deployment, or acceptance must update this file, `docs/03–06`, README, and English mirrors in the same change. After code delivery, target statements must be reconciled with real implementation and verification evidence.
