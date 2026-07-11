import type { ReactNode } from 'react';
import { Empty, Tabs } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { hasAnyRole, hasPermission, useAuthStore } from '../stores/auth';

export interface PermTabItem {
  /** ?tab= 查询参数取值 */
  key: string;
  label: string;
  /** 绑定的权限模块码：任一模块有 view 权限即显示该 Tab */
  modules: string[];
  children: ReactNode;
}

/**
 * 复合页 Tabs：?tab= 查询参数驱动选中项（旧路由重定向落点），
 * 每个 Tab 按对应 module 的 view 权限显示/隐藏（存量会话缺 permissions 时回退 admin 角色）。
 */
export default function PermTabs({ tabs }: { tabs: PermTabItem[] }) {
  const user = useAuthStore((s) => s.user);
  const [searchParams, setSearchParams] = useSearchParams();

  const visible = tabs.filter((t) =>
    user?.permissions
      ? t.modules.some((m) => hasPermission(user, m, 'view'))
      : hasAnyRole(user, ['admin']),
  );

  if (visible.length === 0) {
    return <Empty description="暂无可用功能（缺少查看权限）" style={{ marginTop: 48 }} />;
  }

  const tabParam = searchParams.get('tab');
  const activeKey = visible.some((t) => t.key === tabParam) ? (tabParam as string) : visible[0].key;

  return (
    <Tabs
      activeKey={activeKey}
      items={visible.map((t) => ({ key: t.key, label: t.label, children: t.children }))}
      onChange={(key) => setSearchParams({ tab: key }, { replace: true })}
    />
  );
}
