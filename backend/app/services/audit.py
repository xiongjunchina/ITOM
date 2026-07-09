from sqlalchemy.orm import Session

from app.models import AuditLog, AuthUser


def audit(
    db: Session,
    entity_type: str,
    entity_id: str,
    action: str,
    actor: AuthUser | None,
    summary: dict | None = None,
):
    db.add(
        AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor.id if actor else None,
            actor_name=(actor.person.name if actor and actor.person else (actor.username if actor else None)),
            summary=summary,
        )
    )
