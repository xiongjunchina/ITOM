---
name: itom-feature-delivery
description: Develop a new or enhanced ITOM-Aily-MCP capability in isolated local Docker, hold the verified environment and data for explicit user UAT, and require a separate exact decision before IDC release. Use only after the user selects feature-local.
---

# ITOM Local Feature Delivery

Use this workflow with `AGENTS.md`. If `feature-local` has not been explicitly
selected for the current task, invoke `$itom-task-routing` and wait.

## Build an isolated local candidate

1. Complete the mandatory Git synchronization and architecture gates.
2. Start the ledger with `--track feature-local`, recording grade, scope, and an
   acceptance matrix that separates focused checks, agent-run local acceptance,
   user UAT, CI, and possible IDC acceptance.
3. Use only repository-defined isolated Docker and test data. Never copy IDC
   business data or use production credentials, Secrets, OAuth/Aily apps,
   callbacks, identities, or integrations.
4. Verify at least one success and one failure path, including relevant RBAC,
   audit, idempotency, migration, and recovery behavior. Synchronize affected
   authoritative Chinese documentation and exact English mirrors.
5. Freeze the candidate, run complete CI once, deploy that candidate locally,
   and record `local-candidate-ready`. Report the URL, test account, migrations,
   configuration impact, evidence, boundaries, and rollback plan.

## Hold for explicit user UAT

Treat `local-candidate-ready` as the start of the user's acceptance window, not
as permission to shut down. Keep the application containers, database, volumes,
ports, and acceptance data running and unchanged until the user explicitly says
UAT is complete or explicitly asks to stop the environment.

While user UAT is pending, do not run `docker compose stop` or `down`, restart or
replace the stack, delete volumes or data, close the task ledger, remove its
worktree, or repurpose its ports. Read-only health/status checks are allowed. If
the environment stops unexpectedly, restore the same candidate and data when
safe, then disclose the interruption.

When the user confirms UAT passed, local acceptance still does not authorize
IDC. Present the exact commit, proposed immutable image tag, affected objects,
database impact, disruption, rollback, and IDC acceptance method. Only an
explicit approval of that exact plan may be recorded as `approve-idc`.

If the user explicitly asks to stop without releasing, stop only the named
stack. Preserve volumes and acceptance data unless deletion is separately and
explicitly requested, then close as a local candidate with the user's decision
recorded. Never enter IDC from this route without the separate approval gate.
