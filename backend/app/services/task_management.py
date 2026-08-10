"""任务管理领域服务：Bug 修复与非项目级委派任务。

路由层只负责 HTTP 入参和响应；本模块负责记录级权限、流程推进、状态校验、
审计以及软删除，避免前端或 MCP 绕过业务规则直接修改任务表。
"""

from datetime import date, datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.rbac import ADMIN
from app.events.bus import publish
from app.models import AuthUser, Bug, BugFixTask, Ci, OrgMember, ProcessTask, WorkTask
from app.services import process_engine
from app.services.audit import audit
from app.services.codes import gen_code
from app.services.permissions import has_perm
from app.services.rbac import actor_keys
from app.services.team_scope import require_it_member_if_configured

BUG_STATUSES = ("registered", "confirmed", "fixing", "resolved", "closed", "rejected")
FIX_TASK_STATUSES = ("登记", "排期", "执行", "暂停", "关闭")
WORK_TASK_STATUSES = ("登记", "排期", "执行", "暂停", "关闭", "中止")
# 只有明确属于团队贡献的类别，才允许把委派任务计入固定 20% 团队贡献；
# 其他委派工作默认归入岗位结果，避免普通工作被错误计入团队贡献。
TEAM_CONTRIBUTION_TASK_RULES = {
    "技术研究": "work_task_learning_growth",
    "跨团队支持": "work_task_cross_team_support",
    "知识分享": "work_task_training_knowledge",
}


def _validate_performance_bucket(task_type: str, performance_bucket: str):
    if performance_bucket not in {"role_result", "team_contribution"}:
        raise AppError("INVALID_PERFORMANCE_BUCKET", "绩效归属必须为岗位结果或团队贡献")
    if performance_bucket == "team_contribution" and task_type not in TEAM_CONTRIBUTION_TASK_RULES:
        raise AppError("INVALID_PERFORMANCE_CATEGORY", "团队贡献必须选择技术研究、跨团队支持或知识分享任务类型")


def _is_admin(db: Session, user: AuthUser) -> bool:
    return ADMIN in actor_keys(db, user)


def _require_module(db: Session, user: AuthUser, module: str, action: str):
    if not has_perm(db, user, module, action):
        raise AppError("FORBIDDEN", "没有该功能的操作权限，请联系管理员配置", 403)


def _require_person(user: AuthUser) -> str:
    if not user.person_id:
        raise AppError("PERSON_REQUIRED", "当前账号未绑定人员，不能登记或处理任务", 403)
    return user.person_id


def _member_name(db: Session, person_id: str | None) -> str | None:
    member = db.get(OrgMember, person_id) if person_id else None
    return member.name if member else None


def _current_bug_task(db: Session, bug_id: str) -> ProcessTask | None:
    return process_engine.current_pending_task(db, "bug", bug_id)


def _require_bug_operator(db: Session, bug: Bug, user: AuthUser, expected_seq: int | None = None):
    task = _current_bug_task(db, bug.id)
    if not task:
        raise AppError("BUG_FLOW_NOT_ACTIVE", "Bug 当前没有可处理的流程节点")
    if expected_seq is not None and task.step and task.step.seq != expected_seq:
        raise AppError("BUG_FLOW_STAGE", "Bug 当前不在允许执行此操作的流程节点")
    if not process_engine.can_act_on_task(db, user, task):
        raise AppError("FORBIDDEN", "仅当前流程节点处理人可以执行此操作", 403)
    # Clicking any Bug processing action is an actual handling event, so it
    # must close the upstream correction window even outside the generic
    # process-task HTTP routes.
    task, _ = process_engine.mark_task_viewed(db, user, task.id, handling_action=True)
    return task


def _assign_current_bug_task(db: Session, bug_id: str, assignee: str | None):
    task = _current_bug_task(db, bug_id)
    if task and assignee:
        task.assignee = assignee
    return task


def _bug_process_start(db: Session, bug: Bug, actor: AuthUser):
    """启动 Bug 流程并自动完成“登记 Bug”，将确认节点交给产品经理。"""
    instance = process_engine.start_instance(
        db, "bug", bug.id, {}, preferred_assignee=bug.reporter_id and actor.person_id
    )
    if not instance:
        raise AppError("BUG_FLOW_UNAVAILABLE", "Bug 流程未配置或未启用")
    first = _current_bug_task(db, bug.id)
    if first:
        process_engine.complete_task(db, first.id, actor, "Bug 已登记")
    confirmation = _assign_current_bug_task(db, bug.id, bug.product_manager_id)
    if not confirmation or not confirmation.assignee:
        raise AppError("PRODUCT_MANAGER_UNAVAILABLE", "所属系统未配置在岗产品经理，无法进入 Bug 确认")
    return instance


def _bug_row(db: Session, bug: Bug, user: AuthUser | None = None) -> dict:
    ci = db.get(Ci, bug.ci_id) if bug.ci_id else None
    tasks = db.query(BugFixTask).filter(BugFixTask.bug_id == bug.id, BugFixTask.is_deleted.is_(False)).all()
    is_admin = bool(user and _is_admin(db, user))
    person_id = user.person_id if user else None
    edit_access = (
        process_engine.workflow_edit_access(db, user, "bug", bug.id, "task_bug")
        if user else process_engine.WorkflowEditAccess(False)
    )
    delete_access = (
        process_engine.workflow_delete_access(db, user, "bug", bug.id, "task_bug")
        if user else process_engine.WorkflowEditAccess(False)
    )
    can_edit = edit_access.allowed
    can_confirm = bool(user and bug.product_manager_id and person_id == bug.product_manager_id and bug.status == "registered")
    can_generate = bool(user and bug.dev_leader_id and person_id == bug.dev_leader_id and bug.status == "confirmed")
    can_verify = bool(user and bug.product_manager_id and person_id == bug.product_manager_id and bug.status == "resolved")
    return {
        "id": bug.id,
        "bug_code": bug.bug_code,
        "title": bug.title,
        "description": bug.description,
        "priority": bug.priority,
        "status": bug.status,
        "ci_id": bug.ci_id,
        "ci_name": ci.name if ci else None,
        "product_manager_id": bug.product_manager_id,
        "product_manager_name": _member_name(db, bug.product_manager_id),
        "dev_leader_id": bug.dev_leader_id,
        "dev_leader_name": _member_name(db, bug.dev_leader_id),
        "reporter_id": bug.reporter_id,
        "reproduction": bug.reproduction,
        "expected_result": bug.expected_result,
        "actual_result": bug.actual_result,
        "environment": bug.environment,
        "evidence": bug.evidence,
        "resolution_note": bug.resolution_note,
        "verification_note": bug.verification_note,
        "rejection_reason": bug.rejection_reason,
        "reopened_at": bug.reopened_at,
        "closed_at": bug.closed_at,
        "fix_tasks": [_fix_task_row(db, task) for task in tasks],
        "process": process_engine.instance_view(db, "bug", bug.id),
        "capabilities": {
            "edit": can_edit,
            "delete": delete_access.allowed,
            "confirm": can_confirm or is_admin,
            "generate_fix_tasks": can_generate or is_admin,
            "verify": can_verify or is_admin,
            "reopen": is_admin or bool(person_id and (bug.reporter_id == user.id or bug.product_manager_id == person_id)),
        },
        "workflow_edit_mode": edit_access.mode,
        "workflow_edit_locked_reason": edit_access.reason,
    }


def _fix_task_row(db: Session, task: BugFixTask) -> dict:
    return {
        "id": task.id,
        "bug_id": task.bug_id,
        "name": task.name,
        "task_type": task.task_type,
        "description": task.description,
        "assignee": task.assignee,
        "assignee_name": _member_name(db, task.assignee),
        "plan_start": task.plan_start,
        "plan_date": task.plan_date,
        "plan_effort": task.plan_effort,
        "actual_effort": task.actual_effort,
        "status": task.status,
        "done_at": task.done_at,
        "completion_note": task.completion_note,
    }


def create_bug(db: Session, data: dict, actor: AuthUser) -> Bug:
    _require_module(db, actor, "task_bug", "create")
    reporter_id = _require_person(actor)
    ci = db.get(Ci, data["ci_id"])
    if not ci or ci.is_deleted:
        raise AppError("NOT_FOUND", "所属系统不存在", 404)
    if not ci.product_manager_id:
        raise AppError("PRODUCT_MANAGER_REQUIRED", "所属系统尚未配置产品经理，不能登记 Bug")
    bug = Bug(
        bug_code=gen_code(db, Bug, "bug_code", "BG"),
        title=data["title"],
        description=data["description"],
        priority=data.get("priority") or "P2",
        ci_id=ci.id,
        product_manager_id=ci.product_manager_id,
        reporter_id=actor.id,
        source_type=data.get("source_type"),
        source_id=data.get("source_id"),
        reproduction=data.get("reproduction"),
        expected_result=data.get("expected_result"),
        actual_result=data.get("actual_result"),
        environment=data.get("environment"),
        evidence=data.get("evidence"),
    )
    db.add(bug)
    db.flush()
    _bug_process_start(db, bug, actor)
    audit(db, "bug", bug.id, "create", actor, {"code": bug.bug_code, "ci_id": bug.ci_id})
    publish(db, "bug.registered", "bug", bug.id, {"bug_code": bug.bug_code})
    return bug


def update_bug(db: Session, bug: Bug, data: dict, actor: AuthUser) -> Bug:
    access = process_engine.require_workflow_edit(db, actor, "bug", bug.id, "task_bug")
    allowed = {
        "title", "description", "priority", "reproduction", "expected_result", "actual_result", "environment", "evidence",
    }
    for key, value in data.items():
        if key in allowed:
            setattr(bug, key, value)
    audit(db, "bug", bug.id, "update", actor, {
        "fields": [key for key in data if key in allowed], "workflow_edit_mode": access.mode,
    })
    return bug


def delete_bug(db: Session, bug: Bug, actor: AuthUser):
    """Soft-delete an unreviewed Bug registration and its dependent work safely."""
    access = process_engine.require_workflow_delete(db, actor, "bug", bug.id, "task_bug")
    from app.models import BugFixTask

    stats = {"fix_tasks": 0, "process_instances": 0}
    for task in db.query(BugFixTask).filter(BugFixTask.bug_id == bug.id, BugFixTask.is_deleted.is_(False)):
        task.is_deleted = True
        stats["fix_tasks"] += 1
    stats["process_instances"] = process_engine.archive_instances(
        db, "bug", bug.id, "[单据删除] Bug 已撤回或删除"
    )
    bug.is_deleted = True
    audit(db, "bug", bug.id, "delete", actor, {
        "code": bug.bug_code, **stats, "workflow_delete_mode": access.mode,
    })
    return stats


def confirm_bug(db: Session, bug: Bug, actor: AuthUser, comment: str = "") -> Bug:
    _require_module(db, actor, "task_bug", "edit")
    if bug.status != "registered":
        raise AppError("BUG_STAGE", "只有已登记 Bug 可以确认")
    task = _require_bug_operator(db, bug, actor, expected_seq=2)
    process_engine.approve_task(db, task.id, actor, comment)
    bug.status = "confirmed"
    next_task = _current_bug_task(db, bug.id)
    bug.dev_leader_id = next_task.assignee if next_task else None
    if not bug.dev_leader_id:
        raise AppError("DEV_LEADER_UNAVAILABLE", "当前没有可用的开发负责人，无法生成修复任务")
    audit(db, "bug", bug.id, "confirm", actor, {"comment": comment})
    publish(db, "bug.confirmed", "bug", bug.id, {"dev_leader_id": bug.dev_leader_id})
    return bug


def reject_bug_confirmation(db: Session, bug: Bug, actor: AuthUser, reason: str) -> Bug:
    _require_module(db, actor, "task_bug", "edit")
    if bug.status != "registered":
        raise AppError("BUG_STAGE", "只有已登记 Bug 可以驳回确认")
    if len(reason.strip()) < 5:
        raise AppError("REASON_REQUIRED", "驳回理由至少 5 个字")
    task = _require_bug_operator(db, bug, actor, expected_seq=2)
    process_engine.reject_task(db, task.id, actor, reason)
    bug.status = "rejected"
    bug.rejection_reason = reason.strip()
    audit(db, "bug", bug.id, "reject_confirm", actor, {"reason": bug.rejection_reason})
    return bug


def create_fix_tasks(db: Session, bug: Bug, rows: list[dict], actor: AuthUser) -> list[BugFixTask]:
    _require_module(db, actor, "task_bug", "edit")
    if bug.status != "confirmed":
        raise AppError("BUG_STAGE", "只有已确认 Bug 可以生成修复任务")
    task = _require_bug_operator(db, bug, actor, expected_seq=3)
    if not rows:
        raise AppError("TASK_REQUIRED", "至少登记一条修复任务")
    result = []
    for row in rows:
        assignee = row.get("assignee")
        if not assignee:
            raise AppError("ASSIGNEE_REQUIRED", "每条修复任务必须指定执行人")
        require_it_member_if_configured(db, assignee, "Bug 修复任务负责人")
        item = BugFixTask(
            bug_id=bug.id,
            name=row["name"],
            task_type=row.get("task_type") or "开发",
            description=row.get("description"),
            assignee=assignee,
            plan_start=row.get("plan_start"),
            plan_date=row.get("plan_date"),
            plan_effort=row.get("plan_effort"),
        )
        db.add(item)
        result.append(item)
    db.flush()
    bug.status = "fixing"
    process_engine.complete_task(db, task.id, actor, f"已生成 {len(result)} 条修复任务")
    audit(db, "bug", bug.id, "generate_fix_tasks", actor, {"count": len(result)})
    publish(db, "bug.fix_tasks_created", "bug", bug.id, {"task_ids": [item.id for item in result]})
    return result


def update_fix_task(db: Session, task: BugFixTask, data: dict, actor: AuthUser) -> BugFixTask:
    _require_module(db, actor, "task_bug", "edit")
    bug = db.get(Bug, task.bug_id)
    if not bug or bug.is_deleted or task.is_deleted:
        raise AppError("NOT_FOUND", "Bug 修复任务不存在", 404)
    is_admin = _is_admin(db, actor)
    is_leader = bool(actor.person_id and actor.person_id == bug.dev_leader_id)
    is_assignee = bool(actor.person_id and actor.person_id == task.assignee)
    fields = set(data)
    if not is_admin and not is_leader and not (is_assignee and fields <= {"status", "actual_effort", "completion_note"}):
        raise AppError("FORBIDDEN", "仅开发负责人、任务负责人或管理员可以维护修复任务", 403)
    if "assignee" in data:
        require_it_member_if_configured(db, data["assignee"], "Bug 修复任务负责人")
    if "status" in data:
        status = data["status"]
        if status not in FIX_TASK_STATUSES:
            raise AppError("INVALID_STATUS", "修复任务状态必须为 登记/排期/执行/暂停/关闭")
        allowed = {
            "登记": {"排期"}, "排期": {"执行"}, "执行": {"暂停", "关闭"}, "暂停": {"执行", "关闭"}, "关闭": set(),
        }
        if status != task.status and status not in allowed.get(task.status, set()) and not is_admin:
            raise AppError("INVALID_TRANSITION", f"不允许从「{task.status}」流转到「{status}」")
    old_status = task.status
    for key, value in data.items():
        if key in {"name", "task_type", "description", "assignee", "plan_start", "plan_date", "plan_effort", "actual_effort", "status", "completion_note"}:
            setattr(task, key, value)
    if data.get("status") == "关闭":
        task.done_at = task.done_at or datetime.now()
        if old_status != "关闭":
            publish(db, "bug_fix_task.completed", "bug_fix_task", task.id, {"task_id": task.id, "bug_id": bug.id})
    audit(db, "bug_fix_task", task.id, "update", actor, {"fields": list(data)})
    db.flush()
    live_tasks = db.query(BugFixTask).filter(BugFixTask.bug_id == bug.id, BugFixTask.is_deleted.is_(False)).all()
    if live_tasks and all(item.status == "关闭" for item in live_tasks) and bug.status == "fixing":
        bug.status = "resolved"
        flow_task = _current_bug_task(db, bug.id)
        if flow_task and flow_task.step and flow_task.step.seq == 4:
            process_engine.complete_task(db, flow_task.id, actor, "全部修复任务已关闭，等待产品经理验证")
            _assign_current_bug_task(db, bug.id, bug.product_manager_id)
        audit(db, "bug", bug.id, "ready_for_verification", actor, {"task_count": len(live_tasks)})
        publish(db, "bug.ready_for_verification", "bug", bug.id, {})
    return task


def verify_bug(db: Session, bug: Bug, actor: AuthUser, verified: bool, note: str) -> Bug:
    _require_module(db, actor, "task_bug", "edit")
    if bug.status != "resolved":
        raise AppError("BUG_STAGE", "只有待验证 Bug 可以执行验证")
    if not note.strip():
        raise AppError("NOTE_REQUIRED", "验证说明不能为空")
    task = _require_bug_operator(db, bug, actor, expected_seq=5)
    bug.verification_note = note.strip()
    if verified:
        process_engine.approve_task(db, task.id, actor, note)
        bug.status = "closed"
        bug.closed_at = datetime.now()
        audit(db, "bug", bug.id, "verify_close", actor, {"note": note.strip()})
        publish(db, "bug.closed", "bug", bug.id, {})
    else:
        bug.status = "fixing"
        bug.rejection_reason = note.strip()
        for fix_task in db.query(BugFixTask).filter(BugFixTask.bug_id == bug.id, BugFixTask.is_deleted.is_(False)):
            fix_task.status = "执行"
            fix_task.done_at = None
        process_engine.rewind_to_step(db, "bug", bug.id, 4)
        audit(db, "bug", bug.id, "verify_reject", actor, {"reason": note.strip()})
        publish(db, "bug.reopened", "bug", bug.id, {"reason": note.strip()})
    return bug


def reopen_bug(db: Session, bug: Bug, actor: AuthUser, reason: str) -> Bug:
    _require_module(db, actor, "task_bug", "edit")
    if len(reason.strip()) < 2:
        raise AppError("REASON_REQUIRED", "重新打开原因不能为空")
    is_owner = bool(actor.person_id and (bug.product_manager_id == actor.person_id or bug.reporter_id == actor.id))
    if not _is_admin(db, actor) and not is_owner:
        raise AppError("FORBIDDEN", "仅登记人、产品经理或管理员可以重新打开 Bug", 403)
    if bug.status == "rejected":
        bug.status = "registered"
        bug.rejection_reason = reason.strip()
        bug.reopened_at = datetime.now()
        _bug_process_start(db, bug, actor)
    elif bug.status in ("closed", "resolved"):
        bug.status = "fixing"
        bug.reopened_at = datetime.now()
        bug.rejection_reason = reason.strip()
        for fix_task in db.query(BugFixTask).filter(BugFixTask.bug_id == bug.id, BugFixTask.is_deleted.is_(False)):
            fix_task.status = "执行"
            fix_task.done_at = None
        process_engine.rewind_to_step(db, "bug", bug.id, 4, preferred_assignee=bug.dev_leader_id)
    else:
        raise AppError("BUG_STAGE", "当前状态不支持重新打开")
    audit(db, "bug", bug.id, "reopen", actor, {"reason": reason.strip()})
    publish(db, "bug.reopened", "bug", bug.id, {"reason": reason.strip()})
    return bug


def _work_row(db: Session, task: WorkTask, user: AuthUser | None = None) -> dict:
    is_admin = bool(user and _is_admin(db, user))
    person_id = user.person_id if user else None
    can_edit = is_admin or (
        bool(person_id and task.registrar == person_id and task.assignee is None and task.status == "登记")
    )
    can_delete = is_admin or (
        bool(person_id and task.registrar == person_id and task.assignee is None and task.status == "登记")
    )
    can_transition = is_admin or bool(person_id and (task.assignee == person_id or task.registrar == person_id))
    return {
        "id": task.id,
        "task_code": task.task_code,
        "title": task.title,
        "description": task.description,
        "task_type": task.task_type,
        "source_type": task.source_type,
        "source_id": task.source_id,
        "registrar": task.registrar,
        "registrar_name": _member_name(db, task.registrar),
        "assignee": task.assignee,
        "assignee_name": _member_name(db, task.assignee),
        "priority": task.priority,
        "plan_start": task.plan_start,
        "plan_date": task.plan_date,
        "plan_effort": task.plan_effort,
        "actual_effort": task.actual_effort,
        "status": task.status,
        "performance_bucket": task.performance_bucket,
        "pause_reason": task.pause_reason,
        "abort_reason": task.abort_reason,
        "completion_note": task.completion_note,
        "closed_at": task.closed_at,
        "capabilities": {"edit": can_edit or is_admin, "delete": can_delete, "transition": can_transition},
    }


def list_work_tasks(db: Session, user: AuthUser, q: str = "", status: str = "", scope: str = "") -> tuple[list[dict], int]:
    _require_module(db, user, "task_delegated", "view")
    query = db.query(WorkTask).filter(WorkTask.is_deleted.is_(False))
    if q:
        query = query.filter(or_(WorkTask.title.ilike(f"%{q}%"), WorkTask.task_code.ilike(f"%{q}%")))
    if status:
        query = query.filter(WorkTask.status == status)
    if scope == "mine" and user.person_id:
        query = query.filter(or_(WorkTask.registrar == user.person_id, WorkTask.assignee == user.person_id))
    rows = query.order_by(WorkTask.created_at.desc()).all()
    return [_work_row(db, task, user) for task in rows], len(rows)


def create_work_task(db: Session, data: dict, actor: AuthUser) -> WorkTask:
    _require_module(db, actor, "task_delegated", "create")
    registrar = _require_person(actor)
    _validate_performance_bucket(data.get("task_type") or "其他", data.get("performance_bucket") or "role_result")
    if data.get("assignee"):
        require_it_member_if_configured(db, data["assignee"], "委派任务负责人")
    task = WorkTask(
        task_code=gen_code(db, WorkTask, "task_code", "WT"),
        title=data["title"],
        description=data["description"],
        task_type=data.get("task_type") or "其他",
        source_type=data.get("source_type") or "manual",
        source_id=data.get("source_id"),
        registrar=registrar,
        assignee=data.get("assignee"),
        priority=data.get("priority") or "P3",
        plan_start=data.get("plan_start"),
        plan_date=data.get("plan_date"),
        plan_effort=data.get("plan_effort"),
        performance_bucket=data.get("performance_bucket") or "role_result",
    )
    db.add(task)
    db.flush()
    audit(db, "work_task", task.id, "create", actor, {"code": task.task_code, "source_type": task.source_type})
    publish(db, "work_task.created", "work_task", task.id, {"task_code": task.task_code})
    return task


def update_work_task(db: Session, task: WorkTask, data: dict, actor: AuthUser) -> WorkTask:
    _require_module(db, actor, "task_delegated", "edit")
    is_admin = _is_admin(db, actor)
    is_registrar_unassigned = bool(actor.person_id and task.registrar == actor.person_id and task.assignee is None and task.status == "登记")
    if not is_admin and not is_registrar_unassigned:
        raise AppError("FORBIDDEN", "委派任务分配后仅管理员可以编辑", 403)
    _validate_performance_bucket(
        data.get("task_type", task.task_type),
        data.get("performance_bucket", task.performance_bucket),
    )
    if "assignee" in data and data["assignee"]:
        require_it_member_if_configured(db, data["assignee"], "委派任务负责人")
    for key, value in data.items():
        if hasattr(task, key) and key not in {"task_code", "registrar", "is_deleted"}:
            setattr(task, key, value)
    audit(db, "work_task", task.id, "update", actor, {"fields": list(data)})
    return task


def transition_work_task(db: Session, task: WorkTask, to: str, reason: str, actor: AuthUser) -> WorkTask:
    _require_module(db, actor, "task_delegated", "edit")
    if to not in WORK_TASK_STATUSES:
        raise AppError("INVALID_STATUS", "任务状态必须为 登记/排期/执行/暂停/关闭/中止")
    is_admin = _is_admin(db, actor)
    is_owner = bool(actor.person_id and (task.assignee == actor.person_id or task.registrar == actor.person_id))
    if not is_admin and not is_owner:
        raise AppError("FORBIDDEN", "仅任务登记人、负责人或管理员可以推进任务", 403)
    if to in {"暂停", "中止", "关闭"} and not is_admin:
        raise AppError("FORBIDDEN", "暂停、中止、关闭委派任务需要管理员操作", 403)
    allowed = {
        "登记": {"排期", "中止"}, "排期": {"执行", "中止"}, "执行": {"暂停", "关闭", "中止"},
        "暂停": {"执行", "中止"}, "关闭": set(), "中止": set(),
    }
    if to not in allowed.get(task.status, set()):
        raise AppError("INVALID_TRANSITION", f"不允许从「{task.status}」流转到「{to}」")
    if to in {"暂停", "中止"} and len(reason.strip()) < 2:
        raise AppError("REASON_REQUIRED", "暂停或中止必须填写原因")
    old = task.status
    if to == "暂停":
        task.pause_reason = reason.strip()
    elif to == "中止":
        task.abort_reason = reason.strip()
    elif to == "关闭":
        task.completion_note = reason.strip() or task.completion_note
        task.closed_at = datetime.now()
    task.status = to
    if to == "关闭" and old != "关闭":
        publish(db, "work_task.closed", "work_task", task.id, {"task_code": task.task_code})
    audit(db, "work_task", task.id, "transition", actor, {"from": old, "to": to, "reason": reason})
    return task


def delete_work_task(db: Session, task: WorkTask, actor: AuthUser):
    is_admin = _is_admin(db, actor)
    registrar_can_delete = bool(
        actor.person_id and task.registrar == actor.person_id and task.assignee is None and task.status == "登记"
    )
    # 记录级规则允许登记人删除自己的未分配草稿，不要求其拥有全局 delete
    # 功能开关；已分配任务仍必须具备管理员隐式全权或显式删除权限。
    if not is_admin and not registrar_can_delete:
        _require_module(db, actor, "task_delegated", "delete")
        raise AppError("FORBIDDEN", "任务分配后仅管理员可以删除，登记未分配任务仅登记人可以删除", 403)
    task.is_deleted = True
    audit(db, "work_task", task.id, "delete", actor, {"code": task.task_code})
