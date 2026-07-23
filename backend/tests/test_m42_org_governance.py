"""M42 数字化团队统一口径、业务域删除与飞书自动同步策略。"""
from datetime import datetime

from app.db import SessionLocal
from app.models import BusinessDomain, Department, FeishuConfig, OrgMember, OrgSettings, Requirement
from app.services.team_scope import it_member_ids


def test_configured_digital_team_department_is_authoritative(client, admin_headers):
    with SessionLocal() as db:
        parent = Department(code="m42_org_eff", name="组织效率部", dept_type="business")
        other = Department(code="m42_other", name="其他部门", dept_type="business")
        db.add_all([parent, other]); db.flush()
        digital = Department(code="m42_digital", name="数字化流程效率组", parent_id=parent.id, dept_type="business")
        db.add(digital); db.flush()
        included = OrgMember(name="M42数字化成员", department_id=digital.id)
        excluded = OrgMember(name="M42其他成员", department_id=other.id)
        db.add_all([included, excluded]); db.commit()
        parent_id, included_id, excluded_id = parent.id, included.id, excluded.id

    response = client.patch("/api/admin/org-settings", headers=admin_headers, json={
        "digital_team_department_ids": [parent_id], "digital_team_include_children": True,
    })
    assert response.status_code == 200
    with SessionLocal() as db:
        ids = it_member_ids(db)
    assert included_id in ids and excluded_id not in ids

    members = client.get("/api/members?scope=it&page_size=2000", headers=admin_headers).json()["data"]
    assert included_id in {row["id"] for row in members}

    # 配置统一口径后，项目经理也必须来自同一数字化团队范围（不能只靠前端下拉过滤）。
    rejected = client.post("/api/projects", headers=admin_headers, json={
        "name": "M42非法项目经理", "pm": excluded_id,
        "planned_start": "2026-07-01", "planned_end": "2026-07-31",
    })
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "NOT_IT_TEAM_MEMBER"
    accepted = client.post("/api/projects", headers=admin_headers, json={
        "name": "M42数字化项目经理", "pm": included_id,
        "planned_start": "2026-07-01", "planned_end": "2026-07-31",
    })
    assert accepted.status_code == 200, accepted.text


def test_domain_delete_is_available_and_protects_references(client, admin_headers):
    created = client.post("/api/admin/business-domains", headers=admin_headers, json={
        "code": "m42_deletable", "name": "可删除业务域", "department_ids": [],
    }).json()["data"]
    assert client.delete(f"/api/admin/business-domains/{created['id']}", headers=admin_headers).status_code == 200

    with SessionLocal() as db:
        domain = BusinessDomain(code="m42_used", name="被引用业务域")
        db.add(domain); db.flush()
        db.add(Requirement(
            requirement_code="M42-REQ", title="引用校验", req_type="业务",
            business_domain_id=domain.id, description="引用中的业务域不得删除",
        ))
        db.commit(); domain_id = domain.id
    blocked = client.delete(f"/api/admin/business-domains/{domain_id}", headers=admin_headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "DOMAIN_IN_USE"


def test_auto_sync_settings_are_persisted(client, admin_headers):
    response = client.patch("/api/admin/org-settings", headers=admin_headers, json={
        "feishu_auto_sync_enabled": True, "feishu_auto_sync_interval_minutes": 360,
    })
    assert response.status_code == 200
    payload = client.get("/api/admin/org-settings", headers=admin_headers).json()["data"]
    assert payload["feishu_auto_sync_enabled"] is True
    assert payload["feishu_auto_sync_interval_minutes"] == 360


def test_due_auto_sync_reuses_org_sync_engine(client, monkeypatch):
    calls: list[str] = []
    with SessionLocal() as db:
        cfg = db.query(FeishuConfig).filter(FeishuConfig.is_deleted.is_(False)).first()
        if not cfg:
            cfg = FeishuConfig()
            db.add(cfg)
        cfg.enabled, cfg.app_id, cfg.app_secret = True, "cli_m42", "secret_m42"
        settings = db.query(OrgSettings).filter(OrgSettings.is_deleted.is_(False)).first()
        settings.feishu_auto_sync_enabled = True
        settings.feishu_auto_sync_interval_minutes = 60
        settings.feishu_auto_sync_last_attempt_at = None
        db.commit()

    monkeypatch.setattr("app.services.org_sync.run_sync", lambda _db, source: calls.append(source) or {})
    from app.services.scheduler import scan_feishu_org_sync
    scan_feishu_org_sync()
    scan_feishu_org_sync()
    assert calls == ["feishu"]
