/** 后端统一响应包 */
export interface Envelope<T = unknown> {
  success: boolean;
  data: T;
  total?: number;
  page?: number;
  error?: { code: string; message: string };
}

/** 系统角色 */
export type Role = 'admin' | 'manager' | 'it_pm' | 'it_pjm' | 'it_dev' | 'it_ops' | 'is_mgr' | 'requester';

export const ROLE_LABELS: Record<Role, string> = {
  admin: '系统管理员',
  manager: '团队负责人',
  it_pm: 'IT产品经理',
  it_pjm: 'IT项目经理',
  it_dev: 'IT开发',
  it_ops: 'IT运维',
  is_mgr: '信息安全管理员',
  requester: '业务用户',
};

export const ALL_ROLES = Object.keys(ROLE_LABELS) as Role[];

/** 登录用户 */
export interface AuthUser {
  id: number;
  username: string;
  name: string;
  roles: Role[];
  person_id: number | null;
}

export interface LoginResult {
  token: string;
  user: AuthUser;
}

/** 系统用户（管理端） */
export interface AdminUser {
  id: number;
  username: string;
  roles: Role[];
  person_id: number | null;
  is_active: boolean;
  last_login_at?: string | null;
}

/** 人员主数据 */
export interface Member {
  id: number;
  name: string;
  dept?: string | null;
  team?: string | null;
  position_id?: number | null;
  status?: '在岗' | '离职' | null;
  hire_date?: string | null;
  email?: string | null;
  skills?: string[] | null;
  remarks?: string | null;
}

/** 岗位 */
export interface Position {
  id: number;
  name: string;
  duties?: string | null;
  headcount?: number | null;
}

/** 数据字典条目 */
export interface MasterDataItem {
  id: number;
  category: string;
  code: string;
  name: string;
  sort?: number | null;
  active: boolean;
}

/** 审计日志 */
export interface AuditLog {
  id: number;
  entity_type: string;
  entity_id: number | string;
  action: string;
  actor_name: string;
  summary: string;
  created_at: string;
}

/** 通知 */
export interface NotificationItem {
  id: number;
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
