"""服务项动态表单版本、规范化与权威校验。"""

from datetime import date, datetime
import hashlib
import json
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Department, OrgMember, ServiceItem, ServiceItemFormVersion


SUPPORTED_TYPES = {"string", "integer", "number", "boolean", "array"}
FIELD_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
DEFAULT_SERVICE_REQUEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "description"],
    "properties": {
        "title": {
            "type": "string",
            "title": "标题",
            "minLength": 2,
            "maxLength": 200,
        },
        "description": {
            "type": "string",
            "title": "诉求说明",
            "minLength": 1,
            "maxLength": 2000,
            "x-itom-field-type": "long_text",
        },
        "priority": {
            "type": "string",
            "title": "紧急程度",
            "enum": ["P1", "P2", "P3", "P4"],
            "default": "P3",
        },
        "suspected_major_impact": {
            "type": "boolean",
            "title": "疑似影响多人",
            "default": False,
        },
    },
}


def canonical_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def schema_checksum(schema: dict) -> str:
    return hashlib.sha256(canonical_json(schema).encode()).hexdigest()


def validate_schema(schema: dict) -> dict:
    """校验并返回可持久化的 JSON Schema 子集。"""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise AppError("INVALID_FORM_SCHEMA", "表单 schema.type 必须为 object")
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise AppError("INVALID_FORM_SCHEMA", "表单必须包含 properties")
    required = schema.get("required") or []
    if not isinstance(required, list) or any(code not in properties for code in required):
        raise AppError("INVALID_FORM_SCHEMA", "required 必须引用已定义字段")
    for core in ("title", "description"):
        if core not in properties or core not in required:
            raise AppError("INVALID_FORM_SCHEMA", f"服务请求表单必须包含必填字段 {core}")
    for code, definition in properties.items():
        if not FIELD_CODE.fullmatch(code) or not isinstance(definition, dict):
            raise AppError("INVALID_FORM_SCHEMA", f"非法字段定义：{code}")
        if definition.get("type") not in SUPPORTED_TYPES:
            raise AppError("INVALID_FORM_SCHEMA", f"字段 {code} 类型不受支持")
        if not str(definition.get("title") or "").strip():
            raise AppError("INVALID_FORM_SCHEMA", f"字段 {code} 缺少 title")
        if "enum" in definition and not isinstance(definition["enum"], list):
            raise AppError("INVALID_FORM_SCHEMA", f"字段 {code} 的 enum 必须为数组")
        if definition.get("type") == "array":
            items = definition.get("items") or {}
            if items.get("type") not in {"string", "integer", "number"}:
                raise AppError("INVALID_FORM_SCHEMA", f"字段 {code} 的数组元素类型不受支持")
    normalized = dict(schema)
    normalized["$schema"] = schema.get("$schema") or "https://json-schema.org/draft/2020-12/schema"
    normalized["additionalProperties"] = bool(schema.get("additionalProperties", False))
    normalized["required"] = list(dict.fromkeys(required))
    return normalized


def ensure_default_form(db: Session, item: ServiceItem, published_by: str | None = None) -> ServiceItemFormVersion:
    if item.active_form_version_id:
        row = db.get(ServiceItemFormVersion, item.active_form_version_id)
        if row and not row.is_deleted and row.status == "published":
            return row
    existing = (
        db.query(ServiceItemFormVersion)
        .filter(
            ServiceItemFormVersion.service_item_id == item.id,
            ServiceItemFormVersion.status == "published",
            ServiceItemFormVersion.is_deleted.is_(False),
        )
        .order_by(ServiceItemFormVersion.version.desc())
        .first()
    )
    if existing:
        item.active_form_version_id = existing.id
        return existing
    schema = validate_schema(DEFAULT_SERVICE_REQUEST_SCHEMA)
    row = ServiceItemFormVersion(
        service_item_id=item.id,
        version=1,
        status="published",
        schema=schema,
        published_by=published_by,
        published_at=datetime.now(),
        checksum=schema_checksum(schema),
    )
    db.add(row)
    db.flush()
    item.active_form_version_id = row.id
    return row


def create_draft(db: Session, item: ServiceItem, schema: dict) -> ServiceItemFormVersion:
    normalized = validate_schema(schema)
    latest = db.query(func.max(ServiceItemFormVersion.version)).filter(
        ServiceItemFormVersion.service_item_id == item.id,
        ServiceItemFormVersion.is_deleted.is_(False),
    ).scalar()
    row = ServiceItemFormVersion(
        service_item_id=item.id,
        version=(latest or 0) + 1,
        status="draft",
        schema=normalized,
        checksum=schema_checksum(normalized),
    )
    db.add(row)
    db.flush()
    return row


def publish_version(
    db: Session,
    item: ServiceItem,
    version: int,
    actor_id: str,
) -> ServiceItemFormVersion:
    row = (
        db.query(ServiceItemFormVersion)
        .filter(
            ServiceItemFormVersion.service_item_id == item.id,
            ServiceItemFormVersion.version == version,
            ServiceItemFormVersion.is_deleted.is_(False),
        )
        .first()
    )
    if not row:
        raise AppError("NOT_FOUND", "表单版本不存在", 404)
    if row.status not in {"draft", "published"}:
        raise AppError("FORM_VERSION_RETIRED", "已退役表单版本不可重新发布")
    for current in db.query(ServiceItemFormVersion).filter(
        ServiceItemFormVersion.service_item_id == item.id,
        ServiceItemFormVersion.status == "published",
        ServiceItemFormVersion.id != row.id,
        ServiceItemFormVersion.is_deleted.is_(False),
    ):
        current.status = "retired"
    row.status = "published"
    row.published_by = actor_id
    row.published_at = datetime.now()
    item.active_form_version_id = row.id
    db.flush()
    return row


def active_form(db: Session, item: ServiceItem) -> ServiceItemFormVersion:
    row = db.get(ServiceItemFormVersion, item.active_form_version_id) if item.active_form_version_id else None
    if not row or row.is_deleted or row.status != "published":
        raise AppError("SERVICE_FORM_UNAVAILABLE", "服务项尚未发布可用表单")
    return row


def form_row(row: ServiceItemFormVersion) -> dict:
    return {
        "id": row.id,
        "version": row.version,
        "status": row.status,
        "schema": row.schema,
        "checksum": row.checksum,
        "published_at": row.published_at.isoformat() if row.published_at else None,
    }


def _type_ok(expected: str, value) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    return False


def _conditional_required(definition: dict, answers: dict) -> bool:
    condition = definition.get("x-required-if")
    if not isinstance(condition, dict):
        return False
    field = condition.get("field")
    if "equals" in condition:
        return answers.get(field) == condition.get("equals")
    if "in" in condition and isinstance(condition["in"], list):
        return answers.get(field) in condition["in"]
    return False


def validate_answers(db: Session, schema: dict, answers: dict | None) -> dict:
    """返回 normalized/missing/errors；不直接落库。"""
    answers = dict(answers or {})
    properties = schema.get("properties") or {}
    normalized: dict = {}
    errors: list[dict] = []
    missing: list[dict] = []

    if not schema.get("additionalProperties", False):
        for code in answers.keys() - properties.keys():
            errors.append({"code": code, "message": "字段未在当前表单版本中定义"})

    required = set(schema.get("required") or [])
    required.update(
        code for code, definition in properties.items()
        if _conditional_required(definition, answers)
    )
    for code, definition in properties.items():
        value = answers.get(code, definition.get("default"))
        if value is None or value == "" or value == []:
            if code in required:
                missing.append({"code": code, "title": definition.get("title", code)})
            continue
        expected = definition.get("type")
        if not _type_ok(expected, value):
            errors.append({"code": code, "message": f"必须是 {expected} 类型"})
            continue
        if "enum" in definition and value not in definition["enum"]:
            errors.append({"code": code, "message": "取值不在允许选项中"})
            continue
        if isinstance(value, str):
            if len(value) < int(definition.get("minLength", 0)):
                errors.append({"code": code, "message": f"长度不能少于 {definition['minLength']}"})
                continue
            if "maxLength" in definition and len(value) > int(definition["maxLength"]):
                errors.append({"code": code, "message": f"长度不能超过 {definition['maxLength']}"})
                continue
            try:
                if definition.get("format") == "date":
                    date.fromisoformat(value)
                elif definition.get("format") == "date-time":
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append({"code": code, "message": "日期格式无效"})
                continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in definition and value < definition["minimum"]:
                errors.append({"code": code, "message": f"不能小于 {definition['minimum']}"})
                continue
            if "maximum" in definition and value > definition["maximum"]:
                errors.append({"code": code, "message": f"不能大于 {definition['maximum']}"})
                continue
        if isinstance(value, list):
            if "minItems" in definition and len(value) < definition["minItems"]:
                errors.append({"code": code, "message": f"至少选择 {definition['minItems']} 项"})
                continue
            if "maxItems" in definition and len(value) > definition["maxItems"]:
                errors.append({"code": code, "message": f"最多选择 {definition['maxItems']} 项"})
                continue
            item_type = (definition.get("items") or {}).get("type")
            if item_type and any(not _type_ok(item_type, entry) for entry in value):
                errors.append({"code": code, "message": "数组元素类型无效"})
                continue

        field_type = definition.get("x-itom-field-type")
        if field_type == "person":
            member = db.get(OrgMember, str(value))
            if not member or member.is_deleted or member.status != "在岗":
                errors.append({"code": code, "message": "所选人员不存在或不可用"})
                continue
            allowed_members = definition.get("x-allowed-member-ids") or []
            allowed_departments = definition.get("x-allowed-department-ids") or []
            if allowed_members or allowed_departments:
                if member.id not in allowed_members and member.department_id not in allowed_departments:
                    errors.append({"code": code, "message": "所选人员不在允许范围"})
                    continue
        elif field_type == "department":
            department = db.get(Department, str(value))
            if not department or department.is_deleted or not department.active:
                errors.append({"code": code, "message": "所选部门不存在或不可用"})
                continue
            allowed = definition.get("x-allowed-department-ids") or []
            if allowed and department.id not in allowed:
                errors.append({"code": code, "message": "所选部门不在允许范围"})
                continue
        normalized[code] = value.strip() if isinstance(value, str) else value
    return {"normalized": normalized, "missing": missing, "errors": errors}


def masked_preview(schema: dict, normalized: dict) -> dict:
    properties = schema.get("properties") or {}
    return {
        code: ("***" if properties.get(code, {}).get("x-sensitive") else value)
        for code, value in normalized.items()
    }
