# Task 8C Evidence Report

Date: 2026-08-02

## Scope and guardrails

- Base and synchronized branch: `feature/AI-agent-version` at
  `07d0c2ffa0cb08baa4f224fbd1266dfee5238447`; local and
  `origin/feature/AI-agent-version` matched before edits.
- Changed only Task 8C action transport/state, directly affected frontend
  validation/presentation, tests, Chinese/English documentation, and this
  report.
- No push, deployment, local Docker/Compose, IDC access, Aily/MCP change, or
  `main` change was performed.

## TDD evidence

### RED

1. `backend/.venv/bin/python -m pytest backend/tests/test_wa0_assistant_actions.py -x -vv`
   failed because `confirmation_expires_at` was a naive `datetime`, not an
   explicit-`Z` wire string.
2. `backend/.venv/bin/python -m pytest backend/tests/test_wa0_assistant_stream.py -x -vv`
   failed because the first L3 action SSE emitted offset-free
   `expires_at`.
3. `node --test scripts/assistant-review-fix.test.mjs` failed first because
   the production expiry boundary did not exist, then because a replayed
   `server_preview.action_id=not-a-valid-action-id` passed both the stream
   validator and presenter.
4. The action audit status test was extended for `executing`; it failed until
   the explicit bilingual safe "outcome unknown" mapping was added.

### GREEN

- Public action payloads and the first L3 SSE projection now serialize
  `expires_at` as RFC 3339 UTC with `Z`, while the database remains naive UTC.
- The browser rejects offset-free action expiry and verifies a canonical value
  retains the expected ten-minute UTC duration for an Asia/Shanghai browser.
- Live and replayed `server_preview.action_id` values share the same strict
  26-character ULID validator; malformed replay fails before presentation.
- Confirmation commits an internal `executing` claim before handler entry.
  Claim failure runs no handler. Known failure persists `failed`; uncertain
  post-claim handler/final persistence returns safe `AI_ACTION_OUTCOME_UNKNOWN`
  and preserves non-retryable `executing`, without restoring `prepared`,
  issuing another token, or reporting success.
- The regression proves terminal failure-persistence uncertainty leaves the
  action `executing`; a retry is rejected and the handler count remains one.

## Verification

| Command | Result |
| --- | --- |
| `backend/.venv/bin/python -m pytest backend/tests/test_wa0_assistant_actions.py -q` | Passed (targeted Task 8C action regression) |
| `backend/.venv/bin/python -m pytest backend/tests/test_wa0_assistant_stream.py -q` | Passed (targeted Task 8C SSE regression) |
| `node --test scripts/assistant-review-fix.test.mjs` | `53` passed, `0` failed |
| `npm run build` | Passed: `tsc --noEmit` and Vite production build |
| `backend/.venv/bin/python -m pytest -q` | `721 passed, 2 warnings in 189.51s` |
| `git diff --check` | Passed |

The two backend warnings are pre-existing third-party `ldap3`/`pyasn1`
deprecation warnings (`tagMap` and `typeMap`), not Task 8C failures. Vite
reported its existing chunk-size advisory only; the build completed.

## Documentation delivery

Updated `README.md`, the required Chinese authoritative `docs/03` through
`06` and `docs/10`, plus matching English documents. They now describe the
explicit UTC wire contract, shared replay ULID validation, durable at-most-once
execution claim, no-migration state contract, and the unchanged pending Task 9
IDC UAT scope.

## Remaining concern

Task 9's real PostgreSQL/ASGI/IDC evidence remains pending by design and was
not attempted for this task.

## Review-fix round 1 — fail-closed expiry and outcome UX (2026-08-02)

### Scope and guardrails

- Began from clean, synchronized `feature/AI-agent-version` at
  `60e2516490ccf6426c2b2168c5dde94ba51517bd`; `HEAD`, upstream, and origin
  matched before edits.
- Changed only the Task 8C action service, action SSE/renderer/card boundary,
  focused tests, bilingual delivery documentation, and this report.
- No push, deployment, Docker/Compose, IDC access, Aily/MCP behavior, or
  `main` work was performed.

### RED evidence and root cause

1. `node --test scripts/assistant-review-fix.test.mjs` initially failed six
   new production-boundary regressions: five valid-raw-token action SSE cases
   (missing, `null`, offset-free, malformed, and unparseable expiry) reached
   the stream consumer, and outcome-unknown had no card mapping. The stream
   validator checked action ID/risk but not the token-to-expiry contract; the
   card fell through to generic `failed`/preview presentation.
2. `backend/.venv/bin/python -m pytest backend/tests/test_wa0_assistant_actions.py -q -k 'execution_claim_commit_failure or success_terminal_commit_failure'`
   initially reported one failure: a forced success terminal `db.commit()`
   error left the row `succeeded`, not `executing`. The durable claim was
   correct, but SQLite could release the nested handler savepoint without a
   real outer write transaction, making the success write durable before the
   terminal commit outcome was known. The claim-commit test already proved the
   expected no-handler/prepared-retry behavior.

### GREEN evidence

- The stream validator now requires a non-null, parseable explicit RFC 3339
  UTC `Z` expiry whenever a live action carries a valid raw confirmation token;
  the drawer repeats the same guard before creating `prepared`.
- After the durable claim, SQLite starts an explicit outer write transaction
  before the nested handler savepoint. A failed success terminal commit rolls
  back domain mutation, success result, and audit while retaining `executing`;
  a claim failure still runs no handler and preserves the original `prepared`
  token for an honest retry.
- `AI_ACTION_OUTCOME_UNKNOWN` now clears the token, maps the card to
  non-retryable `executing`, disables confirmation/cancellation, and uses a
  result-pending notice. The no-business-change preview assertion is never
  rendered for that state; success text remains exclusive to `succeeded`.

### Verification

| Command | Result |
| --- | --- |
| `backend/.venv/bin/python -m pytest backend/tests/test_wa0_assistant_actions.py -q -k 'execution_claim_commit_failure or success_terminal_commit_failure or failure_state_persistence_error'` | `3 passed, 75 deselected` |
| `node --test scripts/assistant-review-fix.test.mjs` | `60 passed, 0 failed` |
| `npm run build` | Passed: `tsc --noEmit` and Vite production build |
| `backend/.venv/bin/python -m pytest -q` | `723 passed, 2 warnings in 186.62s` |
| `git diff --check` | Run before commit; no whitespace errors |

The two backend warnings are pre-existing third-party `ldap3`/`pyasn1`
deprecation warnings (`tagMap` and `typeMap`). Vite completed with its existing
chunk-size advisory only.

### Documentation delivery and commit

README, Chinese authoritative `docs/03`–`06` and `docs/10`, and all matching
English mirrors now describe the live token/expiry boundary, SQLite outer
transaction guarantee, and outcome-unknown card semantics. The conventional
commit for this round is `fix(web-agent): fail closed action expiry and outcome UX`.

### Remaining concern

Task 9 real PostgreSQL/ASGI/IDC evidence remains pending by design and was not
attempted. This round adds deterministic SQLite failure-injection coverage; it
does not claim a replacement for Task 9's real PostgreSQL/IDC acceptance.

## Review-fix round 2 — calendar-valid UTC expiry (2026-08-02)

### Scope and guardrails

- Began from clean, synchronized `feature/AI-agent-version` at `f2512fdb7fbfaa51d4c6b5113afe041280de3cf0`; local `HEAD` and `origin/feature/AI-agent-version` matched before edits.
- Changed only the shared frontend expiry parser, its production harness, affected CN/EN contract documentation, and this report.
- No push, deployment, Docker/Compose, IDC access, backend semantic change, Aily/MCP change, or `main` work was performed.

### RED evidence

`frontend/node --test scripts/assistant-review-fix.test.mjs` failed exactly the three new calendar-invalid cases before the parser change: `2030-02-30T00:10:00Z`, `2030-04-31T00:10:00Z`, and `2030-01-01T24:00:00Z` reached the existing `Date.parse` boundary without throwing. The valid leap-day and fractional-second assertions passed, confirming the regression tests target only semantic calendar validity.

### GREEN evidence

`parseAssistantActionExpiry()` now extracts the UTC components and checks month/day limits, Gregorian leap years, and 00–23/00–59/00–59 time ranges before calling `Date.parse`. The existing stream validator and drawer continue to call this same shared boundary; no action can become `prepared` through a normalized invalid expiry. Valid leap-day and fractional-second explicit-`Z` inputs remain accepted.

### Verification

| Command | Result |
| --- | --- |
| `node --test scripts/assistant-review-fix.test.mjs` (RED) | `61 passed, 3 failed`; all 3 failures were the intended new assertions |
| `node --test scripts/assistant-review-fix.test.mjs` (GREEN) | `64 passed, 0 failed` |
| `npm run build` | Passed: `tsc --noEmit` and Vite production build; Vite emitted its existing chunk-size advisory only |
| `git diff --check` | Passed |

### Remaining concern

Task 9 real PostgreSQL/ASGI/IDC evidence remains pending by design and was not attempted. This round is limited to frontend calendar validation and does not claim backend or production acceptance.
