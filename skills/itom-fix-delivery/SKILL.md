---
name: itom-fix-delivery
description: Enforce the ITOM repository fix-task lifecycle, timing, acceptance, documentation, CI, and IDC release gates. Use for every bug fix, regression repair, corrective frontend or backend change, deployment correction, or follow-up repair in ITOM-Aily-MCP.
---

# ITOM Fix Delivery

Use this workflow together with the repository `AGENTS.md`. Never treat the
skill as permission to bypass architecture, security, data, Git, or deployment
approval boundaries.

## Start before implementation

1. Complete the repository Git synchronization gate.
2. Read the required architecture baseline and restate architecture, security,
   migration, and open decisions when required by `AGENTS.md`.
3. Start the ledger:

   `python3 scripts/task-lifecycle.py start --id <id> --track production-fix --grade <S|M|L> --scope <scope> --acceptance <matrix>`

4. Give the user the grade, impact scope, and acceptance matrix within ten
   minutes. Treat S as a small, bounded fix. Freeze its minimum candidate within
   thirty minutes or run `regrade` immediately.

## Diagnose and verify

Work against a concrete acceptance target. Prefer the smallest focused test
that reproduces the real failure. Record each failed acceptance attempt with
`fail`. On the second failure of the same target, stop editing and run
`root-cause` with the new causal explanation before continuing.

After the focused test proves the changed target, run `target-verified`. Only
then assess and update affected formal documentation. Record either the files
updated or the explicit no-contract-change assessment with `docs-assessed`.

## Freeze and deliver

Run `freeze` only after focused acceptance and documentation assessment. Run
the full CI once for that candidate, recording `ci-start` and `ci-finish`.
For user-visible runtime changes, show the exact commit, immutable image tag,
affected objects, rollback tag, disruption, and IDC acceptance method. Record
the user's explicit authorization with `approve-idc` before `idc-start`, then
use the repository release procedure once and record `idc-finish` only after
the changed real workflow passes.
Never count health checks or MCP initialization alone as business acceptance.

If CI or release fails, record `fail`. Do not retry the frozen candidate. Make a
new candidate only after root-cause review and focused re-verification.

Finish with `report`, separating development, pipeline, and external-blocker
time. Run `close` only when the task is genuinely complete or explicitly left
blocked; the history remains in `.itom-task/history.jsonl` for weekly metrics.
