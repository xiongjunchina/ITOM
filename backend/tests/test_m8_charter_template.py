"""M8：项目章程模板下载 + 生成的模板可被章程解析器正确解析（圆环）。"""


def test_charter_template_download(client, admin_headers):
    r = client.get("/api/projects/charter/template", headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml")
    assert "charter_template.docx" in r.headers.get("content-disposition", "")
    assert r.content[:2] == b"PK" and len(r.content) > 1000  # 有效 .docx（zip）


def test_generated_template_parses(client, admin_headers):
    """下载的模板直接回传 parse → 字段/WBS/风险全部解析、无告警。"""
    raw = client.get("/api/projects/charter/template", headers=admin_headers).content
    r = client.post("/api/projects/charter/parse",
                    files={"file": ("charter_template.docx", raw,
                                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                    headers=admin_headers)
    data = r.json()["data"]
    f, d = data["fields"], data["drafts"]
    assert f["name"] and f["pm_name"] and f["planned_start"] and f["planned_end"] and f["budget_10k"] == 50.0
    assert [w["code"] for w in d["wbs"]] == ["M1", "M2", "M3"]
    assert len(d["milestones"]) == 3
    assert len(d["risks"]) == 2 and d["risks"][0]["probability"] in ("高", "中", "低")
    # 无结构性告警（示例项目经理非真实人员的提示属正常）
    assert not any("未解析" in w for w in data["warnings"])


def test_template_requires_create_perm(client, admin_headers):
    # it_dev 无 projects.create → 403
    m = client.post("/api/members", json={"name": "章程测试开发"}, headers=admin_headers).json()["data"]
    client.post("/api/admin/users", json={"username": "charter_dev", "password": "pass123",
                                          "roles": ["it_dev"], "person_id": m["id"]}, headers=admin_headers)
    tok = client.post("/api/auth/login", json={"username": "charter_dev", "password": "pass123"}).json()["data"]["token"]
    r = client.get("/api/projects/charter/template", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
