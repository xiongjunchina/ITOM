"""账号开通（JIT Provisioning）与认证源适配器接口。

设计（docs/06）：认证源经适配器认证成功后调用 provision_user()——
find-or-create 账号与人员档案，仅在账号首次创建时按开通规则赋默认角色；
之后角色完全自由增减，绝不与部门/规则绑死。

当前仅实现 local（管理员建账号也走同一默认角色逻辑）；
AD 域 / 飞书 / 短信 / 微信适配器在上线前对接（AuthProvider 协议已定）。
"""
from typing import Protocol

from sqlalchemy.orm import Session

from app.models import AuthUser, Department, OrgMember, ProvisionRule


class ProvisionProfile:
    """认证源返回的用户画像（各适配器负责映射到该结构）。"""

    def __init__(
        self,
        username: str,
        name: str,
        name_en: str | None = None,
        email: str | None = None,
        mobile: str | None = None,
        department_external_id: str | None = None,
        external_id: str | None = None,
    ):
        self.username = username
        self.name = name
        self.name_en = name_en
        self.email = email
        self.mobile = mobile
        self.department_external_id = department_external_id
        self.external_id = external_id


class AuthProvider(Protocol):
    """认证源适配器协议：authenticate 成功返回 ProvisionProfile，失败返回 None。"""

    source: str

    def authenticate(self, credential: dict) -> ProvisionProfile | None: ...


# 适配器注册表：上线前按需注册 ADProvider/FeishuProvider/SmsProvider/WechatProvider
PROVIDERS: dict[str, AuthProvider] = {}


def default_roles_for(db: Session, department_id: str | None) -> list[str]:
    """按开通规则解析默认角色：department 精确规则优先，其次 dept_type，命中即停。"""
    if not department_id:
        return ["requester"]
    dept = db.get(Department, department_id)
    if not dept:
        return ["requester"]
    rules = (
        db.query(ProvisionRule)
        .filter(ProvisionRule.active.is_(True), ProvisionRule.is_deleted.is_(False))
        .order_by(ProvisionRule.sort)
        .all()
    )
    for r in rules:
        if r.match_type == "department" and r.match_value == dept.id:
            return list(r.default_roles or [])
    for r in rules:
        if r.match_type == "dept_type" and r.match_value == dept.dept_type:
            return list(r.default_roles or [])
    return ["requester"]


def provision_user(db: Session, source: str, profile: ProvisionProfile) -> AuthUser:
    """find-or-create 账号+人员档案。仅首次创建赋默认角色；已存在账号只同步档案。"""
    user = None
    if profile.external_id:
        user = (
            db.query(AuthUser)
            .filter(
                AuthUser.auth_source == source,
                AuthUser.external_id == profile.external_id,
                AuthUser.is_deleted.is_(False),
            )
            .first()
        )
    if not user:
        user = (
            db.query(AuthUser)
            .filter(AuthUser.username == profile.username, AuthUser.is_deleted.is_(False))
            .first()
        )

    dept = None
    if profile.department_external_id:
        dept = (
            db.query(Department)
            .filter(Department.external_id == profile.department_external_id, Department.is_deleted.is_(False))
            .first()
        )

    if user:
        # 已有账号：同步人员档案，不动角色
        if user.person:
            person = user.person
            person.name = profile.name or person.name
            person.name_en = profile.name_en or person.name_en
            person.email = profile.email or person.email
            person.mobile = profile.mobile or person.mobile
            if dept:
                person.department_id = dept.id
        return user

    person = OrgMember(
        name=profile.name,
        name_en=profile.name_en,
        email=profile.email,
        mobile=profile.mobile,
        department_id=dept.id if dept else None,
        external_source=source if source != "local" else None,
        external_id=profile.external_id,
    )
    db.add(person)
    db.flush()
    user = AuthUser(
        username=profile.username,
        password_hash="!external!",  # 外部认证源账号不可本地密码登录
        auth_source=source,
        external_id=profile.external_id,
        person_id=person.id,
        roles=default_roles_for(db, person.department_id),
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user
