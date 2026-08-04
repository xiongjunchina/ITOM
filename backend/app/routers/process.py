"""流程任务操作 + 流程定义自配置管理（admin）。"""
import re
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import AuthUser, ProcessDefinition, ProcessInstance, ProcessStep, ProcessTask
from app.schemas.common import ok
from app.services import process_engine
from app.services.audit import audit

router = APIRouter(tags=["process"])


PROCESS_DISPLAY_ORDER = {
    "service_request": 10,
    "change": 20,
    "ticket_change": 20,
    "incident": 30,
    "problem": 40,
    "project": 50,
    "requirement": 60,
    "bug": 70,
}


def _definition_display_order(definition: ProcessDefinition) -> tuple[int, int, str]:
    entity_key = definition.entity_type
    if definition.entity_type == "ticket":
        ticket_type = (definition.trigger_condition or {}).get("ticket_type")
        entity_key = {
            "service_request": "service_request",
            "change": "ticket_change",
            "incident": "incident",
            "problem": "problem",
        }.get(ticket_type, "service_request")
    return (PROCESS_DISPLAY_ORDER.get(entity_key, 999), -definition.version, definition.code)


class CompleteIn(BaseModel):
    comment: str = ""
    # 仅服务请求的首个受理节点可使用；由服务端复核流程位置、当前处理人和 IT 团队范围。
    implementation_mode: Literal["auto", "self", "member"] | None = None
    implementation_assignee: str | None = None


class RejectIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class ReassignIn(BaseModel):
    assignee: str


class StepIn(BaseModel):
    seq: int
    step_code: str | None = Field(default=None, min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_:-]+$")
    name: str = Field(min_length=1, max_length=128)
    node_type: Literal["processing", "approval"] = "processing"
    default_role: str | None = None
    cc_roles: list[str] = []
    autonomy_level: str = "L4"
    sla_hours: float | None = None
    description: str | None = None


class DefinitionCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_@]+$")
    name: str = Field(min_length=1, max_length=128)
    entity_type: str
    trigger_condition: dict | None = None
    description: str | None = None
    steps: list[StepIn] = Field(min_length=1)


class DefinitionUpdate(BaseModel):
    name: str | None = None
    active: bool | None = None
    trigger_condition: dict | None = None
    description: str | None = None
    steps: list[StepIn] | None = None


def _require_task_operator(
    db: Session,
    user: AuthUser,
    task_id: str,
    *,
    mark_view: bool = True,
    handling_action: bool = False,
) -> tuple[ProcessTask, bool]:
    """流程任务操作权限（M18/M25）：admin、任务处理人本人；未指派任务由步骤默认角色持有者认领。

    用户实测漏洞：业务用户能完成/改派指派给 IT 运维的「受理确认」任务。
    提交人在「用户确认关闭」类步骤（任务指派其本人）天然放行。
    """
    # Viewing and acting are both processing facts.  The engine locks the task
    # row so an upstream correction cannot race a first handler action.
    if mark_view:
        return process_engine.mark_task_viewed(db, user, task_id, handling_action=handling_action)

    # 管理员在节点尚未被实际处理人查阅时改派，不等同于下一节点已经查阅；
    # 因而只做同一套任务授权校验，不能写入 viewed_at/viewed_by。
    task = (
        db.query(ProcessTask)
        .filter(ProcessTask.id == task_id, ProcessTask.is_deleted.is_(False))
        .with_for_update()
        .first()
    )
    if not task:
        raise AppError("NOT_FOUND", "流程任务不存在", 404)
    if not process_engine.can_act_on_task(db, user, task):
        raise AppError("FORBIDDEN", "仅当前流程节点处理人或管理员可以操作", 403)
    return task, False


@router.post("/api/process-tasks/{task_id}/view")
def view_task(task_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    """Current handler explicitly records the first task-detail view."""
    task, newly_viewed = _require_task_operator(db, user, task_id, handling_action=False)
    if newly_viewed:
        audit(db, "process_task", task_id, "view", user, {"step_code": task.step_code_snapshot})
    db.commit()
    return ok({"id": task.id, "viewed_at": task.viewed_at, "viewed_by": task.viewed_by, "newly_viewed": newly_viewed})


def _requester_confirmation_ticket(db: Session, user: AuthUser, task_id: str):
    """识别服务请求最终用户确认节点，并禁止管理员代替提交人确认。"""
    from app.models import Ticket

    task = db.get(ProcessTask, task_id)
    if not task or not task.step or task.step.default_role != "requester":
        return None
    instance = db.get(ProcessInstance, task.instance_id)
    if not instance or instance.entity_type != "ticket":
        return None
    ticket = db.get(Ticket, instance.entity_id)
    if not ticket or ticket.ticket_type != "service_request":
        return None
    if ticket.submitter != user.id:
        raise AppError("FORBIDDEN", "只有服务请求提交人可以确认解决结果", 403)
    return ticket


def _after_task_advanced(db: Session, instance: ProcessInstance, user: AuthUser) -> None:
    """完成/审批同意共用的实体编排回调。"""
    if instance.entity_type == "requirement":
        from app.routers.requirements import on_process_advanced

        on_process_advanced(db, instance.entity_id, user)
    elif instance.entity_type in ("ticket", "ticket_change"):
        from app.services.tickets import on_ticket_advanced

        on_ticket_advanced(db, instance.entity_id, user)
    elif instance.entity_type == "problem":
        from app.routers.problems import on_problem_advanced

        on_problem_advanced(db, instance.entity_id, user)
    elif instance.entity_type == "project" and instance.status == "completed":
        from app.models import Project

        p = db.get(Project, instance.entity_id)
        if p and not p.is_deleted and p.status not in ("closed", "cancelled") and p.pm:
            from app.events import notifier

            notifier.notify(
                db, "project.process_completed", "project", p.id, [p.pm],
                f"项目流程已走完：{p.project_code} {p.name}",
                content="关键节点流程已全部完成，请确认项目是否收尾关闭（关闭需填写理由）。",
                link=f"/projects/{p.id}",
            )


@router.post("/api/process-tasks/{task_id}/complete")
def complete(task_id: str, body: CompleteIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    task, _ = _require_task_operator(db, user, task_id, handling_action=True)
    _requester_confirmation_ticket(db, user, task_id)
    from app.services.tickets import prepare_implementation_handoff

    handoff = prepare_implementation_handoff(
        db,
        task,
        user,
        mode=body.implementation_mode,
        implementation_assignee=body.implementation_assignee,
    )
    # 审批节点的流程图入口与右上角“同意”语义完全一致：
    # 变更审批等状态机联动必须走 approve_task，不能只把任务标成已完成。
    instance = (
        process_engine.approve_task(
            db,
            task_id,
            user,
            body.comment,
            next_preferred_assignee=handoff.assignee_id if handoff else None,
            force_next_unassigned=handoff.force_unassigned if handoff else False,
        )
        if task and task.step and task.step.node_type == "approval"
        else process_engine.complete_task(
            db,
            task_id,
            user,
            body.comment,
            next_preferred_assignee=handoff.assignee_id if handoff else None,
            force_next_unassigned=handoff.force_unassigned if handoff else False,
        )
    )
    audit_data = {"comment": body.comment}
    if handoff:
        audit_data["implementation_assignment"] = {
            "source": handoff.source,
            "assignee": handoff.assignee_id,
            "rule_id": handoff.rule_id,
            "manual_queue": handoff.force_unassigned,
        }
    audit(db, "process_task", task_id, "complete", user, audit_data)
    _after_task_advanced(db, instance, user)
    db.commit()
    return ok({"instance_id": instance.id, "status": instance.status, "current_step_seq": instance.current_step_seq})


@router.post("/api/process-tasks/{task_id}/approve")
def approve(task_id: str, body: CompleteIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    """审批节点右上角「同意」按钮；审批理由可选。"""
    task, _ = _require_task_operator(db, user, task_id, handling_action=True)
    _requester_confirmation_ticket(db, user, task_id)
    from app.services.tickets import prepare_implementation_handoff

    handoff = prepare_implementation_handoff(
        db,
        task,
        user,
        mode=body.implementation_mode,
        implementation_assignee=body.implementation_assignee,
    )
    instance = process_engine.approve_task(
        db,
        task_id,
        user,
        body.comment,
        next_preferred_assignee=handoff.assignee_id if handoff else None,
        force_next_unassigned=handoff.force_unassigned if handoff else False,
    )
    audit_data = {"comment": body.comment}
    if handoff:
        audit_data["implementation_assignment"] = {
            "source": handoff.source,
            "assignee": handoff.assignee_id,
            "rule_id": handoff.rule_id,
            "manual_queue": handoff.force_unassigned,
        }
    audit(db, "process_task", task_id, "approve", user, audit_data)
    _after_task_advanced(db, instance, user)
    db.commit()
    return ok({"instance_id": instance.id, "status": instance.status, "current_step_seq": instance.current_step_seq})


@router.post("/api/process-tasks/{task_id}/reject")
def reject(task_id: str, body: RejectIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    """审批节点右上角「驳回」按钮；驳回理由必填并保留在流程任务记录。"""
    _require_task_operator(db, user, task_id, handling_action=True)
    requester_ticket = _requester_confirmation_ticket(db, user, task_id)
    if requester_ticket:
        from app.services import service_request_closure

        task = db.get(ProcessTask, task_id)
        result = service_request_closure.reopen_from_confirmation(
            db,
            user,
            requester_ticket,
            task,
            body.reason,
            source="web",
        )
        db.commit()
        return ok(result)
    instance = process_engine.reject_task(db, task_id, user, body.reason)
    audit(db, "process_task", task_id, "reject", user, {"reason": body.reason})
    db.commit()
    return ok({"instance_id": instance.id, "status": instance.status, "current_step_seq": instance.current_step_seq})


@router.post("/api/process-tasks/{task_id}/reassign")
def reassign(task_id: str, body: ReassignIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    # 仅管理员的路由调整不应伪造为“下游已查阅”；当前处理人自行改派仍视为已处理。
    _require_task_operator(
        db,
        user,
        task_id,
        mark_view=not _is_process_admin(db, user),
        handling_action=True,
    )
    task = process_engine.reassign_task(db, task_id, body.assignee)
    audit(db, "process_task", task_id, "reassign", user, {"assignee": body.assignee})
    db.commit()
    return ok({"id": task.id, "assignee": task.assignee})


def _is_process_admin(db: Session, user: AuthUser) -> bool:
    from app.core.rbac import ADMIN
    from app.services.rbac import actor_keys

    return ADMIN in actor_keys(db, user)


def _def_row(d: ProcessDefinition, db: Session) -> dict:
    instance_count = (
        db.query(ProcessInstance)
        .filter(ProcessInstance.definition_id == d.id, ProcessInstance.is_deleted.is_(False))
        .count()
    )
    return {
        "id": d.id, "code": d.code, "name": d.name, "entity_type": d.entity_type,
        "trigger_condition": d.trigger_condition, "version": d.version,
        "active": d.active, "description": d.description,
        "instance_count": instance_count,
        "steps_locked": instance_count > 0,
        "steps": [
            {"seq": s.seq, "step_code": s.step_code or f"step_{s.seq}", "name": s.name, "node_type": s.node_type or "processing", "default_role": s.default_role, "cc_roles": s.cc_roles or [],
             "autonomy_level": s.autonomy_level, "sla_hours": s.sla_hours, "description": s.description}
            for s in d.steps if not s.is_deleted
        ],
    }


def _validate_steps(db: Session, steps: list[StepIn]):
    from app.models import UserGroup
    from app.services.rbac import GROUP_PREFIX, valid_role_codes

    seqs = [s.seq for s in steps]
    if sorted(seqs) != list(range(1, len(steps) + 1)):
        raise AppError("INVALID_STEPS", "步骤序号必须从 1 连续递增")
    codes = [s.step_code or f"step_{s.seq}" for s in steps]
    if len(set(codes)) != len(codes):
        raise AppError("INVALID_STEPS", "步骤编码必须唯一")
    for step, code in zip(steps, codes):
        step.step_code = code
    valid_keys = valid_role_codes(db)
    valid_keys |= {
        f"{GROUP_PREFIX}{code}"
        for (code,) in db.query(UserGroup.code).filter(UserGroup.is_deleted.is_(False))
    }
    for s in steps:
        if s.autonomy_level not in ("L1", "L2", "L3", "L4"):
            raise AppError("INVALID_STEPS", f"步骤「{s.name}」自治级别必须为 L1-L4")
        for key in s.cc_roles:
            if key not in valid_keys:
                raise AppError("INVALID_STEPS", f"步骤「{s.name}」知会人 {key} 不是有效的角色或用户组")


def _check_trigger_conflict(db: Session, entity_type: str, trigger: dict | None, exclude_id: str | None = None):
    """同一单据类型下，激活的流程定义触发条件必须唯一，否则匹配歧义。"""
    query = db.query(ProcessDefinition).filter(
        ProcessDefinition.entity_type == entity_type,
        ProcessDefinition.active.is_(True),
        ProcessDefinition.is_deleted.is_(False),
    )
    if exclude_id:
        query = query.filter(ProcessDefinition.id != exclude_id)
    for d in query.all():
        if (d.trigger_condition or {}) == (trigger or {}):
            raise AppError("TRIGGER_CONFLICT", f"与激活流程「{d.name}」的触发条件相同，请先停用它或修改触发条件")


@router.get("/api/admin/process-definitions")
def list_definitions(db: Session = Depends(get_db), _=Depends(require_perm("process_definitions", "view"))):
    rows = db.query(ProcessDefinition).filter(ProcessDefinition.is_deleted.is_(False)).all()
    rows.sort(key=_definition_display_order)
    return ok([_def_row(d, db) for d in rows], total=len(rows))


@router.post("/api/admin/process-definitions")
def create_definition(body: DefinitionCreate, db: Session = Depends(get_db), actor=Depends(require_perm("process_definitions", "create"))):
    if db.query(ProcessDefinition).filter(ProcessDefinition.code == body.code, ProcessDefinition.is_deleted.is_(False)).first():
        raise AppError("DUPLICATE", "流程代码已存在")
    _validate_steps(db, body.steps)
    _check_trigger_conflict(db, body.entity_type, body.trigger_condition)
    definition = ProcessDefinition(
        code=body.code, name=body.name, entity_type=body.entity_type,
        trigger_condition=body.trigger_condition, description=body.description,
    )
    db.add(definition)
    db.flush()
    for s in body.steps:
        db.add(ProcessStep(definition_id=definition.id, **s.model_dump()))
    audit(db, "process_definition", definition.id, "create", actor, {"code": body.code, "steps": len(body.steps)})
    db.commit()
    return ok(_def_row(definition, db))


@router.patch("/api/admin/process-definitions/{def_id}")
def update_definition(def_id: str, body: DefinitionUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("process_definitions", "edit"))):
    definition = db.get(ProcessDefinition, def_id)
    if not definition or definition.is_deleted:
        raise AppError("NOT_FOUND", "流程定义不存在", 404)
    data = body.model_dump(exclude_unset=True)
    steps = data.pop("steps", None)
    if steps is not None:
        instance_count = (
            db.query(ProcessInstance)
            .filter(ProcessInstance.definition_id == definition.id, ProcessInstance.is_deleted.is_(False))
            .count()
        )
        step_models = [StepIn(**s) for s in steps]
        _validate_steps(db, step_models)
        live = (
            db.query(ProcessStep)
            .filter(ProcessStep.definition_id == definition.id, ProcessStep.is_deleted.is_(False))
            .count()
        )
        # 有运行实例时锁结构和责任映射：历史任务必须沿用生成时的节点/RACI；
        # 仅允许改展示名称、说明等非取数字段。需要改节点、处理人或知会关系时另存新版本。
        if instance_count > 0 and len(step_models) != live:
            raise AppError(
                "STEPS_LOCKED",
                f"该流程已有 {instance_count} 个实例，不可增删步骤（当前 {live} 步）；节点/RACI 调整请「另存新版本」",
            )
        # 就地 upsert（M14.2）：保留步骤行 id 不物理删——历史任务(含已删项目的软删任务)
        # 外键引用步骤行，物理删除会撞 ForeignKeyViolation；改名/调参直接更新，
        # 步骤数减少时多余行软删（_def_row/new_version/引擎均过滤软删）。
        existing = (
            db.query(ProcessStep)
            .filter(ProcessStep.definition_id == definition.id, ProcessStep.is_deleted.is_(False))
            .order_by(ProcessStep.seq)
            .all()
        )
        for i, sm in enumerate(step_models):
            if i < len(existing):
                if sm.step_code is None:
                    sm.step_code = existing[i].step_code or f"step_{sm.seq}"
                if instance_count > 0:
                    old = existing[i]
                    protected_before = (old.seq, old.step_code or f"step_{old.seq}", old.node_type or "processing", old.default_role,
                                        old.cc_roles or [], old.autonomy_level, old.sla_hours)
                    protected_after = (sm.seq, sm.step_code, sm.node_type or "processing", sm.default_role,
                                       sm.cc_roles or [], sm.autonomy_level, sm.sla_hours)
                    if protected_before != protected_after:
                        raise AppError(
                            "STEPS_LOCKED",
                            f"该流程已有 {instance_count} 个实例，步骤「{old.name}」的节点/RACI/SLA 已被历史任务引用，请「另存新版本」",
                        )
                for k, v in sm.model_dump().items():
                    setattr(existing[i], k, v)
            else:
                db.add(ProcessStep(definition_id=definition.id, **sm.model_dump()))
        for row in existing[len(step_models):]:
            row.is_deleted = True
    if data.get("active") is True or ("trigger_condition" in data and definition.active):
        _check_trigger_conflict(
            db, definition.entity_type, data.get("trigger_condition", definition.trigger_condition), exclude_id=definition.id
        )
    for k, v in data.items():
        setattr(definition, k, v)
    audit(db, "process_definition", definition.id, "update", actor, {"fields": list(data.keys()), "steps_replaced": steps is not None})
    db.commit()
    db.refresh(definition)
    return ok(_def_row(definition, db))


@router.delete("/api/admin/process-definitions/{def_id}")
def delete_definition(def_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("process_definitions", "delete"))):
    """删除流程定义（M15）：仅 已停用 且 从未产生实例 的版本可删（物理删，无引用）。

    有历史实例（含已删单据的软删实例）的版本保留可追溯；激活中的先停用再删，防误删。
    """
    definition = db.get(ProcessDefinition, def_id)
    if not definition or definition.is_deleted:
        raise AppError("NOT_FOUND", "流程定义不存在", 404)
    if definition.active:
        raise AppError("PROCESS_ACTIVE", "流程处于激活状态，请先停用再删除")
    used = db.query(ProcessInstance).filter(ProcessInstance.definition_id == definition.id).count()  # 含软删：用过即留痕
    if used > 0:
        raise AppError("PROCESS_IN_USE", f"该流程版本已产生 {used} 个实例（含历史单据），不可删除；如不再使用请保持停用")
    code, name = definition.code, definition.name
    db.query(ProcessStep).filter(ProcessStep.definition_id == definition.id).delete()
    db.delete(definition)
    audit(db, "process_definition", def_id, "delete", actor, {"code": code, "name": name})
    db.commit()
    return ok({"id": def_id})


@router.post("/api/admin/process-definitions/{def_id}/new-version")
def new_version(def_id: str, body: DefinitionUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("process_definitions", "edit"))):
    """复制为新版本并停用旧版：老单据沿用旧版步骤，新单据走新版。"""
    old = db.get(ProcessDefinition, def_id)
    if not old or old.is_deleted:
        raise AppError("NOT_FOUND", "流程定义不存在", 404)
    steps = body.steps if body.steps is not None else [
        StepIn(seq=s.seq, step_code=s.step_code or f"step_{s.seq}", name=s.name, node_type=s.node_type or "processing", default_role=s.default_role, cc_roles=s.cc_roles or [],
               autonomy_level=s.autonomy_level, sla_hours=s.sla_hours, description=s.description)
        for s in old.steps if not s.is_deleted
    ]
    _validate_steps(db, steps)
    new_trigger = body.trigger_condition if body.trigger_condition is not None else old.trigger_condition
    _check_trigger_conflict(db, old.entity_type, new_trigger, exclude_id=old.id)
    base_code = re.sub(r"@v\d+$", "", old.code)
    new_ver = old.version + 1
    definition = ProcessDefinition(
        code=f"{base_code}@v{new_ver}",
        name=body.name or old.name,
        entity_type=old.entity_type,
        trigger_condition=body.trigger_condition if body.trigger_condition is not None else old.trigger_condition,
        description=body.description if body.description is not None else old.description,
        version=new_ver,
        active=True,
    )
    db.add(definition)
    db.flush()
    for s in steps:
        db.add(ProcessStep(definition_id=definition.id, **s.model_dump()))
    old.active = False
    audit(db, "process_definition", definition.id, "new_version", actor, {"from": old.code, "to": definition.code})
    db.commit()
    return ok(_def_row(definition, db))


@router.get("/api/process-instances")
def list_instances(
    status: str = "", entity_type: str = "", page: int = 1, page_size: int = 20,
    db: Session = Depends(get_db), _=Depends(require_perm("process_monitor", "view")),
):
    """流程监控：实例列表 + 当前卡点步骤 + 超时任务。"""
    from datetime import datetime

    from app.models import OrgMember, ProcessTask
    from app.schemas.common import paginate

    query = (
        db.query(ProcessInstance)
        .filter(ProcessInstance.is_deleted.is_(False))
    )
    if status:
        query = query.filter(ProcessInstance.status == status)
    if entity_type:
        query = query.filter(ProcessInstance.entity_type == entity_type)
    items, total = paginate(query.order_by(ProcessInstance.created_at.desc()), page, page_size)
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    now = datetime.now()
    rows = []
    for ins in items:
        pending = next((t for t in ins.tasks if t.status == "待处理" and not t.is_deleted), None)
        rows.append({
            "id": ins.id, "definition_name": ins.definition.name, "entity_type": ins.entity_type,
            "entity_id": ins.entity_id, "status": ins.status,
            "current_step": pending.step.name if pending else None,
            "current_assignee": names.get(pending.assignee) if pending and pending.assignee else None,
            "current_due_at": pending.due_at if pending else None,
            "overdue": bool(pending and pending.due_at and pending.due_at < now),
            "started_at": ins.started_at, "completed_at": ins.completed_at,
        })
    return ok(rows, total=total, page=page)
