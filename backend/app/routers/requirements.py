"""需求管理路由（PRD §7）：五阶段协同漏斗（登记→评估→分析→实现→关闭）+ 一键转出闭环。"""
from datetime import date as _date
from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_not_example
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
    Requirement,
    RequirementScore,
    RequirementScoringConfig,
    RequirementTask,
)
from app.schemas.common import ok, paginate
from app.services import process_engine, requirement_scoring
from app.services.audit import audit
from app.services.codes import gen_code
from app.services.permissions import has_perm
from app.services.rbac import effective_roles
from app.services.workflow import allowed_targets, status_names
from app.services.workflow import transition as wf_transition

router = APIRouter(prefix="/api/requirements", tags=["requirements"])

REQ_TYPES = ("业务", "功能", "数据", "集成", "合规")
MOSCOW = ("M", "S", "C", "W")
DECISIONS = ("立项", "搁置", "驳回")


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


class TransitionIn(BaseModel):
    to: str
    fields: dict = {}


class TaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    assignee: str
    plan_date: str | None = None


class TaskUpdate(BaseModel):
    name: str | None = None
    assignee: str | None = None
    plan_date: str | None = None
    status: str | None = None


class ToProblemIn(BaseModel):
    title: str | None = None
    description: str = Field(min_length=1)


def _is_requester_only(db: Session, user: AuthUser) -> bool:
    return effective_roles(db, user) == {REQUESTER}


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
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    domains = {d.id: d.name for d in db.query(BusinessDomain).filter(BusinessDomain.is_deleted.is_(False))}
    status_map = status_names(db, "requirement")
    cfg = requirement_scoring.get_config(db)
    return ok([_row(r, db, names, domains, status_map, cfg) for r in items], total=total, page=page)


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
    if body.req_type not in REQ_TYPES:
        raise AppError("INVALID_TYPE", f"需求类型必须为 {'/'.join(REQ_TYPES)}")
    domain = db.get(BusinessDomain, body.business_domain_id)
    if not domain or domain.is_deleted or not domain.active:
        raise AppError("NOT_FOUND", "所属业务域不存在或已停用", 404)
    person = db.get(OrgMember, user.person_id) if user.person_id else None
    data = body.model_dump()
    if data.get("expected_date"):
        data["expected_date"] = _date.fromisoformat(str(data["expected_date"]))
    r = Requirement(
        **data,
        requirement_code=gen_code(db, Requirement, "requirement_code", "RQ"),
        status="registered", registered_at=datetime.now(),
        requester=user.id, requester_name=person.name if person else user.username,
    )
    db.add(r)
    db.flush()
    process_engine.start_instance(db, "requirement", r.id, {})
    audit(db, "requirement", r.id, "create", user, {"code": r.requirement_code})
    publish(db, "requirement.registered", "requirement", r.id, {})
    _notify_pdm(db, r)
    db.commit()
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
        "defaults": {
            "weights": requirement_scoring.DEFAULT_WEIGHTS,
            "thresholds": requirement_scoring.DEFAULT_THRESHOLDS,
            "rubric": requirement_scoring.DEFAULT_RUBRIC,
            "role_weights": requirement_scoring.DEFAULT_ROLE_WEIGHTS,
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
    for f in ("thresholds", "rubric", "role_weights"):
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
        fully_scored = len(scores) == 6
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
            status="evaluating" if fully_scored else "registered",
            registered_at=datetime.now(),
            evaluating_at=datetime.now() if fully_scored else None,
        )
        db.add(r)
        db.flush()
        process_engine.start_instance(db, "requirement", r.id, {})
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
        "scores": [
            {"id": s.id, "reviewer_name": s.reviewer_name, "reviewer_role": s.reviewer_role,
             "d1_strategy": s.d1_strategy, "d2_value": s.d2_value, "d3_tech": s.d3_tech,
             "d4_org": s.d4_org, "d5_risk": s.d5_risk, "d6_speed": s.d6_speed,
             "is_consensus": s.is_consensus, "comment": s.comment, "created_at": s.created_at}
            for s in scores
        ],
        "tasks": [
            {"id": t.id, "name": t.name, "assignee": t.assignee, "assignee_name": names.get(t.assignee),
             "plan_date": t.plan_date, "status": t.status, "done_at": t.done_at}
            for t in tasks
        ],
        "handover": {
            "problems": [{"id": p.id, "problem_code": p.problem_code, "title": p.title} for p in linked_problems],
            "articles": [{"id": a.id, "article_code": a.article_code, "title": a.title} for a in linked_articles],
        },
        "allowed_transitions": [] if r.is_example else [
            {"to": code, "to_name": status_map.get(code, code)}
            for code in allowed_targets(db, "requirement", r.status, user)
        ],
        "process": process_engine.instance_view(db, "requirement", r.id),
        "can_edit": (not r.is_example) and has_perm(db, user, "requirements", "edit"),
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


@router.post("/{requirement_id}/transition")
def transition_requirement(requirement_id: str, body: TransitionIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("requirements", "edit"))):
    r = _get_requirement(db, requirement_id, user)
    ensure_not_example(r)
    # 阶段门校验
    if body.to == "analyzing" and r.status == "evaluating":
        # 评估门：从评估进入分析，必须已完成六维评分且决议为「立项」
        if requirement_scoring.compute_weighted_total(requirement_scoring.requirement_scores(r)) is None:
            raise AppError("EVAL_INCOMPLETE", "进入分析前需完成六维评分")
        if r.decision != "立项":
            raise AppError("EVAL_NOT_APPROVED", "评估决议须为「立项」才能进入分析（搁置/驳回请转搁置或取消）")
    if body.to == "implementing":
        owner = body.fields.get("owner") or r.owner
        if not owner:
            raise AppError("STAGE_FIELD_REQUIRED", "进入实现前需完成分析：负责人必填")
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
    db.commit()
    cfg = requirement_scoring.get_config(db)
    scores = requirement_scoring.requirement_scores(r)
    return ok({
        "id": r.id, "decision": r.decision,
        "weighted_total": requirement_scoring.compute_weighted_total(scores, cfg.weights),
        "quadrant": requirement_scoring.compute_quadrant(scores, cfg.thresholds, cfg.weights),
        **scores,
    })


# ---------- 实现阶段：任务分解 ----------

@router.post("/{requirement_id}/tasks")
def create_task(requirement_id: str, body: TaskIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("requirements", "edit"))):
    r = _get_requirement(db, requirement_id, user)
    ensure_not_example(r)
    from datetime import date as _date

    task = RequirementTask(
        requirement_id=r.id, name=body.name, assignee=body.assignee,
        plan_date=_date.fromisoformat(body.plan_date) if body.plan_date else None,
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
    ensure_not_example(db.get(Requirement, task.requirement_id))
    data = body.model_dump(exclude_unset=True)
    is_assignee = user.person_id and task.assignee == user.person_id
    if not has_perm(db, user, "requirements", "edit"):
        if not (is_assignee and set(data) <= {"status"}):
            raise AppError("FORBIDDEN", "仅任务负责人可更新自己任务的状态；其他修改需需求编辑权限", 403)
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
def delete_task(task_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("requirements", "edit"))):
    task = db.get(RequirementTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "任务不存在", 404)
    ensure_not_example(db.get(Requirement, task.requirement_id))
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
