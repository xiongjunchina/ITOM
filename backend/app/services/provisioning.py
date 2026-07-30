"""账号开通（JIT Provisioning）与认证源适配器接口。

设计（docs/06）：认证源经适配器认证成功后调用 provision_user()——
find-or-create 账号与人员档案，仅在账号首次创建时按开通规则赋默认角色；
之后角色完全自由增减，绝不与部门/规则绑死。

当前仅实现 local（管理员建账号也走同一默认角色逻辑）；
AD 域 / 飞书 / 短信 / 微信适配器在上线前对接（AuthProvider 协议已定）。
"""
import re

from typing import Protocol

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models import AuthUser, Department, OrgMember, ProvisionRule
from app.services.secrets_store import encrypt_secret
from app.services.team_scope import is_it_member


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


def _department_path_looks_like_it(db: Session, person: OrgMember) -> bool:
    """Conservative fallback for synced trees whose dept_type is not classified yet.

    Feishu sync intentionally keeps local department classifications editable. Until an
    administrator classifies a newly synced tree, a department path explicitly named
    Information Technology/Digitalization must still be treated as IT for the automatic
    business-user branch; otherwise an IT employee could be auto-provisioned as requester.
    """
    department = person.department
    seen: set[str] = set()
    while department and department.id not in seen:
        seen.add(department.id)
        name = (department.name or "").strip().lower()
        if "信息技术" in name or "信息化" in name or "数字化" in name or re.search(r"\bit\b", name):
            return True
        department = db.get(Department, department.parent_id) if department.parent_id else None
    return False


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


def provision_business_feishu_user(
    db: Session,
    *,
    external_id: str,
    display_name: str,
    email: str | None = None,
    mobile: str | None = None,
) -> AuthUser | None:
    """为已同步的非 IT 飞书人员自动创建或绑定业务用户。

    这是飞书登录专用的安全窄入口：人员必须已经存在于组织同步结果中，且不属于
    数字化团队；账号名取邮箱前缀，任何人员/用户名/飞书身份冲突都回退到人工审批。
    返回 ``None`` 表示不能安全自动开户，调用方应继续原有待审批流程。
    """
    if not external_id or not email or "@" not in email:
        return None
    normalized_email = email.strip().lower()
    local_part, _, domain = normalized_email.partition("@")
    if not local_part or not domain or len(local_part) > 64 or not re.fullmatch(r"[A-Za-z0-9_.-]+", local_part):
        return None

    from sqlalchemy import func, or_

    matches = (
        db.query(OrgMember)
        .filter(
            OrgMember.is_deleted.is_(False),
            or_(
                (OrgMember.external_source == "feishu") & (OrgMember.external_id == external_id),
                OrgMember.feishu_user_id == external_id,
                func.lower(OrgMember.email) == normalized_email,
            ),
        )
        .all()
    )
    exact_matches = [
        row for row in matches
        if (row.external_source == "feishu" and row.external_id == external_id)
        or row.feishu_user_id == external_id
    ]
    if len({row.id for row in exact_matches}) > 1:
        return None
    if exact_matches:
        person = exact_matches[0]
    else:
        email_matches = [row for row in matches if (row.email or "").strip().lower() == normalized_email]
        if len({row.id for row in email_matches}) != 1:
            return None
        person = email_matches[0]
    # Automatic opening is limited to an already synchronized Feishu person. A
    # manually created local person that merely shares an email must continue through
    # the explicit onboarding approval flow.
    if (
        not person
        or person.external_source != "feishu"
        or is_it_member(db, person.id)
        or _department_path_looks_like_it(db, person)
    ):
        return None

    # 任何既有飞书绑定冲突都不自动接管。
    external_user = (
        db.query(AuthUser)
        .filter(AuthUser.external_id == external_id, AuthUser.is_deleted.is_(False))
        .first()
    )
    if external_user and external_user.person_id not in {None, person.id}:
        return None

    user = db.query(AuthUser).filter(AuthUser.person_id == person.id, AuthUser.is_deleted.is_(False)).first()
    if user and user.external_id not in {None, external_id}:
        return None
    if not user:
        user = db.query(AuthUser).filter(AuthUser.username == local_part, AuthUser.is_deleted.is_(False)).first()
        if user and user.person_id not in {None, person.id}:
            return None
        if user and user.external_id not in {None, external_id}:
            return None

    if not user:
        user = AuthUser(
            username=local_part,
            password_hash=hash_password(settings.business_initial_password),
            auth_source="feishu",
            external_id=external_id,
            person_id=person.id,
            roles=["requester"],
            is_active=True,
            password_set_at=None,
            initial_password_ciphertext=encrypt_secret(settings.business_initial_password),
        )
        db.add(user)
        db.flush()
    else:
        user.external_id = external_id
        user.auth_source = "feishu"
        user.person_id = person.id
        if not user.roles:
            user.roles = ["requester"]

    person.name = display_name or person.name
    person.email = email or person.email
    person.mobile = mobile or person.mobile
    return user
