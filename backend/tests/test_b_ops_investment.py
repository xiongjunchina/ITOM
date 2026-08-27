"""B-OPS：需求、建设、运维统一投入台账及报表口径。"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.db import SessionLocal
from app.models import (
    AuditLog,
    CostEntry,
    Contract,
    InvestmentBudgetItem,
    InvestmentCostEntry,
    InvestmentWorklog,
    ProjectBudgetItem,
    ProjectEffortEntry,
    ServiceCatalog,
    ServiceItem,
    Ticket,
    Vendor,
)
from app.services.migrate import backfill_unified_investments


TODAY = date.today()


def _member(client, headers, name: str) -> str:
    response = client.post("/api/members", headers=headers, json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


def _service(prefix: str, *, resolved: bool = False) -> tuple[str, str]:
    with SessionLocal() as db:
        catalog = ServiceCatalog(code=f"CAT-{prefix}", name=f"{prefix} 运维目录")
        db.add(catalog)
        db.flush()
        item = ServiceItem(
            item_code=f"SI-{prefix}", name=f"{prefix} 运维服务", catalog_id=catalog.id,
            service_type="operations", target_audience_mode="all", status="上架",
        )
        db.add(item)
        db.flush()
        ticket = Ticket(
            ticket_code=f"TK-{prefix}", title=f"{prefix} 运维工单",
            ticket_type="incident", priority="P2", description="B-OPS 自动化验证",
            service_item_id=item.id, status="resolved" if resolved else "processing",
            submitted_at=datetime.now() - timedelta(hours=4),
            resolved_at=datetime.now() if resolved else None,
            actual_resolution_hours=4 if resolved else None,
        )
        db.add(ticket)
        db.commit()
        return item.id, ticket.id


def test_operations_rollup_report_and_contract_amount_is_not_actual_cost(client, admin_headers):
    person_id = _member(client, admin_headers, "B-OPS 运维工程师")
    service_id, ticket_id = _service("BOPS-ROLLUP", resolved=True)
    with SessionLocal() as db:
        vendor = Vendor(code="VD-BOPS-ROLLUP", name="B-OPS 合同供应商")
        db.add(vendor)
        db.flush()
        contract = Contract(
            code="CT-BOPS-ROLLUP", name="仅作合同额验证", vendor_id=vendor.id,
            amount_10k=88, start_date=TODAY - timedelta(days=30),
            end_date=TODAY + timedelta(days=365),
        )
        db.add(contract)
        db.commit()
        contract_id = contract.id

    contract_summary = client.get(
        "/api/investments/summary", headers=admin_headers,
        params={"subject_type": "contract", "subject_id": contract_id},
    )
    assert contract_summary.status_code == 200, contract_summary.text
    assert contract_summary.json()["data"]["incurred_cost_cny"] == "0.00"

    cost = client.post("/api/investments/costs", headers=admin_headers, json={
        "subject_type": "ticket", "subject_id": ticket_id,
        "recognition_date": str(TODAY), "amount_cny": "1200.00",
        "cost_status": "incurred", "category": "hardware", "cost_nature": "opex",
        "activity_type": "incident_response",
    })
    assert cost.status_code == 200, cost.text
    worklog = client.post("/api/investments/worklogs", headers=admin_headers, json={
        "subject_type": "ticket", "subject_id": ticket_id, "person_id": person_id,
        "work_date": str(TODAY), "effort_days": "0.50", "role_type": "operations",
        "activity_type": "incident_response", "standard_rate_cny_per_day": "1000.00",
    })
    assert worklog.status_code == 200, worklog.text

    service_summary = client.get(
        "/api/investments/summary", headers=admin_headers,
        params={"subject_type": "service_item", "subject_id": service_id},
    )
    assert service_summary.status_code == 200, service_summary.text
    values = service_summary.json()["data"]
    assert values["incurred_cost_cny"] == "1200.00"
    assert values["effort_days"] == "0.50"
    assert values["effort_cost_cny"] == "500.00"
    assert values["management_total_cny"] == "1700.00"

    metrics = client.post("/api/reports/query", headers=admin_headers, json={
        "metric_codes": [
            "operations.incurred_cost_cny", "operations.effort_days",
            "operations.ticket_worklog_coverage", "operations.cost_per_resolved_ticket",
        ],
        "period_start": str(TODAY - timedelta(days=1)), "period_end": str(TODAY),
        "filters": {"service_item_id": service_id},
    })
    assert metrics.status_code == 200, metrics.text
    metric_values = {row["code"]: row["value"] for row in metrics.json()["data"]["metrics"]}
    assert metric_values == {
        "operations.incurred_cost_cny": "1200.00",
        "operations.effort_days": "0.50",
        "operations.ticket_worklog_coverage": 100.0,
        "operations.cost_per_resolved_ticket": "1200.00",
    }


def test_shared_operations_allocation_is_weighted_and_capped(client, admin_headers):
    service_a, _ = _service("BOPS-ALLOC-A")
    service_b, _ = _service("BOPS-ALLOC-B")
    source = client.post("/api/investments/costs", headers=admin_headers, json={
        "subject_type": "shared_operations", "recognition_date": str(TODAY),
        "amount_cny": "1000.00", "cost_status": "incurred", "category": "cloud",
        "cost_nature": "opex", "recurrence": "recurring", "activity_type": "monitoring",
    })
    assert source.status_code == 200, source.text
    source_id = source.json()["data"]["id"]
    allocated = client.post("/api/investments/allocations", headers=admin_headers, json={
        "source_kind": "cost", "source_id": source_id,
        "target_type": "service_item", "target_id": service_a, "percentage": "60.00",
    })
    assert allocated.status_code == 200, allocated.text
    exceeds = client.post("/api/investments/allocations", headers=admin_headers, json={
        "source_kind": "cost", "source_id": source_id,
        "target_type": "service_item", "target_id": service_b, "percentage": "50.00",
    })
    assert exceeds.status_code == 409, exceeds.text
    assert exceeds.json()["error"]["code"] == "INVESTMENT_ALLOCATION_EXCEEDS_100"
    summary = client.get(
        "/api/investments/summary", headers=admin_headers,
        params={"subject_type": "service_item", "subject_id": service_a},
    )
    assert summary.json()["data"]["incurred_cost_cny"] == "600.00"


def test_unclassified_labor_blocks_management_total_and_actual_dates_are_guarded(client, admin_headers):
    person_id = _member(client, admin_headers, "B-OPS 数据质量验证人员")
    service_id, _ = _service("BOPS-QUALITY")
    labor = client.post("/api/investments/costs", headers=admin_headers, json={
        "subject_type": "service_item", "subject_id": service_id,
        "recognition_date": str(TODAY), "amount_cny": "300.00",
        "cost_status": "paid", "category": "labor", "cost_nature": "opex",
        "labor_nature": "unclassified", "activity_type": "operations_management",
    })
    assert labor.status_code == 200, labor.text
    worklog = client.post("/api/investments/worklogs", headers=admin_headers, json={
        "subject_type": "service_item", "subject_id": service_id, "person_id": person_id,
        "work_date": str(TODAY), "effort_days": "1.00", "role_type": "operations",
        "activity_type": "operations_management", "standard_rate_cny_per_day": "800.00",
    })
    assert worklog.status_code == 200, worklog.text
    summary = client.get(
        "/api/investments/summary", headers=admin_headers,
        params={"subject_type": "service_item", "subject_id": service_id},
    ).json()["data"]
    assert summary["paid_cost_cny"] == "300.00"
    assert summary["incurred_cost_cny"] == "300.00"
    assert summary["unclassified_labor_cny"] == "300.00"
    assert summary["management_total_cny"] is None
    assert summary["quality"]["management_total_available"] is False

    future_cost = client.post("/api/investments/costs", headers=admin_headers, json={
        "subject_type": "service_item", "subject_id": service_id,
        "recognition_date": str(TODAY + timedelta(days=1)), "amount_cny": "1.00",
        "cost_status": "incurred", "category": "other",
    })
    assert future_cost.status_code == 422
    future_worklog = client.post("/api/investments/worklogs", headers=admin_headers, json={
        "subject_type": "service_item", "subject_id": service_id, "person_id": person_id,
        "work_date": str(TODAY + timedelta(days=1)), "effort_days": "0.25",
        "role_type": "operations", "activity_type": "monitoring",
    })
    assert future_worklog.status_code == 422
    daily_limit = client.post("/api/investments/worklogs", headers=admin_headers, json={
        "subject_type": "service_item", "subject_id": service_id, "person_id": person_id,
        "work_date": str(TODAY), "effort_days": "1.25",
        "role_type": "operations", "activity_type": "monitoring",
    })
    assert daily_limit.status_code == 409
    assert daily_limit.json()["error"]["code"] == "INVESTMENT_WORKLOG_DAILY_LIMIT"

    with SessionLocal() as db:
        actions = {
            (row.entity_type, row.action)
            for row in db.query(AuditLog).filter(
                AuditLog.entity_type.in_(("investment_cost_entry", "investment_worklog"))
            )
        }
    assert ("investment_cost_entry", "create") in actions
    assert ("investment_worklog", "create") in actions


def test_legacy_project_investment_backfill_is_idempotent(client, admin_headers):
    person_id = _member(client, admin_headers, "B-OPS 迁移验证人员")
    project_response = client.post("/api/projects", headers=admin_headers, json={
        "name": "B-OPS 旧投入迁移项目", "pm": person_id,
        "planned_start": str(TODAY - timedelta(days=10)),
        "planned_end": str(TODAY + timedelta(days=20)),
    })
    assert project_response.status_code == 200, project_response.text
    project_id = project_response.json()["data"]["id"]
    with SessionLocal() as db:
        legacy_budget = ProjectBudgetItem(
            project_id=project_id, category="software", name="旧软件预算",
            amount_cny=Decimal("2000.00"),
        )
        legacy_cost = CostEntry(
            project_id=project_id, entry_date=TODAY, amount_10k=0.05,
            amount_cny=Decimal("500.00"), category="software", cost_type="incurred",
        )
        legacy_effort = ProjectEffortEntry(
            project_id=project_id, person_id=person_id, work_date=TODAY,
            effort_days=Decimal("0.50"), role_type="implementation",
            standard_rate_cny_per_day=Decimal("1000.00"),
        )
        db.add_all([legacy_budget, legacy_cost, legacy_effort])
        db.flush()
        source_ids = (legacy_budget.id, legacy_cost.id, legacy_effort.id)
        backfill_unified_investments(db)
        backfill_unified_investments(db)
        db.commit()
        assert db.query(InvestmentBudgetItem).filter(
            InvestmentBudgetItem.source_type == "legacy_project_budget_item",
            InvestmentBudgetItem.source_id == source_ids[0],
        ).count() == 1
        assert db.query(InvestmentCostEntry).filter(
            InvestmentCostEntry.source_type == "legacy_project_cost",
            InvestmentCostEntry.source_id == source_ids[1],
        ).count() == 1
        assert db.query(InvestmentWorklog).filter(
            InvestmentWorklog.source_type == "legacy_project_effort",
            InvestmentWorklog.source_id == source_ids[2],
        ).count() == 1
