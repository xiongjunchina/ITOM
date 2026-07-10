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
import { hasAnyRole } from '../stores/auth';

export interface MenuNode {
  path?: string; // 叶子节点路由
  key: string;
  label: string;
  icon?: ReactNode;
  roles?: Role[]; // 缺省表示全员可见
  children?: MenuNode[];
}

/** 除业务用户(requester)之外的内部角色 */
const STAFF: Role[] = ['admin', 'manager', 'it_pdm', 'it_pm', 'it_dev', 'it_ops', 'is_mgr', 'it_bp'];

export const MENU_TREE: MenuNode[] = [
  { key: '/dashboard', path: '/dashboard', label: '总览', icon: <DashboardOutlined /> },
  {
    key: 'itsm',
    label: 'ITSM 服务',
    icon: <CustomerServiceOutlined />,
    children: [
      { key: '/itsm/tickets', path: '/itsm/tickets', label: '工单' },
      { key: '/itsm/catalog', path: '/itsm/catalog', label: '服务目录', roles: STAFF },
      { key: '/itsm/cmdb', path: '/itsm/cmdb', label: 'CMDB', roles: STAFF },
      { key: '/itsm/sla', path: '/itsm/sla', label: 'SLA 看板', roles: STAFF },
      { key: '/itsm/problems', path: '/itsm/problems', label: '问题', roles: STAFF },
      { key: '/itsm/vendors', path: '/itsm/vendors', label: '供应商', roles: STAFF },
      { key: '/itsm/contracts', path: '/itsm/contracts', label: '合同', roles: STAFF },
      { key: '/itsm/knowledge', path: '/itsm/knowledge', label: '知识库' },
    ],
  },
  { key: '/projects', path: '/projects', label: '项目管理', icon: <ProjectOutlined />, roles: STAFF },
  { key: '/requirements', path: '/requirements', label: '需求管理', icon: <FileTextOutlined /> },
  {
    key: 'process',
    label: '流程中心',
    icon: <ApartmentOutlined />,
    roles: ['admin', 'manager'],
    children: [
      { key: '/process/definitions', path: '/process/definitions', label: '流程定义' },
      { key: '/process/monitor', path: '/process/monitor', label: '流程监控' },
    ],
  },
  {
    key: 'team',
    label: '团队管理',
    icon: <TeamOutlined />,
    roles: STAFF,
    children: [
      { key: '/team/overview', path: '/team/overview', label: '团队总览' },
      { key: '/team/performance', path: '/team/performance', label: '人效评分', roles: ['admin', 'manager'] },
      { key: '/team/positions', path: '/team/positions', label: '岗位编制' },
      { key: '/team/activities', path: '/team/activities', label: '培训发展' },
      { key: '/team/ideas', path: '/team/ideas', label: '建言献策' },
      { key: '/team/charter', path: '/team/charter', label: '团队文化' },
    ],
  },
  {
    key: 'admin',
    label: '系统管理',
    icon: <SettingOutlined />,
    roles: ['admin', 'is_mgr'],
    children: [
      { key: '/admin/users', path: '/admin/users', label: '用户管理', roles: ['admin'] },
      { key: '/admin/roles', path: '/admin/roles', label: '角色管理', roles: ['admin'] },
      { key: '/admin/groups', path: '/admin/groups', label: '用户组', roles: ['admin'] },
      { key: '/admin/members', path: '/admin/members', label: '人员主数据', roles: ['admin'] },
      { key: '/admin/master-data', path: '/admin/master-data', label: '数据字典', roles: ['admin'] },
      { key: '/admin/workflow-config', path: '/admin/workflow-config', label: '状态机配置', roles: ['admin'] },
      { key: '/admin/audit-logs', path: '/admin/audit-logs', label: '审计日志', roles: ['admin', 'is_mgr'] },
    ],
  },
];

/** 按当前用户角色过滤菜单树 */
export function filterMenu(nodes: MenuNode[], user: AuthUser | null): MenuNode[] {
  return nodes
    .filter((n) => hasAnyRole(user, n.roles))
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
