"""M108：需求驳回退回历史节点、登记人补充重提及存量误终止修复。"""

import pytest

from app.db import SessionLocal
from app.models import AuthUser, ProcessInstance, ProcessTask, Requirement
from app.services import process_engine
from app.services.requirement_returns import repair_rejected_instances


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    domain = client.get("/api/admin/business-domains", headers=admin_headers).json()["data"][0]["id"]
    return {"admin": admin_headers, "domain": domain}


def _register(client, ctx, title):
    response = client.post(
        "/api/requirements",
        json={
            "title": title,
            "req_type": "功能",
            "business_domain_id": ctx["domain"],
            "description": "验证需求退回流程",
        },
        headers=ctx["admin"],
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


def _detail(client, ctx, requirement_id):
    response = client.get(f"/api/requirements/{requirement_id}", headers=ctx["admin"])
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _current(detail):
    return next(
        step
        for step in detail["process"]["steps"]
        if step["seq"] == detail["process"]["current_step_seq"]
    )


def test_return_targets_only_include_reached_prior_positions(client, ctx):
    requirement_id = _register(client, ctx, "M108退回目标约束")
    first = _detail(client, ctx, requirement_id)
    assert first["process"]["return_targets"] == [
        {"seq": 0, "name": "登记人补充", "kind": "requester_supplement"}
    ]

    invalid = client.post(
        f"/api/process-tasks/{_current(first)['task_id']}/reject",
        json={"reason": "尝试退回尚未到达的节点", "target_seq": 2},
        headers=ctx["admin"],
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_RETURN_TARGET"


def test_default_return_goes_to_previous_reached_node(client, ctx):
    requirement_id = _register(client, ctx, "M108默认退回上一节点")
    first = _detail(client, ctx, requirement_id)
    advanced = client.post(
        f"/api/process-tasks/{_current(first)['task_id']}/complete",
        json={"comment": "首节点已处理"},
        headers=ctx["admin"],
    )
    assert advanced.status_code == 200, advanced.text

    second = _detail(client, ctx, requirement_id)
    assert [item["seq"] for item in second["process"]["return_targets"]] == [1, 0]
    returned = client.post(
        f"/api/process-tasks/{_current(second)['task_id']}/reject",
        json={"reason": "方案信息不足，退回上一节点补充"},
        headers=ctx["admin"],
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["data"]["return_target_seq"] == 1

    detail = _detail(client, ctx, requirement_id)
    assert detail["status"] == "evaluating"
    assert detail["process"]["status"] == "running"
    assert detail["process"]["current_step_seq"] == 1
    assert _current(detail)["task_status"] == "待处理"
    assert detail["process"]["return_info"]["reason"] == "方案信息不足，退回上一节点补充"


def test_operator_can_select_any_reached_prior_node(client, ctx):
    requirement_id = _register(client, ctx, "M108选择更早历史节点")
    for comment in ("首节点已处理", "第二节点已处理", "第三节点已处理"):
        detail = _detail(client, ctx, requirement_id)
        response = client.post(
            f"/api/process-tasks/{_current(detail)['task_id']}/complete",
            json={"comment": comment},
            headers=ctx["admin"],
        )
        assert response.status_code == 200, response.text

    approval = _detail(client, ctx, requirement_id)
    assert approval["process"]["current_step_seq"] == 4
    assert [item["seq"] for item in approval["process"]["return_targets"]] == [3, 2, 1, 0]
    returned = client.post(
        f"/api/process-tasks/{_current(approval)['task_id']}/reject",
        json={"reason": "实现条件不完整，退回需求评审重新确认", "target_seq": 1},
        headers=ctx["admin"],
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["data"]["return_target_seq"] == 1

    detail = _detail(client, ctx, requirement_id)
    assert detail["status"] == "evaluating"
    assert detail["process"]["status"] == "running"
    assert detail["process"]["current_step_seq"] == 1
    assert _current(detail)["task_status"] == "待处理"


def test_solution_review_score_can_return_to_selected_review_node(client, ctx):
    requirement_id = _register(client, ctx, "M108方案评估选择退回节点")
    first = _detail(client, ctx, requirement_id)
    response = client.post(
        f"/api/process-tasks/{_current(first)['task_id']}/complete",
        json={"comment": "需求评审通过"},
        headers=ctx["admin"],
    )
    assert response.status_code == 200, response.text

    returned = client.post(
        f"/api/requirements/{requirement_id}/score",
        json={
            "d1_strategy": 3,
            "d2_value": 3,
            "d3_tech": 3,
            "d4_org": 3,
            "d5_risk": 3,
            "d6_speed": 3,
            "decision": "驳回",
            "comment": "方案信息不足，退回需求评审重新确认",
            "return_to_seq": 1,
        },
        headers=ctx["admin"],
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["data"]["flowed_to"] == "evaluating"

    detail = _detail(client, ctx, requirement_id)
    assert detail["process"]["current_step_seq"] == 1
    assert detail["decision"] is None
    assert detail["weighted_total"] is None


def test_historical_rejected_instance_repair_is_idempotent(client, ctx):
    requirement_id = _register(client, ctx, "M108存量驳回修复")
    detail = _detail(client, ctx, requirement_id)
    task_id = _current(detail)["task_id"]

    with SessionLocal() as db:
        actor = db.query(AuthUser).filter(AuthUser.username == "admin").first()
        process_engine.reject_task(db, task_id, actor, "旧版错误地把驳回终止了流程")
        db.commit()

    with SessionLocal() as db:
        requirement = db.get(Requirement, requirement_id)
        instance = (
            db.query(ProcessInstance)
            .filter(ProcessInstance.entity_type == "requirement", ProcessInstance.entity_id == requirement_id)
            .first()
        )
        assert requirement.status == "evaluating"
        assert instance.status == "rejected"
        assert repair_rejected_instances(db) == 1
        db.commit()

    with SessionLocal() as db:
        requirement = db.get(Requirement, requirement_id)
        instance = (
            db.query(ProcessInstance)
            .filter(ProcessInstance.entity_type == "requirement", ProcessInstance.entity_id == requirement_id)
            .first()
        )
        assert requirement.status == "supplementing"
        assert instance.status == "returned"
        assert repair_rejected_instances(db) == 0
        assert (
            db.query(ProcessTask)
            .filter(
                ProcessTask.instance_id == instance.id,
                ProcessTask.status == "待处理",
                ProcessTask.is_deleted.is_(False),
            )
            .count()
            == 0
        )


def test_historical_repair_skips_obsolete_and_on_hold_instances(client, ctx):
    obsolete_id = _register(client, ctx, "M108旧实例不得复活")
    on_hold_id = _register(client, ctx, "M108搁置需求不得复活")

    with SessionLocal() as db:
        actor = db.query(AuthUser).filter(AuthUser.username == "admin").first()
        obsolete_instance = (
            db.query(ProcessInstance)
            .filter(ProcessInstance.entity_type == "requirement", ProcessInstance.entity_id == obsolete_id)
            .first()
        )
        on_hold_instance = (
            db.query(ProcessInstance)
            .filter(ProcessInstance.entity_type == "requirement", ProcessInstance.entity_id == on_hold_id)
            .first()
        )
        obsolete_task = (
            db.query(ProcessTask)
            .filter(ProcessTask.instance_id == obsolete_instance.id, ProcessTask.status == "待处理")
            .first()
        )
        on_hold_task = (
            db.query(ProcessTask)
            .filter(ProcessTask.instance_id == on_hold_instance.id, ProcessTask.status == "待处理")
            .first()
        )
        process_engine.reject_task(db, obsolete_task.id, actor, "旧流程实例错误终止")
        process_engine.reject_task(db, on_hold_task.id, actor, "搁置需求旧流程错误终止")
        db.get(Requirement, on_hold_id).status = "on_hold"
        db.flush()
        db.add(
            ProcessInstance(
                definition_id=obsolete_instance.definition_id,
                entity_type="requirement",
                entity_id=obsolete_id,
                status="completed",
                current_step_seq=obsolete_instance.current_step_seq,
            )
        )
        db.commit()

    with SessionLocal() as db:
        assert repair_rejected_instances(db) == 0
        assert (
            db.query(ProcessInstance)
            .filter(ProcessInstance.entity_type == "requirement", ProcessInstance.entity_id == obsolete_id)
            .order_by(ProcessInstance.created_at.asc(), ProcessInstance.id.asc())
            .first()
            .status
            == "rejected"
        )
        assert db.get(Requirement, on_hold_id).status == "on_hold"
