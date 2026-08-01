"""Request-time discovery policy for fixed assistant capabilities."""
from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.assistant.registry import CapabilityRegistry, registry as default_registry
from app.assistant.types import AssistantChannel, CapabilityContext, CapabilityDefinition, RiskLevel
from app.core.rbac import ADMIN, AUDITOR, BDO, REQUESTER, TEAM_ROLES
from app.models import AiAgentProfile, AiAgentProfileVersion, AuthUser
from app.services.permissions import has_perm, user_permissions
from app.services.rbac import effective_roles


def _audience_for_roles(roles: set[str]) -> str | None:
    if ADMIN in roles:
        return "admin"
    if roles.intersection(TEAM_ROLES):
        return "it"
    if BDO in roles:
        return "bdo"
    if roles and roles.issubset({AUDITOR}):
        return "auditor"
    if REQUESTER in roles:
        return "requester"
    return None


def _minimum_risk(*levels: RiskLevel) -> RiskLevel:
    return min(levels, key=lambda level: level.rank)


def _published_profile_policy(
    db: Session, audience: str, requested_max_risk: RiskLevel
) -> tuple[set[str], RiskLevel] | None:
    """Return only the currently published, enabled profile restrictions.

    Multiple active profiles for one audience are combined conservatively.  A
    missing/incomplete profile fails closed because the WA0 assistant is
    disabled until governance has published it.
    """
    profiles = (
        db.query(AiAgentProfile)
        .filter(
            AiAgentProfile.audience == audience,
            AiAgentProfile.enabled.is_(True),
            AiAgentProfile.status == "published",
            AiAgentProfile.is_deleted.is_(False),
        )
        .all()
    )
    if not profiles:
        return None

    permitted_codes: set[str] | None = None
    limits = [requested_max_risk]
    for profile in profiles:
        version = (
            db.query(AiAgentProfileVersion)
            .filter(
                AiAgentProfileVersion.profile_id == profile.id,
                AiAgentProfileVersion.status == "published",
                AiAgentProfileVersion.is_deleted.is_(False),
            )
            .order_by(AiAgentProfileVersion.version.desc())
            .first()
        )
        if version is None or not isinstance(version.enabled_capabilities, list):
            return None
        codes = {code for code in version.enabled_capabilities if isinstance(code, str)}
        permitted_codes = codes if permitted_codes is None else permitted_codes.intersection(codes)
        try:
            limits.extend((RiskLevel.coerce(profile.max_risk_level), RiskLevel.coerce(version.max_risk_level)))
        except ValueError:
            return None
    return permitted_codes or set(), _minimum_risk(*limits)


def capability_context_for_user(
    db: Session, user_id: str, channel: AssistantChannel | str, max_risk: RiskLevel | str
) -> CapabilityContext | None:
    """Reload account authority from the database; callers never supply roles."""
    user = db.get(AuthUser, user_id)
    if not user or not user.is_active or user.is_deleted:
        return None
    try:
        requested_max_risk = RiskLevel.coerce(max_risk)
        resolved_channel = AssistantChannel.coerce(channel)
    except ValueError:
        return None
    roles = effective_roles(db, user)
    audience = _audience_for_roles(roles)
    if audience is None:
        return None
    profile_policy = _published_profile_policy(db, audience, requested_max_risk)
    if profile_policy is None:
        return None
    _codes, profile_max_risk = profile_policy
    return CapabilityContext(
        channel=resolved_channel,
        audience=audience,
        effective_roles=frozenset(roles),
        permissions=user_permissions(db, user),
        max_risk=profile_max_risk,
    )


def capabilities_for_user(
    db: Session,
    user: AuthUser,
    *,
    channel: AssistantChannel | str,
    max_risk: RiskLevel | str,
    registry: CapabilityRegistry = default_registry,
) -> list[CapabilityDefinition]:
    """Discover a narrow model-visible set; execution must authorize again.

    This function deliberately has no caller-controlled role/audience input.
    Record visibility, current status, ownership, and workflow assignment are
    execution-time checks owned by each capability's domain-service handler.
    """
    user_id = getattr(user, "id", None)
    if not isinstance(user_id, str):
        return []
    context = capability_context_for_user(db, user_id, channel, max_risk)
    if context is None:
        return []
    profile_policy = _published_profile_policy(db, context.audience, context.max_risk)
    if profile_policy is None:
        return []
    enabled_codes, policy_max_risk = profile_policy
    active_user = db.get(AuthUser, user_id)
    if active_user is None:
        return []

    visible: list[CapabilityDefinition] = []
    for definition in registry.definitions():
        if (
            definition.code not in enabled_codes
            or definition.risk.rank > policy_max_risk.rank
            or context.channel not in definition.channels
            or context.audience not in definition.audiences
        ):
            continue
        if definition.module and definition.action and not has_perm(db, active_user, definition.module, definition.action):
            continue
        visible.append(definition)
    return visible
