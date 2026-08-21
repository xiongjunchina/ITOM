---
name: itom-feature-delivery
description: Develop and verify new ITOM capabilities in an isolated local Docker environment, freeze a local release candidate, and require separate user approval before any IDC release. Use for new features, feature completion, workflow expansion, new modules, or user-visible capability enhancements in ITOM-Aily-MCP.
---

# ITOM Feature Delivery

Use this workflow with `AGENTS.md`. Never treat local acceptance as production
delivery or as permission to access production data, credentials, or callbacks.

## Start the feature track

1. Inspect the local worktree/branch and complete the architecture confirmation
   gates. GitHub synchronization is not a prerequisite for local development.
2. Start the ledger with `--track feature-local`, recording grade, scope, and
   an acceptance matrix that separates focused tests, local Docker UAT, CI, and
   IDC acceptance.
3. Use only the repository-defined isolated local environment. Never copy IDC
   business data or use production credentials, Secrets, callback URLs, OAuth
   apps, Aily identities, or production integrations.

## Form a local candidate

Implement and run focused tests first. Exercise at least one successful and one
failure path in the local Docker environment, including relevant permissions,
idempotency, audit, migration, and recovery behavior. After focused acceptance,
assess and synchronize affected authoritative Chinese documentation and exact
English mirrors. Freeze the candidate and run full CI once.

After CI passes, record `local-candidate-ready` with the local business-UAT
evidence. Report the commit, migrations, configuration impact, test evidence,
known boundaries, proposed immutable image tag, rollback point, and IDC
acceptance matrix. Do not push to GitHub, build release images, or write to IDC
until the user separately approves the applicable action.

## Require a separate release decision

Wait for an explicit user decision after the local-candidate report. If the
user defers release, close with `--outcome local-candidate`. If the user approves
the exact plan, record `approve-idc`, then build, publish, and deploy the frozen
candidate once. Complete real-role IDC workflow acceptance before recording
`idc-finish`.
