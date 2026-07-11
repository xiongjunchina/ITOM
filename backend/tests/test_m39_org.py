"""M3.9：组织同步引擎（飞书 SoT）/ 同步记录锁定 / 组织树。"""
import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    return {}


def _snapshot():
    from app.services.org_sync import DeptIn, MemberIn, OrgSnapshot

    return OrgSnapshot(
        departments=[
            DeptIn(external_id="od-root", name="信息技术部"),
            DeptIn(external_id="od-dev", name="开发组", parent_external_id="od-root"),
        ],
        members=[
            MemberIn(external_id="ou-1", name="飞书张三", employee_no="E001", gender="男",
                     employment_type="正式", department_external_id="od-dev",
                     leader_external_id="ou-2", mobile="13800000001"),
            MemberIn(external_id="ou-2", name="飞书李四", employee_no="E002",
                     department_external_id="od-root"),
        ],
    )


def test_org_sync_apply_and_idempotent(client, admin_headers):
    from app.db import SessionLocal
    from app.models import Department, OrgMember
    from app.services.org_sync import apply_org_snapshot

    with SessionLocal() as db:
        stats = apply_org_snapshot(db, "feishu", _snapshot())
        assert stats["dept_created"] == 2 and stats["member_created"] == 2

        # 幂等：重放不重复建
        stats2 = apply_org_snapshot(db, "feishu", _snapshot())
        assert stats2["dept_created"] == 0 and stats2["member_created"] == 0

        zhang = db.query(OrgMember).filter_by(external_id="ou-1").first()
        li = db.query(OrgMember).filter_by(external_id="ou-2").first()
        dev = db.query(Department).filter_by(external_id="od-dev").first()
        assert zhang.department_id == dev.id and zhang.supervisor_id == li.id
        assert dev.parent_id == db.query(Department).filter_by(external_id="od-root").first().id


def test_synced_member_readonly_and_local_fields(client, admin_headers):
    from app.db import SessionLocal
    from app.models import OrgMember

    with SessionLocal() as db:
        zhang_id = db.query(OrgMember).filter_by(external_id="ou-1").first().id

    # 改锁定字段（姓名）被拒
    r = client.patch(f"/api/members/{zhang_id}", json={"name": "本地改名"}, headers=admin_headers)
    assert r.json()["error"]["code"] == "SYNCED_READONLY"
    # 改本地扩展字段（技能/备注）允许
    r = client.patch(f"/api/members/{zhang_id}", json={"skills": ["python"], "remarks": "IT扩展"}, headers=admin_headers)
    assert r.json()["success"], r.text


def test_member_left_and_dept_deactivated_on_disappear(client, admin_headers):
    from app.db import SessionLocal
    from app.models import Department, OrgMember
    from app.services.org_sync import DeptIn, MemberIn, OrgSnapshot, apply_org_snapshot

    smaller = OrgSnapshot(
        departments=[DeptIn(external_id="od-root", name="信息技术部")],
        members=[MemberIn(external_id="ou-2", name="飞书李四", department_external_id="od-root")],
    )
    with SessionLocal() as db:
        stats = apply_org_snapshot(db, "feishu", smaller)
        assert stats["member_left"] == 1 and stats["dept_deactivated"] == 1
        zhang = db.query(OrgMember).filter_by(external_id="ou-1").first()
        assert zhang.status == "离职" and not zhang.is_deleted  # 保留档案
        dev = db.query(Department).filter_by(external_id="od-dev").first()
        assert dev.active is False


def test_local_records_untouched_by_sync(client, admin_headers):
    from app.db import SessionLocal
    from app.models import OrgMember
    from app.services.org_sync import OrgSnapshot, apply_org_snapshot

    local = client.post("/api/members", json={"name": "本地王五"}, headers=admin_headers).json()["data"]
    with SessionLocal() as db:
        apply_org_snapshot(db, "feishu", OrgSnapshot())  # 空快照
        row = db.get(OrgMember, local["id"])
        assert row.status == "在岗"  # 本地记录不受同步影响


def test_org_tree_and_sync_endpoint(client, admin_headers):
    tree = client.get("/api/admin/org-tree", headers=admin_headers).json()["data"]
    assert tree["company"]["name"]
    dev = next((d for d in tree["departments"] if d["name"] == "开发组"), None)
    assert dev is not None and dev["external_source"] == "feishu"
    root = next(d for d in tree["departments"] if d["name"] == "信息技术部")
    assert any(m["name"] == "飞书李四" for m in root["members"])
    assert tree["sync_sources"] == []  # 未配置凭据

    r = client.post("/api/admin/org-sync", json={"source": "feishu"}, headers=admin_headers)
    assert r.status_code == 501 and r.json()["error"]["code"] == "SYNC_NOT_CONFIGURED"
