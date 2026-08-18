---
name: itom-task-routing
description: Require an explicit delivery-route decision before any ITOM-Aily-MCP coding task changes files, starts or alters an application environment, commits, builds release images, or deploys. Use for every new implementation, feature, enhancement, refactor, bug fix, corrective change, or code-generation request in this repository.
---

# ITOM Coding Task Routing

Read the repository `AGENTS.md` and inspect Git and relevant contracts read-only.
Before any mutation, present exactly these routes and recommend the best match:

1. `production-fix`: repair a real IDC incident and carry the accepted candidate
   through separately approved IDC release and real-workflow acceptance.
2. `feature-local`: build a new or enhanced capability in isolated local Docker,
   keep it running for user UAT, and require a later exact IDC release decision.
3. `code-candidate`: produce implementation, tests, builds, and synchronized
   documentation without starting or altering an application runtime or IDC.

Wait for an explicit selection unless the user already named one of those exact
routes for the current task. General approval such as "execute" does not select
a route. Do not edit, start or stop an environment, commit, build release images,
or deploy while the route is unresolved.

After confirmation, read the matching repository skill completely:

- `production-fix` -> `$itom-fix-delivery`
- `feature-local` -> `$itom-feature-delivery`
- `code-candidate` -> `$itom-code-candidate-delivery`

Start `scripts/task-lifecycle.py` with the confirmed `--track`. Reconfirm the
route for every distinct coding task; a prior task's route is not inherited.
