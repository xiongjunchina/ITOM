"""统一报表中心 API。"""
from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from typing import Literal

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import (
    AuthUser,
    ReportAudience,
    ReportInstance,
    ReportTemplate,
    ReportVersion,
)
from app.schemas.common import ok
from app.services import process_engine
from app.services.audit import audit
from app.services.permissions import has_perm
from app.services.reporting import (
    METRIC_MAP,
    can_view_report,
    drilldown_metric,
    generate_report_version,
    metric_catalog,
    publish_report,
    query_metrics,
    report_version_payload,
    resolve_period,
    _digest,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


class QueryIn(BaseModel):
    metric_codes: list[str] = Field(min_length=1, max_length=50)
    period_start: date
    period_end: date
    filters: dict = {}


class TemplateIn(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=128)
    description: str | None = None
    metric_codes: list[str] = Field(min_length=1, max_length=50)
    default_period_type: Literal["week", "month", "quarter", "half_year", "year", "custom"] = "month"
    default_filters: dict = {}


class TemplatePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    description: str | None = None
    metric_codes: list[str] | None = Field(default=None, min_length=1, max_length=50)
    default_period_type: Literal["week", "month", "quarter", "half_year", "year", "custom"] | None = None
    default_filters: dict | None = None
    active: bool | None = None


class ReportCreate(BaseModel):
    template_id: str
    title: str = Field(min_length=2, max_length=200)
    period_type: Literal["week", "month", "quarter", "half_year", "year", "custom"] | None = None
    anchor: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    filters: dict = {}


class NarrativePatch(BaseModel):
    narrative: dict


class PublishIn(BaseModel):
    audience: list[dict] = Field(default_factory=list, max_length=200)


def _template_row(row: ReportTemplate, db: Session, actor: AuthUser) -> dict:
    allowed = {item["code"] for item in metric_catalog(db, actor)}
    codes = row.metric_codes or []
    return {
        "id": row.id, "code": row.code, "name": row.name, "description": row.description,
        "domains": row.domains or [], "metric_codes": codes,
        "available_metric_codes": [code for code in codes if code in allowed],
        "restricted_metric_count": sum(1 for code in codes if code not in allowed),
        "default_filters": row.default_filters or {}, "default_period_type": row.default_period_type,
        "is_system": row.is_system, "active": row.active,
    }


def _report_row(row: ReportInstance) -> dict:
    return {
        "id": row.id, "template_id": row.template_id, "title": row.title,
        "period_type": row.period_type, "period_start": row.period_start, "period_end": row.period_end,
        "filters": row.filters or {}, "status": row.status, "current_version": row.current_version,
        "published_version": row.published_version, "created_by": row.created_by,
        "process_instance_id": row.process_instance_id, "published_at": row.published_at,
        "locked_at": row.locked_at, "created_at": row.created_at,
    }


def _get_report(db: Session, report_id: str) -> ReportInstance:
    row = db.get(ReportInstance, report_id)
    if not row or row.is_deleted:
        raise AppError("REPORT_NOT_FOUND", "报告不存在", 404)
    return row


def _require_owner_or_editor(db: Session, actor: AuthUser, report: ReportInstance):
    if report.created_by != actor.id and not has_perm(db, actor, "reports", "edit"):
        raise AppError("FORBIDDEN", "只有报告创建人或获授权的报表管理员可以修改", 403)


def _selected_version(db: Session, actor: AuthUser, report: ReportInstance) -> ReportVersion:
    version_no = report.current_version if report.created_by == actor.id or has_perm(db, actor, "reports_publish", "view") else report.published_version
    version = db.query(ReportVersion).filter(
        ReportVersion.report_instance_id == report.id, ReportVersion.version == version_no,
        ReportVersion.is_deleted.is_(False),
    ).first()
    if not version:
        raise AppError("REPORT_VERSION_NOT_FOUND", "报告尚未生成可查看版本", 404)
    return version


@router.get("/metrics")
def list_metrics(db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "view"))):
    return ok(metric_catalog(db, actor))


@router.post("/query")
def query(body: QueryIn, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "view"))):
    return ok(query_metrics(db, actor, list(dict.fromkeys(body.metric_codes)), body.period_start, body.period_end, body.filters))


@router.get("/drilldown/{metric_code}")
def drilldown(metric_code: str, period_start: date, period_end: date, limit: int = 200,
              project_id: str = "", portfolio_id: str = "", business_domain_id: str = "",
              ticket_type: str = "", priority: str = "", service_item_id: str = "",
              ci_id: str = "", contract_id: str = "", requirement_id: str = "",
              ticket_id: str = "", problem_id: str = "", subject_type: str = "",
              subject_id: str = "",
              db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "view"))):
    filters = {key: value for key, value in {
        "project_id": project_id, "portfolio_id": portfolio_id, "business_domain_id": business_domain_id,
        "ticket_type": ticket_type, "priority": priority, "service_item_id": service_item_id,
        "ci_id": ci_id, "contract_id": contract_id, "requirement_id": requirement_id,
        "ticket_id": ticket_id, "problem_id": problem_id, "subject_type": subject_type,
        "subject_id": subject_id,
    }.items() if value}
    return ok(drilldown_metric(db, actor, metric_code, period_start, period_end, limit, filters))


@router.get("/templates")
def list_templates(db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "view"))):
    rows = db.query(ReportTemplate).filter(
        ReportTemplate.is_deleted.is_(False), ReportTemplate.active.is_(True)
    ).order_by(ReportTemplate.is_system.desc(), ReportTemplate.created_at).all()
    return ok([_template_row(row, db, actor) for row in rows])


@router.post("/templates")
def create_template(body: TemplateIn, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "create"))):
    if db.query(ReportTemplate).filter(ReportTemplate.code == body.code).first():
        raise AppError("REPORT_TEMPLATE_CODE_EXISTS", "模板编码已存在", 409)
    available = {item["code"] for item in metric_catalog(db, actor)}
    codes = list(dict.fromkeys(body.metric_codes))
    if set(codes) - available:
        raise AppError("REPORT_METRIC_FORBIDDEN", "模板包含当前用户无权使用的指标", 403)
    row = ReportTemplate(
        **body.model_dump(exclude={"metric_codes"}), metric_codes=codes,
        domains=sorted({METRIC_MAP[code].domain for code in codes}), is_system=False,
        active=True, created_by=actor.id,
    )
    db.add(row)
    audit(db, "report_template", row.id, "create", actor, {"code": row.code})
    db.commit()
    db.refresh(row)
    return ok(_template_row(row, db, actor))


@router.patch("/templates/{template_id}")
def patch_template(template_id: str, body: TemplatePatch, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "edit"))):
    row = db.get(ReportTemplate, template_id)
    if not row or row.is_deleted:
        raise AppError("REPORT_TEMPLATE_NOT_FOUND", "报告模板不存在", 404)
    data = body.model_dump(exclude_unset=True)
    if "metric_codes" in data:
        codes = list(dict.fromkeys(data["metric_codes"]))
        available = {item["code"] for item in metric_catalog(db, actor)}
        if set(codes) - available:
            raise AppError("REPORT_METRIC_FORBIDDEN", "模板包含当前用户无权使用的指标", 403)
        data["metric_codes"] = codes
        data["domains"] = sorted({METRIC_MAP[code].domain for code in codes})
    for key, value in data.items():
        setattr(row, key, value)
    audit(db, "report_template", row.id, "update", actor, {"fields": sorted(data)})
    db.commit()
    return ok(_template_row(row, db, actor))


@router.get("")
def list_reports(db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "view"))):
    rows = db.query(ReportInstance).filter(ReportInstance.is_deleted.is_(False)).order_by(ReportInstance.created_at.desc()).all()
    visible = [row for row in rows if can_view_report(db, actor, row)]
    return ok([_report_row(row) for row in visible], total=len(visible))


@router.post("")
def create_report(body: ReportCreate, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "create"))):
    template = db.get(ReportTemplate, body.template_id)
    if not template or template.is_deleted or not template.active:
        raise AppError("REPORT_TEMPLATE_NOT_FOUND", "报告模板不存在或已停用", 404)
    period_type = body.period_type or template.default_period_type
    start, end = resolve_period(period_type, body.anchor, body.period_start, body.period_end)
    row = ReportInstance(
        template_id=template.id, title=body.title, period_type=period_type,
        period_start=start, period_end=end, filters=body.filters, status="draft",
        current_version=0, published_version=0, created_by=actor.id,
    )
    db.add(row)
    db.flush()
    audit(db, "report_instance", row.id, "create", actor, {"template_code": template.code})
    db.commit()
    db.refresh(row)
    return ok(_report_row(row))


@router.get("/{report_id}")
def get_report(report_id: str, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "view"))):
    report = _get_report(db, report_id)
    if not can_view_report(db, actor, report):
        raise AppError("FORBIDDEN", "无权查看该报告", 403)
    version = _selected_version(db, actor, report) if report.current_version else None
    data = _report_row(report)
    data["version"] = report_version_payload(version) if version else None
    if report.created_by == actor.id or has_perm(db, actor, "reports_publish", "view"):
        data["audience"] = [{"subject_type": row.subject_type, "subject_id": row.subject_id} for row in db.query(ReportAudience).filter(
            ReportAudience.report_instance_id == report.id, ReportAudience.is_deleted.is_(False)
        ).all()]
    return ok(data)


@router.post("/{report_id}/generate")
def generate(report_id: str, idempotency_key: str = Header(alias="Idempotency-Key"),
             db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "create"))):
    report = _get_report(db, report_id)
    _require_owner_or_editor(db, actor, report)
    if report.status in {"review", "approved"}:
        raise AppError("REPORT_REVIEW_IN_PROGRESS", "审核中或已审核待发布的报告不能重新生成版本", 409)
    version = generate_report_version(db, actor, report, idempotency_key)
    audit(db, "report_version", version.id, "generate", actor, {"version": version.version, "checksum": version.checksum})
    db.commit()
    return ok(report_version_payload(version))


@router.patch("/{report_id}/narrative")
def patch_narrative(report_id: str, body: NarrativePatch, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "edit"))):
    report = _get_report(db, report_id)
    _require_owner_or_editor(db, actor, report)
    if report.status != "draft" or not report.current_version:
        raise AppError("REPORT_VERSION_LOCKED", "仅草稿版本可以编辑报告说明", 409)
    version = _selected_version(db, actor, report)
    if version.locked_at:
        raise AppError("REPORT_VERSION_LOCKED", "已发布版本不可修改，请生成新版本", 409)
    version.narrative = body.narrative
    version.checksum = _digest({
        "snapshot": version.metric_snapshot, "narrative": version.narrative,
        "formula_versions": version.formula_versions, "version": version.version,
    })
    audit(db, "report_version", version.id, "narrative_update", actor, {"version": version.version})
    db.commit()
    return ok(report_version_payload(version))


@router.post("/{report_id}/submit-review")
def submit_review(report_id: str, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "edit"))):
    report = _get_report(db, report_id)
    _require_owner_or_editor(db, actor, report)
    if report.status != "draft" or not report.current_version:
        raise AppError("REPORT_NOT_DRAFT", "仅已生成的草稿报告可以提交审核", 409)
    instance = process_engine.start_instance(db, "report", report.id, {})
    if not instance:
        raise AppError("REPORT_FLOW_UNAVAILABLE", "正式报告审核流程未启用", 409)
    report.status = "review"
    report.process_instance_id = instance.id
    version = _selected_version(db, actor, report)
    version.status = "review"
    audit(db, "report_instance", report.id, "submit_review", actor, {"version": report.current_version})
    db.commit()
    return ok(_report_row(report))


@router.post("/{report_id}/publish")
def publish(report_id: str, body: PublishIn, db: Session = Depends(get_db), actor: AuthUser = Depends(get_current_user)):
    report = _get_report(db, report_id)
    version = publish_report(db, actor, report, body.audience)
    audit(db, "report_instance", report.id, "publish", actor, {"version": version.version, "audience_count": len(body.audience)})
    db.commit()
    return ok({**_report_row(report), "version": report_version_payload(version)})


@router.get("/{report_id}/versions")
def list_versions(report_id: str, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "view"))):
    report = _get_report(db, report_id)
    if not can_view_report(db, actor, report):
        raise AppError("FORBIDDEN", "无权查看该报告", 403)
    rows = db.query(ReportVersion).filter(
        ReportVersion.report_instance_id == report.id, ReportVersion.is_deleted.is_(False)
    ).order_by(ReportVersion.version.desc()).all()
    if report.created_by != actor.id and not has_perm(db, actor, "reports_publish", "view"):
        rows = [row for row in rows if row.version == report.published_version]
    return ok([report_version_payload(row) for row in rows])


@router.get("/{report_id}/export")
def export_report(report_id: str, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("reports", "view"))):
    report = _get_report(db, report_id)
    if not can_view_report(db, actor, report):
        raise AppError("FORBIDDEN", "无权导出该报告", 403)
    version = _selected_version(db, actor, report)
    workbook = Workbook()
    summary = workbook.active
    summary.title = "报告摘要"
    summary.append(["报告标题", report.title])
    summary.append(["周期", f"{report.period_start.isoformat()} ~ {report.period_end.isoformat()}"])
    summary.append(["版本", version.version])
    summary.append(["校验和", version.checksum])
    summary.append([])
    summary.append(["指标编码", "指标名称", "值", "单位", "数据质量", "公式版本"])
    for item in (version.metric_snapshot or {}).get("metrics", []):
        value = item.get("value")
        if isinstance(value, list):
            value = "; ".join(f"{part.get('key')}={part.get('value')}" for part in value)
        summary.append([item.get("code"), item.get("name_zh"), value, item.get("unit"), item.get("quality"), item.get("formula_version")])
    narrative = workbook.create_sheet("管理说明")
    narrative.append(["章节", "内容"])
    for key, value in (version.narrative or {}).items():
        narrative.append([key, str(value)])
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        for column in sheet.columns:
            width = min(max(len(str(cell.value or "")) for cell in column) + 2, 60)
            sheet.column_dimensions[column[0].column_letter].width = width
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    filename = f"report-{report.id}-v{version.version}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
