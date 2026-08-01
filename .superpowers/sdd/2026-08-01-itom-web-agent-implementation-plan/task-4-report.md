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
