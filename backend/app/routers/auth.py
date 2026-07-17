from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import create_token, hash_password, verify_password
from app.db import get_db
from app.deps import get_current_user
from app.models import AuthUser
from app.schemas.common import ok
from app.schemas.support import LoginIn

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_payload(db: Session, user: AuthUser) -> dict:
    from app.services.permissions import user_permissions
    from app.services.rbac import effective_roles

    return {
        "id": user.id,
        "username": user.username,
        "name": user.person.name if user.person else user.username,
        "roles": sorted(effective_roles(db, user)),  # 有效角色=直接∪组授予∪继承
        "direct_roles": user.roles or [],
        "permissions": user_permissions(db, user),  # {module:[actions]}，admin 为 {"*":[...]}；前端菜单/按钮以此渲染
        "auth_source": user.auth_source,
        "person_id": user.person_id,
        "language": (user.preferences or {}).get("language", "zh"),  # 显示语言：zh/en（登录即应用）
        "avatar": (user.preferences or {}).get("avatar"),  # 自设头像（data URL），顶栏展示
    }


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(AuthUser).filter(AuthUser.username == body.username, AuthUser.is_deleted.is_(False)).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise AppError("LOGIN_FAILED", "用户名或密码错误", 401)
    if not user.is_active:
        raise AppError("LOGIN_FAILED", "账号已禁用", 401)
    user.last_login_at = datetime.now()
    db.commit()
    return ok({"token": create_token(user.id), "user": _user_payload(db, user)})


@router.get("/me")
def me(user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok({**_user_payload(db, user), "preferences": user.preferences or {}})


class PreferencesIn(BaseModel):
    dashboard_widgets: list[str] | None = None
    team_overview_widgets: list[str] | None = None
    language: str | None = Field(default=None, pattern="^(zh|en)$")
    bio: str | None = Field(default=None, max_length=500)
    avatar: str | None = None  # data:image/... base64；显式传 null 表示移除


@router.patch("/me/preferences")
def update_preferences(body: PreferencesIn, user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """个人偏好（总览 widget 配置 / 语言 / 头像 / 个人说明等）：只更新提交的键。"""
    import re as _re

    if body.avatar:
        if not _re.match(r"^data:image/(png|jpe?g|webp|gif);base64,", body.avatar):
            raise AppError("BAD_AVATAR", "头像格式不支持，请上传图片")
        if len(body.avatar) > 400_000:  # 前端已压缩到 256px，此为兜底（约 300KB 图）
            raise AppError("BAD_AVATAR", "头像图片过大")
    prefs = dict(user.preferences or {})
    for k, v in body.model_dump(exclude_unset=True).items():
        prefs[k] = v
    user.preferences = prefs
    db.commit()
    return ok({"preferences": prefs})


@router.get("/me/profile")
def my_profile(user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """个人中心（M36.2）：账号信息 + 关联人员主数据（只读，组织同步维护）+ 个性化偏好。"""
    from app.models import Role
    from app.services.rbac import effective_roles

    roles = sorted(effective_roles(db, user))
    role_names = {r.code: r.name for r in db.query(Role).filter(Role.code.in_(roles)).all()} if roles else {}
    person = user.person
    prefs = user.preferences or {}
    return ok({
        "account": {
            "username": user.username,
            "auth_source": user.auth_source,
            "roles": roles,
            "role_names": role_names,
            "created_at": user.created_at,
            "last_login_at": user.last_login_at,
            "password_set": user.password_set_at is not None,
            "feishu_bound": bool(user.external_id),
        },
        "person": {
            "name": person.name,
            "employee_no": person.employee_no,
            "department_name": person.department.name if person.department else None,
            "position_name": person.position.name if person.position else None,
            "email": person.email,
            "mobile": person.mobile,
            "hire_date": person.hire_date,
            "external_source": person.external_source,
        } if person else None,
        "preferences": {
            "language": prefs.get("language", "zh"),
            "bio": prefs.get("bio"),
            "avatar": prefs.get("avatar"),
        },
    })


class ChangePasswordIn(BaseModel):
    current_password: str | None = None
    new_password: str = Field(min_length=8, max_length=64)


@router.post("/me/password")
def change_my_password(body: ChangePasswordIn, user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """修改本地登录密码（M36.2）。

    飞书开通的账号初始为随机口令（本人不知道），首次自设密码免验当前密码；
    一旦人为设定过（本人自设/管理员重置/本地创建），再改必须验当前密码。
    """
    import re as _re

    if not (_re.search(r"[A-Za-z]", body.new_password) and _re.search(r"\d", body.new_password)):
        raise AppError("WEAK_PASSWORD", "新密码至少 8 位，且需同时包含字母和数字")
    if user.password_set_at is not None:
        if not body.current_password or not verify_password(body.current_password, user.password_hash):
            raise AppError("PASSWORD_WRONG", "当前密码不正确")
    from app.services.audit import audit as _audit

    user.password_hash = hash_password(body.new_password)
    user.password_set_at = datetime.now()
    _audit(db, "auth_user", user.id, "change_password", user, {})
    db.commit()
    return ok({"password_set": True})


# ==================== 飞书扫码登录 + 管理员开通审批（M7） ====================
#
# 流程：员工飞书扫码 → 身份校验通过但不立即登录 → 落一条 LoginRequest（pending）
#      → 管理员在「用户与组管理」为其配置用户名/角色/默认语言并开通 → 员工过渡页轮询到
#      approved 后自动进入系统。飞书凭据就绪前，/feishu/scan 以传入身份模拟飞书 OAuth 回调；
#      通知当前走站内 + 发件箱（channel=in_app），发件箱即飞书推送的未来挂接点。

from fastapi import Header  # noqa: E402

from app.core.security import (  # noqa: E402
    create_pending_token,
    decode_pending_token,
    hash_password,
)
from app.deps import require_perm  # noqa: E402
from app.models import LoginRequest, OrgMember  # noqa: E402
from app.services.audit import audit  # noqa: E402


class FeishuScanIn(BaseModel):
    external_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    email: str | None = None
    mobile: str | None = None
    avatar_url: str | None = None


class ApproveIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    roles: list[str] = []
    language: str = Field(default="zh", pattern="^(zh|en)$")
    person_id: str | None = None
    note: str | None = None


class RejectIn(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


def _admin_person_ids(db: Session) -> list[str]:
    """有 admin_users.create 权限的管理员收件标识（M34：未绑定人员时用账号 id 兜底，
    确保 admin 初装未绑人员也能收到开通申请通知）。"""
    from app.services.permissions import has_perm

    ids = []
    for u in db.query(AuthUser).filter(AuthUser.is_deleted.is_(False), AuthUser.is_active.is_(True)):
        if has_perm(db, u, "admin_users", "create"):
            ids.append(u.person_id or u.id)
    return ids


def _notify(db: Session, event_type: str, req: LoginRequest, title: str, content: str, recipients: list[str], link: str):
    """站内通知 + 发件箱（飞书通道未来挂接点）。"""
    from app.events import notifier

    notifier.notify(db, event_type, "login_request", req.id, recipients, title, content, link)


def _handle_feishu_identity(db: Session, *, external_id: str, display_name: str,
                            email: str | None = None, mobile: str | None = None,
                            avatar_url: str | None = None) -> dict:
    """飞书身份 → 已开通直登 / 未开通落 LoginRequest 返回 pending 凭据（模拟与真实 OAuth 共用）。"""
    existing = (
        db.query(AuthUser)
        .filter(
            AuthUser.auth_source == "feishu",
            AuthUser.external_id == external_id,
            AuthUser.is_deleted.is_(False),
        )
        .first()
    )
    if existing:
        if not existing.is_active:
            raise AppError("LOGIN_FAILED", "账号已禁用，请联系管理员", 401)
        existing.last_login_at = datetime.now()
        db.commit()
        return {"status": "active", "token": create_token(existing.id), "user": _user_payload(db, existing)}

    req = (
        db.query(LoginRequest)
        .filter(
            LoginRequest.external_id == external_id,
            LoginRequest.status == "pending",
            LoginRequest.is_deleted.is_(False),
        )
        .first()
    )
    new_request = req is None
    if new_request:
        req = LoginRequest(
            external_source="feishu", external_id=external_id, display_name=display_name,
            email=email, mobile=mobile, avatar_url=avatar_url, status="pending",
        )
        db.add(req)
        db.flush()
    else:
        req.display_name = display_name  # 刷新展示名
        req.email = email or req.email
        req.mobile = mobile or req.mobile
        req.avatar_url = avatar_url or req.avatar_url
    if new_request:
        _notify(
            db, "onboarding.requested", req,
            title=f"新的登录开通请求：{req.display_name}",
            content=f"{req.display_name} 通过飞书扫码登录，等待开通系统账号。请前往「用户与组管理」处理。",
            recipients=_admin_person_ids(db), link="/admin/identity?tab=onboarding",
        )
    db.commit()
    return {
        "status": "pending", "request_id": req.id, "pending_token": create_pending_token(req.id),
        "display_name": req.display_name,
    }


@router.post("/feishu/scan")
def feishu_scan(body: FeishuScanIn, db: Session = Depends(get_db)):
    """模拟扫码入口（开发/演示用）：真实飞书启用后禁用，防止伪造身份。"""
    from app.services.feishu import is_enabled

    if is_enabled(db):
        raise AppError("SIMULATOR_DISABLED", "已启用真实飞书扫码，模拟入口关闭", 403)
    return ok(_handle_feishu_identity(
        db, external_id=body.external_id, display_name=body.display_name,
        email=body.email, mobile=body.mobile, avatar_url=body.avatar_url,
    ))


class FeishuCallbackIn(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    state: str = Field(min_length=1, max_length=512)


@router.get("/feishu/authorize-url")
def feishu_authorize_url(redirect_uri: str, db: Session = Depends(get_db)):
    """登录页取飞书扫码授权地址（公开）。未启用真实飞书 → 501，前端回退模拟入口。"""
    from app.services.feishu import build_client, get_config, is_enabled

    if not is_enabled(db):
        raise AppError("FEISHU_NOT_ENABLED", "飞书扫码未启用", 501)
    client = build_client(get_config(db))
    state = create_pending_token("oauth-state")  # 复用短时签名令牌做 anti-CSRF state
    db.commit()
    return ok({"url": client.authorize_url(redirect_uri, state)})


@router.post("/feishu/callback")
def feishu_callback(body: FeishuCallbackIn, db: Session = Depends(get_db)):
    """OAuth 回调（公开）：code 换飞书身份 → 直登或落开通请求。"""
    from app.services.feishu import build_client, get_config, is_enabled

    if not is_enabled(db):
        raise AppError("FEISHU_NOT_ENABLED", "飞书扫码未启用", 501)
    if decode_pending_token(body.state) != "oauth-state":
        raise AppError("INVALID_STATE", "登录会话校验失败，请重新扫码", 401)
    client = build_client(get_config(db))
    info = client.oauth_user_info(body.code)
    external_id = info.get("open_id") or info.get("union_id")
    if not external_id:
        raise AppError("FEISHU_ERROR", "飞书未返回用户标识", 502)
    return ok(_handle_feishu_identity(
        db, external_id=external_id,
        display_name=info.get("name") or info.get("en_name") or external_id,
        email=info.get("enterprise_email") or info.get("email"),
        mobile=info.get("mobile"), avatar_url=info.get("avatar_url"),
    ))


class FeishuAppLoginIn(BaseModel):
    code: str = Field(min_length=1)


@router.get("/feishu/client-config")
def feishu_client_config(db: Session = Depends(get_db)):
    """登录页公开配置（M36）：真实飞书是否启用 + App ID（非机密，工作台免登 JSAPI 需要）。"""
    from app.services.feishu import get_config, is_enabled

    enabled = is_enabled(db)
    cfg = get_config(db) if enabled else None
    db.commit()
    return ok({"enabled": enabled, "app_id": cfg.app_id if cfg else None})


@router.post("/feishu/app-login")
def feishu_app_login(body: FeishuAppLoginIn, db: Session = Depends(get_db)):
    """飞书客户端内免登（M36 工作台应用）：JSAPI requestAuthCode 的免登 code 换身份。

    与扫码 OAuth 共用兑换端点与身份处理（直登或落开通请求）；免登无 state（code 一次性+短时）。
    """
    from app.services.feishu import build_client, get_config, is_enabled

    if not is_enabled(db):
        raise AppError("FEISHU_NOT_ENABLED", "飞书认证未启用", 501)
    client = build_client(get_config(db))
    info = client.oauth_user_info(body.code)
    external_id = info.get("open_id") or info.get("union_id")
    if not external_id:
        raise AppError("FEISHU_ERROR", "飞书未返回用户标识", 502)
    return ok(_handle_feishu_identity(
        db, external_id=external_id,
        display_name=info.get("name") or info.get("en_name") or external_id,
        email=info.get("enterprise_email") or info.get("email"),
        mobile=info.get("mobile"), avatar_url=info.get("avatar_url"),
    ))


@router.get("/onboarding/status")
def onboarding_status(authorization: str = Header(default=""), db: Session = Depends(get_db)):
    """过渡页轮询：pending 停留等待；approved 直接返回正式令牌进入系统；rejected 显示原因。"""
    token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    req_id = decode_pending_token(token)
    if not req_id:
        raise AppError("INVALID_PENDING_TOKEN", "登录会话已失效，请重新扫码", 401)
    req = db.get(LoginRequest, req_id)
    if not req or req.is_deleted:
        raise AppError("NOT_FOUND", "登录请求不存在", 404)
    if req.status == "approved" and req.auth_user_id:
        user = db.get(AuthUser, req.auth_user_id)
        if user and user.is_active and not user.is_deleted:
            user.last_login_at = datetime.now()
            db.commit()
            return ok({"status": "approved", "token": create_token(user.id), "user": _user_payload(db, user)})
        raise AppError("LOGIN_FAILED", "账号不可用，请联系管理员", 401)
    if req.status == "rejected":
        return ok({"status": "rejected", "note": req.note, "display_name": req.display_name})
    return ok({"status": "pending", "display_name": req.display_name, "requested_at": req.created_at})


def _request_row(db: Session, req: LoginRequest) -> dict:
    # 自动匹配同步人员：external_id（组织同步的 open_id）优先，其次手机号/邮箱
    person = (
        db.query(OrgMember)
        .filter(OrgMember.external_source == req.external_source,
                OrgMember.external_id == req.external_id, OrgMember.is_deleted.is_(False))
        .first()
    )
    if not person and req.mobile:
        person = db.query(OrgMember).filter(OrgMember.mobile == req.mobile, OrgMember.is_deleted.is_(False)).first()
    if not person and req.email:
        person = db.query(OrgMember).filter(OrgMember.email == req.email, OrgMember.is_deleted.is_(False)).first()
    return {
        "id": req.id, "external_source": req.external_source, "external_id": req.external_id,
        "display_name": req.display_name, "email": req.email, "mobile": req.mobile,
        "status": req.status, "note": req.note, "requested_at": req.created_at,
        "processed_at": req.processed_at, "auth_user_id": req.auth_user_id,
        "matched_person_id": person.id if person else None,
        "matched_person_name": person.name if person else None,
    }


@router.get("/onboarding/requests")
def list_requests(status: str = "pending", db: Session = Depends(get_db), _=Depends(require_perm("admin_users", "view"))):
    query = db.query(LoginRequest).filter(LoginRequest.is_deleted.is_(False))
    if status:
        query = query.filter(LoginRequest.status == status)
    rows = query.order_by(LoginRequest.created_at.desc()).limit(200).all()
    return ok([_request_row(db, r) for r in rows], total=len(rows))


@router.get("/onboarding/pending-count")
def pending_count(db: Session = Depends(get_db), _=Depends(require_perm("admin_users", "view"))):
    n = db.query(LoginRequest).filter(LoginRequest.status == "pending", LoginRequest.is_deleted.is_(False)).count()
    return ok({"pending": n})


@router.post("/onboarding/requests/{request_id}/approve")
def approve_request(request_id: str, body: ApproveIn, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("admin_users", "create"))):
    """开通：为员工创建飞书账号（用户名/角色/默认语言），标记请求已处理并通知员工。"""
    from app.services.rbac import valid_role_codes

    req = db.get(LoginRequest, request_id)
    if not req or req.is_deleted:
        raise AppError("NOT_FOUND", "登录请求不存在", 404)
    if req.status != "pending":
        raise AppError("ALREADY_PROCESSED", "该请求已处理")
    if db.query(AuthUser).filter(AuthUser.username == body.username, AuthUser.is_deleted.is_(False)).first():
        raise AppError("USERNAME_TAKEN", "用户名已存在")
    bad = set(body.roles) - valid_role_codes(db)
    if bad:
        raise AppError("INVALID_ROLE", f"未知角色: {','.join(bad)}")
    if "admin" in body.roles:
        raise AppError("ADMIN_NOT_GRANTABLE", "开通时不可直接授予 admin 角色")
    roles = body.roles
    if not roles:  # 未指定则按开通规则取默认
        from app.services.provisioning import default_roles_for

        person = db.get(OrgMember, body.person_id) if body.person_id else None
        roles = default_roles_for(db, person.department_id if person else None)
    if body.person_id and not db.get(OrgMember, body.person_id):
        raise AppError("NOT_FOUND", "关联人员不存在", 404)

    import secrets

    user = AuthUser(
        username=body.username,
        password_hash=hash_password(secrets.token_urlsafe(24)),  # 飞书用户走扫码，本地口令随机不可用
        auth_source="feishu", external_id=req.external_id,
        roles=roles, person_id=body.person_id, is_active=True,
        preferences={"language": body.language},
    )
    db.add(user)
    db.flush()
    req.status = "approved"
    req.processed_by = actor.id
    req.processed_at = datetime.now()
    req.auth_user_id = user.id
    req.note = body.note
    audit(db, "login_request", req.id, "approve", actor,
          {"username": body.username, "roles": roles, "language": body.language})
    if user.person_id:
        _notify(
            db, "onboarding.approved", req,
            title="您的系统账号已开通", content=f"账号 {body.username} 已开通，欢迎使用 IT 运营管理平台。",
            recipients=[user.person_id], link="/dashboard",
        )
    db.commit()
    return ok({"id": user.id, "username": user.username, "roles": roles})


@router.post("/onboarding/requests/{request_id}/reject")
def reject_request(request_id: str, body: RejectIn, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("admin_users", "create"))):
    req = db.get(LoginRequest, request_id)
    if not req or req.is_deleted:
        raise AppError("NOT_FOUND", "登录请求不存在", 404)
    if req.status != "pending":
        raise AppError("ALREADY_PROCESSED", "该请求已处理")
    req.status = "rejected"
    req.note = body.reason
    req.processed_by = actor.id
    req.processed_at = datetime.now()
    audit(db, "login_request", req.id, "reject", actor, {"reason": body.reason})
    db.commit()
    return ok({"id": req.id, "status": "rejected"})
