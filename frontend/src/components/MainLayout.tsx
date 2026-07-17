import { useEffect, useMemo, useState } from 'react';
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Avatar, Breadcrumb, Dropdown, Layout, Menu, Space, Typography, theme } from 'antd';
import type { MenuProps } from 'antd';
import { DownOutlined, LogoutOutlined, UserOutlined, SafetyOutlined } from '@ant-design/icons';
import { api } from '../api/client';
import type { AuthUser } from '../api/types';
import { useAuthStore } from '../stores/auth';
import { translate, useT } from '../i18n';
import { useLangStore, type Lang } from '../i18n/store';
import NotificationBell from './NotificationBell';
import LangSwitch from './LangSwitch';
import { MENU_TREE, breadcrumbOf, filterMenu, type MenuNode } from './menu';

const { Header, Sider, Content } = Layout;

function toAntdItems(nodes: MenuNode[], lang: Lang): NonNullable<MenuProps['items']> {
  return nodes.map((n) => ({
    key: n.key,
    label: translate(lang, 'menu.' + n.key),
    icon: n.icon,
    children: n.children ? toAntdItems(n.children, lang) : undefined,
  }));
}

export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { token, user, setUser, logout } = useAuthStore();
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const {
    token: { colorBgContainer },
  } = theme.useToken();

  // 进入布局后刷新一次当前用户信息（token 失效则由拦截器跳登录页）
  useEffect(() => {
    if (!token) return;
    api
      .get<AuthUser>('/auth/me')
      .then(setUser)
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const menuItems = useMemo(() => toAntdItems(filterMenu(MENU_TREE, user), lang), [user, lang]);

  const openKey = useMemo(() => {
    const seg = location.pathname.split('/')[1];
    return seg && ['itsm', 'process', 'team', 'admin'].includes(seg) ? [seg] : [];
  }, [location.pathname]);
  const [openKeys, setOpenKeys] = useState<string[]>(openKey);
  useEffect(() => {
    setOpenKeys((prev) => Array.from(new Set([...prev, ...openKey])));
  }, [openKey]);

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  const crumbs = breadcrumbOf(location.pathname);

  const userMenu: MenuProps = {
    items: [
      {
        key: 'profile',
        icon: <UserOutlined />,
        label: t('profile.menu'),
        onClick: () => navigate('/profile'),
      },
      {
        key: 'security',
        icon: <SafetyOutlined />,
        label: t('profile.securityMenu'),
        onClick: () => navigate('/profile?tab=security'),
      },
      { type: 'divider' },
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: t('header.logout'),
        onClick: () => {
          logout();
          navigate('/login', { replace: true });
        },
      },
    ],
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} width={220}>
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontWeight: 600,
            fontSize: collapsed ? 14 : 16,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
          }}
        >
          {collapsed ? t('app.titleShort') : t('app.title')}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          items={menuItems}
          selectedKeys={[location.pathname]}
          openKeys={collapsed ? undefined : openKeys}
          onOpenChange={(keys) => setOpenKeys(keys)}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: colorBgContainer,
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <Breadcrumb items={crumbs.map((key) => ({ title: t('menu.' + key) }))} />
          <Space size="middle">
            <LangSwitch />
            <NotificationBell />
            <Dropdown menu={userMenu}>
              <Space style={{ cursor: 'pointer' }}>
                {user?.avatar ? (
                  <Avatar size={26} src={user.avatar} />
                ) : (
                  <Avatar size={26} style={{ backgroundColor: '#1677ff' }}>
                    {(user?.name || user?.username || '?')[0]}
                  </Avatar>
                )}
                <Typography.Text>{user?.name || user?.username || t('header.user')}</Typography.Text>
                <DownOutlined style={{ fontSize: 10 }} />
              </Space>
            </Dropdown>
          </Space>
        </Header>
        <Content style={{ margin: 16 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
