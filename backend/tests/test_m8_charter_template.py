"""M8/M9：章程模板（单 WBS 表，WBS编号层级+里程碑标志）下载、解析、导入建含层级/依赖/里程碑的项目。"""


def test_charter_template_download(client, admin_headers):
    r = client.get("/api/projects/charter/template", headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml")
    assert r.content[:2] == b"PK" and len(r.content) > 1000


def _parse_template(client, admin_headers):
    raw = client.get("/api/projects/charter/template", headers=admin_headers).content
    return client.post("/api/projects/charter/parse",
                       files={"file": ("charter_template.docx", raw,
                                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                       headers=admin_headers).json()["data"]


def test_generated_template_parses(client, admin_headers):
    """WBS 表(10列，含阶段/编号/词典/DoD/里程碑/前置) + 风险表各自解析、无结构告警。"""
    data = _parse_template(client, admin_headers)
    f, d = data["fields"], data["drafts"]
    assert f["name"] and f["pm_name"] and f["budget_10k"] == 50.0
    assert len(d["wbs"]) == 5
    by_code = {w["wbs_code"]: w for w in d["wbs"]}
    assert by_code["1.2"]["predecessor_codes"] == "1.1"  # 前置按 WBS编号
    assert by_code["1"]["wbs_dict"] and by_code["1"]["assignee_name"] == "张三" and by_code["1"]["stage"]
    # 里程碑=WBS 勾选「是」（编号 2、3）
    assert by_code["2"]["is_milestone"] is True and by_code["3"]["is_milestone"] is True
    assert by_code["1"]["is_milestone"] is False
    assert len(d["risks"]) == 2 and "milestones" not in d
    assert not any("未解析" in w for w in data["warnings"])
    # M13 结构化章节：背景/目标/范围(做与不做)/资源说明 + §2 组织表分流
    assert f["background"] and f["goals"] and f["scope_in"] and f["scope_out"]
    assert "服务器" in f["resource_note"]
    assert [m["name"] for m in f["org_members"]] == ["李四", "王五"]
    assert [m["name"] for m in f["stakeholders"]] == ["赵总", "某供应商"]
    assert f["stakeholders"][0]["duty"] and f["org_members"][0]["role"]
    assert f["description"] is None  # 拼接式描述已废弃


def test_charter_create_builds_hierarchy_deps_milestones(client, admin_headers):
    """建项目：WBS 层级(编号前缀)、前置(编号)、里程碑标志正确落库，里程碑跟踪派生。"""
    def member(name):
        return client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]["id"]

    pm = member("章程PM")
    member("张三"), member("李四"), member("王五")
    data = _parse_template(client, admin_headers)
    f = data["fields"]
    f["pm"] = pm
    r = client.post("/api/projects/charter/create", json={
        "fields": f, "wbs": data["drafts"]["wbs"], "risks": data["drafts"]["risks"],
    }, headers=admin_headers)
    assert r.json()["success"], r.text
    pid = r.json()["data"]["project_id"]
    assert r.json()["data"]["created"]["wbs"] == 5 and r.json()["data"]["created"]["milestones"] == 2

    # M13：结构化章程字段落库并在详情返回
    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()["data"]
    assert detail["background"] and detail["scope_out"] and detail["resource_note"]
    assert len(detail["org_members"]) == 2 and len(detail["stakeholders"]) == 2
    assert detail["stakeholders"][0]["name"] == "赵总"

    wbs = client.get(f"/api/projects/{pid}/wbs", headers=admin_headers).json()["data"]
    by_name = {w["name"]: w for w in wbs}
    # 层级：需求调研/方案设计 挂在 需求与设计 下
    assert by_name["需求调研"]["parent_task_id"] == by_name["需求与设计"]["id"]
    # 前置：方案设计←需求调研
    assert by_name["需求调研"]["id"] in by_name["方案设计"]["predecessor_ids"]
    # 里程碑标志 + 责任人姓名解析
    assert by_name["开发实现"]["is_milestone"] is True and by_name["测试上线"]["is_milestone"] is True
    assert by_name["方案设计"]["assignee_name"] == "李四"
    # 里程碑跟踪派生：仅里程碑=是 的行（开发实现、测试上线）
    track = client.get(f"/api/projects/{pid}/milestone-tracking", headers=admin_headers).json()["data"]
    assert {t["name"] for t in track} == {"开发实现", "测试上线"}


def test_template_requires_create_perm(client, admin_headers):
    m = client.post("/api/members", json={"name": "章程测试开发"}, headers=admin_headers).json()["data"]
    client.post("/api/admin/users", json={"username": "charter_dev", "password": "pass123",
                                          "roles": ["it_dev"], "person_id": m["id"]}, headers=admin_headers)
    tok = client.post("/api/auth/login", json={"username": "charter_dev", "password": "pass123"}).json()["data"]["token"]
    r = client.get("/api/projects/charter/template", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
