/** 后端统一响应包 */
export interface Envelope<T = unknown> {
  success: boolean;
  data: T;
  total?: number;
  page?: number;
  error?: { code: string; message: string };
}

/** 系统角色 */
export type Role =
  | 'admin'
  | 'manager'
  | 'it_pdm'
  | 'it_pm'
  | 'it_dev'
  | 'it_ops'
  | 'is_mgr'
  | 'it_bp'
  | 'requester';

export const ROLE_LABELS: Record<Role, string> = {
  admin: '系统管理员',
  manager: '团队负责人',
  it_pdm: 'IT产品经理',
  it_pm: 'IT项目经理',
  it_dev: 'IT开发',
  it_ops: 'IT运维',
  is_mgr: '信息安全管理员',
  it_bp: 'IT业务合作伙伴',
  requester: '业务用户',
};

export const ALL_ROLES = Object.keys(ROLE_LABELS) as Role[];

/** 登录用户 */
export interface AuthUser {
  id: string;
  username: string;
  name: string;
  roles: Role[];
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
  last_login_at?: string | null;
}

/** 人员主数据 */
export interface Member {
  id: string;
  name: string;
  dept?: string | null;
  team?: string | null;
  position_id?: string | null;
  status?: '在岗' | '离职' | null;
  hire_date?: string | null;
  email?: string | null;
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
