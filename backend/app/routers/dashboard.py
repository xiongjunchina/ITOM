"""总览 Dashboard：单接口一次聚合（PRD §4）。

M1 返回零值结构；M2-M6 各域交付时在此填充真实聚合。
"""
from fastapi import APIRouter, Depends

from app.deps import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(_=Depends(get_current_user)):
    return {
        "success": True,
        "data": {
            "service": {"open_tickets": 0, "sla_rate": None, "change_success_rate": None, "problem_close_rate": None},
            "project": {
                "active": 0,
                "health": {"green": 0, "yellow": 0, "red": 0},
                "overdue_milestones": 0,
                "budget_usage": None,
            },
            "requirement": {
                "by_stage": {"registered": 0, "analyzing": 0, "implementing": 0, "closed": 0},
                "avg_lead_days": None,
            },
            "team": {"top_workload": [], "top_points": [], "trainings": 0, "hirings": 0},
            "alerts": [],
        },
    }
