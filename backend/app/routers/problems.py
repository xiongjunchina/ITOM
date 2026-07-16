"""问题管理（PRD §5.2）：手工创建 / 工单升级转入 / (M5)需求遗留转入。"""
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_not_example
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.events.bus import publish
from app.models import AuthUser, OrgMember, Problem, ProblemTicket, ServiceItem, Ticket
from app.schemas.common import ok, paginate
from app.services import process_engine
from app.services.audit import audit
from app.services.codes import gen_code
from app.services.workflow import allowed_targets, restrict_terminal_targets, require_terminal_transition_admin, status_names
from app.services.workflow import transition as wf_transition

router = APIRouter(tags=["itsm"])


class ProblemCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=1)
    priority: str = "P3"
    service_item_id: str | None = None
    owner: str | None = None
    assigned_line: str | None = None  # M29 专业线：product/ops/dev（页面必选；工单升级默认 ops）


#: 专业线 → 负责人角色（M29）：问题确认与解决确认由对应专业线负责人执行
LINE_LEADER_ROLE = {"product": "it_pdm_leader", "ops": "it_op_leader", "dev": "it_dev_leader"}


def _line_leader_person(db: Session, line: str | None) -> str | None:
    """解析专业线负责人在岗人员（取第一个持有该角色的用户）。"""
    role = LINE_LEADER_ROLE.get(line or "")
    if not role:
        return None
    persons = process_engine._resolve_key_persons(db, role)
    return persons[0] if persons else None


class ProblemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    service_item_id: str | None = None
    owner: str | None = None
    workaround: str | None = None
    root_cause: str | None = None


class TransitionIn(BaseModel):
    to: str
    fields: dict = {}


class LinkTicketIn(BaseModel):
    ticket_id: str


def _row(p: Problem, db: Session, names: dict) -> dict:
    owner = db.get(OrgMember, p.owner) if p.owner else None
    item = db.get(ServiceItem, p.service_item_id) if p.service_item_id else None
    ticket_count = (
        db.query(ProblemTicket).filter(ProblemTicket.problem_id == p.id, ProblemTicket.is_deleted.is_(False)).count()
    )
    return {
        "id": p.id, "problem_code": p.problem_code, "title": p.title,
        "priority": p.priority, "status": p.status, "is_example": p.is_example, "status_name": names.get(p.status, p.status),
        "service_item_id": p.service_item_id, "service_item_name": item.name if item else None,
        "owner": p.owner, "owner_name": owner.name if owner else None,
        "linked_ticket_count": ticket_count,
        "created_at": p.created_at,
    }


def _create_problem(db: Session, data: dict, actor: AuthUser, source_ticket: Ticket | None = None) -> Problem:
    if not data.get("assigned_line"):
        data["assigned_line"] = "ops"  # 工单升级等未选专业线时默认运维线
    if data["assigned_line"] not in LINE_LEADER_ROLE:
        raise AppError("INVALID_LINE", "所属专业线须为 产品线/运维线/开发线")
    problem = Problem(
        **data,
        reporter=actor.id,
        problem_code=gen_code(db, Problem, "problem_code", "PB"),
        source_ticket_id=source_ticket.id if source_ticket else None,
    )
    db.add(problem)
    db.flush()
    if source_ticket:
        db.add(ProblemTicket(problem_id=problem.id, ticket_id=source_ticket.id))
        source_ticket.problem_id = problem.id
    # M29：第 1 步「问题确认」指派对应专业线负责人（产品/运维/开发），而非登记时填的负责人
    process_engine.start_instance(db, "problem", problem.id, {},
                                  preferred_assignee=_line_leader_person(db, problem.assigned_line))
    audit(db, "problem", problem.id, "create", actor, {"code": problem.problem_code, "from_ticket": source_ticket.ticket_code if source_ticket else None})
    publish(db, "problem.created", "problem", problem.id, {})
    return problem


@router.get("/api/problems")
def list_problems(
    page: int = 1, page_size: int = 20, q: str = "", status: str = "", priority: str = "",
    db: Session = Depends(get_db), _: AuthUser = Depends(require_perm("problems", "view")),
):
    query = db.query(Problem).filter(Problem.is_deleted.is_(False))
    if q:
        query = query.filter(or_(Problem.title.ilike(f"%{q}%"), Problem.problem_code.ilike(f"%{q}%")))
    if status:
        query = query.filter(Problem.status == status)
    if priority:
        query = query.filter(Problem.priority == priority)
    items, total = paginate(query.order_by(Problem.is_example.desc(), Problem.created_at.desc()), page, page_size)
    names = status_names(db, "problem")
    return ok([_row(p, db, names) for p in items], total=total, page=page)


@router.post("/api/problems")
def create_problem(body: ProblemCreate, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("problems", "create"))):
    problem = _create_problem(db, body.model_dump(), user)
    db.commit()
    return ok(_row(problem, db, status_names(db, "problem")))


@router.get("/api/problems/{problem_id}")
def get_problem(problem_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("problems", "view"))):
    p = db.get(Problem, problem_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "问题不存在", 404)
    names = status_names(db, "problem")
    detail = _row(p, db, names)
    links = db.query(ProblemTicket).filter(ProblemTicket.problem_id == p.id, ProblemTicket.is_deleted.is_(False)).all()
    tickets = db.query(Ticket).filter(Ticket.id.in_([l.ticket_id for l in links] or ["-"])).all()
    cur_task = process_engine.current_pending_task(db, "problem", p.id)
    cur_seq = cur_task.step.seq if cur_task and cur_task.step else None
    detail.update(
        {
            "description": p.description,
            "root_cause": p.root_cause,
            "workaround": p.workaround,
            "assigned_line": p.assigned_line,
            "reporter": p.reporter,
            # M29：第 1 步「问题确认」当前处理人 → 前端显示 确认属实/驳回 双按钮
            "can_confirm": bool(cur_task and cur_seq == 1 and not p.is_example
                                and process_engine.can_act_on_task(db, user, cur_task)),
            "source_ticket_id": p.source_ticket_id,
            "source_requirement_id": p.source_requirement_id,
            "linked_tickets": [
                {"id": t.id, "ticket_code": t.ticket_code, "title": t.title, "status": t.status}
                for t in tickets
            ],
            # M25：普通流转按钮只给当前节点处理人；审批类（显式授权）保留
            "allowed_transitions": [] if p.is_example else [
                {"to": code, "to_name": names.get(code, code)}
                for code in restrict_terminal_targets(
                    db, "problem", p.status,
                    process_engine.filter_targets_by_flow(
                        db, user, "problem", p.id, p.status, allowed_targets(db, "problem", p.status, user)),
                    allow_terminal=_is_admin(db, user))
            ],
            "process": process_engine.instance_view(db, "problem", p.id),
        }
    )
    return ok(detail)


@router.patch("/api/problems/{problem_id}")
def update_problem(problem_id: str, body: ProblemUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("problems", "edit"))):
    p = db.get(Problem, problem_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "问题不存在", 404)
    ensure_not_example(p)
    data = body.model_dump(exclude_unset=True)
    root_cause_filled = data.get("root_cause") and not p.root_cause
    for k, v in data.items():
        setattr(p, k, v)
    if root_cause_filled:
        publish(db, "problem.root_cause_found", "problem", p.id, {})
    audit(db, "problem", p.id, "update", user, {"fields": list(data.keys())})
    db.commit()
    return ok({"id": p.id})


@router.delete("/api/problems/{problem_id}")
def delete_problem(problem_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("problems", "delete"))):
    """删除问题（M21，软删）：级联软删流程实例与任务；来源工单解除关联。"""
    p = db.get(Problem, problem_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "问题不存在", 404)
    ensure_not_example(p)
    from app.models import ProcessInstance, ProcessTask, Ticket

    p.is_deleted = True
    unlinked = 0
    for t in db.query(Ticket).filter(Ticket.problem_id == p.id, Ticket.is_deleted.is_(False)):
        t.problem_id = None
        unlinked += 1
    for inst in db.query(ProcessInstance).filter(
        ProcessInstance.entity_type == "problem",
        ProcessInstance.entity_id == p.id,
        ProcessInstance.is_deleted.is_(False),
    ):
        inst.is_deleted = True
        for task in db.query(ProcessTask).filter(ProcessTask.instance_id == inst.id, ProcessTask.is_deleted.is_(False)):
            task.is_deleted = True
    audit(db, "problem", p.id, "delete", actor, {"code": p.problem_code, "tickets_unlinked": unlinked})
    db.commit()
    return ok({"id": p.id, "tickets_unlinked": unlinked})


class ConfirmIn(BaseModel):
    handler_id: str = Field(min_length=1, description="根因分析处理人 person id")


class RejectConfirmIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/api/problems/{problem_id}/confirm")
def confirm_problem(problem_id: str, body: ConfirmIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("problems", "view"))):
    """M29：专业线负责人确认问题属实 → 指定处理人进入根因分析；问题状态 → 分析中。"""
    p = db.get(Problem, problem_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "问题不存在", 404)
    ensure_not_example(p)
    task = process_engine.current_pending_task(db, "problem", p.id)
    if not task or not task.step or task.step.seq != 1:
        raise AppError("NOT_CONFIRM_STEP", "当前不在「问题确认」节点")
    if not process_engine.can_act_on_task(db, user, task):
        raise AppError("FORBIDDEN", "仅该节点处理人（专业线负责人）可确认", 403)
    handler = db.get(OrgMember, body.handler_id)
    if not handler or handler.is_deleted:
        raise AppError("NOT_FOUND", "处理人不存在", 404)
    process_engine.complete_task(db, task.id, user, "确认问题属实，转根因分析")
    nxt = process_engine.current_pending_task(db, "problem", p.id)
    if nxt:
        process_engine.reassign_task(db, nxt.id, body.handler_id)  # 指派处理人（自动通知）
    if p.status == "new":
        wf_transition(db, p, "problem", "analyzing", {}, user, system=True)
    audit(db, "problem", p.id, "confirm", user, {"code": p.problem_code, "handler": handler.name})
    db.commit()
    return ok({"id": p.id, "status": p.status})


@router.post("/api/problems/{problem_id}/reject-confirm")
def reject_confirm_problem(problem_id: str, body: RejectConfirmIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("problems", "view"))):
    """M29：确认阶段驳回——问题不属实，退回提单人（理由必填、审计留痕、通知提单人）。"""
    p = db.get(Problem, problem_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "问题不存在", 404)
    ensure_not_example(p)
    task = process_engine.current_pending_task(db, "problem", p.id)
    if not task or not task.step or task.step.seq != 1:
        raise AppError("NOT_CONFIRM_STEP", "当前不在「问题确认」节点")
    if not process_engine.can_act_on_task(db, user, task):
        raise AppError("FORBIDDEN", "仅该节点处理人（专业线负责人）可驳回", 403)
    reporter_person = None
    if p.reporter:
        ru = db.get(AuthUser, p.reporter)
        reporter_person = ru.person_id if ru else None
    task.comment = f"[驳回] {body.reason}"
    process_engine.reassign_task(db, task.id, reporter_person) if reporter_person else None
    audit(db, "problem", p.id, "reject_confirm", user, {"code": p.problem_code, "reason": body.reason})
    if reporter_person:
        from app.events import notifier

        notifier.notify(db, "problem.rejected", "problem", p.id, [reporter_person],
                        f"问题被驳回：{p.problem_code} {p.title}",
                        f"驳回理由：{body.reason}。请补充说明后在流程节点改派回专业线负责人重新确认。",
                        link=f"/itsm/problems/{p.id}")
    db.commit()
    return ok({"id": p.id, "rejected_to": reporter_person})


def on_problem_advanced(db: Session, problem_id: str, actor: AuthUser):
    """M29 问题流程编排：步骤 3 延续步骤 2 处理人；步骤 4 指派专业线负责人并同步状态 resolved；
    流程完成 → 自动闭环（M24）。"""
    from app.services.workflow import closure_path

    p = db.get(Problem, problem_id)
    if not p or p.is_deleted:
        return
    task = process_engine.current_pending_task(db, "problem", p.id)
    if not task:  # 无待处理任务：流程可能已完成
        auto_close_problem_on_process_complete(db, p.id, actor)
        return
    seq = task.step.seq if task.step else None
    if seq == 3 and not task.assignee:
        # 解决与验证：延续根因分析处理人
        from app.models import ProcessTask

        prev = (
            db.query(ProcessTask)
            .join(ProcessTask.step)
            .filter(ProcessTask.instance_id == task.instance_id, ProcessTask.status == "已完成",
                    ProcessTask.is_deleted.is_(False))
            .all()
        )
        prev = next((t for t in prev if t.step and t.step.seq == 2), None)
        if prev and prev.assignee:
            process_engine.reassign_task(db, task.id, prev.assignee)
    elif seq == 4:
        if not task.assignee:
            leader = _line_leader_person(db, p.assigned_line)
            if leader:
                process_engine.reassign_task(db, task.id, leader)
        if p.status not in ("resolved", "closed"):
            if not p.root_cause:
                # 根因兜底：取「根因分析」步骤的处理说明（阶段校验 resolved 必填 root_cause）
                from app.models import ProcessTask

                done = (
                    db.query(ProcessTask)
                    .filter(ProcessTask.instance_id == task.instance_id, ProcessTask.status == "已完成",
                            ProcessTask.is_deleted.is_(False))
                    .all()
                )
                rc = next((t.comment for t in done if t.step and t.step.seq == 2 and t.comment), None)
                p.root_cause = rc or "详见流程处理记录（根因分析步骤）"
            path = closure_path(db, "problem", p.status, actor, dst="resolved", ignore_roles=True)
            for to in path or []:
                wf_transition(db, p, "problem", to, {}, actor, system=True)


@router.post("/api/problems/{problem_id}/transition")
def transition_problem(problem_id: str, body: TransitionIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("problems", "edit"))):
    p = db.get(Problem, problem_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "问题不存在", 404)
    ensure_not_example(p)
    require_terminal_transition_admin(db, user, "problem", p.status, body.to)  # M28：强关仅 admin
    process_engine.require_flow_operator_for_transition(db, user, "problem", p.id, p.status, body.to)  # M25
    had_root_cause = bool(p.root_cause)
    wf_transition(db, p, "problem", body.to, body.fields, user)
    if not had_root_cause and p.root_cause:
        publish(db, "problem.root_cause_found", "problem", p.id, {})
    if body.to == "closed":
        publish(db, "problem.closed", "problem", p.id, {})
        process_engine.finalize_instance(db, "problem", p.id, "问题已关闭，流程随单收尾")  # M24
    db.commit()
    return ok({"id": p.id, "status": p.status})


def _is_admin(db: Session, user: AuthUser) -> bool:
    from app.core.rbac import ADMIN
    from app.services.rbac import actor_keys

    return ADMIN in actor_keys(db, user)


def auto_close_problem_on_process_complete(db: Session, problem_id: str, actor: AuthUser) -> bool:
    """问题流程走完（关闭复盘完成）→ 问题沿状态机自动闭环（M24，与工单 M23 同规则）。"""
    from app.services.workflow import closure_path

    p = db.get(Problem, problem_id)
    if not p or p.is_deleted or p.status == "closed":
        return False
    path = closure_path(db, "problem", p.status, actor, ignore_roles=True)
    if not path:
        audit(db, "problem", p.id, "auto_close_blocked", actor, {"status": p.status})
        return False
    if not p.root_cause:
        p.root_cause = "流程执行完毕，系统自动闭环（详见流程处理记录）"
    for to in path:
        wf_transition(db, p, "problem", to, {}, actor, system=True)
    publish(db, "problem.closed", "problem", p.id, {})
    audit(db, "problem", p.id, "auto_close", actor, {"code": p.problem_code, "path": path})
    db.commit()
    return True


@router.post("/api/problems/{problem_id}/link-ticket")
def link_ticket(problem_id: str, body: LinkTicketIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("problems", "edit"))):
    p = db.get(Problem, problem_id)
    t = db.get(Ticket, body.ticket_id)
    if not p or p.is_deleted or not t or t.is_deleted:
        raise AppError("NOT_FOUND", "问题或工单不存在", 404)
    ensure_not_example(p)
    ensure_not_example(t)
    exists = (
        db.query(ProblemTicket)
        .filter(ProblemTicket.problem_id == p.id, ProblemTicket.ticket_id == t.id, ProblemTicket.is_deleted.is_(False))
        .first()
    )
    if exists:
        raise AppError("DUPLICATE", "该工单已关联")
    db.add(ProblemTicket(problem_id=p.id, ticket_id=t.id))
    t.problem_id = p.id
    audit(db, "problem", p.id, "link_ticket", user, {"ticket": t.ticket_code})
    db.commit()
    return ok({"id": p.id})
