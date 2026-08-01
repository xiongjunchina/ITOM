"""M84：IT 员工网页单据分流与速查。"""

import pytest


@pytest.fixture(scope="module")
def intake_users(client, admin_headers):
    def member_and_user(name: str, username: str, roles: list[str]):
        member = client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]
        created = client.post(
            "/api/admin/users",
            json={"username": username, "password": "pass123", "roles": roles, "person_id": member["id"]},
            headers=admin_headers,
        )
        assert created.status_code == 200, created.text
        token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
        return {"Authorization": f"Bearer {token}"}

    return {
        "it_ops": member_and_user("M84 运维工程师", "m84_ops", ["it_ops"]),
        "requester": member_and_user("M84 业务申请人", "m84_requester", ["requester"]),
    }


def test_it_staff_can_read_guide_and_get_explainable_recommendation(client, intake_users):
    guide = client.get("/api/it-document-guide", headers=intake_users["it_ops"])
    assert guide.status_code == 200, guide.text
    data = guide.json()["data"]
    assert data["staff_intake"]["enabled"] is True
    assert {"service_request", "incident", "change", "problem", "requirement", "project"} == {
        item["type"] for item in data["documents"]
    }
    assert "incident" in data["staff_intake"]["available_types"]

    recommendation = client.post(
        "/api/staff-intake/recommend",
        json={"broad_impact": True},
        headers=intake_users["it_ops"],
    )
    assert recommendation.status_code == 200, recommendation.text
    body = recommendation.json()["data"]
    assert body["recommended_type"] == "incident"
    assert body["target_path"] == "/itsm/incidents?create=1"
    assert body["reason"]
    assert body["counterexample"]


def test_admin_can_use_document_creation_guide(client, admin_headers):
    guide = client.get("/api/it-document-guide", headers=admin_headers)
    assert guide.status_code == 200, guide.text
    assert guide.json()["data"]["staff_intake"]["enabled"] is True
    recommendation = client.post(
        "/api/staff-intake/recommend",
        json={"new_capability": True},
        headers=admin_headers,
    )
    assert recommendation.status_code == 200, recommendation.text
    assert recommendation.json()["data"]["recommended_type"] == "requirement"


def test_business_requester_cannot_use_staff_recommendation(client, intake_users):
    guide = client.get("/api/it-document-guide", headers=intake_users["requester"])
    assert guide.status_code == 200, guide.text
    assert guide.json()["data"]["staff_intake"]["enabled"] is False

    recommendation = client.post(
        "/api/staff-intake/recommend",
        json={"new_capability": True},
        headers=intake_users["requester"],
    )
    assert recommendation.status_code == 403
    assert recommendation.json()["error"]["code"] == "IT_STAFF_ONLY"
