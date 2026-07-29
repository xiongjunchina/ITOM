"""IT 需求登记的共享表单、校验、预览确认和创建逻辑。"""

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.events import notifier
from app.events.bus import publish
from app.models import AuthUser, BusinessDomain, OrgMember, Requirement
from app.services import mcp_intents, process_engine
from app.services.audit import audit
from app.services.codes import gen_code


REQ_TYPES = ("业务", "功能", "数据", "集成", "合规")
REQUIRED_FIELDS = ("title", "req_type", "business_domain_id", "description")


def form_definition(db: Session) -> dict:
    domains = (
        db.query(BusinessDomain)
        .filter(BusinessDomain.active.is_(True), BusinessDomain.is_deleted.is_(False))
        .order_by(BusinessDomain.name)
        .all()
    )
    return {
        "submission_available": bool(domains),
        "blocking_reason": None if domains else "当前没有已启用的业务域，请先由 ITOM 管理员完成业务域配置",
        "form": {
            "required": list(REQUIRED_FIELDS),
            "fields": [
                {"code": "title", "title": "需求标题", "type": "string", "min_length": 2, "max_length": 200},
                {"code": "req_type", "title": "需求类型", "type": "enum", "options": list(REQ_TYPES)},
                {"code": "business_domain_id", "title": "所属业务域", "type": "business_domain"},
                {"code": "description", "title": "需求说明", "type": "long_text"},
                {"code": "expected_date", "title": "期望完成日期", "type": "date"},
                {"code": "expected_effect", "title": "期望效果", "type": "long_text"},
                {"code": "business_value_note", "title": "业务价值说明", "type": "long_text"},
                {"code": "source", "title": "需求来源", "type": "string"},
            ],
        },
        "business_domains": [{"id": row.id, "name": row.name} for row in domains],
    }


def validate_fields(db: Session, fields: dict | None) -> dict:
    fields = dict(fields or {})
    missing = [
        {"code": code, "title": {
            "title": "需求标题", "req_type": "需求类型",
            "business_domain_id": "所属业务域", "description": "需求说明",
        }[code]}
        for code in REQUIRED_FIELDS
        if fields.get(code) in (None, "")
    ]
    errors: list[dict] = []
    allowed = {
        "title", "req_type", "business_domain_id", "description", "source",
        "department", "expected_date", "expected_effect", "business_value_note",
        "parent_requirement_id",
    }
    for code in fields.keys() - allowed:
        errors.append({"code": code, "message": "字段不在 IT 需求登记表中"})
    if fields.get("title") and not 2 <= len(str(fields["title"])) <= 200:
        errors.append({"code": "title", "message": "需求标题长度必须为 2-200 个字符"})
    if fields.get("req_type") and fields["req_type"] not in REQ_TYPES:
        errors.append({"code": "req_type", "message": f"需求类型必须为 {'/'.join(REQ_TYPES)}"})
    domain = db.get(BusinessDomain, fields.get("business_domain_id")) if fields.get("business_domain_id") else None
    if fields.get("business_domain_id") and (not domain or domain.is_deleted or not domain.active):
        errors.append({"code": "business_domain_id", "message": "所属业务域不存在或已停用"})
    normalized = {key: value for key, value in fields.items() if key in allowed and value not in (None, "")}
    if normalized.get("expected_date"):
        try:
            date.fromisoformat(str(normalized["expected_date"]))
        except ValueError:
            errors.append({"code": "expected_date", "message": "期望完成日期格式必须为 YYYY-MM-DD"})
    return {"normalized": normalized, "missing": missing, "errors": errors, "domain": domain}


def _current_process_task(db: Session, requirement_id: str):
    from app.models import ProcessInstance, ProcessTask

    db.flush()
    instance = (
        db.query(ProcessInstance)
        .filter(
            ProcessInstance.entity_type == "requirement",
            ProcessInstance.entity_id == requirement_id,
            ProcessInstance.is_deleted.is_(False),
        )
        .order_by(ProcessInstance.created_at.desc())
        .first()
    )
    if not instance:
        return None
    return (
        db.query(ProcessTask)
        .filter(
            ProcessTask.instance_id == instance.id,
            ProcessTask.status == "待处理",
            ProcessTask.is_deleted.is_(False),
        )
        .first()
    )


def create_requirement(db: Session, data: dict, user: AuthUser, commit: bool = True) -> Requirement:
    validation = validate_fields(db, data)
    if validation["missing"] or validation["errors"]:
        raise AppError("FORM_VALIDATION_FAILED", "IT 需求登记表存在缺失或无效字段")
    normalized = validation["normalized"]
    person = db.get(OrgMember, user.person_id) if user.person_id else None
    if normalized.get("expected_date"):
        normalized["expected_date"] = date.fromisoformat(str(normalized["expected_date"]))
    requirement = Requirement(
        **normalized,
        requirement_code=gen_code(db, Requirement, "requirement_code", "RQ"),
        status="registered",
        registered_at=datetime.now(),
        requester=user.id,
        requester_name=person.name if person else user.username,
    )
    db.add(requirement)
    db.flush()
    process_engine.start_instance(db, "requirement", requirement.id, {})
    requirement.status = "evaluating"
    requirement.evaluating_at = datetime.now()
    domain = validation["domain"]
    if domain and domain.owner_id:
        task = _current_process_task(db, requirement.id)
        if task:
            task.assignee = domain.owner_id
        notifier.notify(
            db,
            "requirement.review_assigned",
            "requirement",
            requirement.id,
            [domain.owner_id],
            f"需求评审指派：{requirement.requirement_code} {requirement.title}",
            f"业务域「{domain.name}」新需求待评审（六维评分）。",
            link=f"/requirements/{requirement.id}",
        )
    audit(db, "requirement", requirement.id, "create", user, {"code": requirement.requirement_code})
    publish(db, "requirement.registered", "requirement", requirement.id, {})
    if commit:
        db.commit()
    return requirement


def prepare_requirement(db: Session, user: AuthUser, fields: dict, idempotency_key: str) -> dict:
    validation = validate_fields(db, fields)
    if validation["missing"] or validation["errors"]:
        return {
            "ready_for_confirmation": False,
            "missing_fields": validation["missing"],
            "validation_errors": validation["errors"],
        }
    intent, token = mcp_intents.prepare(
        db, user, "register_it_requirement", validation["normalized"], idempotency_key
    )
    if intent.status == "executed":
        return {"ready_for_confirmation": True, "already_registered": True, "preview": intent.result_snapshot}
    domain = validation["domain"]
    return {
        "ready_for_confirmation": True,
        "confirmation_token": token,
        "confirmation_expires_at": intent.expires_at.isoformat(),
        "preview": {
            **validation["normalized"],
            "business_domain_name": domain.name if domain else None,
            "next_status": "evaluating",
            "next_status_name": "评估中",
        },
    }


def register_requirement(
    db: Session,
    user: AuthUser,
    confirmation_token: str,
    idempotency_key: str,
) -> tuple[dict, Requirement | None]:
    intent, replay = mcp_intents.require_prepared(
        db, user, "register_it_requirement", idempotency_key, confirmation_token
    )
    if replay:
        snapshot = dict(intent.result_snapshot or {})
        snapshot.update({"created": False, "idempotent_replay": True})
        return snapshot, None
    requirement = create_requirement(db, dict(intent.normalized_payload or {}), user, commit=False)
    result = {
        "requirement_code": requirement.requirement_code,
        "status": requirement.status,
        "status_name": "评估中",
        "created": True,
        "idempotent_replay": False,
        "registered_at": requirement.registered_at.isoformat() if requirement.registered_at else None,
    }
    mcp_intents.mark_executed(intent, "requirement", requirement.id, result)
    return result, requirement


def own_requirement(db: Session, user: AuthUser, requirement_code: str) -> Requirement:
    row = (
        db.query(Requirement)
        .filter(
            Requirement.requirement_code == str(requirement_code or "").strip(),
            Requirement.requester == user.id,
            Requirement.is_deleted.is_(False),
        )
        .first()
    )
    if not row:
        raise AppError("NOT_FOUND", "未找到该 IT 需求", 404)
    return row


def requirement_summary(db: Session, row: Requirement) -> dict:
    domain = db.get(BusinessDomain, row.business_domain_id)
    return {
        "requirement_code": row.requirement_code,
        "title": row.title,
        "req_type": row.req_type,
        "business_domain_name": domain.name if domain else None,
        "status": row.status,
        "registered_at": row.registered_at.isoformat() if row.registered_at else None,
        "expected_date": row.expected_date.isoformat() if row.expected_date else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
    }
