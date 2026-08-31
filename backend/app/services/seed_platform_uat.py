"""仅供本地 Docker 验收的平台运营合成数据。

数据依赖 ``seed_table_uat`` 创建的虚构服务项、需求和人员，不复制 IDC
数据，也不会从应用启动或生产部署流程自动执行。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    AuthUser,
    OrgMember,
    PlatformCapacityCommitment,
    PlatformCapacityPlan,
    PlatformDemandProfile,
    PlatformServiceProfile,
    Requirement,
    ServiceItem,
)
from app.services.seed_table_uat import assert_local_uat_database, seed_table_uat


PLATFORM_UAT_MARKER = "【平台运营UAT】"
PLATFORM_UAT_USER = "platform_uat_cio_disabled"


def _quarter(day: date) -> str:
    return f"{day.year}-Q{((day.month - 1) // 3) + 1}"


def _digest(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _upsert(db: Session, model, lookup: dict, values: dict):
    row = db.query(model).filter_by(**lookup).first()
    if row is None:
        row = model(**{**values, **lookup})
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    row.is_deleted = False
    row.is_example = False
    db.flush()
    return row


def seed_platform_uat(db: Session) -> dict[str, int]:
    """创建可重复执行、可清理的平台服务/需求/容量验收样例。"""

    assert_local_uat_database(str(db.get_bind().url))
    seed_table_uat(db)

    service_item = db.query(ServiceItem).filter(ServiceItem.item_code == "SI-UAT-TABLE").one()
    requirements = db.query(Requirement).filter(
        Requirement.requirement_code.like("RQ-UAT-TABLE-%"),
        Requirement.is_deleted.is_(False),
    ).order_by(Requirement.requirement_code).limit(6).all()
    owner = db.query(OrgMember).filter(OrgMember.employee_no == "UAT-TABLE-001").one()
    actor = _upsert(
        db,
        AuthUser,
        {"username": PLATFORM_UAT_USER},
        {
            "password_hash": "!disabled-local-uat-account!",
            "person_id": owner.id,
            "roles": ["cio"],
            "preferences": {},
            "is_active": False,
        },
    )

    _upsert(
        db,
        PlatformServiceProfile,
        {"service_item_id": service_item.id},
        {
            "owner_id": owner.id,
            "lifecycle": "active",
            "value_proposition": "为业务域提供可复用的跨系统访问与账号权限能力",
            "management_scope": {"scope_note": "仅用于本地平台运营 P0 验收"},
            "created_by": actor.id,
            "updated_by": actor.id,
        },
    )

    demand_profiles: list[PlatformDemandProfile] = []
    period = _quarter(date.today())
    for index, requirement in enumerate(requirements, start=1):
        demand_profiles.append(_upsert(
            db,
            PlatformDemandProfile,
            {"requirement_id": requirement.id},
            {
                "service_item_id": service_item.id,
                "business_domain_id": requirement.business_domain_id,
                "demand_class": ("business", "product", "technology", "reliability", "compliance")[(index - 1) % 5],
                "expected_outcome": f"{PLATFORM_UAT_MARKER}缩短需求 {index} 的交付周期并形成可核验结果",
                "target_quarter": period,
                "capacity_class": ("small", "medium", "large")[index % 3],
                "created_by": actor.id,
                "updated_by": actor.id,
            },
        ))

    approved_plan_payload = {
        "service_item_id": service_item.id,
        "period": period,
        "version": 1,
        "status": "superseded",
        "gross_days": Decimal("40.00"),
        "planned_unavailable_days": Decimal("2.00"),
        "bau_reserve_days": Decimal("4.00"),
        "risk_buffer_days": Decimal("2.00"),
        "net_days": Decimal("32.00"),
        "notes": f"{PLATFORM_UAT_MARKER}已批准基线，已由修订版替代",
        "created_by": actor.id,
        "updated_by": actor.id,
        "approved_by": actor.id,
        "approval_reason": "本地季度容量基线验收",
        "approved_at": datetime.now(),
        "request_digest": _digest({"period": period, "version": 1}),
        "previous_version_id": None,
    }
    version_one = _upsert(
        db,
        PlatformCapacityPlan,
        {"created_by": actor.id, "idempotency_key": "platform-uat-plan-v1"},
        approved_plan_payload,
    )
    version_two = _upsert(
        db,
        PlatformCapacityPlan,
        {"created_by": actor.id, "idempotency_key": "platform-uat-plan-v2"},
        {
            "service_item_id": service_item.id,
            "period": period,
            "version": 2,
            "status": "draft",
            "gross_days": Decimal("48.00"),
            "planned_unavailable_days": Decimal("2.00"),
            "bau_reserve_days": Decimal("5.00"),
            "risk_buffer_days": Decimal("3.00"),
            "net_days": Decimal("38.00"),
            "notes": f"{PLATFORM_UAT_MARKER}当前季度容量修订草稿",
            "created_by": actor.id,
            "updated_by": actor.id,
            "approved_by": None,
            "approval_reason": None,
            "approved_at": None,
            "request_digest": _digest({"period": period, "version": 2}),
            "previous_version_id": version_one.id,
        },
    )

    commitment_specs = (
        (version_one, demand_profiles[0], "v1-demand", "需求交付承诺", "demand", "18.00", "demand", "grow"),
        (version_one, None, "v1-run", "平台可靠性保障", "reliability", "6.00", "run", "run"),
        (version_two, demand_profiles[1], "v2-demand", "重点需求交付", "demand", "20.00", "build", "transform"),
        (version_two, None, "v2-roadmap", "平台产品路线图", "roadmap", "8.00", "build", "grow"),
        (version_two, None, "v2-enable", "FDSE 赋能与知识沉淀", "enablement", "4.00", "run", "run"),
    )
    for plan, demand, key, title, commitment_type, days, stage, intent in commitment_specs:
        subject_type = "requirement" if demand else commitment_type
        subject_id = demand.requirement_id if demand else None
        _upsert(
            db,
            PlatformCapacityCommitment,
            {"created_by": actor.id, "idempotency_key": f"platform-uat-{key}"},
            {
                "plan_id": plan.id,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "title": f"{PLATFORM_UAT_MARKER}{title}",
                "commitment_type": commitment_type,
                "capacity_days": Decimal(days),
                "lifecycle_stage": stage,
                "investment_intent": intent,
                "owner_id": owner.id,
                "status": "planned",
                "updated_by": actor.id,
                "request_digest": _digest({"plan": plan.id, "key": key}),
                "over_capacity_reason": None,
                "over_capacity_approved_by": None,
                "over_capacity_approved_at": None,
            },
        )

    db.commit()
    return {"services": 1, "demands": len(demand_profiles), "plans": 2, "commitments": len(commitment_specs)}


def cleanup_platform_uat(db: Session) -> dict[str, int]:
    """软删除本地平台运营样例，不触碰其他本地或生产数据。"""

    assert_local_uat_database(str(db.get_bind().url))
    actor = db.query(AuthUser).filter(AuthUser.username == PLATFORM_UAT_USER).first()
    if actor is None:
        return {"services": 0, "demands": 0, "plans": 0, "commitments": 0, "users": 0}
    plans = db.query(PlatformCapacityPlan.id).filter(PlatformCapacityPlan.created_by == actor.id).all()
    plan_ids = [row[0] for row in plans]
    commitments = db.query(PlatformCapacityCommitment).filter(
        PlatformCapacityCommitment.plan_id.in_(plan_ids),
        PlatformCapacityCommitment.is_deleted.is_(False),
    ).update({PlatformCapacityCommitment.is_deleted: True}, synchronize_session=False) if plan_ids else 0
    plan_count = db.query(PlatformCapacityPlan).filter(
        PlatformCapacityPlan.created_by == actor.id,
        PlatformCapacityPlan.is_deleted.is_(False),
    ).update({PlatformCapacityPlan.is_deleted: True}, synchronize_session=False)
    demands = db.query(PlatformDemandProfile).filter(
        PlatformDemandProfile.created_by == actor.id,
        PlatformDemandProfile.is_deleted.is_(False),
    ).update({PlatformDemandProfile.is_deleted: True}, synchronize_session=False)
    services = db.query(PlatformServiceProfile).filter(
        PlatformServiceProfile.created_by == actor.id,
        PlatformServiceProfile.is_deleted.is_(False),
    ).update({PlatformServiceProfile.is_deleted: True}, synchronize_session=False)
    users = db.query(AuthUser).filter(
        AuthUser.id == actor.id,
        AuthUser.is_deleted.is_(False),
    ).update({AuthUser.is_deleted: True}, synchronize_session=False)
    db.commit()
    return {"services": services, "demands": demands, "plans": plan_count, "commitments": commitments, "users": users}
