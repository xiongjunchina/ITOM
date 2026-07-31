"""跨域单据关联：白名单、可见范围、幂等与审计。

本服务只处理关联本身。来源和目标单据仍分别由其领域服务创建、流转、校验和授权，
从而避免通过通用关系表绕过 ITOM 的业务规则。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.rbac import REQUESTER
from app.models import AuthUser, Problem, Project, RecordRelation, Requirement, Ticket
from app.services.audit import audit
from app.services.permissions import TICKET_TYPE_MODULE, has_perm
from app.services.rbac import effective_roles


ENTITY_MODELS = {
    "ticket": Ticket,
    "problem": Problem,
    "requirement": Requirement,
    "project": Project,
}

# (来源业务类型, 目标业务类型, relation_type)。ticket 的业务类型取 ticket_type，
# 所以 service_request -> incident 能精确落在白名单中。
RELATION_RULES = {
    ("ticket:service_request", "ticket:incident", "upgraded_to_incident"),
    ("ticket:service_request", "problem", "root_cause_of"),
    ("ticket:incident", "problem", "root_cause_of"),
    ("ticket:incident", "ticket:change", "remediated_by_change"),
    ("problem", "ticket:change", "remediated_by_change"),
    ("requirement", "project", "converted_to_project"),
}

RELATION_LABELS = {
    "upgraded_to_incident": "升级为事件",
    "root_cause_of": "关联根因问题",
    "remediated_by_change": "通过变更修复",
    "converted_to_project": "转为项目",
}

ENTITY_LABELS = {
    "ticket": "工单",
    "problem": "问题",
    "requirement": "需求",
    "project": "项目",
}


def _is_requester_only(db: Session, user: AuthUser) -> bool:
    return effective_roles(db, user) == {REQUESTER}


def get_record(db: Session, entity_type: str, entity_id: str) -> Any:
    model = ENTITY_MODELS.get(entity_type)
    if not model:
        raise AppError("INVALID_ENTITY_TYPE", "不支持的关联单据类型", 422)
    record = db.get(model, entity_id)
    if not record or record.is_deleted:
        raise AppError("NOT_FOUND", "关联单据不存在", 404)
    return record


def _record_kind(entity_type: str, record: Any) -> str:
    return f"ticket:{record.ticket_type}" if entity_type == "ticket" else entity_type


def _record_module(entity_type: str, record: Any) -> str:
    if entity_type == "ticket":
        return TICKET_TYPE_MODULE.get(record.ticket_type, "ticket_sr")
    return {"problem": "problems", "requirement": "requirements", "project": "projects"}[entity_type]


def can_view_record(db: Session, user: AuthUser, entity_type: str, record: Any) -> bool:
    """与各详情路由保持一致的数据范围，而不是仅检查模块开关。"""
    if entity_type == "ticket":
        if _is_requester_only(db, user) and record.submitter != user.id:
            return False
        return record.submitter == user.id or has_perm(db, user, _record_module(entity_type, record), "view")
    if entity_type == "requirement":
        return not _is_requester_only(db, user) or record.requester == user.id
    return has_perm(db, user, _record_module(entity_type, record), "view")


def _require_relation_access(
    db: Session,
    actor: AuthUser,
    source_entity_type: str,
    source: Any,
    target_entity_type: str,
    target: Any,
):
    if not can_view_record(db, actor, source_entity_type, source):
        raise AppError("FORBIDDEN", "无权查看来源单据，不能建立关联", 403)
    # 目标单据的“创建”权限由领域路由在创建时再校验；此处做第二道边界，
    # 防止任何未来调用方绕过该合同而只写关联表。
    if not has_perm(db, actor, _record_module(target_entity_type, target), "create"):
        raise AppError("FORBIDDEN", "当前角色无目标单据的创建权限", 403)


def _digest(
    source_entity_type: str,
    source_entity_id: str,
    target_entity_type: str,
    target_entity_id: str,
    relation_type: str,
    reason: str,
) -> str:
    payload = json.dumps(
        {
            "source_entity_type": source_entity_type,
            "source_entity_id": source_entity_id,
            "target_entity_type": target_entity_type,
            "target_entity_id": target_entity_id,
            "relation_type": relation_type,
            "reason": reason.strip(),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def create_record_relation(
    db: Session,
    *,
    source_entity_type: str,
    source_entity_id: str,
    target_entity_type: str,
    target_entity_id: str,
    relation_type: str,
    reason: str,
    idempotency_key: str,
    actor: AuthUser,
) -> tuple[RecordRelation, bool]:
    """在调用方单次事务中创建关系；重复提交返回第一条有效结果。"""
    reason = reason.strip()
    idempotency_key = idempotency_key.strip()
    if len(reason) < 5:
        raise AppError("INVALID_RELATION_REASON", "关联说明至少填写 5 个字符", 422)
    if not 8 <= len(idempotency_key) <= 128:
        raise AppError("INVALID_IDEMPOTENCY_KEY", "幂等键长度须为 8-128 个字符", 422)
    if source_entity_type == target_entity_type and source_entity_id == target_entity_id:
        raise AppError("INVALID_RELATION", "不能将单据关联到自身", 422)

    source = get_record(db, source_entity_type, source_entity_id)
    target = get_record(db, target_entity_type, target_entity_id)
    if (_record_kind(source_entity_type, source), _record_kind(target_entity_type, target), relation_type) not in RELATION_RULES:
        raise AppError("RELATION_NOT_ALLOWED", "此类单据不支持该关联方式", 422)
    _require_relation_access(db, actor, source_entity_type, source, target_entity_type, target)

    request_digest = _digest(
        source_entity_type, source_entity_id, target_entity_type, target_entity_id, relation_type, reason
    )
    retry = db.query(RecordRelation).filter(
        RecordRelation.is_deleted.is_(False),
        RecordRelation.created_by == actor.id,
        RecordRelation.source_entity_type == source_entity_type,
        RecordRelation.source_entity_id == source_entity_id,
        RecordRelation.target_entity_type == target_entity_type,
        RecordRelation.idempotency_key == idempotency_key,
    ).first()
    if retry:
        if retry.request_digest != request_digest:
            raise AppError("IDEMPOTENCY_CONFLICT", "幂等键已用于不同的关联请求", 409)
        return retry, False

    existing = db.query(RecordRelation).filter(
        RecordRelation.is_deleted.is_(False),
        RecordRelation.source_entity_type == source_entity_type,
        RecordRelation.source_entity_id == source_entity_id,
        RecordRelation.target_entity_type == target_entity_type,
        RecordRelation.target_entity_id == target_entity_id,
        RecordRelation.relation_type == relation_type,
    ).first()
    if existing:
        return existing, False

    relation = RecordRelation(
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        target_entity_type=target_entity_type,
        target_entity_id=target_entity_id,
        relation_type=relation_type,
        reason=reason,
        created_by=actor.id,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    try:
        with db.begin_nested():
            db.add(relation)
            db.flush()
            audit(
                db,
                "record_relation",
                relation.id,
                "create",
                actor,
                {
                    "source": {"type": source_entity_type, "id": source_entity_id},
                    "target": {"type": target_entity_type, "id": target_entity_id},
                    "relation_type": relation_type,
                    "reason": reason,
                },
            )
    except IntegrityError:
        # 并发重复请求命中局部唯一索引后，回读已成功写入的首条关系。
        existing = db.query(RecordRelation).filter(
            RecordRelation.is_deleted.is_(False),
            or_(
                (RecordRelation.source_entity_type == source_entity_type)
                & (RecordRelation.source_entity_id == source_entity_id)
                & (RecordRelation.target_entity_type == target_entity_type)
                & (RecordRelation.target_entity_id == target_entity_id)
                & (RecordRelation.relation_type == relation_type),
                (RecordRelation.created_by == actor.id)
                & (RecordRelation.source_entity_type == source_entity_type)
                & (RecordRelation.source_entity_id == source_entity_id)
                & (RecordRelation.target_entity_type == target_entity_type)
                & (RecordRelation.idempotency_key == idempotency_key),
            ),
        ).first()
        if existing:
            return existing, False
        raise
    return relation, True


def _record_brief(entity_type: str, record: Any) -> dict[str, Any]:
    if entity_type == "ticket":
        return {"entity_type": entity_type, "id": record.id, "code": record.ticket_code, "title": record.title,
                "record_type": record.ticket_type}
    if entity_type == "problem":
        return {"entity_type": entity_type, "id": record.id, "code": record.problem_code, "title": record.title}
    if entity_type == "requirement":
        return {"entity_type": entity_type, "id": record.id, "code": record.requirement_code, "title": record.title}
    return {"entity_type": entity_type, "id": record.id, "code": record.project_code, "title": record.name}


def list_visible_relations(
    db: Session, *, entity_type: str, entity_id: str, actor: AuthUser
) -> list[dict[str, Any]]:
    record = get_record(db, entity_type, entity_id)
    if not can_view_record(db, actor, entity_type, record):
        raise AppError("FORBIDDEN", "无权查看该单据", 403)
    rows = db.query(RecordRelation).filter(
        RecordRelation.is_deleted.is_(False),
        or_(
            (RecordRelation.source_entity_type == entity_type) & (RecordRelation.source_entity_id == entity_id),
            (RecordRelation.target_entity_type == entity_type) & (RecordRelation.target_entity_id == entity_id),
        ),
    ).order_by(RecordRelation.created_at.desc()).all()
    result: list[dict[str, Any]] = []
    for relation in rows:
        outbound = relation.source_entity_type == entity_type and relation.source_entity_id == entity_id
        counterpart_type = relation.target_entity_type if outbound else relation.source_entity_type
        counterpart_id = relation.target_entity_id if outbound else relation.source_entity_id
        try:
            counterpart = get_record(db, counterpart_type, counterpart_id)
        except AppError as exc:
            # 历史关系保留审计，但对端被软删除后不应让来源详情整体不可读。
            if exc.code == "NOT_FOUND":
                continue
            raise
        # 关联两端均需在当前用户可见范围内；否则不泄露其编号、标题和关系存在性。
        if not can_view_record(db, actor, counterpart_type, counterpart):
            continue
        creator = db.get(AuthUser, relation.created_by)
        result.append(
            {
                "id": relation.id,
                "direction": "outbound" if outbound else "inbound",
                "relation_type": relation.relation_type,
                "relation_name": RELATION_LABELS.get(relation.relation_type, relation.relation_type),
                "reason": relation.reason,
                "created_at": relation.created_at,
                "created_by_name": (
                    creator.person.name if creator and creator.person else (creator.username if creator else None)
                ),
                "counterpart": _record_brief(counterpart_type, counterpart),
            }
        )
    return result
