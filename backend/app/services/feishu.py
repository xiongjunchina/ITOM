"""飞书开放平台集成（M11）：组织同步 Provider + 扫码登录 OAuth。

- FeishuClient：tenant/app token、通讯录（部门子树+成员）、OAuth code 换用户身份
- FeishuOrgProvider：仅同步配置的 IT 团队根部门子树 → OrgSnapshot（对接 org_sync 引擎）
- 所有请求走 httpx，10s 超时；飞书错误码非 0 一律抛 AppError 带上游 msg，便于排障
- user_id_type=open_id / department_id_type=open_department_id：external_id 全链路用 open_id，
  与扫码登录(authen user_info.open_id)天然对齐
"""
import logging
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import FeishuConfig
from app.services.org_sync import DeptIn, MemberIn, OrgSnapshot, OrgSyncProvider

logger = logging.getLogger("aom.feishu")

TIMEOUT = 10.0
GENDER_MAP = {1: "男", 2: "女"}
EMPLOYEE_TYPE_MAP = {1: "正式", 2: "实习", 3: "外包", 4: "劳务", 5: "顾问"}


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


def build_client(cfg: FeishuConfig) -> FeishuClient:
    if not (cfg.app_id and cfg.app_secret):
        raise AppError("SYNC_NOT_CONFIGURED", "飞书 App ID / App Secret 未配置", 501)
    return FeishuClient(cfg.api_base, cfg.app_id, cfg.app_secret)


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
