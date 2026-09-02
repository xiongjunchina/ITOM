"""P0 DMC 与需求/项目治理适配：新五维口径、历史兼容和决策记录。"""
from decimal import Decimal

from app.services.requirement_scoring import (
    DEFAULT_WEIGHTS,
    LEGACY_DEFAULT_WEIGHTS,
    classify_project_scope,
    compute_weighted_total,
    decision_level_for_amount,
)


def test_new_five_dimension_score_and_business_maturity_weight():
    scores = {
        "d1_strategy": 5,
        "d2_value": 4,
        "d3_tech": 4,
        "d4_org": 3,
        "d5_risk": 2,
    }
    assert DEFAULT_WEIGHTS == {"d1": 0.2, "d2": 0.2, "d3": 0.2, "d4": 0.3, "d5": 0.1}
    assert compute_weighted_total(scores, DEFAULT_WEIGHTS) == 3.9


def test_legacy_six_dimension_score_is_still_reproducible():
    scores = {
        "d1_strategy": 5,
        "d2_value": 4,
        "d3_tech": 4,
        "d4_org": 3,
        "d5_risk": 2,
        "d6_speed": 4,
    }
    assert compute_weighted_total(scores, LEGACY_DEFAULT_WEIGHTS) == 4.1


def test_decision_level_thresholds_are_inclusive_at_300k():
    assert decision_level_for_amount(None) is None
    assert decision_level_for_amount(Decimal("299999.99")) == "digital_leader"
    assert decision_level_for_amount(Decimal("300000")) == "eason"
    assert decision_level_for_amount(Decimal("1000000")) == "eason"
    assert decision_level_for_amount(Decimal("1000000.01")) == "dmc"


def test_project_classification_returns_reasons_without_changing_route_state():
    result = classify_project_scope(
        solution_type="二次开发", dev_effort=24, external_service_required=True, owner_assigned=True,
    )
    assert result["is_project"] is True
    assert result["route"] == "转项目管理"
    assert result["owner_ready"] is True
    assert "开发人天达到项目阈值" in result["reasons"]


def test_dmc_decision_record_can_be_recorded_and_listed(client, admin_headers):
    member = client.post("/api/members", json={"name": "P0治理记录负责人"}, headers=admin_headers)
    assert member.status_code == 200, member.text
    domain = client.post(
        "/api/admin/business-domains",
        json={"code": "p0govp0", "name": "P0治理业务域P0", "owner_id": None},
        headers=admin_headers,
    ).json()["data"]
    requirement = client.post(
        "/api/requirements",
        json={
            "title": "P0治理记录需求",
            "req_type": "功能",
            "business_domain_id": domain["id"],
            "description": "记录线下 DMC 结果",
        },
        headers=admin_headers,
    ).json()["data"]
    response = client.post(
        "/api/governance/dmc-decisions",
        json={
            "entity_type": "requirement",
            "entity_id": requirement["id"],
            "decision": "conditional",
            "amount_cny": "300000",
            "conditions": "补充实施范围和预算拆分",
            "owner_id": member.json()["data"]["id"],
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["decision_level"] == "eason"
    listed = client.get(
        "/api/governance/dmc-decisions",
        params={"entity_type": "requirement", "entity_id": requirement["id"]},
        headers=admin_headers,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"][0]["conditions"] == "补充实施范围和预算拆分"
