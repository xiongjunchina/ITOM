"""项目管理路由（PRD §6）。派生指标全部实时计算；WBS 任务状态可由任务负责人更新（数据范围规则）。"""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_example_delete_allowed, ensure_not_example
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.events import notifier
from app.events.bus import publish
from app.models import (
    AuthUser,
    InvestmentBudgetItem,
    InvestmentCostEntry,
    InvestmentWorklog,
    Milestone,
    OrgMember,
    Portfolio,
    Project,
    RecordRelation,
    Risk,
    ServiceItem,
    WbsTask,
)
from app.schemas.common import ok, paginate
from app.services import process_engine
from app.services.audit import audit
from app.services.batch_delete import execute_batch_delete
from app.services.charter import parse_charter
from app.services.codes import gen_code
from app.services.permissions import has_perm
from app.services.investment import money, summary as investment_domain_summary
from app.services.projects import apply_wbs_progress, compute_metrics, recalculate_wbs_hierarchy, rebuild_wbs_codes
from app.services.team_scope import digital_team_scope_configured, is_it_member, require_it_member_if_configured
from app.services.workflow import allowed_targets, status_names
from app.services.workflow import transition as wf_transition

router = APIRouter(tags=["projects"])


# ---------- Schemas ----------

class PortfolioIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    owner_id: str | None = None
    year: str | None = None
    description: str | None = None
    sort: int = 0


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    pm: str
    planned_start: date
    planned_end: date
    portfolio_id: str | None = None
    service_item_id: str | None = None
    budget_10k: float | None = None
    description: str | None = None
    requirement_id: str | None = None  # M16：由需求转入时关联，项目关闭自动闭环需求


class ProjectUpdate(BaseModel):
    name: str | None = None
    pm: str | None = None
    planned_start: date | None = None
    planned_end: date | None = None
    portfolio_id: str | None = None
    service_item_id: str | None = None
    budget_10k: float | None = None
    description: str | None = None
    background: str | None = None
    goals: str | None = None
    scope_in: str | None = None
    scope_out: str | None = None
    resource_note: str | None = None
    org_members: list[dict] | None = None
    stakeholders: list[dict] | None = None
    latest_update: str | None = None
    actual_start: date | None = None
    actual_end: date | None = None


class TransitionIn(BaseModel):
    to: str
    fields: dict = {}


class WbsIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    assignee: str
    start_date: date
    end_date: date
    parent_task_id: str | None = None
    stage: str | None = None
    wbs_dict: str | None = None
    deliverable: str | None = None
    is_milestone: bool = False
    remarks: str | None = None
    predecessor_ids: list[str] = []


class WbsUpdate(BaseModel):
    name: str | None = None
    assignee: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    stage: str | None = None
    wbs_dict: str | None = None
    deliverable: str | None = None
    is_milestone: bool | None = None
    remarks: str | None = None
    predecessor_ids: list[str] | None = None
    actual_start: date | None = None
    actual_end: date | None = None
    progress: int | None = Field(default=None, ge=0, le=100)  # 完成度% 0-100


class WbsMoveIn(BaseModel):
    """未开始 WBS 任务的树形调整请求。

    ``parent_task_id`` 为 ``null`` 时移动为一级任务；``before_task_id``
    为 ``null`` 时放到目标层级的末尾。
    """

    parent_task_id: str | None = None
    before_task_id: str | None = None


class WbsBatchMoveIn(BaseModel):
    """一次原子移动多个 WBS 根任务；被选根的后代随树移动。"""

    task_ids: list[str] = Field(min_length=1, max_length=500)
    parent_task_id: str | None = None
    before_task_id: str | None = None


class WbsBatchIdsIn(BaseModel):
    """WBS 层级联选可跨页覆盖整棵树，批量操作上限独立放宽。"""

    ids: list[str] = Field(min_length=1, max_length=500)


class MilestoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    target_date: date
    description: str | None = None


class RiskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    probability: str = Field(pattern="^(高|中|低)$")
    impact: str = Field(pattern="^(高|中|低)$")
    mitigation: str | None = None


class RiskUpdate(BaseModel):
    title: str | None = None
    probability: str | None = None
    impact: str | None = None
    mitigation: str | None = None
    status: str | None = None


class CostIn(BaseModel):
    entry_date: date
    amount_cny: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    amount_10k: float | None = Field(default=None, gt=0)
    category: str = Field(default="other", pattern="^(software|hardware|cloud|network|security|service|outsourcing|telecom|facility|labor|other|legacy)$")
    cost_type: str = Field(default="incurred", pattern="^(incurred|committed|paid)$")
    supplier: str | None = Field(default=None, max_length=128)
    wbs_task_id: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def require_amount(self):
        if self.amount_cny is None and self.amount_10k is None:
            raise ValueError("amount_cny 或 amount_10k 至少填写一个")
        return self


class BudgetItemIn(BaseModel):
    category: str = Field(pattern="^(software|hardware|cloud|network|security|service|outsourcing|telecom|facility|labor|other)$")
    name: str = Field(min_length=1, max_length=128)
    amount_cny: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    note: str | None = Field(default=None, max_length=500)


class EffortEntryIn(BaseModel):
    person_id: str
    work_date: date
    effort_days: Decimal = Field(gt=0, le=2, max_digits=8, decimal_places=2)
    role_type: str = Field(pattern="^(design|development|testing|implementation|pm|operations|other)$")
    standard_rate_cny_per_day: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    wbs_task_id: str | None = None
    note: str | None = Field(default=None, max_length=500)


class CharterCreateIn(BaseModel):
    fields: dict
    wbs: list[dict] = []
    milestones: list[dict] = []
    risks: list[dict] = []


# ---------- 组合 ----------

@router.get("/api/portfolios")
def list_portfolios(db: Session = Depends(get_db), _=Depends(require_perm("projects", "view"))):
    rows = db.query(Portfolio).filter(Portfolio.is_deleted.is_(False)).order_by(Portfolio.is_example.desc(), Portfolio.sort).all()
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    projects = db.query(Project).filter(Project.is_deleted.is_(False)).all()
    stats: dict[str, dict] = {}
    for p in projects:
        if p.portfolio_id:
            s = stats.setdefault(p.portfolio_id, {"count": 0})
            s["count"] += 1
    return ok([
        {"id": r.id, "name": r.name, "is_example": r.is_example, "owner_id": r.owner_id, "owner_name": names.get(r.owner_id),
         "year": r.year, "description": r.description, "sort": r.sort,
         "project_count": stats.get(r.id, {}).get("count", 0)}
        for r in rows
    ], total=len(rows))


@router.post("/api/portfolios")
def create_portfolio(body: PortfolioIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "create"))):
    if db.query(Portfolio).filter(Portfolio.name == body.name, Portfolio.is_deleted.is_(False)).first():
        raise AppError("DUPLICATE", "组合名称已存在")
    require_it_member_if_configured(db, body.owner_id, "项目组合负责人")
    row = Portfolio(**body.model_dump())
    db.add(row)
    db.flush()
    audit(db, "portfolio", row.id, "create", actor, {"name": body.name})
    db.commit()
    return ok({"id": row.id})


@router.patch("/api/portfolios/{portfolio_id}")
def update_portfolio(portfolio_id: str, body: PortfolioIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    row = db.get(Portfolio, portfolio_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "组合不存在", 404)
    ensure_not_example(row)
    require_it_member_if_configured(db, body.owner_id, "项目组合负责人")
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    audit(db, "portfolio", row.id, "update", actor, {"name": body.name})
    db.commit()
    return ok({"id": row.id})


@router.delete("/api/portfolios/{portfolio_id}")
def delete_portfolio(portfolio_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "delete"))):
    """删除项目组合（M21，软删）：组合仅是分组，成员项目解除挂接后保留。"""
    row = db.get(Portfolio, portfolio_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "组合不存在", 404)
    ensure_example_delete_allowed(row, db, actor)
    unlinked = 0
    for p in db.query(Project).filter(Project.portfolio_id == row.id, Project.is_deleted.is_(False)):
        p.portfolio_id = None
        unlinked += 1
    row.is_deleted = True
    audit(db, "portfolio", row.id, "delete", actor, {"name": row.name, "projects_unlinked": unlinked})
    db.commit()
    return ok({"id": row.id, "projects_unlinked": unlinked})


# ---------- 项目 ----------

def _project_row(p: Project, db: Session, names: dict, status_map: dict, with_metrics: bool = True) -> dict:
    row = {
        "id": p.id, "project_code": p.project_code, "name": p.name,
        "pm": p.pm, "pm_name": names.get(p.pm),
        "status": p.status, "status_name": status_map.get(p.status, p.status),
        "planned_start": p.planned_start, "planned_end": p.planned_end,
        "actual_start": p.actual_start, "actual_end": p.actual_end,
        "portfolio_id": p.portfolio_id, "portfolio_name": p.portfolio.name if p.portfolio else None,
        "budget_10k": p.budget_10k, "latest_update": p.latest_update, "is_example": p.is_example,
    }
    if with_metrics:
        row.update(compute_metrics(db, p))
    return row


@router.get("/api/projects")
def list_projects(
    page: int = 1, page_size: int = 20, q: str = "", status: str = "",
    portfolio_id: str = "", scope: str = "",
    db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("projects", "view")),
):
    query = db.query(Project).filter(Project.is_deleted.is_(False))
    if q:
        query = query.filter(or_(Project.name.ilike(f"%{q}%"), Project.project_code.ilike(f"%{q}%")))
    if status:
        query = query.filter(Project.status == status)
    if portfolio_id:
        query = query.filter(Project.portfolio_id == portfolio_id)
    if scope == "mine" and user.person_id:
        query = query.filter(Project.pm == user.person_id)
    items, total = paginate(query.order_by(Project.is_example.desc(), Project.created_at.desc()), page, page_size)
    pend = process_engine.pending_steps_map(db, ["project"], [x.id for x in items], user)
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    status_map = status_names(db, "project")
    rows = []
    for project in items:
        edit_access = process_engine.workflow_edit_access(db, user, "project", project.id, "projects")
        delete_access = process_engine.workflow_delete_access(db, user, "project", project.id, "projects")
        rows.append({
            **_project_row(project, db, names, status_map),
            "pending_step": pend.get(project.id),
            "can_edit": edit_access.allowed and not project.is_example,
            "can_delete": delete_access.allowed and not project.is_example,
            "workflow_edit_mode": edit_access.mode,
            "workflow_edit_locked_reason": edit_access.reason,
        })
    return ok(rows, total=total, page=page)


def _link_requirement(db: Session, project: Project, requirement_id: str, actor: AuthUser):
    """M16：项目创建时挂接来源需求（转项目路径），项目验收关闭后自动闭环该需求。"""
    from app.models import Requirement

    r = db.get(Requirement, requirement_id)
    if not r or r.is_deleted:
        raise AppError("NOT_FOUND", "关联需求不存在", 404)
    r.project_id = project.id
    audit(db, "requirement", r.id, "link_project", actor, {"project": project.project_code})
    if r.requester:
        ru = db.get(AuthUser, r.requester)
        if ru and ru.person_id:
            from app.events import notifier

            notifier.notify(db, "requirement.project_created", "requirement", r.id, [ru.person_id],
                            f"需求已立项：{r.requirement_code} {r.title}",
                            f"项目 {project.project_code}「{project.name}」已创建，可在需求详情跟踪交付。",
                            link=f"/requirements/{r.id}")


def _close_linked_requirements(db: Session, project: Project, actor: AuthUser):
    """M16.5：项目验收关闭 → 提醒项目经理回需求模块完成「实现交付」步骤，进入业务验收。

    不再直接自动关闭需求——闭环须走完流程：实现交付（PM 确认）→ 验收与闭环
    （业务域负责人组织业务部门验收）→ 流程完成时需求自动关闭。"""
    from app.models import Requirement
    from app.services import requirement_scoring

    cfg = requirement_scoring.get_config(db)
    rows = db.query(Requirement).filter(
        Requirement.project_id == project.id, Requirement.is_deleted.is_(False),
        Requirement.status.notin_(("closed", "cancelled")),
    ).all()
    for r in rows:
        route = requirement_scoring.compute_route(r.solution_type, r.dev_effort, cfg.effort_threshold)
        if route != requirement_scoring.ROUTE_PROJECT:
            continue  # 手动挂接的非转项目需求不提醒
        audit(db, "requirement", r.id, "project_delivered", actor, {"project": project.project_code})
        if r.owner:
            from app.events import notifier

            notifier.notify(db, "requirement.project_delivered", "requirement", r.id, [r.owner],
                            f"项目已关闭，请回需求闭环：{r.requirement_code} {r.title}",
                            f"关联项目 {project.project_code} 已验收关闭。请在需求详情完成当前流程步骤，"
                            f"进入业务验收环节（业务域负责人组织）后需求将闭环。",
                            link=f"/requirements/{r.id}")


def _create_project(db: Session, data: dict, actor: AuthUser) -> Project:
    if data["planned_end"] < data["planned_start"]:
        raise AppError("INVALID_DATES", "计划结束不能早于计划开始")
    if not db.get(OrgMember, data["pm"]):
        raise AppError("NOT_FOUND", "项目经理不存在", 404)
    require_it_member_if_configured(db, data["pm"], "项目经理")
    if data.get("service_item_id") and not db.get(ServiceItem, data["service_item_id"]):
        raise AppError("NOT_FOUND", "关联服务项不存在", 404)
    project = Project(
        **data,
        project_code=gen_code(db, Project, "project_code", "PJ"),
        created_by=actor.id,
        status="planning",
    )
    db.add(project)
    db.flush()
    process_engine.start_instance(db, "project", project.id, {}, preferred_assignee=project.pm)
    audit(db, "project", project.id, "create", actor, {"code": project.project_code, "name": project.name})
    publish(db, "project.created", "project", project.id, {"code": project.project_code})
    if project.pm and project.pm != actor.person_id:
        notifier.notify(db, "project.assigned", "project", project.id, [project.pm],
                        f"您被指定为项目经理：{project.project_code} {project.name}",
                        link=f"/projects/{project.id}")
    return project


@router.post("/api/projects")
def create_project(body: ProjectCreate, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "create"))):
    data = body.model_dump()
    requirement_id = data.pop("requirement_id", None)
    project = _create_project(db, data, actor)
    if requirement_id:
        _link_requirement(db, project, requirement_id, actor)
    db.commit()
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    return ok(_project_row(project, db, names, status_names(db, "project")))


@router.get("/api/projects/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("projects", "view"))):
    p = db.get(Project, project_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    status_map = status_names(db, "project")
    detail = _project_row(p, db, names, status_map)
    edit_access = process_engine.workflow_edit_access(db, user, "project", p.id, "projects")
    delete_access = process_engine.workflow_delete_access(db, user, "project", p.id, "projects")
    detail.update({
        "description": p.description,
        "background": p.background, "goals": p.goals,
        "scope_in": p.scope_in, "scope_out": p.scope_out,
        "resource_note": p.resource_note,
        "org_members": p.org_members or [], "stakeholders": p.stakeholders or [],
        "service_item_id": p.service_item_id,
        # M30：无 projects.edit 不下发状态按钮（与 transition 接口一致）；关闭仅 admin/PM 本人
        "allowed_transitions": [] if p.is_example or not has_perm(db, user, "projects", "edit") else [
            {"to": code, "to_name": status_map.get(code, code)}
            for code in allowed_targets(db, "project", p.status, user)
            if code not in ("closed", "cancelled") or _can_close_project(db, user, p)
        ],
        "can_close": (not p.is_example) and _can_close_project(db, user, p),
        "process": process_engine.instance_view(db, "project", p.id),
        "can_edit": (not p.is_example) and edit_access.allowed,
        "can_delete": (not p.is_example) and delete_access.allowed,
        "workflow_edit_mode": edit_access.mode,
        "workflow_edit_locked_reason": edit_access.reason,
    })
    # 关联需求（PRD §6.2 概述页）：M5 需求经 project_id 挂接
    from app.models import Requirement
    from app.services.workflow import status_names as _sn

    req_status = _sn(db, "requirement")
    linked = (
        db.query(Requirement)
        .filter(Requirement.project_id == p.id, Requirement.is_deleted.is_(False))
        .order_by(Requirement.created_at.desc())
        .all()
    )
    # “需求转项目”的新统一关联仍复用 requirement.project_id 维持既有闭环；
    # 将关联说明带回旧的关联需求区，详情页即可避免与通用关系面板重复展示。
    relation_by_requirement = {
        relation.source_entity_id: relation
        for relation in db.query(RecordRelation)
        .filter(
            RecordRelation.is_deleted.is_(False),
            RecordRelation.source_entity_type == "requirement",
            RecordRelation.target_entity_type == "project",
            RecordRelation.target_entity_id == p.id,
            RecordRelation.relation_type == "converted_to_project",
        )
        .all()
    }
    detail["linked_requirements"] = [
        {"id": r.id, "requirement_code": r.requirement_code, "title": r.title,
         "status": r.status, "status_name": req_status.get(r.status, r.status), "moscow": r.moscow,
         "relation_reason": relation_by_requirement[r.id].reason if r.id in relation_by_requirement else None,
         "relation_created_at": relation_by_requirement[r.id].created_at if r.id in relation_by_requirement else None}
        for r in linked
    ]
    return ok(detail)


@router.patch("/api/projects/{project_id}")
def update_project(project_id: str, body: ProjectUpdate, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    p = db.get(Project, project_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    ensure_not_example(p)
    if p.status in ("closed", "cancelled"):
        raise AppError("PROJECT_FINAL", "终态项目不可编辑")
    data = body.model_dump(exclude_unset=True)
    access = process_engine.require_workflow_edit(db, actor, "project", p.id, "projects")
    process_engine.require_safe_correction_fields(access, data, {"pm"})
    if data.get("pm"):
        require_it_member_if_configured(db, data["pm"], "项目经理")
    for k, v in data.items():
        setattr(p, k, v)
    if p.planned_end < p.planned_start:
        raise AppError("INVALID_DATES", "计划结束不能早于计划开始")
    audit(db, "project", p.id, "update", actor, {"fields": list(data.keys()), "workflow_edit_mode": access.mode})
    db.commit()
    return ok({"id": p.id})


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    """删除项目（软删，M14；M14.1 起不限状态）。

    级联：WBS/里程碑/成本/风险/附件/流程实例与任务 软删；关联需求解除挂接；
    该项目 WBS 产生的积分台账软删（绩效/排行自动回算）。总览与负载为实时聚合，自动排除。
    """
    p = db.get(Project, project_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    ensure_example_delete_allowed(p, db, actor)
    access = process_engine.require_workflow_delete(db, actor, "project", p.id, "projects")
    from app.models import Attachment, PointEntry, ProcessInstance, ProcessTask, Requirement

    stats = {"wbs": 0, "milestones": 0, "costs": 0, "budget_items": 0, "effort_entries": 0,
             "risks": 0, "attachments": 0,
             "process_instances": 0, "requirements_unlinked": 0, "point_entries": 0}
    wbs_ids: list[str] = []
    for t in db.query(WbsTask).filter(WbsTask.project_id == p.id, WbsTask.is_deleted.is_(False)):
        t.is_deleted = True
        wbs_ids.append(t.id)
        stats["wbs"] += 1
    for m in db.query(Milestone).filter(Milestone.project_id == p.id, Milestone.is_deleted.is_(False)):
        m.is_deleted = True
        wbs_ids.append(m.id)  # 旧里程碑积分 source_ref 兼容
        stats["milestones"] += 1
    for c in db.query(InvestmentCostEntry).filter(InvestmentCostEntry.project_id == p.id, InvestmentCostEntry.is_deleted.is_(False)):
        c.is_deleted = True
        stats["costs"] += 1
    for item in db.query(InvestmentBudgetItem).filter(
        InvestmentBudgetItem.subject_type == "project", InvestmentBudgetItem.subject_id == p.id,
        InvestmentBudgetItem.is_deleted.is_(False),
    ):
        item.is_deleted = True
        stats["budget_items"] += 1
    for entry in db.query(InvestmentWorklog).filter(InvestmentWorklog.project_id == p.id, InvestmentWorklog.is_deleted.is_(False)):
        entry.is_deleted = True
        stats["effort_entries"] += 1
    for r in db.query(Risk).filter(Risk.project_id == p.id, Risk.is_deleted.is_(False)):
        r.is_deleted = True
        stats["risks"] += 1
    for a in db.query(Attachment).filter(Attachment.entity_type == "project", Attachment.entity_id == p.id,
                                         Attachment.is_deleted.is_(False)):
        a.is_deleted = True
        stats["attachments"] += 1
    for inst in db.query(ProcessInstance).filter(ProcessInstance.entity_type == "project",
                                                 ProcessInstance.entity_id == p.id,
                                                 ProcessInstance.is_deleted.is_(False)):
        inst.is_deleted = True
        stats["process_instances"] += 1
        for task in db.query(ProcessTask).filter(ProcessTask.instance_id == inst.id, ProcessTask.is_deleted.is_(False)):
            task.is_deleted = True
    for req in db.query(Requirement).filter(Requirement.project_id == p.id, Requirement.is_deleted.is_(False)):
        req.project_id = None
        stats["requirements_unlinked"] += 1
    if wbs_ids:
        for pe in db.query(PointEntry).filter(PointEntry.source_ref.in_(wbs_ids), PointEntry.is_deleted.is_(False)):
            pe.is_deleted = True
            stats["point_entries"] += 1
    p.is_deleted = True
    audit(db, "project", p.id, "delete", actor, {
        "code": p.project_code, **stats, "workflow_delete_mode": access.mode,
    })
    db.commit()
    return ok({"id": p.id, "cascade": stats})


def _can_close_project(db: Session, user: AuthUser, p: Project) -> bool:
    """关闭项目权限（M28）：admin 恒可；项目经理本人可关（理由必填已有）；其余节点走流程。"""
    from app.core.rbac import ADMIN
    from app.services.rbac import actor_keys

    if ADMIN in actor_keys(db, user):
        return True
    return bool(p.pm and user.person_id and p.pm == user.person_id)


@router.post("/api/projects/{project_id}/transition")
def transition_project(project_id: str, body: TransitionIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    p = db.get(Project, project_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    ensure_not_example(p)
    rewind_seq = (body.fields or {}).pop("process_step_seq", None)  # 重启回退目标节点（可选）
    reason = str((body.fields or {}).pop("reason", "") or "").strip()
    if body.to in ("paused", "closed") and len(reason) < 2:
        raise AppError("REASON_REQUIRED", "暂停/关闭项目必须填写理由")
    if body.to in ("closed", "cancelled") and not _can_close_project(db, actor, p):
        # M28：项目关闭仅项目经理本人或系统管理员（理由+审计已具备）；其余节点走流程闭环
        raise AppError("FORCE_CLOSE_FORBIDDEN", "仅该项目的项目经理或系统管理员可关闭项目", 403)
    from_code, to = wf_transition(db, p, "project", body.to, body.fields, actor)
    if reason and to in ("paused", "closed"):
        label = "暂停" if to == "paused" else "关闭"
        p.latest_update = f"[{label}] {reason}"  # 理由落最新动态，概述页可见
        audit(db, "project", p.id, "transition_reason", actor, {"to": to, "reason": reason})
    today = date.today()
    if to == "active" and not p.actual_start:
        p.actual_start = today
    if to == "active" and from_code in ("completed", "closed"):
        p.actual_end = None  # 重启：清实际结束（重新完成时再打点）
        if rewind_seq is not None:
            process_engine.rewind_to_step(db, "project", p.id, int(rewind_seq), preferred_assignee=p.pm)
            audit(db, "project", p.id, "process_rewind", actor, {"to_seq": int(rewind_seq)})
    if to == "completed":
        if not p.actual_end:
            p.actual_end = today  # 手动填过则尊重
        publish(db, "project.completed", "project", p.id, {})
    if to == "closed":
        if not p.actual_end:
            p.actual_end = today  # 提前关闭同样落实际结束
        _close_linked_requirements(db, p, actor)  # M16：转项目需求自动闭环
    if to in ("closed", "cancelled"):
        process_engine.finalize_instance(db, "project", p.id, "项目已关闭，流程随单收尾")  # M24
    db.commit()
    return ok({"id": p.id, "status": p.status})


# ---------- 章程导入（两步：解析 → 确认创建） ----------

@router.get("/api/projects/charter/template")
def charter_template(_=Depends(require_perm("projects", "create"))):
    """下载项目章程模板 .docx（含示例，填好后经「导入章程」自动建项目）。"""
    from urllib.parse import quote

    from fastapi.responses import Response

    from app.services.charter_template import build_charter_template_docx

    content = build_charter_template_docx()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=charter_template.docx; filename*=UTF-8''{quote('项目章程模板.docx')}"},
    )


@router.post("/api/projects/charter/parse")
async def charter_parse(file: UploadFile, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "create"))):
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise AppError("FILE_TOO_LARGE", "章程文档不能超过 10MB")
    if not (file.filename or "").lower().endswith(".docx"):
        raise AppError("INVALID_FORMAT", "请上传 .docx 章程文档")
    try:
        result = parse_charter(content)
    except ValueError as e:
        raise AppError("PARSE_FAILED", str(e))
    # 项目经理姓名 → 人员解析
    pm_name = result["fields"].get("pm_name")
    if pm_name:
        member = db.query(OrgMember).filter(OrgMember.name == pm_name, OrgMember.is_deleted.is_(False)).first()
        pm_in_scope = bool(member and (not digital_team_scope_configured(db) or is_it_member(db, member.id)))
        result["fields"]["pm"] = member.id if pm_in_scope else None
        if not member:
            result["warnings"].append(f"项目经理「{pm_name}」不是系统中的人员，请手工选择")
        elif not pm_in_scope:
            result["warnings"].append(f"项目经理「{pm_name}」不属于数字化团队，请手工选择数字化团队成员")
    return ok(result)


@router.post("/api/projects/charter/create")
def charter_create(body: CharterCreateIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "create"))):
    f = body.fields
    required = {"name": "项目名称", "pm": "项目经理", "planned_start": "计划开始", "planned_end": "计划结束"}
    for key, label in required.items():
        if not f.get(key):
            raise AppError("STAGE_FIELD_REQUIRED", f"缺少{label}")
    project = _create_project(db, {
        "name": f["name"], "pm": f["pm"],
        "planned_start": date.fromisoformat(str(f["planned_start"])),
        "planned_end": date.fromisoformat(str(f["planned_end"])),
        "portfolio_id": f.get("portfolio_id"), "service_item_id": f.get("service_item_id"),
        "budget_10k": f.get("budget_10k"), "description": f.get("description"),
        "background": f.get("background"), "goals": f.get("goals"),
        "scope_in": f.get("scope_in"), "scope_out": f.get("scope_out"),
        "resource_note": f.get("resource_note"),
        "org_members": f.get("org_members"), "stakeholders": f.get("stakeholders"),
    }, actor)
    if f.get("requirement_id"):
        _link_requirement(db, project, f["requirement_id"], actor)

    from app.services.projects import create_wbs_by_code

    # WBS：按 WBS编号建层级、前置按编号；里程碑=WBS 勾选「是」派生。负责人未匹配默认项目经理。
    wbs_count, wbs_errors = create_wbs_by_code(db, project, body.wbs, default_assignee=project.pm)
    created = {
        "wbs": wbs_count,
        "milestones": sum(1 for w in body.wbs if w.get("is_milestone")),  # 里程碑=WBS 派生
        "risks": 0,
    }
    for r in body.risks:
        db.add(Risk(project_id=project.id, title=r.get("title") or "未命名风险",
                    probability=r.get("probability") or "中", impact=r.get("impact") or "中",
                    mitigation=r.get("mitigation")))
        created["risks"] += 1
    db.flush()
    imported_tasks = (
        db.query(WbsTask)
        .filter(WbsTask.project_id == project.id, WbsTask.is_deleted.is_(False))
        .all()
    )
    recalculate_wbs_hierarchy(imported_tasks)
    rebuild_wbs_codes(db, project.id)  # 按树规范化 WBS编号（前置引用为 id，不受影响）
    audit(db, "project", project.id, "charter_import", actor, created)
    db.commit()
    return ok({"project_id": project.id, "project_code": project.project_code,
               "created": created, "wbs_errors": wbs_errors})


# ---------- WBS ----------

def _wbs_row(t: WbsTask, names: dict, codes: dict | None = None) -> dict:
    from app.services.projects import wbs_deviation, wbs_status

    return {
        "id": t.id, "wbs_code": t.wbs_code, "stage": t.stage, "name": t.name, "parent_task_id": t.parent_task_id,
        "wbs_dict": t.wbs_dict, "deliverable": t.deliverable,
        "assignee": t.assignee, "assignee_name": names.get(t.assignee),
        "is_milestone": t.is_milestone,
        "start_date": t.start_date, "end_date": t.end_date,
        "actual_start": t.actual_start, "actual_end": t.actual_end,
        "schedule_deviation": wbs_deviation(t.actual_end, t.end_date),  # 进度偏差(天)，计算
        "progress": t.progress or 0,  # 完成度% 0-100
        "status": wbs_status(t.progress or 0, t.end_date),  # 状态，计算（含已延期）
        "completed_at": t.completed_at, "remarks": t.remarks, "description": t.description,
        "predecessor_ids": t.predecessor_ids or [],
        # 前置任务按 WBS 号展示（前端用）
        "predecessor_codes": [codes[pid] for pid in (t.predecessor_ids or []) if codes and pid in codes] if codes else [],
        "sort": t.sort,
        # 当前完成度为 100% 的任务是项目交付记录，不能删除或改变其树形位置。
        # completed_at 保留首次完成时间作为审计证据；若经授权将完成度修正到
        # 100% 以下，删除和结构操作应重新开放。
        "completed_locked": _wbs_is_completed(t),
        "structure_locked": _wbs_is_completed(t),
    }


def _wbs_is_completed(task: WbsTask) -> bool:
    """返回任务当前是否处于完成锁定状态。

    completed_at 是首次完成审计时间，不能用于判断当前状态；完成度经授权
    修正到 100% 以下后，结构调整和删除能力应重新开放。
    """
    return (task.progress or 0) >= 100


def _wbs_children(tasks: list[WbsTask]) -> dict[str | None, list[WbsTask]]:
    children: dict[str | None, list[WbsTask]] = {}
    for item in sorted(tasks, key=lambda row: (row.sort, row.created_at)):
        children.setdefault(item.parent_task_id, []).append(item)
    return children


def _wbs_descendant_ids(task_id: str, children: dict[str | None, list[WbsTask]]) -> set[str]:
    result: set[str] = set()
    stack = [task_id]
    while stack:
        current = stack.pop()
        for child in children.get(current, []):
            if child.id not in result:
                result.add(child.id)
                stack.append(child.id)
    return result


def _wbs_depth_first(children: dict[str | None, list[WbsTask]]) -> list[WbsTask]:
    """返回与树表实际渲染一致的深度优先顺序，并安全保留异常孤立行。"""
    result: list[WbsTask] = []
    visited: set[str] = set()

    def walk(parent_id: str | None):
        for item in children.get(parent_id, []):
            if item.id in visited:
                continue
            visited.add(item.id)
            result.append(item)
            walk(item.id)

    walk(None)
    for siblings in children.values():
        for item in siblings:
            if item.id not in visited:
                visited.add(item.id)
                result.append(item)
    return result


def _move_wbs_roots(
    project_id: str,
    requested_task_ids: list[str],
    parent_task_id: str | None,
    before_task_id: str | None,
    db: Session,
) -> tuple[list[WbsTask], list[WbsTask], dict[str, dict]]:
    """按一个事务校验并移动 WBS 根任务；调用方负责审计与提交。"""
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    ensure_not_example(project)

    tasks = (
        db.query(WbsTask)
        .filter(WbsTask.project_id == project_id, WbsTask.is_deleted.is_(False))
        .order_by(WbsTask.sort, WbsTask.created_at)
        .with_for_update()
        .all()
    )
    by_id = {item.id: item for item in tasks}
    children = _wbs_children(tasks)
    unique_ids = list(dict.fromkeys(requested_task_ids))
    if any(task_id not in by_id for task_id in unique_ids):
        raise AppError("NOT_FOUND", "待移动任务不存在或不属于当前项目", 404)

    requested_ids = set(unique_ids)
    # 父子同时选中时，后代天然跟随父级，不再作为第二个移动根重复处理。
    moved_roots: list[WbsTask] = []
    for item in _wbs_depth_first(children):
        if item.id not in requested_ids:
            continue
        visited: set[str] = set()
        ancestor_id = item.parent_task_id
        has_selected_ancestor = False
        while ancestor_id and ancestor_id not in visited:
            if ancestor_id in requested_ids:
                has_selected_ancestor = True
                break
            visited.add(ancestor_id)
            ancestor_id = by_id.get(ancestor_id).parent_task_id if ancestor_id in by_id else None
        if not has_selected_ancestor:
            moved_roots.append(item)

    if not moved_roots:
        raise AppError("INVALID_WBS_MOVE", "待移动任务的层级关系无效，无法确定移动根")

    moved_root_ids = {item.id for item in moved_roots}
    moved_tree_ids = set(moved_root_ids)
    for item in moved_roots:
        descendants = _wbs_descendant_ids(item.id, children)
        moved_tree_ids.update(descendants)
        if _wbs_is_completed(item):
            raise AppError("WBS_STRUCTURE_LOCKED", "当前完成度为 100% 的 WBS 任务不能调整层级或排序")
        if any(_wbs_is_completed(by_id[descendant_id]) for descendant_id in descendants):
            raise AppError("WBS_STRUCTURE_LOCKED", "待移动任务包含当前完成度为 100% 的子任务，不能调整层级")

    if parent_task_id:
        new_parent = by_id.get(parent_task_id)
        if not new_parent:
            raise AppError("NOT_FOUND", "目标父任务不存在", 404)
        if new_parent.id in moved_tree_ids:
            raise AppError("WBS_CYCLE", "不能将任务移动到自身或其子任务下")
        if _wbs_is_completed(new_parent):
            raise AppError("WBS_STRUCTURE_LOCKED", "目标父任务当前完成度为 100%，不能调整其层级")

    if before_task_id:
        before = by_id.get(before_task_id)
        if not before:
            raise AppError("NOT_FOUND", "排序参照任务不存在", 404)
        if before.id in moved_tree_ids:
            raise AppError("INVALID_WBS_MOVE", "排序参照任务不能是待移动任务或其子任务")
        if before.parent_task_id != parent_task_id:
            raise AppError("INVALID_WBS_MOVE", "排序参照任务必须位于目标层级")

    affected_parent_ids = {parent_task_id, *(item.parent_task_id for item in moved_roots)}
    for affected_parent_id in affected_parent_ids:
        sibling_rows = children.get(affected_parent_id, [])
        if any(_wbs_is_completed(item) for item in sibling_rows if item.id not in moved_root_ids):
            raise AppError(
                "WBS_STRUCTURE_LOCKED",
                "该层级存在当前完成度为 100% 的任务，不能调整顺序或层级",
            )

    old_states = {
        item.id: {
            "old_parent_task_id": item.parent_task_id,
            "old_sort": item.sort,
            "old_wbs_code": item.wbs_code,
        }
        for item in moved_roots
    }
    reordered: dict[str | None, list[WbsTask]] = {
        affected_parent_id: [
            item for item in children.get(affected_parent_id, []) if item.id not in moved_root_ids
        ]
        for affected_parent_id in affected_parent_ids
    }
    target_siblings = reordered[parent_task_id]
    if before_task_id:
        insert_at = next(index for index, item in enumerate(target_siblings) if item.id == before_task_id)
    else:
        insert_at = len(target_siblings)
    target_siblings[insert_at:insert_at] = moved_roots

    for item in moved_roots:
        item.parent_task_id = parent_task_id
    for siblings in reordered.values():
        for index, item in enumerate(siblings):
            item.sort = index
    db.flush()
    rebuild_wbs_codes(db, project_id)
    return tasks, moved_roots, old_states


def _record_wbs_completion(db: Session, task: WbsTask, project: Project):
    """为达到 100% 的任务补齐完成时间及一次性完成事件。"""
    if (task.progress or 0) < 100 or task.completed_at:
        return
    task.completed_at = datetime.now()
    done_date = task.actual_end or task.completed_at.date()
    on_time = done_date <= task.end_date
    publish(db, "wbs.completed", "project", task.project_id, {"task_id": task.id, "on_time": on_time})
    if task.is_milestone and not project.is_example:
        from app.services.points import award_by_rule

        award_by_rule(db, "milestone_achieved", project.pm, task.id, f"里程碑达成 {task.name[:30]}")


@router.get("/api/projects/{project_id}/wbs")
def list_wbs(project_id: str, db: Session = Depends(get_db), _=Depends(require_perm("projects", "view"))):
    tasks = (
        db.query(WbsTask)
        .filter(WbsTask.project_id == project_id, WbsTask.is_deleted.is_(False))
        .order_by(WbsTask.sort, WbsTask.created_at)
        .all()
    )
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    codes = {t.id: t.wbs_code for t in tasks}
    return ok([_wbs_row(t, names, codes) for t in tasks], total=len(tasks))


@router.post("/api/projects/{project_id}/wbs")
def create_wbs(project_id: str, body: WbsIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    p = db.get(Project, project_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    ensure_not_example(p)
    require_it_member_if_configured(db, body.assignee, "项目任务负责人")
    if body.end_date < body.start_date:
        raise AppError("INVALID_DATES", "结束日期不能早于开始日期")
    if body.parent_task_id:
        parent = db.get(WbsTask, body.parent_task_id)
        if not parent or parent.is_deleted or parent.project_id != project_id:
            raise AppError("NOT_FOUND", "父任务不存在", 404)
        if _wbs_is_completed(parent):
            raise AppError("WBS_STRUCTURE_LOCKED", "当前完成度为 100% 的父任务不能新增子任务")
    task = WbsTask(**body.model_dump(), project_id=project_id, wbs_code="0",
                   sort=db.query(WbsTask).filter(WbsTask.project_id == project_id).count())
    db.add(task)
    db.flush()
    progress_changed: list[WbsTask] = []
    if task.parent_task_id:
        all_tasks = (
            db.query(WbsTask)
            .filter(WbsTask.project_id == project_id, WbsTask.is_deleted.is_(False))
            .all()
        )
        progress_changed = recalculate_wbs_hierarchy(all_tasks)
        for item in progress_changed:
            _record_wbs_completion(db, item, p)
    rebuild_wbs_codes(db, project_id)
    summary = {"name": body.name}
    if progress_changed:
        summary["progress_updated_task_ids"] = [item.id for item in progress_changed]
    audit(db, "wbs_task", task.id, "create", actor, summary)
    if task.assignee != actor.person_id:
        notifier.notify(db, "wbs.assigned", "project", project_id, [task.assignee],
                        f"新任务指派：{p.name} / {task.name}", link=f"/projects/{project_id}")
    db.commit()
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    return ok(_wbs_row(task, names))


@router.patch("/api/wbs/{task_id}")
def update_wbs(task_id: str, body: WbsUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    task = db.get(WbsTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "任务不存在", 404)
    project = db.get(Project, task.project_id)
    ensure_not_example(project)
    data = body.model_dump(exclude_unset=True)
    # 数据范围规则：任务负责人可更新自己任务的完成度/实际起止；其余字段需 projects.edit
    is_assignee = user.person_id and task.assignee == user.person_id
    if not has_perm(db, user, "projects", "edit"):
        if not (is_assignee and set(data) <= {"progress", "actual_start", "actual_end"}):
            raise AppError("FORBIDDEN", "仅任务负责人可更新自己任务的完成度；其他修改需项目编辑权限", 403)

    # 已完成任务是交付记录，实际日期必须先通过单独的“降低完成度”操作解锁。
    # 不能在同一个请求里同时降低完成度并修改实际日期，避免审计轨迹被绕过。
    was_completed = _wbs_is_completed(task)
    actual_fields = {"actual_start", "actual_end"} & set(data)
    requested_progress = data.get("progress")
    if was_completed and requested_progress is not None and requested_progress < 100 and actual_fields:
        raise AppError(
            "WBS_REOPEN_ACTUAL_DATES_CONFLICT",
            "请先重新打开任务，再修改实际日期",
        )
    if was_completed and actual_fields:
        raise AppError(
            "WBS_ACTUAL_DATES_LOCKED",
            "已完成任务的实际开始和结束日期已锁定；如需修正，请先将完成度调整为低于 100%",
        )

    next_actual_start = data.get("actual_start", task.actual_start)
    next_actual_end = data.get("actual_end", task.actual_end)
    today = date.today()
    if "actual_end" in data and next_actual_end and next_actual_end > today:
        raise AppError("WBS_ACTUAL_END_IN_FUTURE", "实际结束日期不能晚于今天")
    if actual_fields and next_actual_start and next_actual_end and next_actual_end < next_actual_start:
        raise AppError("WBS_ACTUAL_DATES_INVALID", "实际结束日期不能早于实际开始日期")

    requested_progress = data.pop("progress", None)
    if "actual_end" in data and next_actual_end is not None:
        # 真实结束日不晚于今天，等同于任务完成；以实际结束日为完成时间。
        requested_progress = 100
    progress_changed: list[WbsTask] = []
    reopened_task_ids: list[str] = []
    if requested_progress is not None:
        all_tasks = (
            db.query(WbsTask)
            .filter(WbsTask.project_id == task.project_id, WbsTask.is_deleted.is_(False))
            .all()
        )
        completed_before = {item.id for item in all_tasks if _wbs_is_completed(item)}
        progress_changed = apply_wbs_progress(all_tasks, task, requested_progress)
        for item in progress_changed:
            if item.id in completed_before and not _wbs_is_completed(item):
                item.actual_end = None
                reopened_task_ids.append(item.id)
    for k, v in data.items():
        setattr(task, k, v)
    if task.end_date < task.start_date:
        raise AppError("INVALID_DATES", "结束日期不能早于开始日期")
    # 完成度达 100 → 记完成时间并派按期积分；级联/回算的任务也逐一补齐完成事件。
    completion_candidates = {item.id: item for item in progress_changed}
    if requested_progress is not None:
        completion_candidates[task.id] = task
    for item in completion_candidates.values():
        _record_wbs_completion(db, item, project)
    summary = {"fields": [*data.keys(), *(["progress"] if requested_progress is not None else [])]}
    if progress_changed:
        summary["progress_updated_task_ids"] = [item.id for item in progress_changed]
    if reopened_task_ids:
        summary["reopened_task_ids"] = reopened_task_ids
    audit(db, "wbs_task", task.id, "update", user, summary)
    db.commit()
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    return ok(_wbs_row(task, names))


def _delete_wbs_one(task_id: str, db: Session, actor, *, expected_project_id: str | None = None) -> WbsTask:
    """按单条删除的完整领域规则软删除一个 WBS 任务，不提交事务。"""
    task = db.get(WbsTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "任务不存在", 404)
    if expected_project_id and task.project_id != expected_project_id:
        raise AppError("NOT_FOUND", "任务不存在", 404)
    project = db.get(Project, task.project_id)
    ensure_example_delete_allowed(project, db, actor)
    if _wbs_is_completed(task):
        raise AppError("WBS_COMPLETED_LOCKED", "已完成的 WBS 任务是项目交付记录，不允许删除")
    if db.query(WbsTask).filter(WbsTask.parent_task_id == task.id, WbsTask.is_deleted.is_(False)).first():
        raise AppError("HAS_CHILDREN", "请先删除子任务")
    parent_task_id = task.parent_task_id
    task.is_deleted = True
    progress_changed: list[WbsTask] = []
    if parent_task_id:
        all_tasks = (
            db.query(WbsTask)
            .filter(WbsTask.project_id == task.project_id, WbsTask.is_deleted.is_(False))
            .all()
        )
        progress_changed = recalculate_wbs_hierarchy(all_tasks)
        for item in progress_changed:
            _record_wbs_completion(db, item, project)
    rebuild_wbs_codes(db, task.project_id)
    summary = {"name": task.name}
    if progress_changed:
        summary["progress_updated_task_ids"] = [item.id for item in progress_changed]
    audit(db, "wbs_task", task.id, "delete", actor, summary)
    return task


@router.delete("/api/projects/{project_id}/wbs/batch-delete")
def batch_delete_wbs(
    project_id: str,
    body: WbsBatchIdsIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("projects", "edit")),
):
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)

    # 同时选择父子任务时必须先删最深层子项，否则父项会被 HAS_CHILDREN
    # 拒绝。未知/跨项目 ID 仍交由逐条领域校验返回明确拒绝原因。
    selected = (
        db.query(WbsTask)
        .filter(WbsTask.id.in_(body.ids), WbsTask.project_id == project_id, WbsTask.is_deleted.is_(False))
        .all()
    )
    known_ids = {task.id for task in selected}
    ordered_ids = [
        task.id
        for task in sorted(
            selected,
            key=lambda item: (item.wbs_code.count("."), item.wbs_code, item.created_at),
            reverse=True,
        )
    ]
    ordered_ids.extend(entity_id for entity_id in body.ids if entity_id not in known_ids)

    return ok(execute_batch_delete(
        db,
        ordered_ids,
        lambda task_id: _delete_wbs_one(task_id, db, actor, expected_project_id=project_id),
    ))


@router.delete("/api/wbs/{task_id}")
def delete_wbs(task_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    task = _delete_wbs_one(task_id, db, actor)
    db.commit()
    return ok({"id": task.id})


@router.post("/api/wbs/{task_id}/move")
def move_wbs(
    task_id: str,
    body: WbsMoveIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("projects", "edit")),
):
    """调整当前未完成 WBS 的父级和同级顺序。

    当前完成度为 100% 的任务保持交付锁定；经授权修正到 100% 以下后，
    可重新调整层级和同级顺序，首次完成时间继续保留用于审计。
    """
    task = db.get(WbsTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "任务不存在", 404)
    tasks, moved_roots, old_states = _move_wbs_roots(
        task.project_id,
        [task_id],
        body.parent_task_id,
        body.before_task_id,
        db,
    )
    moved = moved_roots[0]
    old_state = old_states[moved.id]
    audit(
        db,
        "wbs_task",
        moved.id,
        "move",
        actor,
        {
            **old_state,
            "new_parent_task_id": body.parent_task_id,
            "new_sort": moved.sort,
            "new_wbs_code": moved.wbs_code,
            "before_task_id": body.before_task_id,
        },
    )
    db.commit()
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    codes = {item.id: item.wbs_code for item in tasks}
    return ok(_wbs_row(moved, names, codes))


@router.post("/api/projects/{project_id}/wbs/batch-move")
def batch_move_wbs(
    project_id: str,
    body: WbsBatchMoveIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("projects", "edit")),
):
    """原子移动一个或多个 WBS 根及其完整子树。"""
    tasks, moved_roots, old_states = _move_wbs_roots(
        project_id,
        body.task_ids,
        body.parent_task_id,
        body.before_task_id,
        db,
    )
    moved_root_ids = [item.id for item in moved_roots]
    batch_anchor_id = moved_root_ids[0]
    for item in moved_roots:
        audit(
            db,
            "wbs_task",
            item.id,
            "move",
            actor,
            {
                **old_states[item.id],
                "new_parent_task_id": body.parent_task_id,
                "new_sort": item.sort,
                "new_wbs_code": item.wbs_code,
                "before_task_id": body.before_task_id,
                "batch_move": True,
                "batch_anchor_id": batch_anchor_id,
                "batch_size": len(moved_root_ids),
            },
        )
    db.commit()
    return ok({
        "requested_task_ids": list(dict.fromkeys(body.task_ids)),
        "moved_root_ids": moved_root_ids,
        "parent_task_id": body.parent_task_id,
        "before_task_id": body.before_task_id,
        "total": len(tasks),
    })


# ---------- 里程碑跟踪（派生：WBS 中里程碑=是 的行自动汇总，与模板「里程碑跟踪」页一致） ----------

@router.get("/api/projects/{project_id}/milestone-tracking")
def milestone_tracking(project_id: str, db: Session = Depends(get_db), _=Depends(require_perm("projects", "view"))):
    from app.services.projects import wbs_deviation, wbs_status

    tasks = (
        db.query(WbsTask)
        .filter(WbsTask.project_id == project_id, WbsTask.is_deleted.is_(False), WbsTask.is_milestone.is_(True))
        .order_by(WbsTask.sort, WbsTask.created_at)
        .all()
    )
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    rows = [
        {
            "id": t.id, "wbs_code": t.wbs_code, "name": t.name, "stage": t.stage,
            "assignee_name": names.get(t.assignee) or "(待填)",
            "end_date": t.end_date, "actual_end": t.actual_end,
            "schedule_deviation": wbs_deviation(t.actual_end, t.end_date),
            "status": wbs_status(t.progress or 0, t.end_date),
        }
        for t in tasks
    ]
    return ok(rows, total=len(rows))


# ---------- 里程碑（旧独立实体，保留兼容；新界面用里程碑跟踪派生视图） ----------

@router.get("/api/projects/{project_id}/milestones")
def list_milestones(project_id: str, db: Session = Depends(get_db), _=Depends(require_perm("projects", "view"))):
    rows = (
        db.query(Milestone)
        .filter(Milestone.project_id == project_id, Milestone.is_deleted.is_(False))
        .order_by(Milestone.target_date)
        .all()
    )
    today = date.today()
    return ok([
        {"id": m.id, "name": m.name, "target_date": m.target_date, "description": m.description,
         "achieved_at": m.achieved_at, "overdue": not m.achieved_at and m.target_date < today}
        for m in rows
    ], total=len(rows))


@router.post("/api/projects/{project_id}/milestones")
def create_milestone(project_id: str, body: MilestoneIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    if not db.get(Project, project_id):
        raise AppError("NOT_FOUND", "项目不存在", 404)
    _p = db.get(Project, project_id)
    ensure_not_example(_p)
    m = Milestone(**body.model_dump(), project_id=project_id)
    db.add(m)
    db.flush()
    audit(db, "milestone", m.id, "create", actor, {"name": body.name})
    db.commit()
    return ok({"id": m.id})


@router.post("/api/milestones/{milestone_id}/achieve")
def achieve_milestone(milestone_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    m = db.get(Milestone, milestone_id)
    if not m or m.is_deleted:
        raise AppError("NOT_FOUND", "里程碑不存在", 404)
    ensure_not_example(db.get(Project, m.project_id))
    if m.achieved_at:
        raise AppError("ALREADY_DONE", "里程碑已达成")
    m.achieved_at = date.today()
    publish(db, "milestone.achieved", "project", m.project_id, {"milestone_id": m.id})
    audit(db, "milestone", m.id, "achieve", actor, {"name": m.name})
    db.commit()
    return ok({"id": m.id, "achieved_at": m.achieved_at})


@router.delete("/api/milestones/{milestone_id}")
def delete_milestone(milestone_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    m = db.get(Milestone, milestone_id)
    if not m or m.is_deleted:
        raise AppError("NOT_FOUND", "里程碑不存在", 404)
    ensure_example_delete_allowed(db.get(Project, m.project_id), db, actor)
    m.is_deleted = True
    audit(db, "milestone", m.id, "delete", actor, {"name": m.name})
    db.commit()
    return ok({"id": m.id})


# ---------- 风险 ----------

@router.get("/api/projects/{project_id}/risks")
def list_risks(project_id: str, db: Session = Depends(get_db), _=Depends(require_perm("projects", "view"))):
    rows = db.query(Risk).filter(Risk.project_id == project_id, Risk.is_deleted.is_(False)).order_by(Risk.created_at.desc()).all()
    return ok([
        {"id": r.id, "title": r.title, "probability": r.probability, "impact": r.impact,
         "mitigation": r.mitigation, "status": r.status}
        for r in rows
    ], total=len(rows))


@router.post("/api/projects/{project_id}/risks")
def create_risk(project_id: str, body: RiskIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    if not db.get(Project, project_id):
        raise AppError("NOT_FOUND", "项目不存在", 404)
    _p = db.get(Project, project_id)
    ensure_not_example(_p)
    r = Risk(**body.model_dump(), project_id=project_id)
    db.add(r)
    db.flush()
    audit(db, "risk", r.id, "create", actor, {"title": body.title})
    db.commit()
    return ok({"id": r.id})


@router.patch("/api/risks/{risk_id}")
def update_risk(risk_id: str, body: RiskUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    r = db.get(Risk, risk_id)
    if not r or r.is_deleted:
        raise AppError("NOT_FOUND", "风险不存在", 404)
    ensure_not_example(db.get(Project, r.project_id))
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(r, k, v)
    audit(db, "risk", r.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok({"id": r.id})


# ---------- 成本 ----------

@router.get("/api/projects/{project_id}/costs")
def list_costs(project_id: str, db: Session = Depends(get_db), _=Depends(require_perm("projects", "view"))):
    rows = (
        db.query(InvestmentCostEntry)
        .filter(InvestmentCostEntry.project_id == project_id, InvestmentCostEntry.is_deleted.is_(False))
        .order_by(InvestmentCostEntry.recognition_date.desc())
        .all()
    )
    return ok([
        {"id": c.id, "entry_date": c.recognition_date, "amount_10k": float(c.amount_cny / Decimal("10000")),
         "amount_cny": money(c.amount_cny),
         "category": c.category, "cost_type": c.cost_status, "supplier": c.supplier_snapshot,
         "wbs_task_id": c.wbs_task_id, "note": c.note}
        for c in rows
    ], total=len(rows))


@router.post("/api/projects/{project_id}/costs")
def create_cost(project_id: str, body: CostIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    if not db.get(Project, project_id):
        raise AppError("NOT_FOUND", "项目不存在", 404)
    _p = db.get(Project, project_id)
    ensure_not_example(_p)
    if body.wbs_task_id:
        wbs = db.get(WbsTask, body.wbs_task_id)
        if not wbs or wbs.is_deleted or wbs.project_id != project_id:
            raise AppError("INVALID_WBS", "关联 WBS 任务不存在或不属于当前项目")
    amount_cny = body.amount_cny
    if amount_cny is None:
        amount_cny = (Decimal(str(body.amount_10k)) * Decimal("10000")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    c = InvestmentCostEntry(
        lifecycle_stage="build", investment_intent="transform",
        subject_type="project", subject_id=project_id, project_id=project_id,
        recognition_date=body.entry_date, amount_cny=amount_cny,
        cost_status=body.cost_type, category=body.category, cost_nature="capex",
        labor_nature="unclassified" if body.category == "labor" else "none",
        recurrence="one_time", activity_type="implementation", supplier_snapshot=body.supplier,
        wbs_task_id=body.wbs_task_id, note=body.note, created_by=actor.id,
    )
    db.add(c)
    db.flush()
    audit(db, "investment_cost_entry", c.id, "create", actor, {"amount_cny": money(amount_cny), "category": c.category})
    db.commit()
    return ok({"id": c.id})


@router.get("/api/projects/{project_id}/budget-items")
def list_budget_items(project_id: str, db: Session = Depends(get_db), _=Depends(require_perm("projects", "view"))):
    rows = db.query(InvestmentBudgetItem).filter(
        InvestmentBudgetItem.subject_type == "project", InvestmentBudgetItem.subject_id == project_id,
        InvestmentBudgetItem.is_deleted.is_(False)
    ).order_by(InvestmentBudgetItem.created_at).all()
    return ok([{"id": row.id, "category": row.category, "name": row.name,
                "amount_cny": str(row.amount_cny), "note": row.note} for row in rows], total=len(rows))


@router.post("/api/projects/{project_id}/budget-items")
def create_budget_item(project_id: str, body: BudgetItemIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    ensure_not_example(project)
    # 旧 project.budget_10k 迁移行是“无分项时兜底”，新增第一条显式预算后退出汇总。
    for fallback in db.query(InvestmentBudgetItem).filter(
        InvestmentBudgetItem.subject_type == "project",
        InvestmentBudgetItem.subject_id == project_id,
        InvestmentBudgetItem.source_type == "legacy_project_budget_total",
        InvestmentBudgetItem.is_deleted.is_(False),
    ):
        fallback.is_deleted = True
    row = InvestmentBudgetItem(
        lifecycle_stage="build", investment_intent="transform", subject_type="project",
        subject_id=project_id, period_start=project.planned_start, period_end=project.planned_end,
        cost_nature="capex", created_by=actor.id, **body.model_dump(),
    )
    db.add(row)
    db.flush()
    audit(db, "investment_budget_item", row.id, "create", actor, {"amount_cny": money(row.amount_cny), "category": row.category})
    db.commit()
    return ok({"id": row.id})


@router.delete("/api/project-budget-items/{item_id}")
def delete_budget_item(item_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    row = db.get(InvestmentBudgetItem, item_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "预算分项不存在", 404)
    if row.subject_type != "project":
        raise AppError("NOT_FOUND", "预算分项不存在", 404)
    ensure_not_example(db.get(Project, row.subject_id))
    row.is_deleted = True
    audit(db, "investment_budget_item", row.id, "delete", actor, {"amount_cny": money(row.amount_cny)})
    db.commit()
    return ok({"id": row.id})


@router.get("/api/projects/{project_id}/effort-entries")
def list_effort_entries(project_id: str, db: Session = Depends(get_db), _=Depends(require_perm("projects", "view"))):
    rows = db.query(InvestmentWorklog).filter(
        InvestmentWorklog.project_id == project_id, InvestmentWorklog.is_deleted.is_(False)
    ).order_by(InvestmentWorklog.work_date.desc()).all()
    names = {row.id: row.name for row in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    return ok([{"id": row.id, "person_id": row.person_id, "person_name": names.get(row.person_id),
                "work_date": row.work_date, "effort_days": str(row.effort_days), "role_type": row.role_type,
                "standard_rate_cny_per_day": str(row.standard_rate_cny_per_day) if row.standard_rate_cny_per_day is not None else None,
                "wbs_task_id": row.wbs_task_id, "note": row.note} for row in rows], total=len(rows))


@router.post("/api/projects/{project_id}/effort-entries")
def create_effort_entry(project_id: str, body: EffortEntryIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    ensure_not_example(project)
    if body.work_date > date.today():
        raise AppError("INVESTMENT_WORKLOG_FUTURE_DATE", "实际工时不能登记未来日期", 400)
    require_it_member_if_configured(db, body.person_id, "投入人员")
    existing_days = sum((
        item.effort_days for item in db.query(InvestmentWorklog).filter(
            InvestmentWorklog.person_id == body.person_id,
            InvestmentWorklog.work_date == body.work_date,
            InvestmentWorklog.is_deleted.is_(False),
        )
    ), Decimal("0"))
    if existing_days + body.effort_days > Decimal("2"):
        raise AppError("INVESTMENT_WORKLOG_DAILY_LIMIT", "同一人员单日累计投入不能超过 2 人天", 409)
    if body.wbs_task_id:
        wbs = db.get(WbsTask, body.wbs_task_id)
        if not wbs or wbs.is_deleted or wbs.project_id != project_id:
            raise AppError("INVALID_WBS", "关联 WBS 任务不存在或不属于当前项目")
    rate = body.standard_rate_cny_per_day
    if rate is None:
        from app.services.org_settings import get_org_settings

        configured = (get_org_settings(db).report_role_rates or {}).get(body.role_type)
        rate = Decimal(str(configured)) if configured is not None else None
    row = InvestmentWorklog(
        lifecycle_stage="build", investment_intent="transform", subject_type="project",
        subject_id=project_id, project_id=project_id, person_id=body.person_id,
        work_date=body.work_date, effort_days=body.effort_days, role_type=body.role_type,
        activity_type=body.role_type if body.role_type in {"design", "development", "testing", "implementation", "pm"} else "other",
        standard_rate_cny_per_day=rate, wbs_task_id=body.wbs_task_id, note=body.note,
        created_by=actor.id,
    )
    db.add(row)
    db.flush()
    audit(db, "investment_worklog", row.id, "create", actor, {
        "effort_days": str(row.effort_days), "role_type": row.role_type,
        "standard_rate_used": rate is not None,
    })
    db.commit()
    return ok({"id": row.id})


@router.delete("/api/project-effort-entries/{entry_id}")
def delete_effort_entry(entry_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    row = db.get(InvestmentWorklog, entry_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "人天投入记录不存在", 404)
    ensure_not_example(db.get(Project, row.project_id))
    row.is_deleted = True
    audit(db, "investment_worklog", row.id, "delete", actor, {"effort_days": money(row.effort_days)})
    db.commit()
    return ok({"id": row.id})


@router.get("/api/projects/{project_id}/investment-summary")
def investment_summary(project_id: str, db: Session = Depends(get_db), _=Depends(require_perm("projects", "view"))):
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    return ok(investment_domain_summary(db, subject_type="project", subject_id=project_id, lifecycle_stage="build"))


@router.delete("/api/costs/{cost_id}")
def delete_cost(cost_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    c = db.get(InvestmentCostEntry, cost_id)
    if not c or c.is_deleted:
        raise AppError("NOT_FOUND", "成本记录不存在", 404)
    ensure_example_delete_allowed(db.get(Project, c.project_id), db, actor)
    c.is_deleted = True
    audit(db, "investment_cost_entry", c.id, "delete", actor, {"amount_cny": money(c.amount_cny)})
    db.commit()
    return ok({"id": c.id})


# ---------- 进度批量导入（WBS + 里程碑，PRD §6.2 进度页） ----------

from app.services.excel_io import Col, Sheet, build_template, parse_sheet

# WBS 主表（与用户 Excel 设计一致）：层级由 WBS编号 建立，里程碑=WBS 勾选「是」派生，
# 进度偏差/状态在系统内自动计算，故导入模板只收输入列（不含偏差/状态两个公式列）。
PROGRESS_SHEETS = [
    Sheet("WBS任务", [
        Col("stage", "阶段", hint="如 1.立项/2.选型，便于按阶段筛选"),
        Col("wbs_code", "WBS编号", hint="层级式 1/1.1/1.1.1，父级由编号前缀自动推导；留空则顺序编号"),
        Col("name", "任务名称(交付物)", required=True, hint="用名词性交付物命名（如“需求规格说明书”）"),
        Col("wbs_dict", "WBS词典说明(含/不含)", hint="写清含什么/不含什么，厘清工作包边界"),
        Col("deliverable", "交付物/验收标准(DoD)", hint="完成的定义（可检查的验收标准）"),
        Col("assignee_name", "责任人姓名", required=True, hint="唯一；须为系统中已有在岗人员"),
        Col("is_milestone", "里程碑(是/否)", hint="填『是』的行自动汇总到里程碑跟踪页"),
        Col("predecessor_codes", "前置任务(WBS号)", hint="多个用逗号分隔，填被依赖任务的 WBS编号"),
        Col("start_date", "计划开始", required=True, kind="date"),
        Col("end_date", "计划结束", required=True, kind="date"),
        Col("actual_start", "实际开始", kind="date", hint="执行阶段填写"),
        Col("actual_end", "实际结束", kind="date", hint="执行阶段填写，用于算进度偏差"),
        Col("progress", "完成度%(0-100)", hint="填写 0-100 的整数百分比；未填写按 0 处理"),
        Col("remarks", "备注"),
    ]),
]


@router.get("/api/project-progress/template")
def progress_template(_=Depends(require_perm("projects", "edit"))):
    from urllib.parse import quote

    from fastapi.responses import Response

    content = build_template(PROGRESS_SHEETS)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=template.xlsx; filename*=UTF-8''{quote('项目进度导入模板.xlsx')}"},
    )


@router.post("/api/projects/{project_id}/import-progress")
async def import_progress(project_id: str, file: UploadFile, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    ensure_not_example(project)
    if project.status in ("closed", "cancelled"):
        raise AppError("PROJECT_FINAL", "终态项目不可导入")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise AppError("FILE_TOO_LARGE", "导入文件不能超过 5MB")
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise AppError("INVALID_FORMAT", "请上传 .xlsx 文件（使用系统导出的模板）")

    from app.services.projects import create_wbs_by_code

    wbs_rows, wbs_errors = parse_sheet(content, PROGRESS_SHEETS[0])
    errors = [{**e, "sheet": "WBS任务"} for e in wbs_errors]
    sort_base = db.query(WbsTask).filter(WbsTask.project_id == project.id, WbsTask.is_deleted.is_(False)).count()
    # 按 WBS编号建层级、前置按编号、里程碑=WBS 派生（与设计一致）
    count, create_errors = create_wbs_by_code(db, project, wbs_rows, sort_base=sort_base)
    errors += [{"sheet": "WBS任务", "error": msg} for msg in create_errors]
    created = {"wbs": count, "milestones": sum(1 for r in wbs_rows if str(r.get("is_milestone") or "").strip() in ("是", "Y", "yes", "true", "1"))}

    db.flush()
    imported_tasks = (
        db.query(WbsTask)
        .filter(WbsTask.project_id == project.id, WbsTask.is_deleted.is_(False))
        .all()
    )
    recalculate_wbs_hierarchy(imported_tasks)
    rebuild_wbs_codes(db, project.id)
    audit(db, "project", project.id, "import_progress", actor, {**created, "failed": len(errors)})
    db.commit()
    return ok({"created": created, "failed": errors})
