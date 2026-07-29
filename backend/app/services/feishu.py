"""飞书开放平台集成（M11）：组织同步 Provider + 扫码登录 OAuth。

- FeishuClient：tenant/app token、通讯录（部门子树+成员）、OAuth code 换用户身份
- FeishuOrgProvider：仅同步配置的 IT 团队根部门子树 → OrgSnapshot（对接 org_sync 引擎）
- 所有请求走 httpx，10s 超时；飞书错误码非 0 一律抛 AppError 带上游 msg，便于排障
- user_id_type=open_id / department_id_type=open_department_id：external_id 全链路用 open_id，
  与扫码登录(authen user_info.open_id)天然对齐
"""
import logging
import base64
import json
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import FeishuConfig
from app.services.org_sync import DeptIn, MemberIn, OrgSnapshot, OrgSyncProvider
from app.services.secrets_store import decrypt_secret

logger = logging.getLogger("aom.feishu")

TIMEOUT = 10.0
GENDER_MAP = {1: "男", 2: "女"}
EMPLOYEE_TYPE_MAP = {1: "正式", 2: "实习", 3: "外包", 4: "劳务", 5: "顾问"}
HELPDESK_EVENT_SUBSCRIPTIONS = (
    {"type": "helpdesk.ticket", "subtype": "ticket.created_v1"},
    {"type": "helpdesk.ticket", "subtype": "ticket.updated_v1"},
    {"type": "helpdesk.ticket_message", "subtype": "ticket_message.created_v1"},
)


def get_config(db: Session) -> FeishuConfig:
    """取飞书配置单行；不存在则创建空行（enabled=False）。"""
    cfg = db.query(FeishuConfig).filter(FeishuConfig.is_deleted.is_(False)).first()
    if not cfg:
        cfg = FeishuConfig(enabled=False)
        db.add(cfg)
        db.flush()
    return cfg


def is_enabled(db: Session) -> bool:
    cfg = db.query(FeishuConfig).filter(FeishuConfig.is_deleted.is_(False)).first()
    return bool(cfg and cfg.enabled and cfg.app_id and cfg.app_secret)


class FeishuClient:
    def __init__(self, api_base: str, app_id: str, app_secret: str):
        self.api_base = (api_base or "https://open.feishu.cn").rstrip("/")
        self.app_id = app_id
        self.app_secret = app_secret

    # ---------- 基础 ----------

    def _post(self, path: str, json: dict, token: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            resp = httpx.post(f"{self.api_base}{path}", json=json, headers=headers, timeout=TIMEOUT)
            data = resp.json()
        except Exception as e:  # 网络/JSON 异常统一转 502
            raise AppError("FEISHU_UNREACHABLE", f"飞书接口不可达：{e}", 502)
        if data.get("code", -1) != 0:
            raise AppError("FEISHU_ERROR", f"飞书返回错误 {data.get('code')}：{data.get('msg')}", 502)
        return data

    def _get(self, path: str, params: dict, token: str) -> dict:
        try:
            resp = httpx.get(
                f"{self.api_base}{path}", params=params,
                headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT,
            )
            data = resp.json()
        except Exception as e:
            raise AppError("FEISHU_UNREACHABLE", f"飞书接口不可达：{e}", 502)
        if data.get("code", -1) != 0:
            raise AppError("FEISHU_ERROR", f"飞书返回错误 {data.get('code')}：{data.get('msg')}", 502)
        return data

    def tenant_access_token(self) -> str:
        data = self._post("/open-apis/auth/v3/tenant_access_token/internal",
                          {"app_id": self.app_id, "app_secret": self.app_secret})
        return data["tenant_access_token"]

    def app_access_token(self) -> str:
        data = self._post("/open-apis/auth/v3/app_access_token/internal",
                          {"app_id": self.app_id, "app_secret": self.app_secret})
        return data["app_access_token"]

    # ---------- 通讯录（按配置的同步范围拉取） ----------

    def get_department(self, token: str, department_id: str) -> dict:
        data = self._get(f"/open-apis/contact/v3/departments/{department_id}",
                         {"department_id_type": "open_department_id"}, token)
        return data["data"]["department"]

    def list_child_departments(self, token: str, root_department_id: str) -> list[dict]:
        """root 的全部子孙部门（fetch_child=true，分页汇总；不含 root 本身）。"""
        items: list[dict] = []
        page_token = ""
        while True:
            params = {
                "department_id_type": "open_department_id", "user_id_type": "open_id",
                "fetch_child": "true", "page_size": 50,
            }
            if page_token:
                params["page_token"] = page_token
            data = self._get(f"/open-apis/contact/v3/departments/{root_department_id}/children", params, token)
            payload = data.get("data") or {}
            items.extend(payload.get("items") or [])
            if not payload.get("has_more"):
                return items
            page_token = payload.get("page_token") or ""

    def list_department_users(self, token: str, department_id: str) -> list[dict]:
        """某部门的直属成员（分页汇总）。"""
        items: list[dict] = []
        page_token = ""
        while True:
            params = {
                "department_id": department_id, "department_id_type": "open_department_id",
                "user_id_type": "open_id", "page_size": 50,
            }
            if page_token:
                params["page_token"] = page_token
            data = self._get("/open-apis/contact/v3/users/find_by_department", params, token)
            payload = data.get("data") or {}
            items.extend(payload.get("items") or [])
            if not payload.get("has_more"):
                return items
            page_token = payload.get("page_token") or ""

    # ---------- OAuth 扫码登录 ----------

    def authorize_url(self, redirect_uri: str, state: str) -> str:
        from urllib.parse import quote

        return (f"{self.api_base}/open-apis/authen/v1/authorize"
                f"?app_id={self.app_id}&redirect_uri={quote(redirect_uri, safe='')}&state={quote(state, safe='')}")

    def oauth_user_info(self, code: str) -> dict:
        """code → 用户身份：{open_id, union_id, name, en_name, email, mobile, avatar_url}。"""
        app_token = self.app_access_token()
        data = self._post("/open-apis/authen/v1/oidc/access_token",
                          {"grant_type": "authorization_code", "code": code}, token=app_token)
        user_token = data["data"]["access_token"]
        info = self._get("/open-apis/authen/v1/user_info", {}, user_token)
        return info["data"]

    # ---------- 服务台 ----------

    def get_helpdesk_ticket(self, ticket_id: str, helpdesk_id: str, helpdesk_token: str) -> dict:
        """读取服务台工单详情。

        服务台接口除 tenant_access_token 外，还要求
        ``X-Lark-Helpdesk-Authorization=base64(helpdesk_id:helpdesk_token)``。
        两个服务台凭据只在后端使用，绝不返回给浏览器。
        """
        if not ticket_id.strip():
            raise AppError("FEISHU_TICKET_REQUIRED", "飞书工单 ID 不能为空", 422)
        if not helpdesk_id or not helpdesk_token:
            raise AppError("FEISHU_HELPDESK_NOT_CONFIGURED", "飞书服务台 ID / Token 未配置", 501)
        tenant_token = self.tenant_access_token()
        credential = base64.b64encode(f"{helpdesk_id}:{helpdesk_token}".encode()).decode()
        try:
            response = httpx.get(
                f"{self.api_base}/open-apis/helpdesk/v1/tickets/{ticket_id.strip()}",
                headers={
                    "Authorization": f"Bearer {tenant_token}",
                    "Content-Type": "application/json; charset=utf-8",
                    "X-Lark-Helpdesk-Authorization": credential,
                },
                timeout=TIMEOUT,
            )
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise AppError("FEISHU_UNREACHABLE", f"飞书服务台接口不可达：{exc}", 502) from exc
        if data.get("code", -1) != 0:
            raise AppError("FEISHU_HELPDESK_ERROR", f"飞书服务台返回错误 {data.get('code')}：{data.get('msg')}", 502)
        return (data.get("data") or {}).get("ticket") or {}

    def _helpdesk_headers(self, helpdesk_id: str, helpdesk_token: str) -> dict[str, str]:
        """Build the tenant + service-desk headers required by Helpdesk APIs."""
        tenant_token = self.tenant_access_token()
        credential = base64.b64encode(f"{helpdesk_id}:{helpdesk_token}".encode()).decode()
        return {
            "Authorization": f"Bearer {tenant_token}",
            "Content-Type": "application/json; charset=utf-8",
            "X-Lark-Helpdesk-Authorization": credential,
        }

    def subscribe_helpdesk_events(self, helpdesk_id: str, helpdesk_token: str) -> None:
        """为当前自建应用订阅服务台事件。

        飞书服务台事件不是仅在开发者后台勾选后就会生效，还需要调用
        ``/open-apis/helpdesk/v1/events/subscribe``，并使用服务台凭证请求头。
        飞书当前线上接口要求请求体显式提交 ``events``，并且每个事件必须拆成
        ``type`` 与 ``subtype``，不能直接提交开放平台展示的完整事件 Key。
        事件仍需同时在飞书开放平台的应用事件配置中添加并发布。
        """
        if not helpdesk_id or not helpdesk_token:
            raise AppError("FEISHU_HELPDESK_NOT_CONFIGURED", "飞书服务台 ID / Token 未配置", 501)
        try:
            response = httpx.post(
                f"{self.api_base}/open-apis/helpdesk/v1/events/subscribe",
                headers=self._helpdesk_headers(helpdesk_id, helpdesk_token),
                json={"events": [dict(event) for event in HELPDESK_EVENT_SUBSCRIPTIONS]},
                timeout=TIMEOUT,
            )
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise AppError("FEISHU_UNREACHABLE", f"飞书服务台事件订阅接口不可达：{exc}", 502) from exc
        if data.get("code", -1) != 0:
            error = data.get("error") or {}
            violations = error.get("field_violations") or []
            details = "; ".join(
                f"{item.get('field')}: {item.get('description')}"
                for item in violations
                if isinstance(item, dict) and (item.get("field") or item.get("description"))
            )
            if error.get("log_id"):
                details = f"{details}; log_id={error['log_id']}" if details else f"log_id={error['log_id']}"
            detail_suffix = f"（{details}）" if details else ""
            raise AppError(
                "FEISHU_HELPDESK_SUBSCRIBE_ERROR",
                f"飞书服务台事件订阅失败 {data.get('code')}：{data.get('msg')}{detail_suffix}",
                502,
            )

    def send_helpdesk_message(
        self,
        ticket_id: str,
        helpdesk_id: str,
        helpdesk_token: str,
        text: str,
    ) -> str:
        """向同一飞书服务台工单会话发送用户可见文本消息。

        使用 Helpdesk 工单消息接口，而不是单独给用户发机器人私聊，确保
        消息留在“转人工”产生的会话中。接口返回的消息 ID 用于 outbox 审计。
        """
        if not ticket_id.strip() or not text.strip():
            raise AppError("FEISHU_MESSAGE_INVALID", "飞书工单消息缺少工单 ID 或内容", 422)
        return self._send_helpdesk_message_payload(
            ticket_id,
            helpdesk_id,
            helpdesk_token,
            "text",
            json.dumps({"text": text.strip()}, ensure_ascii=False),
        )

    def _send_helpdesk_message_payload(
        self,
        ticket_id: str,
        helpdesk_id: str,
        helpdesk_token: str,
        msg_type: str,
        content: str | dict,
    ) -> str:
        """Send one Helpdesk conversation message and return its message ID."""
        if not ticket_id.strip() or not msg_type.strip():
            raise AppError("FEISHU_MESSAGE_INVALID", "飞书工单消息缺少工单 ID 或消息类型", 422)
        if not helpdesk_id or not helpdesk_token:
            raise AppError("FEISHU_HELPDESK_NOT_CONFIGURED", "飞书服务台 ID / Token 未配置", 501)
        serialized_content = (
            json.dumps(content, ensure_ascii=False, separators=(",", ":"))
            if isinstance(content, dict)
            else content
        )
        try:
            response = httpx.post(
                f"{self.api_base}/open-apis/helpdesk/v1/tickets/{ticket_id.strip()}/messages",
                headers=self._helpdesk_headers(helpdesk_id, helpdesk_token),
                json={"msg_type": msg_type.strip(), "content": serialized_content},
                timeout=TIMEOUT,
            )
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise AppError("FEISHU_UNREACHABLE", f"飞书服务台消息接口不可达：{exc}", 502) from exc
        if data.get("code", -1) != 0:
            raise AppError("FEISHU_HELPDESK_MESSAGE_ERROR", f"飞书服务台消息发送失败 {data.get('code')}：{data.get('msg')}", 502)
        result = data.get("data") or {}
        return str(result.get("message_id") or result.get("id") or "")

    def send_helpdesk_routing_prompt(
        self,
        ticket_id: str,
        helpdesk_id: str,
        helpdesk_token: str,
        service_request_url: str,
        requirement_url: str,
    ) -> tuple[str, str]:
        """把 ITOM 两个稳定入口写入原服务台会话。

        Helpdesk 富文本在部分租户或接口版本中可能不可用，因此先尝试
        ``post``，失败后自动降级为包含完整 URL 的文本消息。两种消息都
        留在原服务台会话中；仅当它们都失败时，outbox 才会重试并最终使用
        独立应用机器人卡片兜底。
        """
        post = {
            "post": {
                "zh_cn": {
                    "title": "请选择 ITOM 后续处理方式",
                    "content": [
                        [{"tag": "text", "text": "人工客服已完成初步确认，请选择要创建的 ITOM 单据。"}],
                        [{"tag": "a", "text": "创建 IT 服务请求（故障、配置、运维）", "href": service_request_url}],
                        [{"tag": "a", "text": "登记 IT 需求（新系统、新功能）", "href": requirement_url}],
                    ],
                }
            }
        }
        try:
            message_id = self._send_helpdesk_message_payload(
                ticket_id,
                helpdesk_id,
                helpdesk_token,
                "post",
                post,
            )
            return message_id, "helpdesk_post"
        except AppError as exc:
            logger.warning(
                "Helpdesk post routing prompt failed for ticket %s; falling back to text: %s",
                ticket_id,
                exc,
            )
            # ``helpdesk:all`` is a deterministic application-scope failure.
            # Trying the text endpoint immediately afterwards only adds another
            # network timeout before the application-bot fallback can be sent.
            # Let the outbox classify this error and switch channels at once.
            if "helpdesk:all" in str(exc) or "99991672" in str(exc):
                raise
        text = (
            "人工客服已完成初步确认，请选择 ITOM 后续处理方式：\n"
            f"创建 IT 服务请求（故障、配置、运维）：{service_request_url}\n"
            f"登记 IT 需求（新系统、新功能）：{requirement_url}"
        )
        message_id = self.send_helpdesk_message(ticket_id, helpdesk_id, helpdesk_token, text)
        return message_id, "helpdesk_text"

    def get_helpdesk_ticket_customized_fields(self, helpdesk_id: str, helpdesk_token: str) -> list[dict]:
        """读取服务台工单自定义字段及下拉选项。

        工单详情中的下拉字段通常只返回选项内部 ``tag``（一个 UUID），而不是
        用户看到的显示名称。服务台字段配置接口同时返回
        ``dropdown_options.children[].display_name``，用于把这个内部值转换回
        可读的字段值后再交给 ITOM 表单。

        不同版本的服务台 API 曾使用 ``ticket_customized_fields`` 和
        ``customized_fields`` 两个路径，按顺序兼容；如果租户尚未开放该接口，
        调用方会保留原始值并记录警告，不会阻断工单交接。
        """
        if not helpdesk_id or not helpdesk_token:
            raise AppError("FEISHU_HELPDESK_NOT_CONFIGURED", "飞书服务台 ID / Token 未配置", 501)
        tenant_token = self.tenant_access_token()
        credential = base64.b64encode(f"{helpdesk_id}:{helpdesk_token}".encode()).decode()
        headers = {
            "Authorization": f"Bearer {tenant_token}",
            "Content-Type": "application/json; charset=utf-8",
            "X-Lark-Helpdesk-Authorization": credential,
        }
        last_error: AppError | None = None
        for endpoint in (
            "/open-apis/helpdesk/v1/ticket_customized_fields",
            "/open-apis/helpdesk/v1/customized_fields",
        ):
            items: list[dict] = []
            page_token = ""
            try:
                while True:
                    params = {"helpdesk_id": helpdesk_id, "page_size": 100}
                    if page_token:
                        params["page_token"] = page_token
                    response = httpx.get(f"{self.api_base}{endpoint}", params=params, headers=headers, timeout=TIMEOUT)
                    data = response.json()
                    if data.get("code", -1) != 0:
                        raise AppError(
                            "FEISHU_HELPDESK_ERROR",
                            f"飞书服务台返回错误 {data.get('code')}：{data.get('msg')}",
                            502,
                        )
                    payload = data.get("data") or {}
                    batch = payload.get("items") or payload.get("ticket_customized_fields") or []
                    if isinstance(batch, list):
                        items.extend(item for item in batch if isinstance(item, dict))
                    if not payload.get("has_more"):
                        return items
                    page_token = str(payload.get("page_token") or payload.get("next_page_token") or "")
                    if not page_token:
                        return items
            except AppError as exc:
                last_error = exc
            except Exception as exc:  # noqa: BLE001
                last_error = AppError("FEISHU_UNREACHABLE", f"飞书服务台接口不可达：{exc}", 502)
        if last_error:
            raise last_error
        return []

    def send_interactive_card(self, receive_id: str, receive_id_type: str, card: dict) -> str:
        """以应用身份发送交互卡片，返回飞书消息 ID。"""
        token = self.tenant_access_token()
        try:
            response = httpx.post(
                f"{self.api_base}/open-apis/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
                json={
                    "receive_id": receive_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card, ensure_ascii=False, separators=(",", ":")),
                },
                timeout=TIMEOUT,
            )
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise AppError("FEISHU_UNREACHABLE", f"飞书消息接口不可达：{exc}", 502) from exc
        if data.get("code", -1) != 0:
            raise AppError("FEISHU_MESSAGE_ERROR", f"飞书消息发送失败 {data.get('code')}：{data.get('msg')}", 502)
        message_id = (data.get("data") or {}).get("message_id")
        if not message_id:
            raise AppError("FEISHU_MESSAGE_ERROR", "飞书消息发送成功但未返回 message_id", 502)
        return message_id

    def send_app_text(self, receive_id: str, receive_id_type: str, text: str) -> str:
        """以应用身份发送普通文本消息。

        服务台工单消息接口需要 ``helpdesk:all``。在租户尚未开通该应用身份
        权限时，可靠同步仍应立即把用户可见进展送达，而不是让 outbox 重试
        数分钟后静默失败；此方法使用应用机器人私聊作为明确的降级通道。
        """
        if not receive_id.strip() or not text.strip():
            raise AppError("FEISHU_MESSAGE_INVALID", "飞书应用消息缺少接收人或内容", 422)
        token = self.tenant_access_token()
        try:
            response = httpx.post(
                f"{self.api_base}/open-apis/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
                json={
                    "receive_id": receive_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text.strip()}, ensure_ascii=False, separators=(",", ":")),
                },
                timeout=TIMEOUT,
            )
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise AppError("FEISHU_UNREACHABLE", f"飞书消息接口不可达：{exc}", 502) from exc
        if data.get("code", -1) != 0:
            raise AppError("FEISHU_MESSAGE_ERROR", f"飞书消息发送失败 {data.get('code')}：{data.get('msg')}", 502)
        message_id = (data.get("data") or {}).get("message_id")
        if not message_id:
            raise AppError("FEISHU_MESSAGE_ERROR", "飞书消息发送成功但未返回 message_id", 502)
        return message_id


def build_client(cfg: FeishuConfig) -> FeishuClient:
    if not (cfg.app_id and cfg.app_secret):
        raise AppError("SYNC_NOT_CONFIGURED", "飞书 App ID / App Secret 未配置", 501)
    return FeishuClient(cfg.api_base, cfg.app_id, cfg.app_secret)


def build_helpdesk_client(db: Session) -> tuple[FeishuClient, FeishuConfig, str, str]:
    """构造服务台客户端并解密服务台 Token。"""
    cfg = get_config(db)
    if not (cfg.app_id and cfg.app_secret):
        raise AppError("FEISHU_CONFIG_INCOMPLETE", "请先配置飞书 App ID 与 App Secret", 501)
    if not (cfg.helpdesk_enabled and cfg.helpdesk_id and cfg.helpdesk_token_encrypted):
        raise AppError("FEISHU_HELPDESK_NOT_CONFIGURED", "请先启用并配置飞书服务台 ID / Token", 501)
    return (
        FeishuClient(cfg.api_base, cfg.app_id, cfg.app_secret),
        cfg,
        cfg.helpdesk_id,
        decrypt_secret(cfg.helpdesk_token_encrypted),
    )


class FeishuOrgProvider(OrgSyncProvider):
    """按配置的同步范围拉取部门子树 + 成员，产出 OrgSnapshot（M32：支持多部门/全公司）。"""

    source = "feishu"

    def __init__(self, client: FeishuClient, scope: list[str]):
        self.client = client
        self.roots = scope  # open_department_id 列表；"0" 表示全公司

    def fetch(self) -> OrgSnapshot:
        token = self.client.tenant_access_token()
        snapshot = OrgSnapshot()
        subtree_ids: set[str] = set()
        for root_id in self.roots:
            if root_id == "0":
                # 全公司：飞书根部门 0 的子树即全部部门；顶层部门 parent 置空
                children = self.client.list_child_departments(token, "0")
                top_parent = None
            else:
                if root_id in subtree_ids:
                    continue
                root = self.client.get_department(token, root_id)
                subtree_ids.add(root_id)
                snapshot.departments.append(DeptIn(
                    external_id=root_id, name=root.get("name") or root_id,
                    parent_external_id=None, sort=int(root.get("order") or 0),
                ))
                children = self.client.list_child_departments(token, root_id)
                top_parent = root_id
            for d in children:
                ext = d.get("open_department_id") or d.get("department_id")
                if ext in subtree_ids:
                    continue
                subtree_ids.add(ext)
                parent = d.get("parent_department_id")
                snapshot.departments.append(DeptIn(
                    external_id=ext, name=d.get("name") or ext,
                    parent_external_id=parent if parent in subtree_ids else top_parent,
                    sort=int(d.get("order") or 0),
                ))

        seen: set[str] = set()
        for dept_ext in [d.external_id for d in snapshot.departments]:
            for u in self.client.list_department_users(token, dept_ext):
                open_id = u.get("open_id")
                if not open_id or open_id in seen:
                    continue  # 多部门挂靠：主取首个出现的部门
                seen.add(open_id)
                status = u.get("status") or {}
                snapshot.members.append(MemberIn(
                    external_id=open_id,
                    name=u.get("name") or open_id,
                    name_en=u.get("en_name") or None,
                    employee_no=u.get("employee_no") or None,
                    gender=GENDER_MAP.get(u.get("gender")),
                    employment_type=EMPLOYEE_TYPE_MAP.get(u.get("employee_type")),
                    work_location=u.get("city") or None,
                    email=u.get("enterprise_email") or u.get("email") or None,
                    mobile=u.get("mobile") or None,
                    department_external_id=dept_ext,
                    leader_external_id=u.get("leader_user_id") or None,
                    status="离职" if status.get("is_resigned") else "在岗",
                ))
        logger.info("feishu snapshot: %d depts, %d members", len(snapshot.departments), len(snapshot.members))
        return snapshot


def parse_scope(raw: str | None) -> list[str]:
    """解析同步范围：逗号/空白分隔的 open_department_id 列表；含 "0" 时视为全公司（仅保留 0）。"""
    import re as _re

    ids = [x for x in _re.split(r"[,\s，、;；]+", (raw or "").strip()) if x]
    return ["0"] if "0" in ids else ids


def provider_from_db(db: Session) -> FeishuOrgProvider:
    cfg = get_config(db)
    if not cfg.enabled:
        raise AppError("SYNC_NOT_CONFIGURED", "飞书集成未启用（系统管理→系统集成→飞书集成）", 501)
    scope = parse_scope(cfg.sync_scope)
    if not scope:
        raise AppError("SYNC_NOT_CONFIGURED", "未配置组织架构同步范围（部门 open_department_id，0=全公司）", 501)
    return FeishuOrgProvider(build_client(cfg), scope)


def run_feishu_sync(db: Session) -> dict:
    """执行同步并回写统计到配置行。"""
    from app.services.org_sync import apply_org_snapshot

    provider = provider_from_db(db)
    stats = apply_org_snapshot(db, "feishu", provider.fetch())
    cfg = get_config(db)
    cfg.last_sync_at = datetime.now()
    cfg.last_sync_stats = stats
    db.commit()
    return stats
