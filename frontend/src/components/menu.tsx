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

export interface MenuNode {
  path?: string; // 叶子节点路由
  key: string;
  label: string;
  icon?: ReactNode;
  /** 功能权限模块码：user.permissions[module] 含 "view"（或 "*" 全权）则可见 */
  module?: string;
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
    label: 'ITSM 服务',
    icon: <CustomerServiceOutlined />,
    children: [
      { key: '/itsm/tickets', path: '/itsm/tickets', label: '工单', module: 'tickets' },
      { key: '/itsm/catalog', path: '/itsm/catalog', label: '服务目录', module: 'catalog', roles: STAFF },
      { key: '/itsm/cmdb', path: '/itsm/cmdb', label: 'CMDB', module: 'cmdb', roles: STAFF },
      { key: '/itsm/sla', path: '/itsm/sla', label: 'SLA 看板', module: 'sla', roles: STAFF },
      { key: '/itsm/problems', path: '/itsm/problems', label: '问题', module: 'problems', roles: STAFF },
      { key: '/itsm/vendors', path: '/itsm/vendors', label: '供应商', module: 'vendors', roles: STAFF },
      { key: '/itsm/contracts', path: '/itsm/contracts', label: '合同', module: 'contracts', roles: STAFF },
      { key: '/itsm/knowledge', path: '/itsm/knowledge', label: '知识库', module: 'knowledge' },
    ],
  },
  { key: '/projects', path: '/projects', label: '项目管理', icon: <ProjectOutlined />, module: 'projects', roles: STAFF },
  { key: '/requirements', path: '/requirements', label: '需求管理', icon: <FileTextOutlined />, module: 'requirements' },
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
    key: 'team',
    label: '团队管理',
    icon: <TeamOutlined />,
    roles: STAFF,
    children: [
      { key: '/team/overview', path: '/team/overview', label: '团队总览', module: 'team_overview' },
      { key: '/team/performance', path: '/team/performance', label: '人效评分', module: 'performance', roles: ['admin', 'cio', 'it_tm'] },
      { key: '/team/positions', path: '/team/positions', label: '岗位编制', module: 'positions' },
      { key: '/team/activities', path: '/team/activities', label: '培训发展', module: 'activities' },
      { key: '/team/ideas', path: '/team/ideas', label: '建言献策', module: 'ideas' },
      { key: '/team/charter', path: '/team/charter', label: '团队文化', module: 'charter' },
    ],
  },
  {
    key: 'admin',
    label: '系统管理',
    icon: <SettingOutlined />,
    roles: ['admin', 'is_mgr'],
    children: [
      { key: '/admin/users', path: '/admin/users', label: '用户管理', module: 'admin_users', roles: ['admin'] },
      { key: '/admin/roles', path: '/admin/roles', label: '角色管理', module: 'admin_roles', roles: ['admin'] },
      { key: '/admin/groups', path: '/admin/groups', label: '用户组', module: 'admin_groups', roles: ['admin'] },
      { key: '/admin/permissions', path: '/admin/permissions', label: '权限配置', module: 'admin_permissions', roles: ['admin'] },
      { key: '/admin/provision-rules', path: '/admin/provision-rules', label: '开通规则', module: 'admin_provision', roles: ['admin'] },
      { key: '/admin/departments', path: '/admin/departments', label: '部门管理', module: 'admin_departments', roles: ['admin'] },
      { key: '/admin/members', path: '/admin/members', label: '人员主数据', module: 'admin_members', roles: ['admin'] },
      { key: '/admin/business-domains', path: '/admin/business-domains', label: '业务域', module: 'admin_business_domains', roles: ['admin'] },
      { key: '/admin/master-data', path: '/admin/master-data', label: '数据字典', module: 'admin_master_data', roles: ['admin'] },
      { key: '/admin/workflow-config', path: '/admin/workflow-config', label: '状态机配置', module: 'admin_workflow', roles: ['admin'] },
      { key: '/admin/audit-logs', path: '/admin/audit-logs', label: '审计日志', module: 'admin_audit', roles: ['admin', 'is_mgr'] },
    ],
  },
];

/** 节点可见性：优先按权限矩阵（module + view），permissions 缺失的存量会话回退角色逻辑 */
function nodeVisible(node: MenuNode, user: AuthUser | null): boolean {
  if (node.module) {
    if (user?.permissions) return hasPermission(user, node.module, 'view');
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

/** path → 面包屑标题链，如 /admin/users → ['系统管理','用户管理'] */
export function breadcrumbOf(pathname: string): string[] {
  for (const node of MENU_TREE) {
    if (node.path === pathname) return [node.label];
    for (const child of node.children ?? []) {
      if (child.path === pathname) return [node.label, child.label];
    }
  }
  return [];
}
