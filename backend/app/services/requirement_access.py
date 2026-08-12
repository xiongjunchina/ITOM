"""需求数据范围策略。

业务用户只能查看本人需求；业务 BDO 还能查看其被明确配置负责的业务服务域内需求。
详情、附件和跨单据关联必须复用同一策略，避免列表可见但详情或附件被拒绝。
"""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.rbac import ADMIN, AUDITOR, BDO, TEAM_ROLES
from app.models import AuthUser, BusinessDomain, Requirement
from app.services.rbac import effective_roles


def is_business_portal_only(db: Session, user: AuthUser) -> bool:
    """账号没有 IT/管理员/审计权限，应按业务门户数据范围授权。

    自定义 BDO/业务用户角色会同时保留自定义角色码和继承的内置角色码，
    因此不能再用 ``roles.issubset({REQUESTER, BDO})`` 判断，否则会把
    自定义 BDO 错当成 IT 内部账号并放开全量需求。
    """
    roles = effective_roles(db, user)
    privileged = {ADMIN, AUDITOR, *TEAM_ROLES}
    return bool(roles) and not roles.intersection(privileged)


def bdo_business_domain_ids(db: Session, user: AuthUser) -> list[str]:
    """返回当前 BDO 被业务服务域明确配置为业务 BDO 的服务域。"""
    if BDO not in effective_roles(db, user) or not user.person_id:
        return []
    return [
        row.id
        for row in db.query(BusinessDomain.id).filter(
            BusinessDomain.is_deleted.is_(False),
            BusinessDomain.business_bdo_id == user.person_id,
        )
    ]


def business_portal_requirement_filter(db: Session, user: AuthUser):
    """用于需求清单：本人登记，或本人作为业务 BDO 负责的服务域。"""
    domain_ids = bdo_business_domain_ids(db, user)
    if domain_ids:
        return or_(
            Requirement.requester == user.id,
            Requirement.business_domain_id.in_(domain_ids),
        )
    return Requirement.requester == user.id


def can_view_requirement(db: Session, user: AuthUser, requirement: Requirement) -> bool:
    """用于详情、附件和关系：与需求清单保持同一数据范围。"""
    if not is_business_portal_only(db, user):
        return True
    if requirement.requester == user.id:
        return True
    return requirement.business_domain_id in bdo_business_domain_ids(db, user)
