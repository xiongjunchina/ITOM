"""组织架构同步引擎（docs/06 §四）：人员/部门主数据以飞书为准（Source of Truth）。

- apply_org_snapshot() 与提供方无关：飞书/AD 适配器只需产出 OrgSnapshot
- 幂等 upsert（按 source+external_id 匹配）；同步字段"外部赢"覆盖本地值
- 外部消失的人员 → 标记离职（保留历史）；消失的部门 → 停用
- 本地手工记录（external_source 为空）不受同步影响
- 本地扩展字段（岗位/技能/备注/部门类型）不被同步触碰——飞书管 HR 基础信息，ITOM 管 IT 扩展
"""
import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import Department, OrgMember

logger = logging.getLogger("aom.org_sync")

# 已同步记录在本系统锁定的字段（以飞书为准）；其余为本地扩展可编辑
MEMBER_SYNCED_FIELDS = {
    "name", "name_en", "employee_no", "gender", "birth_date", "employment_type",
    "supervisor_id", "work_location", "department_id", "email", "mobile", "hire_date", "status",
}
MEMBER_LOCAL_FIELDS = {"position_id", "skills", "remarks"}
DEPT_SYNCED_FIELDS = {"name", "parent_id", "sort", "active"}
DEPT_LOCAL_FIELDS = {"dept_type"}


@dataclass
class DeptIn:
    external_id: str
    name: str
    parent_external_id: str | None = None
    sort: int = 0


@dataclass
class MemberIn:
    external_id: str
    name: str
    name_en: str | None = None
    employee_no: str | None = None
    gender: str | None = None
    employment_type: str | None = None
    work_location: str | None = None
    email: str | None = None
    mobile: str | None = None
    department_external_id: str | None = None
    leader_external_id: str | None = None
    status: str = "在岗"


@dataclass
class OrgSnapshot:
    departments: list[DeptIn] = field(default_factory=list)
    members: list[MemberIn] = field(default_factory=list)


class OrgSyncProvider:
    """适配器协议：fetch() 返回完整组织快照。飞书适配器上线前注册进 SYNC_PROVIDERS。"""

    source: str

    def fetch(self) -> OrgSnapshot: ...


# 上线前注册：SYNC_PROVIDERS["feishu"] = FeishuOrgProvider(app_id, app_secret)
SYNC_PROVIDERS: dict[str, OrgSyncProvider] = {}


def apply_org_snapshot(db: Session, source: str, snapshot: OrgSnapshot) -> dict:
    stats = {"dept_created": 0, "dept_updated": 0, "dept_deactivated": 0,
             "member_created": 0, "member_updated": 0, "member_left": 0}

    # ---- 部门：第一遍 upsert，第二遍挂父子 ----
    dept_by_ext: dict[str, Department] = {}
    for d in snapshot.departments:
        row = (
            db.query(Department)
            .filter(Department.external_source == source, Department.external_id == d.external_id,
                    Department.is_deleted.is_(False))
            .first()
        )
        if row:
            changed = row.name != d.name or row.sort != d.sort or not row.active
            row.name, row.sort, row.active = d.name, d.sort, True
            stats["dept_updated"] += int(changed)
        else:
            row = Department(
                code=f"F{d.external_id[-24:]}", name=d.name, dept_type="business",
                external_source=source, external_id=d.external_id, sort=d.sort,
            )
            db.add(row)
            stats["dept_created"] += 1
        dept_by_ext[d.external_id] = row
    db.flush()
    for d in snapshot.departments:
        row = dept_by_ext[d.external_id]
        parent = dept_by_ext.get(d.parent_external_id) if d.parent_external_id else None
        row.parent_id = parent.id if parent else None
    # 外部消失的部门 → 停用
    seen_ext = set(dept_by_ext.keys())
    for row in db.query(Department).filter(
        Department.external_source == source, Department.is_deleted.is_(False), Department.active.is_(True)
    ):
        if row.external_id not in seen_ext:
            row.active = False
            stats["dept_deactivated"] += 1

    # ---- 人员：upsert（外部赢），第二遍挂上级 ----
    member_by_ext: dict[str, OrgMember] = {}
    for m in snapshot.members:
        row = (
            db.query(OrgMember)
            .filter(OrgMember.external_source == source, OrgMember.external_id == m.external_id,
                    OrgMember.is_deleted.is_(False))
            .first()
        )
        dept = dept_by_ext.get(m.department_external_id) if m.department_external_id else None
        values = {
            "name": m.name, "name_en": m.name_en, "employee_no": m.employee_no,
            "gender": m.gender, "employment_type": m.employment_type,
            "work_location": m.work_location, "email": m.email, "mobile": m.mobile,
            "department_id": dept.id if dept else None, "status": m.status,
        }
        if row:
            changed = any(getattr(row, k) != v for k, v in values.items())
            for k, v in values.items():
                setattr(row, k, v)
            stats["member_updated"] += int(changed)
        else:
            row = OrgMember(**values, external_source=source, external_id=m.external_id)
            db.add(row)
            stats["member_created"] += 1
        member_by_ext[m.external_id] = row
    db.flush()
    for m in snapshot.members:
        row = member_by_ext[m.external_id]
        leader = member_by_ext.get(m.leader_external_id) if m.leader_external_id else None
        row.supervisor_id = leader.id if leader else None
    # 外部消失的人员 → 离职（保留档案与历史单据关联）
    seen_members = set(member_by_ext.keys())
    for row in db.query(OrgMember).filter(
        OrgMember.external_source == source, OrgMember.is_deleted.is_(False), OrgMember.status == "在岗"
    ):
        if row.external_id not in seen_members:
            row.status = "离职"
            stats["member_left"] += 1

    db.commit()
    logger.info("org sync from %s: %s", source, stats)
    return stats


def run_sync(db: Session, source: str) -> dict:
    provider = SYNC_PROVIDERS.get(source)  # 测试可注入假 provider 覆盖
    if provider:
        return apply_org_snapshot(db, source, provider.fetch())
    if source == "feishu":
        from app.services.feishu import run_feishu_sync

        return run_feishu_sync(db)
    from app.core.errors import AppError

    raise AppError("SYNC_NOT_CONFIGURED", f"{source} 同步尚未配置凭据（上线前接入）", 501)
