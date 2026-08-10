"""工单路由（PRD §5.1）。"""
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_example_delete_allowed, ensure_not_example
from app.core.rbac import BDO, REQUESTER
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import AuthUser, OrgMember, ServiceDispatchRule, ServiceItem, Ticket, TicketSatisfaction
from app.schemas.common import ok, paginate
from app.schemas.itsm import SatisfactionIn, TicketCloseIn, TicketCreate, TicketUpdate, TransitionIn
from app.services import process_engine
from app.services import tickets as svc
from app.services.audit import audit
from app.services.team_scope import require_it_member_if_configured
from app.services.service_audience import service_item_visible_to_user
from app.services.workflow import allowed_targets, restrict_terminal_targets, require_terminal_transition_admin, status_names

router = APIRouter(prefix="/api/tickets", tags=["itsm"])


def _is_admin(db: Session, user: AuthUser) -> bool:
    from app.core.rbac import ADMIN
    from app.services.rbac import actor_keys

    return ADMIN in actor_keys(db, user)


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
    # BDO 是业务用户的受控子集；无 IT/审计等其他角色时，仍只能处理本人单据。
    return bool(roles) and roles.issubset({REQUESTER, BDO})


def _ticket_query(
    db: Session,
    user: AuthUser,
    *,
    q: str = "",
    status: str = "",
    ticket_type: str = "",
    priority: str = "",
    assignee: str = "",
    scope: str = "",
):
    """列表与导出共用同一权限、数据范围和筛选语义。"""
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
    return query


def _row(t: Ticket, db: Session, names: dict) -> dict:
    assignee = db.get(OrgMember, t.assignee) if t.assignee else None
    implementation_assignee = db.get(OrgMember, t.implementation_assignee) if t.implementation_assignee else None
    return {
        "id": t.id, "ticket_code": t.ticket_code, "title": t.title,
        "ticket_type": t.ticket_type, "priority": t.priority,
        "status": t.status, "status_name": names.get(t.status, t.status),
        "service_item_id": t.service_item_id,
        "service_item_name": t.service_item.name if t.service_item else None,
        "service_category": t.service_category,
        "other_info": t.other_info,
        "service_line": t.service_line,
        "submitter": t.submitter, "submitter_name": t.submitter_name, "submitter_dept": t.submitter_dept,
        "assignee": t.assignee, "assignee_name": assignee.name if assignee else None,
        "implementation_assignee": t.implementation_assignee,
        "implementation_assignee_name": implementation_assignee.name if implementation_assignee else None,
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
    query = _ticket_query(
        db, user, q=q, status=status, ticket_type=ticket_type,
        priority=priority, assignee=assignee, scope=scope,
    )
    items, total = paginate(query.order_by(Ticket.is_example.desc(), Ticket.submitted_at.desc()), page, page_size)
    names = {**status_names(db, "ticket"), **status_names(db, "ticket_change")}
    pend = process_engine.pending_steps_map(db, ["ticket", "ticket_change"], [t.id for t in items], user)
    rows = []
    for ticket in items:
        entity_type = svc.entity_type_of(ticket)
        edit_access = process_engine.workflow_edit_access(db, user, entity_type, ticket.id, _ticket_module(ticket.ticket_type))
        delete_access = process_engine.workflow_delete_access(db, user, entity_type, ticket.id, _ticket_module(ticket.ticket_type))
        rows.append({
            **_row(ticket, db, names),
            "pending_step": pend.get(ticket.id),
            "can_edit": edit_access.allowed and not ticket.is_example,
            "can_delete": delete_access.allowed and not ticket.is_example,
            "workflow_edit_mode": edit_access.mode,
            "workflow_edit_locked_reason": edit_access.reason,
        })
    return ok(rows, total=total, page=page)


def _ticket_export_response(content: bytes, filename: str) -> Response:
    from urllib.parse import quote

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=tickets.xlsx; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/export")
def export_tickets(
    q: str = "",
    status: str = "",
    ticket_type: str = "",
    priority: str = "",
    assignee: str = "",
    scope: str = "",
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """导出当前筛选条件下的全部有权工单，而不是前端当前页。"""
    from app.services.excel_io import Col, Sheet, build_export

    query = _ticket_query(
        db, user, q=q, status=status, ticket_type=ticket_type,
        priority=priority, assignee=assignee, scope=scope,
    )
    names = {**status_names(db, "ticket"), **status_names(db, "ticket_change")}
    type_names = {"service_request": "服务请求", "incident": "事件", "change": "变更"}
    rows = []
    for ticket in query.order_by(Ticket.is_example.desc(), Ticket.submitted_at.desc()).all():
        row = _row(ticket, db, names)
        rows.append({
            "ticket_code": row["ticket_code"],
            "title": row["title"],
            "ticket_type": type_names.get(row["ticket_type"], row["ticket_type"]),
            "priority": row["priority"],
            "status": row["status_name"],
            "service_item": row["service_item_name"],
            "service_category": row["service_category"],
            "assignee": row["assignee_name"],
            "submitter": row["submitter_name"],
            "submitted_at": row["submitted_at"],
            "sla_hours": row["sla_resolution_hours"],
        })
    sheet = Sheet("工单清单", [
        Col("ticket_code", "工单编号"), Col("title", "标题"), Col("ticket_type", "单据类型"),
        Col("priority", "优先级"), Col("status", "状态"), Col("service_item", "服务项"),
        Col("service_category", "服务类别"), Col("assignee", "受理人"), Col("submitter", "提交人"),
        Col("submitted_at", "提交时间"), Col("sla_hours", "SLA（小时）", kind="float"),
    ])
    return _ticket_export_response(build_export(sheet, rows), "工单清单.xlsx")


@router.post("")
def create_ticket(body: TicketCreate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    _require_type_perm(db, user, body.ticket_type, "create")  # M17.2：按工单类型鉴权
    service_item = db.get(ServiceItem, body.service_item_id)
    if not service_item or service_item.is_deleted:
        raise AppError("NOT_FOUND", "服务项不存在", 404)
    if not service_item_visible_to_user(db, service_item, user):
        raise AppError("SERVICE_ITEM_FORBIDDEN", "当前账号不在该服务项的服务对象范围内", 403)
    require_it_member_if_configured(db, body.assignee, "工单受理人")
    ticket = svc.create_ticket(db, body.model_dump(exclude_none=True), user)
    names = {**status_names(db, "ticket"), **status_names(db, "ticket_change")}
    return ok(_row(ticket, db, names))


def _get_ticket(db: Session, ticket_id: str, user: AuthUser) -> Ticket:
    t = db.get(Ticket, ticket_id)
    if not t:
        raise AppError("NOT_FOUND", "工单不存在", 404)
    if t.is_deleted:
        # Aily/站内历史通知可在业务单据被撤回后仍保留原详情链接。保留与
        # 不存在记录相同的 HTTP 语义，避免泄漏已删除数据，但给出可操作原因。
        raise AppError("TICKET_DELETED", "工单已撤回或删除，无法查看详情", 404)
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
    implementation_rule = db.get(ServiceDispatchRule, t.implementation_rule_id) if t.implementation_rule_id else None
    rating = (
        db.query(TicketSatisfaction)
        .filter(
            TicketSatisfaction.ticket_id == t.id,
            TicketSatisfaction.is_deleted.is_(False),
        )
        .first()
    )
    # M18：无该类型编辑权限（如业务用户看自己的单）不下发流转按钮，与 transition 接口守卫一致
    edit_access = process_engine.workflow_edit_access(
        db, user, etype, t.id, _ticket_module(t.ticket_type)
    )
    delete_access = process_engine.workflow_delete_access(
        db, user, etype, t.id, _ticket_module(t.ticket_type)
    )
    can_edit = edit_access.allowed
    # M25：流程驱动——普通流转按钮只给当前节点处理人（或 admin）；审批类（显式授权）保留
    _flow_ok, flow_assignee = process_engine.flow_operator_check(db, user, etype, t.id)
    detail.update(
        {
            "submitter": t.submitter,
            "description": t.description, "remarks": t.remarks, "ci_id": t.ci_id,
            "service_category": t.service_category, "other_info": t.other_info,
            "solution": t.solution, "root_cause": t.root_cause, "closure_code": t.closure_code,
            "change_type": t.change_type, "risk_level": t.risk_level,
            "change_reason": t.change_reason, "rollback_plan": t.rollback_plan,
            "planned_start_at": t.planned_start_at, "planned_end_at": t.planned_end_at,
            "implementation_plan": t.implementation_plan,
            "request_data": t.request_data,
            "request_form_version_id": t.request_form_version_id,
            "request_form_snapshot": t.request_form_snapshot,
            "dispatch_source": t.dispatch_source,
            "assigned_at": t.assigned_at,
            "implementation_rule_id": t.implementation_rule_id,
            "implementation_rule_name": implementation_rule.name if implementation_rule else None,
            "implementation_source": t.implementation_source,
            "implementation_selected_by": t.implementation_selected_by,
            "implementation_selected_at": t.implementation_selected_at,
            "accepted_at": t.accepted_at,
            "confirmation_due_at": t.confirmation_due_at,
            "suspected_major_impact": t.suspected_major_impact,
            "approved_at": t.approved_at, "approval_comment": t.approval_comment,
            "first_response_at": t.first_response_at, "resolved_at": t.resolved_at, "closed_at": t.closed_at,
            "paused_minutes": t.paused_minutes, "reopen_count": t.reopen_count,
            "first_time_fix": t.first_time_fix,
            "sla_response_min": t.sla_response_min,
            "actual_response_min": t.actual_response_min, "actual_resolution_hours": t.actual_resolution_hours,
            # M31：SR/事件状态全程由流程编排同步——非 admin 仅保留 挂起/恢复（SLA 暂停语义，
            # 不与流程脱节）；变更保持审批链按钮（M25 处理人过滤+显式授权）；终态仅 admin（M30）
            "allowed_transitions": [] if t.is_example or not can_edit else [
                {"to": code, "to_name": names.get(code, code)}
                for code in restrict_terminal_targets(
                    db, etype, t.status,
                    process_engine.filter_targets_by_flow(
                        db, user, etype, t.id, t.status, allowed_targets(db, etype, t.status, user)),
                    allow_terminal=_is_admin(db, user))
                if _ticket_target_allowed(db, user, t, code)
            ],
            "can_close": _can_close_ticket(db, user, t) and not t.is_example and t.status not in ("closed", "rejected"),
            "can_edit": can_edit and not t.is_example,
            "can_delete": delete_access.allowed and not t.is_example,
            "workflow_edit_mode": edit_access.mode,
            "workflow_edit_locked_reason": edit_access.reason,
            "flow_operator_name": flow_assignee,  # 前端可提示"由谁处理中"
            "process": process_engine.instance_view(db, etype, t.id),
            "satisfaction_detail": (
                {
                    "score": rating.score,
                    "tags": rating.tags or [],
                    "comment": rating.comment,
                    "source": rating.source,
                    "rated_at": rating.rated_at,
                }
                if rating
                else None
            ),
        }
    )
    return ok(detail)


@router.patch("/{ticket_id}")
def update_ticket(ticket_id: str, body: TicketUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    t = _get_ticket(db, ticket_id, user)
    ensure_not_example(t)
    if t.status in ("closed", "rejected"):
        raise AppError("TICKET_FINAL", "终态工单不可编辑")
    data = body.model_dump(exclude_unset=True)
    access = process_engine.require_workflow_edit(db, user, svc.entity_type_of(t), t.id, _ticket_module(t.ticket_type))
    process_engine.require_safe_correction_fields(access, data, {"assignee"})
    if "assignee" in data:
        require_it_member_if_configured(db, data["assignee"], "工单受理人")
    reassigned = "assignee" in data and data["assignee"] != t.assignee
    for k, v in data.items():
        setattr(t, k, v)
    audit(db, "ticket", t.id, "update", user, {"fields": list(data.keys()), "workflow_edit_mode": access.mode})
    if reassigned and t.assignee:
        # The detail page edits Ticket.assignee directly.  When a live process
        # task exists, route the same change through the process engine so the
        # authorization source and the displayed ticket owner cannot diverge.
        pending = process_engine.current_pending_task(db, svc.entity_type_of(t), t.id)
        if pending:
            process_engine.reassign_task(db, pending.id, t.assignee)
        else:
            from app.events import notifier
            from app.events.bus import publish

            publish(db, "ticket.assigned", "ticket", t.id, {"assignee": t.assignee})
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
    if not _ticket_target_allowed(db, user, t, body.to):
        # M31：SR/事件状态由完成流程步骤自动同步（受理→处理中，末步→已解决，完成→关闭）
        raise AppError("USE_PROCESS_STEP", "请通过「完成此步骤」推进流程，工单状态将自动同步", 403)
    # M28：普通授权的终态流转=强制关闭，仅系统管理员（正常闭环走流程完成自动关闭）
    require_terminal_transition_admin(db, user, svc.entity_type_of(t), t.status, body.to)
    # M25：普通流转仅流程当前处理人；审批类流转由状态机 allowed_roles 授权
    process_engine.require_flow_operator_for_transition(db, user, svc.entity_type_of(t), t.id, t.status, body.to)
    ensure_not_example(t)
    svc.do_transition(db, t, body.to, body.fields, user)
    return ok({"id": t.id, "status": t.status})


#: M31：SR/事件非 admin 可手动操作的状态目标（挂起/从挂起恢复）——其余状态由流程编排自动同步
_MANUAL_TARGETS_NON_CHANGE = {"paused", "processing"}


def _ticket_target_allowed(db: Session, user: AuthUser, t: Ticket, to_code: str) -> bool:
    """SR/事件：非 admin 仅 挂起（processing→paused）与 恢复（paused→processing）；变更不限（审批链）。"""
    if t.ticket_type == "change" or _is_admin(db, user):
        return True
    if to_code == "paused":
        return True
    if to_code == "processing" and t.status == "paused":
        return True
    return False


def _can_close_ticket(db: Session, user: AuthUser, t: Ticket) -> bool:
    """关闭工单权限（M28，用户定稿）：admin 恒可强关；服务请求登记人本人可关（理由+审计）；
    事件/变更必须走完流程自动闭环，处理节点亦无权关闭。"""
    from app.core.rbac import ADMIN
    from app.services.rbac import actor_keys

    if ADMIN in actor_keys(db, user):
        return True
    return t.ticket_type == "service_request" and t.submitter == user.id


@router.post("/{ticket_id}/close")
def close_ticket(ticket_id: str, body: TicketCloseIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    """一键关单：理由必填、审计留痕（M20/M28）。登记人关闭自己的服务请求不要求模块 edit 权限。"""
    t = _get_ticket(db, ticket_id, user)
    if not _can_close_ticket(db, user, t):
        raise AppError(
            "FORCE_CLOSE_FORBIDDEN",
            "服务请求仅登记人本人可主动关闭；事件/变更须走完流程自动闭环。强制关闭请联系系统管理员",
            403,
        )
    ensure_not_example(t)
    svc.quick_close(db, t, body.reason, user)
    return ok({"id": t.id, "status": t.status})


@router.delete("/{ticket_id}")
def delete_ticket(ticket_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    """删除工单：终止流程待办后软删，已发送的外部历史消息保留审计。"""
    t = _get_ticket(db, ticket_id, user)
    ensure_example_delete_allowed(t, db, user)
    access = process_engine.require_workflow_delete(db, user, svc.entity_type_of(t), t.id, _ticket_module(t.ticket_type))

    etype = svc.entity_type_of(t)
    instances = process_engine.archive_instances(db, etype, t.id, "[单据删除] 工单已撤回或删除")
    t.is_deleted = True
    audit(db, "ticket", t.id, "delete", user, {
        "code": t.ticket_code, "process_instances": instances, "workflow_delete_mode": access.mode,
    })
    db.commit()
    return ok({"id": t.id, "process_instances": instances})


@router.post("/{ticket_id}/satisfaction")
def rate(ticket_id: str, body: SatisfactionIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    t = _get_ticket(db, ticket_id, user)
    ensure_not_example(t)
    rating = svc.rate_satisfaction(
        db,
        t,
        body.score,
        user,
        tags=body.tags,
        comment=body.comment,
        source="web",
    )
    return ok({
        "id": t.id,
        "satisfaction": t.satisfaction,
        "tags": rating.tags or [],
        "comment": rating.comment,
        "source": rating.source,
        "rated_at": rating.rated_at,
    })


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
