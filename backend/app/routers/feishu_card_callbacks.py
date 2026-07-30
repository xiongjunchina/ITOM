"""飞书新版交互卡片公开回调入口。"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.services.aily import get_aily_config
from app.services.feishu_card_callbacks import (
    handle_card_action,
    verify_and_decode_callback,
)


logger = logging.getLogger("aom.feishu_card_callbacks")
router = APIRouter(prefix="/api/integrations/feishu", tags=["feishu-card-callbacks"])


def _error_toast(exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={"toast": {"type": "error", "content": exc.message}},
    )


@router.post("/card-actions")
async def card_actions(request: Request, db: Session = Depends(get_db)):
    """验签后处理 card.action.trigger；业务错误以 Toast 返回并保留原卡片。"""
    raw_body = await request.body()
    config = get_aily_config(db)
    payload = verify_and_decode_callback(
        raw_body=raw_body,
        timestamp=request.headers.get("x-lark-request-timestamp"),
        nonce=request.headers.get("x-lark-request-nonce"),
        signature=request.headers.get("x-lark-signature"),
        config=config,
    )

    if payload.get("type") == "url_verification":
        challenge = str(payload.get("challenge") or "")
        if not challenge:
            raise AppError("FEISHU_CARD_CHALLENGE_INVALID", "飞书回调校验缺少 challenge", 400)
        return {"challenge": challenge}

    try:
        response = handle_card_action(db, payload, config)
        db.commit()
        return response
    except AppError as exc:
        db.rollback()
        return _error_toast(exc)
    except Exception as exc:
        db.rollback()
        logger.error("Feishu card callback failed (%s)", exc.__class__.__name__)
        return JSONResponse(
            status_code=200,
            content={
                "toast": {
                    "type": "error",
                    "content": "ITOM 处理失败，请稍后重试",
                }
            },
        )
