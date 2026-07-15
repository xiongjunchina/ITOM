"""工单域业务逻辑（PRD §5.1）。"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.events import notifier
from app.events.bus import publish
from app.models import AuthUser, OrgMember, ServiceItem, Ticket
from app.services import process_engine, sla
from app.services.audit import audit
from app.services.codes import gen_code
from app.services.workflow import transition as wf_transition

CHANGE = "change"
TICKET_TYPES = ("incident", "service_request", "change")


def entity_type_of(ticket: Ticket) -> str:
    return "ticket_change" if ticket.ticket_type == CHANGE else "ticket"


def _approver_person_ids(db: Session, entity_type: str) -> list[str]:
    """按状态机 pending_approval→approved 的 allowed_roles 动态解析审批人（含组/继承）。"""
    from app.services.rbac import actor_keys
    from app.services.workflow import get_transition

    rule = get_transition(db, entity_type, "pending_approval", "approved")
    allowed = set(rule.allowed_roles or []) if rule else set()
    users = db.query(AuthUser).filter(AuthUser.is_active.is_(True)).all()
    if not allowed:  # 未限定角色则不定向通知
        return []
    return [u.person_id for u in users if u.person_id and (actor_keys(db, u) & allowed)]


def create_ticket(db: Session, data: dict, actor: AuthUser) -> Ticket:
    if data["ticket_type"] not in TICKET_TYPES:
        raise AppError("INVALID_TYPE", "工单类型无效")
    item = db.get(ServiceItem, data["service_item_id"])
    if not item or item.is_deleted or item.status != "上架":
        raise AppError("INVALID_ITEM", "服务项不存在或已下架")
    if data["ticket_type"] == CHANGE and not data.get("change_type"):
        raise AppError("STAGE_FIELD_REQUIRED", "变更工单必须选择变更类型")

    now = datetime.now()
    resp_min, reso_hours = sla.resolve_targets(db, data["priority"], item)
    person = db.get(OrgMember, actor.person_id) if actor.person_id else None

    ticket = Ticket(
        **data,
        ticket_code=gen_code(db, Ticket, "ticket_code", "TK"),
        status="new",
        submitter=actor.id,
        submitter_name=person.name if person else actor.username,
        submitter_dept=person.department.name if person and person.department else None,
        service_line=item.catalog.name,
        submitted_at=now,
        sla_response_min=resp_min,
        sla_resolution_hours=reso_hours,
    )
    db.add(ticket)
    db.flush()

    process_engine.start_instance(
        db,
        entity_type_of(ticket),
        ticket.id,
        {"ticket_type": ticket.ticket_type},
        preferred_assignee=ticket.assignee,
    )
    audit(db, "ticket", ticket.id, "create", actor, {"code": ticket.ticket_code, "type": ticket.ticket_type})
    publish(db, "ticket.created", "ticket", ticket.id, {"code": ticket.ticket_code})

    if ticket.assignee:
        notifier.notify(
            db, "ticket.assigned", "ticket", ticket.id,
            [ticket.assignee],
            f"新工单指派：{ticket.ticket_code} {ticket.title}",
            link=f"/itsm/tickets/{ticket.id}",
        )
    db.commit()
    return ticket


def do_transition(db: Session, ticket: Ticket, to: str, fields: dict, actor: AuthUser, system: bool = False) -> Ticket:
    now = datetime.now()
    etype = entity_type_of(ticket)
    from_code, _ = wf_transition(db, ticket, etype, to, fields, actor, system=system)

    # 打点与派生
    if from_code == "new" and to != "new":
        sla.mark_first_response(ticket, now)
    if to == "paused":
        ticket.paused_started_at = now
    if from_code == "paused" and to != "paused":
        if ticket.paused_started_at:
            ticket.paused_minutes = (ticket.paused_minutes or 0) + (now - ticket.paused_started_at).total_seconds() / 60
            ticket.paused_started_at = None
    if to == "resolved":
        sla.mark_resolved(ticket, now)
        publish(db, "ticket.resolved", "ticket", ticket.id, {})
        if ticket.submitter:
            submitter_user = db.get(AuthUser, ticket.submitter)
            if submitter_user and submitter_user.person_id:
                notifier.notify(
                    db, "ticket.resolved", "ticket", ticket.id,
                    [submitter_user.person_id],
                    f"您的工单已解决：{ticket.ticket_code} {ticket.title}，请确认并评价",
                    link=f"/itsm/tickets/{ticket.id}",
                )
    if from_code == "resolved" and to == "processing":  # 重开
        ticket.reopen_count = (ticket.reopen_count or 0) + 1
        ticket.resolved_at = None
        ticket.sla_resolution_met = None
        ticket.first_time_fix = False
    if to == "closed":
        ticket.closed_at = now
        publish(db, "ticket.closed", "ticket", ticket.id, {"sla_met": bool(ticket.sla_resolution_met)})
    # 变更审批
    if to == "pending_approval":
        publish(db, "change.approval_requested", "ticket", ticket.id, {})
        approvers = _approver_person_ids(db, entity_type_of(ticket))
        if approvers:
            notifier.notify(
                db, "change.approval_requested", "ticket", ticket.id,
                approvers,
                f"变更待审批：{ticket.ticket_code} {ticket.title}（风险 {ticket.risk_level or '-'}）",
                link=f"/itsm/tickets/{ticket.id}",
            )
    if to in ("approved", "rejected"):
        ticket.approved_by = actor.id
        ticket.approved_at = now
        ticket.approval_comment = fields.get("approval_comment") or ticket.approval_comment
        publish(db, f"change.{to}", "ticket", ticket.id, {})

    db.commit()
    return ticket


def _closure_path(db: Session, etype: str, src: str, actor: AuthUser, ignore_roles: bool = False) -> list[str] | None:
    """BFS 最短状态机路径 src→closed（尊重用户配置的转换与角色限制），不可达返回 None。

    ignore_roles=True：系统编排（流程完成自动闭环）不受操作者角色限制。
    """
    from collections import deque

    from app.core.rbac import ADMIN
    from app.models import WorkflowTransition
    from app.services.rbac import actor_keys

    held = actor_keys(db, actor)
    adj: dict[str, list[str]] = {}
    rows = (
        db.query(WorkflowTransition)
        .filter(WorkflowTransition.entity_type == etype, WorkflowTransition.is_deleted.is_(False))
        .all()
    )
    for tr in rows:
        allowed = tr.allowed_roles or []
        if ignore_roles or not allowed or ADMIN in held or held & set(allowed):
            adj.setdefault(tr.from_code, []).append(tr.to_code)
    prev: dict[str, str | None] = {src: None}
    queue = deque([src])
    while queue:
        cur = queue.popleft()
        if cur == "closed":
            break
        for nxt in adj.get(cur, []):
            if nxt not in prev:
                prev[nxt] = cur
                queue.append(nxt)
    if "closed" not in prev:
        return None
    path: list[str] = []
    node: str | None = "closed"
    while node is not None and node != src:
        path.append(node)
        node = prev[node]
    return list(reversed(path))


def quick_close(db: Session, ticket: Ticket, reason: str, actor: AuthUser) -> Ticket:
    """一键关单（M20，列表管理动作）：沿状态机允许路径逐步推进至 closed。

    不绕过状态机——路径不可达（如变更单卡在待审批且无审批权）时报错提示。
    理由记入解决方案（为空时）与备注，审计留痕。
    """
    if ticket.status in ("closed", "rejected"):
        raise AppError("TICKET_FINAL", "工单已是终态")
    etype = entity_type_of(ticket)
    path = _closure_path(db, etype, ticket.status, actor)
    if not path:
        raise AppError("NO_CLOSE_PATH", "状态机不允许从当前状态流转到已关闭（或需要审批角色），请在详情页按流程处理")
    if not ticket.solution:
        ticket.solution = reason
    note = f"[关单说明] {reason}"
    ticket.remarks = f"{ticket.remarks}\n{note}" if ticket.remarks else note
    for to in path:
        # 阶段必填字段兜底：solution 已提前写入；closed 需关闭代码（默认「已解决」，语义由理由说明）
        fields = {"closure_code": ticket.closure_code or "resolved"} if to == "closed" else {}
        do_transition(db, ticket, to, fields, actor)
    audit(db, "ticket", ticket.id, "quick_close", actor, {"code": ticket.ticket_code, "path": path, "reason": reason})
    db.commit()
    return ticket


def auto_close_on_process_complete(db: Session, ticket_id: str, actor: AuthUser) -> bool:
    """流程实例完成 → 工单沿状态机自动闭环到 closed（M23，用户实测：变更复盘完成后状态仍停在待审批）。

    系统级编排：路径不受操作者角色限制（审批语义已在流程「变更审批」步骤履行）；
    阶段必填字段兜底（solution/closure_code）。路径不可达仅记审计，不阻塞任务完成。
    """
    t = db.get(Ticket, ticket_id)
    if not t or t.is_deleted or t.status in ("closed", "rejected"):
        return False
    etype = entity_type_of(t)
    path = _closure_path(db, etype, t.status, actor, ignore_roles=True)
    if not path:
        audit(db, "ticket", t.id, "auto_close_blocked", actor, {"code": t.ticket_code, "status": t.status})
        return False
    if not t.solution:
        t.solution = "流程执行完毕，系统自动闭环"
    for to in path:
        fields = {"closure_code": t.closure_code or "resolved"} if to == "closed" else {}
        do_transition(db, t, to, fields, actor, system=True)
    audit(db, "ticket", t.id, "auto_close", actor, {"code": t.ticket_code, "path": path})
    db.commit()
    return True


def rate_satisfaction(db: Session, ticket: Ticket, score: int, actor: AuthUser) -> Ticket:
    if ticket.status != "closed":
        raise AppError("NOT_CLOSED", "工单关闭后才能评价")
    if ticket.submitter != actor.id:
        raise AppError("FORBIDDEN", "只有提交人可以评价", 403)
    if not 1 <= score <= 5:
        raise AppError("INVALID_SCORE", "评分须为 1-5")
    ticket.satisfaction = score
    audit(db, "ticket", ticket.id, "satisfaction", actor, {"score": score})
    if score >= 4:
        publish(db, "ticket.satisfaction_rated", "ticket", ticket.id, {"score": score})
    db.commit()
    return ticket
