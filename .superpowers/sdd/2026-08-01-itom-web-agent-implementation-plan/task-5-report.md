# Task 5 Report — WA0 Owned Web Conversations and Retention

## Status and boundary

- Branch: `feature/AI-agent-version`
- Required pre-task base and observed `HEAD`: `a5334c9a8dd16a77f7a8b63f63ba7254ec041f94`
- Initial worktree: clean.
- Planned commit: `feat(agent): add owned web conversations`
- Scope delivered: schemas, owner-scoped conversation service and router, registration, focused tests, and synchronized documentation only.
- Not performed: branch operation, push, deployment, IDC/network access, provider call, local ITOM runtime, SSE, tool loop, L3 action, business handler, UI, scheduler cleanup, migration, or WA1 work.

The repository-wide GitHub synchronization gate was intentionally not run: the task explicitly prohibited push and network operations. The local base/branch gate was verified before editing.

## Implementation summary

- Added `GET /api/assistant/bootstrap`, `POST/GET /api/assistant/conversations`, `GET /api/assistant/conversations/{id}`, and `POST /api/assistant/conversations/{id}/archive` for the authenticated ITOM account.
- Every conversation lookup filters by database `auth_user_id`; an unowned ID always returns `AI_CONVERSATION_NOT_FOUND` 404, including archive. The user route never grants an administrator transcript access.
- `PageContextIn` is `extra="forbid"`. It accepts only a normalized local route, bounded safe identifiers, and at most 20 unique GLIDs. It rejects client roles/permissions, document/prompt/cookie/header payloads, external/protocol-relative/traversal/encoded-separator routes, duplicate or invalid selected IDs, and all extra fields.
- Bootstrap returns only `enabled`, profile code/version, `max_risk`, `suggested_prompts`, `retention_days`, and `fallback_available`. Missing, disabled, unpublished, malformed, or otherwise unresolvable policy returns disabled fallback data without exposing governance internals; inactive accounts are rejected by the existing database-loaded authentication dependency.
- Creation resolves the current published profile/version through Task 2 policy. Retention is fail-closed: 0 writes no ordinary user/assistant body; 1–90 sets stable `expires_at`. The message helper recursively redacts content and text before staging persistence, including a failed-message path.
- Lists are owner-only, default to active state, support owner-only archived inclusion, and use `created_at DESC, id DESC` ordering. Archive alters conversation visibility only and preserves `AiAction` records.

## Strict TDD evidence

All tests use the isolated SQLite test fixture and no IDC data.

1. Initial strict-context RED: `tests/test_wa0_assistant_conversations.py` expected 422 for client-supplied `roles`; the endpoint was absent and returned 404. GREEN: route registration plus extra-forbid schema made the test pass.
2. Owner-lifecycle RED: after adding the owner create/list/get/archive test, creation returned `ASSISTANT_UNAVAILABLE` 503. GREEN: the smallest profile resolution, create, owner filter, archive, and deterministic list implementation made both tests pass.
3. Route/bootstrap RED: protocol-relative, traversal-like, and encoded-separator routes reached profile resolution (403), while bootstrap returned 404. GREEN: normalized-path validation and bootstrap fail-closed allowlist made 15 focused cases pass.
4. Retention-zero RED: the test proved no `persist_ordinary_message` policy boundary existed. GREEN: the service returned `None` for both completed and failed ordinary messages at retention 0, leaving no `AiMessage` row.
5. Normalization regression RED: `/itsm//tickets` returned 403 rather than 422. GREEN: empty internal path segments are now rejected and the focused suite passed.

The first attempt used the unavailable `python` executable and exited 127 before test collection. The runner was changed to the repository virtual environment before accepting any product RED/GREEN evidence.

## Final verification

```text
Focused Task 5:
Command: .venv/bin/python -m pytest tests/test_wa0_assistant_conversations.py -q
Directory: backend
Result: 25 passed in 4.19s
Exit: 0

All WA0 suites:
Command: .venv/bin/python -m pytest tests/test_wa0_*.py -q
Directory: backend
Result: 169 passed in 12.48s
Exit: 0

Full backend regression:
Command: .venv/bin/python -m pytest -q
Directory: backend
Result: 479 passed, 2 warnings in 108.60s
Exit: 0

Compile/import/router and diff check:
Command: .venv/bin/python -m compileall -q app tests/test_wa0_assistant_conversations.py
Command: .venv/bin/python -c "import app.main; from app.routers.assistant import router; assert any(route.path == '/api/assistant/bootstrap' for route in router.routes); assert any(route.path == '/api/assistant/conversations/{conversation_id}/archive' for route in router.routes)"
Command: git diff --check
Result: no output
Exit: 0
```

The two full-suite warnings are pre-existing third-party `ldap3` deprecations for `pyasn1` `tagMap` and `typeMap`; Task 5 emits no warnings.

## Documentation assessment

- Updated `README.md` and the authoritative Chinese PRD/API/data-model/identity/handoff documents, plus all matching English mirrors.
- The documentation now records Task 5 as implemented; specifies owner-only/non-leaking conversation routes, PageContext allowlist, bootstrap non-leakage, 0/1–90 retention semantics, redacted persistence, stable pagination, and archive/audit preservation.
- `docs/03` records Task 6+ as pending. `docs/04` records no new schema/migration but the actual semantics of the reviewed Task 1 conversation/message tables. `docs/05` records only the Task 5 endpoints, explicitly excluding SSE/actions. `docs/06` records the unchanged authentication source plus Task 5 ownership enforcement.

## Self-review

- No response serializes roles, permissions, provider configuration, prompt, handler, secret, raw message body, action payload, confirmation token, or another user's count/detail/archive state.
- Profile resolution reloads the database identity/policy and fails closed before creation when an active published profile/version and valid retention cannot be resolved.
- Retention 0 is enforced at the only ordinary-message persistence boundary; both user and assistant roles share it, including failed status. Positive retention has a bounded 1–90 policy and fixed creation-time expiry.
- Archive neither soft-deletes the conversation nor modifies `AiAction`; a future cleanup task remains responsible for expiry deletion semantics.
- No Task 6 action endpoint, Task 7 message/SSE endpoint, provider invocation, or business-domain write was introduced.

## Fix round 1 — frozen retention and runtime-proof repair

### Boundary and root cause

- Reviewed fix base and initial `HEAD`: `ae9dfcebeccd320233d766bc1c21f6f40c960a8d` on `feature/AI-agent-version`; the worktree was clean before this round.
- No branch operation, push, deployment, IDC access, network request, provider call, local ITOM runtime, migration, SSE/tool loop, action/business handler, UI, scheduler work, or WA1 work occurred.
- Root cause 1: `persist_ordinary_message()` reread mutable `AiAgentProfile.retention_days`, allowing a zero-retention conversation to start retaining after a later positive publication and stopping an already-positive captured conversation after a later zero publication.
- Root cause 2: bootstrap/create treated any enabled published row/version as usable, without proving the schema-marked snapshot, bilingual prompts, fixed capability/risk limits, provider health/compatibility, publication, or active-row/latest-version agreement.
- Root cause 3: bootstrap hard-coded `fallback_available=True` instead of deriving it from the existing authenticated, permission-aware document-guide payload.
- Root cause 4: list pagination had no explicit upper page bound.

### Strict TDD evidence

1. **RED:** the updated Task 5 fixture first created a genuinely publishable requester profile: complete `schema_version=1` snapshot, bilingual prompts, valid limits/scope, publication timestamp, and an enabled freshly-probed compatible provider. The focused suite then failed exactly on the reviewed behavior: five malformed published-profile variants stayed enabled, malformed guide payload still claimed fallback availability, zero→positive republish wrote a body, positive→zero stopped it, deletion still wrote, a legacy captured snapshot still wrote, and page `10001` returned 200. Command: `.venv/bin/python -m pytest tests/test_wa0_assistant_conversations.py -q`; result: `11 failed, 27 passed` (exit 1).
2. **GREEN:** extracted Task 4 runtime validation and immutable captured-version retention helpers; bootstrap/create use the runtime proof, creation takes retention only from that immutable snapshot, and ordinary-message writes read only the captured version then lock/revalidate the current profile and database-loaded audience before flushing. The guide now exposes an explicit safe authenticated-payload helper, and `page` is limited to 1–10,000. The focused suite passed `38 passed`.
3. **Additional RED/GREEN:** a complete but timestamp-less captured version followed by a valid newer publication initially still wrote a body (`1 failed`). `immutable_retention_days()` was tightened to require publication proof; the exact test then passed (`1 passed`).
4. **Final GREEN:** all Task 5 tests pass with republish 0→positive and positive→0, disabled/deleted profile, missing legacy snapshot, missing publication proof, malformed runtime variants, safe/unsafe guide fallback, and page boundary coverage.

### Final verification

```text
Focused Task 5:
Command: .venv/bin/python -m pytest tests/test_wa0_assistant_conversations.py -q
Directory: /Users/xjun/Gitrepo/ITOM-Aily-MCP/backend
Result: 39 passed in 9.20s
Exit: 0

Affected Task 4 profile-governance regression:
Command: .venv/bin/python -m pytest tests/test_wa0_ai_admin_api.py -q
Directory: /Users/xjun/Gitrepo/ITOM-Aily-MCP/backend
Result: 33 passed in 5.54s
Exit: 0

All WA0:
Command: .venv/bin/python -m pytest tests/test_wa0_*.py -q
Directory: /Users/xjun/Gitrepo/ITOM-Aily-MCP/backend
Result: 183 passed in 18.93s
Exit: 0

Full backend:
Command: .venv/bin/python -m pytest -q
Directory: /Users/xjun/Gitrepo/ITOM-Aily-MCP/backend
Result: 493 passed, 2 warnings in 116.22s
Exit: 0

Compile/import/router/diff:
Command: .venv/bin/python -m compileall -q app tests/test_wa0_assistant_conversations.py
Command: .venv/bin/python -c "import app.main; from app.routers.assistant import router; assert any(route.path == '/api/assistant/bootstrap' for route in router.routes); assert any(route.path == '/api/assistant/conversations/{conversation_id}/archive' for route in router.routes); assert any(route.path == '/api/assistant/conversations' for route in router.routes)"
Command: git diff --check
Result: no output
Exit: 0
```

The two full-suite warnings are the existing third-party `ldap3` deprecations for pyasn1 `tagMap` and `typeMap`; this round adds no warnings.

### Documentation synchronization

- Updated Chinese authority and English mirror pairs for `README.md`, PRD (`03`), data model (`04`), API/architecture (`05`), identity/organization (`06`), and the Aily/MCP handoff (`10`).
- The contracts now state the captured-version-only retention decision, no live-profile/`expires_at` inference, zero never becoming positive, current-profile withdrawal/audience/runtime-proof stop rules, complete runtime publication proof, the authenticated permission-aware document-guide fallback contract without claiming WA1, and the 1–10,000 page limit.
- The English README milestone/status now correctly says WA0 Tasks 1–5 implemented; no Chinese/English status remains at Tasks 1–4.

### Fix-round self-review

- The write boundary returns before creating or flushing `AiMessage` whenever captured version, schema marker, retention, or publication proof is absent/malformed; retention 0 therefore never reaches a body write on normal or failure paths.
- Positive retained conversations keep their captured version decision, but profile-row locking plus current database identity/audience/runtime validation prevents an in-flight message from crossing a concurrent publish/withdraw boundary. The code never uses live retention to decide historical retention.
- Runtime validation reuses the Task 4 publish rules for prompts, capability/risk/scope, provider health and compatibility, then checks complete snapshot and active-row/latest-version agreement. Bootstrap conceals all failure causes.
- `fallback_available` evaluates the real existing authenticated guide service and rejects malformed or exceptional payloads; it returns no guide content through bootstrap.
- The change adds no schema/migration, route that exposes transcripts, provider call, SSE, tool loop, L3 action, domain write, UI, scheduler, deployment, or WA1 behavior.

## Fix round 2 — serialize profile runtime state

### Scope, root cause, and resolution

- Reviewed clean base: `e6a24115d6fe0ce7b7d576947b5562f2ea9e4973` on `feature/AI-agent-version`.
- Scope stayed within Task 5: the shared published-runtime validator, conversation creation transaction, Task 5 tests, this report, and the affected Chinese/English API and handoff mirrors. No Task 6+ implementation, branch operation, push, deployment, IDC/network access, provider call, local ITOM runtime, migration, SSE/tool loop, action/business handler, UI, or scheduler work occurred.
- Root cause 1: `_validate_publishable()` coerced persisted `enabled_capabilities` and `knowledge_scope` with `or []`; a `NULL` runtime field could pass as a valid empty list.
- Root cause 2: conversation creation resolved profile runtime state before it shared Task 4 publication/withdrawal serialization, so a publication state change could commit before the conversation insert.
- Resolution: runtime validation now receives the raw persisted fields and rejects missing or malformed values. Creation now begins one transaction with the Task 4 governance advisory/provider-row locking discipline, then locks and refreshes the exact active profile row, re-resolves database identity/runtime state, inserts, and commits; any failure rolls the transaction back. PostgreSQL provides the cross-pod advisory and `FOR UPDATE` serialization, while SQLite preserves the same call/reload order for deterministic service tests.

### Strict RED/GREEN evidence

1. **RED:** after adding raw-runtime, entry-point, real Task 4 publication, lock-order, and withdrawal-barrier tests, the focused selection reported `5 failed, 4 passed, 39 deselected` (exit 1). The five expected failures were raw `enabled_capabilities=None`, raw `knowledge_scope=None`, bootstrap for `knowledge_scope=None`, missing governance-lock-before-runtime order, and creation succeeding after the deterministic real Task 4 withdrawal committed. An earlier direct-service attempt lacked the module database fixture and produced four `no such table` setup failures; that test setup was corrected before recording product RED evidence.
2. **GREEN:** replacing the two coercions with raw values and introducing the shared Task 4 governance-lock entry point made the same focused selection report `9 passed, 39 deselected` (exit 0). The raw-shape matrix also covers malformed mapping aliases for both fields; separate bootstrap/create cases cover each required collection being `None`.
3. **Real publication/withdrawal coverage:** the zero-retention regression now publishes and republishes through `get_profile_draft()` → `update_profile_draft()` → `publish_profile()`, not a direct version fixture. The deterministic withdrawal barrier invokes the real Task 4 draft update and `publish_profile()` in a separate session before creation takes the shared lock; creation reloads the withdrawn state, returns `AI_ASSISTANT_UNAVAILABLE`, and leaves no conversation row. A lock-order contract asserts governance lock before runtime reload.
4. **Symmetric real-republish RED/GREEN:** a creation barrier starts with a real Task 4 zero-retention publication, commits a real Task 4 republish to 30 days immediately before governance-lock acquisition, then asserts that creation captured the newer version and positive expiry. Temporarily disabling the creation lock flag produced `1 failed, 48 deselected` because it captured 0; restoring the lock produced `1 passed, 48 deselected`.

### Final verification

```text
Focused Task 5:
Command: .venv/bin/python -m pytest -q tests/test_wa0_assistant_conversations.py
Directory: /Users/xjun/Gitrepo/ITOM-Aily-MCP/backend
Result: 49 passed in 11.04s
Exit: 0

Affected Task 4 profile-governance regression:
Command: .venv/bin/python -m pytest -q tests/test_wa0_ai_admin_api.py
Directory: /Users/xjun/Gitrepo/ITOM-Aily-MCP/backend
Result: 33 passed in 5.46s
Exit: 0

All WA0:
Command: .venv/bin/python -m pytest -q tests/test_wa0_*.py
Directory: /Users/xjun/Gitrepo/ITOM-Aily-MCP/backend
Result: 193 passed in 20.02s
Exit: 0

Full backend:
Command: .venv/bin/python -m pytest -q
Directory: /Users/xjun/Gitrepo/ITOM-Aily-MCP/backend
Result: 503 passed, 2 warnings in 112.06s
Exit: 0
```

The two full-suite warnings are existing third-party `ldap3` deprecations for `pyasn1` `tagMap` and `typeMap`; this fix adds none.

### Documentation and Task 9 acceptance boundary

- Updated the Chinese API/architecture authority and its English mirror, plus the Chinese/English Aily/MCP handoff mirrors. They now specify raw-list fail-closed runtime validation, creation lock/reload order, deterministic SQLite evidence, and the remaining PostgreSQL boundary.
- Assessed README, `docs/03-PRD.md`, `docs/04-数据模型设计.md`, `docs/06-用户身份与组织模型设计.md`, and their English mirrors: no capability/milestone, persisted-field, endpoint beyond the API contract, or identity/organization contract changed in this round, so no edit was required.
- PostgreSQL two-session row-lock contention was **not run** locally or in IDC. The existing Task 9 brief already requires the IDC acceptance harness: a two-session barrier proving conversation creation/ordinary-message persistence contends with real profile publish/withdrawal on the same profile lock, including 0→positive and positive→0 retention outcomes. This remains a required Task 9 acceptance step, not a claim for this round.

### Fix-round self-review

- `None`, mappings, and any other non-list persisted collection cannot become an empty permitted list at runtime; bootstrap and create fail closed without explaining governance state.
- Creation does not read a candidate runtime profile until it has joined the same governance lock order as Task 4, then locks the exact profile row and validates the freshly loaded state before insertion. If withdrawal wins first, no conversation is written.
- The transaction rollback releases locks on unavailable/malformed runtime state and preserves the existing owner, retention, redaction, archive, pagination, and bootstrap non-leakage boundaries.
- This round did not alter historical retention resolution, ordinary-message semantics, route shapes, schemas, migrations, provider transport, authorization policy, or any later-task surface.
