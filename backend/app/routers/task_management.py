"""任务管理 API：开发任务中的 Bug 修复与非项目级委派任务。"""

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import get_current_user
from app.models import (
    AuthUser,
    Bug,
    BugFixTask,
    Ci,
    OrgMember,
    Project,
    ProjectDevelopmentTask,
    WbsTask,
    WorkTask,
)
from app.schemas.common import ok, paginate
from app.services import task_management

router = APIRouter(prefix="/api/task-management", tags=["task-management"])


class BugCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=1)
    ci_id: str
    priority: str = "P2"
    source_type: str | None = None
    source_id: str | None = None
    reproduction: str | None = None
    expected_result: str | None = None
    actual_result: str | None = None
    environment: str | None = None
    evidence: str | None = None


class BugUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    priority: str | None = None
    ci_id: str | None = None
    reproduction: str | None = None
    expected_result: str | None = None
    actual_result: str | None = None
    environment: str | None = None
    evidence: str | None = None


class ConfirmIn(BaseModel):
    comment: str = ""


class RejectIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class FixTaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    task_type: str = "开发"
    description: str | None = None
    assignee: str
    plan_start: date | None = None
    plan_date: date | None = None
    plan_effort: float | None = None


class FixTasksIn(BaseModel):
    tasks: list[FixTaskIn] = Field(min_length=1)


class FixTaskUpdate(BaseModel):
    name: str | None = None
    task_type: str | None = None
    description: str | None = None
    assignee: str | None = None
    plan_start: date | None = None
    plan_date: date | None = None
    plan_effort: float | None = None
    actual_effort: float | None = None
    status: str | None = None
    completion_note: str | None = None


class VerifyIn(BaseModel):
    verified: bool
    note: str = Field(min_length=1, max_length=1000)


class ReopenIn(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class WorkTaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=1)
    task_type: str = "其他"
    source_type: str = "manual"
    source_id: str | None = None
    assignee: str | None = None
    priority: str = "P3"
    plan_start: date | None = None
    plan_date: date | None = None
    plan_effort: float | None = None
    performance_bucket: str = "role_result"


class WorkTaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    task_type: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    assignee: str | None = None
    priority: str | None = None
    plan_start: date | None = None
    plan_date: date | None = None
    plan_effort: float | None = None
    actual_effort: float | None = None
    performance_bucket: str | None = None


class WorkTaskTransitionIn(BaseModel):
    to: str
    reason: str = ""


class TaskProgressIn(BaseModel):
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    comment: str = Field(min_length=1, max_length=2000)


class ProjectTaskCreate(BaseModel):
    project_id: str
    wbs_task_id: str | None = None
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=1)
    acceptance_criteria: str | None = None
    task_type: str = "开发"
    assignee: str | None = None
    priority: str = "P3"
    environment: str | None = None
    version: str | None = None
    plan_start: date | None = None
    plan_date: date | None = None
    plan_effort: float | None = None


class ProjectTaskUpdate(BaseModel):
    project_id: str | None = None
    wbs_task_id: str | None = None
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    acceptance_criteria: str | None = None
    task_type: str | None = None
    assignee: str | None = None
    priority: str | None = None
    environment: str | None = None
    version: str | None = None
    plan_start: date | None = None
    plan_date: date | None = None
    plan_effort: float | None = None
    actual_effort: float | None = None
    status: str | None = None
    completion_note: str | None = None


@router.get("/reference/cis")
def list_bug_ci_references(db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    """Bug 登记的所属系统只读选项：复用 CMDB 配置项，不要求用户具备 CMDB 管理权限。"""
    task_management._require_module(db, user, "task_bug", "view")
    rows = db.query(Ci).filter(Ci.is_deleted.is_(False), Ci.status != "已下线").order_by(Ci.name, Ci.ci_code).all()
    names = {
        member.id: member.name
        for member in db.query(OrgMember).filter(OrgMember.id.in_({row.product_manager_id for row in rows if row.product_manager_id}))
    }
    return ok([
        {
            "id": row.id,
            "ci_code": row.ci_code,
            "name": row.name,
            "category": row.category,
            "product_manager_name": names.get(row.product_manager_id),
        }
        for row in rows
    ], total=len(rows), page=1)


def _get_bug(db: Session, bug_id: str) -> Bug:
    bug = db.get(Bug, bug_id)
    if not bug or bug.is_deleted:
        raise AppError("NOT_FOUND", "Bug 不存在", 404)
    return bug


def _get_fix_task(db: Session, task_id: str) -> BugFixTask:
    task = db.get(BugFixTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "Bug 修复任务不存在", 404)
    return task


def _get_work_task(db: Session, task_id: str) -> WorkTask:
    task = db.get(WorkTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "委派任务不存在", 404)
    return task


def _get_project_task(db: Session, task_id: str) -> ProjectDevelopmentTask:
    task = db.get(ProjectDevelopmentTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "项目开发任务不存在", 404)
    return task


@router.get("/bugs")
def list_bugs(q: str = "", status: str = "", scope: str = "", db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    task_management._require_module(db, user, "task_bug", "view")
    query = db.query(Bug).filter(Bug.is_deleted.is_(False))
    if q:
        query = query.filter(Bug.title.ilike(f"%{q}%") | Bug.bug_code.ilike(f"%{q}%"))
    if status:
        query = query.filter(Bug.status == status)
    if scope == "mine" and user.person_id:
        query = query.filter((Bug.reporter_id == user.id) | (Bug.product_manager_id == user.person_id) | (Bug.dev_leader_id == user.person_id))
    rows = query.order_by(Bug.created_at.desc()).all()
    return ok([task_management._bug_row(db, bug, user) for bug in rows], total=len(rows), page=1)


@router.post("/bugs")
def create_bug(body: BugCreate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    bug = task_management.create_bug(db, body.model_dump(), user)
    db.commit()
    return ok(task_management._bug_row(db, bug, user))


@router.get("/bugs/{bug_id}")
def get_bug(bug_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    task_management._require_module(db, user, "task_bug", "view")
    return ok(task_management._bug_row(db, _get_bug(db, bug_id), user))


@router.patch("/bugs/{bug_id}")
def update_bug(bug_id: str, body: BugUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    bug = task_management.update_bug(db, _get_bug(db, bug_id), body.model_dump(exclude_unset=True), user)
    db.commit()
    return ok(task_management._bug_row(db, bug, user))


@router.delete("/bugs/{bug_id}")
def delete_bug(bug_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    bug = _get_bug(db, bug_id)
    stats = task_management.delete_bug(db, bug, user)
    db.commit()
    return ok({"id": bug.id, "deleted": True, "cascade": stats})


@router.post("/bugs/{bug_id}/confirm")
def confirm_bug(bug_id: str, body: ConfirmIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    bug = task_management.confirm_bug(db, _get_bug(db, bug_id), user, body.comment)
    db.commit()
    return ok(task_management._bug_row(db, bug, user))


@router.post("/bugs/{bug_id}/reject-confirm")
def reject_bug(bug_id: str, body: RejectIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    bug = task_management.reject_bug_confirmation(db, _get_bug(db, bug_id), user, body.reason)
    db.commit()
    return ok(task_management._bug_row(db, bug, user))


@router.post("/bugs/{bug_id}/fix-tasks")
def create_fix_tasks(bug_id: str, body: FixTasksIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    bug = _get_bug(db, bug_id)
    tasks = task_management.create_fix_tasks(db, bug, [row.model_dump() for row in body.tasks], user)
    db.commit()
    return ok({"bug": task_management._bug_row(db, bug, user), "tasks": [task_management._fix_task_row(db, task) for task in tasks]})


@router.patch("/bug-fix-tasks/{task_id}")
def update_fix_task(task_id: str, body: FixTaskUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    task = task_management.update_fix_task(db, _get_fix_task(db, task_id), body.model_dump(exclude_unset=True), user)
    db.commit()
    return ok(task_management._fix_task_row(db, task))


@router.post("/bugs/{bug_id}/verify")
def verify_bug(bug_id: str, body: VerifyIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    bug = task_management.verify_bug(db, _get_bug(db, bug_id), user, body.verified, body.note)
    db.commit()
    return ok(task_management._bug_row(db, bug, user))


@router.post("/bugs/{bug_id}/reopen")
def reopen_bug(bug_id: str, body: ReopenIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    bug = task_management.reopen_bug(db, _get_bug(db, bug_id), user, body.reason)
    db.commit()
    return ok(task_management._bug_row(db, bug, user))


@router.get("/work-tasks")
def list_work_tasks(q: str = "", status: str = "", scope: str = "", db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    rows, total = task_management.list_work_tasks(db, user, q, status, scope)
    return ok(rows, total=total, page=1)


@router.post("/work-tasks")
def create_work_task(body: WorkTaskCreate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    task = task_management.create_work_task(db, body.model_dump(), user)
    db.commit()
    return ok(task_management._work_row(db, task, user))


@router.get("/work-tasks/{task_id}")
def get_work_task(task_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    task_management._require_module(db, user, "task_delegated", "view")
    return ok(task_management._work_row(db, _get_work_task(db, task_id), user))


@router.patch("/work-tasks/{task_id}")
def update_work_task(task_id: str, body: WorkTaskUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    task = task_management.update_work_task(db, _get_work_task(db, task_id), body.model_dump(exclude_unset=True), user)
    db.commit()
    return ok(task_management._work_row(db, task, user))


@router.post("/work-tasks/{task_id}/transition")
def transition_work_task(task_id: str, body: WorkTaskTransitionIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    task = task_management.transition_work_task(db, _get_work_task(db, task_id), body.to, body.reason, user)
    db.commit()
    return ok(task_management._work_row(db, task, user))


@router.post("/work-tasks/{task_id}/progress")
def add_work_task_progress(
    task_id: str,
    body: TaskProgressIn,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    task = task_management.add_work_task_progress(
        db, _get_work_task(db, task_id), body.progress_percent, body.comment, user,
    )
    db.commit()
    return ok(task_management._work_row(db, task, user))


@router.delete("/work-tasks/{task_id}")
def delete_work_task(task_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    task = _get_work_task(db, task_id)
    task_management.delete_work_task(db, task, user)
    db.commit()
    return ok({"id": task.id, "deleted": True})


@router.get("/reference/projects")
def list_project_references(db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    task_management._require_module(db, user, "task_development", "view")
    rows = (
        db.query(Project)
        .filter(Project.is_deleted.is_(False))
        .order_by(Project.project_code.desc())
        .all()
    )
    return ok([
        {"id": row.id, "project_code": row.project_code, "name": row.name, "status": row.status}
        for row in rows
    ], total=len(rows), page=1)


@router.get("/reference/projects/{project_id}/wbs")
def list_project_wbs_references(
    project_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    task_management._require_module(db, user, "task_development", "view")
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise AppError("NOT_FOUND", "所属项目不存在", 404)
    rows = (
        db.query(WbsTask)
        .filter(WbsTask.project_id == project_id, WbsTask.is_deleted.is_(False))
        .order_by(WbsTask.wbs_code)
        .all()
    )
    return ok([
        {"id": row.id, "wbs_code": row.wbs_code, "name": row.name}
        for row in rows
    ], total=len(rows), page=1)


@router.get("/project-tasks")
def list_project_tasks(
    q: str = "", status: str = "", scope: str = "",
    db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user),
):
    rows, total = task_management.list_project_tasks(db, user, q, status, scope)
    return ok(rows, total=total, page=1)


@router.post("/project-tasks")
def create_project_task(
    body: ProjectTaskCreate,
    db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user),
):
    task = task_management.create_project_task(db, body.model_dump(), user)
    db.commit()
    return ok(task_management._project_task_row(db, task, user))


@router.get("/project-tasks/{task_id}")
def get_project_task(
    task_id: str,
    db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user),
):
    task_management._require_module(db, user, "task_development", "view")
    return ok(task_management._project_task_row(db, _get_project_task(db, task_id), user))


@router.patch("/project-tasks/{task_id}")
def update_project_task(
    task_id: str, body: ProjectTaskUpdate,
    db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user),
):
    task = task_management.update_project_task(
        db, _get_project_task(db, task_id), body.model_dump(exclude_unset=True), user,
    )
    db.commit()
    return ok(task_management._project_task_row(db, task, user))


@router.post("/project-tasks/{task_id}/progress")
def add_project_task_progress(
    task_id: str, body: TaskProgressIn,
    db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user),
):
    task = task_management.add_project_task_progress(
        db, _get_project_task(db, task_id), body.progress_percent, body.comment, user,
    )
    db.commit()
    return ok(task_management._project_task_row(db, task, user))


@router.delete("/project-tasks/{task_id}")
def delete_project_task(
    task_id: str,
    db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user),
):
    task = _get_project_task(db, task_id)
    task_management.delete_project_task(db, task, user)
    db.commit()
    return ok({"id": task.id, "deleted": True})
