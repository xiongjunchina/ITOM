from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import create_token, hash_password, verify_password
from app.db import get_db
from app.deps import get_current_user
from app.models import AuthUser, OrgMember, ProcessInstance, ProcessTask, Project, Problem, Requirement, Ticket
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
    valid = bool(user and verify_password(body.password, user.password_hash))
    if user and not valid:
        from app.services.ldap_auth import authenticate_ldap
        valid = authenticate_ldap(db, body.username, body.password)
        if valid:
            user.auth_source = "ad"
    if not user or not valid:
        raise AppError("LOGIN_FAILED", "用户名或密码错误", 401)
    if not user.is_active:
        raise AppError("LOGIN_FAILED", "账号已禁用", 401)
    user.last_login_at = datetime.now()
    from app.services.audit import audit as _audit
    _audit(db, "auth_user", user.id, "login", user, {"source": "password"})
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
    notification_preferences: dict[str, bool] | None = None
    theme: str | None = Field(default=None, pattern="^(light|dark|system)$")
    density: str | None = Field(default=None, pattern="^(default|compact)$")
    # 每个清单的列可见性/宽度偏好；仅允许通过当前用户接口写入，服务端
    # 对数量和宽度做边界校验，避免把任意数据写入偏好 JSON。
    table_views: dict[str, dict] | None = None


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
    updates = body.model_dump(exclude_unset=True)
    table_views = updates.get("table_views")
    if table_views is not None:
        if len(table_views) > 64:
            raise AppError("TABLE_VIEW_INVALID", "清单视图配置数量不能超过 64 个", 422)
        normalized_views: dict[str, dict] = {}
        for table_key, view in table_views.items():
            if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,63}", table_key):
                raise AppError("TABLE_VIEW_INVALID", "清单视图标识格式不正确", 422)
            if not isinstance(view, dict):
                raise AppError("TABLE_VIEW_INVALID", "清单视图配置格式不正确", 422)
            visible = view.get("visible", [])
            widths = view.get("widths", {})
            if not isinstance(visible, list) or len(visible) > 128 or not all(isinstance(x, str) for x in visible):
                raise AppError("TABLE_VIEW_INVALID", "可见字段配置格式不正确", 422)
            if not isinstance(widths, dict) or len(widths) > 128:
                raise AppError("TABLE_VIEW_INVALID", "列宽配置格式不正确", 422)
            normalized_views[table_key] = {
                "visible": visible,
                "widths": {
                    str(key): max(80, min(800, int(value)))
                    for key, value in widths.items()
                    if isinstance(key, str) and isinstance(value, (int, float))
                },
            }
        updates["table_views"] = normalized_views
    for k, v in updates.items():
        prefs[k] = v
    user.preferences = prefs
    from app.services.audit import audit as _audit
    _audit(db, "auth_user", user.id, "update_preferences", user,
           {"keys": sorted(body.model_dump(exclude_unset=True))})
    db.commit()
    return ok({"preferences": prefs})


@router.get("/me/todos")
def list_my_todos(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """当前用户可处理的流程待办，详情页负责执行具体流程动作。"""
    from app.services import process_engine

    page = max(1, page)
    page_size = max(1, min(100, page_size))
    tasks = (
        db.query(ProcessTask)
        .join(ProcessInstance, ProcessTask.instance_id == ProcessInstance.id)
        .filter(
            ProcessTask.status == "待处理",
            ProcessTask.is_deleted.is_(False),
            ProcessInstance.status.in_(["running", "进行中"]),
            ProcessInstance.is_deleted.is_(False),
        )
        .order_by(ProcessTask.due_at.is_(None), ProcessTask.due_at.asc(), ProcessTask.created_at.desc())
        .all()
    )
    member_names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    items = []
    for task in tasks:
        if not process_engine.can_act_on_task(db, user, task):
            continue
        instance = db.get(ProcessInstance, task.instance_id)
        if not instance:
            continue
        entity = None
        code = None
        title = None
        if instance.entity_type in ("ticket", "ticket_change"):
            entity = db.get(Ticket, instance.entity_id)
            code, title = (entity.ticket_code, entity.title) if entity else (None, None)
        elif instance.entity_type == "requirement":
            entity = db.get(Requirement, instance.entity_id)
            code, title = (entity.requirement_code, entity.title) if entity else (None, None)
        elif instance.entity_type == "project":
            entity = db.get(Project, instance.entity_id)
            code, title = (entity.project_code, entity.name) if entity else (None, None)
        elif instance.entity_type == "problem":
            entity = db.get(Problem, instance.entity_id)
            code, title = (entity.problem_code, entity.title) if entity else (None, None)
        elif instance.entity_type == "bug":
            from app.models import Bug

            entity = db.get(Bug, instance.entity_id)
            code, title = (entity.bug_code, entity.title) if entity else (None, None)
        if not entity or getattr(entity, "is_deleted", False):
            continue
        link_template = process_engine.ENTITY_LINKS.get(instance.entity_type)
        if not link_template:
            continue
        items.append({
            "id": task.id,
            "task_id": task.id,
            "entity_type": instance.entity_type,
            "entity_id": instance.entity_id,
            "code": code,
            "title": title,
            "process_name": instance.definition.name,
            "step_name": task.step.name if task.step else "",
            "step_seq": task.step.seq if task.step else None,
            "assignee": task.assignee,
            "assignee_name": member_names.get(task.assignee) if task.assignee else None,
            "due_at": task.due_at,
            "created_at": task.created_at,
            "link": link_template.format(id=instance.entity_id),
        })
    total = len(items)
    start = (page - 1) * page_size
    return ok(items[start:start + page_size], total=total, page=page)


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
            "notification_preferences": prefs.get("notification_preferences", {}),
            "theme": prefs.get("theme", "light"),
            "density": prefs.get("density", "default"),
            "table_views": prefs.get("table_views", {}),
        },
    })


@router.get("/me/audit-logs")
def my_audit_logs(
    page: int = 1, page_size: int = 20,
    user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db),
):
    """当前账号自己的操作记录，不暴露其他人的审计数据。"""
    from app.models import AuditLog
    from app.schemas.common import paginate

    page_size = min(max(page_size, 1), 100)
    query = db.query(AuditLog).filter(AuditLog.actor == user.id)
    items, total = paginate(query.order_by(AuditLog.created_at.desc()), page, page_size)
    return ok([{
        "id": item.id, "entity_type": item.entity_type, "entity_id": item.entity_id,
        "action": item.action, "summary": item.summary, "created_at": item.created_at,
    } for item in items], total=total, page=page)


@router.delete("/me/feishu-binding")
def unbind_my_feishu(user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """解绑前必须已设置本地密码，确保用户仍可登录。人员主数据关联不受影响。"""
    if not user.external_id:
        raise AppError("NOT_BOUND", "当前账号未绑定飞书")
    if user.password_set_at is None:
        raise AppError("PASSWORD_REQUIRED", "请先设置本地登录密码，再解绑飞书")
    from app.services.audit import audit as _audit

    _audit(db, "auth_user", user.id, "unbind_feishu", user, {})
    user.external_id = None
    user.auth_source = "local"
    db.commit()
    return ok({"feishu_bound": False, "auth_source": "local"})


class BindFeishuIn(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    state: str = Field(min_length=1, max_length=512)


@router.get("/me/feishu-binding/authorize-url")
def feishu_binding_authorize_url(
    redirect_uri: str, user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db),
):
    """为当前已登录账号发起飞书绑定/换绑 OAuth。"""
    from app.services.feishu import build_client, get_config, is_enabled

    if not is_enabled(db):
        raise AppError("FEISHU_NOT_ENABLED", "飞书认证未启用", 501)
    state = create_pending_token(f"bind:{user.id}")
    return ok({"url": build_client(get_config(db)).authorize_url(redirect_uri, state)})


@router.post("/me/feishu-binding")
def bind_my_feishu(
    body: BindFeishuIn, user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db),
):
    """将 OAuth 返回的飞书身份绑定到当前账号；同一身份不可占用两个账号。"""
    from app.services.feishu import build_client, get_config, is_enabled
    from app.services.audit import audit as _audit

    if decode_pending_token(body.state) != f"bind:{user.id}":
        raise AppError("INVALID_STATE", "绑定会话校验失败，请重试", 401)
    if not is_enabled(db):
        raise AppError("FEISHU_NOT_ENABLED", "飞书认证未启用", 501)
    info = build_client(get_config(db)).oauth_user_info(body.code)
    external_id = info.get("open_id")
    occupied = db.query(AuthUser).filter(
        AuthUser.external_id == external_id, AuthUser.id != user.id, AuthUser.is_deleted.is_(False)
    ).first()
    if occupied:
        raise AppError("FEISHU_ALREADY_BOUND", "该飞书身份已绑定其他账号")
    user.external_id = external_id
    user.auth_source = "feishu"
    from app.services.aily import sync_aily_notification_identity

    sync_aily_notification_identity(db, user=user, feishu_info=info)
    _audit(db, "auth_user", user.id, "bind_feishu", user, {})
    db.commit()
    return ok({"feishu_bound": True, "auth_source": "feishu"})


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
    user.initial_password_ciphertext = None
    user.initial_password_sent_at = None
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
                            avatar_url: str | None = None,
                            feishu_info: dict | None = None) -> dict:
    """飞书身份 → 已开通直登 / 业务用户自动开户 / 其他人员进入审批。"""
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
        from app.services.aily import sync_aily_notification_identity

        sync_aily_notification_identity(db, user=existing, feishu_info=feishu_info)
        audit(db, "auth_user", existing.id, "login", existing, {"source": "feishu"})
        db.commit()
        return {"status": "active", "token": create_token(existing.id), "user": _user_payload(db, existing)}

    # 业务用户 JIT 开户：仅使用组织同步已经确认的非 IT 人员，不能安全匹配时继续审批流。
    from app.services.provisioning import provision_business_feishu_user

    business_user = provision_business_feishu_user(
        db,
        external_id=external_id,
        display_name=display_name,
        email=email,
        mobile=mobile,
    )
    if business_user:
        if not business_user.is_active:
            raise AppError("LOGIN_FAILED", "账号已禁用，请联系管理员", 401)
        business_user.last_login_at = datetime.now()
        from app.services.aily import sync_aily_notification_identity

        sync_aily_notification_identity(db, user=business_user, feishu_info=feishu_info)
        audit(db, "auth_user", business_user.id, "auto_provision_business_login", business_user, {
            "source": "feishu", "role_initialized": "requester",
        })
        db.commit()
        return {"status": "active", "token": create_token(business_user.id), "user": _user_payload(db, business_user)}

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
        feishu_info=info,
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
        feishu_info=info,
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
    """开通：生成随机初始密码并邮件送达；发送失败则事务回滚。"""
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
    from app.services.account_linking import get_linkable_person

    person = get_linkable_person(db, body.person_id)
    roles = body.roles
    if not roles:  # 未指定则按开通规则取默认
        from app.services.provisioning import default_roles_for

        roles = default_roles_for(db, person.department_id if person else None)

    import secrets
    import string

    alphabet = string.ascii_letters + string.digits + "!@#$%"
    initial_password = "".join([
        secrets.choice(string.ascii_uppercase), secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits), secrets.choice("!@#$%"),
        *(secrets.choice(alphabet) for _ in range(8)),
    ])

    user = AuthUser(
        username=body.username,
        password_hash=hash_password(initial_password),
        auth_source="feishu", external_id=req.external_id,
        roles=roles, person=person, is_active=True,
        preferences={"language": body.language},
        password_set_at=datetime.now(),
    )
    db.add(user)
    db.flush()
    req.status = "approved"
    req.processed_by = actor.id
    req.processed_at = datetime.now()
    req.auth_user_id = user.id
    req.note = body.note
    audit(db, "login_request", req.id, "approve", actor,
          {"username": body.username, "roles": roles, "language": body.language,
           "initial_password_generated": True})
    from app.services.secrets_store import encrypt_secret
    user.initial_password_ciphertext = encrypt_secret(initial_password)
    if user.person_id:
        _notify(
            db, "onboarding.approved", req,
            title="您的系统账号已开通", content=f"账号 {body.username} 已开通，欢迎使用 IT 运营管理平台。",
            recipients=[user.person_id], link="/dashboard",
        )
    db.commit()
    return ok({"id": user.id, "username": user.username, "roles": roles, "initial_password_available": True})


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
