"""M30：六模块详情页按钮下发与接口权限全面一致——显示的按钮必然可操作。

规则：普通中间流转=当前节点处理人（M25）；审批类=状态机显式授权；终态状态按钮=仅 admin
（登记人关单走各自的专门按钮 can_close）；无模块 edit 权限不下发状态按钮。
"""
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

    ops_pid, ops_h = member_and_user("运维M30", "m30_ops", ["it_ops"])
    req_pid, req_h = member_and_user("业务M30", "m30_req", ["requester"])
    dev_pid, dev_h = member_and_user("开发M30", "m30_dev", ["it_dev"])
    pm_pid, pm_h = member_and_user("PM-M30", "m30_pm", ["it_pm"])
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    domain = client.get("/api/admin/business-domains", headers=admin_headers).json()["data"][0]["id"]
    return {"admin": admin_headers, "ops_pid": ops_pid, "ops_h": ops_h, "req_h": req_h,
            "dev_pid": dev_pid, "dev_h": dev_h, "pm_pid": pm_pid, "pm_h": pm_h,
            "item": item, "domain": domain}


def _assert_buttons_work(client, headers, detail_url, transition_url):
    """一致性断言：detail 下发的每个流转按钮，接口调用都不应因权限拒绝（403）。

    用 dry-run 方式：只验证非法目标之外的权限层——对每个下发目标发起请求，
    如果返回 403 即为「显示了不可用按钮」的不一致缺陷。
    """
    d = client.get(detail_url, headers=headers).json()["data"]
    for tr in d.get("allowed_transitions", []):
        r = client.post(transition_url, json={"to": tr["to"], "fields": {}}, headers=headers)
        assert r.status_code != 403, f"按钮「{tr['to_name']}」下发了但接口 403：{r.text}"
        if r.status_code == 200:
            return  # 已流转一步，后续目标基于旧状态无意义


def test_sr_submitter_no_status_buttons_but_can_close(client, ctx):
    """服务请求登记人（有 edit 的 IT 员工提单）：不见终态状态按钮，见专门关闭按钮。"""
    t = client.post("/api/tickets", json={
        "title": "M30-SR按钮", "ticket_type": "service_request", "priority": "P4",
        "description": "d", "service_item_id": ctx["item"],
    }, headers=ctx["ops_h"]).json()["data"]
    # 推进到 resolved（登记人自关路径），admin 操作状态
    client.post(f"/api/tickets/{t['id']}/transition", json={"to": "resolved", "fields": {"solution": "s"}},
                headers=ctx["admin"])
    d = client.get(f"/api/tickets/{t['id']}", headers=ctx["ops_h"]).json()["data"]
    assert all(x["to"] != "closed" for x in d["allowed_transitions"]), "终态按钮不应下发给非 admin"
    assert d["can_close"] is True  # 登记人专门关闭按钮
    da = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]
    assert any(x["to"] == "closed" for x in da["allowed_transitions"])  # admin 可见终态按钮


def test_incident_handler_buttons_all_operable(client, ctx):
    """事件节点处理人：下发的按钮全部可操作（一致性扫描）。"""
    t = client.post("/api/tickets", json={
        "title": "M30-事件按钮", "ticket_type": "incident", "priority": "P3",
        "description": "d", "service_item_id": ctx["item"],
    }, headers=ctx["admin"]).json()["data"]
    proc = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]["process"]
    cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
    client.post(f"/api/process-tasks/{cur['task_id']}/reassign", json={"assignee": ctx["ops_pid"]}, headers=ctx["admin"])
    _assert_buttons_work(client, ctx["ops_h"], f"/api/tickets/{t['id']}", f"/api/tickets/{t['id']}/transition")


def test_project_viewer_no_buttons_pm_operable(client, ctx):
    """项目：只有查看权的开发不见状态按钮；PM 本人按钮全部可操作。"""
    p = client.post("/api/projects", json={"name": "M30项目按钮", "pm": ctx["pm_pid"],
                                           "planned_start": "2026-08-01", "planned_end": "2026-12-31"},
                    headers=ctx["admin"]).json()["data"]
    d = client.get(f"/api/projects/{p['id']}", headers=ctx["dev_h"]).json()["data"]
    assert d["allowed_transitions"] == [], "无 edit 权限不应下发项目状态按钮"
    _assert_buttons_work(client, ctx["pm_h"], f"/api/projects/{p['id']}", f"/api/projects/{p['id']}/transition")


def test_requirement_terminal_admin_only_submitter_can_close(client, ctx):
    """需求：终态状态按钮仅 admin；提出人走专门关闭按钮。"""
    r = client.post("/api/requirements", json={"title": "M30需求按钮", "req_type": "功能",
                                               "business_domain_id": ctx["domain"], "description": "d"},
                    headers=ctx["ops_h"]).json()["data"]
    d = client.get(f"/api/requirements/{r['id']}", headers=ctx["ops_h"]).json()["data"]
    assert all(x["to"] not in ("closed", "cancelled") for x in d["allowed_transitions"])
    assert d["can_close"] is True  # 提出人专门关闭按钮
    # requester（无 edit）完全无状态按钮
    r2 = client.post("/api/requirements", json={"title": "M30业务需求", "req_type": "功能",
                                                "business_domain_id": ctx["domain"], "description": "d"},
                     headers=ctx["req_h"]).json()["data"]
    d2 = client.get(f"/api/requirements/{r2['id']}", headers=ctx["req_h"]).json()["data"]
    assert d2["allowed_transitions"] == []
    assert d2["can_close"] is True
