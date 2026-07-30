"""飞书新版交互卡片回调的验签、解密、身份映射与领域动作编排。"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AilyIntegrationConfig, AuthUser, ExternalIdentity
from app.services import service_request_closure
from app.services.aily_cards import (
    build_action_result_card,
    build_reopen_feedback_card,
)
from app.services.mcp_intents import validate_idempotency_key
from app.services.permissions import has_perm
from app.services.secrets_store import decrypt_secret


MAX_CALLBACK_BODY_BYTES = 64 * 1024
MAX_SIGNATURE_AGE_SECONDS = 300
_GO_TIMESTAMP_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d{1,9}))? (?P<offset>[+-]\d{4})"
    r"(?: \S+)?$"
)


def _raw_card_update(card: dict) -> dict:
    """按新版 card.action.trigger 契约包装立即更新的原始卡片。"""
    return {"type": "raw", "data": card}


def _secure_equal(left: str, right: str) -> bool:
    """对可能包含非 ASCII 字符的飞书字段做稳定的字节比较。"""
    return hmac.compare_digest(str(left).encode("utf-8"), str(right).encode("utf-8"))


def _secret(value: str | None, code: str, message: str) -> str:
    plaintext = decrypt_secret(value)
    if not plaintext:
        raise AppError(code, message, 503)
    return plaintext


def _parse_callback_timestamp(value: str) -> int:
    """解析 Unix 秒/毫秒及真实 Aily 回调出现的 Go 时间字符串。"""
    raw = str(value or "").strip()
    try:
        timestamp = int(raw)
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        return timestamp
    except ValueError:
        pass

    # 实际公网联调中，Feishu/Aily 回调曾发送类似：
    # 2026-07-30 14:55:43.067598676 +0800 CST m=+72889.432249819
    # 签名计算仍使用原始 header 字符串；这里只将墙上时钟部分转换为 epoch
    # 做时效校验，并忽略 Go 的单调时钟后缀。
    normalized = raw.split(" m=", 1)[0]
    match = _GO_TIMESTAMP_RE.fullmatch(normalized)
    if match:
        fraction = (match.group("fraction") or "")[:6].ljust(6, "0")
        parsed = datetime.strptime(
            f"{match.group('date')}.{fraction} {match.group('offset')}",
            "%Y-%m-%d %H:%M:%S.%f %z",
        )
        return int(parsed.timestamp())
    raise ValueError("unsupported callback timestamp")


def _decrypt_callback(ciphertext: str, encrypt_key: str) -> dict:
    """按飞书官方 SDK 的 AES-256-CBC + PKCS#7 规则解密回调。"""
    try:
        encrypted = base64.b64decode(ciphertext, validate=True)
        if len(encrypted) < 32 or len(encrypted) % 16:
            raise ValueError("invalid ciphertext length")
        digest = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
        decryptor = Cipher(
            algorithms.AES(digest),
            modes.CBC(encrypted[:16]),
        ).decryptor()
        padded = decryptor.update(encrypted[16:]) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
        payload = json.loads(plaintext.decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError("FEISHU_CARD_CALLBACK_DECRYPT_FAILED", "飞书卡片回调解密失败", 400) from exc
    if not isinstance(payload, dict):
        raise AppError("FEISHU_CARD_CALLBACK_INVALID", "飞书卡片回调格式无效", 400)
    return payload


def _decode_envelope(raw_body: bytes, encrypt_key: str) -> dict:
    try:
        envelope = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError("FEISHU_CARD_CALLBACK_INVALID", "飞书卡片回调 JSON 无效", 400) from exc
    if not isinstance(envelope, dict):
        raise AppError("FEISHU_CARD_CALLBACK_INVALID", "飞书卡片回调格式无效", 400)
    return (
        _decrypt_callback(str(envelope["encrypt"]), encrypt_key)
        if envelope.get("encrypt")
        else envelope
    )


def verify_and_decode_callback(
    *,
    raw_body: bytes,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
    config: AilyIntegrationConfig,
) -> dict:
    """验证原始请求签名、时效和 Verification Token，并返回明文载荷。"""
    if not config.enabled:
        raise AppError("AILY_MCP_DISABLED", "Aily MCP 尚未启用", 503)
    if not raw_body or len(raw_body) > MAX_CALLBACK_BODY_BYTES:
        raise AppError("FEISHU_CARD_CALLBACK_INVALID", "飞书卡片回调正文无效", 400)

    verification_token = _secret(
        config.card_callback_verification_token_encrypted,
        "FEISHU_CARD_CALLBACK_NOT_CONFIGURED",
        "飞书卡片回调 Verification Token 未配置",
    )
    encrypt_key = _secret(
        config.card_callback_encrypt_key_encrypted,
        "FEISHU_CARD_CALLBACK_NOT_CONFIGURED",
        "飞书卡片回调 Encrypt Key 未配置",
    )
    signature_headers = (timestamp, nonce, signature)
    if not all(signature_headers):
        # 飞书保存 Webhook 地址时会发送仅含 encrypt 的 URL challenge，实测该
        # 验证请求没有 X-Lark-* 签名头。这个只读握手仍必须成功解密并通过
        # Verification Token；任何业务回调或仅缺部分签名头的请求继续拒绝。
        if any(signature_headers):
            raise AppError("FEISHU_CARD_SIGNATURE_MISSING", "飞书卡片回调缺少签名头", 401)
        payload = _decode_envelope(raw_body, encrypt_key)
        if payload.get("type") != "url_verification":
            raise AppError("FEISHU_CARD_SIGNATURE_MISSING", "飞书卡片回调缺少签名头", 401)
        header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
        received_token = str(header.get("token") or payload.get("token") or "")
        if not received_token or not _secure_equal(verification_token, received_token):
            raise AppError("FEISHU_CARD_TOKEN_INVALID", "飞书卡片回调 Token 无效", 401)
        return payload
    try:
        request_time = _parse_callback_timestamp(str(timestamp))
    except (TypeError, ValueError) as exc:
        raise AppError("FEISHU_CARD_SIGNATURE_INVALID", "飞书卡片回调签名时间无效", 401) from exc
    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - request_time) > MAX_SIGNATURE_AGE_SECONDS:
        raise AppError("FEISHU_CARD_SIGNATURE_EXPIRED", "飞书卡片回调签名已过期", 401)

    expected = hashlib.sha256(
        timestamp.encode("utf-8")
        + nonce.encode("utf-8")
        + encrypt_key.encode("utf-8")
        + raw_body
    ).hexdigest()
    if not _secure_equal(expected, signature):
        raise AppError("FEISHU_CARD_SIGNATURE_INVALID", "飞书卡片回调签名无效", 401)

    payload = _decode_envelope(raw_body, encrypt_key)
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    received_token = str(header.get("token") or payload.get("token") or "")
    if not received_token or not _secure_equal(verification_token, received_token):
        raise AppError("FEISHU_CARD_TOKEN_INVALID", "飞书卡片回调 Token 无效", 401)
    return payload


def _allowed(value: str, candidates: list[str]) -> bool:
    return any(_secure_equal(value, str(candidate)) for candidate in candidates)


def _record_pending_operator(
    db: Session,
    *,
    tenant_id: str,
    app_id: str,
    subject_type: str,
    subject_id: str,
) -> None:
    row = (
        db.query(ExternalIdentity)
        .filter(
            ExternalIdentity.provider == "feishu",
            ExternalIdentity.tenant_id == tenant_id,
            ExternalIdentity.app_id == app_id,
            ExternalIdentity.subject_type == subject_type,
            ExternalIdentity.subject_id == subject_id,
        )
        .first()
    )
    if not row:
        row = ExternalIdentity(
            provider="feishu",
            tenant_id=tenant_id,
            app_id=app_id,
            subject_type=subject_type,
            subject_id=subject_id,
            auth_user_id=None,
            status="pending",
            verified_at=datetime.now(),
        )
        db.add(row)
    elif row.is_deleted or row.status == "pending":
        row.is_deleted = False
        row.auth_user_id = None
        row.status = "pending"
        row.verified_at = datetime.now()
    db.commit()


def _resolve_operator(
    db: Session,
    payload: dict,
    config: AilyIntegrationConfig,
) -> AuthUser:
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    operator = event.get("operator") if isinstance(event.get("operator"), dict) else {}
    event_type = str(header.get("event_type") or "")
    if event_type != "card.action.trigger":
        raise AppError("FEISHU_CARD_EVENT_UNSUPPORTED", "仅接受新版飞书卡片交互回调", 400)

    app_id = str(header.get("app_id") or "").strip()
    if not config.bot_app_id or not _secure_equal(app_id, config.bot_app_id):
        raise AppError("FEISHU_CARD_APP_FORBIDDEN", "卡片回调应用与机器人配置不一致", 403)
    tenant_id = str(header.get("tenant_key") or operator.get("tenant_key") or "").strip()
    operator_tenant = str(operator.get("tenant_key") or tenant_id).strip()
    if not tenant_id or not _secure_equal(tenant_id, operator_tenant):
        raise AppError("FEISHU_CARD_TENANT_INVALID", "卡片回调租户不一致", 403)

    # Aily JWT 的 tenant_id 与飞书 card.action.trigger 的 tenant_key 在真实
    # 联调中属于不同标识命名空间，不能要求字符串相等。回调 tenant_key 若
    # 未直接出现在 Aily 白名单中，必须由同一已验签 Bot App 下的点击人标识
    # 唯一锚定到“已授权 Aily 租户 + 已授权 Agent/Bot App”的活动身份映射；
    # 未映射用户或白名单为空时仍拒绝，不把签名通过等同于业务授权。
    allowed_tenants = list(config.allowed_tenant_ids or [])
    callback_tenant_directly_allowed = _allowed(tenant_id, allowed_tenants)
    allowed_mapping_apps = list(config.allowed_agent_ids or []) + [app_id]
    found: list[tuple[ExternalIdentity, str, str]] = []
    for subject_type in ("open_id", "user_id", "union_id"):
        subject_id = str(operator.get(subject_type) or "").strip()
        if not subject_id:
            continue
        query = (
            db.query(ExternalIdentity)
            .filter(
                ExternalIdentity.provider == "feishu",
                ExternalIdentity.app_id.in_(allowed_mapping_apps),
                ExternalIdentity.subject_type == subject_type,
                ExternalIdentity.subject_id == subject_id,
                ExternalIdentity.status == "active",
                ExternalIdentity.is_deleted.is_(False),
            )
        )
        if callback_tenant_directly_allowed:
            query = query.filter(ExternalIdentity.tenant_id == tenant_id)
        else:
            query = query.filter(ExternalIdentity.tenant_id.in_(allowed_tenants))
        rows = query.all()
        found.extend((row, subject_type, subject_id) for row in rows)
    if not callback_tenant_directly_allowed and not found:
        raise AppError(
            "FEISHU_CARD_TENANT_FORBIDDEN",
            "卡片回调租户或点击人身份尚未获 ITOM 授权",
            403,
        )
    user_ids = {row.auth_user_id for row, _, _ in found if row.auth_user_id}
    if len(user_ids) > 1:
        raise AppError("FEISHU_CARD_IDENTITY_AMBIGUOUS", "卡片点击人存在冲突的 ITOM 身份映射", 403)
    if not found or not user_ids:
        pending_type = next(
            (kind for kind in ("open_id", "user_id", "union_id") if operator.get(kind)),
            "",
        )
        pending_id = str(operator.get(pending_type) or "").strip()
        if pending_type and pending_id:
            _record_pending_operator(
                db,
                tenant_id=tenant_id,
                app_id=app_id,
                subject_type=pending_type,
                subject_id=pending_id,
            )
        raise AppError("AILY_IDENTITY_UNMAPPED", "该飞书用户尚未映射到 ITOM 账号", 403)

    identity = found[0][0]
    user = db.get(AuthUser, next(iter(user_ids)))
    if not user or not user.is_active or user.is_deleted:
        raise AppError("AILY_ITOM_ACCOUNT_DISABLED", "映射的 ITOM 账号不存在或已停用", 403)
    if not has_perm(db, user, "ticket_sr", "view"):
        raise AppError("FORBIDDEN", "当前账号无服务请求操作权限", 403)
    identity.last_used_at = datetime.now()
    db.flush()
    return user


def _action_value(payload: dict) -> tuple[str, str, str, dict]:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    value = action.get("value") if isinstance(action.get("value"), dict) else {}
    operation = str(value.get("itom_action") or "").strip()
    ticket_code = str(value.get("ticket_code") or "").strip()
    idempotency_key = str(value.get("idempotency_key") or "").strip()
    if operation not in {"show_reopen_form", "reopen", "confirm_resolved", "rate"}:
        raise AppError("FEISHU_CARD_ACTION_UNSUPPORTED", "不支持的卡片操作", 422)
    if not ticket_code or len(ticket_code) > 64:
        raise AppError("FEISHU_CARD_ACTION_INVALID", "卡片缺少有效工单编号", 422)
    validate_idempotency_key(idempotency_key)
    return operation, ticket_code, idempotency_key, action


def handle_card_action(
    db: Session,
    payload: dict,
    config: AilyIntegrationConfig,
) -> dict:
    """以已验签的点击人身份执行卡片动作并生成飞书即时更新响应。"""
    user = _resolve_operator(db, payload, config)
    operation, ticket_code, idempotency_key, action = _action_value(payload)

    if operation == "show_reopen_form":
        ticket = service_request_closure.confirmation_target(db, user, ticket_code)
        card = build_reopen_feedback_card(
            ticket_code=ticket.ticket_code,
            title=ticket.title,
            solution=str(ticket.solution or "").strip()[:500],
            idempotency_key=idempotency_key,
        )
        return {
            "toast": {"type": "info", "content": "请补充未解决原因后提交"},
            "card": _raw_card_update(card),
        }

    if operation == "reopen":
        form_value = action.get("form_value") if isinstance(action.get("form_value"), dict) else {}
        feedback = str(form_value.get("feedback") or action.get("input_value") or "").strip()
        result, _ = service_request_closure.confirm_resolution(
            db,
            user,
            ticket_code,
            False,
            feedback,
            idempotency_key,
            source="feishu_card",
        )
        return {
            "toast": {"type": "success", "content": "服务请求已重新打开"},
            "card": _raw_card_update(
                build_action_result_card(
                    title="服务请求已重新打开",
                    template="orange",
                    content=f"**工单编号：** {result['ticket_code']}\n{result['message']}",
                )
            ),
        }

    if operation == "confirm_resolved":
        result, _ = service_request_closure.confirm_resolution(
            db,
            user,
            ticket_code,
            True,
            "",
            idempotency_key,
            source="feishu_card",
        )
        return {
            "toast": {"type": "success", "content": "服务请求已关闭"},
            "card": _raw_card_update(
                build_action_result_card(
                    title="服务请求已确认解决",
                    content=f"**工单编号：** {result['ticket_code']}\n{result['message']}",
                )
            ),
        }

    try:
        score = int((action.get("value") or {}).get("score"))
    except (TypeError, ValueError) as exc:
        raise AppError("FEISHU_CARD_SCORE_INVALID", "评价星级必须为 1-5", 422) from exc
    result, _ = service_request_closure.rate_request(
        db,
        user,
        ticket_code,
        score,
        None,
        "",
        idempotency_key,
        source="feishu_card",
    )
    return {
        "toast": {"type": "success", "content": f"已提交 {result['score']} 星评价"},
        "card": _raw_card_update(
            build_action_result_card(
                title="感谢您的评价",
                content=f"**工单编号：** {result['ticket_code']}\n**评价：** {result['score']} 星",
            )
        ),
    }
