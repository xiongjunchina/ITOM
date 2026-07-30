# Task Management Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the new Task Management area with compatible requirement-development tasks, a dedicated Bug repair workflow, and delegated work tasks without changing existing business history.

**Architecture:** Keep `RequirementTask` as the source of truth for requirement-development rows. Add separate `Bug`/`BugFixTask` and `WorkTask` aggregates, using the existing workflow engine, RBAC, audit, soft-delete, and event/points services. Preserve old requirement routes and permission codes while exposing new pages and APIs.

**Tech Stack:** FastAPI, SQLAlchemy 2, PostgreSQL startup migrations, existing workflow engine, React + TypeScript + Ant Design, pytest, Vite.

## Global Constraints

- Work only on `feature/aily-agent-mcp`; never push `main`.
- Before each new development batch, verify clean worktree and local HEAD equals the GitHub branch tip.
- No destructive migration: existing `requirement_task`, `problem`, `point_entry`, performance, and process history remain readable.
- Every behavior/API/model/permission change updates Chinese authoritative docs and matching `docs/en` mirrors in the same delivery.
- Write failing tests before production code and run the relevant test after every task.
- IDC Kubernetes is the only final runtime and acceptance environment; local Docker is not used for acceptance.

---

### Task 1: Add additive models and migration contract

**Files:**
- Modify: `backend/app/models/itsm_assets.py` (add nullable CI product-manager reference)
- Modify: `backend/app/models/requirement.py` (add `Bug`, `BugFixTask`, `WorkTask` in a focused module if the model package pattern permits)
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/services/migrate.py`
- Test: `backend/tests/test_m82_task_management_models.py`
- Docs: `docs/04-数据模型设计.md`, `docs/en/04-data-model-design.md`

**Interfaces:**
- Produces SQLAlchemy models and startup migration columns used by later API tasks.
- New status values are persisted as Chinese UI states with stable English entity/process codes where the existing module uses codes.

- [x] **Step 1: Write failing model/migration tests**

  Assert that the new tables are created in the test metadata, `ci.product_manager_id` is nullable, and the existing `requirement_task` rows remain queryable after migration setup.

- [x] **Step 2: Run the focused tests and verify the expected failure**

  Run: `cd backend && python -m pytest tests/test_m82_task_management_models.py -q`

  Expected: failure because the new models and migration column do not exist.

- [x] **Step 3: Implement the additive model and migration definitions**

  Add only new tables and nullable columns. Do not add a delete operation, data rewrite, or destructive column migration.

- [x] **Step 4: Run the focused tests and verify they pass**

  Run: `cd backend && python -m pytest tests/test_m82_task_management_models.py -q`

- [x] **Step 5: Update model documentation and commit**

  Document fields, soft-delete behavior, historical snapshot fields, and compatibility guarantees in both language versions, then commit with `feat(task): add compatible task domain models`.

### Task 2: Add permissions, codes, and Bug workflow definition

**Files:**
- Modify: `backend/app/services/permissions.py`
- Modify: `backend/app/services/seed.py`
- Modify: `backend/app/services/migrate.py` if a new versioned process definition needs an idempotent upgrade
- Test: `backend/tests/test_m82_task_management_permissions.py`
- Test: `backend/tests/test_m82_bug_flow_definition.py`
- Docs: `docs/06-用户身份与组织模型设计.md`, `docs/en/06-user-identity-and-organization-model.md`

**Interfaces:**
- Produces permission modules `task_development`, `task_bug`, and `task_delegated`, while retaining `req_tasks`.
- Produces a versioned `bug_flow` with five steps and approval/processing node semantics.

- [x] **Step 1: Write failing permission and flow tests**

  Cover IT-member visibility, requester denial, administrator management, product-manager confirmation, developer-task execution, and product-manager verification assignment.

- [x] **Step 2: Run the tests and verify the expected failure**

  Run: `cd backend && python -m pytest tests/test_m82_task_management_permissions.py tests/test_m82_bug_flow_definition.py -q`

- [x] **Step 3: Implement permission defaults and idempotent workflow seeding**

  Ensure an existing administrator-edited permission row is not overwritten. Use a new process-definition version instead of mutating an active definition used by historical instances.

- [x] **Step 4: Run the focused tests and verify they pass**

- [x] **Step 5: Commit the permission and workflow slice**

  Commit with `feat(task): add task permissions and bug workflow`.

### Task 3: Implement Bug and delegated-task domain APIs

**Files:**
- Create: `backend/app/routers/task_management.py`
- Create: `backend/app/services/task_management.py`
- Modify: `backend/app/main.py` to register the router if required by the existing assembly pattern
- Test: `backend/tests/test_m82_bug_flow_api.py`
- Test: `backend/tests/test_m82_work_task_api.py`
- Docs: `docs/05-API契约与架构设计.md`, `docs/en/05-api-contract-and-architecture.md`

**Interfaces:**
- `GET/POST/PATCH /api/task-management/bugs`
- `GET /api/task-management/bugs/{id}`
- `POST /api/task-management/bugs/{id}/confirm`
- `POST /api/task-management/bugs/{id}/reject-confirm`
- `POST /api/task-management/bugs/{id}/fix-tasks`
- `PATCH /api/task-management/bug-fix-tasks/{id}`
- `POST /api/task-management/bugs/{id}/verify`
- `POST /api/task-management/bugs/{id}/reopen`
- `GET/POST/PATCH/DELETE /api/task-management/work-tasks`
- `POST /api/task-management/work-tasks/{id}/transition`

- [x] **Step 1: Write failing API tests**

  Cover Bug registration with CI/product-manager snapshot, confirmation authorization, multi-row fix-task creation, child-task completion gate, verification close, reopen, delegated-task lifecycle, search, and delete rules.

- [x] **Step 2: Run the API tests and verify the expected failures**

  Run: `cd backend && python -m pytest tests/test_m82_bug_flow_api.py tests/test_m82_work_task_api.py -q`

- [x] **Step 3: Implement domain services before route handlers**

  Centralize state transitions, assignee scope checks, product-manager snapshot resolution, all-child-task completion checks, soft-delete rules, event publication, and audit summaries in the service layer.

- [x] **Step 4: Implement route handlers using the domain service**

  Route handlers must not write tables directly without invoking the service validation. All list responses include capability fields for the frontend.

- [x] **Step 5: Run focused tests and then the existing requirement/problem suites**

  Run: `cd backend && python -m pytest tests/test_m82_bug_flow_api.py tests/test_m82_work_task_api.py tests/test_m5_requirements.py tests/test_m18_task_guard.py tests/test_m29_problem_flow.py -q`

- [x] **Step 6: Commit the backend domain slice**

  Commit with `feat(task): implement bug and delegated task APIs`.

### Task 4: Rebuild the frontend task-management navigation and pages

**Files:**
- Modify: `frontend/src/components/menu.tsx`
- Modify: `frontend/src/router.tsx`
- Create or modify: `frontend/src/pages/task-management/DevelopmentTasksPage.tsx`
- Create or modify: `frontend/src/pages/task-management/BugListPage.tsx`
- Create or modify: `frontend/src/pages/task-management/DelegatedTasksPage.tsx`
- Modify: `frontend/src/pages/requirements/ActiveTaskList.tsx` for compatible reuse
- Modify: `frontend/src/api/types.ts`, `frontend/src/i18n/*`
- Test/build: existing frontend typecheck and production build
- Docs: `docs/03-PRD.md`, `docs/用户操作手册.md`, `docs/en/03-PRD.md`, `docs/en/user-operation-manual.md`

**Interfaces:**
- New menu routes `/task-management/development` and `/task-management/delegated`.
- Legacy `/requirements/tasks` redirects to the requirement-development tab without losing bookmarks.

- [ ] **Step 1: Add frontend contract fixtures/tests for tabs and capability fields**

- [ ] **Step 2: Run the frontend typecheck/build and verify the missing-route failure**

  Run: `cd frontend && npm run build`

- [ ] **Step 3: Implement the menu, router, tabs, list filters, search, and action visibility**

  Keep requirement task editing semantics unchanged. Add Bug and delegated-task forms only for fields validated by the backend.

- [ ] **Step 4: Implement admin list actions and ordinary-user restrictions**

  Render edit/pause/abort/close/delete only from backend capability fields; failed API authorization remains visible as a handled error.

- [ ] **Step 5: Run the frontend build**

- [ ] **Step 6: Commit the frontend slice**

  Commit with `feat(task): add task management pages`.

### Task 5: Add performance and points integrations

**Files:**
- Modify: `backend/app/services/points.py`
- Modify: `backend/app/services/perf.py`
- Modify: `backend/app/services/perf_bplus.py`
- Modify: `backend/app/services/seed.py`
- Test: `backend/tests/test_m82_task_performance.py`
- Docs: `docs/03-PRD.md`, `docs/08-IT团队角色绩效评分PRD.md`, `docs/05-API契约与架构设计.md`, matching `docs/en/` mirrors

**Interfaces:**
- New role-result metrics `bug_fix_delivery` and `delegated_work_delivery`.
- New idempotent events for BugFixTask completion and accepted delegated-task completion.

- [ ] **Step 1: Write failing performance tests**

  Assert requirement-task scoring remains unchanged, BugFixTask on-time completion is counted once, delegated work defaults to role result, and team-contribution mappings require the explicit eligible category.

- [ ] **Step 2: Run the focused tests and verify the expected failure**

  Run: `cd backend && python -m pytest tests/test_m82_task_performance.py -q`

- [ ] **Step 3: Implement event subscribers and metric extraction**

  Preserve existing role-result/team-contribution buckets and use source entity IDs for idempotency.

- [ ] **Step 4: Run focused performance and existing performance tests**

  Run: `cd backend && python -m pytest tests/test_m82_task_performance.py tests/test_m61_perf.py tests/test_m62_perf.py tests/test_bplus_performance.py -q`

- [ ] **Step 5: Commit the performance slice**

  Commit with `feat(task): include bug and delegated work in performance metrics`.

### Task 6: Full verification and IDC acceptance

**Files:**
- Modify: affected Chinese docs and matching `docs/en` mirrors only where implementation differs from the committed design
- Test: all affected backend tests and full frontend build

- [ ] **Step 1: Run backend tests**

  Run: `cd backend && python -m pytest -q`

- [ ] **Step 2: Run frontend production build**

  Run: `cd frontend && npm run build`

- [ ] **Step 3: Run static checks**

  Run: `git diff --check`

- [ ] **Step 4: Push the clean feature branch and wait for GitHub Quality Gate**

  Verify the pushed commit is the same as local HEAD before image build.

- [ ] **Step 5: Build/publish linux/amd64 images and deploy IDC**

  Use `deploy/k8s/push-images.sh` and `deploy/k8s/k8s-deploy.sh`; do not start local Docker for acceptance.

- [ ] **Step 6: Verify rollout, health, permissions, lifecycle, history, and performance evidence in IDC**

  Test requirement task compatibility, Bug five-node flow, delegated lifecycle, deletion restrictions, search, historical records, and a multi-role performance recompute.

- [ ] **Step 7: Commit any final documentation corrections, push, and report the evidence**

  Only after fresh command output confirms the required tests, build, rollout, and UAT results may the work be described as complete or proposed for a Pull Request to `main`.
