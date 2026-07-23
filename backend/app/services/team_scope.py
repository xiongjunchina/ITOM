"""团队管理统一人员口径：仅 IT 团队，不把全公司人员混入统计与选择器。"""

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AuthUser, Department, OrgMember, Role, UserGroup, UserGroupMember
from app.services.org_settings import expand_department_ids, get_org_settings


def _is_it_role(code: str | None) -> bool:
    return bool(code and (code == "cio" or code == "is_mgr" or code.startswith("it_")))


def it_member_ids(db: Session, active_only: bool = True) -> set[str]:
    """返回 IT 团队人员 ID。

    主口径是 department.dept_type=it；为兼容未补部门的存量账号，持有 IT 内置角色
    （含自定义角色的 base_role）或加入授予 IT 角色用户组的人员也纳入。
    """
    settings = get_org_settings(db)
    configured_roots = settings.digital_team_department_ids or []
    if configured_roots:
        department_ids = expand_department_ids(db, configured_roots, settings.digital_team_include_children)
        query = db.query(OrgMember).filter(
            OrgMember.is_deleted.is_(False), OrgMember.department_id.in_(department_ids or {"-"})
        )
        if active_only:
            query = query.filter(OrgMember.status == "在岗")
        return {m.id for m in query}

    query = db.query(OrgMember).join(Department, Department.id == OrgMember.department_id).filter(
        OrgMember.is_deleted.is_(False), Department.is_deleted.is_(False), Department.dept_type == "it"
    )
    if active_only:
        query = query.filter(OrgMember.status == "在岗")
    result = {m.id for m in query}

    role_bases = {r.code: r.base_role for r in db.query(Role).filter(Role.is_deleted.is_(False))}
    for user in db.query(AuthUser).filter(AuthUser.person_id.isnot(None), AuthUser.is_deleted.is_(False)):
        roles = user.roles or []
        if any(_is_it_role(role_bases.get(code) or code) for code in roles):
            result.add(user.person_id)

    group_rows = (
        db.query(UserGroupMember.person_id, UserGroup.roles)
        .join(UserGroup, UserGroup.id == UserGroupMember.group_id)
        .filter(UserGroupMember.is_deleted.is_(False), UserGroup.is_deleted.is_(False))
    )
    for person_id, roles in group_rows:
        if any(_is_it_role(role_bases.get(code) or code) for code in (roles or [])):
            result.add(person_id)

    if active_only and result:
        active = {m.id for m in db.query(OrgMember.id).filter(
            OrgMember.id.in_(result), OrgMember.is_deleted.is_(False), OrgMember.status == "在岗"
        )}
        result &= active
    return result


def is_it_member(db: Session, person_id: str | None) -> bool:
    return bool(person_id and person_id in it_member_ids(db))


def digital_team_scope_configured(db: Session) -> bool:
    """是否已由管理员配置数字化团队根部门。"""
    return bool(get_org_settings(db).digital_team_department_ids)


def require_it_member_if_configured(db: Session, person_id: str | None, label: str = "人员") -> None:
    """配置了统一口径后强制校验；未配置时兼容历史数据录入流程。"""
    if not person_id:
        return
    if digital_team_scope_configured(db) and not is_it_member(db, person_id):
        raise AppError("NOT_IT_TEAM_MEMBER", f"{label}只能选择数字化团队成员")


def require_it_member(db: Session, person_id: str | None, label: str = "人员") -> None:
    """校验业务负责人/处理人等人员选择必须落在数字化团队范围内。"""
    if not is_it_member(db, person_id):
        raise AppError("NOT_IT_TEAM_MEMBER", f"{label}只能选择数字化团队成员")


def require_it_members(db: Session, person_ids: list[str] | set[str], label: str = "人员") -> None:
    """批量校验人员选择，避免仅依赖前端 scope 参数。"""
    allowed = it_member_ids(db)
    invalid = {person_id for person_id in person_ids if person_id} - allowed
    if invalid:
        raise AppError("NOT_IT_TEAM_MEMBER", f"{label}只能选择数字化团队成员")
