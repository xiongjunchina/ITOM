"""B+ 矩阵角色绩效：周期快照、外部原数据、分级评审和发布隔离。"""

from app.db import SessionLocal
from app.models import UserGroup, UserGroupMember


def _member_and_user(client, admin_headers, name, username, roles):
    member = client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]
    client.post(
        "/api/admin/users",
        json={"username": username, "password": "pass123", "roles": roles, "person_id": member["id"]},
        headers=admin_headers,
    )
    token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
    return member["id"], {"Authorization": f"Bearer {token}"}


def test_bplus_recompute_external_input_and_publish(client, admin_headers):
    profiles = client.get("/api/admin/performance/role-profiles", headers=admin_headers)
    assert profiles.status_code == 200, profiles.text
    assert any(item["role_code"] == "it_bm" for item in profiles.json()["data"])
    metrics = client.get("/api/admin/performance/metric-definitions", headers=admin_headers)
    assert metrics.status_code == 200, metrics.text
    metric_rows = metrics.json()["data"]
    assert any(item["metric_code"] == "external_business_satisfaction" and item["source_type"] == "external" for item in metric_rows)
    assert any(item["metric_code"] == "internal_external_satisfaction" and item["source_type"] == "derived" for item in metric_rows)

    dev_id, dev_headers = _member_and_user(client, admin_headers, "B+开发", "bplus_dev", ["it_dev"])
    _, cio_headers = _member_and_user(client, admin_headers, "B+CIO", "bplus_cio", ["cio"])

    recompute = client.post("/api/admin/performance/2026-Q3/recompute", headers=cio_headers)
    assert recompute.status_code == 200, recompute.text
    data = recompute.json()["data"]
    assert data["status"] == "auto_scored"
    dev = next(row for row in data["rows"] if row["person_id"] == dev_id)
    assert any(role["role_code"] == "it_dev" for role in dev["roles"])

    # 发布前员工接口不能看到内部参考分。
    before = client.get("/api/my/performance?period=2026-Q3", headers=dev_headers).json()["data"]
    assert before["published"] is False and before["result"] is None

    invalid_external = client.post("/api/admin/performance/external-inputs", json={
        "period": "2026-Q3", "metric_code": "external_business_satisfaction",
        "target_type": "person", "target_id": "missing-person", "evaluator_name": "业务负责人",
        "raw_score": 4, "raw_scale": 5,
    }, headers=cio_headers)
    assert invalid_external.status_code == 422

    domain = client.post("/api/admin/business-domains", json={
        "code": "bplus-person-domain", "name": "B+ 业务服务域", "owner_id": dev_id,
    }, headers=cio_headers)
    assert domain.status_code == 200, domain.text
    domain_id = domain.json()["data"]["id"]

    external = client.post("/api/admin/performance/external-inputs", json={
        "period": "2026-Q3", "metric_code": "external_business_satisfaction",
        "target_type": "business_domain", "target_id": domain_id, "evaluator_name": "业务负责人",
        "evaluator_department": "供应链", "raw_score": 4.5, "raw_scale": 5,
        "comment": "系统外满意度回收", "status": "verified",
    }, headers=cio_headers)
    assert external.status_code == 200, external.text
    assert external.json()["data"]["normalized_score"] == 90.0

    published = client.post("/api/admin/performance/2026-Q3/publish", headers=cio_headers)
    assert published.status_code == 200, published.text
    after = client.get("/api/my/performance?period=2026-Q3", headers=dev_headers).json()["data"]
    assert after["published"] is True
    assert "roles" in after["result"] and "dimensions" not in after["result"]


def test_team_performance_overview_uses_bplus_result_model(client, admin_headers):
    """团队人效总览必须读取当前矩阵角色结果，不再返回旧版 PerfScheme 维度表。"""
    response = client.get("/api/team/performance/overview?period=2026-Q3", headers=admin_headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert {"period", "version", "status", "rows"} <= set(data)
    if data["rows"]:
        row = data["rows"][0]
        assert {"roles", "business_contribution", "professional_contribution", "team_contribution_score", "regular_score"} <= set(row)
        assert "scheme_name" not in row and "dims" not in row


def test_bplus_manager_scope_and_new_version(client, admin_headers):
    dev_id, _ = _member_and_user(client, admin_headers, "B+组员", "bplus_member", ["it_dev"])
    multi_id, _ = _member_and_user(client, admin_headers, "B+多角色员工", "bplus_multi", ["it_dev", "it_pm"])
    tm_id, tm_headers = _member_and_user(client, admin_headers, "B+专业负责人", "bplus_tm", ["it_tm"])
    _, cio_headers = _member_and_user(client, admin_headers, "B+终审CIO", "bplus_cio2", ["cio"])
    with SessionLocal() as db:
        group = UserGroup(code="bplus-dev", name="B+开发资源池", roles=["it_dev"], owner_id=tm_id)
        db.add(group)
        db.flush()
        db.add(UserGroupMember(group_id=group.id, person_id=dev_id))
        db.commit()

    recompute = client.post("/api/admin/performance/2026-Q2/recompute", headers=cio_headers)
    assert recompute.status_code == 200, recompute.text
    configured = client.get("/api/admin/performance/assignments?period=2026-Q2", headers=cio_headers)
    assert configured.status_code == 200, configured.text
    multi_assignments = [item for item in configured.json()["data"]["assignments"] if item["person_id"] == multi_id]
    assert len(multi_assignments) == 2 and {item["role_weight"] for item in multi_assignments} == {40}
    adjusted_weights = [30, 50]
    adjusted = client.put("/api/admin/performance/assignments", json={
        "period": "2026-Q2", "person_id": multi_id,
        "assignments": [
            {"assignment_id": item["assignment_id"], "role_weight": weight, "evaluator_ids": item["evaluator_ids"]}
            for item, weight in zip(multi_assignments, adjusted_weights)
        ],
    }, headers=cio_headers)
    assert adjusted.status_code == 200, adjusted.text
    refreshed = client.post("/api/admin/performance/2026-Q2/recompute", headers=cio_headers)
    assert refreshed.status_code == 200, refreshed.text
    persisted = client.get("/api/admin/performance/assignments?period=2026-Q2", headers=cio_headers)
    assert sorted(item["role_weight"] for item in persisted.json()["data"]["assignments"] if item["person_id"] == multi_id) == adjusted_weights
    dev_assignments = [item for item in configured.json()["data"]["assignments"] if item["person_id"] == dev_id]
    assert dev_assignments
    updated = client.put("/api/admin/performance/assignments", json={
        "period": "2026-Q2", "person_id": dev_id,
        "assignments": [{"assignment_id": item["assignment_id"], "role_weight": item["role_weight"], "evaluator_ids": item["evaluator_ids"]} for item in dev_assignments],
    }, headers=cio_headers)
    assert updated.status_code == 200, updated.text
    assignment = next(
        role["assignment_id"]
        for row in recompute.json()["data"]["rows"]
        if row["person_id"] == dev_id
        for role in row["roles"]
        if role["role_code"] == "it_dev"
    )
    component = client.get("/api/admin/performance/reviews?period=2026-Q2", headers=tm_headers).json()["data"]
    detail = next(row for row in component["rows"] if row["person_id"] == dev_id)
    person_detail = client.get(f"/api/admin/performance/reviews/person/{dev_id}?period=2026-Q2", headers=tm_headers)
    assert person_detail.status_code == 200, person_detail.text
    assert person_detail.json()["data"]["row"]["person_id"] == dev_id
    assert len(person_detail.json()["data"]["row"]["roles"]) == len(dev_assignments)
    dimension = next(dim for dim in next(role for role in detail["roles"] if role["assignment_id"] == assignment)["dimensions"] if dim["code"] == "requirement_delivery")
    r = client.put(f"/api/admin/performance/reviews/{assignment}/components/requirement_delivery", json={
        "score": 88, "reason": "负责人初评：交付记录完整",
    }, headers=tm_headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["effective_score"] == 88

    # 普通成员没有分级评审编辑权限。
    member_headers = _member_and_user(client, admin_headers, "B+普通成员", "bplus_plain", ["it_dev"])[1]
    denied = client.put(f"/api/admin/performance/reviews/{assignment}/components/requirement_delivery", json={"score": 1}, headers=member_headers)
    assert denied.status_code == 403

    client.post("/api/admin/performance/2026-Q2/publish", headers=cio_headers)
    unlocked = client.post("/api/admin/performance/2026-Q2/unlock", headers=cio_headers)
    assert unlocked.status_code == 200
    assert unlocked.json()["data"]["version"] == 2


def test_pmo_reviews_project_managers_and_is_cio_direct(client, admin_headers):
    pmo_id, pmo_headers = _member_and_user(client, admin_headers, "B+项目治理PMO", "bplus_pmo", ["it_pmo"])
    pm_id, _ = _member_and_user(client, admin_headers, "B+项目经理", "bplus_pm", ["it_pm"])
    _, cio_headers = _member_and_user(client, admin_headers, "B+项目CIO", "bplus_pmo_cio", ["cio"])
    with SessionLocal() as db:
        group = UserGroup(code="bplus-pm", name="B+ IT PM 虚拟团队", roles=["it_pm"], owner_id=pmo_id)
        db.add(group)
        db.flush()
        db.add(UserGroupMember(group_id=group.id, person_id=pm_id))
        db.commit()

    recompute = client.post("/api/admin/performance/2027-Q1/recompute", headers=cio_headers)
    assert recompute.status_code == 200, recompute.text
    assignments = client.get("/api/admin/performance/assignments?period=2027-Q1", headers=cio_headers).json()["data"]["assignments"]
    pm_assignment = next(item for item in assignments if item["person_id"] == pm_id and item["role_code"] == "it_pm")
    pmo_assignment = next(item for item in assignments if item["person_id"] == pmo_id and item["role_code"] == "it_pmo")
    assert pm_assignment["evaluator_ids"] == [pmo_id]
    assert pm_assignment["review_mode"] == "manager_review"
    assert pmo_assignment["review_mode"] == "cio_direct"
    assert pmo_assignment["evaluator_ids"] == []
    pmo_profile = next(item for item in client.get("/api/admin/performance/role-profiles", headers=cio_headers).json()["data"] if item["role_code"] == "it_pmo")
    cannot_downgrade = client.patch(
        f"/api/admin/performance/role-profiles/{pmo_profile['id']}",
        json={"review_mode": "manager_review"}, headers=admin_headers,
    )
    assert cannot_downgrade.status_code == 422, cannot_downgrade.text

    detail = client.get("/api/admin/performance/reviews?period=2027-Q1", headers=cio_headers).json()["data"]
    pm_role = next(role for row in detail["rows"] if row["person_id"] == pm_id for role in row["roles"] if role["role_code"] == "it_pm")
    score = client.put(
        f"/api/admin/performance/reviews/{pm_role['assignment_id']}/components/project_manager_delivery",
        json={"score": 90, "reason": "PMO 初评项目经理交付"}, headers=pmo_headers,
    )
    assert score.status_code == 200, score.text


def test_multiple_reviewers_are_saved_and_weighted(client, admin_headers):
    dev_id, _ = _member_and_user(client, admin_headers, "B+多评审员工", "bplus_multi_reviewee", ["it_dev"])
    lead_a, lead_a_headers = _member_and_user(client, admin_headers, "B+评审人A", "bplus_reviewer_a", ["it_tm"])
    lead_b, lead_b_headers = _member_and_user(client, admin_headers, "B+评审人B", "bplus_reviewer_b", ["it_tm"])
    _, cio_headers = _member_and_user(client, admin_headers, "B+多评审CIO", "bplus_multi_review_cio", ["cio"])
    recompute = client.post("/api/admin/performance/2028-Q1/recompute", headers=cio_headers)
    assert recompute.status_code == 200, recompute.text
    assignments = client.get("/api/admin/performance/assignments?period=2028-Q1", headers=cio_headers).json()["data"]["assignments"]
    dev_assignment = next(item for item in assignments if item["person_id"] == dev_id and item["role_code"] == "it_dev")
    updated = client.put("/api/admin/performance/assignments", json={
        "period": "2028-Q1", "person_id": dev_id,
        "assignments": [{
            "assignment_id": dev_assignment["assignment_id"], "role_weight": dev_assignment["role_weight"],
            "evaluator_ids": [lead_a, lead_b], "evaluator_weights": {lead_a: 25, lead_b: 75},
        }],
    }, headers=cio_headers)
    assert updated.status_code == 200, updated.text
    detail = client.get("/api/admin/performance/reviews/person/{0}?period=2028-Q1".format(dev_id), headers=cio_headers).json()["data"]["row"]
    role = next(item for item in detail["roles"] if item["role_code"] == "it_dev")
    dimension = next(item for item in role["dimensions"] if item["code"] == "requirement_delivery")
    endpoint = f"/api/admin/performance/reviews/{role['assignment_id']}/components/requirement_delivery"
    assert client.put(endpoint, json={"score": 80, "reason": "评审人A独立评分"}, headers=lead_a_headers).status_code == 200
    second = client.put(endpoint, json={"score": 100, "reason": "评审人B独立评分"}, headers=lead_b_headers)
    assert second.status_code == 200, second.text
    refreshed = client.get("/api/admin/performance/reviews/person/{0}?period=2028-Q1".format(dev_id), headers=cio_headers).json()["data"]["row"]
    refreshed_dimension = next(item for item in next(item for item in refreshed["roles"] if item["role_code"] == "it_dev")["dimensions"] if item["code"] == "requirement_delivery")
    assert refreshed_dimension["manager_scores"] == {lead_a: 80, lead_b: 100}
    assert refreshed_dimension["professional_manager_score"] == 95.0


def test_contribution_rules_are_configurable_and_validated(client, admin_headers):
    current = client.get("/api/admin/performance/contribution-rules", headers=admin_headers)
    assert current.status_code == 200, current.text
    config = current.json()["data"]
    config["internal_satisfaction_weight"] = 40
    config["external_satisfaction_weight"] = 60
    updated = client.put("/api/admin/performance/contribution-rules", json=config, headers=admin_headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["external_satisfaction_weight"] == 60
    config["external_satisfaction_weight"] = 50
    invalid = client.put("/api/admin/performance/contribution-rules", json=config, headers=admin_headers)
    assert invalid.status_code == 422


def test_external_input_can_update_and_delete_until_locked(client, admin_headers):
    member_id, _ = _member_and_user(client, admin_headers, "B+外部数据维护", "bplus_external_maint", ["it_bm"])
    domain = client.post("/api/admin/business-domains", json={"code": "bplus-input-domain", "name": "B+ 原数据业务域", "owner_id": member_id}, headers=admin_headers)
    assert domain.status_code == 200, domain.text
    domain_id = domain.json()["data"]["id"]
    created = client.post("/api/admin/performance/external-inputs", json={
        "period": "2026-All", "metric_code": "external_business_satisfaction",
        "target_type": "business_domain", "target_id": domain_id, "evaluator_name": "业务负责人",
        "raw_score": 80, "raw_scale": 100, "status": "verified",
    }, headers=admin_headers)
    assert created.status_code == 200, created.text
    input_id = created.json()["data"]["id"]

    updated = client.patch(f"/api/admin/performance/external-inputs/{input_id}", json={
        "period": "2026-All", "metric_code": "external_business_satisfaction",
        "target_type": "business_domain", "target_id": domain_id, "evaluator_name": "业务负责人",
        "raw_score": 86, "raw_scale": 100, "status": "verified",
    }, headers=admin_headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["normalized_score"] == 86.0

    deleted = client.delete(f"/api/admin/performance/external-inputs/{input_id}", headers=admin_headers)
    assert deleted.status_code == 200, deleted.text
    listed = client.get("/api/admin/performance/external-inputs?period=2026-All", headers=admin_headers)
    assert listed.status_code == 200 and all(item["id"] != input_id for item in listed.json()["data"])

    locked = client.post("/api/admin/performance/external-inputs", json={
        "period": "2026-All", "metric_code": "external_business_satisfaction",
        "target_type": "business_domain", "target_id": domain_id, "evaluator_name": "业务负责人",
        "raw_score": 90, "raw_scale": 100, "status": "locked",
    }, headers=admin_headers)
    assert locked.status_code == 200, locked.text
    locked_id = locked.json()["data"]["id"]
    assert client.delete(f"/api/admin/performance/external-inputs/{locked_id}", headers=admin_headers).status_code == 409


def test_external_domain_satisfaction_only_scores_domain_owner_and_bp(client, admin_headers):
    bm_id, _ = _member_and_user(client, admin_headers, "业务线负责人", "bplus_domain_bm", ["it_bm"])
    bp_id, _ = _member_and_user(client, admin_headers, "业务合作伙伴", "bplus_domain_bp", ["it_bp"])
    dev_id, _ = _member_and_user(client, admin_headers, "业务域开发", "bplus_domain_dev", ["it_dev"])
    domain = client.post("/api/admin/business-domains", json={
        "code": "bplus-domain", "name": "B+ 测试业务域", "owner_id": bm_id,
    }, headers=admin_headers)
    assert domain.status_code == 200, domain.text
    domain_id = domain.json()["data"]["id"]
    members = client.put(f"/api/admin/business-domains/{domain_id}/members", json={"person_ids": [bp_id, dev_id]}, headers=admin_headers)
    assert members.status_code == 200, members.text

    recompute = client.post("/api/admin/performance/2026-Q1/recompute", headers=admin_headers)
    assert recompute.status_code == 200, recompute.text
    external = client.post("/api/admin/performance/external-inputs", json={
        "period": "2026-Q1", "metric_code": "external_business_satisfaction",
        "target_type": "business_domain", "target_id": domain_id,
        "evaluator_name": "业务部门负责人", "raw_score": 4.5, "raw_scale": 5,
        "status": "verified",
    }, headers=admin_headers)
    assert external.status_code == 200, external.text
    refreshed = client.post("/api/admin/performance/2026-Q1/recompute", headers=admin_headers)
    assert refreshed.status_code == 200, refreshed.text
    rows = {row["person_id"]: row for row in refreshed.json()["data"]["rows"]}
    bm_role = next(role for role in rows[bm_id]["roles"] if role["role_code"] == "it_bm")
    bp_role = next(role for role in rows[bp_id]["roles"] if role["role_code"] == "it_bp")
    dev_role = next(role for role in rows[dev_id]["roles"] if role["role_code"] == "it_dev")
    assert next(dim for dim in bm_role["dimensions"] if dim["code"] == "internal_external_satisfaction")["system_score"] == 90.0
    assert next(dim for dim in bp_role["dimensions"] if dim["code"] == "internal_external_satisfaction")["system_score"] == 90.0
    assert all(dim["system_score"] != 90.0 for dim in dev_role["dimensions"])
