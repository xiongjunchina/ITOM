"""项目管理路由（PRD §6）。派生指标全部实时计算；WBS 任务状态可由任务负责人更新（数据范围规则）。"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.events import notifier
from app.events.bus import publish
from app.models import (
    AuthUser,
    CostEntry,
    Milestone,
    OrgMember,
    Portfolio,
    Project,
    Risk,
    ServiceItem,
    WbsTask,
)
from app.schemas.common import ok, paginate
from app.services import process_engine
from app.services.audit import audit
from app.services.charter import parse_charter
from app.services.codes import gen_code
from app.services.permissions import has_perm
from app.services.projects import compute_metrics, rebuild_wbs_codes
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


class ProjectUpdate(BaseModel):
    name: str | None = None
    pm: str | None = None
    planned_start: date | None = None
    planned_end: date | None = None
    portfolio_id: str | None = None
    service_item_id: str | None = None
    budget_10k: float | None = None
    description: str | None = None
    latest_update: str | None = None


class TransitionIn(BaseModel):
    to: str
    fields: dict = {}


class WbsIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    assignee: str
    start_date: date
    end_date: date
    parent_task_id: str | None = None
    description: str | None = None
    deliverable: str | None = None
    predecessor_ids: list[str] = []


class WbsUpdate(BaseModel):
    name: str | None = None
    assignee: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None
    deliverable: str | None = None
    predecessor_ids: list[str] | None = None
    status: str | None = None


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
    amount_10k: float = Field(gt=0)
    note: str | None = None


class CharterCreateIn(BaseModel):
    fields: dict
    wbs: list[dict] = []
    milestones: list[dict] = []
    risks: list[dict] = []


# ---------- 组合 ----------

@router.get("/api/portfolios")
def list_portfolios(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.query(Portfolio).filter(Portfolio.is_deleted.is_(False)).order_by(Portfolio.sort).all()
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    projects = db.query(Project).filter(Project.is_deleted.is_(False)).all()
    stats: dict[str, dict] = {}
    for p in projects:
        if p.portfolio_id:
            s = stats.setdefault(p.portfolio_id, {"count": 0})
            s["count"] += 1
    return ok([
        {"id": r.id, "name": r.name, "owner_id": r.owner_id, "owner_name": names.get(r.owner_id),
         "year": r.year, "description": r.description, "sort": r.sort,
         "project_count": stats.get(r.id, {}).get("count", 0)}
        for r in rows
    ], total=len(rows))


@router.post("/api/portfolios")
def create_portfolio(body: PortfolioIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "create"))):
    if db.query(Portfolio).filter(Portfolio.name == body.name, Portfolio.is_deleted.is_(False)).first():
        raise AppError("DUPLICATE", "组合名称已存在")
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
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    audit(db, "portfolio", row.id, "update", actor, {"name": body.name})
    db.commit()
    return ok({"id": row.id})


# ---------- 项目 ----------

def _project_row(p: Project, db: Session, names: dict, status_map: dict, with_metrics: bool = True) -> dict:
    row = {
        "id": p.id, "project_code": p.project_code, "name": p.name,
        "pm": p.pm, "pm_name": names.get(p.pm),
        "status": p.status, "status_name": status_map.get(p.status, p.status),
        "planned_start": p.planned_start, "planned_end": p.planned_end,
        "actual_start": p.actual_start, "actual_end": p.actual_end,
        "portfolio_id": p.portfolio_id, "portfolio_name": p.portfolio.name if p.portfolio else None,
        "budget_10k": p.budget_10k, "latest_update": p.latest_update,
    }
    if with_metrics:
        row.update(compute_metrics(db, p))
    return row


@router.get("/api/projects")
def list_projects(
    page: int = 1, page_size: int = 20, q: str = "", status: str = "",
    portfolio_id: str = "", scope: str = "",
    db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user),
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
    items, total = paginate(query.order_by(Project.created_at.desc()), page, page_size)
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    status_map = status_names(db, "project")
    return ok([_project_row(p, db, names, status_map) for p in items], total=total, page=page)


def _create_project(db: Session, data: dict, actor: AuthUser) -> Project:
    if data["planned_end"] < data["planned_start"]:
        raise AppError("INVALID_DATES", "计划结束不能早于计划开始")
    if not db.get(OrgMember, data["pm"]):
        raise AppError("NOT_FOUND", "项目经理不存在", 404)
    if data.get("service_item_id") and not db.get(ServiceItem, data["service_item_id"]):
        raise AppError("NOT_FOUND", "关联服务项不存在", 404)
    project = Project(**data, project_code=gen_code(db, Project, "project_code", "PJ"), status="planning")
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
    project = _create_project(db, body.model_dump(), actor)
    db.commit()
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    return ok(_project_row(project, db, names, status_names(db, "project")))


@router.get("/api/projects/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    p = db.get(Project, project_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    status_map = status_names(db, "project")
    detail = _project_row(p, db, names, status_map)
    detail.update({
        "description": p.description,
        "service_item_id": p.service_item_id,
        "allowed_transitions": [
            {"to": code, "to_name": status_map.get(code, code)}
            for code in allowed_targets(db, "project", p.status, user)
        ],
        "process": process_engine.instance_view(db, "project", p.id),
        "can_edit": has_perm(db, user, "projects", "edit"),
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
    detail["linked_requirements"] = [
        {"id": r.id, "requirement_code": r.requirement_code, "title": r.title,
         "status": r.status, "status_name": req_status.get(r.status, r.status), "moscow": r.moscow}
        for r in linked
    ]
    return ok(detail)


@router.patch("/api/projects/{project_id}")
def update_project(project_id: str, body: ProjectUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    p = db.get(Project, project_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    if p.status in ("closed", "cancelled"):
        raise AppError("PROJECT_FINAL", "终态项目不可编辑")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(p, k, v)
    if p.planned_end < p.planned_start:
        raise AppError("INVALID_DATES", "计划结束不能早于计划开始")
    audit(db, "project", p.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok({"id": p.id})


@router.post("/api/projects/{project_id}/transition")
def transition_project(project_id: str, body: TransitionIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    p = db.get(Project, project_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    from_code, to = wf_transition(db, p, "project", body.to, body.fields, actor)
    today = date.today()
    if to == "active" and not p.actual_start:
        p.actual_start = today
    if to == "completed":
        p.actual_end = today
        publish(db, "project.completed", "project", p.id, {})
    db.commit()
    return ok({"id": p.id, "status": p.status})


# ---------- 章程导入（两步：解析 → 确认创建） ----------

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
        result["fields"]["pm"] = member.id if member else None
        if not member:
            result["warnings"].append(f"项目经理「{pm_name}」不是系统中的人员，请手工选择")
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
    }, actor)

    created = {"wbs": 0, "milestones": 0, "risks": 0}
    default_start = project.planned_start
    for idx, w in enumerate(body.wbs):
        end = date.fromisoformat(str(w["end_date"])) if w.get("end_date") else project.planned_end
        start = date.fromisoformat(str(w["start_date"])) if w.get("start_date") else default_start
        if start > end:
            start = end
        db.add(WbsTask(
            project_id=project.id, name=w.get("name") or f"任务{idx+1}", assignee=w.get("assignee") or project.pm,
            start_date=start, end_date=end, description=w.get("description"),
            deliverable=w.get("deliverable"), sort=idx, wbs_code=str(idx + 1),
        ))
        default_start = end
        created["wbs"] += 1
    for m in body.milestones:
        if not m.get("target_date"):
            continue
        db.add(Milestone(project_id=project.id, name=m.get("name") or "里程碑",
                         target_date=date.fromisoformat(str(m["target_date"])), description=m.get("description")))
        created["milestones"] += 1
    for r in body.risks:
        db.add(Risk(project_id=project.id, title=r.get("title") or "未命名风险",
                    probability=r.get("probability") or "中", impact=r.get("impact") or "中",
                    mitigation=r.get("mitigation")))
        created["risks"] += 1
    db.flush()
    rebuild_wbs_codes(db, project.id)
    audit(db, "project", project.id, "charter_import", actor, created)
    db.commit()
    return ok({"project_id": project.id, "project_code": project.project_code, "created": created})


# ---------- WBS ----------

def _wbs_row(t: WbsTask, names: dict) -> dict:
    return {
        "id": t.id, "wbs_code": t.wbs_code, "name": t.name, "parent_task_id": t.parent_task_id,
        "assignee": t.assignee, "assignee_name": names.get(t.assignee),
        "start_date": t.start_date, "end_date": t.end_date, "status": t.status,
        "completed_at": t.completed_at, "description": t.description, "deliverable": t.deliverable,
        "predecessor_ids": t.predecessor_ids or [], "sort": t.sort,
    }


@router.get("/api/projects/{project_id}/wbs")
def list_wbs(project_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    tasks = (
        db.query(WbsTask)
        .filter(WbsTask.project_id == project_id, WbsTask.is_deleted.is_(False))
        .order_by(WbsTask.sort, WbsTask.created_at)
        .all()
    )
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    return ok([_wbs_row(t, names) for t in tasks], total=len(tasks))


@router.post("/api/projects/{project_id}/wbs")
def create_wbs(project_id: str, body: WbsIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    p = db.get(Project, project_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    if body.end_date < body.start_date:
        raise AppError("INVALID_DATES", "结束日期不能早于开始日期")
    if body.parent_task_id:
        parent = db.get(WbsTask, body.parent_task_id)
        if not parent or parent.project_id != project_id:
            raise AppError("NOT_FOUND", "父任务不存在", 404)
    task = WbsTask(**body.model_dump(), project_id=project_id, wbs_code="0",
                   sort=db.query(WbsTask).filter(WbsTask.project_id == project_id).count())
    db.add(task)
    db.flush()
    rebuild_wbs_codes(db, project_id)
    audit(db, "wbs_task", task.id, "create", actor, {"name": body.name})
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
    data = body.model_dump(exclude_unset=True)
    # 数据范围规则：任务负责人可更新自己任务的状态；其余字段需 projects.edit
    is_assignee = user.person_id and task.assignee == user.person_id
    if not has_perm(db, user, "projects", "edit"):
        if not (is_assignee and set(data) <= {"status"}):
            raise AppError("FORBIDDEN", "仅任务负责人可更新自己任务的状态；其他修改需项目编辑权限", 403)
    if data.get("status") and data["status"] not in ("未开始", "进行中", "已完成"):
        raise AppError("INVALID_STATUS", "状态必须为 未开始/进行中/已完成")
    for k, v in data.items():
        setattr(task, k, v)
    if task.end_date < task.start_date:
        raise AppError("INVALID_DATES", "结束日期不能早于开始日期")
    if data.get("status") == "已完成" and not task.completed_at:
        task.completed_at = datetime.now()
        on_time = task.completed_at.date() <= task.end_date
        publish(db, "wbs.completed", "project", task.project_id, {"task_id": task.id, "on_time": on_time})
    audit(db, "wbs_task", task.id, "update", user, {"fields": list(data.keys())})
    db.commit()
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    return ok(_wbs_row(task, names))


@router.delete("/api/wbs/{task_id}")
def delete_wbs(task_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    task = db.get(WbsTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "任务不存在", 404)
    if db.query(WbsTask).filter(WbsTask.parent_task_id == task.id, WbsTask.is_deleted.is_(False)).first():
        raise AppError("HAS_CHILDREN", "请先删除子任务")
    task.is_deleted = True
    rebuild_wbs_codes(db, task.project_id)
    audit(db, "wbs_task", task.id, "delete", actor, {"name": task.name})
    db.commit()
    return ok({"id": task.id})


# ---------- 里程碑 ----------

@router.get("/api/projects/{project_id}/milestones")
def list_milestones(project_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
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
    m.is_deleted = True
    audit(db, "milestone", m.id, "delete", actor, {"name": m.name})
    db.commit()
    return ok({"id": m.id})


# ---------- 风险 ----------

@router.get("/api/projects/{project_id}/risks")
def list_risks(project_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
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
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(r, k, v)
    audit(db, "risk", r.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok({"id": r.id})


# ---------- 成本 ----------

@router.get("/api/projects/{project_id}/costs")
def list_costs(project_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = (
        db.query(CostEntry)
        .filter(CostEntry.project_id == project_id, CostEntry.is_deleted.is_(False))
        .order_by(CostEntry.entry_date.desc())
        .all()
    )
    return ok([
        {"id": c.id, "entry_date": c.entry_date, "amount_10k": c.amount_10k, "note": c.note}
        for c in rows
    ], total=len(rows))


@router.post("/api/projects/{project_id}/costs")
def create_cost(project_id: str, body: CostIn, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    if not db.get(Project, project_id):
        raise AppError("NOT_FOUND", "项目不存在", 404)
    c = CostEntry(**body.model_dump(), project_id=project_id, created_by=actor.id)
    db.add(c)
    db.flush()
    audit(db, "cost_entry", c.id, "create", actor, {"amount_10k": body.amount_10k})
    db.commit()
    return ok({"id": c.id})


@router.delete("/api/costs/{cost_id}")
def delete_cost(cost_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("projects", "edit"))):
    c = db.get(CostEntry, cost_id)
    if not c or c.is_deleted:
        raise AppError("NOT_FOUND", "成本记录不存在", 404)
    c.is_deleted = True
    audit(db, "cost_entry", c.id, "delete", actor, {"amount_10k": c.amount_10k})
    db.commit()
    return ok({"id": c.id})
