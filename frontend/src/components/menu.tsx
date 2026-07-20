import type { ReactNode } from 'react';
import {
  ApartmentOutlined,
  CustomerServiceOutlined,
  DashboardOutlined,
  FileTextOutlined,
  ProjectOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import type { AuthUser, Role } from '../api/types';
import { hasAnyRole, hasPermission } from '../stores/auth';
import { useBrandingStore } from '../stores/branding';

export interface MenuNode {
  path?: string; // 叶子节点路由
  key: string;
  label: string;
  icon?: ReactNode;
  /** 功能权限模块码：user.permissions[module] 含 "view"（或 "*" 全权）则可见 */
  module?: string;
  /** 多模块绑定（复合页）：任一模块有 view 权限即可见；与 module 并存时二者取并集 */
  modules?: string[];
  /** 回退角色（仅当存量会话的 user.permissions 缺失时生效） */
  roles?: Role[];
  children?: MenuNode[];
}

/** 除业务用户(requester)之外的内部角色（权限缺失时的回退过滤用） */
const STAFF: Role[] = [
  'admin', 'cio', 'it_bm', 'it_tm',
  'it_pdm', 'it_pm', 'it_dev', 'it_ops', 'is_mgr', 'it_bp',
];

export const MENU_TREE: MenuNode[] = [
  { key: '/dashboard', path: '/dashboard', label: '总览', icon: <DashboardOutlined />, module: 'dashboard' },
  {
    key: 'itsm',
    label: 'ITSM',
    icon: <CustomerServiceOutlined />,
    children: [
      { key: '/itsm/tickets', path: '/itsm/tickets', label: '服务请求', module: 'ticket_sr' },
      { key: '/itsm/catalog', path: '/itsm/catalog', label: '服务目录', module: 'catalog', roles: STAFF },
      { key: '/itsm/cmdb', path: '/itsm/cmdb', label: 'CMDB', module: 'cmdb', roles: STAFF },
      { key: '/itsm/sla', path: '/itsm/sla', label: 'SLA', module: 'sla', roles: STAFF },
      { key: '/itsm/changes', path: '/itsm/changes', label: '变更管理', module: 'ticket_change', roles: STAFF },
      { key: '/itsm/incidents', path: '/itsm/incidents', label: '事件管理', module: 'ticket_incident', roles: STAFF },
      { key: '/itsm/problems', path: '/itsm/problems', label: '问题管理', module: 'problems', roles: STAFF },
      { key: '/itsm/vendors', path: '/itsm/vendors', label: '供应商管理', module: 'vendors', roles: STAFF },
      { key: '/itsm/contracts', path: '/itsm/contracts', label: '合同管理', module: 'contracts', roles: STAFF },
      { key: '/itsm/knowledge', path: '/itsm/knowledge', label: '知识库', module: 'knowledge' },
    ],
  },
  {
    key: 'projects',
    label: '项目管理',
    icon: <ProjectOutlined />,
    roles: STAFF,
    children: [
      { key: '/projects/list', path: '/projects/list', label: '项目列表', module: 'projects' },
      { key: '/projects/portfolios', path: '/projects/portfolios', label: '项目组合', module: 'projects' },
    ],
  },
  {
    key: 'requirements',
    label: '需求管理',
    icon: <FileTextOutlined />,
    children: [
      { key: '/requirements/overview', path: '/requirements/overview', label: '需求总览', module: 'requirements' },
      { key: '/requirements/tasks', path: '/requirements/tasks', label: '任务跟踪', module: 'req_tasks' },
      { key: '/requirements/scoring', path: '/requirements/scoring', label: '评分规则', module: 'req_scoring' },
    ],
  },
  {
    key: 'team',
    label: '团队管理',
    icon: <TeamOutlined />,
    roles: STAFF,
    children: [
      { key: '/team/overview', path: '/team/overview', label: '团队总览', module: 'team_overview' },
      { key: '/team/performance', path: '/team/performance', label: '人效评分', module: 'performance', roles: ['admin', 'cio'] },
      { key: '/team/positions', path: '/team/positions', label: '岗位编制', module: 'positions', roles: ['admin', 'cio'] },
      { key: '/team/activities', path: '/team/activities', label: '培训发展', module: 'activities' },
      { key: '/team/ideas', path: '/team/ideas', label: '活动积分', module: 'ideas' },
      { key: '/team/charter', path: '/team/charter', label: '团队文化', module: 'charter' },
    ],
  },
  {
    key: 'process',
    label: '流程中心',
    icon: <ApartmentOutlined />,
    roles: ['admin', 'cio', 'it_tm'],
    children: [
      { key: '/process/definitions', path: '/process/definitions', label: '流程定义', module: 'process_definitions' },
      { key: '/process/monitor', path: '/process/monitor', label: '流程监控', module: 'process_monitor' },
    ],
  },
  {
    key: 'admin',
    label: '系统管理',
    icon: <SettingOutlined />,
    roles: ['admin', 'is_mgr'],
    children: [
      {
        key: '/admin/org', path: '/admin/org', label: '组织管理',
        modules: ['admin_departments', 'admin_members', 'admin_business_domains'], roles: ['admin'],
      },
      {
        key: '/admin/identity', path: '/admin/identity', label: '用户与组管理',
        modules: ['admin_users', 'admin_groups'], roles: ['admin'],
      },
      {
        key: '/admin/access', path: '/admin/access', label: '角色与权限',
        modules: ['admin_roles', 'admin_provision', 'admin_permissions'], roles: ['admin'],
      },
      { key: '/admin/master-data', path: '/admin/master-data', label: '数据字典', module: 'admin_master_data', roles: ['admin'] },
      { key: '/admin/workflow-config', path: '/admin/workflow-config', label: '状态机配置', module: 'admin_workflow', roles: ['admin'] },
      { key: '/admin/integrations', path: '/admin/integrations', label: '系统集成', module: 'admin_feishu', roles: ['admin'] },
      { key: '/admin/ui-branding', path: '/admin/ui-branding', label: '界面与品牌', module: 'admin_ui_branding', roles: ['admin'] },
      { key: '/admin/audit-logs', path: '/admin/audit-logs', label: '审计日志', module: 'admin_audit', roles: ['admin', 'is_mgr'] },
    ],
  },
];

/** 节点绑定的全部模块码（module 与 modules 的并集） */
export function nodeModules(node: Pick<MenuNode, 'module' | 'modules'>): string[] {
  return [...(node.module ? [node.module] : []), ...(node.modules ?? [])];
}

/** 节点可见性：优先按权限矩阵（任一绑定 module 有 view 即可见），permissions 缺失的存量会话回退角色逻辑 */
function nodeVisible(node: MenuNode, user: AuthUser | null): boolean {
  const mods = nodeModules(node);
  if (mods.length > 0) {
    if (user?.permissions) return mods.some((m) => hasPermission(user, m, 'view'));
    return hasAnyRole(user, node.roles); // 兼容未重新登录的存量会话
  }
  // 无 module 的分组节点：权限模式下由子节点过滤结果决定（此处先放行）
  if (user?.permissions) return true;
  return hasAnyRole(user, node.roles);
}

/** 按当前用户权限矩阵（回退：角色）过滤菜单树 */
export function filterMenu(nodes: MenuNode[], user: AuthUser | null): MenuNode[] {
  return nodes
    .filter((n) => nodeVisible(n, user))
    .map((n) => (n.children ? { ...n, children: filterMenu(n.children, user) } : n))
    .filter((n) => !n.children || n.children.length > 0);
}

/** 仅持业务用户角色的账号进入 F 服务门户；混合角色仍使用内部工作台。 */
export function isRequesterOnly(user: AuthUser | null): boolean {
  return !!user?.roles.includes('requester') && !user.roles.some((role) => role !== 'requester');
}

/**
 * 登录/首页落点：菜单序第一个有权限的页面（M19）。
 * 总览被关掉的用户（如业务用户）落到其可见的第一项（服务请求），而不是硬闯 /dashboard。
 */
export function firstAccessiblePath(user: AuthUser | null): string {
  const rolePaths = useBrandingStore.getState().current?.config.roles;
  const preferred = user?.roles.includes('requester') ? rolePaths?.requester_landing
    : user?.roles.includes('it_op_leader') ? rolePaths?.noc_landing
    : user?.roles.some((r) => ['cio','it_bm','it_tm','it_pdm_leader','it_dev_leader'].includes(r)) ? rolePaths?.manager_landing
    : user?.roles.includes('it_ops') ? rolePaths?.operator_landing
    : undefined;
  const allowedPaths = new Set<string>();
  const first = (nodes: MenuNode[]): string | null => {
    for (const n of nodes) {
      if (n.path) { allowedPaths.add(n.path); return n.path; }
      const p = n.children ? first(n.children) : null;
      if (p) return p;
    }
    return null;
  };
  const filtered = filterMenu(MENU_TREE, user);
  const fallback = first(filtered) ?? '/dashboard';
  const collect = (nodes: MenuNode[]) => nodes.forEach((n) => { if (n.path) allowedPaths.add(n.path); if (n.children) collect(n.children); });
  collect(filtered);
  return preferred && allowedPaths.has(preferred) ? preferred : fallback;
}

/** path → 面包屑菜单 key 链（如 /itsm/tickets → ['itsm','/itsm/tickets']），由调用方经 t('menu.'+key) 翻译 */
export function breadcrumbOf(pathname: string): string[] {
  for (const node of MENU_TREE) {
    if (node.path === pathname) return [node.key];
    for (const child of node.children ?? []) {
      if (child.path === pathname) return [node.key, child.key];
    }
  }
  return [];
}
