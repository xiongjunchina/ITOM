"""工单域业务逻辑（PRD §5.1）。"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.events import notifier
from app.events.bus import publish
from app.models import (
    Attachment,
    AuthUser,
    OrgMember,
    ProcessInstance,
    ProcessStep,
    ProcessTask,
    ServiceItem,
    ServiceItemFormVersion,
    Ticket,
    TicketSatisfaction,
)
from app.services import dispatch, process_engine, service_forms, sla
from app.services.audit import audit
from app.services.codes import gen_code
from app.services.workflow import transition as wf_transition

CHANGE = "change"
TICKET_TYPES = ("incident", "service_request", "change")
TICKET_ATTACHMENT_DRAFT = "ticket_draft"
MAX_TICKET_ATTACHMENTS = 10


@dataclass(frozen=True)
class ImplementationHandoff:
    """受理节点转交实施交付时传给流程引擎的唯一派单决定。"""

    assignee_id: str | None
    force_unassigned: bool
    source: str
    rule_id: str | None


def _actor_can_select_implementation(db: Session, actor: AuthUser) -> None:
    """实施交付选择只能由当前 IT 处理人或管理员做出，不能从 Aily/业务报单绕过。"""
    from app.core.rbac import ADMIN
    from app.services.rbac import actor_keys
    from app.services.team_scope import require_it_member

    if ADMIN in actor_keys(db, actor):
        return
    require_it_member(db, actor.person_id, "当前处理人")


def _validate_implementation_member(db: Session, person_id: str | None) -> str:
    from app.services.team_scope import require_it_member

    if not person_id:
        raise AppError("IMPLEMENTATION_ASSIGNEE_REQUIRED", "请选择实施交付人")
    require_it_member(db, person_id, "实施交付人")
    # 复用派单目标校验：除团队范围外还必须是在岗且有启用账号的真实 ITOM 人员。
    dispatch.validate_rule_target(db, "member", person_id, "fixed")
    return person_id


def _service_request_handoff_ticket(db: Session, task: ProcessTask) -> Ticket | None:
    """仅识别服务请求首个受理节点 → 非 requester 后续交付节点。

    不依赖展示名称“受理/实施”，以流程实例的稳定顺序和 requester 动态节点为准。
    这样不同服务项绑定的流程仍能使用同一规则，同时不会把后续回改窗口当作派单入口。
    """
    instance = db.get(ProcessInstance, task.instance_id)
    if not instance or instance.is_deleted or instance.entity_type != "ticket":
        return None
    ticket = db.get(Ticket, instance.entity_id)
    if not ticket or ticket.is_deleted or ticket.ticket_type != "service_request":
        return None
    steps = sorted((step for step in instance.definition.steps if not step.is_deleted), key=lambda step: step.seq)
    try:
        index = next(i for i, step in enumerate(steps) if step.id == task.step_id)
    except StopIteration:
        return None
    if index != 0 or index + 1 >= len(steps) or steps[index + 1].default_role == "requester":
        return None
    return ticket


def prepare_implementation_handoff(
    db: Session,
    task: ProcessTask,
    actor: AuthUser,
    *,
    mode: str | None,
    implementation_assignee: str | None,
) -> ImplementationHandoff | None:
    """在首节点完成前解析实施交付人，并将可审计事实写入服务请求。

    优先级固定为：受理人明确指定（本人/同事）→ 服务项实施规则 → 目录实施兜底
    → 全局实施兜底 → 后续流程节点默认角色。最后一种没有额外规则记录，保持原流程
    定义的职责语义。该方法不得被工单 PATCH/上游回改调用。
    """
    ticket = _service_request_handoff_ticket(db, task)
    if not ticket:
        if mode is not None or implementation_assignee is not None:
            raise AppError("IMPLEMENTATION_ASSIGNMENT_NOT_AVAILABLE", "仅服务请求受理转交实施节点时可安排实施交付人")
        return None

    selected_mode = mode or "auto"
    if selected_mode not in {"auto", "self", "member"}:
        raise AppError("INVALID_IMPLEMENTATION_MODE", "实施交付安排只能选择自动、本人或指定同事")
    if selected_mode != "member" and implementation_assignee is not None:
        raise AppError("INVALID_IMPLEMENTATION_ASSIGNEE", "仅“指定同事”可提交实施交付人")

    _actor_can_select_implementation(db, actor)
    now = datetime.now()
    if selected_mode == "self":
        assignee_id = _validate_implementation_member(db, actor.person_id)
        ticket.implementation_assignee = assignee_id
        ticket.implementation_rule_id = None
        ticket.implementation_source = "self_selected"
        ticket.implementation_selected_by = actor.id
        ticket.implementation_selected_at = now
        return ImplementationHandoff(assignee_id, False, "self_selected", None)

    if selected_mode == "member":
        assignee_id = _validate_implementation_member(db, implementation_assignee)
        ticket.implementation_assignee = assignee_id
        ticket.implementation_rule_id = None
        ticket.implementation_source = "handler_selected"
        ticket.implementation_selected_by = actor.id
        ticket.implementation_selected_at = now
        return ImplementationHandoff(assignee_id, False, "handler_selected", None)

    # 自动模式：每次在实际交接时取最新的有效规则，避免“配置更新了但尚未受理的
    # 旧单据仍按过时负责人执行”。无规则时由下一流程节点的默认角色兜底。
    decision = dispatch.assign(db, ticket.service_item, dispatch_stage="implementation")
    if decision.rule:
        ticket.implementation_assignee = decision.assignee_id
        ticket.implementation_rule_id = decision.rule.id
        ticket.implementation_source = "manual_queue" if decision.manual_queue else decision.source
        ticket.implementation_selected_by = actor.id
        ticket.implementation_selected_at = now
        return ImplementationHandoff(
            decision.assignee_id,
            decision.manual_queue,
            ticket.implementation_source,
            decision.rule.id,
        )

    ticket.implementation_assignee = None
    ticket.implementation_rule_id = None
    ticket.implementation_source = "step_default"
    ticket.implementation_selected_by = actor.id
    ticket.implementation_selected_at = now
    return ImplementationHandoff(None, False, "step_default", None)


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
    attachment_ids = list(dict.fromkeys(data.pop("attachment_ids", []) or []))
    if attachment_ids and data["ticket_type"] != "service_request":
        raise AppError("ATTACHMENT_NOT_AVAILABLE", "仅服务请求支持提交前补充附件", 422)
    if len(attachment_ids) > MAX_TICKET_ATTACHMENTS:
        raise AppError("ATTACHMENT_LIMIT_EXCEEDED", f"单张服务请求最多上传 {MAX_TICKET_ATTACHMENTS} 个附件")
    process_definition_id = None
    force_initial_unassigned = False
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
            force_initial_unassigned = decision.manual_queue
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

    if attachment_ids:
        staged = (
            db.query(Attachment)
            .filter(
                Attachment.id.in_(attachment_ids),
                Attachment.entity_type == TICKET_ATTACHMENT_DRAFT,
                Attachment.entity_id == actor.id,
                Attachment.uploaded_by == actor.id,
                Attachment.is_deleted.is_(False),
            )
            .all()
        )
        if len(staged) != len(attachment_ids):
            raise AppError("ATTACHMENT_DRAFT_INVALID", "存在已失效或不属于当前账号的临时附件", 409)
        for attachment in staged:
            attachment.entity_type = "ticket"
            attachment.entity_id = ticket.id
            audit(
                db,
                "attachment",
                attachment.id,
                "bind_ticket",
                actor,
                {"ticket_id": ticket.id, "ticket_code": ticket.ticket_code},
            )

    process_engine.start_instance(
        db,
        entity_type_of(ticket),
        ticket.id,
        {"ticket_type": ticket.ticket_type},
        preferred_assignee=ticket.assignee,
        definition_id=process_definition_id,
        force_unassigned=force_initial_unassigned,
    )
    audit(
        db,
        "ticket",
        ticket.id,
        "create",
        actor,
        {"code": ticket.ticket_code, "type": ticket.ticket_type, "attachment_count": len(attachment_ids)},
    )
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


def do_transition(
    db: Session,
    ticket: Ticket,
    to: str,
    fields: dict,
    actor: AuthUser,
    system: bool = False,
    commit: bool = True,
) -> Ticket:
    now = datetime.now()
    etype = entity_type_of(ticket)
    from_code, _ = wf_transition(db, ticket, etype, to, fields, actor, system=system)

    # 打点与派生
    if from_code == "new" and to != "new":
        sla.mark_first_response(ticket, now)
    if ticket.ticket_type == "service_request" and from_code == "new" and to == "processing":
        if not ticket.accepted_at:
            ticket.accepted_at = now
        publish(db, "ticket.accepted", "ticket", ticket.id, {"accepted_at": now.isoformat()})
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
        pending = process_engine.current_pending_task(db, etype, ticket.id)
        ticket.confirmation_due_at = pending.due_at if pending else None
        publish(
            db,
            "ticket.resolved",
            "ticket",
            ticket.id,
            {
                "resolved_at": now.isoformat(),
                "confirmation_due_at": (
                    ticket.confirmation_due_at.isoformat() if ticket.confirmation_due_at else None
                ),
                "reopen_count": ticket.reopen_count or 0,
            },
        )
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
        ticket.confirmation_due_at = None
        ticket.sla_resolution_met = None
        ticket.first_time_fix = False
        publish(
            db,
            "ticket.reopened",
            "ticket",
            ticket.id,
            {"reopen_count": ticket.reopen_count},
        )
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

    if commit:
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
        # 首次解决时尊重处理人已显式填写的解决方案；服务请求被用户重开后，
        # 则用本轮最新有效处理任务的说明刷新 solution，避免再次进入待确认时
        # 仍向用户展示上一次未能解决问题的旧说明。流程回退产生的历史任务已
        # 软删除，不参与本轮解决说明选择。
        if not t.solution or (t.ticket_type == "service_request" and (t.reopen_count or 0) > 0):
            from app.models import ProcessTask

            done = (
                db.query(ProcessTask)
                .filter(ProcessTask.instance_id == inst.id, ProcessTask.status == "已完成",
                        ProcessTask.is_deleted.is_(False))
                .order_by(ProcessTask.completed_at.desc())
                .all()
            )
            latest_comment = next((x.comment for x in done if x.comment), None)
            if latest_comment or not t.solution:
                t.solution = latest_comment or "详见流程处理记录"
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


def rate_satisfaction(
    db: Session,
    ticket: Ticket,
    score: int,
    actor: AuthUser,
    *,
    tags: list[str] | None = None,
    comment: str = "",
    source: str = "web",
    commit: bool = True,
) -> TicketSatisfaction:
    if ticket.status != "closed":
        raise AppError("NOT_CLOSED", "工单关闭后才能评价")
    if ticket.submitter != actor.id:
        raise AppError("FORBIDDEN", "只有提交人可以评价", 403)
    if not 1 <= score <= 5:
        raise AppError("INVALID_SCORE", "评分须为 1-5")
    if source not in {"web", "aily", "feishu_card"}:
        raise AppError("INVALID_SOURCE", "评价来源无效")
    normalized_tags: list[str] = []
    for raw in tags or []:
        value = str(raw or "").strip()
        if not value:
            continue
        if len(value) > 32:
            raise AppError("INVALID_TAG", "评价标签不能超过 32 个字符")
        if value not in normalized_tags:
            normalized_tags.append(value)
    if len(normalized_tags) > 5:
        raise AppError("TOO_MANY_TAGS", "评价标签最多 5 个")
    normalized_comment = str(comment or "").strip()
    if len(normalized_comment) > 500:
        raise AppError("COMMENT_TOO_LONG", "评价意见不能超过 500 个字符")

    rating = (
        db.query(TicketSatisfaction)
        .filter(
            TicketSatisfaction.ticket_id == ticket.id,
            TicketSatisfaction.is_deleted.is_(False),
        )
        .with_for_update()
        .first()
    )
    previous_score = rating.score if rating else None
    now = datetime.now()
    if rating:
        rating.score = score
        rating.tags = normalized_tags
        rating.comment = normalized_comment or None
        rating.source = source
        rating.rated_by = actor.id
        rating.rated_at = now
    else:
        rating = TicketSatisfaction(
            ticket_id=ticket.id,
            score=score,
            tags=normalized_tags,
            comment=normalized_comment or None,
            source=source,
            rated_by=actor.id,
            rated_at=now,
        )
        db.add(rating)
        db.flush()
    ticket.satisfaction = score
    audit(
        db,
        "ticket",
        ticket.id,
        "satisfaction_update" if previous_score is not None else "satisfaction_create",
        actor,
        {"score": score, "tags": normalized_tags, "source": source},
    )
    publish(
        db,
        "ticket.satisfaction_saved",
        "ticket",
        ticket.id,
        {"score": score, "rated_at": now.isoformat()},
    )
    if score >= 4 and (previous_score is None or previous_score < 4):
        publish(db, "ticket.satisfaction_rated", "ticket", ticket.id, {"score": score})
    if commit:
        db.commit()
    return rating
