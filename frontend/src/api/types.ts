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

/** 总览看板 */
export interface DashboardData {
  service: {
    open_tickets: number;
    open_by_priority?: { P1: number; P2: number; P3: number; P4: number };
    sla_rate: number;
    change_success_rate: number;
    problem_close_rate: number;
  };
  project: {
    active: number;
    health: { green: number; yellow: number; red: number };
    overdue_milestones: number;
    budget_usage: number;
  };
  requirement: {
    by_stage: { registered: number; analyzing: number; implementing: number; closed: number };
    avg_lead_days: number;
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
}

// ============ M3 知识库 ============

export type KnowledgeStatus = 'draft' | 'published';

/** 知识文章列表行 */
export interface KnowledgeRow {
  id: string;
  article_code: string;
  title: string;
  tags: string[];
  status: KnowledgeStatus;
  author_name: string | null;
  view_count: number;
  helpful_count: number;
  created_at: string;
  updated_at: string;
}

/** 知识文章详情 */
export interface KnowledgeDetail extends KnowledgeRow {
  content: string;
  /** 作者 auth_user.id，用于编辑权判断 */
  author?: string | null;
  linked_tickets: LinkedTicketBrief[];
  voted: boolean;
}

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
