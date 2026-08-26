"""统一报表中心 B2：指标口径、项目投入、时效、版本与发布锁定。"""
from datetime import date, datetime, timedelta

from app.db import SessionLocal
from app.core.security import hash_password
from app.models import AuthUser, BusinessDomain, ProcessTask, ReportInstance, Requirement, RolePermission


TODAY = date.today()


def _create_member(client, headers, name: str) -> str:
    response = client.post("/api/members", json={"name": name}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


def _create_project(client, headers, person_id: str) -> str:
    response = client.post("/api/projects", headers=headers, json={
        "name": "报表中心投入分析项目", "pm": person_id,
        "planned_start": str(TODAY - timedelta(days=10)),
        "planned_end": str(TODAY + timedelta(days=20)),
    })
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


def test_metric_catalog_and_no_data_semantics(client, admin_headers):
    catalog = client.get("/api/reports/metrics", headers=admin_headers)
    assert catalog.status_code == 200, catalog.text
    codes = {row["code"] for row in catalog.json()["data"]}
    assert {"project.actual_cost_cny", "requirement.p90_lead_days", "process.avg_cycle_hours"} <= codes

    empty = client.post("/api/reports/query", headers=admin_headers, json={
        "metric_codes": ["itsm.ticket_count", "itsm.avg_resolution_hours"],
        "period_start": "2099-01-01", "period_end": "2099-01-31",
    })
    assert empty.status_code == 200, empty.text
    values = {row["code"]: row for row in empty.json()["data"]["metrics"]}
    assert values["itsm.ticket_count"]["value"] == 0
    assert values["itsm.ticket_count"]["quality"] == "ok"
    assert values["itsm.avg_resolution_hours"]["value"] is None
    assert values["itsm.avg_resolution_hours"]["quality"] == "no_data"


def test_project_investment_precise_amounts_and_effort(client, admin_headers):
    person_id = _create_member(client, admin_headers, "报表投入测试人员")
    project_id = _create_project(client, admin_headers, person_id)

    budget = client.post(f"/api/projects/{project_id}/budget-items", headers=admin_headers, json={
        "category": "hardware", "name": "服务器预算", "amount_cny": "200000.00",
    })
    assert budget.status_code == 200, budget.text
    cost = client.post(f"/api/projects/{project_id}/costs", headers=admin_headers, json={
        "entry_date": str(TODAY), "amount_cny": "12345.67", "category": "hardware",
        "cost_type": "incurred", "supplier": "本地测试供应商",
    })
    assert cost.status_code == 200, cost.text
    effort = client.post(f"/api/projects/{project_id}/effort-entries", headers=admin_headers, json={
        "person_id": person_id, "work_date": str(TODAY), "effort_days": "2.00",
        "role_type": "implementation", "standard_rate_cny_per_day": "1200.00",
    })
    assert effort.status_code == 200, effort.text

    summary = client.get(f"/api/projects/{project_id}/investment-summary", headers=admin_headers)
    assert summary.status_code == 200, summary.text
    data = summary.json()["data"]
    assert data["budget_cny"] == "200000.00"
    assert data["incurred_cost_cny"] == "12345.67"
    assert data["effort_days"] == "2.00"
    assert data["effort_cost_cny"] == "2400.00"

    metrics = client.post("/api/reports/query", headers=admin_headers, json={
        "metric_codes": ["project.budget_cny", "project.actual_cost_cny", "project.effort_days", "project.effort_cost_cny"],
        "period_start": str(TODAY - timedelta(days=30)), "period_end": str(TODAY + timedelta(days=30)),
        "filters": {"project_id": project_id},
    })
    assert metrics.status_code == 200, metrics.text
    values = {row["code"]: row["value"] for row in metrics.json()["data"]["metrics"]}
    assert values["project.budget_cny"] == "200000.00"
    assert values["project.actual_cost_cny"] == "12345.67"
    assert values["project.effort_days"] == "2.00"
    assert values["project.effort_cost_cny"] == "2400.00"


def test_requirement_timeliness_metrics(client, admin_headers):
    with SessionLocal() as db:
        domain = BusinessDomain(code="report-b2-domain", name="报表 B2 隔离业务域", active=True)
        db.add(domain)
        db.flush()
        domain_id = domain.id
        registered = datetime.now() - timedelta(days=10)
        db.add(Requirement(
            requirement_code="RQ-REPORT-B2-001", title="报表时效测试需求", req_type="功能",
            business_domain_id=domain_id, description="用于验证需求处理时效指标",
            status="closed", registered_at=registered, evaluating_at=registered + timedelta(days=1),
            analyzing_at=registered + timedelta(days=3), implementing_at=registered + timedelta(days=5),
            closed_at=registered + timedelta(days=8), target_date=(registered + timedelta(days=9)).date(),
        ))
        db.commit()
    response = client.post("/api/reports/query", headers=admin_headers, json={
        "metric_codes": ["requirement.avg_lead_days", "requirement.p50_lead_days", "requirement.p90_lead_days", "requirement.on_time_rate", "requirement.stage_cycle_days"],
        "period_start": str(TODAY - timedelta(days=30)), "period_end": str(TODAY),
        "filters": {"business_domain_id": domain_id},
    })
    assert response.status_code == 200, response.text
    values = {row["code"]: row["value"] for row in response.json()["data"]["metrics"]}
    assert values["requirement.avg_lead_days"] == 8.0
    assert values["requirement.p50_lead_days"] == 8.0
    assert values["requirement.p90_lead_days"] == 8.0
    assert values["requirement.on_time_rate"] == 100.0
    assert [item["value"] for item in values["requirement.stage_cycle_days"]] == [1.0, 2.0, 2.0, 3.0]


def test_sensitive_metrics_and_drilldown_are_reauthorized(client, admin_headers):
    del admin_headers
    with SessionLocal() as db:
        db.add(AuthUser(
            username="report_viewer_b2", password_hash=hash_password("pass1234"),
            roles=["report_viewer_b2"], is_active=True,
        ))
        db.add_all([
            RolePermission(role_code="report_viewer_b2", module="reports", actions=["view"]),
            RolePermission(role_code="report_viewer_b2", module="projects", actions=["view"]),
            RolePermission(role_code="report_viewer_b2", module="requirements", actions=["view"]),
        ])
        db.commit()
    token = client.post("/api/auth/login", json={"username": "report_viewer_b2", "password": "pass1234"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    catalog = client.get("/api/reports/metrics", headers=headers)
    codes = {row["code"] for row in catalog.json()["data"]}
    assert "project.count" in codes
    assert "project.actual_cost_cny" not in codes
    assert "project.effort_days" not in codes
    forbidden = client.post("/api/reports/query", headers=headers, json={
        "metric_codes": ["project.actual_cost_cny"],
        "period_start": str(TODAY - timedelta(days=30)), "period_end": str(TODAY),
    })
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "REPORT_METRIC_FORBIDDEN"
    drilldown = client.get(
        "/api/reports/drilldown/project.actual_cost_cny",
        headers=headers,
        params={"period_start": str(TODAY - timedelta(days=30)), "period_end": str(TODAY)},
    )
    assert drilldown.status_code == 403
    unknown_filter = client.post("/api/reports/query", headers=headers, json={
        "metric_codes": ["project.count"], "period_start": str(TODAY - timedelta(days=30)),
        "period_end": str(TODAY), "filters": {"raw_sql": "forbidden"},
    })
    assert unknown_filter.status_code == 400
    assert unknown_filter.json()["error"]["code"] == "REPORT_FILTER_UNKNOWN"


def test_report_idempotency_review_publish_lock_and_export(client, admin_headers):
    templates = client.get("/api/reports/templates", headers=admin_headers).json()["data"]
    template = next(row for row in templates if row["code"] == "monthly_management")
    created = client.post("/api/reports", headers=admin_headers, json={
        "template_id": template["id"], "title": "B2 正式月报",
        "period_type": "custom", "period_start": str(TODAY - timedelta(days=30)), "period_end": str(TODAY),
    })
    assert created.status_code == 200, created.text
    report_id = created.json()["data"]["id"]
    headers = {**admin_headers, "Idempotency-Key": "report-b2-generate-001"}
    first = client.post(f"/api/reports/{report_id}/generate", headers=headers)
    again = client.post(f"/api/reports/{report_id}/generate", headers=headers)
    assert first.status_code == 200 and again.status_code == 200
    assert first.json()["data"]["id"] == again.json()["data"]["id"]
    assert first.json()["data"]["checksum"] == again.json()["data"]["checksum"]

    other = client.post("/api/reports", headers=admin_headers, json={
        "template_id": template["id"], "title": "另一个月报",
        "period_type": "custom", "period_start": str(TODAY - timedelta(days=10)), "period_end": str(TODAY),
    }).json()["data"]["id"]
    conflict = client.post(f"/api/reports/{other}/generate", headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    submitted = client.post(f"/api/reports/{report_id}/submit-review", headers=admin_headers)
    assert submitted.status_code == 200, submitted.text
    process_id = submitted.json()["data"]["process_instance_id"]
    with SessionLocal() as db:
        task = db.query(ProcessTask).filter(ProcessTask.instance_id == process_id, ProcessTask.status == "待处理").first()
        assert task is not None
        task_id = task.id
    approved = client.post(f"/api/process-tasks/{task_id}/approve", headers=admin_headers, json={"comment": "同意发布"})
    assert approved.status_code == 200, approved.text
    detail = client.get(f"/api/reports/{report_id}", headers=admin_headers)
    assert detail.json()["data"]["status"] == "approved"

    published = client.post(f"/api/reports/{report_id}/publish", headers=admin_headers, json={
        "audience": [{"subject_type": "role", "subject_id": "cio"}],
    })
    assert published.status_code == 200, published.text
    assert published.json()["data"]["status"] == "published"
    assert published.json()["data"]["version"]["status"] == "locked"

    locked_edit = client.patch(f"/api/reports/{report_id}/narrative", headers=admin_headers, json={"narrative": {"summary": "不可覆盖"}})
    assert locked_edit.status_code == 409
    assert locked_edit.json()["error"]["code"] == "REPORT_VERSION_LOCKED"
    exported = client.get(f"/api/reports/{report_id}/export", headers=admin_headers)
    assert exported.status_code == 200
    assert exported.content[:2] == b"PK"

    new_headers = {**admin_headers, "Idempotency-Key": "report-b2-generate-002"}
    new_version = client.post(f"/api/reports/{report_id}/generate", headers=new_headers)
    assert new_version.status_code == 200, new_version.text
    assert new_version.json()["data"]["version"] == 2
    versions = client.get(f"/api/reports/{report_id}/versions", headers=admin_headers).json()["data"]
    assert [(row["version"], row["status"]) for row in versions] == [(2, "draft"), (1, "locked")]
    edited = client.patch(f"/api/reports/{report_id}/narrative", headers=admin_headers, json={"narrative": {"summary": "新版本说明"}})
    assert edited.status_code == 200, edited.text
    with SessionLocal() as db:
        report = db.get(ReportInstance, report_id)
        assert report.published_version == 1 and report.current_version == 2
