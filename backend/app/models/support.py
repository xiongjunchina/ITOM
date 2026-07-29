"""支撑域模型（docs/04 §1）+ 岗位表（人员主数据依赖）。"""
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GlidBase, JsonCol


class Position(GlidBase):
    __tablename__ = "position"

    position_code: Mapped[str | None] = mapped_column(String(32), index=True, comment="岗位编码")
    name: Mapped[str] = mapped_column(String(64))
    position_family: Mapped[str | None] = mapped_column(String(32), comment="岗位族/序列")
    duties: Mapped[str | None] = mapped_column(Text, comment="分工职责")
    headcount: Mapped[int] = mapped_column(Integer, default=0, comment="编制数")
    service_domains: Mapped[list | None] = mapped_column(JsonCol, default=list, comment="服务业务域名称列表")
    primary_roles: Mapped[list | None] = mapped_column(JsonCol, default=list, comment="主责角色 code 列表")
    level_framework: Mapped[str | None] = mapped_column(String(64), comment="职级/能力框架")
    location_scope: Mapped[str | None] = mapped_column(String(128), comment="办公地点范围")
    skills: Mapped[str | None] = mapped_column(Text, comment="关键技能，分号分隔")
    contractor_allowed: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否允许外包/合同制")
    status: Mapped[str] = mapped_column(String(16), default="启用", comment="启用/停用")
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="展示顺序")


class Department(GlidBase):
    """公司组织架构（对齐 ServiceNow cmn_department）：一人一部门，纯数据不带权限。"""

    __tablename__ = "department"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"))
    dept_type: Mapped[str] = mapped_column(String(16), default="business", comment="it/business/audit")
    external_source: Mapped[str | None] = mapped_column(String(16), comment="同步来源预留：feishu/ad")
    external_id: Mapped[str | None] = mapped_column(String(128), comment="外部组织节点 ID 预留")
    sort: Mapped[int] = mapped_column(BigInteger, default=0, comment="排序（飞书部门 order 为超大整数，M34.1 扩为 BIGINT）")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class OrgMember(GlidBase):
    """人员主数据：人的档案（who you are），零权限语义。团队归属看用户组，权限看角色。"""

    __tablename__ = "org_member"

    name: Mapped[str] = mapped_column(String(64), comment="中文姓名")
    name_en: Mapped[str | None] = mapped_column(String(64), comment="英文姓名")
    employee_no: Mapped[str | None] = mapped_column(String(32), comment="工号")
    gender: Mapped[str | None] = mapped_column(String(8), comment="男/女")
    birth_date: Mapped[date | None] = mapped_column(Date)
    employment_type: Mapped[str | None] = mapped_column(String(16), comment="正式/外包/实习")
    supervisor_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), comment="直属上级")
    work_location: Mapped[str | None] = mapped_column(String(64), comment="办公地点")
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), index=True)
    position_id: Mapped[str | None] = mapped_column(ForeignKey("position.id"))
    status: Mapped[str] = mapped_column(String(16), default="在岗", comment="在岗/离职")
    hire_date: Mapped[date | None] = mapped_column(Date)
    email: Mapped[str | None] = mapped_column(String(128))
    mobile: Mapped[str | None] = mapped_column(String(32))
    external_source: Mapped[str | None] = mapped_column(String(16), comment="同步来源预留：feishu/ad")
    external_id: Mapped[str | None] = mapped_column(String(128), comment="外部人员 ID 预留")
    feishu_user_id: Mapped[str | None] = mapped_column(String(64), comment="飞书集成预留")
    skills: Mapped[list | None] = mapped_column(JsonCol, default=list)
    remarks: Mapped[str | None] = mapped_column(Text)

    position: Mapped[Position | None] = relationship()
    department: Mapped[Department | None] = relationship()


class BusinessDomain(GlidBase):
    """业务域/服务线：负责人是字段不是角色（ServiceNow ownership 惯例）。"""

    __tablename__ = "business_domain"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), comment="BP 负责人")
    backup_owner_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class BusinessDomainMember(GlidBase):
    """业务域服务团队（矩阵组织的横向服务线成员：BM 带领的 BP/开发等）。"""

    __tablename__ = "business_domain_member"
    __table_args__ = (UniqueConstraint("domain_id", "person_id"),)

    domain_id: Mapped[str] = mapped_column(ForeignKey("business_domain.id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("org_member.id"), index=True)


class BusinessDomainDepartment(GlidBase):
    """业务域服务范围：关联组织架构中的业务部门，可选择覆盖其下级部门。"""

    __tablename__ = "business_domain_department"
    __table_args__ = (UniqueConstraint("domain_id", "department_id"),)

    domain_id: Mapped[str] = mapped_column(ForeignKey("business_domain.id"), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("department.id"), index=True)
    include_children: Mapped[bool] = mapped_column(Boolean, default=True)


class ProvisionRule(GlidBase):
    """账号首次开通的默认角色映射（仅首次生效，之后角色自由增减，绝不绑死）。"""

    __tablename__ = "provision_rule"

    match_type: Mapped[str] = mapped_column(String(16), comment="dept_type/department")
    match_value: Mapped[str] = mapped_column(String(128), comment="dept_type 值或 department.id")
    default_roles: Mapped[list] = mapped_column(JsonCol, default=list)
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="小号优先，命中即停")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Role(GlidBase):
    """角色注册表：内置角色承载系统权限；自定义角色继承内置角色权限，
    并可被状态机 allowed_roles 与流程步骤 default_role 精确引用。"""

    __tablename__ = "role"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    base_role: Mapped[str | None] = mapped_column(String(32), comment="自定义角色继承的内置角色 code；内置角色为空")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class RolePermission(GlidBase):
    """功能权限矩阵：角色 × 模块 → 动作集（view/create/edit/delete）。admin 不入矩阵隐式全权。"""

    __tablename__ = "role_permission"
    __table_args__ = (UniqueConstraint("role_code", "module"),)

    role_code: Mapped[str] = mapped_column(String(32), index=True)
    module: Mapped[str] = mapped_column(String(48))
    actions: Mapped[list] = mapped_column(JsonCol, default=list)


class UserGroup(GlidBase):
    """用户组=团队/派单单位/资源池（矩阵组织的纵向专业线用它表达）。"""

    __tablename__ = "user_group"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    roles: Mapped[list | None] = mapped_column(JsonCol, default=list, comment="组授予的角色（人进组自动继承）")
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), comment="组负责人/专业线 TM")


class UserGroupMember(GlidBase):
    __tablename__ = "user_group_member"
    __table_args__ = (UniqueConstraint("group_id", "person_id"),)

    group_id: Mapped[str] = mapped_column(ForeignKey("user_group.id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("org_member.id"), index=True)


class AuthUser(GlidBase):
    __tablename__ = "auth_user"

    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    auth_source: Mapped[str] = mapped_column(String(16), default="local", comment="local/ad/feishu/sms/wechat")
    external_id: Mapped[str | None] = mapped_column(String(128), comment="外部认证源用户 ID")
    person_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"))
    roles: Mapped[list] = mapped_column(JsonCol, default=list, comment="直接角色；有效角色=直接∪组授予")
    preferences: Mapped[dict | None] = mapped_column(JsonCol, default=dict, comment="个人偏好：总览 widget 配置等")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    password_set_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="本地口令最近一次设定时间"
    )
    initial_password_ciphertext: Mapped[str | None] = mapped_column(
        Text, comment="审批生成初始密码的加密密文；改密/重置后清空"
    )
    initial_password_sent_at: Mapped[datetime | None] = mapped_column(DateTime)

    person: Mapped[OrgMember | None] = relationship()


class WorkflowStatus(GlidBase):
    __tablename__ = "workflow_status"

    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    is_initial: Mapped[bool] = mapped_column(Boolean, default=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class WorkflowTransition(GlidBase):
    __tablename__ = "workflow_transition"

    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    from_code: Mapped[str] = mapped_column(String(32))
    to_code: Mapped[str] = mapped_column(String(32))
    allowed_roles: Mapped[list | None] = mapped_column(JsonCol, default=list, comment="空=不限角色")


class MasterData(GlidBase):
    __tablename__ = "master_data"

    category: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(GlidBase):
    __tablename__ = "audit_log"

    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(26), index=True)
    action: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str | None] = mapped_column(String(26), comment="auth_user.id")
    actor_name: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[dict | None] = mapped_column(JsonCol)


class LoginRequest(GlidBase):
    """飞书扫码登录后、管理员开通前的待处理登录请求（M7）。

    员工扫码通过飞书身份校验后不立即进入系统；管理员为其配置用户名/角色/默认语言，
    开通前员工停留在过渡页并轮询本请求状态。飞书凭据就绪前 scan 接口以传入身份模拟回调。
    """

    __tablename__ = "login_request"

    external_source: Mapped[str] = mapped_column(String(16), default="feishu", comment="feishu/…")
    external_id: Mapped[str] = mapped_column(String(128), index=True, comment="飞书 open_id/union_id")
    display_name: Mapped[str] = mapped_column(String(128), comment="飞书返回的姓名")
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    email: Mapped[str | None] = mapped_column(String(128))
    mobile: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True, comment="pending/approved/rejected")
    note: Mapped[str | None] = mapped_column(String(500), comment="管理员备注 / 驳回原因")
    processed_by: Mapped[str | None] = mapped_column(String(26))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    auth_user_id: Mapped[str | None] = mapped_column(String(26), comment="开通后创建的用户 id")


class NotificationOutbox(GlidBase):
    __tablename__ = "notification_outbox"

    event_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(26))
    payload: Mapped[dict | None] = mapped_column(JsonCol)
    channel: Mapped[str] = mapped_column(String(16), default="in_app", comment="in_app/feishu…")
    status: Mapped[str] = mapped_column(String(16), default="pending", comment="pending/sent/failed")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class InAppNotification(GlidBase):
    __tablename__ = "in_app_notification"

    recipient: Mapped[str] = mapped_column(String(26), index=True, comment="收件标识：人员 id 或账号 id（M34 双语义，无外键弱引用）")
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(200), comment="前端路由")
    read_at: Mapped[datetime | None] = mapped_column(DateTime)


class Attachment(GlidBase):
    __tablename__ = "attachment"

    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(26), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str | None] = mapped_column(String(26))


class UiBrandingVersion(GlidBase):
    """UI 品牌配置快照：草稿与每次发布均保留完整 JSON，支持审计回滚。"""

    __tablename__ = "ui_branding_version"

    version: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True, comment="draft/published")
    config: Mapped[dict] = mapped_column(JsonCol, default=dict)
    published_by: Mapped[str | None] = mapped_column(String(26))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class UiBrandingAsset(GlidBase):
    """受控品牌图片；仅允许白名单位图类型，经公开只读端点提供。"""

    __tablename__ = "ui_branding_asset"

    kind: Mapped[str] = mapped_column(String(32), comment="logo_light/logo_dark/logo_square/favicon/login_background")
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    uploaded_by: Mapped[str | None] = mapped_column(String(26))


class FeishuConfig(GlidBase):
    """飞书集成单行配置（M11/M32）：组织同步（按配置范围）+ 扫码登录 OAuth + 服务台。

    app_secret 与 helpdesk_token 仅在 PUT 时写入，GET 返回掩码；
    enabled=False 时扫码登录退回模拟入口（开发用）。
    """

    __tablename__ = "feishu_config"

    api_base: Mapped[str] = mapped_column(String(100), default="https://open.feishu.cn", comment="飞书开放平台 API 基址")
    app_id: Mapped[str | None] = mapped_column(String(64), comment="自建应用 App ID")
    app_secret: Mapped[str | None] = mapped_column(String(128), comment="自建应用 App Secret")
    helpdesk_id: Mapped[str | None] = mapped_column(String(64), comment="服务台 ID")
    helpdesk_token_encrypted: Mapped[str | None] = mapped_column(Text, comment="服务台 Token 加密密文")
    helpdesk_enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="启用服务台 API 接入")
    helpdesk_event_verification_token_encrypted: Mapped[str | None] = mapped_column(
        Text, comment="事件订阅 Verification Token 加密密文"
    )
    helpdesk_event_url: Mapped[str | None] = mapped_column(String(500), comment="事件订阅回调地址")
    helpdesk_event_subscription_status: Mapped[str] = mapped_column(
        String(16), default="not_configured", comment="服务台事件订阅状态"
    )
    helpdesk_event_subscription_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="最近一次服务台事件订阅成功时间"
    )
    helpdesk_event_subscription_error: Mapped[str | None] = mapped_column(
        Text, comment="最近一次服务台事件订阅错误"
    )
    sync_scope: Mapped[str | None] = mapped_column(String(512), comment="组织架构同步范围：open_department_id 列表（逗号分隔），0=全公司（M32）")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="启用真实飞书（同步+扫码）")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sync_stats: Mapped[dict | None] = mapped_column(JsonCol, comment="上次同步统计")


class FeishuHelpdeskHandoff(GlidBase):
    """飞书服务台到 ITOM 的一次性交接上下文。

    令牌只保存哈希；原始工单快照用于在员工打开 ITOM 创建页时预填，
    不把服务台 Token 或飞书身份放进浏览器 URL。交接记录默认短期有效，
    创建服务请求/需求后标记为 consumed，便于审计和防重放。
    """

    __tablename__ = "feishu_helpdesk_handoff"
    __table_args__ = (UniqueConstraint("token_hash"),)

    ticket_id: Mapped[str] = mapped_column(String(128), index=True, comment="飞书服务台工单 ID")
    action: Mapped[str] = mapped_column(String(32), comment="service_request/requirement")
    source_user_open_id: Mapped[str] = mapped_column(String(128), index=True, comment="飞书 guest open_id")
    source_agent_open_id: Mapped[str | None] = mapped_column(String(128), comment="飞书客服 open_id")
    helpdesk_id: Mapped[str] = mapped_column(String(64), comment="服务台 ID")
    token_hash: Mapped[str] = mapped_column(String(128), index=True)
    ticket_snapshot: Mapped[dict] = mapped_column(JsonCol, default=dict, comment="脱敏后的工单字段快照")
    status: Mapped[str] = mapped_column(String(16), default="issued", index=True, comment="issued/consumed/expired")
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    consumed_entity_type: Mapped[str | None] = mapped_column(String(32))
    consumed_entity_id: Mapped[str | None] = mapped_column(String(26))
    callback_event_id: Mapped[str | None] = mapped_column(String(128), unique=True, index=True, comment="飞书卡片回调事件 ID，防重复处理")


class FeishuHelpdeskIntake(GlidBase):
    """飞书服务台与 ITOM 的待分流记录。

    一条记录对应一个飞书工单。人工客服完成初步沟通后，员工从卡片选择
    服务请求或 IT 需求，ITOM 才创建正式单据；在此之前只保存脱敏快照和
    外部身份，避免重复建单并保留跨系统关联。
    """

    __tablename__ = "feishu_helpdesk_intake"
    __table_args__ = (UniqueConstraint("helpdesk_id", "ticket_id"),)

    helpdesk_id: Mapped[str] = mapped_column(String(64), index=True)
    ticket_id: Mapped[str] = mapped_column(String(128), index=True)
    guest_open_id: Mapped[str | None] = mapped_column(String(128), index=True)
    guest_name: Mapped[str | None] = mapped_column(String(128))
    agent_open_id: Mapped[str | None] = mapped_column(String(128))
    agent_name: Mapped[str | None] = mapped_column(String(128))
    feishu_status: Mapped[str | None] = mapped_column(String(64))
    feishu_stage: Mapped[str | None] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(
        String(24), default="pending", index=True,
        comment="pending/service_request/requirement/cancelled",
    )
    snapshot: Mapped[dict] = mapped_column(JsonCol, default=dict)
    linked_entity_type: Mapped[str | None] = mapped_column(String(32))
    linked_entity_id: Mapped[str | None] = mapped_column(String(26), index=True)
    choice_card_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    routing_prompt_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="原服务台会话分流入口发送时间",
    )
    routing_prompt_channel: Mapped[str | None] = mapped_column(
        String(24), comment="helpdesk_post/helpdesk_text/im_card_fallback",
    )
    routing_prompt_message_id: Mapped[str | None] = mapped_column(
        String(128), comment="分流入口对应的飞书消息 ID",
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)


class FeishuHelpdeskSyncEvent(GlidBase):
    """飞书事件入站 outbox：先快速确认，再由后台幂等消费并重试。"""

    __tablename__ = "feishu_helpdesk_sync_event"
    __table_args__ = (UniqueConstraint("event_id"),)

    event_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    ticket_id: Mapped[str | None] = mapped_column(String(128), index=True)
    payload: Mapped[dict] = mapped_column(JsonCol, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True,
                                        comment="pending/processing/processed/failed")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)


class FeishuHelpdeskOutbox(GlidBase):
    """向飞书回写的可靠 outbox，仅承载用户可见消息或分流入口。"""

    __tablename__ = "feishu_helpdesk_outbox"
    __table_args__ = (UniqueConstraint("dedupe_key"),)

    helpdesk_id: Mapped[str] = mapped_column(String(64), index=True)
    ticket_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(24), comment="routing_prompt/choice_card/public_message")
    dedupe_key: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[dict] = mapped_column(JsonCol, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True,
                                        comment="pending/sending/sent/failed")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(String(128))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class SystemIntegrationConfig(GlidBase):
    """系统集成全局配置单行记录；敏感字段在 JSON 内以加密密文保存。"""

    __tablename__ = "system_integration_config"
    email_config: Mapped[dict] = mapped_column(JsonCol, default=dict)
    ldap_config: Mapped[dict] = mapped_column(JsonCol, default=dict)


class OrgSettings(GlidBase):
    """组织治理单行配置：数字化团队口径与飞书自动同步策略。"""

    __tablename__ = "org_settings"

    digital_team_department_ids: Mapped[list] = mapped_column(JsonCol, default=list)
    digital_team_member_ids: Mapped[list] = mapped_column(
        JsonCol,
        default=list,
        comment="不随部门整体纳入的数字化团队指定人员 ID",
    )
    digital_team_include_children: Mapped[bool] = mapped_column(Boolean, default=True)
    feishu_auto_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    feishu_auto_sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    feishu_auto_sync_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
