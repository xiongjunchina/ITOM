"""战略项目组合治理：目标、评分、决策、依赖、资源冲突与基线。"""
from datetime import date

from app.db import SessionLocal
from app.models import Portfolio, PortfolioProject, PortfolioScoringRule, Project
from app.services.migrate import ensure_portfolio_governance_schema
from app.services.permissions import DEFAULT_MATRIX, MODULE_CODES


def _member(client, headers, name):
    return client.post("/api/members", headers=headers, json={"name": name}).json()["data"]["id"]


def _project(client, headers, name, pm, portfolio_id=None):
    return client.post("/api/projects", headers=headers, json={
        "name": name,
        "pm": pm,
        "planned_start": "2026-09-01",
        "planned_end": "2026-12-31",
        "portfolio_id": portfolio_id,
        "budget_10k": 100,
    }).json()["data"]


def _user(client, admin_headers, name, username, roles):
    person_id = _member(client, admin_headers, name)
    created = client.post("/api/admin/users", headers=admin_headers, json={
        "username": username,
        "password": "pass123",
        "roles": roles,
        "person_id": person_id,
    })
    assert created.status_code == 200, created.text
    token = client.post("/api/auth/login", json={
        "username": username,
        "password": "pass123",
    }).json()["data"]["token"]
    return person_id, {"Authorization": f"Bearer {token}"}


def test_portfolio_permission_contract():
    expected = {
        "portfolio_governance", "portfolio_scoring", "portfolio_decision",
        "portfolio_resource", "portfolio_audit",
    }
    assert expected <= MODULE_CODES
    assert "e" in DEFAULT_MATRIX["cio"]["portfolio_decision"]
    assert "e" not in DEFAULT_MATRIX["it_pmo"]["portfolio_decision"]
    assert "e" in DEFAULT_MATRIX["it_bm"]["portfolio_scoring"]
    assert "e" in DEFAULT_MATRIX["it_tm"]["portfolio_resource"]
    assert "e" not in DEFAULT_MATRIX["it_pm"]["portfolio_scoring"]
    assert "c" in DEFAULT_MATRIX["it_pm"]["portfolio_governance"]
    assert DEFAULT_MATRIX["auditor"]["portfolio_audit"] == "v"


def test_portfolio_governance_end_to_end(client, admin_headers):
    pm = _member(client, admin_headers, "组合治理PM")
    shared = _member(client, admin_headers, "共享架构师")
    created = client.post("/api/portfolios", headers=admin_headers, json={
        "name": "2027 数字化价值组合",
        "owner_id": pm,
        "year": "2027",
        "status": "draft",
        "planning_start": "2027-01-01",
        "planning_end": "2027-12-31",
        "budget_limit_10k": 500,
    })
    assert created.status_code == 200, created.text
    portfolio_id = created.json()["data"]["id"]
    portfolio = next(row for row in client.get("/api/portfolios", headers=admin_headers).json()["data"] if row["id"] == portfolio_id)
    assert portfolio["portfolio_code"].startswith("PF-")
    assert portfolio["budget_limit_10k"] == 500

    primary = _project(client, admin_headers, "核心平台升级", pm, portfolio_id)
    outside = _project(client, admin_headers, "统一身份前置", pm)
    dashboard = client.get(f"/api/portfolios/{portfolio_id}/dashboard", headers=admin_headers)
    assert dashboard.status_code == 200, dashboard.text
    data = dashboard.json()["data"]
    assert data["summary"]["project_count"] == 1
    assert len(data["scoring_rules"]) == 5
    assert sum(rule["weight"] for rule in data["scoring_rules"] if rule["active"]) == 100

    objective = client.post(f"/api/portfolios/{portfolio_id}/objectives", headers=admin_headers, json={
        "objective_code": "OBJ-01",
        "name": "核心流程线上化率",
        "metric_name": "线上化率",
        "target_value": 95,
        "weight": 60,
        "owner_id": pm,
    })
    assert objective.status_code == 200, objective.text
    objective_id = objective.json()["data"]["id"]
    contribution = client.put(
        f"/api/portfolios/{portfolio_id}/projects/{primary['id']}/objectives",
        headers=admin_headers,
        json={"contributions": [{"objective_id": objective_id, "weight": 80, "note": "交付统一流程平台"}]},
    )
    assert contribution.status_code == 200, contribution.text

    rules = data["scoring_rules"]
    scores = [{"rule_id": rule["id"], "score": 80 + idx, "evidence": f"证据-{idx}"} for idx, rule in enumerate(rules)]
    scored = client.put(
        f"/api/portfolios/{portfolio_id}/projects/{primary['id']}/scores",
        headers=admin_headers,
        json={"scores": scores},
    )
    assert scored.status_code == 200, scored.text
    assert scored.json()["data"]["system_score"] == 81.6
    assert scored.json()["data"]["status"] == "scoring"

    pending = client.post(
        f"/api/portfolios/{portfolio_id}/projects/{primary['id']}/transition",
        headers=admin_headers,
        json={"to": "pending_review", "reason": "评分证据齐备，提交组合评审"},
    )
    assert pending.status_code == 200, pending.text
    missing_priority = client.post(
        f"/api/portfolios/{portfolio_id}/projects/{primary['id']}/transition",
        headers=admin_headers,
        json={"to": "admitted", "reason": "缺少治理排序不能纳入"},
    )
    assert missing_priority.status_code == 400
    assert missing_priority.json()["error"]["code"] == "PRIORITY_REQUIRED"
    admitted = client.post(
        f"/api/portfolios/{portfolio_id}/projects/{primary['id']}/transition",
        headers=admin_headers,
        json={"to": "admitted", "reason": "符合年度战略并优先保障资源", "priority_rank": 1},
    )
    assert admitted.status_code == 200, admitted.text

    dependency = client.post("/api/project-dependencies", headers=admin_headers, json={
        "predecessor_project_id": outside["id"],
        "successor_project_id": primary["id"],
        "dependency_type": "finish_to_start",
        "deliverable": "统一身份接口",
        "impact": "high",
        "owner_id": pm,
    })
    assert dependency.status_code == 200, dependency.text
    cycle = client.post("/api/project-dependencies", headers=admin_headers, json={
        "predecessor_project_id": primary["id"],
        "successor_project_id": outside["id"],
        "dependency_type": "finish_to_start",
        "deliverable": "反向依赖",
    })
    assert cycle.status_code == 400
    assert cycle.json()["error"]["code"] == "DEPENDENCY_CYCLE"

    for project_id, allocation in ((primary["id"], 60), (outside["id"], 50)):
        commitment = client.post("/api/project-resource-commitments", headers=admin_headers, json={
            "project_id": project_id,
            "person_id": shared,
            "role_name": "架构师",
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
            "allocation_percent": allocation,
        })
        assert commitment.status_code == 200, commitment.text

    dashboard = client.get(f"/api/portfolios/{portfolio_id}/dashboard", headers=admin_headers).json()["data"]
    assert dashboard["summary"]["resource_conflict_count"] == 1
    assert dashboard["resource_conflicts"][0]["allocation_percent"] == 110
    assert dashboard["dependencies"][0]["predecessor_project_name"] == "统一身份前置"

    baseline = client.post(
        f"/api/portfolios/{portfolio_id}/baselines",
        headers=admin_headers,
        json={"reason": "2027 年度组合正式基线"},
    )
    assert baseline.status_code == 200, baseline.text
    assert baseline.json()["data"]["version"] == 1
    actions = client.get(
        f"/api/portfolios/{portfolio_id}/governance-actions", headers=admin_headers,
    ).json()["data"]
    assert any(row["action"] == "objectives_updated" for row in actions)
    assert any(row["action"] == "baseline_published" for row in actions)
    refreshed = client.get(f"/api/portfolios/{portfolio_id}/dashboard", headers=admin_headers).json()["data"]
    assert refreshed["latest_baseline"]["version"] == 1
    assert refreshed["portfolio"]["status"] == "active"
    first_rule = refreshed["scoring_rules"][0]
    changed_rule = {
        "dimension_code": first_rule["dimension_code"],
        "name": first_rule["name"],
        "description": first_rule["description"],
        "weight": first_rule["weight"] - 1,
        "evidence_required": first_rule["evidence_required"],
        "active": first_rule["active"],
        "sort": first_rule["sort"],
    }
    assert client.put(
        f"/api/portfolios/{portfolio_id}/scoring-rules/{first_rule['id']}",
        headers=admin_headers,
        json=changed_rule,
    ).status_code == 200
    invalidated = client.get(f"/api/portfolios/{portfolio_id}/dashboard", headers=admin_headers).json()["data"]
    assert invalidated["projects"][0]["system_score"] is None
    blocked_baseline = client.post(
        f"/api/portfolios/{portfolio_id}/baselines",
        headers=admin_headers,
        json={"reason": "评分权重未闭合时不得发布"},
    )
    assert blocked_baseline.status_code == 400
    assert blocked_baseline.json()["error"]["code"] == "SCORING_INCOMPLETE"
    changed_rule["weight"] = first_rule["weight"]
    assert client.put(
        f"/api/portfolios/{portfolio_id}/scoring-rules/{first_rule['id']}",
        headers=admin_headers,
        json=changed_rule,
    ).status_code == 200
    assert client.get(
        f"/api/portfolios/{portfolio_id}/dashboard", headers=admin_headers,
    ).json()["data"]["projects"][0]["system_score"] == 81.6
    second_baseline = client.post(
        f"/api/portfolios/{portfolio_id}/baselines",
        headers=admin_headers,
        json={"reason": "评分规则恢复后的第二版基线"},
    )
    assert second_baseline.status_code == 200, second_baseline.text
    assert second_baseline.json()["data"]["version"] == 2
    deleted_outside = client.delete(f"/api/projects/{outside['id']}", headers=admin_headers)
    assert deleted_outside.status_code == 200, deleted_outside.text
    assert deleted_outside.json()["data"]["cascade"]["project_dependencies"] == 1
    assert deleted_outside.json()["data"]["cascade"]["resource_commitments"] == 1
    after_delete = client.get(f"/api/portfolios/{portfolio_id}/dashboard", headers=admin_headers).json()["data"]
    assert after_delete["dependencies"] == []
    assert after_delete["resource_conflicts"] == []
    assert after_delete["latest_baseline"]["version"] == 2


def test_non_empty_portfolio_cannot_be_deleted(client, admin_headers):
    pm = _member(client, admin_headers, "不可删除组合PM")
    portfolio_id = client.post("/api/portfolios", headers=admin_headers, json={"name": "不可删除组合"}).json()["data"]["id"]
    _project(client, admin_headers, "仍在组合项目", pm, portfolio_id)
    response = client.delete(f"/api/portfolios/{portfolio_id}", headers=admin_headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PORTFOLIO_NOT_EMPTY"


def test_project_can_move_between_portfolios_and_return(client, admin_headers):
    pm = _member(client, admin_headers, "组合迁移PM")
    first = client.post("/api/portfolios", headers=admin_headers, json={"name": "迁移组合甲"}).json()["data"]["id"]
    second = client.post("/api/portfolios", headers=admin_headers, json={"name": "迁移组合乙"}).json()["data"]["id"]
    project = _project(client, admin_headers, "跨组合迁移项目", pm, first)

    moved = client.patch(f"/api/projects/{project['id']}", headers=admin_headers, json={"portfolio_id": second})
    assert moved.status_code == 200, moved.text
    assert client.get(f"/api/portfolios/{first}/dashboard", headers=admin_headers).json()["data"]["summary"]["project_count"] == 0
    assert client.get(f"/api/portfolios/{second}/dashboard", headers=admin_headers).json()["data"]["summary"]["project_count"] == 1

    returned = client.patch(f"/api/projects/{project['id']}", headers=admin_headers, json={"portfolio_id": first})
    assert returned.status_code == 200, returned.text
    assert client.get(f"/api/portfolios/{first}/dashboard", headers=admin_headers).json()["data"]["summary"]["project_count"] == 1
    assert client.get(f"/api/portfolios/{second}/dashboard", headers=admin_headers).json()["data"]["summary"]["project_count"] == 0


def test_objective_weight_and_pm_record_scope(client, admin_headers):
    pm_id, pm_headers = _user(client, admin_headers, "组合权限PM", "portfolio_scope_pm", ["it_pm"])
    other_id, other_headers = _user(client, admin_headers, "其他组合PM", "portfolio_scope_other", ["it_pm"])
    _, bm_headers = _user(client, admin_headers, "组合评分BM", "portfolio_scope_bm", ["it_bm"])
    portfolio_id = client.post("/api/portfolios", headers=admin_headers, json={"name": "组合权限边界"}).json()["data"]["id"]
    project = _project(client, admin_headers, "PM提交材料项目", pm_id, portfolio_id)
    other_project = _project(client, admin_headers, "其他PM项目", other_id)
    objective = client.post(f"/api/portfolios/{portfolio_id}/objectives", headers=admin_headers, json={
        "objective_code": "SCOPE-01", "name": "权限边界目标", "weight": 70,
    })
    assert objective.status_code == 200, objective.text
    objective_id = objective.json()["data"]["id"]
    overflow = client.post(f"/api/portfolios/{portfolio_id}/objectives", headers=admin_headers, json={
        "objective_code": "SCOPE-02", "name": "超额权重目标", "weight": 31,
    })
    assert overflow.status_code == 400
    assert overflow.json()["error"]["code"] == "OBJECTIVE_WEIGHT_OVERFLOW"

    own = client.put(
        f"/api/portfolios/{portfolio_id}/projects/{project['id']}/objectives",
        headers=pm_headers,
        json={"contributions": [{"objective_id": objective_id, "weight": 60}]},
    )
    assert own.status_code == 200, own.text
    forbidden = client.put(
        f"/api/portfolios/{portfolio_id}/projects/{project['id']}/objectives",
        headers=other_headers,
        json={"contributions": [{"objective_id": objective_id, "weight": 60}]},
    )
    assert forbidden.status_code == 403
    assert client.post(f"/api/portfolios/{portfolio_id}/objectives", headers=pm_headers, json={
        "objective_code": "PM-NO", "name": "PM不可创建组合目标",
    }).status_code == 403
    assert client.post("/api/project-dependencies", headers=pm_headers, json={
        "predecessor_project_id": project["id"],
        "successor_project_id": other_project["id"],
        "deliverable": "PM负责项目的接口清单",
    }).status_code == 200
    dashboard = client.get(f"/api/portfolios/{portfolio_id}/dashboard", headers=admin_headers).json()["data"]
    scores = [{"rule_id": rule["id"], "score": 80, "evidence": "PM不应提交评分"} for rule in dashboard["scoring_rules"]]
    assert client.put(
        f"/api/portfolios/{portfolio_id}/projects/{project['id']}/scores",
        headers=pm_headers,
        json={"scores": scores},
    ).status_code == 403
    first_rule = dashboard["scoring_rules"][0]
    assert client.put(
        f"/api/portfolios/{portfolio_id}/scoring-rules/{first_rule['id']}",
        headers=bm_headers,
        json={
            "dimension_code": first_rule["dimension_code"],
            "name": first_rule["name"],
            "weight": first_rule["weight"],
            "evidence_required": True,
            "active": True,
            "sort": first_rule["sort"],
        },
    ).status_code == 403
    scored = client.put(
        f"/api/portfolios/{portfolio_id}/projects/{project['id']}/scores",
        headers=bm_headers,
        json={"scores": [{**score, "evidence": "BM评分证据"} for score in scores]},
    )
    assert scored.status_code == 200, scored.text


def test_portfolio_migration_is_idempotent_and_preserves_primary_link(client, admin_headers):
    pm = _member(client, admin_headers, "存量组合迁移PM")
    with SessionLocal() as db:
        portfolio = Portfolio(name="存量无编码组合", portfolio_code=None, status="draft")
        db.add(portfolio)
        db.flush()
        project = Project(
            project_code="PJ-LEGACY-PORTFOLIO",
            name="存量组合项目",
            pm=pm,
            planned_start=date(2026, 1, 1),
            planned_end=date(2026, 12, 31),
            portfolio_id=portfolio.id,
        )
        db.add(project)
        db.commit()
        portfolio_id = portfolio.id
        project_id = project.id

    for _ in range(2):
        with SessionLocal() as db:
            ensure_portfolio_governance_schema(db)

    with SessionLocal() as db:
        portfolio = db.get(Portfolio, portfolio_id)
        project = db.get(Project, project_id)
        memberships = db.query(PortfolioProject).filter(
            PortfolioProject.project_id == project_id,
            PortfolioProject.is_deleted.is_(False),
        ).all()
        rules = db.query(PortfolioScoringRule).filter(
            PortfolioScoringRule.portfolio_id == portfolio_id,
            PortfolioScoringRule.is_deleted.is_(False),
        ).all()
        assert portfolio.portfolio_code.startswith("PF-LEGACY-")
        assert project.portfolio_id == portfolio_id
        assert len(memberships) == 1
        assert memberships[0].governance_status == "admitted"
        assert len(rules) == 5
