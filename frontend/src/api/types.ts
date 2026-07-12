/** 后端统一响应包 */
export interface Envelope<T = unknown> {
  success: boolean;
  data: T;
  total?: number;
  page?: number;
  error?: { code: string; message: string };
}

/** 系统角色（13 个内置角色，矩阵式 IT 组织） */
export type Role =
  | 'admin'
  | 'cio'
  | 'it_bm'
  | 'it_tm'
  | 'it_pdm'
  | 'it_pm'
  | 'it_dev'
  | 'it_ops'
  | 'is_mgr'
  | 'it_bp'
  | 'auditor'
  | 'requester';

export const ROLE_LABELS: Record<Role, string> = {
  admin: '系统管理员',
  cio: 'CIO(IT总负责人)',
  it_bm: 'IT业务线负责人',
  it_tm: 'IT专业线负责人',
  it_pdm: 'IT产品经理',
  it_pm: 'IT项目经理',
  it_dev: 'IT开发',
  it_ops: 'IT运维',
  is_mgr: '信息安全管理员',
  it_bp: 'IT业务合作伙伴',
  auditor: '审计员',
  requester: '业务用户',
};

export const ALL_ROLES = Object.keys(ROLE_LABELS) as Role[];

/** 认证源 */
export type AuthSource = 'local' | 'ad' | 'feishu' | 'sms' | 'wechat';

/** 个人偏好（GET /auth/me 返回；PATCH /auth/me/preferences 更新） */
export interface UserPreferences {
  /** 总览面板 widget 有序列表：数组顺序即显示顺序；缺省或空数组 = 默认顺序全部显示 */
  dashboard_widgets?: string[];
  /** 团队总览页 widget 有序列表；语义同 dashboard_widgets */
  team_overview_widgets?: string[];
}

/** 登录用户 */
export interface AuthUser {
  id: string;
  username: string;
  name: string;
  /** 有效角色 = 直接角色 ∪ 用户组授予 ∪ 继承展开（菜单/权限过滤用它） */
  roles: Role[];
  /** 直接授予的角色（不含组继承） */
  direct_roles?: Role[];
  /**
   * 合并后的功能权限矩阵 {模块: 动作[]}；admin 为 {"*": [四动作]}。
   * 菜单可见性由它驱动；存量会话（未重新登录）可能缺失，此时回退旧的 roles 逻辑。
   */
  permissions?: Record<string, string[]>;
  auth_source?: AuthSource;
  person_id: string | null;
  /** 个人偏好（登录响应不含；进入布局后由 GET /auth/me 刷新写入 store） */
  preferences?: UserPreferences;
}

export interface LoginResult {
  token: string;
  user: AuthUser;
}

/** 系统用户（管理端） */
export interface AdminUser {
  id: string;
  username: string;
  roles: Role[];
  person_id: string | null;
  is_active: boolean;
  auth_source: AuthSource;
  last_login_at?: string | null;
}

/** 人员主数据（人的档案，纯数据零权限） */
export interface Member {
  id: string;
  /** 中文姓名 */
  name: string;
  name_en?: string | null;
  /** 工号 */
  employee_no?: string | null;
  /** 性别：男/女 */
  gender?: string | null;
  birth_date?: string | null;
  /** 用工类型：正式/外包/实习 */
  employment_type?: string | null;
  /** 直属上级（人员主数据 id） */
  supervisor_id?: string | null;
  /** 直属上级姓名（org-tree 接口回显） */
  supervisor_name?: string | null;
  /** 办公地点 */
  work_location?: string | null;
  department_id?: string | null;
  department_name?: string | null;
  position_id?: string | null;
  position_name?: string | null;
  status?: '在岗' | '离职' | null;
  hire_date?: string | null;
  email?: string | null;
  mobile?: string | null;
  /** 同步来源（本地维护为空） */
  external_source?: string | null;
  skills?: string[] | null;
  remarks?: string | null;
}

/** 岗位 */
export interface Position {
  id: string;
  name: string;
  duties?: string | null;
  headcount?: number | null;
}

/** 数据字典条目 */
export interface MasterDataItem {
  id: string;
  category: string;
  code: string;
  name: string;
  sort?: number | null;
  active: boolean;
}

/** 审计日志 */
export interface AuditLog {
  id: string;
  entity_type: string;
  entity_id: string;
  action: string;
  actor_name: string;
  summary: string;
  created_at: string;
}

/** 通知 */
export interface NotificationItem {
  id: string;
  title: string;
  content: string;
  link?: string | null;
  read_at?: string | null;
  created_at: string;
}

/** 总览看板：ITSM 四板块（服务工单/变更/事件/问题）独立卡片数据 */
export interface ItsmBlocks {
  service_request: { open: number; month_resolved: number; sla_rate: number | null };
  change: { pending_approval: number; implementing: number; success_rate: number | null };
  incident: { open: number; sla_warned: number; month_resolved: number; sla_rate: number | null };
  problem: { open: number; known_errors: number; close_rate: number | null };
}

/** 总览看板 */
export interface DashboardData {
  service: {
    open_tickets: number;
    open_by_priority?: { P1: number; P2: number; P3: number; P4: number };
    /** 分型统计：服务请求/事件未关闭数、变更待审批/实施中数 */
    by_type?: {
      service_request_open: number;
      incident_open: number;
      change_pending_approval: number;
      change_implementing: number;
    };
    /** ITSM 四板块卡片数据 */
    itsm_blocks?: ItsmBlocks;
    sla_rate: number | null;
    change_success_rate: number | null;
    problem_close_rate: number | null;
    open_problems?: number;
  };
  project: {
    active: number;
    health: { green: number; yellow: number; red: number };
    overdue_milestones: number;
    budget_usage: number | null;
  };
  requirement: {
    by_stage: { registered: number; analyzing: number; implementing: number; closed: number };
    avg_lead_days: number | null;
  };
  team: {
    top_workload: { name: string; value: number }[];
    top_points: { name: string; value: number }[];
    trainings: number;
    hirings: number;
  };
  alerts: { type: string; title: string; link?: string | null }[];
}

// ============ ITSM 工单 ============

export type TicketType = 'incident' | 'service_request' | 'change';
export type TicketPriority = 'P1' | 'P2' | 'P3' | 'P4';

export const TICKET_TYPE_LABELS: Record<TicketType, string> = {
  incident: '事件',
  service_request: '服务请求',
  change: '变更',
};

export const TICKET_TYPE_COLORS: Record<TicketType, string> = {
  incident: 'volcano',
  service_request: 'cyan',
  change: 'purple',
};

export const PRIORITY_COLORS: Record<TicketPriority, string> = {
  P1: 'red',
  P2: 'orange',
  P3: 'blue',
  P4: 'default',
};

/** 工单列表行 */
export interface TicketRow {
  id: string;
  ticket_code: string;
  title: string;
  ticket_type: TicketType;
  priority: TicketPriority;
  status: string;
  status_name: string;
  service_item_id: string | null;
  service_item_name: string | null;
  service_line: string | null;
  submitter_name: string | null;
  submitter_dept: string | null;
  assignee: string | null;
  assignee_name: string | null;
  submitted_at: string;
  sla_resolution_hours: number | null;
  sla_response_met: boolean | null;
  sla_resolution_met: boolean | null;
  sla_warned: boolean;
  satisfaction: number | null;
  /** 示例数据（列表置顶返回，后端强制只读） */
  is_example?: boolean;
}

/** 可执行的状态流转 */
export interface AllowedTransition {
  to: string;
  to_name: string;
}

/** 工单流程步骤 */
export interface ProcessStep {
  seq: number;
  name: string;
  default_role?: string | null;
  /** 知会人（角色 code 或 "group:组码"）：步骤激活时仅收站内通知，不产生任务 */
  cc_roles?: string[];
  autonomy_level?: string | null;
  task_id: string | null;
  task_status: '未开始' | '待处理' | '已完成';
  assignee_name?: string | null;
  due_at?: string | null;
  completed_at?: string | null;
}

/** 工单关联流程实例 */
export interface TicketProcess {
  definition_name: string;
  status: string;
  current_step_seq?: number | null;
  steps: ProcessStep[];
}

/** 工单详情 */
export interface TicketDetail extends TicketRow {
  /** 提交人 auth_user.id，用于满意度评价资格判断 */
  submitter?: string | null;
  description: string;
  remarks?: string | null;
  solution?: string | null;
  root_cause?: string | null;
  closure_code?: string | null;
  change_type?: string | null;
  risk_level?: string | null;
  change_reason?: string | null;
  rollback_plan?: string | null;
  implementation_plan?: string | null;
  planned_start_at?: string | null;
  planned_end_at?: string | null;
  approved_at?: string | null;
  approval_comment?: string | null;
  first_response_at?: string | null;
  resolved_at?: string | null;
  closed_at?: string | null;
  paused_minutes?: number | null;
  reopen_count: number;
  first_time_fix?: boolean | null;
  sla_response_min?: number | null;
  actual_response_min?: number | null;
  actual_resolution_hours?: number | null;
  allowed_transitions: AllowedTransition[];
  process?: TicketProcess | null;
}

// ============ M2.5 自配置：角色 / 用户组 ============

/** 角色定义（13 个内置角色 + 自定义角色） */
export interface RoleDef {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  /** 自定义角色的权限模板（创建时复制其权限矩阵）；内置角色为空 */
  base_role?: Role | null;
  is_builtin: boolean;
  user_count: number;
}

/** 用户组 = 纵向专业线（资源池）：派单/协作单位，owner=TM；人进组自动继承组授予的角色 */
export interface UserGroup {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  /** 组负责人（专业线 TM，人员主数据 id） */
  owner_id?: string | null;
  owner_name?: string | null;
  /** 组授予的角色 code 列表（不允许 admin） */
  roles: string[];
  members: { id: string; name: string }[];
}

// ============ M3.6 功能权限矩阵 ============

/** 权限动作 */
export type PermAction = 'view' | 'create' | 'edit' | 'delete';

export const PERM_ACTION_LABELS: Record<PermAction, string> = {
  view: '可见',
  create: '新建',
  edit: '修改',
  delete: '删除',
};

/** 权限模块注册项（GET /admin/permission-modules） */
export interface PermissionModule {
  code: string;
  name: string;
  /** 分组名：总览/ITSM/项目/需求/流程/团队/系统管理 */
  group: string;
}

/** 某角色在某模块上的权限条目（GET/PUT /admin/permissions） */
export interface RolePermissionEntry {
  role_code: string;
  module: string;
  actions: string[];
}

// ============ M3.5 身份与组织：部门 / 业务域 / 开通规则 ============

/** 部门类型 */
export type DeptType = 'it' | 'business' | 'audit';

export const DEPT_TYPE_LABELS: Record<DeptType, string> = {
  it: 'IT',
  business: '业务',
  audit: '审计',
};

export const DEPT_TYPE_COLORS: Record<DeptType, string> = {
  it: 'blue',
  business: 'green',
  audit: 'orange',
};

/** 部门（公司组织架构，一人一部门，仅数据归属不带权限） */
export interface Department {
  id: string;
  code: string;
  name: string;
  parent_id: string | null;
  dept_type: DeptType;
  sort: number;
  active: boolean;
  /** 同步来源（本地维护为空） */
  external_source?: string | null;
  member_count: number;
}

/** 组织架构树：部门节点（含直属人员，GET /admin/org-tree） */
export interface OrgTreeDept extends Omit<Department, 'member_count'> {
  members: Member[];
}

/** 组织架构树数据（GET /admin/org-tree） */
export interface OrgTreeData {
  company: { name: string; master_data_id: string | null };
  departments: OrgTreeDept[];
  /** 未归属任何部门的人员 */
  unassigned_members: Member[];
  /** 已配置的外部同步源（如 feishu）；空数组=外部同步未配置 */
  sync_sources: string[];
}

/** 业务域 = 横向服务线：owner=BM 总体负责，服务团队为跟随成员（负责人是数据字段而非角色） */
export interface BusinessDomain {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  owner_id?: string | null;
  owner_name?: string | null;
  backup_owner_id?: string | null;
  backup_owner_name?: string | null;
  /** 服务团队成员（跟随该业务线的 BP/开发等） */
  members: { id: string; name: string }[];
  sort: number;
  active: boolean;
}

/** 开通规则匹配类型 */
export type ProvisionMatchType = 'dept_type' | 'department';

export const PROVISION_MATCH_LABELS: Record<ProvisionMatchType, string> = {
  dept_type: '按部门类型',
  department: '按具体部门',
};

/** 开通规则（仅账号首次创建时赋默认角色，之后角色自由增减） */
export interface ProvisionRule {
  id?: string;
  match_type: ProvisionMatchType;
  /** match_type=dept_type 时为 it/business/audit；=department 时为部门 id */
  match_value: string;
  /** 回显用（如部门名） */
  match_label?: string | null;
  default_roles: string[];
  sort: number;
  active: boolean;
}

// ============ M2.5 自配置：状态机 ============

export type WorkflowEntityType = 'ticket' | 'ticket_change';

export const WORKFLOW_ENTITY_LABELS: Record<WorkflowEntityType, string> = {
  ticket: '工单（事件/服务请求）',
  ticket_change: '工单（变更）',
};

/** 状态定义 */
export interface WorkflowStatusDef {
  id?: string;
  entity_type?: WorkflowEntityType;
  code: string;
  name: string;
  is_initial: boolean;
  is_terminal: boolean;
  sort: number;
}

/** 流转规则；allowed_roles 元素 = 角色 code 或 "group:组码"，空数组 = 不限角色 */
export interface WorkflowTransitionDef {
  id?: string;
  entity_type?: WorkflowEntityType;
  from_code: string;
  to_code: string;
  allowed_roles: string[];
}

export interface WorkflowConfig {
  statuses: WorkflowStatusDef[];
  transitions: WorkflowTransitionDef[];
}

// ============ M2.5 自配置：流程定义 ============

export type AutonomyLevel = 'L1' | 'L2' | 'L3' | 'L4';

export const AUTONOMY_LABELS: Record<AutonomyLevel, string> = {
  L1: 'L1 全自动',
  L2: 'L2 自动执行·人工确认',
  L3: 'L3 人工为主·系统辅助',
  L4: 'L4 纯人工',
};

/** 流程步骤定义；default_role = 角色 code 或 "group:组码" */
export interface ProcessStepDef {
  seq: number;
  name: string;
  default_role?: string | null;
  /** 知会人列表（与 default_role 同一词表）：步骤激活时仅通知、不产生任务、不阻塞 */
  cc_roles?: string[];
  autonomy_level: AutonomyLevel;
  sla_hours?: number | null;
  description?: string | null;
}

/** 流程定义 */
export interface ProcessDefinition {
  id: string;
  code: string;
  name: string;
  entity_type: WorkflowEntityType;
  trigger_condition?: Record<string, unknown> | null;
  version: number;
  active: boolean;
  description?: string | null;
  instance_count: number;
  steps_locked: boolean;
  steps: ProcessStepDef[];
}

// ============ 服务目录 ============

export type CatalogTier = 'gold' | 'silver' | 'bronze';

export const TIER_LABELS: Record<CatalogTier, string> = {
  gold: '金牌',
  silver: '银牌',
  bronze: '铜牌',
};

export const TIER_COLORS: Record<CatalogTier, string> = {
  gold: '#d4a017',
  silver: '#8c8c8c',
  bronze: '#cd7f32',
};

/** 服务目录 */
export interface Catalog {
  id: string;
  code: string;
  name: string;
  tier: CatalogTier;
  description?: string | null;
  sort?: number | null;
  status: '上架' | '下架';
  item_count: number;
  /** 示例数据（列表置顶返回，后端强制只读） */
  is_example?: boolean;
}

/** 服务项 */
export interface ServiceItem {
  id: string;
  item_code: string;
  name: string;
  catalog_id: string;
  catalog_name?: string | null;
  service_type?: string | null;
  owner?: string | null;
  owner_name?: string | null;
  description?: string | null;
  sla_response_hours?: number | null;
  sla_resolution_hours?: number | null;
  target_audience?: string | null;
  status: '上架' | '下架';
  /** 示例数据（列表置顶返回，后端强制只读） */
  is_example?: boolean;
}

// ============ SLA ============

/** SLA 策略 */
export interface SlaPolicy {
  id?: string;
  priority: TicketPriority;
  response_minutes: number;
  resolution_hours: number;
  active: boolean;
}

// ============ M3 问题管理 ============

export type ProblemStatus = 'new' | 'analyzing' | 'known_error' | 'resolved' | 'closed';

export const PROBLEM_STATUS_LABELS: Record<ProblemStatus, string> = {
  new: '新建',
  analyzing: '分析中',
  known_error: '已知错误',
  resolved: '已解决',
  closed: '已关闭',
};

/** 问题列表行 */
export interface ProblemRow {
  id: string;
  problem_code: string;
  title: string;
  priority: TicketPriority;
  status: string;
  status_name: string;
  service_item_id: string | null;
  service_item_name: string | null;
  owner: string | null;
  owner_name: string | null;
  linked_ticket_count: number;
  created_at: string;
  /** 示例数据（列表置顶返回，后端强制只读） */
  is_example?: boolean;
}

/** 关联工单摘要 */
export interface LinkedTicketBrief {
  id: string;
  ticket_code: string;
  title: string;
  status?: string;
}

/** 问题详情 */
export interface ProblemDetail extends ProblemRow {
  description: string;
  root_cause?: string | null;
  workaround?: string | null;
  source_ticket_id?: string | null;
  linked_tickets: LinkedTicketBrief[];
  allowed_transitions: AllowedTransition[];
  process?: TicketProcess | null;
}

// ============ M3 CMDB ============

export const CI_STATUS_OPTIONS = ['运行中', '维护中', '已下线'] as const;
export const CI_ENV_OPTIONS = ['生产', '测试', '开发'] as const;
export const CI_RELATION_TYPES = ['运行于', '依赖', '连接'] as const;

export const CI_STATUS_COLORS: Record<string, string> = {
  运行中: 'green',
  维护中: 'orange',
  已下线: 'default',
};

/** 配置项 */
export interface CiRow {
  id: string;
  ci_code: string;
  name: string;
  category: string;
  status: string;
  owner: string | null;
  owner_name: string | null;
  environment: string | null;
  business_owner: string | null;
  vendor_id: string | null;
  vendor_name: string | null;
  description: string | null;
  launch_date: string | null;
  attrs: Record<string, unknown>;
  remarks: string | null;
  /** 示例数据（列表置顶返回，后端强制只读） */
  is_example?: boolean;
}

/** CI 摘要（影响分析中的关联方） */
export interface CiBrief {
  id: string;
  name: string;
  category: string | null;
  status: string | null;
}

/** CI 关系条目 */
export interface CiRelationEntry {
  relation_id: string;
  relation_type: string;
  ci: CiBrief;
}

/** 影响分析结果 */
export interface CiImpact {
  ci: CiRow;
  upstream: CiRelationEntry[];
  downstream: CiRelationEntry[];
  tickets: {
    id: string;
    ticket_code: string;
    title: string;
    status: string;
    priority: TicketPriority;
    submitted_at: string;
  }[];
}

// ============ M3 供应商 / 合同 ============

export type VendorRating = 'A' | 'B' | 'C' | 'D';

export const VENDOR_RATING_COLORS: Record<VendorRating, string> = {
  A: 'green',
  B: 'blue',
  C: 'orange',
  D: 'red',
};

/** 供应商 */
export interface Vendor {
  id: string;
  code: string;
  name: string;
  contact: string | null;
  phone: string | null;
  email: string | null;
  service_scope: string | null;
  rating: VendorRating | null;
  status: '合作中' | '已终止';
  remarks: string | null;
  contract_count: number;
  ci_count: number;
  /** 示例数据（列表置顶返回，后端强制只读） */
  is_example?: boolean;
}

export type ContractStatus = '未生效' | '生效' | '临期' | '已过期';

export const CONTRACT_STATUS_COLORS: Record<ContractStatus, string> = {
  未生效: 'default',
  生效: 'green',
  临期: 'orange',
  已过期: 'red',
};

/** 合同（status/days_to_expiry 为后端计算态） */
export interface Contract {
  id: string;
  code: string;
  name: string;
  vendor_id: string;
  vendor_name: string | null;
  amount_10k: number | null;
  start_date: string;
  end_date: string;
  owner: string | null;
  owner_name: string | null;
  status: ContractStatus;
  remarks: string | null;
  days_to_expiry: number | null;
  /** 示例数据（列表置顶返回，后端强制只读） */
  is_example?: boolean;
}

// ============ M3 知识库 ============

export type KnowledgeStatus = 'draft' | 'published';

/** 知识文章内容格式：markdown=站内编写；html=文档导入（docx/html 转换） */
export type KnowledgeContentFormat = 'markdown' | 'html';

/** 知识文章列表行 */
export interface KnowledgeRow {
  id: string;
  article_code: string;
  title: string;
  tags: string[];
  status: KnowledgeStatus;
  content_format: KnowledgeContentFormat;
  author_name: string | null;
  view_count: number;
  helpful_count: number;
  created_at: string;
  updated_at: string;
  /** 示例数据（列表置顶返回，后端强制只读） */
  is_example?: boolean;
}

/** 知识文章详情 */
export interface KnowledgeDetail extends KnowledgeRow {
  content: string;
  /** 作者 auth_user.id，用于编辑权判断 */
  author?: string | null;
  linked_tickets: LinkedTicketBrief[];
  voted: boolean;
}

/** 知识文档导入结果（POST /knowledge/import，创建为草稿） */
export interface KnowledgeImportResult {
  article_id: string;
  article_code: string;
  title: string;
}

// ============ M3.10 Excel 批量导入 ============

/** Excel 导入失败行（部分成功语义：失败行修正后可重新导入，已入库的行会报「已存在，跳过」） */
export interface ImportFailedRow {
  row: number;
  error: string;
  /** 多 sheet 模板（服务目录）时标记来源工作表 */
  sheet?: string;
}

/** Excel 导入结果；created 为总数或分项计数（目录/服务项、WBS/里程碑等） */
export interface ImportResult {
  created: number | Record<string, number>;
  failed: ImportFailedRow[];
}

// ============ M4 项目管理 ============

/** 项目状态 */
export type ProjectStatus = 'planning' | 'active' | 'paused' | 'completed' | 'closed' | 'cancelled';

/** 项目状态 → 中文名 + Badge 展示（planning 蓝 / active 处理中 / paused 橙 / completed 绿 / closed·cancelled 灰） */
export const PROJECT_STATUS: Record<
  ProjectStatus,
  { label: string; badge: 'default' | 'processing' | 'success' | 'warning'; color?: string }
> = {
  planning: { label: '规划中', badge: 'default', color: 'blue' },
  active: { label: '进行中', badge: 'processing' },
  paused: { label: '已暂停', badge: 'warning', color: 'orange' },
  completed: { label: '已完成', badge: 'success' },
  closed: { label: '已关闭', badge: 'default' },
  cancelled: { label: '已取消', badge: 'default' },
};

/** 项目健康度 */
export type ProjectHealth = 'green' | 'yellow' | 'red';

export const HEALTH_META: Record<ProjectHealth, { color: string; label: string }> = {
  green: { color: '#52c41a', label: '正常' },
  yellow: { color: '#faad14', label: '预警' },
  red: { color: '#ff4d4f', label: '风险' },
};

/** 项目组合 */
export interface Portfolio {
  id: string;
  name: string;
  owner_id: string | null;
  owner_name: string | null;
  year: string | null;
  description: string | null;
  sort: number;
  project_count: number;
  /** 示例数据（列表置顶返回，后端强制只读） */
  is_example?: boolean;
}

/** 项目列表行（含后端实时计算的派生指标） */
export interface ProjectRow {
  id: string;
  project_code: string;
  name: string;
  pm: string;
  pm_name: string | null;
  status: ProjectStatus | string;
  status_name: string;
  planned_start: string;
  planned_end: string;
  actual_start: string | null;
  actual_end: string | null;
  portfolio_id: string | null;
  portfolio_name: string | null;
  budget_10k: number | null;
  latest_update: string | null;
  /** 进度 0-100；无 WBS 任务时为 null */
  progress: number | null;
  planned_progress: number | null;
  spi: number | null;
  cpi: number | null;
  /** 进度偏差（计划-实际，百分点） */
  deviation: number | null;
  health: ProjectHealth;
  actual_cost_10k: number;
  /** 预算执行率 %；无预算时 null */
  budget_usage: number | null;
  task_total: number;
  task_done: number;
  milestone_total: number;
  milestone_overdue: number;
  open_risks: number;
  red_risks: number;
  /** 示例数据（列表置顶返回，后端强制只读） */
  is_example?: boolean;
}

/** 项目详情 */
export interface LinkedRequirementBrief {
  id: string;
  requirement_code: string;
  title: string;
  status: string;
  status_name: string;
  moscow?: string | null;
}

export interface ProjectDetail extends ProjectRow {
  /** 关联需求（需求实现阶段挂接本项目） */
  linked_requirements?: LinkedRequirementBrief[];
  description: string | null;
  service_item_id: string | null;
  allowed_transitions: AllowedTransition[];
  /** 项目流程实例视图（结构同工单流程） */
  process: TicketProcess | null;
  /** 当前用户是否有 projects.edit 权限（写操作按钮显隐） */
  can_edit: boolean;
}

/** WBS 任务状态 */
export type WbsStatus = '未开始' | '进行中' | '已完成';

export const WBS_STATUS_COLORS: Record<WbsStatus, string> = {
  未开始: '#bfbfbf',
  进行中: '#1677ff',
  已完成: '#52c41a',
};

/** WBS 任务 */
export interface WbsTask {
  id: string;
  wbs_code: string;
  name: string;
  parent_task_id: string | null;
  assignee: string;
  assignee_name: string | null;
  start_date: string;
  end_date: string;
  status: WbsStatus;
  completed_at: string | null;
  description: string | null;
  deliverable: string | null;
  predecessor_ids: string[];
  sort: number;
}

/** 里程碑 */
export interface Milestone {
  id: string;
  name: string;
  target_date: string;
  description: string | null;
  achieved_at: string | null;
  overdue: boolean;
}

/** 风险概率/影响档位 */
export type RiskGrade = '高' | '中' | '低';

export const RISK_GRADES: RiskGrade[] = ['高', '中', '低'];

/** 项目风险 */
export interface Risk {
  id: string;
  title: string;
  probability: RiskGrade;
  impact: RiskGrade;
  mitigation: string | null;
  status: '开放' | '已关闭';
}

/** 成本明细 */
export interface CostEntry {
  id: string;
  entry_date: string;
  amount_10k: number;
  note: string | null;
}

/** 章程解析：WBS 草稿行 */
export interface CharterWbsDraft {
  code?: string | null;
  name: string;
  description?: string | null;
  deliverable?: string | null;
  start_date?: string | null;
  end_date?: string | null;
}

/** 章程解析：里程碑草稿行 */
export interface CharterMilestoneDraft {
  name: string;
  target_date?: string | null;
}

/** 章程解析：风险草稿行 */
export interface CharterRiskDraft {
  title: string;
  probability?: string | null;
  impact?: string | null;
  mitigation?: string | null;
}

/** 章程解析结果（POST /projects/charter/parse） */
export interface CharterParseResult {
  fields: {
    name: string | null;
    /** 解析到的项目经理姓名匹配到的人员 id；匹配失败为 null */
    pm: string | null;
    pm_name: string | null;
    planned_start: string | null;
    planned_end: string | null;
    budget_10k: number | null;
    description: string | null;
  };
  drafts: {
    wbs: CharterWbsDraft[];
    milestones: CharterMilestoneDraft[];
    risks: CharterRiskDraft[];
  };
  warnings: string[];
}

/** 章程确认创建结果 */
export interface CharterCreateResult {
  project_id: string;
  project_code: string;
  created: { wbs: number; milestones: number; risks: number };
}

/** 附件条目（GET /attachments） */
export interface AttachmentItem {
  id: string;
  filename: string;
  size: number;
  created_at: string;
}

// ============ M5 需求管理 ============

/** 需求状态 */
export type RequirementStatus =
  | 'registered'
  | 'analyzing'
  | 'implementing'
  | 'closed'
  | 'on_hold'
  | 'cancelled';

/** 需求状态 → 中文名 + Badge 展示（与 PROJECT_STATUS 同构：color 优先于 badge） */
export const REQ_STATUS: Record<
  RequirementStatus,
  { label: string; badge: 'default' | 'processing' | 'success' | 'warning'; color?: string }
> = {
  registered: { label: '已登记', badge: 'default', color: 'blue' },
  analyzing: { label: '分析中', badge: 'processing' },
  implementing: { label: '实现中', badge: 'processing', color: 'purple' },
  closed: { label: '已关闭', badge: 'success' },
  on_hold: { label: '已搁置', badge: 'warning', color: 'orange' },
  cancelled: { label: '已取消', badge: 'default' },
};

/** 需求类型（后端白名单） */
export const REQ_TYPES = ['业务', '功能', '数据', '集成', '合规'] as const;

/** MoSCoW 优先级 */
export type Moscow = 'M' | 'S' | 'C' | 'W';

export const MOSCOW_KEYS: Moscow[] = ['M', 'S', 'C', 'W'];

/** MoSCoW 标签：M红 / S橙 / C蓝 / W灰 */
export const MOSCOW_META: Record<Moscow, { color: string; label: string }> = {
  M: { color: 'red', label: 'M 必须' },
  S: { color: 'orange', label: 'S 应该' },
  C: { color: 'blue', label: 'C 可以' },
  W: { color: 'default', label: 'W 暂缓' },
};

/** 验收标准条目（PATCH acceptance_criteria 时全量提交） */
export interface AcceptanceCriterion {
  text: string;
  checked: boolean;
}

/** 需求任务状态 */
export type RequirementTaskStatus = '待处理' | '进行中' | '已完成';

export const REQ_TASK_STATUSES: RequirementTaskStatus[] = ['待处理', '进行中', '已完成'];

export const REQ_TASK_STATUS_COLORS: Record<RequirementTaskStatus, string> = {
  待处理: 'default',
  进行中: 'processing',
  已完成: 'success',
};

/** 需求任务（实现阶段分解） */
export interface RequirementTask {
  id: string;
  name: string;
  /** 负责人（人员主数据 id） */
  assignee: string;
  assignee_name: string | null;
  plan_date: string | null;
  status: RequirementTaskStatus;
  done_at: string | null;
}

/** 需求列表行 */
export interface RequirementRow {
  id: string;
  requirement_code: string;
  title: string;
  req_type: string;
  business_domain_id: string;
  business_domain_name: string | null;
  source: string | null;
  requester_name: string | null;
  moscow: Moscow | null;
  owner: string | null;
  owner_name: string | null;
  target_date: string | null;
  status: RequirementStatus | string;
  status_name: string;
  registered_at: string;
  closed_at: string | null;
  /** 交付周期（天，closed 后才有） */
  lead_days: number | null;
  project_id: string | null;
  task_total: number;
  task_done: number;
  /** 任务完成比 0-100；无任务时 null */
  progress: number | null;
  /** 示例数据（列表置顶返回，后端强制只读） */
  is_example?: boolean;
}

/** 需求详情 */
export interface RequirementDetail extends RequirementRow {
  description: string;
  solution: string | null;
  acceptance_criteria: AcceptanceCriterion[];
  closure_note: string | null;
  remarks: string | null;
  /** 提出人 auth_user.id */
  requester: string | null;
  analyzing_at: string | null;
  implementing_at: string | null;
  project_name: string | null;
  tasks: RequirementTask[];
  /** 关闭收尾已转出清单 */
  handover: {
    problems: { id: string; problem_code: string; title: string }[];
    articles: { id: string; article_code: string; title: string }[];
  };
  allowed_transitions: AllowedTransition[];
  /** 需求流程实例视图（结构同工单流程） */
  process: TicketProcess | null;
  /** 当前用户是否有 requirements.edit 权限 */
  can_edit: boolean;
}

// ============ M6 团队管理 ============

/** 积分来源类型 → 中文名（自动积分维度） */
export const POINT_SOURCE_LABELS: Record<string, string> = {
  ticket_resolved: '工单解决',
  ticket_sla_met: 'SLA达成',
  ticket_satisfaction: '满意度好评',
  idea_submit: '建言',
  idea_like: '被点赞',
  idea_adopt: '建言采纳',
  wbs_done_on_time: '任务按期',
  milestone_achieved: '里程碑',
  requirement_task_done: '需求任务',
  requirement_closed: '需求交付',
  knowledge_published: '发布知识',
  knowledge_voted: '知识好评',
  training_host: '主讲培训',
  training_attend: '参与培训',
  campaign_award: '专项活动',
};

/** 积分流水条目 */
export interface PointEntryRow {
  id?: string;
  points: number;
  source_type: string;
  period: string;
  note: string | null;
  created_at: string;
}

/** 我的积分（GET /points/mine；未关联人员档案时无 period_total） */
export interface MyPoints {
  period: string;
  period_total?: number;
  total: number;
  entries: PointEntryRow[];
}

/** 本期积分排行榜（GET /points/leaderboard） */
export interface PointsLeaderboard {
  period: string;
  board: { person_name: string | null; points: number }[];
}

/** 积分规则（自动事件分值，可调可停用） */
export interface PointRule {
  code: string;
  name: string;
  points: number;
  active: boolean;
}

/** 建言状态 */
export type IdeaStatus = 'submitted' | 'adopted' | 'implemented' | 'declined';

export const IDEA_STATUS_COLORS: Record<IdeaStatus, string> = {
  submitted: 'processing',
  adopted: 'success',
  implemented: 'blue',
  declined: 'default',
};

/** 建言 */
export interface IdeaRow {
  id: string;
  idea_code: string;
  title: string;
  content: string;
  proposer_name: string | null;
  status: IdeaStatus | string;
  status_name: string;
  like_count: number;
  liked: boolean;
  adopted_at: string | null;
  decline_reason: string | null;
  created_at: string;
  /** 示例数据（列表置顶返回，后端强制只读） */
  is_example?: boolean;
}

/** 专项活动状态 */
export type CampaignStatus = 'draft' | 'active' | 'offline';

export const CAMPAIGN_STATUS_COLORS: Record<CampaignStatus, string> = {
  draft: 'default',
  active: 'green',
  offline: 'red',
};

/** 专项活动激励任务 */
export interface CampaignTaskRow {
  id: string;
  name: string;
  description: string | null;
  points: number;
  /** 每人上限次数；0 = 不限 */
  max_times: number;
}

/** 专项活动列表行 */
export interface CampaignRow {
  id: string;
  name: string;
  description: string | null;
  period_label: string;
  start_date: string;
  end_date: string;
  performance_ratio: number;
  status: CampaignStatus | string;
  status_name: string;
  /** 示例数据（列表置顶返回，后端强制只读） */
  is_example?: boolean;
  total_awarded: number;
  tasks: CampaignTaskRow[];
  my_points?: number;
  my_performance?: number;
}

/** 专项活动发放记录 */
export interface CampaignAwardRow {
  id?: string;
  person_name: string | null;
  task_name: string | null;
  points: number;
  note: string | null;
  created_at: string;
}

/** 专项活动详情（含发放记录与排行榜） */
export interface CampaignDetail extends CampaignRow {
  awards: CampaignAwardRow[];
  leaderboard: { person_name: string | null; points: number; performance: number }[];
  can_manage: boolean;
}

/** 培训发展活动 */
export interface TrainingRow {
  id: string;
  activity_type: string;
  topic: string;
  activity_date: string;
  host_id?: string | null;
  host_name: string | null;
  participant_names: string[];
  output_link: string | null;
  remarks: string | null;
}

/** 团队文化（单例） */
export interface TeamCharterData {
  vision: string | null;
  goals: string | null;
  principles: string | null;
  updated_at: string | null;
}

/** 招聘需求状态 → Tag 颜色 */
export const HIRING_STATUS_COLORS: Record<string, string> = {
  待招聘: 'orange',
  面试中: 'blue',
  已到岗: 'green',
  已取消: 'default',
};

export const HIRING_STATUSES = ['待招聘', '面试中', '已到岗', '已取消'] as const;

/** 招聘级别（与后端白名单一致） */
export const HIRING_LEVELS = ['高级', '中级', '初级'] as const;

export const HIRING_LEVEL_COLORS: Record<string, string> = {
  高级: 'gold',
  中级: 'blue',
  初级: 'default',
};

/** 招聘需求 */
export interface HiringNeedRow {
  id: string;
  position_id: string;
  position_name: string | null;
  /** 级别：高级/中级/初级 */
  level: string;
  headcount: number;
  /** 任职资格（硬性条件与优先项） */
  qualification: string | null;
  status: string;
  progress_note: string | null;
}

/** 团队总览（GET /team/overview） */
export interface TeamOverviewData {
  period: string;
  workload: {
    person_id: string;
    person_name: string;
    tickets: number;
    wbs_tasks: number;
    req_tasks: number;
    total: number;
  }[];
  points_board: { person_name: string | null; points: number }[];
  trainings_month: number;
  active_campaigns: number;
  onboard_count: number;
  open_hirings: number;
}

/** 评分维度（维度库，GET /perf/dimensions） */
export interface PerfDimension {
  code: string;
  name: string;
  /** 公共维度：无贡献计 0 分（非公共维度无数据则不计入、权重自动归一） */
  public: boolean;
  /** 口径说明（v1 默认实现） */
  description: string;
}

/** 计分方案内的维度配置 */
export interface PerfSchemeDimension {
  code: string;
  weight: number;
}

/** 计分方案（GET /perf/schemes） */
export interface PerfScheme {
  id: string;
  name: string;
  description: string | null;
  position_ids: string[];
  position_names: string[];
  dimensions: PerfSchemeDimension[];
  weight_total: number;
  /** 默认兜底方案（全局唯一）：未匹配任何方案的人员按它计分 */
  is_default: boolean;
  active: boolean;
}

/** 加减分事项（POST /perf/adjustments / DELETE /perf/adjustments/{id}） */
export interface PerfAdjustment {
  id: string;
  kind: 'bonus' | 'penalty';
  points: number;
  reason: string;
  created_at: string;
}

/** 维度单元格：score=系统参考值（null=无数据）；override=人工核定分；effective=核定优先的生效值 */
export interface PerfDimCell {
  score: number | null;
  override: number | null;
  effective: number | null;
  weight: number;
}

/** 人效评分行；total = base_score + bonus − penalty（基础分与加减分均无时为 null） */
export interface PerformanceRow {
  person_id: string;
  person_name: string;
  position_name: string | null;
  scheme_id: string | null;
  scheme_name: string | null;
  /** 维度加权基础分；未配置方案或全部维度无数据为 null */
  base_score: number | null;
  /** 加分合计 */
  bonus: number;
  /** 扣分合计 */
  penalty: number;
  /** 本期加减分事项明细 */
  adjustments: PerfAdjustment[];
  total: number | null;
  /** 维度得分，仅含所适用方案配置的维度 */
  dims: Record<string, PerfDimCell>;
}

/** 人效评分（GET /team/performance） */
export interface PerformanceData {
  period: string;
  rows: PerformanceRow[];
  /** 维度库（动态生成列与口径说明） */
  dimensions: PerfDimension[];
  /** 计分公式说明 */
  note: string;
}

/** 流程实例（监控行） */
export interface ProcessInstanceRow {
  id: string;
  definition_name: string;
  entity_type: string;
  entity_id: string;
  status: string;
  current_step: string | null;
  current_assignee: string | null;
  current_due_at: string | null;
  overdue: boolean;
  started_at: string;
  completed_at: string | null;
}

export const PROCESS_INSTANCE_STATUS: Record<string, { label: string; color: string }> = {
  running: { label: '进行中', color: 'processing' },
  completed: { label: '已完成', color: 'success' },
  cancelled: { label: '已取消', color: 'default' },
};

/** 流程实例实体类型 → 中文 */
export const PROCESS_ENTITY_LABELS: Record<string, string> = {
  ticket: '工单',
  ticket_change: '变更',
  problem: '问题',
  project: '项目',
  requirement: '需求',
};

/** SLA 看板 */
export interface SlaDashboard {
  month: string;
  by_priority: Record<TicketPriority, { resolved: number; met: number; rate: number | null }>;
  warning_tickets: {
    id: string;
    ticket_code: string;
    title: string;
    priority: TicketPriority;
    status: string;
    submitted_at: string;
    sla_resolution_hours: number | null;
  }[];
}
