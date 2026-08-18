---
name: itom-code-candidate-delivery
description: Produce an ITOM-Aily-MCP implementation candidate with focused tests, builds, and synchronized documentation while leaving all application runtimes and IDC untouched. Use only after the user selects code-candidate.
---

# ITOM Code Candidate Delivery

Use this workflow with `AGENTS.md`. If `code-candidate` has not been explicitly
selected for the current task, invoke `$itom-task-routing` and wait.

1. Complete the mandatory Git synchronization and architecture gates.
2. Start the ledger with `--track code-candidate`, recording grade, scope, and
   a code/test/build/documentation acceptance matrix.
3. Implement and run focused tests without starting an application runtime.
   Do not start, stop, restart, or otherwise alter an existing Docker or local
   application environment; it may belong to another task's user UAT.
4. After focused target verification, synchronize affected authoritative Chinese
   documentation and exact English mirrors. Record explicit no-contract-change
   assessments for documents that are unaffected.
5. Freeze one candidate and run complete CI once. Frontend or package builds are
   allowed, but do not build or publish release images.

Stop at the verified code candidate. This route cannot call `approve-idc`, enter
IDC deployment states, or release to IDC. If the user later wants local business
UAT or IDC delivery, begin a new task and invoke `$itom-task-routing` again.
