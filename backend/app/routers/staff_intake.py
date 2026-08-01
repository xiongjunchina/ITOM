"""IT 员工网页单据分流与速查接口。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import get_current_user
from app.models import AuthUser
from app.schemas.common import ok
from app.services import it_document_guide


router = APIRouter(tags=["staff-intake"])


class RecommendationIn(BaseModel):
    broad_impact: bool = False
    recurring_or_root_cause: bool = False
    planned_production_change: bool = False
    new_capability: bool = False


@router.get("/api/it-document-guide")
def get_document_guide(db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    """返回六类单据的静态速查内容及当前用户可用入口。"""
    return ok(it_document_guide.guide_payload(db, user))


@router.post("/api/staff-intake/recommend")
def recommend_document_type(
    body: RecommendationIn,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """依据临时判断项给出推荐；问答不落库。"""
    available = it_document_guide.available_types(db, user)
    if not it_document_guide.staff_intake_enabled(db, user, available):
        raise AppError("IT_STAFF_ONLY", "仅数字化团队成员或系统管理员可使用创建单据指引", 403)

    result = it_document_guide.recommend(**body.model_dump())
    if result["recommended_type"] not in available:
        result["target_path"] = None
        result["permission_notice"] = "当前账号没有该单据的创建权限，请联系具备权限的 IT 同事处理。"
    return ok(result)
