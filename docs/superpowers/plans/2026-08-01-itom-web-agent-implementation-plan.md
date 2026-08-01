# ITOM 网页智能体实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有 Aily MCP 普通用户边界的前提下，为 ITOM 网页增加按登录用户真实权限工作的智能助手，并分 WA0–WA4 完成模型治理、只读顾问、业务闭环、IT 员工受控写操作和效果治理。

**Architecture:** 网页助手只接受当前 ITOM Bearer 登录身份，通过独立 `/api/assistant` 适配器进入统一能力层；Aily 继续使用 `x-aily-jwt` 和 `/mcp/`。模型只选择服务端代码注册的能力，所有读取和写入均重新经过 ITOM 权限、数据范围、记录状态、流程任务、领域服务、确认、幂等与审计。

**Tech Stack:** Python 3.12、FastAPI 0.115、SQLAlchemy 2、Pydantic 2、PostgreSQL 16/SQLite tests、httpx、React 18、TypeScript 5.7、Ant Design 5、Axios/fetch SSE、pytest、Vite、IDC Kubernetes。

## Global Constraints

- 开始任何代码修改前，工作区必须干净，当前分支必须是 `feature/AI-agent-version`，并与 `origin/feature/AI-agent-version` 同步；已封存的 `feature/aily-agent-mcp` 不再接收提交，只通过用户批准的 PR 合入 `main`。
- IDC Kubernetes 是唯一运行、联调和验收环境；本地只运行临时 SQLite 自动化测试和前端生产构建，不启动 Docker/Compose ITOM 运行环境。
- ITOM 领域服务和 API 是业务事实、权限和流程的唯一依据；模型、提示词、档案和前端隐藏均不授权。
- 网页身份和 Aily 身份严格隔离；网页不自调用公网 `/mcp/`，Aily 工具范围不因网页助手而扩大。
- 所有 L3 写操作必须先形成服务端预览，再由本人明确确认；确认凭证单次使用、默认 10 分钟过期，并绑定用户、会话、能力和规范化参数摘要。
- L4 删除、批量变更、角色权限、流程定义和密钥操作首期不得注册为智能体能力。
- API Key、Token、Secret、Cookie、Authorization、密码和标记为敏感的动态表单字段不得进入模型、消息表、普通日志或 API 回显。
- 数据库迁移只新增表、列、索引和默认权限，不回填、不重算、不改写既有业务记录、流程实例、Aily 身份、MCP 意图或 MCP 审计。
- 每个阶段均以“实现 + 自动化测试 + 中文权威文档 + `docs/en` 英文镜像 + 前端生产构建 + IDC 验收”为完整交付。
- 每个任务只暂存计划列出的文件，禁止 `git add -A`；每个可独立审核的任务使用 Conventional Commit 提交。

## 文件结构锁定

### 后端新增

- `backend/app/models/assistant.py`：七类 AI 配置、会话、消息、动作和调用审计模型。
- `backend/app/schemas/assistant.py`：网页助手、动作确认、管理员配置的 Pydantic 输入输出契约。
- `backend/app/assistant/types.py`：渠道、受众、风险等级、模型事件和能力结果类型。
- `backend/app/assistant/redaction.py`：入模、持久化和日志三层脱敏。
- `backend/app/assistant/registry.py`：代码能力注册表及 JSON Schema 导出。
- `backend/app/assistant/policy.py`：根据用户、权限、数据范围、状态和流程任务裁剪能力。
- `backend/app/assistant/providers/base.py`：模型适配器协议。
- `backend/app/assistant/providers/openai_compatible.py`：OpenAI-compatible 流式、工具和结构化输出适配器。
- `backend/app/assistant/gateway.py`：主备模型选择、超时、熔断式降级和调用审计。
- `backend/app/assistant/orchestrator.py`：提示边界、工具循环、追问和 SSE 事件组织。
- `backend/app/assistant/capabilities/guidance.py`：模块说明、单据判断和导航。
- `backend/app/assistant/capabilities/queries.py`：本人记录、可见记录和本人待办查询。
- `backend/app/assistant/capabilities/service_requests.py`：服务请求草稿与闭环能力。
- `backend/app/assistant/capabilities/requirements.py`：BDO 需求草稿与登记能力。
- `backend/app/assistant/capabilities/it_operations.py`：关联建单、流程、工单、Bug 和任务能力。
- `backend/app/services/assistant_config.py`：提供商和档案草稿/发布/回滚。
- `backend/app/services/assistant_conversations.py`：会话归属、消息保存、归档与保留策略。
- `backend/app/services/assistant_actions.py`：L3 预览、确认、幂等、重授权和结果审计。
- `backend/app/services/assistant_knowledge.py`：已发布、当前用户可见的安全知识检索。
- `backend/app/services/process_actions.py`：网页/API/智能体共同使用的流程动作领域入口。
- `backend/app/services/ticket_actions.py`：网页/API/智能体共同使用的工单派单和流转领域入口。
- `backend/app/services/record_conversion.py`：跨单据“准备→创建并关联”的共同领域入口。
- `backend/app/routers/assistant.py`：`/api/assistant` 网页会话和 SSE API。
- `backend/app/routers/admin_ai.py`：`/api/admin/ai` 模型、档案、健康、用量和审计 API。

### 前端新增

- `frontend/src/api/assistant.ts`：带 Bearer/X-Lang 的 POST-SSE 客户端和事件解析。
- `frontend/src/components/assistant/AssistantLauncher.tsx`：全局右下角入口。
- `frontend/src/components/assistant/AssistantDrawer.tsx`：桌面抽屉/窄屏全屏会话容器。
- `frontend/src/components/assistant/AssistantMessageList.tsx`：文本、规则来源、结果和错误事件。
- `frontend/src/components/assistant/AssistantActionCard.tsx`：L2 预览、L3 确认/取消及失效状态。
- `frontend/src/components/assistant/AssistantContext.ts`：白名单页面上下文类型和构造器。
- `frontend/src/components/assistant/assistant.css`：助手局部样式。
- `frontend/src/pages/admin/AiAssistant.tsx`：提供商、档案、运行状态、用量和动作审计管理页。
- `frontend/src/i18n/locales/assistant.ts`：完整中英文助手文案。

### 既有文件只按职责修改

- `backend/app/models/__init__.py`、`backend/app/services/migrate.py`：注册模型和幂等增量迁移。
- `backend/app/services/permissions.py`：增加 `admin_ai`，默认仅 admin 拥有全动作。
- `backend/app/core/config.py`：增加部署侧模型主机白名单和安全限值。
- `backend/app/main.py`、`backend/app/routers/__init__.py`：注册新路由与保留任务。
- `backend/app/routers/process.py`、`tickets.py`、`record_relations.py`：改为调用共同领域入口，不复制规则。
- `backend/app/services/scheduler.py`：定时执行对话保留清理。
- `frontend/src/api/types.ts`、`router.tsx`、`components/MainLayout.tsx`、`components/menu.tsx`、`styles.css`：接入类型、管理页和全局入口。
- `frontend/src/i18n/index.ts`、`dict.ts`、`locales/admin.ts`：注册中英文文案和菜单。
- `backend/tests/test_wa0_*.py` 至 `test_wa4_*.py`：按阶段新增自动化，不连接 IDC 数据库。
- `README.md`、`docs/03-PRD.md`、`04-数据模型设计.md`、`05-API契约与架构设计.md`、`06-用户身份与组织模型设计.md`、`10-Aily-MCP版本交接与决策上下文.md` 及对应 `docs/en/`：每阶段同步实际完成状态。

---

### Task 0: 开发前 Git 与 IDC 数据安全检查

**Files:** 无代码文件；只读取 Git、GitHub Actions 和 IDC 状态。

**Interfaces:**
- Consumes: 已确认设计提交 `fe478a0` 和本实施计划提交。
- Produces: 干净且与远端同步的 `feature/AI-agent-version`、通过质量门禁的基线、数据库结构变更前的批准备份/检查点证据。

- [ ] **Step 1: 验证分支与工作区**

```bash
git branch --show-current
git status --short
git rev-list --left-right --count HEAD...origin/feature/AI-agent-version
```

Expected: 分支为 `feature/AI-agent-version`，工作区无输出；若本地领先，只允许推送当前 feature 分支。

- [ ] **Step 2: 推送当前文档基线并等待质量门禁**

```bash
git push origin feature/AI-agent-version
gh run list --branch feature/AI-agent-version --workflow "ITOM Quality Gate" --limit 1
```

Expected: 最新 run 的 backend、frontend、repository-contract 全部成功；失败时停止编码并先修复基线。

- [ ] **Step 3: 只读记录 IDC 当前状态**

```bash
curl --noproxy '*' --fail --silent --show-error https://itom.snnc.cc:30443/api/health
```

Expected: 返回 `success=true` 和 `status=ok`；另记录当前 backend/frontend 镜像、Pod Ready、PostgreSQL PVC 和最新可恢复点，不打印 Secret。

- [ ] **Step 4: 在首次结构迁移部署前完成批准的集群内 PostgreSQL 备份/检查点**

Expected: 备份文件、时间、数据库版本、校验值和恢复命令均留在批准的 IDC 运维位置；未取得可恢复证据时不得部署 Task 1。

---

### Task 1: WA0 数据模型、迁移与权限模块

**Files:**
- Create: `backend/app/models/assistant.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/services/migrate.py`, `backend/app/services/permissions.py`
- Test: `backend/tests/test_wa0_assistant_models.py`
- Docs: `docs/04-数据模型设计.md`, `docs/en/04-data-model.md`, `docs/06-用户身份与组织模型设计.md`, `docs/en/06-identity-and-org-model.md`

**Interfaces:**
- Produces: `AiProviderConfig`, `AiAgentProfile`, `AiAgentProfileVersion`, `AiConversation`, `AiMessage`, `AiAction`, `AiProviderCall`；权限模块 `admin_ai`。
- Consumes: `GlidBase`, `JsonCol`, `AuthUser`, 当前启动时 `run_migrations()` 机制。

- [ ] **Step 1: 写失败测试，证明新表、唯一约束和默认关闭状态不存在**

```python
def test_wa0_models_are_additive_and_disabled_by_default(client):
    from app.models import AiAgentProfile, AiProviderConfig
    from app.db import SessionLocal
    with SessionLocal() as db:
        provider = AiProviderConfig(code="primary", name="Primary", provider_type="openai_compatible")
        profile = AiAgentProfile(code="requester", audience="requester")
        db.add_all([provider, profile]); db.commit()
        assert provider.enabled is False
        assert profile.enabled is False
```

Run: `cd backend && python -m pytest tests/test_wa0_assistant_models.py -q`
Expected: FAIL，因为模型尚不存在。

- [ ] **Step 2: 创建聚焦模型及约束**

```python
class AiAction(GlidBase):
    __tablename__ = "ai_action"
    __table_args__ = (UniqueConstraint("auth_user_id", "capability_code", "idempotency_key"),)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("ai_conversation.id"), index=True)
    auth_user_id: Mapped[str] = mapped_column(ForeignKey("auth_user.id"), index=True)
    capability_code: Mapped[str] = mapped_column(String(96), index=True)
    risk_level: Mapped[str] = mapped_column(String(2))
    normalized_payload: Mapped[dict] = mapped_column(JsonCol, default=dict)
    payload_digest: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(16), default="prepared", index=True)
```

其余模型按设计基线保存加密密钥、能力探测、档案版本、会话归属、脱敏消息、调用耗时与结果码；所有外键、查询索引和状态字段显式定义。

- [ ] **Step 3: 增加 PostgreSQL 幂等增量迁移**

在 `run_migrations()` 中增加 `ensure_assistant_schema(db)`：只执行 `CREATE TABLE IF NOT EXISTS`、缺列补齐和 `CREATE INDEX IF NOT EXISTS`；SQLite 继续由 `Base.metadata.create_all()` 建表。测试同时保存一条既有 `Ticket`，迁移后断言编号、状态和请求数据未变化。

- [ ] **Step 4: 增加 `admin_ai` 权限模块**

```python
MODULES.append(("admin_ai", "AI 智能体", "系统管理"))
```

只允许 admin 通过隐式全权访问；不把 `admin_ai` 写入 requester、BDO、IT 员工或 auditor 默认矩阵。

- [ ] **Step 5: 运行模型测试和完整后端回归**

Run: `cd backend && python -m pytest tests/test_wa0_assistant_models.py -q && python -m pytest -q`
Expected: 全部 PASS。

- [ ] **Step 6: 同步中英文数据与身份文档并提交**

```bash
git add backend/app/models/assistant.py backend/app/models/__init__.py backend/app/services/migrate.py backend/app/services/permissions.py backend/tests/test_wa0_assistant_models.py docs/04-数据模型设计.md docs/06-用户身份与组织模型设计.md docs/en/04-data-model.md docs/en/06-identity-and-org-model.md
git commit -m "feat(agent): add WA0 persistence foundation"
```

---

### Task 2: WA0 脱敏、能力注册与动态策略裁剪

**Files:**
- Create: `backend/app/assistant/__init__.py`, `types.py`, `redaction.py`, `registry.py`, `policy.py`
- Test: `backend/tests/test_wa0_assistant_policy.py`, `backend/tests/test_wa0_assistant_redaction.py`
- Docs: `docs/05-API契约与架构设计.md`, `docs/en/05-api-and-architecture.md`, `docs/06-用户身份与组织模型设计.md`, `docs/en/06-identity-and-org-model.md`

**Interfaces:**
- Produces: `RiskLevel`, `AssistantChannel`, `CapabilityDefinition`, `CapabilityContext`, `CapabilityResult`, `register_capability()`, `capabilities_for_user()`、`redact_for_model()`。
- Consumes: `effective_roles()`, `user_permissions()`, `has_perm()`；不接收前端传入角色。

- [ ] **Step 1: 写角色直授、组授予、auditor 和 requester 隔离失败测试**

```python
def test_requester_never_discovers_internal_capability(client, requester_user):
    codes = {c.code for c in capabilities_for_user(db, requester_user, channel="web", max_risk="L3")}
    assert "service_request.prepare" in codes
    assert "incident.create" not in codes
    assert "process_task.complete" not in codes
```

同时测试 BDO 只增加需求能力、组授予 IT 角色生效、仅 auditor 用户不发现 L2/L3、管理员也不能发现 L4。

- [ ] **Step 2: 定义固定能力契约**

```python
@dataclass(frozen=True)
class CapabilityDefinition:
    code: str
    channels: frozenset[AssistantChannel]
    audiences: frozenset[str]
    module: str | None
    action: str | None
    risk: RiskLevel
    input_model: type[BaseModel]
    handler: Callable[[Session, AuthUser, BaseModel], CapabilityResult]
    requires_confirmation: bool = False
```

注册时拒绝重复 code、L3 未声明确认、L4、无输入模型或无处理器；数据库只能按 code 关闭能力。

- [ ] **Step 3: 实现请求级策略上下文**

`capabilities_for_user()` 每次从数据库重新读取活动账号、`effective_roles`、权限矩阵和档案最高等级；记录级能力在执行时还调用定义内的数据范围/状态/流程检查器。返回给模型的 schema 不包含处理器、内部角色矩阵和禁用能力。

- [ ] **Step 4: 实现三层脱敏并测试**

```python
SENSITIVE_KEYS = {"password", "token", "secret", "cookie", "authorization", "api_key"}

def redact_mapping(value: object, sensitive_fields: set[str] = frozenset()) -> object:
    ...
```

测试大小写、嵌套对象、数组、Bearer 文本、JWT 形态、动态表单 `sensitive=true` 字段；断言原值不出现在模型输入、`AiMessage.content` 和日志摘要。

- [ ] **Step 5: 运行测试、同步架构/身份文档并提交**

Run: `cd backend && python -m pytest tests/test_wa0_assistant_policy.py tests/test_wa0_assistant_redaction.py -q`
Commit: `feat(agent): enforce capability and redaction policy`

---

### Task 3: WA0 OpenAI-compatible 模型网关与安全探测

**Files:**
- Create: `backend/app/assistant/providers/__init__.py`, `base.py`, `openai_compatible.py`, `backend/app/assistant/gateway.py`
- Modify: `backend/app/core/config.py`, `backend/requirements.txt`
- Test: `backend/tests/test_wa0_ai_provider.py`

**Interfaces:**
- Produces: `ProviderProbe`, `ChatRequest`, `ModelStreamEvent`, `ModelProvider.probe()`, `ModelProvider.stream_chat()`、`AssistantGateway.stream()`。
- Consumes: `AiProviderConfig`、`encrypt_secret()/decrypt_secret()`、`httpx.AsyncClient`。

- [ ] **Step 1: 用 `httpx.MockTransport` 写失败测试**

测试 HTTPS/允许主机、无 URL 凭据、超时、401 脱敏、SSE delta、工具调用、JSON Schema、主模型失败后同策略备用模型切换；断言 API Key 不进入异常文本。

- [ ] **Step 2: 增加部署侧允许主机配置**

```python
ai_provider_allowed_hosts: str = ""
ai_provider_connect_timeout_seconds: int = 5
ai_provider_read_timeout_seconds: int = 60
```

`AI_PROVIDER_ALLOWED_HOSTS` 使用逗号分隔精确主机/受控后缀；空列表拒绝保存启用的提供商。URL 必须为 HTTPS、无用户名/密码/查询/片段；解析到 loopback、link-local 或 metadata 地址时拒绝。

- [ ] **Step 3: 实现协议和 OpenAI-compatible 适配器**

```python
class ModelProvider(Protocol):
    async def probe(self) -> ProviderProbe: ...
    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ModelStreamEvent]: ...
```

只支持 `/chat/completions` 兼容结构；未知事件、非法 JSON、缺失 finish reason 均产生安全失败，不尝试猜测业务动作。

- [ ] **Step 4: 实现主备选择和调用审计**

Gateway 只选择 `enabled=True`、最近探测成功且满足请求能力的提供商；L2/L3 请求必须 `supports_tools && supports_json_schema`。每次调用写 `AiProviderCall` 的 provider/model/tokens/latency/result_code/redacted_error，不保存 Prompt 或密钥。

- [ ] **Step 5: 运行专项及完整回归并提交**

Run: `cd backend && python -m pytest tests/test_wa0_ai_provider.py -q && python -m pytest -q`
Commit: `feat(agent): add secure model provider gateway`

---

### Task 4: WA0 管理员提供商与档案版本 API

**Files:**
- Create: `backend/app/services/assistant_config.py`, `backend/app/routers/admin_ai.py`
- Modify: `backend/app/routers/__init__.py`, `backend/app/main.py`
- Test: `backend/tests/test_wa0_ai_admin_api.py`
- Docs: `docs/05-API契约与架构设计.md`, `docs/en/05-api-and-architecture.md`

**Interfaces:**
- Produces: 设计基线中的 `/api/admin/ai/providers`、`profiles/{code}/draft|publish|rollback`、`health|usage|action-audits`。
- Consumes: Task 1 模型、Task 3 gateway、`require_perm("admin_ai", ...)`、`audit()`。

- [ ] **Step 1: 写 API 权限、密钥不回显和发布前探测失败测试**

```python
def test_provider_read_returns_has_secret_not_ciphertext(client, admin_headers):
    row = client.post("/api/admin/ai/providers", headers=admin_headers, json=VALID_PROVIDER).json()["data"]
    assert row["has_secret"] is True
    assert "api_key" not in row and "api_key_encrypted" not in row
```

非 admin 请求全部 403；档案不得启用未注册能力或把 requester 最高等级设为 L4。

- [ ] **Step 2: 实现提供商 CRUD 与探测**

保存新 key 时加密；空 key 保留旧密文；返回只含 `has_secret`。`POST /test` 依次验证鉴权、流式、结构化输出和工具调用，并保存脱敏结果。

- [ ] **Step 3: 实现四类档案草稿、发布和回滚**

预置 code：`requester`、`bdo`、`it_staff`、`admin`。发布时复制不可变 `AiAgentProfileVersion`，校验中英文系统指令、最高风险、注册能力、知识范围和可用提供商；回滚通过复制历史版本生成新的发布版本，不修改历史行。

- [ ] **Step 4: 实现健康、用量和动作审计读接口**

只返回聚合指标和脱敏动作摘要；默认不返回完整会话、Prompt、消息正文、密钥或 normalized payload。

- [ ] **Step 5: 测试、同步 API 文档并提交**

Run: `cd backend && python -m pytest tests/test_wa0_ai_admin_api.py -q`
Commit: `feat(agent): govern providers and agent profiles`

---

### Task 5: WA0 网页会话、消息归属与保留策略

**Files:**
- Create: `backend/app/schemas/assistant.py`, `backend/app/services/assistant_conversations.py`, `backend/app/routers/assistant.py`
- Modify: `backend/app/main.py`, `backend/app/routers/__init__.py`
- Test: `backend/tests/test_wa0_assistant_conversations.py`

**Interfaces:**
- Produces: `bootstrap()`, `create_conversation()`, `list_own_conversations()`, `get_own_conversation()`, `archive_own_conversation()` 和对应 REST API。
- Consumes: 当前 `AuthUser`、已发布档案、Task 2 策略和脱敏。

- [ ] **Step 1: 写本人范围与白名单页面上下文失败测试**

测试用户 A 不能读取/归档用户 B 会话；客户端传入 `roles`、`permissions`、DOM、HTML、任意 URL 或超过 20 个 selected IDs 时返回 422；`route` 只接受站内 `/...`。

- [ ] **Step 2: 定义固定输入输出**

```python
class PageContextIn(BaseModel):
    route: str = Field(pattern=r"^/")
    page_type: str | None = Field(default=None, max_length=48)
    entity_type: str | None = Field(default=None, max_length=32)
    entity_id: str | None = Field(default=None, max_length=26)
    tab: str | None = Field(default=None, max_length=64)
    selected_ids: list[str] = Field(default_factory=list, max_length=20)
```

`bootstrap` 返回 `enabled/profile/max_risk/suggested_prompts/retention_days/fallback_available`，不返回内部权限矩阵或禁用能力。

- [ ] **Step 3: 实现会话生命周期与 0–90 天语义**

0 天表示普通消息正文不落库，只保留会话最小元数据和业务动作审计；1–90 天按 `expires_at` 清理消息。用户归档只影响本人列表，不删除动作审计。

- [ ] **Step 4: 测试并提交**

Run: `cd backend && python -m pytest tests/test_wa0_assistant_conversations.py -q`
Commit: `feat(agent): add owned web conversations`

---

### Task 6: WA0 L3 动作预览、确认、幂等和重授权

**Files:**
- Create: `backend/app/services/assistant_actions.py`
- Modify: `backend/app/routers/assistant.py`
- Test: `backend/tests/test_wa0_assistant_actions.py`

**Interfaces:**
- Produces: `prepare_action(db, actor, conversation_id, capability_code, payload, idempotency_key)`、`confirm_action(...)`、`cancel_action(...)`。
- Consumes: Task 2 注册能力/策略、`AiAction`、领域处理器。

- [ ] **Step 1: 写确认安全矩阵失败测试**

覆盖：他人确认、过期、重复确认、同键同参重试、同键异参冲突、准备后撤权、记录状态变化、取消后确认、auditor 写入、处理器异常不显示成功。

- [ ] **Step 2: 实现规范化摘要和单次 Token**

```python
def prepare_action(...) -> PreparedAction:
    normalized = definition.input_model.model_validate(payload).model_dump(mode="json")
    digest = payload_digest(normalized)
    raw_token = secrets.token_urlsafe(32)
    # 仅保存 sha256(raw_token)，响应一次性返回 raw_token
```

预览来自服务端 handler 的 `preview()`，模型不得自造最终字段、SLA、流程或处理队列。

- [ ] **Step 3: 实现行锁、重授权和事务结果**

确认时 `SELECT ... FOR UPDATE` 先锁动作，再锁定并刷新所属 active 会话，之后才进入 Task 4 governance/provider/profile 锁序；`authorize_record()` 和 mutation 仅接收 `ActionUnitOfWork.lock_one()/update_locked()`、`FrozenActionRecord` 快照和不暴露真实 ORM 身份的 `LockedActionRecord`，预览授权/预览仅接收独立 Session actor 上下文和无 Session-like 属性的 `ReadOnlyActionData`。预览门面递归校验完整 SQLAlchemy AST，只接受单个直接映射表的显式直接标量列、同表安全条件/排序和编译期非负有界 limit/offset，并以固定 max + 1 检测溢出；实体/关系/eager、join/alias/subquery/CTE、聚合/窗口/函数、text/raw SQL、跨表引用、任意层级行锁及动态/负数/超限分页均拒绝。mutation 句柄以模块私有状态绑定精确 UoW、Session、外层事务与 savepoint；成功更新消费旧句柄并返回合并快照的新句柄，伪造、跨范围、事务结束后及重复使用均失败关闭。成功业务写入、`AiAction.succeeded`、结果实体和通用审计在同一事务提交。失败先回滚业务事务，再单独写脱敏失败状态；任何失败响应不得使用“已创建/已关闭”。

Fix Round 2 还要求：准备在预览结束后、动作插入/幂等赢家处理前先 `FOR UPDATE + populate_existing` 锁定并重检所属 active 会话；`archive_own_conversation()` 在提交前同样锁定并刷新所属会话行。

- [ ] **Step 4: 暴露 confirm/cancel API 并测试**

```text
POST /api/assistant/actions/{id}/confirm
POST /api/assistant/actions/{id}/cancel
```

Run: `cd backend && python -m pytest tests/test_wa0_assistant_actions.py -q`
Commit: `feat(agent): enforce confirmed assistant actions`

---

### Task 7: WA0 编排器、工具循环和 POST-SSE

**Files:**
- Create: `backend/app/assistant/orchestrator.py`
- Modify: `backend/app/routers/assistant.py`
- Test: `backend/tests/test_wa0_assistant_stream.py`, `backend/tests/test_wa0_prompt_boundary.py`

**Interfaces:**
- Produces: `AssistantOrchestrator.stream_turn()`；SSE 事件 `meta|delta|message|action|error|done`。
- Consumes: gateway、当前档案、能力 schema、会话服务、动作服务。

- [ ] **Step 1: 创建 FakeProvider 并写流式契约失败测试**

```python
events = client.post(
    f"/api/assistant/conversations/{conversation_id}/messages",
    headers=headers,
    json={"content": "帮我查自己的工单", "client_message_id": "msg-001", "page_context": {"route": "/itsm/tickets"}},
)
assert response.headers["content-type"].startswith("text/event-stream")
assert event_types(events) == ["meta", "delta", "message", "done"]
```

另测断流、非法工具 code、非法参数、超出 4 次工具循环、模型声称成功但服务端没有结果、Prompt 注入要求泄露系统指令。

- [ ] **Step 2: 固定 SSE 事件契约**

```text
event: meta    data: {conversation_id,user_message_id,assistant_message_id}
event: delta   data: {text}
event: message data: {message}
event: action  data: {action_id,risk,preview,confirmation_token,expires_at}
event: error   data: {code,message,retryable,fallback_path?}
event: done    data: {finish_reason}
```

- [ ] **Step 3: 实现严格提示分层与工具循环**

系统指令、档案指令、已授权能力 schema、安全知识和用户输入分别构造；知识和业务正文用“不可信上下文”边界包裹。工具调用只按 code 查注册表并再次鉴权；L3 只返回 action 预览，绝不在流式生成过程中直接执行。

- [ ] **Step 4: 实现断流与降级**

客户端断开即取消模型请求；已准备动作保持 `prepared` 直到过期但不会执行。无可用模型、超时或非法输出返回规则指引/原生路径，不把 provider 错误原文返回用户。

- [ ] **Step 5: 测试并提交**

Run: `cd backend && python -m pytest tests/test_wa0_assistant_stream.py tests/test_wa0_prompt_boundary.py -q`
Commit: `feat(agent): stream guarded assistant turns`

---

### Task 8: WA0 网页助手外壳与管理员 AI 页面

**Files:**
- Create: 前端新增文件结构中列出的 9 个文件
- Modify: `frontend/src/api/types.ts`, `router.tsx`, `components/MainLayout.tsx`, `components/menu.tsx`, `styles.css`, `i18n/index.ts`, `i18n/dict.ts`, `i18n/locales/admin.ts`
- Test: TypeScript/Vite build；IDC 浏览器 UAT 在 Task 9。

**Interfaces:**
- Produces: 全登录用户助手入口、抽屉、消息流、动作卡、`/admin/ai-assistant` 管理页。
- Consumes: Tasks 4–7 API 和 SSE 契约。

- [ ] **Step 1: 定义前端类型和 POST-SSE 客户端**

```ts
export type AssistantStreamEvent =
  | { type: 'delta'; data: { text: string } }
  | { type: 'action'; data: AssistantActionPreview }
  | { type: 'error'; data: { code: string; message: string; retryable: boolean; fallback_path?: string } }
  | { type: 'done'; data: { finish_reason: string } };
```

`streamAssistantMessage()` 从 Zustand 读取 token、从语言 store 读取 X-Lang，使用 `fetch` 发送 POST 并按空行解析 SSE；401 执行现有 logout 行为。

- [ ] **Step 2: 接入全局入口和白名单上下文**

业务门户和内部工作台均渲染 `AssistantLauncher`。上下文只由 router location 和页面显式注册值构造，禁止读取 DOM。桌面宽 480px，窄屏 `width="100%"`；原生页面始终可用。

- [ ] **Step 3: 实现消息和动作交互**

结构化展示规则来源、跳转按钮、缺失字段、预览和服务端结果；L3 卡片必须点击“确认执行”，取消/过期/状态冲突均禁用按钮。流中断只显示“未执行任何操作”。

- [ ] **Step 4: 实现管理员页面和权限菜单**

管理页包含提供商、档案、运行状态、用量、动作审计五个标签；Secret 输入只写不读。菜单绑定 `admin_ai`，路由即使直接访问也由后端 403 兜底。

- [ ] **Step 5: 完成中英文文案和生产构建**

Run: `cd frontend && npm run build`
Expected: TypeScript 0 错误、Vite 成功。

- [ ] **Step 6: 提交前端 WA0**

Commit: `feat(agent): add web assistant and admin console`

---

### Task 9: WA0 文档、完整回归、IDC 部署与基础验收

**Files:**
- Modify: `README.md`, `docs/03-PRD.md`, `04-数据模型设计.md`, `05-API契约与架构设计.md`, `06-用户身份与组织模型设计.md`, `10-Aily-MCP版本交接与决策上下文.md` 及全部对应 `docs/en/`

**Interfaces:**
- Produces: 可配置但默认关闭的 WA0 生产基础。

- [ ] **Step 1: 文档标记 WA0 已实现并逐字段核对 API/模型/权限**

不得把 WA1–WA4 写成已实现；记录 `AI_PROVIDER_ALLOWED_HOSTS`、密钥不回显、保留 0–90 天和回滚方式。

- [ ] **Step 2: 运行本地质量门禁并提交**

```bash
cd backend && python -m pytest -q
cd ../frontend && npm run build
cd .. && git diff --check
git commit -m "docs(agent): complete WA0 delivery contract"
git push origin feature/AI-agent-version
```

- [ ] **Step 3: 等待 GitHub Actions 全绿，再构建部署不可变镜像**

```bash
cd deploy/k8s
./push-images.sh
./k8s-deploy.sh
```

Expected: linux/amd64、rollout、Ready Endpoint、镜像身份、前端→后端 `/api/health`、外部健康和 MCP initialize 全部通过。

- [ ] **Step 4: IDC WA0 UAT**

验证：默认无已发布档案时入口安全不可用；管理员配置允许的模型后探测通过；API Key 不回显；发布/回滚四类档案；requester/BDO/IT/admin bootstrap 不混淆；模型断开时原生页面和“创建单据指引”仍可用；既有 Aily 创建/查询工具不变。

---

### Task 10: WA1 模块说明、单据判断、导航和安全知识

**Files:**
- Create: `backend/app/assistant/capabilities/guidance.py`, `backend/app/services/assistant_knowledge.py`
- Modify: `backend/app/services/it_document_guide.py`
- Test: `backend/tests/test_wa1_guidance.py`, `backend/tests/test_wa1_knowledge.py`
- Docs: PRD/API 中英文镜像

**Interfaces:**
- Produces capabilities: `guide.explain_module`(L0)、`guide.recommend_record_type`(L2)、`navigation.open_page`(L0)、`knowledge.search_published`(L1)。
- Consumes: 现有 `DOCUMENTS`/`recommend_document()`、菜单权限映射、`KnowledgeArticle.status=published`。

- [ ] **Step 1: 写单据定义和知识泄露失败测试**

普通用户描述单人软件故障必须推荐服务请求；描述大范围故障只能提示联系 IT/提交个人服务请求，不能让其创建事件。草稿、内部备注、无 knowledge view 权限、其他用户私有内容不得检索。

- [ ] **Step 2: 将确定性规则注册为能力而不是复制进 Prompt**

```python
register_capability(CapabilityDefinition(
    code="guide.recommend_record_type",
    risk="L2",
    input_model=RecordRecommendationIn,
    handler=recommend_record_type,
))
```

推荐输出包含 `recommended_type/label/reason/counterexample/target_path`；目标路径还要按当前 `view/create` 权限裁剪。

- [ ] **Step 3: 实现安全知识检索**

仅搜索 `status="published" && !is_deleted`，先检查 `knowledge.view`；截断正文、清理 HTML、脱敏后入模，输出文章 code/title/link/snippet，不向模型发送整个知识库。

- [ ] **Step 4: 测试并提交**

Run: `cd backend && python -m pytest tests/test_wa1_guidance.py tests/test_wa1_knowledge.py -q`
Commit: `feat(agent): add governed guidance knowledge`

---

### Task 11: WA1 本人记录、可见记录、待办与下一步解释

**Files:**
- Create: `backend/app/assistant/capabilities/queries.py`
- Modify: 必要的领域查询 service；禁止从 assistant 直接复刻 router 内整段 SQL
- Test: `backend/tests/test_wa1_assistant_queries.py`

**Interfaces:**
- Produces capabilities: `service_request.list_own/get_own`、`requirement.list_own/get_own`、`record.search_visible`、`workflow.list_my_pending`、`workflow.explain_next_step`。
- Consumes: `service_request_intake.own_ticket/ticket_summary`、`requirement_intake.own_requirement/requirement_summary`、`process_engine.can_act_on_task/instance_view`、各域可见性 helper。

- [ ] **Step 1: 写跨用户、跨模块和流程任务隔离测试**

requester 只能查本人服务请求；BDO 只能额外查本人需求；IT 人员查询结果须同时满足模块 view 和领域数据范围；流程待办只包含本人 assignee 或本人有效角色可认领任务；admin 不绕过提交人专属信息边界。

- [ ] **Step 2: 把必要的 router 查询提取为领域查询函数**

函数签名统一为：

```python
def search_visible_records(db: Session, actor: AuthUser, query: RecordSearchIn) -> list[RecordSummary]: ...
def list_actionable_tasks(db: Session, actor: AuthUser, limit: int = 20) -> list[TaskSummary]: ...
```

Router 与 assistant 共同调用；assistant 不直接调用 FastAPI route function。

- [ ] **Step 3: 限制检索规模与返回字段**

单次最多 20 条，只返回 code/title/status/status_name/link/owner/next_step 等允许字段；内部备注、根因、审批意见按角色和记录类型裁剪。

- [ ] **Step 4: 测试并提交**

Run: `cd backend && python -m pytest tests/test_wa1_assistant_queries.py -q`
Commit: `feat(agent): add role scoped assistant queries`

---

### Task 12: WA1 上下文体验、规则降级与 IDC 角色验收

**Files:**
- Modify: `frontend/src/components/assistant/*`, `frontend/src/i18n/locales/assistant.ts`, `README.md` 和 PRD/API/身份中英文文档

**Interfaces:**
- Produces: 可用的只读网页顾问；模型不可用时的确定性规则降级。

- [ ] **Step 1: 增加按页面建议问题和安全跳转**

服务请求页建议“查询我的未关闭请求”，需求页对 BDO 建议“查看我的需求”，内部页面按权限建议待办/模块说明；前端只接受服务端返回且以 `/` 开头的路径。

- [ ] **Step 2: 保留并合并现有 `StaffIntakeDrawer` 规则资产**

助手可用时顶部“创建单据指引”入口并入助手；模型故障时同一入口直接展示现有四个确定性问题和手工选单，不删除 `it_document_guide` API。

- [ ] **Step 3: 运行完整测试/构建、提交、推送和 IDC 部署**

Run: `cd backend && python -m pytest -q && cd ../frontend && npm run build && cd .. && git diff --check`
Deploy: 等质量门禁全绿后运行 `deploy/k8s/push-images.sh` 和同标签 `k8s-deploy.sh`。

- [ ] **Step 4: 多角色 WA1 UAT**

用 requester、BDO、IT 开发、IT 运维、产品经理、管理员、auditor 各验证一次能力清单、本人范围、待办、页面跳转和降级；保存 UAT 记录但不保存真实敏感对话。

---

### Task 13: WA2 普通业务用户服务请求闭环

**Files:**
- Create: `backend/app/assistant/capabilities/service_requests.py`
- Modify: `backend/app/services/service_request_intake.py`, `service_request_closure.py`（仅提取共同无提交入口时）
- Test: `backend/tests/test_wa2_assistant_service_requests.py`
- Frontend: `AssistantActionCard.tsx`, `AssistantMessageList.tsx`

**Interfaces:**
- Produces: `service_item.search` L1、`service_item.get_form` L1、`service_request.prepare` L2、`service_request.submit` L3、`service_request.confirm_resolution` L3、`service_request.rate` L3。
- Consumes: 现有 Aily P1/P2 领域服务；不得复制表单、SLA、派单、确认或评价规则。

- [ ] **Step 1: 写普通用户正反向闭环失败测试**

覆盖实时服务项、动态必填字段、类型/长度/选项/日期/人员范围、真实 SLA/流程/队列预览、确认提交、本人查询、补充、确认关闭/重开、1–5 星评价；普通用户尝试需求/事件/他人工单必须 403。

- [ ] **Step 2: 注册只调用既有领域服务的能力**

```python
def preview_service_request(db, actor, data):
    return service_request_intake.prepare_request(db, actor, data.service_item_id, data.answers, data.idempotency_key)
```

网页 `AiAction` 管确认；领域服务仍生成最终真实预览和业务记录。成功后返回 ticket id/code/link/status，前端不得根据模型文本推断成功。

- [ ] **Step 3: 支持缺失字段追问和结构化按钮**

模型只追问服务端返回的必填缺失字段；枚举、人员和日期使用按钮/选择器，不要求用户手输固定选项。确认关闭、重开和星级使用动作卡。

- [ ] **Step 4: 运行 WA2 与 Aily P1/P2 回归并提交**

Run: `cd backend && python -m pytest tests/test_wa2_assistant_service_requests.py tests/test_m81_aily_mcp_p1.py tests/test_m82_aily_mcp_p2.py tests/test_m83_feishu_card_callbacks.py -q`
Commit: `feat(agent): close requester service loop`

---

### Task 14: WA2 BDO 需求闭环与阶段验收

**Files:**
- Create: `backend/app/assistant/capabilities/requirements.py`
- Modify: `backend/app/services/requirement_intake.py`（仅共同入口）
- Test: `backend/tests/test_wa2_assistant_requirements.py`
- Docs: PRD/API/身份/README 中英文镜像

**Interfaces:**
- Produces: `requirement.get_form` L1、`requirement.prepare` L2、`requirement.submit` L3、`requirement.list_own/get_own` L1。
- Consumes: `ensure_registration_authorized()` 和现有需求领域服务。

- [ ] **Step 1: 写 BDO 与 requester 边界失败测试**

BDO 可取得真实表单、预览、确认登记和查询本人需求；requester 即便管理员在档案中误启用 capability 也不能发现/执行；BDO 不能评审、转项目、查看任务跟踪或他人需求。

- [ ] **Step 2: 注册需求能力并复用现有确认/幂等语义**

服务端预览返回业务域、目标、期望日期和实际流程；确认后调用 `register_requirement()`，返回 requirement code/link/status。

- [ ] **Step 3: 完整回归、文档、提交、推送和 IDC 部署**

Run: `cd backend && python -m pytest -q && cd ../frontend && npm run build && cd .. && git diff --check`。

- [ ] **Step 4: IDC WA2 UAT**

requester 完成一次“描述→服务项选择→缺失必填→预览→确认→ITOM 入单→查询”；BDO 完成一次需求登记；再验证 requester 被拒绝需求、Aily 原有服务请求/BDO 需求链路均不变。

---

### Task 15: WA3 将高频写操作收敛为共同领域动作

**Files:**
- Create: `backend/app/services/process_actions.py`, `ticket_actions.py`, `record_conversion.py`
- Modify: `backend/app/routers/process.py`, `tickets.py`, `record_relations.py`
- Test: `backend/tests/test_wa3_shared_domain_actions.py` 及既有 M18/M20/M25/M28/M31/M84 回归

**Interfaces:**
- Produces: `complete/approve/reject/reassign_process_task()`、`assign/transition_ticket()`、`prepare/submit_record_conversion()`。
- Consumes: 当前 route 中的真实守卫、`process_engine`、`tickets`、`record_relations` 和 audit。

- [ ] **Step 1: 先写路由与服务等价失败测试**

对同一 actor/记录/参数，原 API 与新 service 必须产生同样成功结果或同样错误 code；覆盖当前处理人、默认角色认领、审批节点、提交人确认、终态、状态白名单和关联幂等。

- [ ] **Step 2: 把授权和事务从 router 移入共同领域入口**

```python
def complete_process_task(db: Session, actor: AuthUser, task_id: str, comment: str) -> dict:
    require_task_operator(db, actor, task_id)
    ...
```

Router 只做 Pydantic 解析和 `ok()` 包装；网页助手调用相同函数。不得从 assistant 调用带 `Depends` 的 route function。

- [ ] **Step 3: 保持提交边界可组合**

共同函数默认不自行 `db.commit()`，由 API 或 `assistant_actions.confirm_action()` 在完成业务写入、动作状态和审计后统一提交；异常统一回滚。

- [ ] **Step 4: 运行高风险回归并提交**

Run: `cd backend && python -m pytest tests/test_wa3_shared_domain_actions.py tests/test_m18_task_guard.py tests/test_m20_ticket_admin_ops.py tests/test_m25_flow_operator.py tests/test_m28_close_policy.py tests/test_m30_button_consistency.py tests/test_m84_record_relations.py -q`
Commit: `refactor(domain): share guarded workflow actions`

---

### Task 16: WA3 IT 员工受控写能力、前端与验收

**Files:**
- Create: `backend/app/assistant/capabilities/it_operations.py`
- Modify: `backend/app/assistant/registry.py`, assistant 前端组件
- Test: `backend/tests/test_wa3_it_capabilities.py`
- Docs: 全部受影响中英文权威文档

**Interfaces:**
- Produces L3 capabilities: `record.convert_and_link`、`process_task.complete/approve/reject/reassign`、`ticket.assign/transition`、`bug.create/confirm/create_fix_tasks/verify`、`work_task.create/update/transition`。
- Consumes: Task 15 共同动作、`task_management` 领域服务；不注册删除、权限、流程定义或批量操作。

- [ ] **Step 1: 写角色、流程处理人和状态矩阵失败测试**

IT 开发不能执行产品经理 Bug 确认；产品经理不能代替开发人员完成修复；开发负责人只能在对应节点派单；非当前处理人不能完成流程；管理员也受提交人确认等硬规则；权限撤销后已生成 action 确认必须失败。

- [ ] **Step 2: 注册每个独立 L3 能力和服务端预览**

每项能力定义独立 input model、模块动作、状态检查、流程检查、preview、handler 和审计；不创建“万能更新单据”能力。

- [ ] **Step 3: 前端按结构化 schema 展示必要字段**

派单使用人员选择，状态使用允许目标按钮，Bug 修复任务支持多行预览但一次确认，关联建单展示来源、目标类型、真实目标表单和关系原因。所有动作均可取消。

- [ ] **Step 4: 完整测试、构建、文档、提交和部署**

Run: `cd backend && python -m pytest -q && cd ../frontend && npm run build && cd .. && git diff --check`。

- [ ] **Step 5: IDC WA3 多角色 UAT**

至少完成：服务请求→事件关联、事件→问题或变更关联、本人流程任务完成、合法派单、Bug 登记→确认→派修复→修复→产品经理验证、委派任务登记→排期→执行→关闭；每个反向越权场景返回明确拒绝且无业务写入。

---

### Task 17: WA4 保留清理、运行指标、场景评估和知识治理

**Files:**
- Create: `backend/app/assistant/evaluation.py`
- Modify: `backend/app/services/scheduler.py`, `assistant_conversations.py`, `assistant_config.py`, `backend/app/routers/admin_ai.py`, `frontend/src/pages/admin/AiAssistant.tsx`
- Test: `backend/tests/test_wa4_assistant_governance.py`
- Docs: PRD/API/数据模型/README 中英文镜像

**Interfaces:**
- Produces: 定时清理、health/usage/action-audits 聚合、受控评估集执行和模型比较。
- Consumes: `AiProviderCall.purpose/scenario_code`、`AiAction`、档案发布版本和已发布知识。

- [ ] **Step 1: 写保留和指标准确性失败测试**

0 天消息不落正文；过期消息清理但业务 action/audit 保留；用量按 provider/model/profile/version/result 汇总；失败率、P50/P95、token 和费用不混入 Aily MCP 审计。

- [ ] **Step 2: 实现幂等清理任务**

Scheduler 每日按 profile retention 删除/脱敏过期 `AiMessage`，归档空会话；每批最多 500 行并提交，重复执行结果稳定，不删除 `AiAction` 和通用 `AuditLog`。

- [ ] **Step 3: 实现场景评估而不触发业务写入**

评估集覆盖 ITIL 分类、角色能力隔离、提示注入、缺失字段追问和规则降级；仅允许 L0–L2 或 L3 preview，禁止 confirm。结果以 `purpose="evaluation"` 和 `scenario_code` 写调用审计，比较模型准确率、时延、结构合规率和成本。

- [ ] **Step 4: 增加管理员治理视图**

展示健康、最近错误码、用量、时延、失败率、场景结果、知识命中和动作成功/拒绝；不把模型得分当作业务 UAT 通过条件。

- [ ] **Step 5: 测试、文档、提交、推送和 IDC 部署**

Run: 完整 pytest、前端 build、`git diff --check`；质量门禁全绿后使用不可变镜像部署并验证清理、指标和评估均不影响 Aily 与原生页面。

---

### Task 18: 全量安全回归、恢复演练、用户验收与 PR

**Files:**
- Modify only if evidence reveals a defect: implementation、对应测试及中英文文档必须同改。
- Evidence: `docs/` 下新增本次 WA0–WA4 UAT 记录及 `docs/en/` 镜像。

**Interfaces:**
- Produces: 可提交 PR 的完整网页智能体版本；不直接合入 main。

- [ ] **Step 1: 运行完整自动化和静态交付检查**

```bash
cd backend && python -m pytest -q
cd ../frontend && npm run build
cd ..
git diff --check
bash -n deploy/k8s/push-images.sh deploy/k8s/k8s-deploy.sh
```

Expected: 全部成功。

- [ ] **Step 2: 执行安全负向清单**

验证越权读取、越权写入、前端伪造角色、提示注入、工具 code 注入、SSRF、密钥回显、跨会话、过期确认、重复确认、同键异参、流式断开、模型错误成功宣称、auditor 写入、管理员突破业务硬规则均被拒绝且可审计。

- [ ] **Step 3: 执行 IDC 恢复演练**

记录当前新镜像和 Task 0 已保存的上一稳定不可变镜像标签；将该实际标签赋给 `TAG` 后执行 `./k8s-deploy.sh`，验证应用可回滚、新增表保留且旧版本可忽略，既有业务数据、Secret、PVC、上传和 Aily 配置未丢失。数据库恢复只在批准的隔离恢复验证中执行，不覆盖在线数据。

- [ ] **Step 4: 用户参与的业务 UAT**

由真实 requester、BDO、至少三种 IT 角色和 admin 验证 WA0–WA4；每个场景记录预期、实际、业务实体编号、审计编号和结论。模型指标不能替代业务闭环证据。

- [ ] **Step 5: 创建 feature → main PR，等待用户批准**

```bash
git status --short
git push origin feature/AI-agent-version
gh pr create --base main --head feature/AI-agent-version \
  --title "feat: add governed ITOM web assistant" \
  --body "Implements WA0-WA4 from the approved ITOM web-agent design baseline. Includes additive migrations, role-aware capability isolation, explicit-confirmation writes, full automated regression, IDC UAT, Aily MCP regression, and rollback evidence. Feishu Approval P3 remains deferred."
```

PR 必须说明迁移、权限、密钥、回滚、自动化、IDC UAT、Aily 回归和未实施项；未经用户批准不得 merge。

## 设计基线覆盖自检

| 设计基线章节 | 落地任务 | 覆盖结论 |
|---|---|---|
| §1、§3、§7 目标、入口与分层 | Task 5、7、8、12 | 会话、编排、全局入口、上下文入口和四级能力分层均有实现与验收步骤 |
| §2 安全与系统记录边界 | Task 0、2、6、7、15、18 | ITOM 权限、领域服务、审计、显式确认、幂等和恢复演练形成闭环 |
| §4 角色能力矩阵 | Task 2、11、13、14、16 | requester、BDO、IT、admin、auditor 的服务端能力边界分别测试 |
| §5、§6 业务规则与写操作 | Task 2、6、16 | 审批节点、执行节点、负责人边界、预览和确认令牌均由服务端校验 |
| §8 模型与管理员配置 | Task 3、4、8、17 | Provider、Profile、密钥、探测、评估和治理页面完整覆盖 |
| §9、§10 数据与生命周期 | Task 1、5、17 | 新增模型、增量迁移、保留策略、清理和审计保留均有验证 |
| §11 接口与流式协议 | Task 4、5、6、7 | 管理接口、会话接口、确认接口和 SSE 事件契约均有测试 |
| §12 失败与降级 | Task 2、3、6、7、12、18 | 无模型、超时、断流、工具失败、配置错误和确定性指引回退均被覆盖 |
| §13 分阶段路线图 | Task 1–17 | WA0–WA4 按检查点拆分，禁止跨阶段一次性开放 |
| §14 验收标准 | Task 9、12、14、16–18 | 自动化、IDC 多角色 UAT、Aily 回归、安全负向和回滚证据共同验收 |

## 执行节奏与停止条件

- 推荐按 WA0、WA1、WA2、WA3、WA4 五个检查点执行；每个检查点部署 IDC 并由用户确认后再进入下一阶段。
- 任一阶段出现历史业务数据变化、Aily MCP 回归、越权、密钥回显、无法回滚、迁移失败、IDC 健康失败或质量门禁失败，立即停止后续阶段。
- 第一轮实现只执行 WA0；不要在一个开发批次中同时开放 WA1–WA4。
- P3 飞书审批保持暂缓，不借网页智能体任务顺带实施。
