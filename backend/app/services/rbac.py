"""授权键展开：用户 → {直接角色, 组授予角色, 自定义角色继承的内置角色, group:组码}。

对齐 ServiceNow 最佳实践：角色优先挂组（人进组自动继承组的角色），直接授予保留为特例。
- API 权限守卫按内置角色判定（自定义角色经 base_role 继承生效）
- 状态机 allowed_roles / 流程步骤 default_role 可精确引用自定义角色码或 "group:组码"
"""
from sqlalchemy.orm import Session

from app.models import AuthUser, Role, UserGroup, UserGroupMember

GROUP_PREFIX = "group:"


def effective_roles(db: Session, user: AuthUser) -> set[str]:
    """有效角色 = 直接角色 ∪ 所属组授予的角色 ∪ 自定义角色继承的内置角色。"""
    roles: set[str] = set(user.roles or [])
    if user.person_id:
        groups = (
            db.query(UserGroup)
            .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
            .filter(
                UserGroupMember.person_id == user.person_id,
                UserGroupMember.is_deleted.is_(False),
                UserGroup.is_deleted.is_(False),
            )
            .all()
        )
        for g in groups:
            roles |= set(g.roles or [])
    if roles:
        customs = (
            db.query(Role)
            .filter(Role.code.in_(roles), Role.is_builtin.is_(False), Role.is_deleted.is_(False))
            .all()
        )
        roles |= {r.base_role for r in customs if r.base_role}
    return roles


def actor_keys(db: Session, user: AuthUser) -> set[str]:
    """授权判定键 = 有效角色 + group:组码（供状态机/流程精确引用组）。"""
    keys = effective_roles(db, user)
    if user.person_id:
        rows = (
            db.query(UserGroup.code)
            .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
            .filter(
                UserGroupMember.person_id == user.person_id,
                UserGroupMember.is_deleted.is_(False),
                UserGroup.is_deleted.is_(False),
            )
            .all()
        )
        keys |= {f"{GROUP_PREFIX}{code}" for (code,) in rows}
    return keys


def valid_role_codes(db: Session) -> set[str]:
    return {r.code for r in db.query(Role.code).filter(Role.is_deleted.is_(False))}
