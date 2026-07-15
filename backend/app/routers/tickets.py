"""工单路由（PRD §5.1）。"""
from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_not_example
from app.core.rbac import REQUESTER
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import AuthUser, OrgMember, Ticket
from app.schemas.common import ok, paginate
from app.schemas.itsm import SatisfactionIn, TicketCloseIn, TicketCreate, TicketUpdate, TransitionIn
from app.services import process_engine
from app.services import tickets as svc
from app.services.audit import audit
from app.services.workflow import allowed_targets, status_names

router = APIRouter(prefix="/api/tickets", tags=["itsm"])


def _ticket_module(ticket_type: str) -> str:
    """M17.2：工单按类型独立授权（服务请求/事件/变更 三个权限模块）。"""
    from app.services.permissions import TICKET_TYPE_MODULE

    return TICKET_TYPE_MODULE.get(ticket_type, "ticket_sr")


def _require_type_perm(db: Session, user: AuthUser, ticket_type: str, action: str):
    from app.services.permissions import has_perm

    module = _ticket_module(ticket_type)
    if not has_perm(db, user, module, action):
        raise AppError("FORBIDDEN", "当前角色无此工单类型的操作权限", 403)


def _allowed_view_types(db: Session, user: AuthUser) -> list[str]:
    from app.services.permissions import TICKET_TYPE_MODULE, has_perm

    return [t for t, m in TICKET_TYPE_MODULE.items() if has_perm(db, user, m, "view")]


def _is_requester_only(db: Session, user: AuthUser) -> bool:
    from app.services.rbac import effective_roles

    roles = effective_roles(db, user)
    return roles == {REQUESTER}  # auditor 等其他角色可全局只读


def _row(t: Ticket, db: Session, names: dict) -> dict:
    assignee = db.get(OrgMember, t.assignee) if t.assignee else None
    return {
        "id": t.id, "ticket_code": t.ticket_code, "title": t.title,
        "ticket_type": t.ticket_type, "priority": t.priority,
        "status": t.status, "status_name": names.get(t.status, t.status),
        "service_item_id": t.service_item_id,
        "service_item_name": t.service_item.name if t.service_item else None,
        "service_line": t.service_line,
        "submitter_name": t.submitter_name, "submitter_dept": t.submitter_dept,
        "assignee": t.assignee, "assignee_name": assignee.name if assignee else None,
        "submitted_at": t.submitted_at,
        "sla_resolution_hours": t.sla_resolution_hours,
        "sla_response_met": t.sla_response_met, "sla_resolution_met": t.sla_resolution_met,
        "sla_warned": t.sla_warned, "satisfaction": t.satisfaction,
        "is_example": t.is_example,
    }


@router.get("")
def list_tickets(
    page: int = 1,
    page_size: int = 20,
    q: str = "",
    status: str = "",
    ticket_type: str = "",
    priority: str = "",
    assignee: str = "",
    scope: str = "",
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    allowed_types = _allowed_view_types(db, user)
    if not allowed_types:
        raise AppError("FORBIDDEN", "当前角色无任何工单类型的查看权限", 403)
    query = db.query(Ticket).filter(Ticket.is_deleted.is_(False), Ticket.ticket_type.in_(allowed_types))
    if _is_requester_only(db, user) or scope == "mine":
        query = query.filter(or_(Ticket.submitter == user.id, Ticket.assignee == (user.person_id or "-")))
    if q:
        query = query.filter(or_(Ticket.title.ilike(f"%{q}%"), Ticket.ticket_code.ilike(f"%{q}%")))
    if status:
        query = query.filter(Ticket.status == status)
    if ticket_type:
        query = query.filter(Ticket.ticket_type == ticket_type)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if assignee:
        query = query.filter(Ticket.assignee == assignee)
    items, total = paginate(query.order_by(Ticket.is_example.desc(), Ticket.submitted_at.desc()), page, page_size)
    names = {**status_names(db, "ticket"), **status_names(db, "ticket_change")}
    return ok([_row(t, db, names) for t in items], total=total, page=page)


@router.post("")
def create_ticket(body: TicketCreate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    _require_type_perm(db, user, body.ticket_type, "create")  # M17.2：按工单类型鉴权
    ticket = svc.create_ticket(db, body.model_dump(exclude_none=True), user)
    names = {**status_names(db, "ticket"), **status_names(db, "ticket_change")}
    return ok(_row(ticket, db, names))


def _get_ticket(db: Session, ticket_id: str, user: AuthUser) -> Ticket:
    t = db.get(Ticket, ticket_id)
    if not t or t.is_deleted:
        raise AppError("NOT_FOUND", "工单不存在", 404)
    if _is_requester_only(db, user) and t.submitter != user.id:
        raise AppError("FORBIDDEN", "无权查看他人工单", 403)
    if t.submitter != user.id:  # 提交人恒可见自己的单；他人单按类型模块鉴权
        from app.services.permissions import has_perm

        if not has_perm(db, user, _ticket_module(t.ticket_type), "view"):
            raise AppError("FORBIDDEN", "当前角色无此工单类型的查看权限", 403)
    return t


@router.get("/{ticket_id}")
def get_ticket(ticket_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    from app.services.permissions import has_perm

    t = _get_ticket(db, ticket_id, user)
    etype = svc.entity_type_of(t)
    names = status_names(db, etype)
    detail = _row(t, db, names)
    # M18：无该类型编辑权限（如业务用户看自己的单）不下发流转按钮，与 transition 接口守卫一致
    can_edit = has_perm(db, user, _ticket_module(t.ticket_type), "edit")
    # M25：流程驱动——普通流转按钮只给当前节点处理人（或 admin）；审批类（显式授权）保留
    _flow_ok, flow_assignee = process_engine.flow_operator_check(db, user, etype, t.id)
    detail.update(
        {
            "submitter": t.submitter,
            "description": t.description, "remarks": t.remarks, "ci_id": t.ci_id,
            "solution": t.solution, "root_cause": t.root_cause, "closure_code": t.closure_code,
            "change_type": t.change_type, "risk_level": t.risk_level,
            "change_reason": t.change_reason, "rollback_plan": t.rollback_plan,
            "planned_start_at": t.planned_start_at, "planned_end_at": t.planned_end_at,
            "implementation_plan": t.implementation_plan,
            "approved_at": t.approved_at, "approval_comment": t.approval_comment,
            "first_response_at": t.first_response_at, "resolved_at": t.resolved_at, "closed_at": t.closed_at,
            "paused_minutes": t.paused_minutes, "reopen_count": t.reopen_count,
            "first_time_fix": t.first_time_fix,
            "sla_response_min": t.sla_response_min,
            "actual_response_min": t.actual_response_min, "actual_resolution_hours": t.actual_resolution_hours,
            "allowed_transitions": [] if t.is_example or not can_edit else [
                {"to": code, "to_name": names.get(code, code)}
                for code in process_engine.filter_targets_by_flow(
                    db, user, etype, t.id, t.status, allowed_targets(db, etype, t.status, user))
            ],
            "can_edit": can_edit and not t.is_example,
            "flow_operator_name": flow_assignee,  # 前端可提示"由谁处理中"
            "process": process_engine.instance_view(db, etype, t.id),
        }
    )
    return ok(detail)


@router.patch("/{ticket_id}")
def update_ticket(ticket_id: str, body: TicketUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    t = _get_ticket(db, ticket_id, user)
    _require_type_perm(db, user, t.ticket_type, "edit")  # M17.2
    ensure_not_example(t)
    if t.status in ("closed", "rejected"):
        raise AppError("TICKET_FINAL", "终态工单不可编辑")
    data = body.model_dump(exclude_unset=True)
    reassigned = "assignee" in data and data["assignee"] != t.assignee
    for k, v in data.items():
        setattr(t, k, v)
    audit(db, "ticket", t.id, "update", user, {"fields": list(data.keys())})
    if reassigned and t.assignee:
        from app.events import notifier

        notifier.notify(
            db, "ticket.assigned", "ticket", t.id, [t.assignee],
            f"工单改派给您：{t.ticket_code} {t.title}", link=f"/itsm/tickets/{t.id}",
        )
    db.commit()
    return ok({"id": t.id})


@router.post("/{ticket_id}/transition")
def transition_ticket(ticket_id: str, body: TransitionIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    t = _get_ticket(db, ticket_id, user)
    _require_type_perm(db, user, t.ticket_type, "edit")  # M17.2
    # M25：普通流转仅流程当前处理人；审批类流转由状态机 allowed_roles 授权
    process_engine.require_flow_operator_for_transition(db, user, svc.entity_type_of(t), t.id, t.status, body.to)
    ensure_not_example(t)
    svc.do_transition(db, t, body.to, body.fields, user)
    return ok({"id": t.id, "status": t.status})


@router.post("/{ticket_id}/close")
def close_ticket(ticket_id: str, body: TicketCloseIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    """一键关单（M20 列表管理动作）：沿状态机路径推进至已关闭，理由必填。"""
    t = _get_ticket(db, ticket_id, user)
    _require_type_perm(db, user, t.ticket_type, "edit")
    process_engine.require_flow_operator(db, user, svc.entity_type_of(t), t.id)  # M25：仅流程当前处理人
    ensure_not_example(t)
    svc.quick_close(db, t, body.reason, user)
    return ok({"id": t.id, "status": t.status})


@router.delete("/{ticket_id}")
def delete_ticket(ticket_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    """删除工单（M20，软删）：按类型模块 delete 权限（默认仅 admin）；级联软删流程实例与任务。"""
    t = _get_ticket(db, ticket_id, user)
    _require_type_perm(db, user, t.ticket_type, "delete")
    ensure_not_example(t)
    from app.models import ProcessInstance, ProcessTask

    t.is_deleted = True
    etype = svc.entity_type_of(t)
    instances = 0
    for inst in db.query(ProcessInstance).filter(
        ProcessInstance.entity_type == etype,
        ProcessInstance.entity_id == t.id,
        ProcessInstance.is_deleted.is_(False),
    ):
        inst.is_deleted = True
        instances += 1
        for task in db.query(ProcessTask).filter(ProcessTask.instance_id == inst.id, ProcessTask.is_deleted.is_(False)):
            task.is_deleted = True
    audit(db, "ticket", t.id, "delete", user, {"code": t.ticket_code, "process_instances": instances})
    db.commit()
    return ok({"id": t.id, "process_instances": instances})


@router.post("/{ticket_id}/satisfaction")
def rate(ticket_id: str, body: SatisfactionIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    t = _get_ticket(db, ticket_id, user)
    ensure_not_example(t)
    svc.rate_satisfaction(db, t, body.score, user)
    return ok({"id": t.id, "satisfaction": t.satisfaction})


@router.post("/{ticket_id}/escalate-problem")
def escalate_problem(ticket_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("problems", "create"))):
    """一键升级为问题：自动带工单上下文并双向关联。"""
    t = _get_ticket(db, ticket_id, user)
    ensure_not_example(t)
    if t.problem_id:
        raise AppError("ALREADY_ESCALATED", "该工单已关联问题")
    from app.routers.problems import _create_problem

    problem = _create_problem(
        db,
        {
            "title": t.title,
            "description": f"[由工单 {t.ticket_code} 升级]\n\n{t.description}",
            "priority": t.priority,
            "service_item_id": t.service_item_id,
            "owner": t.assignee,
        },
        user,
        source_ticket=t,
    )
    db.commit()
    return ok({"problem_id": problem.id, "problem_code": problem.problem_code})


@router.post("/{ticket_id}/to-knowledge")
def to_knowledge(ticket_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    """一键沉淀为知识草稿：带出工单上下文，作者进知识库编辑后发布。"""
    t = _get_ticket(db, ticket_id, user)
    from app.models import KnowledgeArticle, OrgMember
    from app.services.codes import gen_code

    person = db.get(OrgMember, user.person_id) if user.person_id else None
    content = f"""## 问题现象

{t.description}

## 解决方案

{t.solution or '（待补充）'}

## 根因

{t.root_cause or '（待补充）'}

> 来源工单：{t.ticket_code} {t.title}
"""
    article = KnowledgeArticle(
        article_code=gen_code(db, KnowledgeArticle, "article_code", "KB"),
        title=t.title,
        content=content,
        tags=[t.service_line] if t.service_line else [],
        status="draft",
        author=user.id,
        author_name=person.name if person else user.username,
        linked_ticket_ids=[t.id],
    )
    db.add(article)
    db.flush()
    audit(db, "knowledge_article", article.id, "create_from_ticket", user, {"ticket": t.ticket_code})
    db.commit()
    return ok({"article_id": article.id, "article_code": article.article_code})
