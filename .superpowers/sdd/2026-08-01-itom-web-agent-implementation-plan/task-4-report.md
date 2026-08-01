# Task 4 Report — WA0 Provider and Agent Profile Governance

## Status and Git boundary

- Status: implemented and verified on the requested local branch; commit evidence is reported after the selective commit.
- Branch: `feature/AI-agent-version`
- Requested clean base and pre-task `HEAD`: `64d61f2e8d3252df3366d6e2ce5f834edc43bbae`
- Planned commit subject: `feat(agent): govern providers and agent profiles`
- Workspace: `/Users/xjun/Gitrepo/ITOM-Aily-MCP`
- Prohibited activity: no branch switch, rebase, reset, merge, push, deployment, live provider request, live DNS lookup, IDC access, local ITOM runtime, or schema migration occurred.

The initial gate showed a clean worktree on the requested branch and exact base. The branch was already eight local commits ahead of the cached remote-tracking tip. The task explicitly prohibited push and live network access, so the repository-wide synchronization rule was not executed and no remote state was changed.

## Implementation summary

- Added 12 administrator governance routes under `/api/admin/ai`; every route has a persisted server-side `admin_ai` permission dependency (`view`, `edit`, or `delete`) and no handler trusts a client-side role claim.
- Added provider create/list/update/soft-delete/probe services. Credentials are encrypted with the existing secret store, are write-only, preserve the existing value when omitted or blank, preserve exact nonblank credential bytes, and are represented only by `has_secret` in responses.
- Reused Task 3's OpenAI-compatible adapter for HTTPS, host allowlist, DNS pinning/SSRF controls, redirect refusal, timeout rules, redaction, and the exact sequential authentication → streaming → tools → JSON Schema probe. Tests use `httpx.MockTransport` and controlled DNS only.
- Persisted probe status, capability booleans, redacted stable errors, timestamp, enabled-state correction, and audit in one service transaction. A failed probe is committed truthfully as failed and then returned as a business error; it cannot leave the provider healthy or enabled.
- Enforced provider activation only after a recent successful authentication/stream probe. Provider URL, model, type, or nonblank secret changes invalidate the probe and disable the provider. Fallback references must exist, remain acyclic, and cannot be deleted while referenced.
- Bootstrapped exactly four fixed profile codes: `requester`, `bdo`, `it_staff`, and `admin`. Draft updates use optimistic revision checks; published versions are immutable and strictly increasing; rollback copies a historical published snapshot into a new version.
- Validated publish-time provider health and compatibility, bilingual prompts, fixed registry capability code/audience/risk boundaries, L4 rejection, and server-defined knowledge scopes. Database content only narrows fixed registered capability definitions and never supplies executable handlers.
- Added aggregate/redacted allowlist responses for health, usage, and action audits. Mutation audits contain identifiers, field names, counts, statuses, and stable codes only—never credentials, prompts, model output, action inputs, confirmation tokens, or raw provider bodies.
- No admin UI, conversation/action/orchestrator flow, domain capability, migration, deployment, or WA1 code was added. No Task 1 schema defect blocked Task 4.

## Strict TDD evidence

All tests ran against the isolated backend test database. The implementation proceeded in observed RED/GREEN cycles:

1. Permission boundary: all 12 planned routes returned `404` in RED; the minimal registered guarded routes made all 12 unauthorized-access cases pass with `403`.
2. Provider secret and CRUD contract: four provider cases failed before implementation; encrypted write-only create/list/update behavior and probe-gated activation made all four pass.
3. Probe truthfulness: the placeholder performed no sequence and returned success on failure in RED; the Task 3 adapter sequence and atomic failure persistence made both success/failure cases pass.
4. Profile governance: draft, publish, and rollback cases failed against placeholder payloads/revisions; fixed profiles, registry validation, optimistic concurrency, immutable versions, and copy-forward rollback made all three pass.
5. Aggregate surfaces: usage/action audit contract failed before allowlist aggregation; both aggregate/redaction cases passed after implementation.
6. Credential byte preservation: a nonblank secret with significant edge whitespace was trimmed in RED; narrowing normalization to name/model made the exact-secret test pass while blank updates still preserve the old ciphertext.
7. Fallback self-review: provider creation incorrectly accepted a dangling fallback with `200` in RED; create-time existing-chain validation, rollback-on-error, and cycle rejection made the regression pass.

Final focused Task 4 run:

```text
Command: .venv/bin/python -m pytest tests/test_wa0_ai_admin_api.py -q
Working directory: /Users/xjun/Gitrepo/ITOM-Aily-MCP/backend
Output: 25 passed in 5.07s
Exit: 0
```

Final full backend regression:

```text
Command: .venv/bin/python -m pytest -q
Working directory: /Users/xjun/Gitrepo/ITOM-Aily-MCP/backend
Output: 446 passed, 2 warnings in 99.62s (0:01:39)
Exit: 0
```

## Changed files

- `backend/app/services/assistant_config.py`
- `backend/app/routers/admin_ai.py`
- `backend/app/routers/__init__.py`
- `backend/app/main.py`
- `backend/tests/test_wa0_ai_admin_api.py`
- `README.md`
- `docs/03-PRD.md`
- `docs/05-API契约与架构设计.md`
- `docs/10-Aily-MCP版本交接与决策上下文.md`
- `docs/en/03-PRD.md`
- `docs/en/05-api-and-architecture.md`
- `docs/en/10-aily-mcp-handoff-and-decision-context.md`
- `.superpowers/sdd/2026-08-01-itom-web-agent-implementation-plan/task-4-report.md`

## Documentation assessment

- Updated the authoritative Chinese API/architecture contract and English mirror with all 12 endpoints, permission requirements, write-only secret rules, transport/probe behavior, fixed profile/version semantics, publish constraints, and aggregate/redacted response boundaries.
- Updated the Chinese/English PRD status and Task 4 governance behavior.
- Updated the Chinese/English Aily/MCP handoff context and README milestone/current-delivery statements from Task 1–3 to Task 1–4.
- Assessed `docs/04-数据模型设计.md` and its English mirror: no update required because Task 4 uses the reviewed Task 1 schema and adds no persisted field, table, constraint, or migration.
- Assessed `docs/06-用户身份与组织模型设计.md` and its English mirror: no update required because the existing persisted RBAC identity boundary is unchanged; Task 4 applies the already-defined `admin_ai` permission on the server.

## Security and atomicity self-review

- Confirmed response serializers do not include `api_key`, ciphertext, prompts, action payloads, confirmation tokens, provider request/response bodies, or user conversation content.
- Confirmed all provider/profile mutations audit in the same transaction as state changes; validation failures occur before commit, and handled integrity conflicts roll back.
- Confirmed failed probes persist `failed`, redacted capability/error data, `last_probed_at`, disabled state, and audit together before returning `AI_PROVIDER_PROBE_FAILED`.
- Confirmed profile publication validates the current draft revision and creates a new immutable row; replaying the same draft revision is stale. Rollback validates the expected latest version and creates another new immutable row.
- Confirmed fallback creation/update cannot reference a missing/deleted provider or create a cycle, and referenced providers cannot be soft-deleted.
- Confirmed tests inject provider transports and DNS answers; production adapter construction was never exercised against a live host.

## Warning classification

The two full-suite warnings are existing third-party `ldap3` imports of deprecated pyasn1 `tagMap` and `typeMap`. They are unrelated to Task 4 and did not produce failures.

## Final review verdict

Task 4 is internally complete within the requested WA0 scope: implementation, focused tests, full backend regression, and affected Chinese/English documentation are aligned. Delivery remains local by instruction; no push, deployment, live provider, or IDC acceptance was attempted.

# Task 4 review fix round 1 — 2026-08-01

## Review status and boundary

- Review result addressed: `Needs fixes` at `FIX_BASE=c4584c8ef1cb23e4bf70341e65b023cb800d75f9`.
- Scope remained Task 4. No admin UI, conversation/action/orchestrator, domain capability, WA1, deployment, live provider, live DNS, IDC, branch switch, rebase, reset, merge, or push was added or performed.
- The review exposed one strictly necessary Task 1 schema repair: `ai_agent_profile_version` had no place to persist staged `name/default_provider_id/enabled/retention_days`. Fix round 1 adds one additive `config_snapshot JSONB NOT NULL DEFAULT '{}'` column through the existing idempotent PostgreSQL migration path; no table, destructive DDL, or data rewrite was added.
- Suggested local commit subject: `fix(agent): serialize provider and profile governance`.

## Root-cause verification

1. Provider create/update/delete/probe used ordinary session reads and `FOR UPDATE` only on the probe row. Update could validate a cached healthy row, race a model/base/secret invalidation in another pod, and later write `enabled=true` against the new unverified configuration. Cross-row fallback, delete/reference, and primary checks had the same unlocked check-then-write shape.
2. Draft PATCH wrote publication-controlled fields directly to `ai_agent_profile`, while prompts/capabilities lived in version 0. A rejected publish therefore left the active row partially changed even though no immutable version was created.
3. Provider deletion and profile publication did not share a transaction lock, so active-reference creation could race delete despite each operation being locally transactional.
4. `/usage` loaded all `AiProviderCall` ORM rows and aggregated in Python without a reporting window.

## Fix summary

- Added one stable transaction-scoped PostgreSQL advisory-lock key dedicated to AI provider governance. Provider create/update/delete/probe-result persistence and profile publish/rollback acquire it before validation or state reads, then refresh and `FOR UPDATE` every provider row in deterministic ID order. SQLite keeps the same refresh/order path for deterministic tests, while multi-pod production serialization is PostgreSQL-owned.
- Kept URL/model/secret invalidation, recent-probe enablement, fallback-chain validation, primary promotion, delete/reference checks, probe result, and mutation audit inside the locked transaction. Profile publish/rollback use the same lock before creating/changing an active provider reference.
- Added `AiAgentProfileVersion.config_snapshot` for `name`, `default_provider_id`, `retention_days`, and `enabled`. Draft PATCH updates only version 0 plus its prompts/capabilities/knowledge/risk. Successful publish validates first, then atomically applies the snapshot to `ai_agent_profile` and creates an immutable version. Rejected publish leaves the active row and every published-version field unchanged. Rollback copies and reapplies the historical active-settings snapshot into a new version.
- Replaced Python full-row usage aggregation with three SQL aggregate/group queries bounded by `days`, default 30 and validated to 1–90. The response includes `window_days` and `window_started_at`; selected SQL fields exclude provider-call error, conversation, message, profile-version, and model columns.

## Strict TDD RED/GREEN evidence

### Provider serialization and stale enablement

```text
Command: .venv/bin/python -m pytest <three provider lock/stale tests> -q
RED: 3 failed
- no _lock_provider_governance boundary existed;
- create bypassed the sentinel lock and returned 200;
- a cached healthy row enabled successfully after another transaction changed the model and invalidated the probe.

GREEN: 3 passed in 0.64s
```

The SQL-boundary test captures `SELECT pg_advisory_xact_lock(:lock_key)` before the provider query, ID ordering, `FOR UPDATE`, `populate_existing`, and row read. The deterministic stale-session test now returns `AI_PROVIDER_PROBE_REQUIRED` and leaves the changed row `unverified` and disabled.

### Draft isolation, publish, rollback, and schema repair

```text
Command: .venv/bin/python -m pytest <profile isolation + two model/migration tests> -q
RED: 3 failed
- published versions had no config_snapshot;
- the ORM model had no config_snapshot;
- additive PostgreSQL DDL did not repair the missing column.

GREEN: 3 passed in 1.00s
```

The API test publishes V1, edits an unhealthy V2 draft, verifies the active row and every V1 persisted field remain byte-for-byte unchanged through draft edit and rejected publish, then verifies successful V2 publication and V1 rollback-copy application as V3.

The active-reference lock test was mutation-checked by temporarily removing the publish/rollback lock calls:

```text
RED: 1 failed; publish reached AI_PROFILE_PROMPT_REQUIRED (400) instead of the lock sentinel (409)
GREEN after restoring both lock calls: 1 passed in 0.62s
```

### Bounded SQL usage aggregation

```text
Command: .venv/bin/python -m pytest <aggregate allowlist + usage window tests> -q
RED: 2 failed; window fields were absent and days was ignored.
First GREEN attempt: 1 passed, 1 failed because a prior test's isolated-database call remained in the module fixture.
Test-fixture correction: explicitly clear AiProviderCall rows before the hand-derived three-row window fixture.
GREEN: 2 passed in 0.69s
```

The final fixture proves that two recent rows produce exact totals/grouping while a 31-day-old row is excluded. SQL capture proves no sensitive/full-row columns are selected, and `days=0` or `days=91` returns 422.

## Final verification

Task 4 API suite:

```text
Command: .venv/bin/python -m pytest tests/test_wa0_ai_admin_api.py -q
Output: 30 passed in 4.97s
Exit: 0
```

All WA0 suites:

```text
Command: .venv/bin/python -m pytest tests/test_wa0_*.py -q
Output: 141 passed in 8.34s
Exit: 0
```

Full backend regression:

```text
Command: .venv/bin/python -m pytest -q
Output: 451 passed, 2 warnings in 99.11s (0:01:39)
Exit: 0
```

The two warnings remain the pre-existing ldap3 imports of deprecated pyasn1 `tagMap` and `typeMap`.

## Fix-round changed files

- `backend/app/services/assistant_config.py`
- `backend/app/routers/admin_ai.py`
- `backend/app/models/assistant.py`
- `backend/app/services/migrate.py`
- `backend/tests/test_wa0_ai_admin_api.py`
- `backend/tests/test_wa0_assistant_models.py`
- `README.md`
- `docs/03-PRD.md`
- `docs/04-数据模型设计.md`
- `docs/05-API契约与架构设计.md`
- `docs/10-Aily-MCP版本交接与决策上下文.md`
- `docs/en/03-PRD.md`
- `docs/en/04-data-model.md`
- `docs/en/05-api-and-architecture.md`
- `docs/en/10-aily-mcp-handoff-and-decision-context.md`
- `.superpowers/sdd/2026-08-01-itom-web-agent-implementation-plan/task-4-report.md`

## Documentation assessment and parity

- Updated README, PRD, API/architecture, data model, and handoff context in authoritative Chinese and matching English mirrors for advisory locking, staged active settings, atomic publish/rollback, the additive snapshot column, and bounded SQL usage semantics.
- This section supersedes the original report's statement that `docs/04` needed no change: review fix round 1 identified and repaired the missing version-snapshot persistence contract.
- Reassessed `docs/06-用户身份与组织模型设计.md` and its English mirror: no change is required because server-side `admin_ai` authorization, user identity, role derivation, and organization boundaries are unchanged.

## Fix-round self-review verdict

- All provider graph writes and active-reference publication paths share one PostgreSQL transaction advisory lock and deterministic row-lock order; no in-process mutex is used for production safety.
- Either serialized order of enable-vs-invalidate, fallback-cycle creation, primary promotion, or delete-vs-publish ends in a valid state: later operations refresh and revalidate after acquiring the same lock.
- Draft edits no longer touch active profile fields. Publish validation completes before active state/version creation, and rollback applies only a copied immutable source snapshot.
- Usage work is bounded by both time (1–90 days) and selected/grouped SQL columns.
- No live external system was contacted. Delivery remains a local, unpushed Task 4 fix round.

# Task 4 review fix round 2 — 2026-08-01

## Review status and boundary

- Review findings addressed at `FIX_BASE=677bfb521de710298b936a893eced4d9f3e221a8` on `feature/AI-agent-version`.
- Scope remained Task 4. No branch switch, rebase, reset, merge, push, deployment, live provider/DNS/network request, IDC access, local application runtime, admin UI, conversation/action/orchestrator, domain capability, or WA1 work was performed.
- One additive Task 1 schema extension was necessary and explicitly allowed by the review: `ai_provider_config.config_revision INTEGER NOT NULL DEFAULT 1`. The existing idempotent PostgreSQL repair path adds it without DML, destructive DDL, or rewriting existing rows. The existing `config_snapshot` column remains unchanged; legacy `{}` is recognized as incomplete rather than backfilled.

## Root-cause verification

1. `probe_provider()` acquired the synchronous PostgreSQL transaction advisory lock and provider row locks, then awaited `adapter.probe()` and `adapter.aclose()` before commit. A second same-event-loop request could synchronously wait for that lock and prevent the first coroutine from resuming, producing a deadlock. The same shape also let a result computed for an old configuration overwrite newer state.
2. `_profile_config()` always began with current `ai_agent_profile` fields and overlaid any keys present in `config_snapshot`. A legacy published version with `{}` therefore appeared to contain the current active settings, so rollback returned 200 and copied newer configuration into a historical version copy.

## Fix summary

- Added monotonic `config_revision`, initialized to 1. Under the existing cross-pod governance advisory lock, provider type, URL, model, nonblank replacement secret, timeout, output limit, temperature, or fallback change increments the revision and invalidates/disables prior health. The revision contains no secret-derived hash or plaintext.
- Split provider administration probing into three phases:
  - Phase A: short locked transaction refreshes/locks all providers in deterministic ID order, validates the target, snapshots detached encrypted configuration plus revision, and commits.
  - Phase B: exact Task 3 sequential async probe and adapter close run with `Session.in_transaction() == false`; no advisory or row lock spans network I/O.
  - Phase C: short locked transaction refreshes current state and persists truthful redacted success/failure only when the provider still exists and its revision matches. Change/deletion rolls back and returns 409 `AI_PROVIDER_PROBE_STALE`; the old result never overwrites newer state.
- Added `schema_version=1` to every newly bootstrapped/updated draft snapshot, published snapshot, and rollback-copy snapshot. New snapshots contain all four activity-controlled fields: `name`, `default_provider_id`, `retention_days`, and `enabled`; prompts, capabilities, knowledge scope, and risk remain in their existing immutable version columns.
- Historical rollback now validates the explicit marker, required fields, and safe field types/ranges before publish validation or writes. `{}`, missing markers, and incomplete historical snapshots return 409 `AI_PROFILE_LEGACY_SNAPSHOT_UNAVAILABLE`. No historical value is synthesized from current active profile state. A complete snapshot still copies to a new monotonically increasing version and atomically applies its active settings.

## Strict TDD RED/GREEN evidence

### Probe transaction boundary, concurrent mutation, and stale result

The first command used the unavailable `python` executable and exited 127 before collecting product evidence. The runner was corrected to the repository virtual environment; no production code changed for that environment-only failure. The initial provider fixture also lacked the controlled allowlist and failed at setup; the fixture was corrected before accepting RED.

Observed product RED:

```text
Command: .venv/bin/python -m pytest tests/test_wa0_ai_admin_api.py -q -k 'releases_database_transaction_before_awaiting_network or mutation_can_finish_during_probe'
Output: 2 failed, 30 deselected in 0.70s
- probe_db.in_transaction() was True while the fake provider awaited;
- AiProviderConfig had no config_revision.
Exit: 1
```

GREEN after the Phase A/B/C and revision implementation:

```text
Same focused command
Output: 2 passed, 30 deselected in 0.61s
Exit: 0
```

The final stale-result fixture changes only `fallback_provider_id` while the fake probe is suspended. The second mutation commits and increments the revision before the probe resumes; the probe returns `AI_PROVIDER_PROBE_STALE`, while the newer fallback, `unverified` status, empty capabilities, null probe timestamp, and disabled state remain intact.

```text
Final focused revalidation after changing the interleaving mutation to fallback-only:
Output: 2 passed, 31 deselected in 0.69s
Exit: 0
```

### Legacy snapshot fail-closed rollback

Observed RED after inserting a pre-migration `{}` published version, running the repository migration path, preserving `{}`, and publishing complete V2 settings:

```text
Command: .venv/bin/python -m pytest tests/test_wa0_ai_admin_api.py -q -k 'legacy_profile_snapshot_rollback'
Output: 1 failed, 32 deselected in 0.69s
- rollback of version 1 returned 200 and copied the current V2 active settings.
Exit: 1
```

GREEN after explicit versioned snapshots and strict historical decoding:

```text
Same focused command
Output: 1 passed, 32 deselected in 0.64s
Exit: 0
```

The regression captures the active profile and every published-version column before rejected rollback and verifies byte-for-byte equality afterward. It then publishes complete V3, rolls complete V2 forward as V4, verifies V4 equals V2's marked snapshot, and verifies legacy V1 remains `{}`.

## Final verification

Task 4 API suite:

```text
Command: .venv/bin/python -m pytest tests/test_wa0_ai_admin_api.py -q
Output: 33 passed in 5.01s
Exit: 0
```

Task 1 model/migration suite:

```text
Command: .venv/bin/python -m pytest tests/test_wa0_assistant_models.py -q
Output: 6 passed in 0.43s
Exit: 0
```

All WA0 suites:

```text
Command: .venv/bin/python -m pytest tests/test_wa0_*.py -q
Output: 144 passed in 8.49s
Exit: 0
```

Full backend regression:

```text
Command: .venv/bin/python -m pytest -q
Output: 454 passed, 2 warnings in 99.21s (0:01:39)
Exit: 0
```

Compile/import verification:

```text
Command: .venv/bin/python -m compileall -q app tests/test_wa0_ai_admin_api.py tests/test_wa0_assistant_models.py
Command: .venv/bin/python -c "import app.main; from app.models import AiProviderConfig, AiAgentProfileVersion; from app.services import assistant_config, migrate; assert AiProviderConfig.config_revision is not None; assert assistant_config.PROFILE_CONFIG_SCHEMA_VERSION == 1; assert migrate.ASSISTANT_ENSURE_COLUMNS['ai_provider_config']"
Output: no output
Exit: 0
```

The two warnings remain the pre-existing `ldap3` imports of deprecated pyasn1 `tagMap` and `typeMap`; neither warning is in Task 4 code.

## Fix-round changed files

- `backend/app/models/assistant.py`
- `backend/app/services/assistant_config.py`
- `backend/app/services/migrate.py`
- `backend/tests/test_wa0_ai_admin_api.py`
- `backend/tests/test_wa0_assistant_models.py`
- `README.md`
- `docs/03-PRD.md`
- `docs/04-数据模型设计.md`
- `docs/05-API契约与架构设计.md`
- `docs/10-Aily-MCP版本交接与决策上下文.md`
- `docs/en/03-PRD.md`
- `docs/en/04-data-model.md`
- `docs/en/05-api-and-architecture.md`
- `docs/en/10-aily-mcp-handoff-and-decision-context.md`
- `docs/superpowers/specs/2026-08-01-itom-web-agent-design.md`
- `docs/en/superpowers/specs/2026-08-01-itom-web-agent-design.md`
- `.superpowers/sdd/2026-08-01-itom-web-agent-implementation-plan/task-4-report.md`

## Documentation assessment and CN/EN parity

- Updated README's Chinese and English capability summaries, Chinese-authoritative/English-mirror PRD, data model, API/architecture, Aily/MCP handoff context, and Web Agent design baseline for Phase A/B/C probing, `config_revision`, stale-result conflict, complete marked snapshots, and fail-closed legacy rollback.
- Documented the one-time legacy limitation explicitly: migration preserves `{}` and incomplete rows; rollback rejects them without guessing or mutating current/history.
- Reassessed `docs/06-用户身份与组织模型设计.md` and `docs/en/06-identity-and-org-model.md`: no change is required because account identity, role derivation, organization scope, and real server-side `admin_ai` authorization are unchanged.
- Reassessed deployment and user-operation documentation: no change is required because this round adds no configuration variable, operator workflow, UI, runtime deployment, or end-user behavior.

## Fix-round self-review verdict

- No synchronous PostgreSQL advisory/row lock or SQLAlchemy transaction spans `await adapter.probe()` or awaited adapter close.
- Concurrent probes of the same unchanged revision may both complete; each Phase C is serialized and truthful. Any intervening probe-relevant mutation increments the revision under the same governance lock, invalidates health, and makes older results stale.
- Delete is detected explicitly in Phase C even without a revision increment. Non-probe changes such as display name or primary flag do not falsify the configuration identity; fallback and every outbound/probe input do.
- Secrets remain encrypted write-only. No response/audit/error exposes ciphertext or plaintext, and no revision/hash derives from plaintext.
- Legacy rollback validation occurs before any active/version write. Complete rollback still validates provider health/capability compatibility and writes the copy plus active settings atomically.
- Migration remains additive and idempotent and performs no data backfill/reinterpretation. No live external system was contacted. Delivery remains local and unpushed by instruction.
