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
