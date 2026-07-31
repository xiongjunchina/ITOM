"""跨域单据关联：安全读取，以及“创建目标并关联”的统一编排入口。

本路由不直接写入任何业务表。目标工单、问题、项目仍分别调用既有领域服务，
以保留其字段校验、流程启动、通知和审计；通用关系仅在目标成功创建后同事务写入。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_not_example
from app.db import get_db
from app.deps import get_current_user
from app.models import AuthUser, ServiceItem
from app.schemas.common import ok
from app.services import tickets as ticket_service
from app.services.record_relations import (
    find_submission_retry,
    get_record,
    list_visible_relations,
    record_brief,
    target_for_relation,
    create_record_relation,
)
from app.services.service_audience import service_item_visible_to_user
from app.services.team_scope import require_it_member_if_configured

router = APIRouter(tags=["record-relations"])


class RelationPrepareIn(BaseModel):
    source_entity_type: str
    source_entity_id: str
    relation_type: str


class RelationSubmitIn(RelationPrepareIn):
    reason: str = Field(min_length=5, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    target: dict[str, Any]


def _target_defaults(source_entity_type: str, source: Any, target_kind: str) -> dict[str, Any]:
    """只继承安全的上下文；用户仍须在目标表单完成目标领域的必填信息。"""
    if source_entity_type == "ticket":
        code = source.ticket_code
        title = source.title
        description = source.description
        service_item_id = source.service_item_id
        priority = source.priority
    elif source_entity_type == "problem":
        code = source.problem_code
        title = source.title
        description = source.description
        service_item_id = source.service_item_id
        priority = source.priority
    else:
        code = source.requirement_code
        title = source.title
        description = source.description
        service_item_id = None
        priority = None

    if target_kind == "ticket:incident":
        return {
            "title": f"[由 {code} 升级] {title}",
            "description": f"[来源单据：{code}]\n\n{description}",
            "priority": priority or "P2",
            "service_item_id": service_item_id,
        }
    if target_kind == "problem":
        return {
            "title": f"[根因分析] {title}",
            "description": f"[来源单据：{code}]\n\n{description}",
            "priority": priority or "P3",
            "service_item_id": service_item_id,
            "assigned_line": "ops",
        }
    if target_kind == "ticket:change":
        return {
            "title": f"[修复变更] {title}",
            "description": f"[来源单据：{code}]\n\n{description}",
            "priority": priority or "P3",
            "service_item_id": service_item_id,
            "change_type": "普通",
        }
    return {
        "name": f"[由需求转入] {title}",
        "description": f"[来源需求：{code}]\n\n{description}",
    }


def _target_requirements(target_kind: str) -> list[str]:
    if target_kind == "ticket:incident":
        return ["title", "description", "priority", "service_item_id"]
    if target_kind == "problem":
        return ["title", "description", "priority", "assigned_line"]
    if target_kind == "ticket:change":
        return ["title", "description", "priority", "service_item_id", "change_type"]
    return ["name", "pm", "planned_start", "planned_end"]


def _submission_digest(body: RelationSubmitIn, target_data: dict[str, Any]) -> str:
    """目标数据经过 Pydantic 正规化后再取摘要，保证重试仅认同一业务请求。"""
    payload = {
        "source_entity_type": body.source_entity_type,
        "source_entity_id": body.source_entity_id,
        "relation_type": body.relation_type,
        "reason": body.reason.strip(),
        "target": target_data,
    }
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(content.encode()).hexdigest()


def _validate_ticket_target(body: RelationSubmitIn, target_kind: str) -> dict[str, Any]:
    from app.schemas.itsm import TicketCreate

    try:
        return TicketCreate.model_validate({**body.target, "ticket_type": target_kind.split(":", 1)[1]}).model_dump(
            exclude_none=True
        )
    except ValidationError as exc:
        raise AppError("TARGET_FORM_INVALID", "目标工单表单不完整或格式错误", 422) from exc


def _validate_problem_target(body: RelationSubmitIn) -> dict[str, Any]:
    from app.routers.problems import ProblemCreate

    try:
        return ProblemCreate.model_validate(body.target).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise AppError("TARGET_FORM_INVALID", "目标问题表单不完整或格式错误", 422) from exc


def _validate_project_target(body: RelationSubmitIn) -> dict[str, Any]:
    from app.routers.projects import ProjectCreate

    try:
        return ProjectCreate.model_validate(body.target).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise AppError("TARGET_FORM_INVALID", "目标项目表单不完整或格式错误", 422) from exc


def _create_ticket_target(db: Session, data: dict[str, Any], actor: AuthUser):
    ticket_type = data["ticket_type"]
    from app.services.permissions import TICKET_TYPE_MODULE, has_perm

    module = TICKET_TYPE_MODULE.get(ticket_type, "ticket_sr")
    if not has_perm(db, actor, module, "create"):
        raise AppError("FORBIDDEN", "当前角色无此工单类型的操作权限", 403)
    service_item = db.get(ServiceItem, data["service_item_id"])
    if not service_item or service_item.is_deleted:
        raise AppError("NOT_FOUND", "服务项不存在", 404)
    if not service_item_visible_to_user(db, service_item, actor):
        raise AppError("SERVICE_ITEM_FORBIDDEN", "当前账号不在该服务项的服务对象范围内", 403)
    require_it_member_if_configured(db, data.get("assignee"), "工单受理人")
    return ticket_service.create_ticket(db, data, actor, commit=False)


def _create_problem_target(db: Session, data: dict[str, Any], actor: AuthUser):
    from app.routers.problems import _create_problem

    require_it_member_if_configured(db, data.get("owner"), "问题负责人")
    return _create_problem(db, data, actor)


def _create_project_target(db: Session, data: dict[str, Any], actor: AuthUser, requirement_id: str):
    from app.routers.projects import _create_project, _link_requirement
    from app.models import Requirement

    # requirement_id 只允许由来源需求服务端注入，不能由客户端指向其他需求。
    data = {key: value for key, value in data.items() if key != "requirement_id"}
    requirement = db.get(Requirement, requirement_id)
    if not requirement or requirement.is_deleted:
        raise AppError("NOT_FOUND", "关联需求不存在", 404)
    if requirement.project_id:
        raise AppError("ALREADY_LINKED_PROJECT", "该需求已关联项目，不能重复创建项目", 409)
    project = _create_project(db, data, actor)
    _link_requirement(db, project, requirement_id, actor)
    return project


@router.get("/api/records/{entity_type}/{entity_id}/relations")
def get_record_relations(
    entity_type: str,
    entity_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return ok(list_visible_relations(db, entity_type=entity_type, entity_id=entity_id, actor=user))


@router.post("/api/record-relations/prepare")
def prepare_record_relation(
    body: RelationPrepareIn,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """复核可见性/目标创建权限并返回可安全继承的表单默认值；不写入数据。"""
    source, target_entity_type, target_kind = target_for_relation(
        db,
        source_entity_type=body.source_entity_type,
        source_entity_id=body.source_entity_id,
        relation_type=body.relation_type,
        actor=user,
    )
    ensure_not_example(source)
    return ok(
        {
            "source": record_brief(body.source_entity_type, source),
            "relation_type": body.relation_type,
            "target_entity_type": target_entity_type,
            "target_record_type": target_kind.split(":", 1)[1] if ":" in target_kind else None,
            "defaults": _target_defaults(body.source_entity_type, source, target_kind),
            "required_fields": _target_requirements(target_kind),
        }
    )


@router.post("/api/record-relations/submit")
def submit_record_relation(
    body: RelationSubmitIn,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """创建目标记录、建立关联和审计；全程处于单个数据库事务。

    对 PostgreSQL，来源行锁使同一来源/操作者/目标类型/幂等键的并发请求串行化：
    后到请求会在创建目标之前读到首条关系并返回，避免重复创建目标。
    """
    source, target_entity_type, target_kind = target_for_relation(
        db,
        source_entity_type=body.source_entity_type,
        source_entity_id=body.source_entity_id,
        relation_type=body.relation_type,
        actor=user,
        lock_source=True,
    )
    ensure_not_example(source)

    if target_kind.startswith("ticket:"):
        target_data = _validate_ticket_target(body, target_kind)
    elif target_kind == "problem":
        target_data = _validate_problem_target(body)
    else:
        target_data = _validate_project_target(body)

    request_digest = _submission_digest(body, target_data)
    retry = find_submission_retry(
        db,
        actor=user,
        source_entity_type=body.source_entity_type,
        source_entity_id=body.source_entity_id,
        target_entity_type=target_entity_type,
        idempotency_key=body.idempotency_key,
        request_digest=request_digest,
    )
    if retry:
        target = get_record(db, retry.target_entity_type, retry.target_entity_id)
        return ok(
            {
                "target": record_brief(retry.target_entity_type, target),
                "relation": {"id": retry.id, "relation_type": retry.relation_type},
                "idempotent_replay": True,
            }
        )

    # 目标单据、通用关系和关联审计必须一起成功；任何领域校验、唯一约束或提交失败
    # 都回滚本次刚创建的目标，不能留下“已创建但未关联”的半成品记录。
    try:
        if target_kind.startswith("ticket:"):
            target = _create_ticket_target(db, target_data, user)
        elif target_kind == "problem":
            target = _create_problem_target(db, target_data, user)
        else:
            target = _create_project_target(db, target_data, user, source.id)

        relation, relation_created = create_record_relation(
            db,
            source_entity_type=body.source_entity_type,
            source_entity_id=body.source_entity_id,
            target_entity_type=target_entity_type,
            target_entity_id=target.id,
            relation_type=body.relation_type,
            reason=body.reason,
            idempotency_key=body.idempotency_key,
            request_digest=request_digest,
            actor=user,
        )
        # 正常重试已在创建目标前处理。这里若命中历史关系，继续提交会留下新建目标，
        # 因此必须报冲突并回滚，提示调用方用新的幂等键重新准备。
        if not relation_created:
            raise AppError("RELATION_CONFLICT", "关联已存在，请刷新后重试", 409)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(
        {
            "target": record_brief(target_entity_type, target),
            "relation": {"id": relation.id, "relation_type": relation.relation_type},
            "idempotent_replay": False,
        }
    )
