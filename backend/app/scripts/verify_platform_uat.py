"""对已启动的本地后端执行平台运营 P0 成功/失败路径验收。"""

from __future__ import annotations

import argparse
import json
from datetime import date
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.security import create_token
from app.db import SessionLocal
from app.models import AuthUser
from app.services.seed_table_uat import assert_local_uat_database


LOCAL_API_HOSTS = {"localhost", "127.0.0.1", "::1"}


def assert_local_api_base(api_base: str) -> None:
    parsed = urlparse(api_base)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in LOCAL_API_HOSTS:
        raise RuntimeError("平台运营 UAT 只允许调用本地 API")


def next_quarter(day: date) -> str:
    quarter = ((day.month - 1) // 3) + 1
    return f"{day.year + (1 if quarter == 4 else 0)}-Q{1 if quarter == 4 else quarter + 1}"


def _expect(response: httpx.Response, status: int, code: str | None = None) -> dict:
    if response.status_code != status:
        raise RuntimeError(f"本地 UAT HTTP 状态异常：期望 {status}，实际 {response.status_code}")
    payload = response.json()
    if code and payload.get("error", {}).get("code") != code:
        raise RuntimeError(f"本地 UAT 错误码异常：期望 {code}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="验证本地平台运营 P0 API 成功与失败路径")
    parser.add_argument("--api-base", default="http://127.0.0.1:6800")
    parser.add_argument("--confirm-local", action="store_true")
    args = parser.parse_args()
    if not args.confirm_local:
        parser.error("必须显式传入 --confirm-local")
    assert_local_uat_database(settings.database_url)
    assert_local_api_base(args.api_base)

    with SessionLocal() as db:
        admin = db.query(AuthUser).filter(
            AuthUser.username == "admin",
            AuthUser.is_active.is_(True),
            AuthUser.is_deleted.is_(False),
        ).one()
        token = create_token(admin.id)

    headers = {"Authorization": f"Bearer {token}"}
    plan_key = "platform-uat-runtime-plan-v1"
    commitment_key = "platform-uat-runtime-commitment-v1"
    with httpx.Client(base_url=args.api_base, headers=headers, timeout=10, trust_env=False) as client:
        _expect(client.get("/api/health"), 200)
        service_payload = _expect(client.get("/api/platform/services", params={"page_size": 200}), 200)
        demand_payload = _expect(client.get("/api/platform/demands", params={"page_size": 200}), 200)
        services = service_payload["data"]
        demands = demand_payload["data"]
        service = next((row for row in services if row["item_code"] == "SI-UAT-TABLE"), None)
        if service is None or not demands:
            raise RuntimeError("本地平台运营合成数据未就绪")

        body = {
            "service_item_id": service["service_item_id"],
            "period": next_quarter(date.today()),
            "gross_days": "20.00",
            "planned_unavailable_days": "1.00",
            "bau_reserve_days": "2.00",
            "risk_buffer_days": "1.00",
            "notes": "【平台运营UAT】运行时 API 验收计划",
        }
        create_headers = {**headers, "Idempotency-Key": plan_key}
        created = _expect(client.post("/api/platform/capacity-plans", headers=create_headers, json=body), 200)["data"]
        replayed = _expect(client.post("/api/platform/capacity-plans", headers=create_headers, json=body), 200)["data"]
        if created["id"] != replayed["id"]:
            raise RuntimeError("本地容量计划幂等重放返回了不同记录")

        plan_id = created["id"]
        if created["status"] == "draft":
            commitment = {
                "subject_type": "roadmap",
                "title": "【平台运营UAT】下一季度平台路线图",
                "commitment_type": "roadmap",
                "capacity_days": "6.00",
                "lifecycle_stage": "build",
                "investment_intent": "grow",
                "status": "planned",
            }
            _expect(client.post(
                f"/api/platform/capacity-plans/{plan_id}/commitments",
                headers={**headers, "Idempotency-Key": commitment_key},
                json=commitment,
            ), 200)
            created = _expect(client.post(f"/api/platform/capacity-plans/{plan_id}/submit"), 200)["data"]
        if created["status"] != "review":
            raise RuntimeError("本地容量计划未停留在待业务审批状态")

        approval = client.post(
            f"/api/platform/capacity-plans/{plan_id}/approve",
            json={"reason": "验证管理员不能替代业务审批人"},
        )
        _expect(approval, 403, "CAPACITY_APPROVAL_FORBIDDEN")
        locked = client.patch(f"/api/platform/capacity-plans/{plan_id}", json={"notes": "不应改写"})
        _expect(locked, 409, "CAPACITY_PLAN_LOCKED")

    print(json.dumps({
        "health": "passed",
        "services": service_payload.get("total", len(services)),
        "demands": demand_payload.get("total", len(demands)),
        "plan_create": "passed",
        "idempotency_replay": "passed",
        "admin_approval_denied": "passed",
        "review_lock": "passed",
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
