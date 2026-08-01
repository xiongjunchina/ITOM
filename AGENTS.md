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

## Aily Agent + MCP development line

The `feature/aily-agent-mcp` branch is the dedicated development line for the
Feishu Aily Agent + MCP Server version. Before designing or implementing work
on this branch:

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
6. Commit and push development changes only to `feature/aily-agent-mcp` (or a
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

The IDC Kubernetes cluster is the sole runtime delivery and acceptance environment. The user's workstation must not start the ITOM application stack, a local database, Docker Compose, port 8180, or ngrok for routine development validation. A local application environment is allowed only when the user explicitly requests a temporary isolated investigation.

The distinction is:

- GitHub Actions runs the complete backend regression, frontend production build, deployment-file checks, and documentation-delivery guard without using the IDC business database.
- Building linux/amd64 release images on the workstation is allowed because it does not start a local ITOM runtime. The release scripts must build from a clean commit and use an immutable Git-derived tag.
- Real application, Aily, MCP, callback, identity, and user-workflow validation runs only in IDC.

For every user-visible fix or feature, the default completion flow is:

1. Implement the code and synchronize affected Chinese and English documentation.
2. Push the feature branch and require `.github/workflows/quality-gate.yml` to pass. Automated tests use an isolated temporary database and must never target the IDC business database.
3. For schema-affecting releases, complete the approved in-cluster backup/checkpoint procedure before deployment. Never reset or replace IDC PVCs, Secrets, uploads, accounts, or integration configuration.
4. Build and publish the backend/frontend linux/amd64 images with `deploy/k8s/push-images.sh`. Publish only a clean commit, use the same immutable tag for both images, and verify the architecture.
5. Deploy that exact tag with `deploy/k8s/k8s-deploy.sh`.
6. Verify strict rollout success, expected image identities, pod/service/ingress health, the frontend-to-backend `/api/health` path, external `/api/health`, MCP `initialize`, and the changed real user workflow in IDC.
7. Treat the work as delivered only after IDC verification succeeds; report any infrastructure blocker explicitly and retain the previous image tag as the rollback point.

Do not treat CI, a successful image build, `/api/health`, or MCP initialization alone as complete business acceptance.
