---
name: itom-fix-delivery
description: Repair a real ITOM-Aily-MCP IDC production incident through focused verification, CI, separately approved immutable release, and real business acceptance. Use only after the user selects production-fix for a bug, regression, deployment correction, or other corrective production task.
---

# ITOM Production Fix Delivery

Use this workflow with `AGENTS.md`. If `production-fix` has not been explicitly
selected for the current task, invoke `$itom-task-routing` and wait.

## Establish the candidate

1. Complete the mandatory Git synchronization and architecture gates.
2. Start the ledger with `--track production-fix`, recording grade, impact scope,
   and an acceptance matrix that includes the real IDC symptom and workflow.
3. Diagnose the actual IDC state read-only, then make the smallest safe change.
   Do not start a local application runtime unless the user separately approves
   a temporary isolated investigation.
4. Record failures and perform the required root-cause review. After focused
   target verification, synchronize affected Chinese and English documentation.
5. Freeze one candidate and run complete CI once.

## Finish in IDC

The completion target is the repaired real IDC workflow, not a code-only handoff.
Before any IDC write, show the exact commit and immutable image tag, affected
objects, database impact, disruption, rollback tag, and real-role acceptance
method. Record the user's explicit authorization with `approve-idc`; never infer
release permission from route selection, CI, health checks, or an earlier task.

Build, publish, and deploy the approved candidate once. Verify rollout, image
identity, internal and external health paths, MCP where affected, and the changed
real business workflow. Record `idc-finish` only after that workflow passes.
