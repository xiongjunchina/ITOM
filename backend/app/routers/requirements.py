"""需求管理路由（PRD §7）：五阶段协同漏斗（登记→评估→分析→实现→关闭）+ 一键转出闭环。"""
from datetime import date as _date
from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_example_delete_allowed, ensure_not_example
from app.core.rbac import ADMIN, IT_PDM, REQUESTER
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.events import notifier
from app.events.bus import publish
from app.models import (
    AuthUser,
    BusinessDomain,
    KnowledgeArticle,
    OrgMember,
    Problem,
    Project,
    RecordRelation,
    Requirement,
    RequirementScore,
    RequirementScoringConfig,
    RequirementTask,
)
from app.schemas.common import ok, paginate
from app.services import process_engine, requirement_intake, requirement_scoring
from app.services.audit import audit
from app.services.codes import gen_code
from app.services.permissions import has_perm
from app.services.rbac import effective_roles
from app.services.team_scope import require_it_member_if_configured
from app.services.workflow import allowed_targets, closure_path, restrict_terminal_targets, require_terminal_transition_admin, status_names
from app.services.workflow import transition as wf_transition

router = APIRouter(prefix="/api/requirements", tags=["requirements"])

REQ_TYPES = ("业务", "功能", "数据", "集成", "合规")
MOSCOW = ("M", "S", "C", "W")
DECISIONS = ("通过", "搁置", "驳回")


def _validate_scores(data: dict):
    for d in ("d1_strategy", "d2_value", "d3_tech", "d4_org", "d5_risk", "d6_speed"):
        v = data.get(d)
        if v is not None and (not isinstance(v, int) or not 1 <= v <= 5):
            raise AppError("INVALID_SCORE", "各维度评分必须为 1-5 的整数")


class RequirementCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    req_type: str
    business_domain_id: str
    description: str = Field(min_length=1)
    source: str | None = None
    parent_requirement_id: str | None = None
    # 登记可选进阶字段（默认折叠，不计入必填）
    department: str | None = None
    expected_date: str | None = None
    expected_effect: str | None = None
    business_value_note: str | None = None


class RequirementUpdate(BaseModel):
    title: str | None = None
    req_type: str | None = None
    business_domain_id: str | None = None
    description: str | None = None
    source: str | None = None
    department: str | None = None
    expected_date: str | None = None
    expected_effect: str | None = None
    business_value_note: str | None = None
    prd_effort: float | None = None
    dev_effort: float | None = None
    solution_type: str | None = None
    moscow: str | None = None
    owner: str | None = None
    target_date: str | None = None
    solution: str | None = None
    acceptance_criteria: list[dict] | None = None
    project_id: str | None = None
    remarks: str | None = None
    closure_note: str | None = None


class ScoreIn(BaseModel):
    """评估阶段单人共识评分（六维 1-5）+ 决议。"""
    d1_strategy: int | None = None
    d2_value: int | None = None
    d3_tech: int | None = None
    d4_org: int | None = None
    d5_risk: int | None = None
    d6_speed: int | None = None
    decision: str | None = None
    comment: str | None = None


class ScoringConfigIn(BaseModel):
    weights: dict | None = None
    thresholds: dict | None = None
    rubric: dict | None = None
    role_weights: dict | None = None
    effort_threshold: float | None = None
    review_assignees: dict | None = None


class TransitionIn(BaseModel):
    to: str
    fields: dict = {}


class TaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    assignee: str
    plan_date: str | None = None
    plan_effort: float | None = None


class TaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    assignee: str | None = None
    plan_date: str | None = None
    plan_effort: float | None = None
    actual_effort: float | None = None
    status: str | None = None


class ToProblemIn(BaseModel):
    title: str | None = None
    description: str = Field(min_length=1)


def _is_requester_only(db: Session, user: AuthUser) -> bool:
    return effective_roles(db, user) == {REQUESTER}


def _can_manage_requirement_tasks(db: Session, user: AuthUser, requirement: Requirement) -> bool:
    """任务维护权：全局任务/需求编辑者，或当前实现中需求的负责人。"""
    if requirement.is_example or requirement.status != "implementing":
        return False
    if has_perm(db, user, "requirements", "edit") or has_perm(db, user, "req_tasks", "edit"):
        return True
    return bool(user.person_id and requirement.owner == user.person_id)


def _can_delete_requirement_tasks(db: Session, user: AuthUser) -> bool:
    """删除仍保持原有管理权限，不因需求负责人身份自动扩大。"""
    return has_perm(db, user, "requirements", "edit") or has_perm(db, user, "req_tasks", "edit")


def _task_progress(db: Session, requirement_id: str) -> dict:
    tasks = db.query(RequirementTask).filter(
        RequirementTask.requirement_id == requirement_id, RequirementTask.is_deleted.is_(False)
    ).all()
    done = sum(1 for t in tasks if t.status == "已完成")
    return {
        "task_total": len(tasks),
        "task_done": done,
        "progress": round(done / len(tasks) * 100, 1) if tasks else None,
    }


def _row(r: Requirement, db: Session, names: dict, domains: dict, status_map: dict, cfg=None) -> dict:
    lead_days = None
    if r.closed_at and r.registered_at:
        lead_days = round((r.closed_at - r.registered_at).total_seconds() / 86400, 1)
    scores = requirement_scoring.requirement_scores(r)
    weights = cfg.weights if cfg else None
    thresholds = cfg.thresholds if cfg else None
    return {
        "id": r.id, "requirement_code": r.requirement_code, "title": r.title, "is_example": r.is_example,
        "req_type": r.req_type, "business_domain_id": r.business_domain_id,
        "business_domain_name": domains.get(r.business_domain_id),
        "source": r.source, "requester_name": r.requester_name, "department": r.department,
        "moscow": r.moscow, "owner": r.owner, "owner_name": names.get(r.owner),
        "target_date": r.target_date, "expected_date": r.expected_date,
        "status": r.status, "status_name": status_map.get(r.status, r.status),
        "registered_at": r.registered_at, "closed_at": r.closed_at, "lead_days": lead_days,
        "project_id": r.project_id,
        **scores,
        "weighted_total": requirement_scoring.compute_weighted_total(scores, weights),
        "quadrant": requirement_scoring.compute_quadrant(scores, thresholds, weights),
        "decision": r.decision, "prd_effort": r.prd_effort, "dev_effort": r.dev_effort,
        "solution_type": r.solution_type,
        "route": requirement_scoring.compute_route(
            r.solution_type, r.dev_effort, cfg.effort_threshold if cfg else None
        ),
        **_task_progress(db, r.id),
    }


@router.get("")
def list_requirements(
    page: int = 1, page_size: int = 50, q: str = "", status: str = "",
    business_domain_id: str = "", moscow: str = "", decision: str = "", scope: str = "",
    db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user),
):
    query = db.query(Requirement).filter(Requirement.is_deleted.is_(False))
    if _is_requester_only(db, user):
        query = query.filter(Requirement.requester == user.id)
    elif scope == "mine":
        query = query.filter(or_(Requirement.requester == user.id,
                                 Requirement.owner == (user.person_id or "-")))
    if q:
        query = query.filter(or_(Requirement.title.ilike(f"%{q}%"), Requirement.requirement_code.ilike(f"%{q}%")))
    if status:
        query = query.filter(Requirement.status == status)
    if business_domain_id:
        query = query.filter(Requirement.business_domain_id == business_domain_id)
    if moscow:
        query = query.filter(Requirement.moscow == moscow)
    if decision:
        query = query.filter(Requirement.decision == decision)
    items, total = paginate(query.order_by(Requirement.is_example.desc(), Requirement.created_at.desc()), page, page_size)
    pend = process_engine.pending_steps_map(db, ["requirement"], [x.id for x in items], user)
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    domains = {d.id: d.name for d in db.query(BusinessDomain).filter(BusinessDomain.is_deleted.is_(False))}
    status_map = status_names(db, "requirement")
    cfg = requirement_scoring.get_config(db)
    return ok([
        {
            **_row(r, db, names, domains, status_map, cfg),
            "pending_step": pend.get(r.id),
            "can_manage_tasks": _can_manage_requirement_tasks(db, user, r),
        }
        for r in items
    ], total=total, page=page)


def _current_process_task(db: Session, requirement_id: str):
    """需求流程实例的当前待处理任务。"""
    from app.models import ProcessInstance, ProcessTask

    db.flush()  # Session autoflush=False：先落刚生成的实例/任务再查

    inst = (
        db.query(ProcessInstance)
        .filter(ProcessInstance.entity_type == "requirement", ProcessInstance.entity_id == requirement_id,
                ProcessInstance.is_deleted.is_(False))
        .order_by(ProcessInstance.created_at.desc())
        .first()
    )
    if not inst:
        return None
    return (
        db.query(ProcessTask)
        .filter(ProcessTask.instance_id == inst.id, ProcessTask.status == "待处理",
                ProcessTask.is_deleted.is_(False))
        .first()
    )


def _assign_review_to_domain_owner(db: Session, r: Requirement):
    """M16：按业务域把评审任务指派给服务线负责人（域 owner）并通知；无 owner 则保持角色默认。"""
    domain = db.get(BusinessDomain, r.business_domain_id)
    owner = domain.owner_id if domain else None
    if not owner:
        return
    task = _current_process_task(db, r.id)
    if task:
        task.assignee = owner
    notifier.notify(db, "requirement.review_assigned", "requirement", r.id, [owner],
                    f"需求评审指派：{r.requirement_code} {r.title}",
                    f"业务域「{domain.name}」新需求待评审（六维评分）。",
                    link=f"/requirements/{r.id}")


def _enter_evaluating(db: Session, r: Requirement):
    """登记即进入评审（M16 流程：登记→按业务域指派服务线负责人评审）。"""
    r.status = "evaluating"
    if not r.evaluating_at:
        r.evaluating_at = datetime.now()
    _assign_review_to_domain_owner(db, r)


def _complete_review_step(db: Session, r: Requirement, user: AuthUser, comment: str):
    """决议落定时同步推进流程：完成「需求评审」步骤任务（引擎自动生成下一步骤任务）。"""
    task = _current_process_task(db, r.id)
    if task:
        process_engine.complete_task(db, task.id, user, comment[:500])


def _assign_solution_review(db: Session, r: Requirement):
    """立项后进入方案评估：产品 leader 主责、开发 leader 知会（评分规则配置页可配）。"""
    cfg = requirement_scoring.get_config(db)
    assignees = cfg.review_assignees or {}
    pdm_leader = assignees.get("pdm_leader")
    dev_leader = assignees.get("dev_leader")
    task = _current_process_task(db, r.id)
    if task and pdm_leader:
        task.assignee = pdm_leader
    recipients = [p for p in (pdm_leader, dev_leader) if p]
    if recipients:
        notifier.notify(db, "requirement.solution_review", "requirement", r.id, recipients,
                        f"方案评估：{r.requirement_code} {r.title}",
                        "请评估解决方案类型与开发人天（二开<阈值→需求实现；新购或≥阈值→转项目）。",
                        link=f"/requirements/{r.id}")


def on_process_advanced(db: Session, requirement_id: str, actor: AuthUser):
    """M16.5：需求流程步骤推进后的编排（由 process complete 端点回调）。

    - 推进到「验收与闭环」→ 任务指派该需求业务域负责人并通知（组织业务部门验收）
    - 流程全部完成 → 需求自动关闭（验收清单未全勾则改为通知负责人手动关闭）
    """
    from app.models import ProcessInstance, ProcessStep

    r = db.get(Requirement, requirement_id)
    if not r or r.is_deleted or r.status in ("closed", "cancelled"):
        return
    inst = (
        db.query(ProcessInstance)
        .filter(ProcessInstance.entity_type == "requirement", ProcessInstance.entity_id == r.id,
                ProcessInstance.is_deleted.is_(False))
        .order_by(ProcessInstance.created_at.desc())
        .first()
    )
    if not inst:
        return
    if inst.status == "completed":
        criteria = r.acceptance_criteria or []
        if criteria and not all(c.get("checked") for c in criteria):
            if r.owner:
                notifier.notify(db, "requirement.acceptance_pending", "requirement", r.id, [r.owner],
                                f"流程已完成，待勾选验收标准：{r.requirement_code} {r.title}",
                                "业务验收流程已完成，但验收标准未全部勾选；请核对后关闭需求。",
                                link=f"/requirements/{r.id}")
            return
        wf_transition(db, r, "requirement", "closed", {}, actor)
        r.closed_at = datetime.now()
        if not r.closure_note:
            r.closure_note = "[闭环] 业务验收完成，流程闭环"
        audit(db, "requirement", r.id, "auto_close", actor, {"via": "process_completed"})
        requester_person = None
        if r.requester:
            ru = db.get(AuthUser, r.requester)
            requester_person = ru.person_id if ru else None
        recipients = [p for p in {r.owner, requester_person} if p]
        if recipients:
            notifier.notify(db, "requirement.closed", "requirement", r.id, recipients,
                            f"需求已闭环：{r.requirement_code} {r.title}",
                            "业务验收完成，需求正式闭环。",
                            link=f"/requirements/{r.id}")
        publish(db, "requirement.closed", "requirement", r.id, {})
        return
    # 未完成：若当前步骤是「验收与闭环」→ 指派业务域负责人组织业务验收
    task = _current_process_task(db, r.id)
    if not task:
        return
    step = db.get(ProcessStep, task.step_id)
    if step and "验收" in (step.name or ""):
        domain = db.get(BusinessDomain, r.business_domain_id)
        owner = domain.owner_id if domain else None
        if owner:
            task.assignee = owner
            notifier.notify(db, "requirement.acceptance", "requirement", r.id, [owner],
                            f"需求业务验收：{r.requirement_code} {r.title}",
                            f"实现交付已完成，请组织业务部门验收（业务域「{domain.name}」）；"
                            f"完成「验收与闭环」步骤后需求自动关闭。",
                            link=f"/requirements/{r.id}")


def _notify_pdm(db: Session, requirement: Requirement):
    users = db.query(AuthUser).filter(AuthUser.is_active.is_(True)).all()
    recipients = [u.person_id for u in users if u.person_id and IT_PDM in effective_roles(db, u)]
    if recipients:
        notifier.notify(db, "requirement.registered", "requirement", requirement.id,
                        recipients,
                        f"新需求登记：{requirement.requirement_code} {requirement.title}",
                        link=f"/requirements/{requirement.id}")


@router.post("")
def create_requirement(body: RequirementCreate, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("requirements", "create"))):
    r = requirement_intake.create_requirement(db, body.model_dump(), user)
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    domains = {d.id: d.name for d in db.query(BusinessDomain).filter(BusinessDomain.is_deleted.is_(False))}
    return ok(_row(r, db, names, domains, status_names(db, "requirement"), requirement_scoring.get_config(db)))


# ---------- 评分规则配置（系统管理，admin 可调）：字面量路由须早于 /{requirement_id} ----------

@router.get("/scoring-config")
def get_scoring_config(db: Session = Depends(get_db), _: AuthUser = Depends(get_current_user)):
    cfg = requirement_scoring.get_config(db)
    db.commit()
    return ok({
        "id": cfg.id, "weights": cfg.weights, "thresholds": cfg.thresholds,
        "rubric": cfg.rubric, "role_weights": cfg.role_weights,
        "effort_threshold": cfg.effort_threshold if cfg.effort_threshold is not None
        else requirement_scoring.DEFAULT_EFFORT_THRESHOLD,
        "review_assignees": cfg.review_assignees or {},
        "defaults": {
            "weights": requirement_scoring.DEFAULT_WEIGHTS,
            "thresholds": requirement_scoring.DEFAULT_THRESHOLDS,
            "rubric": requirement_scoring.DEFAULT_RUBRIC,
            "role_weights": requirement_scoring.DEFAULT_ROLE_WEIGHTS,
            "effort_threshold": requirement_scoring.DEFAULT_EFFORT_THRESHOLD,
        },
    })


@router.put("/scoring-config")
def update_scoring_config(body: ScoringConfigIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    if ADMIN not in effective_roles(db, user):
        raise AppError("FORBIDDEN", "仅管理员可修改评分规则", 403)
    cfg = requirement_scoring.get_config(db)
    data = body.model_dump(exclude_unset=True)
    if "weights" in data and data["weights"]:
        w = data["weights"]
        if abs(sum(w.get(k, 0) for k in ("d1", "d2", "d3", "d4", "d5", "d6")) - 1.0) > 0.001:
            raise AppError("INVALID_WEIGHTS", "六维权重之和须为 1.0")
        cfg.weights = w
    if data.get("effort_threshold") is not None and data["effort_threshold"] <= 0:
        raise AppError("INVALID_THRESHOLD", "转项目人天阈值必须大于 0")
    for f in ("thresholds", "rubric", "role_weights", "effort_threshold", "review_assignees"):
        if f in data and data[f] is not None:
            setattr(cfg, f, data[f])
    audit(db, "requirement_scoring_config", cfg.id, "update", user, {"fields": list(data.keys())})
    db.commit()
    return ok({"id": cfg.id})


# ---------- 批量导入：模板导出 + 上传解析入库 ----------

def _import_sheet() -> "Sheet":
    from app.services.excel_io import Col, Sheet
    return Sheet("需求登记", [
        Col("title", "需求名称", required=True),
        Col("req_type", "需求类型", required=True, enum=list(REQ_TYPES)),
        Col("business_domain", "所属业务域", required=True, hint="按业务域名称精确匹配"),
        Col("description", "需求描述", required=True),
        Col("source", "需求来源"),
        Col("department", "渠道/部门"),
        Col("requester_name", "提出人"),
        Col("expected_date", "期望完成时间", kind="date"),
        Col("expected_effect", "期望效果"),
        Col("business_value_note", "运营价值"),
        Col("d1_strategy", "战略对齐(1-5)", kind="int", hint="评估分，可留空"),
        Col("d2_value", "业务价值(1-5)", kind="int"),
        Col("d3_tech", "技术可行性(1-5)", kind="int"),
        Col("d4_org", "组织就绪(1-5)", kind="int"),
        Col("d5_risk", "风险等级(1-5)", kind="int", hint="分越高风险越大(反向)"),
        Col("d6_speed", "价值速度(1-5)", kind="int"),
        Col("decision", "最终决议", enum=list(DECISIONS)),
        Col("prd_effort", "PRD人天", kind="float"),
        Col("dev_effort", "开发人天", kind="float"),
    ])


@router.get("/template")
def requirement_template(_: AuthUser = Depends(require_perm("requirements", "create"))):
    from urllib.parse import quote

    from fastapi.responses import Response

    from app.services.excel_io import build_template
    content = build_template([_import_sheet()])
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=requirement_template.xlsx; "
                 f"filename*=UTF-8''{quote('需求登记导入模板.xlsx')}"},
    )


@router.post("/import")
async def import_requirements(file: UploadFile, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("requirements", "create"))):
    from app.services.excel_io import parse_sheet
    rows, errors = parse_sheet(await file.read(), _import_sheet())
    domains = {d.name: d for d in db.query(BusinessDomain).filter(
        BusinessDomain.is_deleted.is_(False), BusinessDomain.active.is_(True))}
    person = db.get(OrgMember, user.person_id) if user.person_id else None
    score_keys = ("d1_strategy", "d2_value", "d3_tech", "d4_org", "d5_risk", "d6_speed")
    imported = 0
    for row in rows:
        rownum = row["_row"]
        if row["req_type"] not in REQ_TYPES:
            errors.append({"row": rownum, "error": f"需求类型须为 {'/'.join(REQ_TYPES)}"})
            continue
        domain = domains.get(row["business_domain"])
        if not domain:
            errors.append({"row": rownum, "error": f"业务域「{row['business_domain']}」不存在或已停用"})
            continue
        scores = {k: row.get(k) for k in score_keys if row.get(k) is not None}
        bad = [k for k, v in scores.items() if not 1 <= int(v) <= 5]
        if bad:
            errors.append({"row": rownum, "error": "评分须为 1-5 的整数"})
            continue
        if row.get("decision") and row["decision"] not in DECISIONS:
            errors.append({"row": rownum, "error": f"决议须为 {'/'.join(DECISIONS)}"})
            continue
        r = Requirement(
            requirement_code=gen_code(db, Requirement, "requirement_code", "RQ"),
            title=row["title"], req_type=row["req_type"], business_domain_id=domain.id,
            description=row["description"], source=row.get("source"),
            department=row.get("department"),
            requester_name=row.get("requester_name") or (person.name if person else user.username),
            requester=user.id,
            expected_date=row.get("expected_date"), expected_effect=row.get("expected_effect"),
            business_value_note=row.get("business_value_note"),
            prd_effort=row.get("prd_effort"), dev_effort=row.get("dev_effort"),
            decision=row.get("decision"),
            score_d1_strategy=scores.get("d1_strategy"), score_d2_value=scores.get("d2_value"),
            score_d3_tech=scores.get("d3_tech"), score_d4_org=scores.get("d4_org"),
            score_d5_risk=scores.get("d5_risk"), score_d6_speed=scores.get("d6_speed"),
            status="registered",
            registered_at=datetime.now(),
        )
        db.add(r)
        db.flush()
        process_engine.start_instance(db, "requirement", r.id, {})
        _enter_evaluating(db, r)  # M16：导入需求同样进入评审（已带分的由评审人确认决议）
        imported += 1
    db.commit()
    return ok({"imported": imported, "errors": errors})


def _get_requirement(db: Session, requirement_id: str, user: AuthUser) -> Requirement:
    r = db.get(Requirement, requirement_id)
    if not r or r.is_deleted:
        raise AppError("NOT_FOUND", "需求不存在", 404)
    if _is_requester_only(db, user) and r.requester != user.id:
        raise AppError("FORBIDDEN", "无权查看他人需求", 403)
    return r


@router.get("/{requirement_id}")
def get_requirement(requirement_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    r = _get_requirement(db, requirement_id, user)
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    domains = {d.id: d.name for d in db.query(BusinessDomain).filter(BusinessDomain.is_deleted.is_(False))}
    status_map = status_names(db, "requirement")
    detail = _row(r, db, names, domains, status_map, requirement_scoring.get_config(db))
    project = db.get(Project, r.project_id) if r.project_id else None
    project_relation = None
    if project:
        project_relation = (
            db.query(RecordRelation)
            .filter(
                RecordRelation.is_deleted.is_(False),
                RecordRelation.source_entity_type == "requirement",
                RecordRelation.source_entity_id == r.id,
                RecordRelation.target_entity_type == "project",
                RecordRelation.target_entity_id == project.id,
                RecordRelation.relation_type == "converted_to_project",
            )
            .first()
        )
    tasks = (
        db.query(RequirementTask)
        .filter(RequirementTask.requirement_id == r.id, RequirementTask.is_deleted.is_(False))
        .order_by(RequirementTask.created_at)
        .all()
    )
    linked_problems = db.query(Problem).filter(Problem.source_requirement_id == r.id, Problem.is_deleted.is_(False)).all()
    linked_articles = db.query(KnowledgeArticle).filter(
        KnowledgeArticle.source_requirement_id == r.id, KnowledgeArticle.is_deleted.is_(False)
    ).all()
    scores = (
        db.query(RequirementScore)
        .filter(RequirementScore.requirement_id == r.id, RequirementScore.is_deleted.is_(False))
        .order_by(RequirementScore.created_at)
        .all()
    )
    detail.update({
        "description": r.description, "solution": r.solution,
        "acceptance_criteria": r.acceptance_criteria or [],
        "closure_note": r.closure_note, "remarks": r.remarks,
        "requester": r.requester,
        "expected_effect": r.expected_effect, "business_value_note": r.business_value_note,
        "evaluating_at": r.evaluating_at,
        "analyzing_at": r.analyzing_at, "implementing_at": r.implementing_at,
        "project_name": project.name if project else None,
        "project_relation_reason": project_relation.reason if project_relation else None,
        "scores": [
            {"id": s.id, "reviewer_name": s.reviewer_name, "reviewer_role": s.reviewer_role,
             "d1_strategy": s.d1_strategy, "d2_value": s.d2_value, "d3_tech": s.d3_tech,
             "d4_org": s.d4_org, "d5_risk": s.d5_risk, "d6_speed": s.d6_speed,
             "is_consensus": s.is_consensus, "comment": s.comment, "created_at": s.created_at}
            for s in scores
        ],
        "tasks": [
            {"id": t.id, "name": t.name, "description": t.description,
             "assignee": t.assignee, "assignee_name": names.get(t.assignee),
             "plan_date": t.plan_date, "plan_effort": t.plan_effort, "actual_effort": t.actual_effort,
             "status": t.status, "done_at": t.done_at}
            for t in tasks
        ],
        "handover": {
            "problems": [{"id": p.id, "problem_code": p.problem_code, "title": p.title} for p in linked_problems],
            "articles": [{"id": a.id, "article_code": a.article_code, "title": a.title} for a in linked_articles],
        },
        # M31：需求状态全程由编排驱动（决议/转开发/转项目/流程闭环/主动关闭均有专门动作）——
        # 手动状态按钮仅 admin（修数据口子）
        "allowed_transitions": [] if r.is_example or not _is_req_admin(db, user) else [
            {"to": code, "to_name": status_map.get(code, code)}
            for code in allowed_targets(db, "requirement", r.status, user)
        ],
        "can_close": _can_close_requirement(db, user, r) and not r.is_example and r.status not in ("closed", "cancelled"),
        "process": process_engine.instance_view(db, "requirement", r.id),
        "can_edit": (not r.is_example) and has_perm(db, user, "requirements", "edit"),
        "can_manage_tasks": _can_manage_requirement_tasks(db, user, r),
        "can_delete_tasks": _can_delete_requirement_tasks(db, user),
    })
    return ok(detail)


@router.patch("/{requirement_id}")
def update_requirement(requirement_id: str, body: RequirementUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("requirements", "edit"))):
    r = _get_requirement(db, requirement_id, user)
    ensure_not_example(r)
    if r.status in ("closed", "cancelled"):
        raise AppError("REQ_FINAL", "终态需求不可编辑")
    data = body.model_dump(exclude_unset=True)
    if data.get("moscow") and data["moscow"] not in MOSCOW:
        raise AppError("INVALID_MOSCOW", "优先级必须为 M/S/C/W")
    if data.get("req_type") and data["req_type"] not in REQ_TYPES:
        raise AppError("INVALID_TYPE", f"需求类型必须为 {'/'.join(REQ_TYPES)}")
    if data.get("solution_type") and data["solution_type"] not in (
        requirement_scoring.SOLUTION_SECONDARY, requirement_scoring.SOLUTION_NEW_SYSTEM,
    ):
        raise AppError("INVALID_SOLUTION_TYPE", "方案类型必须为 二次开发/新购系统")
    if data.get("project_id") and not db.get(Project, data["project_id"]):
        raise AppError("NOT_FOUND", "关联项目不存在", 404)
    for df in ("target_date", "expected_date"):
        if data.get(df):
            data[df] = _date.fromisoformat(str(data[df]))
    for k, v in data.items():
        setattr(r, k, v)
    audit(db, "requirement", r.id, "update", user, {"fields": list(data.keys())})
    db.commit()
    return ok({"id": r.id})


@router.delete("/{requirement_id}")
def delete_requirement(requirement_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("requirements", "delete"))):
    """删除需求（M21，软删；delete 权限默认仅 admin）：级联软删开发任务清单与流程实例。"""
    r = db.get(Requirement, requirement_id)
    if not r or r.is_deleted:
        raise AppError("NOT_FOUND", "需求不存在", 404)
    ensure_example_delete_allowed(r, db, actor)
    from app.models import ProcessInstance, ProcessTask, RequirementTask

    r.is_deleted = True
    stats = {"tasks": 0, "process_instances": 0}
    for task in db.query(RequirementTask).filter(RequirementTask.requirement_id == r.id, RequirementTask.is_deleted.is_(False)):
        task.is_deleted = True
        stats["tasks"] += 1
    for inst in db.query(ProcessInstance).filter(
        ProcessInstance.entity_type == "requirement",
        ProcessInstance.entity_id == r.id,
        ProcessInstance.is_deleted.is_(False),
    ):
        inst.is_deleted = True
        stats["process_instances"] += 1
        for ptask in db.query(ProcessTask).filter(ProcessTask.instance_id == inst.id, ProcessTask.is_deleted.is_(False)):
            ptask.is_deleted = True
    audit(db, "requirement", r.id, "delete", actor, {"code": r.requirement_code, **stats})
    db.commit()
    return ok({"id": r.id, **stats})


def _is_req_admin(db: Session, user: AuthUser) -> bool:
    from app.services.rbac import actor_keys

    return ADMIN in actor_keys(db, user)


def _can_close_requirement(db: Session, user: AuthUser, r: Requirement) -> bool:
    """关闭需求权限（M28）：admin 恒可强关；登记人（提出人）本人可关（理由+审计）；
    处理节点无权关闭——走完流程自动闭环。"""
    from app.services.rbac import actor_keys

    if ADMIN in actor_keys(db, user):
        return True
    return bool(r.requester and r.requester == user.id)


class RequirementCloseIn(BaseModel):
    """主动关闭需求（M28）：理由必填（≥5 字），审计留痕。"""

    reason: str = Field(min_length=5, max_length=500)


@router.post("/{requirement_id}/close")
def close_requirement(requirement_id: str, body: RequirementCloseIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    """登记人/管理员主动关闭需求 → 已取消（与评审驳回同终态）；流程实例随单收尾。"""
    r = _get_requirement(db, requirement_id, user)
    ensure_not_example(r)
    if r.status in ("closed", "cancelled"):
        raise AppError("REQ_FINAL", "需求已是终态")
    if not _can_close_requirement(db, user, r):
        raise AppError(
            "FORCE_CLOSE_FORBIDDEN",
            "仅需求提出人本人可主动关闭（须写明理由）；处理节点请完成流程步骤，走完流程自动闭环。强制关闭请联系系统管理员",
            403,
        )
    path = closure_path(db, "requirement", r.status, user, dst="cancelled", ignore_roles=True)
    if path:
        for to in path:
            wf_transition(db, r, "requirement", to, {}, user, system=True)
    else:  # 状态机不可达时按管理动作直接落终态（登记人撤回不应被配置卡死）
        r.status = "cancelled"
    now = datetime.now()
    r.closed_at = now
    r.closure_note = f"[主动关闭] {body.reason}"
    process_engine.finalize_instance(db, "requirement", r.id, f"需求已主动关闭：{body.reason}"[:500])
    audit(db, "requirement", r.id, "close", user, {"code": r.requirement_code, "reason": body.reason})
    if r.owner:
        notifier.notify(db, "requirement.cancelled", "requirement", r.id, [r.owner],
                        f"需求已关闭：{r.requirement_code} {r.title}",
                        f"关闭理由：{body.reason}", link=f"/requirements/{r.id}")
    publish(db, "requirement.cancelled", "requirement", r.id, {})
    db.commit()
    return ok({"id": r.id, "status": r.status})


@router.post("/{requirement_id}/transition")
def transition_requirement(requirement_id: str, body: TransitionIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("requirements", "edit"))):
    r = _get_requirement(db, requirement_id, user)
    ensure_not_example(r)
    if not _is_req_admin(db, user):
        # M31：需求状态由评分决议/转开发/转项目/流程闭环等专门动作驱动，手动流转仅 admin
        raise AppError("USE_PROCESS_STEP", "请使用评审决议、转开发/转项目或完成流程步骤推进，需求状态将自动同步", 403)
    # 阶段门校验
    if body.to == "analyzing" and r.status == "evaluating":
        # 评估门：从评估进入分析，必须已完成六维评分且决议为「立项」
        if requirement_scoring.compute_weighted_total(requirement_scoring.requirement_scores(r)) is None:
            raise AppError("EVAL_INCOMPLETE", "进入分析前需完成六维评分")
        if r.decision != "通过":
            raise AppError("EVAL_NOT_APPROVED", "评估决议须为「通过」才能进入分析（搁置/驳回请转搁置或取消）")
    if body.to == "implementing":
        owner = body.fields.get("owner") or r.owner
        if not owner:
            raise AppError("STAGE_FIELD_REQUIRED", "进入实现前需完成分析：负责人必填")
        require_it_member_if_configured(db, owner, "需求负责人")
    if body.to == "closed":
        criteria = r.acceptance_criteria or []
        if criteria and not all(c.get("checked") for c in criteria):
            raise AppError("ACCEPTANCE_PENDING", "验收标准未全部通过，不能关闭（有遗留请先转出问题或填写关闭说明）")
    from_code, to = wf_transition(db, r, "requirement", body.to, body.fields, user)
    now = datetime.now()
    if to == "evaluating" and not r.evaluating_at:
        r.evaluating_at = now
    if to == "analyzing" and not r.analyzing_at:
        r.analyzing_at = now
    if to == "implementing" and not r.implementing_at:
        r.implementing_at = now
    if to == "closed":
        r.closed_at = now
        publish(db, "requirement.closed", "requirement", r.id, {})
    if to in ("closed", "cancelled"):
        process_engine.finalize_instance(db, "requirement", r.id, "需求已终态，流程随单收尾")  # M24
    publish(db, f"requirement.{to}", "requirement", r.id, {})
    # 通知提出人阶段变化
    if r.requester and r.requester != user.id:
        requester_user = db.get(AuthUser, r.requester)
        if requester_user and requester_user.person_id:
            status_map = status_names(db, "requirement")
            notifier.notify(db, "requirement.stage_changed", "requirement", r.id,
                            [requester_user.person_id],
                            f"需求进入「{status_map.get(to, to)}」：{r.requirement_code} {r.title}",
                            link=f"/requirements/{r.id}")
    db.commit()
    return ok({"id": r.id, "status": r.status})


# ---------- 评估阶段：六维评分与决议 ----------

@router.post("/{requirement_id}/score")
def score_requirement(requirement_id: str, body: ScoreIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("requirements", "edit"))):
    """单人共识评分：写入/更新共识评分行并回填需求六维分，返回实时总分与象限。"""
    r = _get_requirement(db, requirement_id, user)
    ensure_not_example(r)
    if r.status in ("closed", "cancelled"):
        raise AppError("REQ_FINAL", "终态需求不可评分")
    data = body.model_dump(exclude_unset=True)
    _validate_scores(data)
    if data.get("decision") and data["decision"] not in DECISIONS:
        raise AppError("INVALID_DECISION", f"决议必须为 {'/'.join(DECISIONS)}")
    dims = {k: data[k] for k in ("d1_strategy", "d2_value", "d3_tech", "d4_org", "d5_risk", "d6_speed") if k in data}
    # 回填需求六维分
    field_map = {"d1_strategy": "score_d1_strategy", "d2_value": "score_d2_value", "d3_tech": "score_d3_tech",
                 "d4_org": "score_d4_org", "d5_risk": "score_d5_risk", "d6_speed": "score_d6_speed"}
    for k, v in dims.items():
        setattr(r, field_map[k], v)
    if "decision" in data:
        r.decision = data["decision"]
    # M16 评估门：决议按象限约束——「重新评估」象限仅可 搁置/驳回；其余象限方可立项；
    # 驳回=关闭需求，必填理由（≥5 字）
    cfg = requirement_scoring.get_config(db)
    scores_now = requirement_scoring.requirement_scores(r)
    quadrant = requirement_scoring.compute_quadrant(scores_now, cfg.thresholds, cfg.weights)
    if r.decision == "通过":
        if quadrant is None:
            raise AppError("EVAL_INCOMPLETE", "进入分析前需完成六维评分")
        if quadrant == requirement_scoring.QUADRANT_REEVALUATE:
            raise AppError("QUADRANT_REJECTED", "评分落入「重新评估」象限，仅可选择 搁置（补充后重评）或 驳回（关闭）")
    if r.decision == "驳回" and len((data.get("comment") or "").strip()) < 5:
        raise AppError("REASON_REQUIRED", "驳回将关闭需求，必须填写理由（至少 5 个字）")
    # upsert 共识评分行
    person = db.get(OrgMember, user.person_id) if user.person_id else None
    row = (
        db.query(RequirementScore)
        .filter(RequirementScore.requirement_id == r.id, RequirementScore.is_consensus.is_(True),
                RequirementScore.is_deleted.is_(False))
        .first()
    )
    if not row:
        row = RequirementScore(requirement_id=r.id, is_consensus=True)
        db.add(row)
    row.reviewer_id = user.id
    row.reviewer_name = person.name if person else user.username
    for k, v in dims.items():
        setattr(row, k, v)
    if "comment" in data:
        row.comment = data["comment"]
    audit(db, "requirement", r.id, "score", user, {"decision": r.decision})

    # M16：保存决议即自动流转（评审动作一步到位）
    flowed_to = None
    if r.status == "evaluating" and r.decision:
        now = datetime.now()
        if r.decision == "通过":
            wf_transition(db, r, "requirement", "analyzing", {}, user)
            if not r.analyzing_at:
                r.analyzing_at = now
            _complete_review_step(db, r, user, f"评审通过（象限：{quadrant}）")
            _assign_solution_review(db, r)  # 产品 leader 主责、开发 leader 知会
            flowed_to = "analyzing"
        elif r.decision == "搁置":
            wf_transition(db, r, "requirement", "on_hold", {}, user)
            if r.requester:
                ru = db.get(AuthUser, r.requester)
                if ru and ru.person_id:
                    notifier.notify(db, "requirement.on_hold", "requirement", r.id, [ru.person_id],
                                    f"需求已搁置：{r.requirement_code} {r.title}",
                                    f"评审意见：{(data.get('comment') or '').strip() or '待补充价值论证后重新评审'}",
                                    link=f"/requirements/{r.id}")
            flowed_to = "on_hold"
        elif r.decision == "驳回":
            wf_transition(db, r, "requirement", "cancelled", {}, user)
            # M24：驳回=需求终态——收尾整个流程实例（评审任务记驳回理由），
            # 不再走 _complete_review_step（那会推进流程、给产品 leader 派发方案评估任务）
            process_engine.finalize_instance(db, "requirement", r.id,
                                             f"评审驳回，需求关闭：{(data.get('comment') or '').strip()}"[:500])
            r.closure_note = f"[评审驳回] {(data.get('comment') or '').strip()}"
            r.closed_at = now
            if r.requester:
                ru = db.get(AuthUser, r.requester)
                if ru and ru.person_id:
                    notifier.notify(db, "requirement.rejected", "requirement", r.id, [ru.person_id],
                                    f"需求评审未通过：{r.requirement_code} {r.title}",
                                    f"驳回理由：{(data.get('comment') or '').strip()}",
                                    link=f"/requirements/{r.id}")
            flowed_to = "cancelled"
        if flowed_to:
            publish(db, f"requirement.{flowed_to}", "requirement", r.id, {})
    db.commit()
    scores = requirement_scoring.requirement_scores(r)
    return ok({
        "id": r.id, "decision": r.decision, "status": r.status, "flowed_to": flowed_to,
        "weighted_total": requirement_scoring.compute_weighted_total(scores, cfg.weights),
        "quadrant": requirement_scoring.compute_quadrant(scores, cfg.thresholds, cfg.weights),
        **scores,
    })


class ToProjectIn(BaseModel):
    pm_id: str


@router.post("/{requirement_id}/to-project")
def route_to_project(requirement_id: str, body: ToProjectIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("requirements", "edit"))):
    """转项目管理（M16）：仅 route=转项目管理 的需求可转；指派 PM→通知其备章程建项目并关联本需求。"""
    r = _get_requirement(db, requirement_id, user)
    ensure_not_example(r)
    if r.status != "analyzing":
        raise AppError("ROUTE_STAGE", "仅「方案评估（分析中）」阶段可执行转项目")
    cfg = requirement_scoring.get_config(db)
    route = requirement_scoring.compute_route(r.solution_type, r.dev_effort, cfg.effort_threshold)
    if route != requirement_scoring.ROUTE_PROJECT:
        raise AppError("ROUTE_NOT_PROJECT",
                       "当前方案不满足转项目条件（需 新购系统 或 二开人天≥阈值），请先完善方案类型与开发人天")
    pm = db.get(OrgMember, body.pm_id)
    if not pm or pm.is_deleted:
        raise AppError("NOT_FOUND", "项目经理不存在", 404)
    require_it_member_if_configured(db, body.pm_id, "项目经理")
    r.owner = pm.id
    wf_transition(db, r, "requirement", "implementing", {}, user)
    if not r.implementing_at:
        r.implementing_at = datetime.now()
    # 推进流程：完成「方案评估」步骤 → 「实现交付」任务指派给项目经理（跟踪项目交付）
    _complete_review_step(db, r, user, f"转项目管理，项目经理：{pm.name}")
    task = _current_process_task(db, r.id)
    if task:
        task.assignee = pm.id
    notifier.notify(db, "requirement.to_project", "requirement", r.id, [pm.id],
                    f"需求转项目：{r.requirement_code} {r.title}",
                    "您被指派为项目经理。请准备项目章程，在「项目管理」创建项目并关联本需求；项目验收关闭后需求将自动闭环。",
                    link=f"/requirements/{r.id}")
    audit(db, "requirement", r.id, "to_project", user, {"pm": pm.name})
    publish(db, "requirement.to_project", "requirement", r.id, {"pm_id": pm.id})
    db.commit()
    return ok({"id": r.id, "status": r.status, "owner": r.owner})


class ToDevIn(BaseModel):
    owner_id: str


@router.post("/{requirement_id}/to-dev")
def route_to_dev(requirement_id: str, body: ToDevIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("requirements", "edit"))):
    """转开发实现（M16.2，与转项目对称）：指派开发负责人→进入实现→通知其登记任务清单排期。"""
    r = _get_requirement(db, requirement_id, user)
    ensure_not_example(r)
    if r.status != "analyzing":
        raise AppError("ROUTE_STAGE", "仅「方案评估（分析中）」阶段可执行转开发实现")
    cfg = requirement_scoring.get_config(db)
    route = requirement_scoring.compute_route(r.solution_type, r.dev_effort, cfg.effort_threshold)
    if route != requirement_scoring.ROUTE_DEV:
        raise AppError("ROUTE_NOT_DEV",
                       "当前方案不满足转开发条件（需 二次开发 且 人天<阈值）；新购或超阈值请走「转项目管理」")
    owner = db.get(OrgMember, body.owner_id)
    if not owner or owner.is_deleted:
        raise AppError("NOT_FOUND", "开发负责人不存在", 404)
    require_it_member_if_configured(db, body.owner_id, "开发负责人")
    r.owner = owner.id
    wf_transition(db, r, "requirement", "implementing", {}, user)
    if not r.implementing_at:
        r.implementing_at = datetime.now()
    # 推进流程：完成「方案评估」步骤 → 「实现交付」任务指派给开发负责人
    _complete_review_step(db, r, user, f"转开发实现，开发负责人：{owner.name}")
    task = _current_process_task(db, r.id)
    if task:
        task.assignee = owner.id
    notifier.notify(db, "requirement.to_dev", "requirement", r.id, [owner.id],
                    f"需求转开发实现：{r.requirement_code} {r.title}",
                    "您被指派为开发负责人。请在「需求管理 → 任务跟踪」登记开发任务清单并排期（优先级按六维评分排序）。",
                    link="/requirements/tasks")
    audit(db, "requirement", r.id, "to_dev", user, {"owner": owner.name})
    publish(db, "requirement.to_dev", "requirement", r.id, {"owner_id": owner.id})
    db.commit()
    return ok({"id": r.id, "status": r.status, "owner": r.owner})


# ---------- 实现中任务清单（跨需求聚合，排期/实现阶段） ----------

@router.get("/tasks/active")
def active_tasks(
    scope: str = "", status: str = "",
    db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("req_tasks", "view")),
):
    """任务跟踪清单（M17.2 独立授权：业务用户不可见）：任务/处理人/关联需求/进度。"""
    q = (
        db.query(RequirementTask, Requirement)
        .join(Requirement, RequirementTask.requirement_id == Requirement.id)
        .filter(
            RequirementTask.is_deleted.is_(False), Requirement.is_deleted.is_(False),
            Requirement.status.in_(("analyzing", "implementing")),
        )
    )
    if scope == "mine" and user.person_id:
        q = q.filter(RequirementTask.assignee == user.person_id)
    if status:
        q = q.filter(RequirementTask.status == status)
    rows = q.all()
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    domains = {d.id: d.name for d in db.query(BusinessDomain).filter(BusinessDomain.is_deleted.is_(False))}
    status_map = status_names(db, "requirement")
    cfg = requirement_scoring.get_config(db)

    # M16：排期优先级 = 六维加权总分（高分需求的任务在前），同分按计划日期
    def _prio(pair):
        t, r = pair
        total = requirement_scoring.compute_weighted_total(
            requirement_scoring.requirement_scores(r), cfg.weights)
        return (-(total if total is not None else -1), t.plan_date is None, t.plan_date or _date.max, t.status)

    rows = sorted(rows, key=_prio)
    return ok([
        {
            "id": t.id, "name": t.name, "description": t.description,
            "assignee": t.assignee, "assignee_name": names.get(t.assignee),
            "plan_date": t.plan_date, "plan_effort": t.plan_effort, "actual_effort": t.actual_effort,
            "status": t.status, "done_at": t.done_at,
            "requirement_id": r.id, "requirement_code": r.requirement_code,
            "requirement_title": r.title, "requirement_status": r.status,
            "requirement_status_name": status_map.get(r.status, r.status),
            "requirement_owner_name": names.get(r.owner),
            "business_domain_name": domains.get(r.business_domain_id),
            "moscow": r.moscow,
            "weighted_total": requirement_scoring.compute_weighted_total(
                requirement_scoring.requirement_scores(r), cfg.weights),
            "quadrant": requirement_scoring.compute_quadrant(
                requirement_scoring.requirement_scores(r), cfg.thresholds, cfg.weights),
            "can_manage_tasks": _can_manage_requirement_tasks(db, user, r),
        }
        for t, r in rows
    ])


# ---------- 实现阶段：任务分解 ----------

def _require_task_perm(db: Session, user: AuthUser, requirement: Requirement | None = None):
    """任务维护权限：全局编辑者或实现中需求负责人。"""
    if not requirement or not _can_manage_requirement_tasks(db, user, requirement):
        raise AppError("FORBIDDEN", "无任务维护权限（需需求/任务编辑权限，或为实现中需求负责人）", 403)


@router.post("/{requirement_id}/tasks")
def create_task(requirement_id: str, body: TaskIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    r = _get_requirement(db, requirement_id, user)
    ensure_not_example(r)
    _require_task_perm(db, user, r)
    from datetime import date as _date

    task = RequirementTask(
        requirement_id=r.id, name=body.name, description=body.description, assignee=body.assignee,
        plan_date=_date.fromisoformat(body.plan_date) if body.plan_date else None,
        plan_effort=body.plan_effort,
    )
    db.add(task)
    db.flush()
    audit(db, "requirement_task", task.id, "create", user, {"name": body.name})
    if task.assignee != user.person_id:
        notifier.notify(db, "requirement.task_assigned", "requirement", r.id, [task.assignee],
                        f"需求任务指派：{r.title} / {task.name}", link=f"/requirements/{r.id}")
    db.commit()
    return ok({"id": task.id})


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, body: TaskUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    task = db.get(RequirementTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "任务不存在", 404)
    requirement = db.get(Requirement, task.requirement_id)
    ensure_not_example(requirement)
    data = body.model_dump(exclude_unset=True)
    if data.get("assignee"):
        require_it_member_if_configured(db, data["assignee"], "需求任务负责人")
    is_assignee = user.person_id and task.assignee == user.person_id
    can_manage = _can_manage_requirement_tasks(db, user, requirement)
    if not can_manage and not (is_assignee and set(data) <= {"status", "actual_effort"}):
        raise AppError("FORBIDDEN", "仅需求负责人可维护任务；任务负责人只能更新自己的状态和实际工时", 403)
    if data.get("status") and data["status"] not in ("待处理", "进行中", "已完成"):
        raise AppError("INVALID_STATUS", "状态必须为 待处理/进行中/已完成")
    if "plan_date" in data and data["plan_date"]:
        from datetime import date as _date

        data["plan_date"] = _date.fromisoformat(str(data["plan_date"]))
    for k, v in data.items():
        setattr(task, k, v)
    if data.get("status") == "已完成" and not task.done_at:
        task.done_at = datetime.now()
        publish(db, "requirement.task_completed", "requirement", task.requirement_id, {"task_id": task.id})
    audit(db, "requirement_task", task.id, "update", user, {"fields": list(data.keys())})
    db.commit()
    return ok({"id": task.id})


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    if not _can_delete_requirement_tasks(db, user):
        raise AppError("FORBIDDEN", "无任务删除权限（需 需求管理编辑 或 任务跟踪编辑）", 403)
    task = db.get(RequirementTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "任务不存在", 404)
    ensure_example_delete_allowed(db.get(Requirement, task.requirement_id), db, user)
    task.is_deleted = True
    audit(db, "requirement_task", task.id, "delete", user, {"name": task.name})
    db.commit()
    return ok({"id": task.id})


# ---------- 关闭收尾：一键转出（跨域闭环） ----------

@router.post("/{requirement_id}/to-problem")
def handover_problem(requirement_id: str, body: ToProblemIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("requirements", "edit"))):
    """转出是需求收尾动作，随需求编辑权（不要求问题域权限）。"""
    r = _get_requirement(db, requirement_id, user)
    ensure_not_example(r)
    problem = Problem(
        problem_code=gen_code(db, Problem, "problem_code", "PB"),
        title=body.title or f"[需求遗留] {r.title}"[:200],
        description=f"[来自需求 {r.requirement_code}]\n\n{body.description}",
        priority="P3", owner=r.owner, source_requirement_id=r.id,
    )
    db.add(problem)
    db.flush()
    process_engine.start_instance(db, "problem", problem.id, {}, preferred_assignee=problem.owner)
    audit(db, "problem", problem.id, "create_from_requirement", user, {"requirement": r.requirement_code})
    publish(db, "requirement.handover_problem", "requirement", r.id, {"problem_id": problem.id})
    db.commit()
    return ok({"problem_id": problem.id, "problem_code": problem.problem_code})


@router.post("/{requirement_id}/to-knowledge")
def handover_knowledge(requirement_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("requirements", "edit"))):
    r = _get_requirement(db, requirement_id, user)
    ensure_not_example(r)
    person = db.get(OrgMember, user.person_id) if user.person_id else None
    criteria_md = "\n".join(f"- [{'x' if c.get('checked') else ' '}] {c.get('text', '')}" for c in (r.acceptance_criteria or []))
    content = (
        f"# {r.title}\n\n> 由需求 {r.requirement_code} 经验沉淀生成\n\n"
        f"## 需求背景\n\n{r.description}\n\n"
        + (f"## 解决方案\n\n{r.solution}\n\n" if r.solution else "")
        + (f"## 验收标准\n\n{criteria_md}\n" if criteria_md else "")
    )
    article = KnowledgeArticle(
        article_code=gen_code(db, KnowledgeArticle, "article_code", "KB"),
        title=f"{r.title}（经验沉淀）"[:200], content=content, content_format="markdown",
        status="draft", tags=["需求沉淀"], author=user.id,
        author_name=person.name if person else user.username,
        source_requirement_id=r.id,
    )
    db.add(article)
    db.flush()
    audit(db, "knowledge_article", article.id, "create_from_requirement", user, {"requirement": r.requirement_code})
    publish(db, "requirement.handover_knowledge", "requirement", r.id, {"article_id": article.id})
    db.commit()
    return ok({"article_id": article.id, "article_code": article.article_code})
