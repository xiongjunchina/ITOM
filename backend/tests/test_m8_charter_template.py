"""M8：章程模板（里程碑表 + WBS 表分离）下载、解析、并经导入创建含层级/依赖的项目。"""


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
    """里程碑表(3列) / WBS表(8列，含上级+前置) / 风险表(5列) 各自解析、无结构告警。"""
    data = _parse_template(client, admin_headers)
    f, d = data["fields"], data["drafts"]
    assert f["name"] and f["pm_name"] and f["planned_start"] and f["planned_end"] and f["budget_10k"] == 50.0
    # WBS：5 任务，字段完整
    assert len(d["wbs"]) == 5
    by_name = {w["name"]: w for w in d["wbs"]}
    assert by_name["方案设计"]["parent_name"] == "需求与设计"
    assert by_name["方案设计"]["predecessor_names"] == "需求调研"
    assert by_name["需求与设计"]["assignee_name"] == "张三"
    assert by_name["测试上线"]["start_date"] and by_name["测试上线"]["deliverable"]
    # 里程碑：2 条（独立于 WBS）
    assert {m["name"] for m in d["milestones"]} == {"需求评审通过", "系统上线"}
    assert len(d["risks"]) == 2
    assert not any("未解析" in w for w in data["warnings"])


def test_charter_create_builds_hierarchy_and_deps(client, admin_headers):
    """用模板解析结果建项目：WBS 层级(parent)与前置(predecessor)正确落库。"""
    # 需要真实项目经理 + 负责人
    def member(name):
        return client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]["id"]

    pm = member("章程PM")
    m_zhang = member("张三")  # 与模板负责人同名 → 解析到该人员
    m_li = member("李四")
    data = _parse_template(client, admin_headers)
    f = data["fields"]
    f["pm"] = pm  # parse 未匹配到 PM，手工指定
    r = client.post("/api/projects/charter/create", json={
        "fields": f, "wbs": data["drafts"]["wbs"],
        "milestones": data["drafts"]["milestones"], "risks": data["drafts"]["risks"],
    }, headers=admin_headers)
    assert r.json()["success"], r.text
    pid = r.json()["data"]["project_id"]
    assert r.json()["data"]["created"] == {"wbs": 5, "milestones": 2, "risks": 2}

    wbs = client.get(f"/api/projects/{pid}/wbs", headers=admin_headers).json()["data"]
    by_name = {w["name"]: w for w in wbs}
    # 层级：需求调研/方案设计 挂在 需求与设计 下
    assert by_name["需求调研"]["parent_task_id"] == by_name["需求与设计"]["id"]
    assert by_name["方案设计"]["parent_task_id"] == by_name["需求与设计"]["id"]
    # 前置：方案设计←需求调研，测试上线←开发实现
    assert by_name["需求调研"]["id"] in by_name["方案设计"]["predecessor_ids"]
    assert by_name["开发实现"]["id"] in by_name["测试上线"]["predecessor_ids"]
    # 负责人按姓名解析
    assert by_name["张三" if False else "需求与设计"]["assignee"] == m_zhang
    assert by_name["方案设计"]["assignee"] == m_li
    # 里程碑
    ms = client.get(f"/api/projects/{pid}/milestones", headers=admin_headers).json()["data"]
    assert {m["name"] for m in ms} == {"需求评审通过", "系统上线"}


def test_template_requires_create_perm(client, admin_headers):
    m = client.post("/api/members", json={"name": "章程测试开发"}, headers=admin_headers).json()["data"]
    client.post("/api/admin/users", json={"username": "charter_dev", "password": "pass123",
                                          "roles": ["it_dev"], "person_id": m["id"]}, headers=admin_headers)
    tok = client.post("/api/auth/login", json={"username": "charter_dev", "password": "pass123"}).json()["data"]["token"]
    r = client.get("/api/projects/charter/template", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
