# ITOM Web Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a role-aware ITOM web assistant without changing the normal-user Aily MCP boundary, then deliver model governance, read-only advice, business-user loops, controlled IT-staff writes, and quality governance through WA0–WA4.

**Architecture:** The web assistant accepts only the current ITOM Bearer identity through an independent `/api/assistant` adapter. Aily retains `x-aily-jwt` and `/mcp/`. The model selects only code-registered capabilities; every read and write is rechecked by ITOM permission, data scope, record state, workflow assignment, domain services, confirmation, idempotency, and audit.

**Tech Stack:** Python 3.12, FastAPI 0.115, SQLAlchemy 2, Pydantic 2, PostgreSQL 16/SQLite tests, httpx, React 18, TypeScript 5.7, Ant Design 5, Axios/fetch SSE, pytest, Vite, and IDC Kubernetes.

## Global Constraints

- Before code changes, the worktree is clean, the branch is `feature/aily-agent-mcp`, and it is synchronized with `origin/feature/aily-agent-mcp`; only a user-approved PR may merge into `main`.
- IDC Kubernetes is the sole runtime, integration, and acceptance environment. Local execution is limited to temporary-SQLite automation and the frontend production build; do not start the Docker/Compose ITOM stack.
- ITOM domain services and APIs remain the sole source of business state, permission, and workflow. A model, prompt, profile, or hidden UI element never grants authority.
- Web and Aily identities remain isolated. Web does not call the public `/mcp/`, and web capabilities do not enlarge Aily's tool list.
- Every L3 write first produces a server preview, then requires explicit confirmation by the actor. The single-use token defaults to ten minutes and binds user, conversation, capability, and normalized payload digest.
- Do not register L4 delete, bulk change, role/permission, process-definition, or secret operations.
- API keys, tokens, secrets, cookies, Authorization, passwords, and form fields marked sensitive never enter a model, message content, ordinary logs, or API reads.
- Migration adds tables, columns, indexes, and default permission only. It does not backfill, recalculate, or rewrite business records, process instances, Aily identities, MCP intents, or MCP audit.
- Each phase is complete only with implementation, automation, authoritative Chinese docs, matching `docs/en`, production frontend build, and IDC acceptance.
- Stage only listed files, never `git add -A`; every independently reviewable task uses a Conventional Commit.

## Locked File Structure

### New backend files

- `backend/app/models/assistant.py`: the seven AI configuration, conversation, message, action, and provider-call models.
- `backend/app/schemas/assistant.py`: Pydantic contracts for web assistant, action confirmation, and admin configuration.
- `backend/app/assistant/types.py`: channel, audience, risk, model-event, and capability-result types.
- `backend/app/assistant/redaction.py`: model-input, persistence, and log redaction.
- `backend/app/assistant/registry.py`: code capability registry and JSON Schema export.
- `backend/app/assistant/policy.py`: capability trimming by user, permission, data scope, state, and workflow assignment.
- `backend/app/assistant/providers/base.py`: provider protocol.
- `backend/app/assistant/providers/openai_compatible.py`: OpenAI-compatible stream, tool, and structured-output adapter.
- `backend/app/assistant/gateway.py`: primary/fallback selection, timeout, safe fallback, and call audit.
- `backend/app/assistant/orchestrator.py`: instruction boundaries, tool loop, follow-up questions, and SSE events.
- `backend/app/assistant/capabilities/guidance.py`: module definitions, record recommendation, and navigation.
- `backend/app/assistant/capabilities/queries.py`: own/visible records and actionable-task queries.
- `backend/app/assistant/capabilities/service_requests.py`: requester service-request draft and loop.
- `backend/app/assistant/capabilities/requirements.py`: BDO requirement draft and registration.
- `backend/app/assistant/capabilities/it_operations.py`: linked creation, workflow, ticket, Bug, and task actions.
- `backend/app/services/assistant_config.py`: provider and profile draft/publish/rollback.
- `backend/app/services/assistant_conversations.py`: ownership, message persistence, archive, and retention.
- `backend/app/services/assistant_actions.py`: L3 preview, confirmation, idempotency, re-authorization, and result audit.
- `backend/app/services/assistant_knowledge.py`: safe retrieval of published, actor-visible knowledge.
- `backend/app/services/process_actions.py`: shared domain entry points for API and assistant workflow actions.
- `backend/app/services/ticket_actions.py`: shared domain entry points for ticket assignment and transition.
- `backend/app/services/record_conversion.py`: shared prepare/create-and-link domain entry point.
- `backend/app/routers/assistant.py`: `/api/assistant` web conversation and SSE API.
- `backend/app/routers/admin_ai.py`: `/api/admin/ai` provider, profile, health, usage, and audit API.

### New frontend files

- `frontend/src/api/assistant.ts`: authenticated POST-SSE client.
- `frontend/src/components/assistant/AssistantLauncher.tsx`: global launcher.
- `frontend/src/components/assistant/AssistantDrawer.tsx`: desktop drawer/mobile full-screen shell.
- `frontend/src/components/assistant/AssistantMessageList.tsx`: text, source, result, and error events.
- `frontend/src/components/assistant/AssistantActionCard.tsx`: L2 preview and L3 confirm/cancel states.
- `frontend/src/components/assistant/AssistantContext.ts`: whitelisted page context.
- `frontend/src/components/assistant/assistant.css`: local assistant styles.
- `frontend/src/pages/admin/AiAssistant.tsx`: providers, profiles, health, usage, and action audit.
- `frontend/src/i18n/locales/assistant.ts`: complete Chinese and English strings.

### Existing files changed only within their current responsibility

- Models/migration/permission: `backend/app/models/__init__.py`, `services/migrate.py`, `services/permissions.py`.
- Security/runtime/router: `core/config.py`, `main.py`, `routers/__init__.py`, `services/scheduler.py`.
- Shared domain extraction: `routers/process.py`, `tickets.py`, `record_relations.py`.
- Frontend integration: `api/types.ts`, `router.tsx`, `components/MainLayout.tsx`, `components/menu.tsx`, `styles.css`, i18n indexes/dictionaries.
- Tests: `backend/tests/test_wa0_*.py` through `test_wa4_*.py`; they use temporary SQLite and never IDC business data.
- Delivery docs: README and matching Chinese/English PRD, data model, API/architecture, identity, and handover documents.

---

### Task 0: Git and IDC data-safety preflight

**Files:** Read-only Git, Actions, and IDC state.

**Interfaces:**
- Consumes: approved design commit `fe478a0` plus the plan commit.
- Produces: clean/synchronized feature branch, green baseline gate, and approved database backup/checkpoint evidence.

- [ ] **Step 1: Verify branch and worktree**

```bash
git branch --show-current
git status --short
git rev-list --left-right --count HEAD...origin/feature/aily-agent-mcp
```

Expected: feature branch and no local changes. If local is ahead, push only the feature branch.

- [ ] **Step 2: Push the documentation baseline and wait for the gate**

```bash
git push origin feature/aily-agent-mcp
gh run list --branch feature/aily-agent-mcp --workflow "ITOM Quality Gate" --limit 1
```

Expected: backend, frontend, and repository-contract all pass; otherwise stop before coding.

- [ ] **Step 3: Record current IDC evidence read-only**

```bash
curl --noproxy '*' --fail --silent --show-error https://itom.snnc.cc:30443/api/health
```

Record current images, Ready Pods, PostgreSQL PVC, and recovery point without printing secrets.

- [ ] **Step 4: Complete the approved in-cluster PostgreSQL backup/checkpoint before Task 1 deployment**

Record backup path, time, PostgreSQL version, checksum, and restore command in the approved IDC operations location. Do not deploy the schema release without recovery evidence.

---

### Task 1: WA0 models, migration, and permission module

**Files:**
- Create: `backend/app/models/assistant.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/services/migrate.py`, `backend/app/services/permissions.py`
- Test: `backend/tests/test_wa0_assistant_models.py`
- Docs: bilingual data-model and identity documents.

**Interfaces:** Produces the seven `Ai*` models and `admin_ai`; consumes `GlidBase`, `JsonCol`, `AuthUser`, and startup migration.

- [ ] Write the failing additive/default-disabled model test.

```python
def test_wa0_models_are_additive_and_disabled_by_default(client):
    provider = AiProviderConfig(code="primary", name="Primary", provider_type="openai_compatible")
    profile = AiAgentProfile(code="requester", audience="requester")
    db.add_all([provider, profile]); db.commit()
    assert provider.enabled is False and profile.enabled is False
```

- [ ] Create focused models with explicit foreign keys, status fields, indexes, and unique `(auth_user_id, capability_code, idempotency_key)` on `AiAction`.
- [ ] Add idempotent PostgreSQL `ensure_assistant_schema(db)`; test that an existing Ticket is unchanged.
- [ ] Add `admin_ai` without granting it to requester, BDO, IT staff, or auditor defaults.
- [ ] Run `cd backend && python -m pytest tests/test_wa0_assistant_models.py -q && python -m pytest -q`.
- [ ] Update bilingual data/identity docs and commit `feat(agent): add WA0 persistence foundation`.

---

### Task 2: WA0 redaction, capability registry, and dynamic policy

**Files:** new `assistant/types.py`, `redaction.py`, `registry.py`, `policy.py`; tests `test_wa0_assistant_policy.py`, `test_wa0_assistant_redaction.py`; bilingual API/identity docs.

**Interfaces:** Produces `CapabilityDefinition`, `CapabilityContext`, `CapabilityResult`, `register_capability()`, `capabilities_for_user()`, and `redact_for_model()`.

- [ ] Write failing tests for requester/BDO/IT/admin/auditor, direct and group-granted roles.
- [ ] Define the immutable registry contract:

```python
@dataclass(frozen=True)
class CapabilityDefinition:
    code: str
    channels: frozenset[AssistantChannel]
    audiences: frozenset[str]
    module: str | None
    action: str | None
    risk: RiskLevel
    input_model: type[BaseModel]
    handler: Callable[[Session, AuthUser, BaseModel], CapabilityResult]
    requires_confirmation: bool = False
```

- [ ] Reject duplicate code, any L4 registration, and L3 without confirmation.
- [ ] Recompute account/roles/permission on every discovery and record-specific scope/state/workflow on execution.
- [ ] Redact nested keys, Bearer/JWT-like strings, and dynamic form `sensitive=true` fields before model, persistence, or logs.
- [ ] Run both tests, update bilingual architecture/identity docs, and commit `feat(agent): enforce capability and redaction policy`.

---

### Task 3: WA0 secure OpenAI-compatible provider gateway

**Files:** new provider package and `assistant/gateway.py`; modify `core/config.py`, `requirements.txt`; test `test_wa0_ai_provider.py`.

**Interfaces:** Produces `ProviderProbe`, `ChatRequest`, `ModelStreamEvent`, `ModelProvider.probe/stream_chat`, and `AssistantGateway.stream()`.

- [ ] Use `httpx.MockTransport` to test allowed HTTPS host, no credentials, timeout, redacted 401, SSE delta, tool call, JSON Schema, and safe primary/fallback switch.
- [ ] Add `AI_PROVIDER_ALLOWED_HOSTS`, 5-second connect timeout, and 60-second read timeout. Empty allowlist refuses enabled providers; loopback/link-local/metadata targets are denied.
- [ ] Implement:

```python
class ModelProvider(Protocol):
    async def probe(self) -> ProviderProbe: ...
    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ModelStreamEvent]: ...
```

- [ ] Require tools and JSON Schema for L2/L3. Unknown/invalid provider output safely fails.
- [ ] Write only model/tokens/latency/result/redacted error to `AiProviderCall`.
- [ ] Run the provider test and full regression; commit `feat(agent): add secure model provider gateway`.

---

### Task 4: WA0 provider/profile administration API

**Files:** new `services/assistant_config.py`, `routers/admin_ai.py`; register routes; test `test_wa0_ai_admin_api.py`; bilingual API docs.

**Interfaces:** Produces the approved `/api/admin/ai/providers`, profile draft/publish/rollback, health, usage, and action-audit endpoints.

- [ ] Test admin-only access, `has_secret` reads, probe-before-enable, registered capability validation, and L4 rejection.
- [ ] Encrypt new keys, preserve old ciphertext on blank update, and never return key/ciphertext.
- [ ] Probe auth/stream/JSON Schema/tools before enable or publish.
- [ ] Preseed `requester`, `bdo`, `it_staff`, `admin`; publish immutable versions, and rollback by copying into a new version.
- [ ] Return aggregates/redacted action summaries only, not transcripts, prompts, payloads, or secrets.
- [ ] Run tests, update docs, and commit `feat(agent): govern providers and agent profiles`.

---

### Task 5: WA0 owned web conversations and retention semantics

**Files:** new schemas, conversation service, assistant router; register routes; test `test_wa0_assistant_conversations.py`.

**Interfaces:** Produces bootstrap/create/list/get/archive for current ITOM user.

- [ ] Test cross-user denial and page-context rejection for roles, permissions, DOM/HTML, external URL, or more than 20 selected IDs.
- [ ] Define:

```python
class PageContextIn(BaseModel):
    route: str = Field(pattern=r"^/")
    page_type: str | None = Field(default=None, max_length=48)
    entity_type: str | None = Field(default=None, max_length=32)
    entity_id: str | None = Field(default=None, max_length=26)
    tab: str | None = Field(default=None, max_length=64)
    selected_ids: list[str] = Field(default_factory=list, max_length=20)
```

- [ ] Return only enabled/profile/max risk/suggestions/retention/fallback from bootstrap.
- [ ] Define retention 0 as no ordinary message body persistence; 1–90 uses `expires_at`. Archive never deletes action audit.
- [ ] Run tests and commit `feat(agent): add owned web conversations`.

---

### Task 6: WA0 L3 preview, confirmation, idempotency, and re-authorization

**Files:** new `services/assistant_actions.py`; modify assistant router; test `test_wa0_assistant_actions.py`.

**Interfaces:** Produces `prepare_action()`, `confirm_action()`, and `cancel_action()`.

- [ ] Test wrong actor, expiry, retry, idempotency conflict, revoked permission, changed state, cancellation, auditor, and handler failure.
- [ ] Normalize through the Pydantic input model, hash payload, generate a random 32-byte token, and store only its SHA-256.
- [ ] Obtain preview from the server handler, never from model prose.
- [ ] Confirm under `SELECT FOR UPDATE`, recompute capability and record guards, and atomically persist business result/action/audit. After exception rollback, store a separate redacted failure state.
- [ ] Expose confirm/cancel endpoints, run tests, and commit `feat(agent): enforce confirmed assistant actions`.

---

### Task 7: WA0 orchestrator, tool loop, and POST-SSE

**Files:** new `assistant/orchestrator.py`; modify router; tests `test_wa0_assistant_stream.py`, `test_wa0_prompt_boundary.py`.

**Interfaces:** Produces `AssistantOrchestrator.stream_turn()` and SSE `meta|delta|message|action|error|done`.

- [ ] Test exact SSE order with a FakeProvider; test disconnect, unknown tool, invalid parameters, more than four tool loops, injection, and false success prose.
- [ ] Emit the fixed event contract documented in the Chinese plan.
- [ ] Separate system/profile/capability/knowledge/user layers and mark knowledge/record text untrusted.
- [ ] Resolve every tool code through the registry and re-authorize. L3 emits only a prepared action.
- [ ] Cancel provider on disconnect and return a redacted fallback error without writes.
- [ ] Run tests and commit `feat(agent): stream guarded assistant turns`.

---

### Task 8: WA0 web shell and AI administration page

**Files:** create the nine listed frontend files; integrate types, router, layout, menu, styles, and i18n.

**Interfaces:** Produces the global assistant, structured action card, and `/admin/ai-assistant`.

- [ ] Define the discriminated `AssistantStreamEvent` union and authenticated POST-SSE parser.
- [ ] Render the launcher in business portal and internal workbench; send only route/page/entity/tab/explicit selection.
- [ ] Show source, link, missing fields, preview, and server result. L3 needs explicit confirm; cancelled/expired/conflicted cards disable actions.
- [ ] Build provider/profile/health/usage/action-audit admin tabs bound to `admin_ai`; secrets are write-only.
- [ ] Add complete Chinese/English strings and run `cd frontend && npm run build`.
- [ ] Commit `feat(agent): add web assistant and admin console`.

---

### Task 9: WA0 documentation, regression, IDC deployment, and acceptance

**Files:** README plus all affected authoritative Chinese docs and matching English mirrors.

- [ ] Mark only WA0 implemented; document env allowlist, no-secret reads, retention, and rollback.
- [ ] Run full pytest, frontend build, and `git diff --check`; commit `docs(agent): complete WA0 delivery contract` and push feature branch.
- [ ] Wait for green Actions, then run `deploy/k8s/push-images.sh` and the same-tag `k8s-deploy.sh`.
- [ ] IDC verify default-off, provider probe, secret non-disclosure, four profile publish/rollback, role-separated bootstrap, safe fallback, native pages, and unchanged Aily tools.

---

### Task 10: WA1 guidance, recommendation, navigation, and safe knowledge

**Files:** new guidance capability and knowledge service; modify deterministic guide; tests `test_wa1_guidance.py`, `test_wa1_knowledge.py`; bilingual docs.

**Interfaces:** Produces `guide.explain_module` L0, `guide.recommend_record_type` L2, `navigation.open_page` L0, and `knowledge.search_published` L1.

- [ ] Test single-user issue → service request; broad-impact normal user → personal request/contact IT, never incident creation; deny drafts/internal/private content.
- [ ] Register the existing deterministic rule as a capability, not prompt prose.
- [ ] Permission-trim returned target paths.
- [ ] Search only published/nondeleted articles after `knowledge.view`; sanitize/truncate/redact and return code/title/link/snippet.
- [ ] Run tests and commit `feat(agent): add governed guidance knowledge`.

---

### Task 11: WA1 own/visible records, actionable tasks, and next-step explanation

**Files:** new query capabilities; extract focused domain query functions where router logic is currently embedded; test `test_wa1_assistant_queries.py`.

**Interfaces:** Produces own service request/requirement queries, `record.search_visible`, `workflow.list_my_pending`, and `workflow.explain_next_step`.

- [ ] Test requester own-only, BDO own-requirement-only, IT module plus data scope, assignee/default-role actionable tasks, and hard admin boundaries.
- [ ] Expose shared functions:

```python
def search_visible_records(db: Session, actor: AuthUser, query: RecordSearchIn) -> list[RecordSummary]: ...
def list_actionable_tasks(db: Session, actor: AuthUser, limit: int = 20) -> list[TaskSummary]: ...
```

- [ ] Reuse those functions from routers and assistant; never call a FastAPI route from assistant.
- [ ] Limit to 20 rows and safe summary fields; trim internal notes/root cause/approval comments.
- [ ] Run tests and commit `feat(agent): add role scoped assistant queries`.

---

### Task 12: WA1 contextual UX, deterministic fallback, and IDC role UAT

**Files:** assistant frontend components, assistant i18n, README, and bilingual PRD/API/identity docs.

- [ ] Add server suggestions by page and accept only internal `/...` paths.
- [ ] Merge the current Record Creation Guide into the assistant while preserving its deterministic API and fallback UI.
- [ ] Run full tests/build/diff check, push after green gate, deploy immutable images.
- [ ] IDC test requester, BDO, developer, operator, product manager, admin, and auditor capability lists, own scope, tasks, navigation, and fallback.

---

### Task 13: WA2 requester service-request loop

**Files:** new service-request capabilities; modify only shared domain entry points if required; test `test_wa2_assistant_service_requests.py`; structured frontend cards.

**Interfaces:** Produces service-item search/form, request prepare/submit, resolution confirmation/reopen, and rating.

- [ ] Test live catalog, dynamic field validation, SLA/process/queue preview, confirmed submit, own query/supplement, close/reopen, rating, and negative requirement/incident/other-user attempts.
- [ ] Call existing `service_request_intake` and `service_request_closure`; do not duplicate forms, SLA, dispatch, confirmation, or rating.
- [ ] Ask only server-reported required fields; render enum/person/date as controls and close/reopen/rating as action cards.
- [ ] Run WA2 tests plus existing P1/P2/card-callback regressions; commit `feat(agent): close requester service loop`.

---

### Task 14: WA2 BDO requirement loop and phase acceptance

**Files:** new requirement capabilities; shared requirement entry only; test `test_wa2_assistant_requirements.py`; bilingual docs.

**Interfaces:** Produces requirement form/prepare/submit/list own/get own.

- [ ] Test BDO positive loop, requester denial despite profile misconfiguration, and BDO denial for review/project/task/other-user data.
- [ ] Reuse `ensure_registration_authorized()` and requirement intake preview/register.
- [ ] Run full pytest/build/diff, document, commit, push, and deploy after green gate.
- [ ] IDC run one requester request and one BDO requirement; verify requester denial and unchanged Aily loops.

---

### Task 15: WA3 shared guarded domain actions

**Files:** new `process_actions.py`, `ticket_actions.py`, `record_conversion.py`; refactor process/ticket/relation routers; test `test_wa3_shared_domain_actions.py` plus M18/M20/M25/M28/M31/M84.

**Interfaces:** Produces guarded workflow complete/approve/reject/reassign, ticket assign/transition, and record conversion prepare/submit.

- [ ] Test route/service equivalence for identical actor, record, and input, including operator, claim, approval, requester confirmation, terminal state, transition whitelist, and idempotency.
- [ ] Move authorization/transaction logic from routes into shared functions; routes retain only validation and envelope.
- [ ] Default shared functions to no commit so API or assistant action commits business state, action status, and audit together.
- [ ] Run the named high-risk regressions and commit `refactor(domain): share guarded workflow actions`.

---

### Task 16: WA3 controlled IT-staff capabilities, UI, and acceptance

**Files:** new IT operations capabilities; registry/frontend updates; test `test_wa3_it_capabilities.py`; bilingual docs.

**Interfaces:** Produces linked creation, process task, ticket assign/transition, Bug lifecycle, and work-task create/update/transition. No delete/permission/process-definition/bulk capability.

- [ ] Test role, current operator, assignment, lifecycle state, hard admin rules, and permission revocation between preview and confirm.
- [ ] Register one narrow L3 capability per action with explicit model, permission, state, workflow, preview, handler, and audit.
- [ ] Render assignee selectors, allowed target buttons, multirow Bug fix preview, and conversion source/target/form/reason.
- [ ] Run full regression/build/docs, push/deploy immutable images.
- [ ] IDC complete linked-record, process, assignment, Bug, and delegated-task positive loops plus unauthorized negative cases.

---

### Task 17: WA4 retention cleanup, metrics, evaluation, and knowledge governance

**Files:** new `assistant/evaluation.py`; modify scheduler, conversation/config/admin services and admin UI; test `test_wa4_assistant_governance.py`; bilingual docs.

**Interfaces:** Produces idempotent cleanup, health/usage/action aggregates, controlled evaluation, and model comparison.

- [ ] Test retention 0, expiry cleanup with action preservation, provider/model/profile/version aggregates, P50/P95/tokens/cost, and separation from MCP audit.
- [ ] Run daily cleanup in batches of 500; never delete `AiAction` or `AuditLog`.
- [ ] Evaluate ITIL classification, role isolation, injection, missing-field follow-up, and fallback using L0–L2 or L3 preview only; never confirm.
- [ ] Store evaluation calls as `purpose="evaluation"` with `scenario_code`; compare accuracy, latency, schema compliance, and cost.
- [ ] Add governance UI, run full delivery gate, push/deploy, and verify metrics do not replace business UAT.

---

### Task 18: Final security regression, recovery drill, user UAT, and PR

**Files:** change implementation/tests/bilingual docs only when evidence exposes a defect; add bilingual WA0–WA4 UAT records.

**Interfaces:** Produces a PR-ready feature branch, never a direct main merge.

- [ ] Run full pytest, production build, diff check, and deployment-script syntax validation.
- [ ] Test unauthorized read/write, forged role, prompt/tool injection, SSRF, secret disclosure, cross-conversation, expired/repeated/conflicting confirmation, disconnect, false-success prose, auditor write, and admin hard-rule bypass.
- [ ] Record current and previous immutable images; prove application rollback preserves new tables and all existing data/secrets/PVC/uploads/Aily configuration. Validate database restore only in an approved isolated target.
- [ ] Run real requester, BDO, at least three IT roles, and admin UAT with expected/actual/entity/audit/result evidence.
- [ ] Push feature branch and create a feature-to-main PR whose body explicitly lists migration, permission, secrets, rollback, automation, IDC UAT, Aily regression, and deferred items. Wait for user approval before merge.

## Design Baseline Coverage Review

| Design section | Delivery tasks | Coverage conclusion |
|---|---|---|
| §1, §3, §7 goals, entry points, and layers | Tasks 5, 7, 8, 12 | Covers conversations, orchestration, global/context entry points, and all four capability levels |
| §2 security and system-of-record boundary | Tasks 0, 2, 6, 7, 15, 18 | Enforces ITOM authorization, domain services, audit, explicit confirmation, idempotency, and recovery |
| §4 role capability matrix | Tasks 2, 11, 13, 14, 16 | Separately tests requester, BDO, IT, admin, and auditor server-side capabilities |
| §5, §6 business and mutation rules | Tasks 2, 6, 16 | Server validates approval/execution nodes, ownership, previews, and confirmation tokens |
| §8 model and admin configuration | Tasks 3, 4, 8, 17 | Covers providers, profiles, secrets, probes, evaluation, and governance UI |
| §9, §10 data and lifecycle | Tasks 1, 5, 17 | Covers additive models/migrations, retention, cleanup, and durable audit evidence |
| §11 API and streaming protocol | Tasks 4, 5, 6, 7 | Tests admin, conversation, confirmation, and SSE contracts |
| §12 failure and degradation | Tasks 2, 3, 6, 7, 12, 18 | Covers no-model, timeout, disconnect, tool failure, bad configuration, and deterministic fallback |
| §13 staged roadmap | Tasks 1–17 | Delivers WA0–WA4 as gated checkpoints and prevents premature cross-stage enablement |
| §14 acceptance | Tasks 9, 12, 14, 16–18 | Requires automation, IDC multi-role UAT, Aily regression, negative security tests, and rollback evidence |

## Execution Cadence and Stop Conditions

- Execute at five checkpoints: WA0, WA1, WA2, WA3, WA4. Deploy and obtain user confirmation after each checkpoint.
- Stop immediately on historical data mutation, Aily regression, unauthorized access, secret disclosure, rollback failure, migration failure, IDC health failure, or quality-gate failure.
- The first implementation batch is WA0 only; do not enable WA1–WA4 in the same batch.
- Feishu Approval P3 remains deferred and is not added through this work.
