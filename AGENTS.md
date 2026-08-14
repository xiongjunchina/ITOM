# ITOM Repository Working Agreement

## Documentation is part of delivery

Every code change must assess and update the related documentation in the same delivery. A change is not complete when behavior, API, data model, configuration, deployment, permissions, user workflow, or acceptance criteria have changed but the documentation has not.

Required checks before declaring work complete:

1. Update `README.md` when capabilities, milestones, setup, deployment, or collaboration practices change.
2. Update the authoritative Chinese design documents under `docs/`: product behavior in `03-PRD.md`, persisted fields in `04-数据模型设计.md`, endpoints and architecture in `05-API契约与架构设计.md`, and identity/organization behavior in `06-用户身份与组织模型设计.md`.
3. Apply equivalent updates to the matching files under `docs/en/` in the same change.
4. If a document does not need an update, explicitly verify that the change does not alter its contract; do not silently skip the check.
5. Keep documentation changes in the same commit or pull request as the implementation and tests.

The delivery definition of done is: **implementation + tests + affected documentation are mutually consistent**.

## Mandatory coding-task route confirmation

Before every new coding task, present the user with a route choice and wait for
confirmation. Use a structured selection control when the client exposes one;
otherwise ask one concise numbered question. Do not edit files, start an
application environment, commit, build release images, or deploy before the
route is confirmed.

Offer exactly these routes, recommending the best match from the request:

1. `production-fix`: an IDC production problem; diagnose the real IDC state,
   make the minimum fix, run focused acceptance and CI, then require a separate
   exact release approval before refreshing IDC and replaying the user's real workflow.
2. `feature-local`: a new or expanded capability; develop and verify in the
   isolated local Docker environment, stop at a local release candidate, and
   require a separate user decision before any IDC release.
3. `code-candidate`: implement, test, build, and synchronize documentation only;
   do not start local Docker and never release to IDC under this task.

After confirmation, start `scripts/task-lifecycle.py` with the matching
`--track`. The local evidence under `.itom-task/` must not be committed.

## Mandatory coding-task execution standard

Read `skills/itom-fix-delivery/SKILL.md` for `production-fix` or
`skills/itom-feature-delivery/SKILL.md` for `feature-local`. For
`code-candidate`, apply the common gates below without an application runtime.

1. Record task grade, impact scope, and an explicit acceptance matrix at task start.
2. For an S task, freeze a minimum candidate within 30 minutes; if the scope grows, re-grade immediately.
3. Do not update formal delivery documentation, commit, push, build release images, or deploy before the changed real target has passed its focused acceptance.
4. After the second failure of the same acceptance target, stop patching. Record a root-cause review before making another candidate.
5. Run complete CI once for a frozen candidate. An unchanged retry is forbidden; record root cause and freeze a new candidate first.
6. Before every IDC write, show the exact commit, immutable image tag, affected objects, database impact, disruption, rollback tag, and IDC acceptance method. Record explicit user approval with `approve-idc` before `idc-start`.
7. Report development, CI/pipeline waiting, and external-blocker time separately.
8. Preserve evidence for first-pass acceptance, rework commits, candidate-to-IDC-ready time, and CI/build/deploy waiting share.

`scripts/git-hooks/pre-commit` enforces the target-verification and documentation
assessment gates. Bypassing hooks does not waive this working agreement.

## Aily Agent + MCP and Web Agent development lines

The `feature/aily-agent-mcp` branch is archived and must not receive new
commits. The `feature/AI-agent-version` branch is the dedicated development
line for the current Feishu Aily Agent + MCP Server + ITOM Web Agent version.
Before designing or implementing work on the current branch:

1. Read `docs/10-Aily-MCP版本交接与决策上下文.md` completely and distinguish
   confirmed baseline facts from proposals and pending decisions.
2. Restate the intended architecture, security boundary, migration strategy,
   and open decisions to the user. Do not start implementation until the user
   confirms the proposed design.
3. Treat ITOM domain services and APIs as the system of record. MCP tools must
   not bypass business validation, workflow authorization, RBAC, audit, or
   idempotency by writing directly to database tables.
4. Verify the current official Feishu Aily and MCP documentation before fixing
   transports, authentication, callbacks, or product capability claims in the
   design; these external contracts are time-sensitive.
5. Keep secrets out of URLs, logs, prompts, tool results, commits, and test
   fixtures. Map Feishu identity to an ITOM account before authorizing any
   user-scoped or mutating tool.
6. Commit and push development changes only to `feature/AI-agent-version` (or a
   child feature branch). Merge into `main` through a user-approved Pull
   Request. Never rewrite the `v1.0.0-feishu-helpdesk` tag or use the frozen
   `/Users/xjun/Gitrepo/ITOM` worktree for new-version development.

The frozen Feishu Helpdesk baseline remains recoverable from the annotated tag
`v1.0.0-feishu-helpdesk` at commit `f13f702`.

## Mandatory pre-development Git synchronization

Before starting every new development task or modifying code:

1. Check the worktree and current branch with `git status` and `git branch`.
2. If local changes exist, commit them as a separate baseline/version record;
   never mix those changes with the new task.
3. Push the current development branch to GitHub and verify that the local
   `HEAD` equals the remote branch tip.
4. Only after synchronization succeeds may new implementation changes begin.

If GitHub synchronization is unavailable or the local and remote tips differ,
stop before editing code and report the exact blocker. This gate applies to
every subsequent update, not only large refactors or releases.

## Deployment and verification environment

IDC Kubernetes remains the sole production delivery and final acceptance environment. The local application stack is forbidden for `production-fix` and `code-candidate` unless the user separately approves a temporary isolated investigation. A confirmed `feature-local` task may start the repository-defined local Docker application and test database for development and UAT. It must never use copied IDC business data, production credentials, Kubernetes Secrets, production OAuth/Aily applications, production callback URLs, or production integrations. Ngrok or another public tunnel still requires separate explicit approval.

The distinction is:

- GitHub Actions runs the complete backend regression, frontend production build, deployment-file checks, and documentation-delivery guard without using the IDC business database.
- Building linux/amd64 release images on the workstation is allowed because it does not start a local ITOM runtime. The release scripts must build from a clean commit and use an immutable Git-derived tag.
- Local feature UAT may prove a release candidate, but real production Aily, MCP, callback, identity, and user-workflow acceptance runs only in IDC.

For a `production-fix`, the completion flow is:

1. Implement the code and synchronize affected Chinese and English documentation.
2. Push the feature branch and require `.github/workflows/quality-gate.yml` to pass. Automated tests use an isolated temporary database and must never target the IDC business database.
3. For schema-affecting releases, complete the approved in-cluster backup/checkpoint procedure before deployment. Never reset or replace IDC PVCs, Secrets, uploads, accounts, or integration configuration.
4. Build and publish the backend/frontend linux/amd64 images with `deploy/k8s/push-images.sh`. Publish only a clean commit, use the same immutable tag for both images, and verify the architecture.
5. Deploy that exact tag with `deploy/k8s/k8s-deploy.sh`.
6. Verify strict rollout success, expected image identities, pod/service/ingress health, the frontend-to-backend `/api/health` path, external `/api/health`, MCP `initialize`, and the changed real user workflow in IDC.
7. Treat the work as delivered only after IDC verification succeeds; report any infrastructure blocker explicitly and retain the previous image tag as the rollback point.

For a `feature-local` task, stop after isolated local business UAT, affected
bilingual documentation, a frozen commit, and one passing CI run. Record
`local-candidate-ready` and report the exact release and rollback plan. Do not
build release images or write to IDC until the user separately approves that
exact plan. A deferred local candidate may be closed as `local-candidate`.

For a `code-candidate` task, stop after implementation, focused verification,
affected bilingual documentation, a frozen commit, and one passing CI run. It
cannot enter the IDC approval or deployment states.

Do not treat CI, a successful image build, `/api/health`, or MCP initialization alone as complete business acceptance.
