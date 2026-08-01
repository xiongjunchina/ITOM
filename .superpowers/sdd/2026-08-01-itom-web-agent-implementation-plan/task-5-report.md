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
