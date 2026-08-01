"""Authenticated owner-only endpoints for web assistant conversations and actions."""

import asyncio
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.assistant.orchestrator import AssistantOrchestrator, SSE_EVENT_TYPES
from app.db import get_db
from app.deps import get_current_user
from app.models import AuthUser
from app.schemas.assistant import ConversationCreateIn, PageContextIn
from app.schemas.common import ok
from app.services import assistant_actions, assistant_conversations


router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class ConfirmActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    confirmation_token: str = Field(min_length=1, max_length=512)


class ConversationMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=8000)
    client_message_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    page_context: PageContextIn | None = None


def _encode_sse(event: dict) -> str:
    event_type = event.get("type")
    if event_type not in SSE_EVENT_TYPES or not isinstance(event.get("data"), dict):
        raise RuntimeError("invalid assistant SSE event")
    payload = json.dumps(
        jsonable_encoder(event["data"]),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: {event_type}\ndata: {payload}\n\n"


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
    page: int = Query(default=1, ge=1, le=10_000),
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


@router.post("/conversations/{conversation_id}/messages")
async def stream_conversation_message(
    conversation_id: str,
    body: ConversationMessageIn,
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    actor_id = user.id
    # Authentication has already produced a scalar identity.  End the request
    # dependency transaction before returning a long-lived StreamingResponse;
    # the orchestrator opens only dedicated short sessions thereafter.
    await asyncio.to_thread(db.rollback)

    async def generate():
        orchestrator = AssistantOrchestrator(
            actor_id=actor_id,
            disconnect_check=request.is_disconnected,
        )
        async for event in orchestrator.stream_turn(
            conversation_id=conversation_id,
            content=body.content,
            client_message_id=body.client_message_id,
            page_context=body.page_context.model_dump(mode="json") if body.page_context else None,
        ):
            yield _encode_sse(event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store, private",
            "Vary": "Authorization",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/actions/{action_id}/confirm")
def confirm_action(
    action_id: str,
    body: ConfirmActionIn,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return ok(assistant_actions.confirm_action(db, user, action_id, body.confirmation_token))


@router.post("/actions/{action_id}/cancel")
def cancel_action(
    action_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return ok(assistant_actions.cancel_action(db, user, action_id))
