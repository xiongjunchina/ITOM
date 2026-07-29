# ITOM Feishu Aily Agent + MCP Server Final Design Baseline

> Status: **formal baseline; P0/P1 complete; P2 code, automation, real-Aily conversational closure, and live bot receipt have passed separately; normal-user same-ticket end-to-end UAT remains**
> Approval date: 2026-07-29
> The Chinese document is authoritative. This file is its English mirror.

## 1. Purpose and status semantics

This document is the approved product and architecture baseline for the `feature/aily-agent-mcp` development line. It defines the goals, boundaries, tools, target data model, phases, and acceptance criteria. The implementation must not reintroduce Feishu Helpdesk or turn Aily, MCP, or Feishu into a second ITOM business system.

This document records both target contracts and actual status. The branch implements P0 protocol/identity/messaging foundations, P1 service-request and requirement intake, and P2 acceptance/confirmation timestamps, three closure MCP tools, shared web/MCP confirmation semantics, reliable user messages, and rating detail. The real-Aily conversational loop and live bot receipt have passed separately; a normal-user same-ticket end-to-end P2 run and P3 remain incomplete.

Before starting work, a new chat must read `AGENTS.md`, this document, `docs/03-PRD.md`, `docs/04-数据模型设计.md`, `docs/05-API契约与架构设计.md`, and `docs/06-用户身份与组织模型设计.md`, then inspect the real code and Git status.

## 2. Version and worktree baseline

| Object | Value | Constraint |
|---|---|---|
| Frozen commit | `f13f702` | Historical Feishu Helpdesk baseline |
| Historical tag | `v1.0.0-feishu-helpdesk` | Immutable recovery reference |
| Historical branch | `release/feishu-helpdesk-v1` | Historical inspection/maintenance only |
| Stable branch | `main` | Accepts only user-approved Pull Requests |
| New development branch | `feature/aily-agent-mcp` | Sole long-lived Aily + MCP development line |
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

## 4. Approved architecture

Use **Approach A: embed the MCP Server in the existing FastAPI backend**.

```text
Feishu user ⇄ Aily Agent
                  │  HTTPStreaming / x-aily-jwt
                  ▼
          Nginx :8180 /mcp
                  ▼
        MCP embedded in FastAPI
                  ▼
       ITOM domain services / RBAC / workflow / audit
                  ▼
                PostgreSQL

ITOM domain event → reliable notification outbox → Aily-bot Feishu message → user
User reply → Aily → MCP → ITOM confirmation, reopen, or rating
```

Local development uses Docker and an ngrok tunnel for the complete `127.0.0.1:8180` origin, including the frontend, `/api`, Feishu OAuth callback, and `/mcp`. IDC infrastructure is currently blocked; final release still requires the repository's Kubernetes acceptance flow.

### 4.1 Responsibility boundary

| Component | Responsible for | Forbidden |
|---|---|---|
| Aily | Intent understanding, candidate presentation, missing-field questions, preview, confirmation, result explanation | Inventing catalog/SLA/process, storing business state, authorizing operations |
| MCP Server | Tool discovery, authentication, identity mapping, normalization, domain-service calls, structured errors, audit | Direct table writes, bypassing RBAC/state machines, exposing secrets or general HTTP/SQL |
| ITOM | Sole source for catalog, forms, SLA, dispatch, workflow, permissions, records, ratings, and audit | Delegating authorization or final business state to an LLM |
| Feishu platform | Aily conversation, identity/organization, bot messaging, static knowledge, later approvals | Treating external payloads as trusted business facts |

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

**Current state: code, P1/P2 automation, the production frontend build, local Docker/ngrok, the real-Aily conversational closure loop, normal-user identity, and live bot receipt are complete. One same-ticket end-to-end run under the normal user remains.**

- actual acceptance and confirmation deadlines come from workflow execution;
- `get_my_pending_confirmations`, `confirm_service_request_resolution`, and `rate_service_request` enforce own-record scope and an explicit ticket code;
- unresolved feedback rewinds to the nearest handling step; obsolete tasks are soft-deleted for audit, and the next resolution refreshes the user-visible `solution` from the latest active handling note; web and MCP share semantics, and administrators cannot confirm for the submitter;
- acceptance, resolution, reopen, closure, and rating write the reliable Aily outbox; each confirmation cycle sends one reminder at 80% of its deadline window; disabled bot configuration preserves pending messages without consuming retries;
- one effective `ticket_satisfaction` row stores score/tags/comment/source/audit and updates the compatibility score;
- direct confirmation/reopen/rating uses same-transaction idempotency: identical replay succeeds, while same-key/different-payload conflicts.

P2 automated snapshot on 2026-07-29: the full backend suite reports `270 passed`; focused P1+P2 regression reports `8 passed` (three P2 tests), covering discovery, acceptance/resolution timing, pending lists, idempotent 80% deadline reminders, cross-user denial, explicit-ticket reopen, workflow rewind and latest-solution refresh, replay, closure, rating create/update, key conflict, shared web/MCP semantics, no administrator proxy confirmation, outbox counts, and non-disclosure of internal information. The TypeScript/Vite production image builds successfully. Local Docker model metadata and PostgreSQL both contain 81 tables including `ticket_satisfaction`; local 8180 and ngrok-public health checks pass, and public `/mcp/` returns 15 tools.

P2 real-Aily conversational UAT on 2026-07-29: Aily reloaded and displayed 15 tools. `get_my_pending_confirmations` first returned an empty list, then returned `TK-202607-0001`, its solution, and confirmation deadline after the IT role accepted and resolved it through the application workflow. The user invoked `confirm_service_request_resolution(resolved=false)` through Aily, moving the ticket back to `processing` with reopen count 1. After another IT handling cycle, Aily confirmed resolution and closure, then `rate_service_request` saved five stars, the “Timely response / Professional resolution” tags, and a comment. ITOM ended with `closed`, one `ticket_satisfaction(source=aily)` row, and acceptance/resolution/reopen/closure/rating events in the reliable outbox. Regression ticket `TK-202607-0002` further proved that the pre-reopen “first handling” note was excluded: Aily returned only “second handling: internal routing added and access restored,” then closed and rated the ticket successfully. The IT handler is `it_op1`.

Later that day, the real Aily external identity was rebound from local `admin` to the normal user `xiongjun`. After the agent page was refreshed, a live `get_current_user_context` call returned the readable account name “熊军” and active status; the persisted mapping, last-used timestamp, and successful MCP audit agree. Its recipient identifier is an Aily-agent-scoped `open_id`, which is not assumed equal to the ITOM login application's `open_id`. The bot remains `message_enabled=false` without credentials proven to match that identity scope, so proactive rows remain `pending` and actual delivery is not claimed. Final acceptance still requires bot credential, recipient-identity, and delivery verification.

Proactive-message integration on 2026-07-30: credentials for the Feishu application bound to Aily passed the Feishu tenant-token call. Before enabling delivery, 15 historical unsent P2 UAT rows were soft-deleted with an audit record to prevent a bulk accidental send. Proactive messaging was then enabled and exactly one controlled test message was sent to the active identity mapped to `xiongjun`. Feishu returned a provider message ID; the ITOM outbox is `sent`, the latest test status is `success`, no redacted error remains, and the user confirmed that the message was visible in the Feishu client. Live bot receipt has passed; this evidence does not replace the final normal-user same-ticket business loop from creation through rating.

Acceptance: a business user and IT staff complete request → dispatch → accept → resolve → notify → confirm/reopen → close → rate. Multiple pending confirmations do not cross-link, and internal information is not sent externally.

### Phase 3: Feishu Approval and release

- connect selected ITOM approval steps to Feishu Approval with bidirectional idempotency;
- complete IDC security, performance, recovery, and real-role UAT;
- open a user-approved PR from `feature/aily-agent-mcp` to `main`.

## 11. Definition of done

Each change includes implementation, tests, authoritative Chinese docs, and matching `docs/en` mirrors. Run relevant unit, API/MCP integration, identity/permission, idempotency/retry tests, and the production frontend build. Local phases use Docker + ngrok for real Aily integration; final release still requires IDC acceptance.

`/api/health`, one successful tool call, a successful build, or simulated payloads are not full business acceptance. Evidence must cover real identity and a multi-role business loop.

## 12. Maintenance

This file is the current final design baseline. Any decision changing routing, tool contracts, identity, security, data, messaging, deployment, or acceptance must update this file, `docs/03–06`, README, and English mirrors in the same change. After code delivery, target statements must be reconciled with real implementation and verification evidence.
