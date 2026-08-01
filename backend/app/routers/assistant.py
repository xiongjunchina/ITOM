"""Authenticated owner-only endpoints for web assistant conversations."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import AuthUser
from app.schemas.assistant import ConversationCreateIn
from app.schemas.common import ok
from app.services import assistant_conversations


router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.get("/bootstrap")
def bootstrap(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return ok(assistant_conversations.bootstrap_payload(db, user))


@router.post("/conversations")
def create_conversation(
    body: ConversationCreateIn,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return ok(assistant_conversations.create_conversation(
        db, user, language=body.language, page_context=body.page_context.model_dump(mode="json"),
    ))


@router.get("/conversations")
def list_conversations(
    include_archived: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    rows, total = assistant_conversations.list_own_conversations(
        db, user, include_archived=include_archived, page=page, page_size=page_size,
    )
    return ok(rows, total=total, page=page)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return ok(assistant_conversations.get_own_conversation(db, user, conversation_id))


@router.post("/conversations/{conversation_id}/archive")
def archive_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return ok(assistant_conversations.archive_own_conversation(db, user, conversation_id))
