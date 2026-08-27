"""M106：流程运行时节点是详情页阶段和评估操作的唯一事实来源。"""

import pytest

from app.db import SessionLocal
from app.models import Requirement


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    domain = client.get("/api/admin/business-domains", headers=admin_headers).json()["data"][0]["id"]
    return {"admin": admin_headers, "item": item, "domain": domain}


def _requirement(client, ctx, title="M106流程一致性"):
    response = client.post(
        "/api/requirements",
        json={"title": title, "req_type": "功能", "business_domain_id": ctx["domain"], "description": "验证流程阶段"},
        headers=ctx["admin"],
    )
    assert response.json()["success"], response.text
    return response.json()["data"]["id"]


def _detail(client, headers, requirement_id):
    response = client.get(f"/api/requirements/{requirement_id}", headers=headers)
    assert response.json()["success"], response.text
    return response.json()["data"]


def test_requirement_detail_projects_stage_from_pending_task(client, ctx):
    requirement_id = _requirement(client, ctx)
    initial = _detail(client, ctx["admin"], requirement_id)
    assert initial["process"]["current_step_seq"] == 1
    assert "需求评审" in initial["process"]["current_step_name"]
    assert initial["status"] == "evaluating"

    current = next(step for step in initial["process"]["steps"] if step["seq"] == initial["process"]["current_step_seq"])
    advanced = client.post(
        f"/api/process-tasks/{current['task_id']}/complete",
        json={"comment": "M106完成需求评审"},
        headers=ctx["admin"],
    )
    assert advanced.json()["success"], advanced.text

    detail = _detail(client, ctx["admin"], requirement_id)
    assert detail["process"]["current_step_seq"] == 2
    assert "方案评估" in detail["process"]["current_step_name"]
    assert detail["status"] == "analyzing"

    # 模拟存量单据的落后业务状态：详情仍必须以当前流程任务投影为准。
    with SessionLocal() as db:
        record = db.get(Requirement, requirement_id)
        assert record is not None
        record.status = "registered"
        db.commit()
    projected = _detail(client, ctx["admin"], requirement_id)
    assert projected["status"] == "analyzing"


def test_requirement_scoring_is_rejected_after_evaluation_nodes(client, ctx):
    requirement_id = _requirement(client, ctx, "M106评分阶段关闭")
    for _ in range(2):
        detail = _detail(client, ctx["admin"], requirement_id)
        current = next(step for step in detail["process"]["steps"] if step["seq"] == detail["process"]["current_step_seq"])
        response = client.post(
            f"/api/process-tasks/{current['task_id']}/complete",
            json={"comment": "M106推进流程"},
            headers=ctx["admin"],
        )
        assert response.json()["success"], response.text

    detail = _detail(client, ctx["admin"], requirement_id)
    assert detail["process"]["current_step_seq"] >= 3
    response = client.post(
        f"/api/requirements/{requirement_id}/score",
        json={"d1_strategy": 5, "d2_value": 5, "d3_tech": 5, "d4_org": 5, "d5_risk": 1, "d6_speed": 5},
        headers=ctx["admin"],
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EVAL_STAGE_CLOSED"


def test_my_todos_returns_current_process_tasks(client, ctx):
    ticket = client.post(
        "/api/tickets",
        json={
            "title": "M106待办聚合",
            "ticket_type": "service_request",
            "priority": "P4",
            "description": "验证个人中心待办",
            "service_item_id": ctx["item"],
        },
        headers=ctx["admin"],
    ).json()["data"]
    response = client.get("/api/auth/me/todos", headers=ctx["admin"])
    assert response.json()["success"], response.text
    item = next((row for row in response.json()["data"] if row["code"] == ticket["ticket_code"]), None)
    assert item is not None
    assert item["entity_type"] == "ticket"
    assert item["link"] == f"/itsm/tickets/{ticket['id']}"
