# ITOM Web Agent Design Baseline

> Status: **design approved; WA0 Tasks 1–6 implemented with Task 6 Fix Round 2 complete; Task 7+ pending**
> Approval date: 2026-08-01
> The Chinese document is authoritative; this is its English mirror.

## 1. Purpose

Most ITOM users have little ITIL knowledge. A normal employee should not need to understand service-request, incident, problem, change, requirement, and project boundaries before using the service. IT staff also need role-aware help based on their current page and workflow work.

This design introduces the **ITOM Assistant** with two isolated entrances and one shared capability core. Feishu Aily keeps its existing normal-user MCP entrance, while the ITOM web application adds a conversation entrance based on the current login session. They do not share an authentication protocol, but they reuse ITOM domain services, form validation, permission, data scope, workflow, confirmation, idempotency, and audit. ITOM remains the sole source of business truth.

- A normal business user works only with own service requests.
- A BDO may additionally register and follow own IT requirements.
- IT staff receive system-wide guidance and progressively enabled operations, always filtered by effective role, permission, data scope, and workflow task.
- Administrators may configure models, profiles, knowledge scope, and maximum action level, but model configuration never grants business permission.

## 2. Mandatory architecture rules

1. **Two entrances, isolated identity**: web uses the ITOM login; Aily retains `x-aily-jwt`, tenant/Agent/Origin allowlists, and external-identity mapping. Web never calls the public `/mcp/` as its own backend.
2. **Shared domain capability**: both entrances reuse domain services rather than copying catalog, form, workflow, state, or authorization rules.
3. **The model does not authorize**: it understands, summarizes, asks, and orchestrates. The server recalculates permission, data scope, record state, and workflow assignment for every capability call.
4. **The model never writes tables**: all reads and mutations pass through registered capabilities and domain services. No general SQL, HTTP, shell, filesystem, or raw database tool exists.
5. **Controlled writes**: create/edit/assign/transition/confirm/close first produces a server preview, then requires explicit user confirmation and idempotent execution.
6. **Only the server declares success**: UI success states require a successful domain result; model prose is not a business result.
7. **Safe degradation**: the existing deterministic Record Creation Guide remains as a fallback when the model is unavailable.
8. **Existing Aily scope is unchanged**: internal web capabilities are not automatically exposed to normal-user MCP.

## 3. Architecture and responsibilities

```text
Feishu Aily ─ x-aily-jwt ─▶ existing Aily MCP adapter ─┐
                                                       ├─▶ shared assistant capability layer
ITOM web ─ login/Bearer ─▶ web-session adapter ───────┘       │
                                                              ├─ identity/policy context
                                                              ├─ orchestrator
                                                              ├─ model gateway
                                                              ├─ safe knowledge retrieval
                                                              └─ capability registry
                                                                      │
                                                                      ▼
                                                        ITOM domain services / RBAC /
                                                        data scope / workflow / audit
```

| Component | Responsibility | Forbidden |
| --- | --- | --- |
| Web adapter | Login identity, language, allowlisted page context, SSE | Trusting client-supplied roles or whole-page DOM |
| Aily MCP adapter | Existing Aily identity and normal-user contract | Becoming a general internal-staff channel |
| Orchestrator | Intent, clarification, capability selection, response composition | Changing business state by itself |
| Model gateway | Provider adaptation, streaming, timeout, fallback | Exposing secrets to browser or prompts |
| Capability registry | Permission, scope, schemas, risk, confirmation, handler | Letting the model compose arbitrary endpoints |
| Safe knowledge | Published module guidance and user-visible knowledge | Returning secrets, internal notes, or unauthorized data |
| Domain service | Forms, state, workflow, permission, idempotency, transaction | Bypassing current business rules |

## 4. User boundaries

**Requester**: eligible service-item search, real form, draft/preview/explicit submission, own request query/supplement, own confirmation/reopen/rating. No requirement, incident, problem, change, project, Bug, internal task, other-user data, internal note, root cause, or approval detail.

**BDO**: all requester capabilities plus real IT-requirement form, draft/confirmation/registration, and own requirement tracking. No review, project management, process monitoring, or IT-internal task authority follows from BDO.

**IT staff**: guidance for every actually accessible module, field and operation; record-type recommendation; own task and visible-record query; status/next-step explanation; draft and exact navigation. Mutations remain gated by the actual role, permission, data scope, and current process assignee. A persona changes wording, not authority.

**Administrator**: feature access and model governance, but business invariants remain. An administrator cannot confirm a service request for its submitter, use a prompt to expand a normal user's scope, or read back model/integration secrets.

## 5. Capability levels and registry

| Level | Type | Rule |
| --- | --- | --- |
| L0 | Concept/field/operation explanation and navigation | Direct response |
| L1 | Query inside current permission and data scope | Server authorization first |
| L2 | Classification, missing-field collection, draft and preview | No formal business write |
| L3 | Create/edit/assign/transition/confirm/close | Server preview, explicit confirmation, idempotent execution |
| L4 | Delete, bulk change, roles, workflow definition, secrets | Not exposed initially |

An administrator may lower a profile's maximum level or disable a capability, never raise it beyond the user's business authorization.

Every executable capability is code-registered with code/name, channel/audience, required permission, data-scope checker, allowed states, input JSON Schema, structured output, risk, confirmation and idempotency rules, domain handler, audit, timeout, and degradation. Every L3 handler separately implements pre-preview record authorization through `authorize_preview`, read-only `preview`, and confirmation-lock `authorize_record`; a missing method prevents registration. The database may disable registered capabilities but cannot invent executable handlers. The model receives only capabilities available for the current request.

## 6. Web experience

- Both the business portal and internal workbench expose a bottom-right **ITOM Assistant** button. Desktop uses a 440–520px right drawer; narrow screens use full-screen mode.
- Page context is allowlisted: route, page type, current entity type/ID, active tab, and an explicitly selected record. Whole-page DOM is never sent.
- Responses may contain explanation, rule source, next action, navigation, query result, missing fields, preview, and confirm/cancel cards.
- Native pages remain available. Assistant or model failure never blocks core ITOM use.
- Once mature, the current top Record Creation Guide is merged into the assistant entrance while its deterministic rules remain a fallback.

## 7. Model and profile governance

System Management gains an **AI Assistant** page separate from `aily_integration_config`. Administrators maintain provider type, API base, model, encrypted key, timeout, output limit, temperature, streaming/tool/structured-output support, primary/fallback relation, and enabled state. V1 prioritizes an OpenAI-compatible adapter; other protocols use separate adapters.

Pre-publish probes verify connectivity, auth, streaming, JSON Schema, tool calling, timeout, and sensitive-data echo. A model without tool/structured-output support is limited to L0/L1. Administration probing follows short locked configuration-revision snapshot → asynchronous network probe with no database transaction → short locked revision comparison and atomic persistence; a result after change or deletion is discarded.

Four profiles are preseeded: business user, BDO, IT staff, and administrator. Each has bilingual instructions, maximum level, enabled registered capabilities, knowledge scope, and response style with draft/test/publish/version/rollback. Every new version stores a complete schema-marked active-configuration snapshot; an unprovable legacy version cannot be rolled back or filled from current active settings. Profiles restrict; they do not authorize.

## 8. Target data and privacy

| Table | Purpose |
| --- | --- |
| `ai_provider_config` | Provider connection, encrypted secret, probes, primary/fallback, enablement |
| `ai_agent_profile` | Audience profile, active version, maximum level |
| `ai_agent_profile_version` | Versioned instruction/capability/knowledge settings and publish history |
| `ai_conversation` | Web session, user, language, allowlisted page context, lifecycle |
| `ai_message` | Redacted message, structured content, usage, latency |
| `ai_action` | Capability, risk, safe request digest, one-use confirmation, named idempotency uniqueness, result, business entity |
| `ai_provider_call` | Model, token, latency, result code, redacted error metadata |

Migration is additive only and does not rewrite historical business data, process instances, `AilyIntegrationConfig`, or `/mcp/`. The feature remains disabled until a provider test and profile publication succeed.

Web conversation retention defaults to 30 days and is configurable from 0–90 days. Users read only their own conversations. Administrators see operational metrics and action audit by default, not full transcripts. Ordinary conversation may be archived/deleted under policy; business-action audit follows the system audit policy. Passwords, tokens, secrets, cookies, auth headers, and sensitive form fields never enter model input, message storage, or ordinary logs.

## 9. Target APIs

```text
GET    /api/assistant/bootstrap
POST   /api/assistant/conversations
GET    /api/assistant/conversations
GET    /api/assistant/conversations/{id}
POST   /api/assistant/conversations/{id}/messages    # SSE
POST   /api/assistant/actions/{id}/confirm
POST   /api/assistant/actions/{id}/cancel
POST   /api/assistant/conversations/{id}/archive

GET/POST/PATCH /api/admin/ai/providers
POST           /api/admin/ai/providers/{id}/test
GET/PATCH      /api/admin/ai/profiles/{code}/draft
POST           /api/admin/ai/profiles/{code}/publish
POST           /api/admin/ai/profiles/{code}/rollback
GET            /api/admin/ai/health
GET            /api/admin/ai/usage
GET            /api/admin/ai/action-audits
```

Read APIs return only `has_secret`, never secret values. Bootstrap returns the current profile, available level, suggested questions, and retention policy without exposing the internal permission matrix or handler implementation.

## 10. Security and degradation

- Recheck active account, effective roles, permission, data scope, record state, and process assignment per call.
- Authorize an L3 preview before record metadata and run it in an independent Session that is always rolled back and closed. PostgreSQL is transaction-read-only; the handler sees only an immutable actor context plus `ReadOnlyActionData`, and raw Session/Engine/Connection/transaction surfaces, DML/text transaction statements, handler writes, flush, commit, and rollback all fail closed, while preview status must be exactly `prepared`.
- Reject normalized input if recursive redaction would change it. Never persist or execute the redacted substitute and never use it for the idempotency digest.
- Bind an L3 token to user, conversation, capability, normalized payload digest, and expiry; make it single-use.
- Use the named unique idempotency target; same-key/same-input returns only the winner without a new token, same-key/different-input is rejected, and state drift requires a new preview.
- Prepare relocks and refreshes the owned conversation row after preview and before action insert/idempotency-winner handling. Confirmation retains the action row lock, then locks and refreshes the owned conversation row, proves that the conversation-captured profile/version/provider remains runnable under the governance lock order, and gives record authorization/mutation only an immutable actor context plus `ActionUnitOfWork`. Domain mutation, success result, and audit stay in a nested savepoint; failure rolls back only that savepoint and lets the same outer transaction commit the bounded terminal fact. Conversation archive follows the same row-lock-and-refresh discipline before commit.
- Treat user text, knowledge, and record content as untrusted data that cannot override system instructions or capability boundaries.
- Allow only administrator-approved HTTPS model endpoints; redact credentials and sensitive answers.
- Model failure returns to deterministic guidance, search, and native pages. Invalid structure, timeout, or broken streaming never triggers a mutation.

SQLite automation proves only service-call order, rollback outcomes, injected races, and savepoint semantics. Task 9 IDC must add real two-Session PostgreSQL evidence: preview is read-only and rejects writes; same/different-payload preparation has one winner; a waiter after handler/audit failure sees `failed` with exactly one handler call; and failure-state commit faults are never reported as durable.
- Switch to a fallback model only when the same data policy applies; otherwise degrade safely.

## 11. Delivery phases and acceptance

The web-agent program uses `WA` identifiers so it cannot be confused with Aily P0–P3.

| Phase | Scope | Acceptance |
| --- | --- | --- |
| WA0 | Provider/probe, profile versions, conversation/message/action/call audit, registry, redaction, SSE | Disabled by default; no secret echo; historical data unchanged |
| WA1 | L0/L1 advisor, page explanation, record classification, navigation, own records/tasks/next step, deterministic fallback | Roles see only real authorization; model outage does not block native UI |
| WA2 | Requester request draft/submit/query/confirm/rate; BDO requirement draft/register/query | Reuse current domain services; normal users cannot create requirements/incidents; Aily regression unchanged |
| WA3 | High-value IT L3 actions: linked record creation, accept/assign/process/transition, Bug and task work | Every write previews/confirms; state/RBAC/workflow/idempotency/audit apply |
| WA4 | Quality, cost, latency, failure, evaluation sets, model comparison, knowledge governance | Measurable governance without replacing business UAT |

Automation covers requester, BDO, IT roles and admin; direct/group/inherited roles; capability isolation and data scope; L3 confirmation/expiry/retry/conflict; prompt injection; provider failure; redaction; retention; and full Aily MCP regression. IDC UAT proves that requester is service-request-only, BDO adds own requirements only, IT roles receive different capabilities, permission changes immediately narrow the agent, model publish/rollback works, fallback remains usable, action audit is traceable, and the existing Aily loop is unchanged.

This design excludes Feishu Approval P3, a general agent marketplace, autonomous multi-agent work, model approval, free SQL/HTTP/shell, bulk deletion, replacing the process engine, and exposing incident/problem/change/project creation to normal business users.
