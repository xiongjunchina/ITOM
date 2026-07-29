"""工单域业务逻辑（PRD §5.1）。"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.events import notifier
from app.events.bus import publish
from app.models import AuthUser, OrgMember, ServiceItem, ServiceItemFormVersion, Ticket
from app.services import dispatch, process_engine, service_forms, sla
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


def create_ticket(db: Session, data: dict, actor: AuthUser, commit: bool = True) -> Ticket:
    if data["ticket_type"] not in TICKET_TYPES:
        raise AppError("INVALID_TYPE", "工单类型无效")
    item = db.get(ServiceItem, data["service_item_id"])
    if not item or item.is_deleted or item.status != "上架":
        raise AppError("INVALID_ITEM", "服务项不存在或已下架")
    if data["ticket_type"] == CHANGE and not data.get("change_type"):
        raise AppError("STAGE_FIELD_REQUIRED", "变更工单必须选择变更类型")

    data = dict(data)
    process_definition_id = None
    if data["ticket_type"] == "service_request":
        form = None
        if data.get("request_form_version_id"):
            form = db.get(ServiceItemFormVersion, data["request_form_version_id"])
            if (
                not form
                or form.is_deleted
                or form.service_item_id != item.id
                or form.status != "published"
                or item.active_form_version_id != form.id
            ):
                raise AppError("SERVICE_FORM_CHANGED", "服务表单已更新，请刷新后重新填写", 409)
        else:
            form = service_forms.ensure_default_form(db, item, actor.id)
        answers = dict(data.get("request_data") or {})
        answers.setdefault("title", data.get("title"))
        answers.setdefault("description", data.get("description"))
        properties = form.schema.get("properties") or {}
        if "priority" in properties:
            answers.setdefault("priority", data.get("priority") or item.default_priority)
        if "suspected_major_impact" in properties:
            answers.setdefault(
                "suspected_major_impact",
                bool(data.get("suspected_major_impact", False)),
            )
        validation = service_forms.validate_answers(db, form.schema, answers)
        if validation["missing"] or validation["errors"]:
            raise AppError("FORM_VALIDATION_FAILED", "服务请求表单存在缺失或无效字段")
        normalized = validation["normalized"]
        data["request_data"] = normalized
        data["request_form_version_id"] = form.id
        data["request_form_snapshot"] = service_forms.form_row(form)
        data["title"] = normalized["title"]
        data["description"] = normalized["description"]
        data["priority"] = normalized.get("priority") or data.get("priority") or item.default_priority
        data["suspected_major_impact"] = bool(
            normalized.get("suspected_major_impact", data.get("suspected_major_impact", False))
        )
        process_definition_id = item.process_definition_id
        if not data.get("assignee"):
            decision = dispatch.assign(db, item)
            data["assignee"] = decision.assignee_id
            data["dispatch_rule_id"] = decision.rule.id if decision.rule else None
            data["dispatch_source"] = decision.source
            if decision.assignee_id:
                data["assigned_at"] = datetime.now()
        else:
            data["dispatch_source"] = data.get("dispatch_source") or "manual"
            data["assigned_at"] = data.get("assigned_at") or datetime.now()

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
        definition_id=process_definition_id,
    )
    audit(db, "ticket", ticket.id, "create", actor, {"code": ticket.ticket_code, "type": ticket.ticket_type})
    publish(db, "ticket.created", "ticket", ticket.id, {"code": ticket.ticket_code})

    if ticket.assignee:
        publish(db, "ticket.assigned", "ticket", ticket.id, {"assignee": ticket.assignee})

    if ticket.assignee:
        notifier.notify(
            db, "ticket.assigned", "ticket", ticket.id,
            [ticket.assignee],
            f"新工单指派：{ticket.ticket_code} {ticket.title}",
            link=f"/itsm/tickets/{ticket.id}",
        )
    if not ticket.assignee and ticket.ticket_type == "service_request":
        publish(db, "ticket.dispatch_unassigned", "ticket", ticket.id, {"source": ticket.dispatch_source})
    if commit:
        db.commit()
    return ticket


def do_transition(db: Session, ticket: Ticket, to: str, fields: dict, actor: AuthUser, system: bool = False) -> Ticket:
    now = datetime.now()
    etype = entity_type_of(ticket)
    from_code, _ = wf_transition(db, ticket, etype, to, fields, actor, system=system)

    # 打点与派生
    if from_code == "new" and to != "new":
        sla.mark_first_response(ticket, now)
    if to == "processing" and from_code != "processing":
        publish(db, "ticket.processing", "ticket", ticket.id, {})
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
    if to in ("closed", "rejected"):
        # M24：单据终态 → 收尾流程实例（作废剩余待办，监控不再显示 running）
        process_engine.finalize_instance(db, etype, ticket.id, f"单据已{'关闭' if to == 'closed' else '拒绝'}，流程随单收尾")
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
    """状态机闭环路径（实现挪至 workflow.closure_path，问题单等实体共用）。"""
    from app.services.workflow import closure_path

    return closure_path(db, etype, src, actor, ignore_roles=ignore_roles)


def quick_close(db: Session, ticket: Ticket, reason: str, actor: AuthUser) -> Ticket:
    """一键关单（M20，列表管理动作）：沿状态机允许路径逐步推进至 closed。

    不绕过状态机——路径不可达（如变更单卡在待审批且无审批权）时报错提示。
    理由记入解决方案（为空时）与备注，审计留痕。
    """
    if ticket.status in ("closed", "rejected"):
        raise AppError("TICKET_FINAL", "工单已是终态")
    etype = entity_type_of(ticket)
    # 关闭权已在端点校验（admin/登记人，M28）——路径不再受操作者角色限制
    path = _closure_path(db, etype, ticket.status, actor, ignore_roles=True)
    if not path:
        raise AppError("NO_CLOSE_PATH", "状态机不允许从当前状态流转到已关闭，请检查状态机配置")
    if not ticket.solution:
        ticket.solution = reason
    note = f"[关单说明] {reason}"
    ticket.remarks = f"{ticket.remarks}\n{note}" if ticket.remarks else note
    for to in path:
        # 阶段必填字段兜底：solution 已提前写入；closed 需关闭代码（默认「已解决」，语义由理由说明）
        fields = {"closure_code": ticket.closure_code or "resolved"} if to == "closed" else {}
        do_transition(db, ticket, to, fields, actor, system=True)
    audit(db, "ticket", ticket.id, "quick_close", actor, {"code": ticket.ticket_code, "path": path, "reason": reason})
    db.commit()
    return ticket


def on_ticket_advanced(db: Session, ticket_id: str, actor: AuthUser) -> None:
    """工单流程编排（M31）：状态由流程自动同步，处理人不再手动流转。

    服务请求/事件：任一步骤完成后状态仍 new → 处理中（打首次响应 SLA）；
    进入最后一步（用户确认/关闭复盘）→ 已解决（打解决 SLA、通知提交人确认评价）；
    流程完成 → 已关闭（M23）。变更单保持状态机审批链（显式授权），仅终点闭环。
    """
    from app.services.process_engine import _live_steps, current_pending_task
    from app.services.workflow import closure_path

    t = db.get(Ticket, ticket_id)
    if not t or t.is_deleted or t.status in ("closed", "rejected"):
        return
    etype = entity_type_of(t)
    task = current_pending_task(db, etype, t.id)
    if not task:
        auto_close_on_process_complete(db, t.id, actor)
        return
    if t.ticket_type == "change":
        # 变更单的状态由审批链驱动：申请处理节点完成后，立即进入
        # ``pending_approval``，这样审批人看到的状态与当前流程节点一致。
        # 审批节点的同意/驳回仍由 process_engine.approve_task/reject_task
        # 负责，避免在这里重复推进审批状态。
        if task.step and task.step.node_type == "approval" and t.status == "new":
            do_transition(db, t, "pending_approval", {}, actor, system=True)
        return
    from app.models import ProcessInstance

    inst = db.get(ProcessInstance, task.instance_id)
    live = _live_steps(inst.definition)
    last_seq = max(s.seq for s in live) if live else None
    cur_seq = task.step.seq if task.step else None
    if cur_seq is not None and last_seq is not None and cur_seq == last_seq and t.status not in ("resolved",):
        if not t.solution:
            from app.models import ProcessTask

            done = (
                db.query(ProcessTask)
                .filter(ProcessTask.instance_id == inst.id, ProcessTask.status == "已完成",
                        ProcessTask.is_deleted.is_(False))
                .order_by(ProcessTask.completed_at.desc())
                .all()
            )
            t.solution = next((x.comment for x in done if x.comment), None) or "详见流程处理记录"
        path = closure_path(db, etype, t.status, actor, dst="resolved", ignore_roles=True)
        for to in path or []:
            do_transition(db, t, to, {}, actor, system=True)
    elif t.status == "new":
        path = closure_path(db, etype, t.status, actor, dst="processing", ignore_roles=True)
        for to in path or []:
            do_transition(db, t, to, {}, actor, system=True)


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
