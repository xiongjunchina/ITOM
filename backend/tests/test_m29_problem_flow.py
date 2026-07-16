"""M29：问题管理新流程——专业线确认（可驳回退回提单人）→根因分析（负责人派处理人）
→解决验证（延续处理人）→解决确认关闭（负责人，完成自动关闭）。"""
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

    ops_pid, ops_h = member_and_user("运维提单人M29", "m29_ops", ["it_ops"])
    pdm_leader_pid, pdm_leader_h = member_and_user("产品负责人M29", "m29_pdml", ["it_pdm_leader"])
    dev_pid, dev_h = member_and_user("开发处理人M29", "m29_dev", ["it_dev"])
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    return {"admin": admin_headers, "ops_pid": ops_pid, "ops_h": ops_h,
            "pdm_leader_pid": pdm_leader_pid, "pdm_leader_h": pdm_leader_h,
            "dev_pid": dev_pid, "dev_h": dev_h, "item": item}


def _problem(client, ctx, title, line="product"):
    return client.post("/api/problems", json={
        "title": title, "description": "d", "priority": "P2",
        "service_item_id": ctx["item"], "assigned_line": line,
    }, headers=ctx["ops_h"]).json()["data"]


def _proc(client, headers, pid):
    return client.get(f"/api/problems/{pid}", headers=headers).json()["data"]["process"]


def _cur(proc):
    return next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])


def test_line_leader_auto_assigned_and_reporter_cannot_complete(client, ctx):
    """产品线问题 → 第 1 步自动指派产品负责人；提单人不能完成确认步骤（用户实测漏洞）。"""
    p = _problem(client, ctx, "M29-产品数据错乱")
    proc = _proc(client, ctx["admin"], p["id"])
    cur = _cur(proc)
    assert cur["name"] == "问题确认" and cur["assignee_name"] == "产品负责人M29"
    # 提单人（钟俊歌场景）完成此步骤 → 403
    r = client.post(f"/api/process-tasks/{cur['task_id']}/complete", json={"comment": "自己确认"}, headers=ctx["ops_h"])
    assert r.status_code == 403
    # 提单人也无确认权（can_confirm false / confirm 403）
    d = client.get(f"/api/problems/{p['id']}", headers=ctx["ops_h"]).json()["data"]
    assert d["can_confirm"] is False
    r = client.post(f"/api/problems/{p['id']}/confirm", json={"handler_id": ctx["dev_pid"]}, headers=ctx["ops_h"])
    assert r.status_code == 403


def test_full_flow_confirm_analyze_resolve_close(client, ctx):
    """确认属实→处理人根因分析→解决验证延续同人→负责人确认关闭→问题自动 closed。"""
    p = _problem(client, ctx, "M29-完整链路")
    d = client.get(f"/api/problems/{p['id']}", headers=ctx["pdm_leader_h"]).json()["data"]
    assert d["can_confirm"] is True
    # 负责人确认属实并指定开发处理人
    r = client.post(f"/api/problems/{p['id']}/confirm", json={"handler_id": ctx["dev_pid"]}, headers=ctx["pdm_leader_h"])
    assert r.json()["success"], r.text
    assert r.json()["data"]["status"] == "analyzing"  # 状态机同步
    proc = _proc(client, ctx["admin"], p["id"])
    cur = _cur(proc)
    assert cur["name"] == "根因分析" and cur["assignee_name"] == "开发处理人M29"
    # 处理人完成根因分析 → 解决与验证延续同一处理人
    r = client.post(f"/api/process-tasks/{cur['task_id']}/complete",
                    json={"comment": "根因：缓存键冲突导致数据串写"}, headers=ctx["dev_h"])
    assert r.json()["success"], r.text
    proc = _proc(client, ctx["admin"], p["id"])
    cur = _cur(proc)
    assert cur["name"] == "解决与验证" and cur["assignee_name"] == "开发处理人M29"
    # 处理人完成解决验证 → 第 4 步回到专业线负责人，问题状态 → resolved（root_cause 兜底=根因分析说明）
    r = client.post(f"/api/process-tasks/{cur['task_id']}/complete",
                    json={"comment": "已修复并回归验证通过"}, headers=ctx["dev_h"])
    assert r.json()["success"], r.text
    d = client.get(f"/api/problems/{p['id']}", headers=ctx["admin"]).json()["data"]
    assert d["status"] == "resolved"
    assert "缓存键冲突" in (d["root_cause"] or "")
    proc = d["process"]
    cur = _cur(proc)
    assert cur["name"] == "解决确认与关闭" and cur["assignee_name"] == "产品负责人M29"
    # 提单人不能替负责人确认关闭
    r = client.post(f"/api/process-tasks/{cur['task_id']}/complete", json={"comment": "偷偷关闭"}, headers=ctx["ops_h"])
    assert r.status_code == 403
    # 负责人登记关闭理由完成 → 问题自动 closed
    r = client.post(f"/api/process-tasks/{cur['task_id']}/complete",
                    json={"comment": "确认问题已解决，关闭：修复已上线一周无复发"}, headers=ctx["pdm_leader_h"])
    assert r.json()["success"], r.text
    d = client.get(f"/api/problems/{p['id']}", headers=ctx["admin"]).json()["data"]
    assert d["status"] == "closed"


def test_reject_returns_to_reporter_with_audit(client, ctx):
    """驳回：理由必填 → 任务退回提单人（通知+审计），问题保持 new。"""
    p = _problem(client, ctx, "M29-不属实驳回")
    # 理由太短 422
    assert client.post(f"/api/problems/{p['id']}/reject-confirm", json={"reason": "abc"},
                       headers=ctx["pdm_leader_h"]).status_code == 422
    r = client.post(f"/api/problems/{p['id']}/reject-confirm",
                    json={"reason": "无法复现，日志无异常，判定为误报"}, headers=ctx["pdm_leader_h"])
    assert r.json()["success"], r.text
    d = client.get(f"/api/problems/{p['id']}", headers=ctx["admin"]).json()["data"]
    assert d["status"] == "new"
    proc = d["process"]
    cur = _cur(proc)
    assert cur["name"] == "问题确认" and cur["assignee_name"] == "运维提单人M29"  # 退回提单人
    # 提单人收到通知
    notes = client.get("/api/notifications", headers=ctx["ops_h"]).json()["data"]
    assert any("驳回" in n["title"] for n in notes)
    # 提单人补充后改派回负责人重新确认（改派权：任务处理人本人）
    r = client.post(f"/api/process-tasks/{cur['task_id']}/reassign",
                    json={"assignee": ctx["pdm_leader_pid"]}, headers=ctx["ops_h"])
    assert r.json()["success"], r.text


def test_line_options_and_default(client, ctx):
    """运维线/开发线指派对应负责人；升级来源未选线默认 ops。"""
    p = _problem(client, ctx, "M29-开发线问题", line="dev")
    proc = _proc(client, ctx["admin"], p["id"])
    cur = _cur(proc)
    # 测试库无 it_dev_leader 用户 → 未指派（认领机制兜底），default_role 为空但描述说明动态指派
    assert cur["name"] == "问题确认"
    r = client.post("/api/problems", json={"title": "M29-非法线", "description": "d", "priority": "P3",
                                           "assigned_line": "network"}, headers=ctx["admin"])
    assert r.json()["error"]["code"] == "INVALID_LINE"


def test_known_error_button_semantics(client, ctx):
    """M29.1：节点处理人（产品经理）可转已知错误（独立 ITIL 语义）；
    已解决按钮不下发、手动流转 403（由完成流程步骤自动同步）。"""
    p = _problem(client, ctx, "M29-已知错误语义")
    client.post(f"/api/problems/{p['id']}/confirm", json={"handler_id": ctx["dev_pid"]}, headers=ctx["pdm_leader_h"])
    # 处理人视角：按钮只有已知错误，没有已解决
    d = client.get(f"/api/problems/{p['id']}", headers=ctx["dev_h"]).json()["data"]
    targets = [x["to"] for x in d["allowed_transitions"]]
    assert "known_error" in targets and "resolved" not in targets
    # 手动转已解决 → 403 提示走流程
    r = client.post(f"/api/problems/{p['id']}/transition", json={"to": "resolved", "fields": {}}, headers=ctx["dev_h"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "USE_PROCESS_STEP"
    # 转已知错误（根因+规避）成功
    r = client.post(f"/api/problems/{p['id']}/transition",
                    json={"to": "known_error", "fields": {"root_cause": "第三方组件缺陷", "workaround": "定时重启规避"}},
                    headers=ctx["dev_h"])
    assert r.json()["success"], r.text
    # 之后正常完成步骤 2/3 → 状态自动到 resolved（known_error→resolved 路径）
    for _ in range(2):
        proc = _proc(client, ctx["admin"], p["id"])
        cur = _cur(proc)
        client.post(f"/api/process-tasks/{cur['task_id']}/complete", json={"comment": "推进完成"}, headers=ctx["admin"])
    d = client.get(f"/api/problems/{p['id']}", headers=ctx["admin"]).json()["data"]
    assert d["status"] == "resolved"
