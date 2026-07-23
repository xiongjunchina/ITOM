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

## Deployment and verification environment

The IDC Kubernetes cluster is the sole delivery and acceptance environment. Do not deploy or validate changes with the local Docker environment unless the user explicitly asks for a temporary local investigation.

For every user-visible fix or feature, the default completion flow is:

1. Implement the code and synchronize affected Chinese and English documentation.
2. Run the relevant automated tests and production frontend build locally.
3. Build and publish the backend/frontend images required by `deploy/k8s`.
4. Deploy to the IDC Kubernetes cluster with the repository deployment scripts.
5. Verify rollout status, pod/service health, the frontend-to-backend `/api/health` path, and the changed user workflow in the IDC environment.
6. Treat the work as delivered only after IDC verification succeeds; report any infrastructure blocker explicitly.

Do not treat a successful local build, test run, or local Docker deployment as final acceptance.
