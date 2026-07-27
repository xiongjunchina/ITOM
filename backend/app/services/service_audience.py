"""服务项服务对象范围判定。

服务对象是业务用户的可见范围。内部 IT 角色仍可查看完整服务目录；仅持
requester 角色的用户才需要按服务项配置的部门/员工范围过滤。
"""

from sqlalchemy.orm import Session

from app.core.rbac import REQUESTER
from app.models import AuthUser, Department, OrgMember, ServiceItem
from app.services.rbac import effective_roles


def is_requester_only(db: Session, user: AuthUser) -> bool:
    return effective_roles(db, user) == {REQUESTER}


def _member_in_department_scope(db: Session, member: OrgMember, department_id: str) -> bool:
    """部门范围包含当前部门及其下级部门，兼容组织架构树的层级选择。"""
    current_id = member.department_id
    visited: set[str] = set()
    while current_id and current_id not in visited:
        if current_id == department_id:
            return True
        visited.add(current_id)
        department = db.get(Department, current_id)
        if not department or department.is_deleted or not department.active:
            return False
        current_id = department.parent_id
    return False


def service_item_visible_to_user(db: Session, item: ServiceItem, user: AuthUser) -> bool:
    """判断当前用户是否可以看到/申请该服务项。

    未结构化的历史文本服务对象按旧版“全体员工”行为放行，避免升级后误隐藏；
    管理员和 IT 内部角色不受业务用户服务对象范围限制。
    """
    if not is_requester_only(db, user) or (item.target_audience_mode or "all") != "custom":
        return True
    if not user.person_id:
        return False
    member = db.get(OrgMember, user.person_id)
    if not member or member.is_deleted or member.status != "在岗":
        return False
    for ref in item.target_audience_refs or []:
        if not isinstance(ref, dict):
            continue
        if ref.get("type") == "member" and ref.get("id") == member.id:
            return True
        if ref.get("type") == "department" and _member_in_department_scope(db, member, str(ref.get("id") or "")):
            return True
    return False
