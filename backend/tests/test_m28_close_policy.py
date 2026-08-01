"""M28 关闭策略（用户定稿）補充：需求/项目登记人可关（理由+审计）；
问题/工单手动流转到终态仅 admin；处理节点一律走流程闭环。"""
import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    def member_and_user(name, username, roles):
        m = client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]
        client.post(
            "/api/admin/users",
            json={"username": username, "password": "pass123", "roles": roles, "person_id": m["id"]},
            headers=admin_headers,
        )
        token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
        return m["id"], {"Authorization": f"Bearer {token}"}

    req_pid, req_h = member_and_user("业务数字化经理M28", "m28_req", ["bdo"])
    pdm_pid, pdm_h = member_and_user("产品M28", "m28_pdm", ["it_pdm"])
    pm_pid, pm_h = member_and_user("项目经理M28", "m28_pm", ["it_pm"])
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    domain = client.get("/api/admin/business-domains", headers=admin_headers).json()["data"][0]["id"]
    return {"admin": admin_headers, "req_h": req_h, "pdm_h": pdm_h,
            "pm_pid": pm_pid, "pm_h": pm_h, "item": item, "domain": domain}


def test_requirement_submitter_close_with_reason(client, ctx):
    """需求提出人可主动关闭（理由必填→已取消+审计+流程收尾）；产品经理不可。"""
    r = client.post("/api/requirements", json={"title": "M28提出人撤回", "req_type": "功能",
                                               "business_domain_id": ctx["domain"], "description": "d"},
                    headers=ctx["req_h"]).json()["data"]
    # 处理节点（产品经理，有 requirements.edit）不可主动关闭
    resp = client.post(f"/api/requirements/{r['id']}/close", json={"reason": "产品试图关闭"}, headers=ctx["pdm_h"])
    assert resp.status_code == 403
    # 理由太短 422
    assert client.post(f"/api/requirements/{r['id']}/close", json={"reason": "abc"}, headers=ctx["req_h"]).status_code == 422
    # 提出人本人关闭
    resp = client.post(f"/api/requirements/{r['id']}/close", json={"reason": "业务方向调整，主动撤回"}, headers=ctx["req_h"])
    assert resp.json()["success"], resp.text
    d = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]
    assert d["status"] == "cancelled" and "[主动关闭]" in d["closure_note"]
    assert d["process"]["status"] == "completed"  # 流程实例随单收尾
    # 终态再关 → 报错
    assert client.post(f"/api/requirements/{r['id']}/close", json={"reason": "再关一次试试"},
                       headers=ctx["req_h"]).json()["error"]["code"] == "REQ_FINAL"


def test_requirement_manual_terminal_transition_admin_only(client, ctx):
    """需求手动流转到 cancelled/closed（普通授权）仅 admin。"""
    r = client.post("/api/requirements", json={"title": "M28终态流转", "req_type": "功能",
                                               "business_domain_id": ctx["domain"], "description": "d"},
                    headers=ctx["admin"]).json()["data"]
    resp = client.post(f"/api/requirements/{r['id']}/transition", json={"to": "cancelled", "fields": {}}, headers=ctx["pdm_h"])
    assert resp.status_code == 403 and resp.json()["error"]["code"] in ("FORCE_CLOSE_FORBIDDEN", "USE_PROCESS_STEP")
    resp = client.post(f"/api/requirements/{r['id']}/transition", json={"to": "cancelled", "fields": {}}, headers=ctx["admin"])
    assert resp.json()["success"], resp.text


def test_problem_manual_close_admin_only(client, ctx):
    """问题手动流转 closed 仅 admin（正常闭环走流程完成自动关闭）。"""
    p = client.post("/api/problems", json={"title": "M28问题强关", "description": "d", "priority": "P3",
                                           "service_item_id": ctx["item"]}, headers=ctx["admin"]).json()["data"]
    for to in ("analyzing", "resolved"):
        client.post(f"/api/problems/{p['id']}/transition",
                    json={"to": to, "fields": {"root_cause": "配置漂移"}}, headers=ctx["admin"])
    # 产品经理（有 problems.edit? it_pdm 矩阵 problems v）→ 403（无 edit 先拦或终态守卫拦，都为 403）
    resp = client.post(f"/api/problems/{p['id']}/transition", json={"to": "closed", "fields": {}}, headers=ctx["pdm_h"])
    assert resp.status_code == 403
    resp = client.post(f"/api/problems/{p['id']}/transition", json={"to": "closed", "fields": {}}, headers=ctx["admin"])
    assert resp.json()["success"], resp.text


def test_project_close_pm_or_admin_only(client, ctx):
    """项目关闭仅 PM 本人或 admin；其他有 projects.edit 的人 403。"""
    p = client.post("/api/projects", json={"name": "M28项目关闭", "pm": ctx["pm_pid"],
                                           "planned_start": "2026-08-01", "planned_end": "2026-12-31"},
                    headers=ctx["admin"]).json()["data"]
    client.post(f"/api/projects/{p['id']}/transition", json={"to": "active", "fields": {}}, headers=ctx["admin"])
    # 产品经理（it_pdm 有 projects.edit? staff 矩阵 projects vce？若无 edit 则权限层 403，同样验证拒绝）
    resp = client.post(f"/api/projects/{p['id']}/transition",
                       json={"to": "closed", "fields": {"reason": "他人试图关闭项目"}}, headers=ctx["pdm_h"])
    assert resp.status_code == 403
    # PM 本人可关（理由必填已有）
    resp = client.post(f"/api/projects/{p['id']}/transition",
                       json={"to": "closed", "fields": {"reason": "项目验收完成，PM 关闭"}}, headers=ctx["pm_h"])
    assert resp.json()["success"], resp.text
