"""授权键展开：用户 → {内置角色, 自定义角色, 继承的内置角色, group:组码}。

- API 权限守卫按内置角色判定（自定义角色经 base_role 继承生效）
- 状态机 allowed_roles / 流程步骤 default_role 可精确引用自定义角色码或 "group:组码"
"""
from sqlalchemy.orm import Session

from app.models import AuthUser, Role, UserGroup, UserGroupMember

GROUP_PREFIX = "group:"


def actor_keys(db: Session, user: AuthUser) -> set[str]:
    keys: set[str] = set(user.roles or [])
    if keys:
        customs = (
            db.query(Role)
            .filter(Role.code.in_(keys), Role.is_builtin.is_(False), Role.is_deleted.is_(False))
            .all()
        )
        keys |= {r.base_role for r in customs if r.base_role}
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
