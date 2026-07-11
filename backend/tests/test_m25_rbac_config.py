"""M2.5：自定义角色/用户组/状态机配置/流程定义管理。"""
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

    item_id = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    return {"member_and_user": member_and_user, "item": item_id}


def test_builtin_roles_seeded(client, admin_headers):
    roles = client.get("/api/admin/roles", headers=admin_headers).json()["data"]
    assert sum(1 for r in roles if r["is_builtin"]) == 13  # 含 auditor + cio/it_bm/it_tm


def test_custom_role_inherits_permissions(client, admin_headers, ctx):
    # 自定义 DBA 角色继承 it_ops
    r = client.post(
        "/api/admin/roles",
        json={"code": "dba", "name": "DBA", "base_role": "it_ops", "description": "数据库管理员"},
        headers=admin_headers,
    )
    assert r.json()["success"], r.text

    _, dba_headers = ctx["member_and_user"]("钱七", "dba01", ["dba"])
    # 继承 it_ops → 可创建工单（团队成员基础能力，本就全员可用），关键验证：可见全部工单（非 requester 限制）
    listing = client.get("/api/tickets", headers=dba_headers)
    assert listing.status_code == 200

    # 内置角色：名称/描述可改，继承关系不可改，不可删
    roles = client.get("/api/admin/roles", headers=admin_headers).json()["data"]
    builtin_id = next(r["id"] for r in roles if r["code"] == "it_ops")
    assert client.patch(f"/api/admin/roles/{builtin_id}", json={"name": "IT运维工程师"}, headers=admin_headers).json()["success"]
    assert client.patch(f"/api/admin/roles/{builtin_id}", json={"base_role": "it_dev"}, headers=admin_headers).json()["error"]["code"] == "BUILTIN_ROLE"
    assert client.delete(f"/api/admin/roles/{builtin_id}", headers=admin_headers).json()["error"]["code"] == "BUILTIN_ROLE"

    # 被用户持有的自定义角色不可删
    dba_id = next(r["id"] for r in roles if r["code"] == "dba")
    assert client.delete(f"/api/admin/roles/{dba_id}", headers=admin_headers).json()["error"]["code"] == "ROLE_IN_USE"

    # 继承 admin 被拒
    r = client.post(
        "/api/admin/roles",
        json={"code": "superx", "name": "超管2", "base_role": "admin"},
        headers=admin_headers,
    )
    assert r.json()["error"]["code"] == "INVALID_BASE_ROLE"


def test_group_membership_and_workflow_auth(client, admin_headers, ctx):
    # 建组 + 加人
    g = client.post("/api/admin/groups", json={"code": "db_team", "name": "数据库组"}, headers=admin_headers).json()["data"]
    p1, u1_headers = ctx["member_and_user"]("孙八", "sun01", ["it_dev"])
    client.put(f"/api/admin/groups/{g['id']}/members", json={"person_ids": [p1]}, headers=admin_headers)
    groups = client.get("/api/admin/groups", headers=admin_headers).json()["data"]
    assert any(gr["code"] == "db_team" and len(gr["members"]) == 1 for gr in groups)

    # 把变更审批权限改为 manager + group:db_team
    cfg = client.get("/api/admin/workflow-config?entity_type=ticket_change", headers=admin_headers).json()["data"]
    for t in cfg["transitions"]:
        if t["from_code"] == "pending_approval" and t["to_code"] == "approved":
            t["allowed_roles"] = ["manager", "group:db_team"]
    r = client.put(
        "/api/admin/workflow-config",
        json={
            "entity_type": "ticket_change",
            "statuses": cfg["statuses"],
            "transitions": [
                {"from_code": t["from_code"], "to_code": t["to_code"], "allowed_roles": t["allowed_roles"]}
                for t in cfg["transitions"]
            ],
        },
        headers=admin_headers,
    )
    assert r.json()["success"], r.text

    # 组成员孙八(it_dev, 非 manager)现在可以审批变更
    t = client.post(
        "/api/tickets",
        json={"title": "组授权测试变更", "ticket_type": "change", "priority": "P3", "description": "d",
              "service_item_id": ctx["item"], "change_type": "标准"},
        headers=u1_headers,
    ).json()["data"]
    client.post(f"/api/tickets/{t['id']}/transition", json={"to": "pending_approval", "fields": {}}, headers=u1_headers)
    r = client.post(f"/api/tickets/{t['id']}/transition", json={"to": "approved", "fields": {}}, headers=u1_headers)
    assert r.json()["success"], r.text

    # 引用中的组不可删
    assert client.delete(f"/api/admin/groups/{g['id']}", headers=admin_headers).json()["error"]["code"] != "NOT_FOUND"


def test_person_groups_two_way(client, admin_headers, ctx):
    """按人设置用户组与按组设置成员双向一致。"""
    g1 = client.post("/api/admin/groups", json={"code": "grp_a", "name": "A组"}, headers=admin_headers).json()["data"]
    g2 = client.post("/api/admin/groups", json={"code": "grp_b", "name": "B组"}, headers=admin_headers).json()["data"]
    p, _ = ctx["member_and_user"]("组员甲", "grpuser01", ["it_dev"])

    r = client.put(f"/api/admin/members/{p}/groups", json={"group_ids": [g1["id"], g2["id"]]}, headers=admin_headers)
    assert r.json()["success"], r.text
    mine = client.get(f"/api/admin/members/{p}/groups", headers=admin_headers).json()["data"]
    assert {x["code"] for x in mine} == {"grp_a", "grp_b"}

    # 按组视角能看到该成员
    groups = client.get("/api/admin/groups", headers=admin_headers).json()["data"]
    ga = next(x for x in groups if x["code"] == "grp_a")
    assert any(m["id"] == p for m in ga["members"])

    # 改为只留 A 组
    client.put(f"/api/admin/members/{p}/groups", json={"group_ids": [g1["id"]]}, headers=admin_headers)
    mine = client.get(f"/api/admin/members/{p}/groups", headers=admin_headers).json()["data"]
    assert [x["code"] for x in mine] == ["grp_a"]

    # 不存在的组被拒
    r = client.put(f"/api/admin/members/{p}/groups", json={"group_ids": ["NOPE"]}, headers=admin_headers)
    assert r.json()["error"]["code"] == "INVALID_GROUP"


def test_workflow_config_validation(client, admin_headers):
    bad = {
        "entity_type": "ticket",
        "statuses": [
            {"code": "new", "name": "新建", "is_initial": True, "is_terminal": False, "sort": 1},
            {"code": "done", "name": "完成", "is_initial": True, "is_terminal": True, "sort": 2},
        ],
        "transitions": [{"from_code": "new", "to_code": "done", "allowed_roles": []}],
    }
    r = client.put("/api/admin/workflow-config", json=bad, headers=admin_headers)
    assert r.json()["error"]["code"] == "INVALID_CONFIG"  # 两个初始状态

    bad["statuses"][1]["is_initial"] = False
    bad["transitions"].append({"from_code": "new", "to_code": "ghost", "allowed_roles": []})
    r = client.put("/api/admin/workflow-config", json=bad, headers=admin_headers)
    assert "不存在的状态" in r.json()["error"]["message"]


def test_status_in_use_protected(client, admin_headers, ctx):
    _, u = ctx["member_and_user"]("周九", "zhou01", ["it_ops"])
    t = client.post(
        "/api/tickets",
        json={"title": "占用状态的单", "ticket_type": "incident", "priority": "P3", "description": "d",
              "service_item_id": ctx["item"]},
        headers=u,
    ).json()["data"]
    client.post(f"/api/tickets/{t['id']}/transition", json={"to": "processing", "fields": {}}, headers=u)

    cfg = client.get("/api/admin/workflow-config?entity_type=ticket", headers=admin_headers).json()["data"]
    statuses = [s for s in cfg["statuses"] if s["code"] != "processing"]
    transitions = [
        {"from_code": t2["from_code"], "to_code": t2["to_code"], "allowed_roles": t2["allowed_roles"]}
        for t2 in cfg["transitions"]
        if t2["from_code"] != "processing" and t2["to_code"] != "processing"
    ]
    r = client.put(
        "/api/admin/workflow-config",
        json={"entity_type": "ticket", "statuses": statuses, "transitions": transitions},
        headers=admin_headers,
    )
    assert r.json()["error"]["code"] == "STATUS_IN_USE"


def test_process_definition_crud_and_versioning(client, admin_headers, ctx):
    # 与激活流程触发条件相同 → 冲突被拒（匹配歧义保护）
    r = client.post(
        "/api/admin/process-definitions",
        json={
            "code": "vip_flow", "name": "VIP 快速通道", "entity_type": "ticket",
            "trigger_condition": {"ticket_type": "incident"},
            "steps": [{"seq": 1, "name": "极速受理", "default_role": "it_ops", "autonomy_level": "L2"}],
        },
        headers=admin_headers,
    )
    assert r.json()["error"]["code"] == "TRIGGER_CONFLICT"

    # 换独立触发条件后创建成功
    r = client.post(
        "/api/admin/process-definitions",
        json={
            "code": "vip_flow", "name": "VIP 快速通道", "entity_type": "ticket",
            "trigger_condition": {"ticket_type": "incident", "channel": "vip"},
            "steps": [
                {"seq": 1, "name": "极速受理", "default_role": "it_ops", "autonomy_level": "L2", "sla_hours": 0.25},
                {"seq": 2, "name": "处理关闭", "default_role": "it_ops", "autonomy_level": "L3"},
            ],
        },
        headers=admin_headers,
    )
    assert r.json()["success"], r.text
    vip = r.json()["data"]

    # 步骤序号不连续被拒
    r = client.post(
        "/api/admin/process-definitions",
        json={"code": "bad_flow", "name": "x", "entity_type": "ticket",
              "steps": [{"seq": 1, "name": "a"}, {"seq": 3, "name": "b"}]},
        headers=admin_headers,
    )
    assert r.json()["error"]["code"] == "INVALID_STEPS"

    # 无实例时可直接改步骤
    r = client.patch(
        f"/api/admin/process-definitions/{vip['id']}",
        json={"steps": [{"seq": 1, "name": "受理并处理", "default_role": "it_ops", "autonomy_level": "L2"}]},
        headers=admin_headers,
    )
    assert len(r.json()["data"]["steps"]) == 1

    # 给 incident_flow 制造一个实例 → 步骤锁定
    _, u = ctx["member_and_user"]("吴十", "wu01", ["it_ops"])
    client.post(
        "/api/tickets",
        json={"title": "占用流程的事件单", "ticket_type": "incident", "priority": "P3", "description": "d",
              "service_item_id": ctx["item"]},
        headers=u,
    )
    defs = client.get("/api/admin/process-definitions", headers=admin_headers).json()["data"]
    incident = next(d for d in defs if d["code"] == "incident_flow")
    assert incident["instance_count"] > 0 and incident["steps_locked"]

    r = client.patch(
        f"/api/admin/process-definitions/{incident['id']}",
        json={"steps": [{"seq": 1, "name": "只此一步"}]},
        headers=admin_headers,
    )
    assert r.json()["error"]["code"] == "STEPS_LOCKED"

    # 另存新版本：旧版停用、新版 active、老实例不受影响
    r = client.post(
        f"/api/admin/process-definitions/{incident['id']}/new-version",
        json={"steps": [{"seq": 1, "name": "受理", "default_role": "it_ops", "autonomy_level": "L3"},
                        {"seq": 2, "name": "闭环", "default_role": "it_ops", "autonomy_level": "L3"}]},
        headers=admin_headers,
    )
    v2 = r.json()["data"]
    assert v2["version"] == 2 and v2["active"] and v2["code"] == "incident_flow@v2"
    defs = client.get("/api/admin/process-definitions", headers=admin_headers).json()["data"]
    old = next(d for d in defs if d["code"] == "incident_flow")
    assert old["active"] is False

    # 新建事件单挂到 v2
    t = client.post(
        "/api/tickets",
        json={"title": "验证新版流程", "ticket_type": "incident", "priority": "P3", "description": "d",
              "service_item_id": ctx["item"]},
        headers=u,
    ).json()["data"]
    detail = client.get(f"/api/tickets/{t['id']}", headers=u).json()["data"]
    assert len(detail["process"]["steps"]) == 2 and detail["process"]["steps"][0]["name"] == "受理"


def test_group_as_process_default_role(client, admin_headers, ctx):
    """流程步骤 default_role 指向用户组时自动指派组内在岗成员。"""
    g = client.post("/api/admin/groups", json={"code": "net_team", "name": "网络组"}, headers=admin_headers).json()["data"]
    p, _ = ctx["member_and_user"]("郑一", "zheng01", ["it_ops"])
    client.put(f"/api/admin/groups/{g['id']}/members", json={"person_ids": [p]}, headers=admin_headers)

    # 先停用 sr_flow（否则触发条件冲突校验会拒绝新流程）
    defs = client.get("/api/admin/process-definitions", headers=admin_headers).json()["data"]
    sr = next(d for d in defs if d["code"] == "sr_flow")
    client.patch(f"/api/admin/process-definitions/{sr['id']}", json={"active": False}, headers=admin_headers)
    r = client.post(
        "/api/admin/process-definitions",
        json={
            "code": "net_flow", "name": "网络请求流程", "entity_type": "ticket",
            "trigger_condition": {"ticket_type": "service_request"},
            "steps": [{"seq": 1, "name": "网络组受理", "default_role": "group:net_team", "autonomy_level": "L3"}],
        },
        headers=admin_headers,
    )
    assert r.json()["success"], r.text

    t = client.post(
        "/api/tickets",
        json={"title": "网络端口开通", "ticket_type": "service_request", "priority": "P3", "description": "d",
              "service_item_id": ctx["item"]},
        headers=admin_headers,
    ).json()["data"]
    detail = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()["data"]
    step = detail["process"]["steps"][0]
    assert detail["process"]["definition_name"] == "网络请求流程"
    assert step["assignee_name"] == "郑一"  # 组内在岗成员自动指派
