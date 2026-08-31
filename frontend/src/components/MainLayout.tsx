import { useEffect, useMemo, useState } from 'react';
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Alert, Avatar, Button, Breadcrumb, Dropdown, Layout, Menu, Space, Typography } from 'antd';
import type { MenuProps } from 'antd';
import { DownOutlined, InfoCircleOutlined, LogoutOutlined, UserOutlined, SafetyOutlined, MenuFoldOutlined, MenuUnfoldOutlined, SearchOutlined, BookOutlined, FormOutlined } from '@ant-design/icons';
import { api } from '../api/client';
import type { AuthUser } from '../api/types';
import { useAuthStore } from '../stores/auth';
import { translate, useT } from '../i18n';
import { useLangStore, type Lang } from '../i18n/store';
import NotificationBell from './NotificationBell';
import LangSwitch from './LangSwitch';
import { MENU_TREE, breadcrumbOf, filterMenu, isRequesterOnly, type MenuNode } from './menu';
import { localized, useBrandingStore } from '../stores/branding';
import StaffIntakeDrawer from './StaffIntakeDrawer';
import type { ItDocumentGuideResponse } from './DocumentTypeHint';
import AssistantLauncher from './assistant/AssistantLauncher';

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
  const [staffIntakeOpen, setStaffIntakeOpen] = useState(false);
  const [staffIntakeEnabled, setStaffIntakeEnabled] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { token, user, setUser, logout } = useAuthStore();
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const branding = useBrandingStore((s) => s.current?.config);

  // 进入布局后刷新一次当前用户信息（token 失效则由拦截器跳登录页）
  const requesterPortal = isRequesterOnly(user);
  const canViewManual = user?.roles.includes('admin') ?? false;

  useEffect(() => {
    if (!token) return;
    api
      .get<AuthUser>('/auth/me')
      .then(setUser)
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (!token || requesterPortal) {
      setStaffIntakeEnabled(false);
      return;
    }
    api.get<ItDocumentGuideResponse>('/it-document-guide')
      .then((guide) => setStaffIntakeEnabled(guide.staff_intake.enabled))
      .catch(() => setStaffIntakeEnabled(false));
  }, [token, requesterPortal]);

  const menuItems = useMemo(() => toAntdItems(filterMenu(MENU_TREE, user), lang), [user, lang]);
  const selectedMenuPath = location.pathname.startsWith('/team/performance/review/') ? '/team/performance' : location.pathname;
  const portalItems = useMemo(() => {
    const visible = filterMenu(MENU_TREE, user);
    const leaves = visible.flatMap((node) => node.children ?? [node]).filter((node) => node.path);
    return leaves.slice(0, 6);
  }, [user]);

  const openKey = useMemo(() => breadcrumbOf(location.pathname).slice(0, -1), [location.pathname]);
  const [openKeys, setOpenKeys] = useState<string[]>(openKey);
  useEffect(() => {
    setOpenKeys((prev) => Array.from(new Set([...prev, ...openKey])));
  }, [openKey]);

  if (!token) {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }

  const crumbs = breadcrumbOf(location.pathname);
  const brandName = localized(branding, 'brand', 'system_name', lang, t('app.title'));
  const shortName = localized(branding, 'brand', 'short_name', lang, t('app.titleShort'));
  const horizontalLogo = branding?.brand.logo_light_url || branding?.brand.logo_dark_url;
  const logo = collapsed ? branding?.brand.logo_square_url : horizontalLogo;
  const announcement = localized(branding, 'announcement', 'text', lang);
  const now = Date.now();
  const announcementActive = !!branding?.announcement.enabled && !!announcement && (!branding.announcement.starts_at || Date.parse(branding.announcement.starts_at) <= now) && (!branding.announcement.ends_at || Date.parse(branding.announcement.ends_at) >= now);
  const environment = branding?.environment;
  const themePreference = user?.preferences?.theme ?? branding?.appearance.default_theme ?? 'light';
  const shellDark = themePreference === 'dark'
    || (themePreference === 'system' && window.matchMedia?.('(prefers-color-scheme: dark)').matches);
  const currentTitleKey = crumbs[crumbs.length - 1];
  const currentTitle = location.pathname === '/about' ? t('about.title') : currentTitleKey ? t('menu.' + currentTitleKey) : brandName;
  const siderTheme = branding?.appearance.sidebar_theme === 'light' ? 'light' : 'dark';

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
      {
        key: 'about',
        icon: <InfoCircleOutlined />,
        label: t('about.menu'),
        onClick: () => navigate('/about'),
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

  const userControl = (
    <Dropdown menu={userMenu}>
      <Space className="app-user-menu">
        <Avatar size={26} src={user?.avatar} style={{ backgroundColor: '#2b58d6' }}>
          {(user?.name || user?.username || '?')[0]}
        </Avatar>
        <Typography.Text>{user?.name || user?.username || t('header.user')}</Typography.Text>
        <DownOutlined style={{ fontSize: 10 }} />
      </Space>
    </Dropdown>
  );

  if (requesterPortal) {
    return (
      <Layout className={`portal-f ${shellDark ? 'portal-f--dark' : ''}`}>
        <Header className="portal-f__header">
          <button className="portal-f__brand" onClick={() => navigate('/')}>
            {branding?.brand.logo_square_url
              ? <img src={branding.brand.logo_square_url} alt="" />
              : <span>IT</span>}
            <strong>{shortName}</strong>
          </button>
          <nav className="portal-f__nav" aria-label="业务门户导航">
            {portalItems.map((item) => (
              <button key={item.path} className={location.pathname === item.path ? 'is-active' : ''} onClick={() => navigate(item.path!)}>
                {translate(lang, 'menu.' + item.key)}
              </button>
            ))}
          </nav>
          <Space size={12}>
            <Button className="portal-f__search" type="text" icon={<SearchOutlined />} aria-label="搜索" />
            <AssistantLauncher />
            {canViewManual && (
              <Button className="app-manual-entry" type="text" icon={<BookOutlined />} onClick={() => navigate('/user-manual')}>
                {t('header.manual')}
              </Button>
            )}
            <LangSwitch />
            <NotificationBell />
            {userControl}
          </Space>
        </Header>
        {environment?.show_marker && environment.label !== 'production' && <div className="environment-ribbon">{environment.label.toUpperCase()}</div>}
        {announcementActive && <Alert banner closable={branding?.announcement.dismissible} type={branding?.announcement.type === 'maintenance' ? 'warning' : branding.announcement.type} message={announcement} />}
        <Content className="portal-f__content">
          <main className="portal-f__inner"><Outlet /></main>
        </Content>
      </Layout>
    );
  }

  return (
    <Layout className={`app-shell workbench-c ${shellDark ? 'workbench-c--dark' : ''} app-shell--${siderTheme}`}>
      <Sider className="app-sider" theme="light" collapsed={collapsed} width={216} collapsedWidth={72} trigger={null}>
        <div className={`app-brand ${collapsed ? 'is-collapsed' : ''}`}>
          {logo ? <img src={logo} alt={brandName} className="app-brand__logo" /> : <span className="app-brand__mark">IT</span>}
          {!collapsed && <div className="app-brand__copy"><strong>{brandName}</strong><span>{shortName} / OPERATIONS</span></div>}
        </div>
        {!collapsed && <div className="app-nav-caption">WORKSPACE</div>}
        <Menu
          className="app-menu"
          theme="light"
          mode="inline"
          items={menuItems}
          selectedKeys={[selectedMenuPath]}
          openKeys={collapsed ? undefined : openKeys}
          onOpenChange={(keys) => setOpenKeys(keys)}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout className="app-main">
        <Header className="app-header">
          <Space size={14}>
            <Button className="app-collapse" type="text" aria-label={collapsed ? '展开导航' : '收起导航'} icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => setCollapsed(!collapsed)} />
            <div className="app-page-identity">
              <Typography.Title level={4}>{currentTitle}</Typography.Title>
              <Breadcrumb items={crumbs.map((key) => ({ title: t('menu.' + key) }))} />
            </div>
          </Space>
          <Space size="middle">
            <AssistantLauncher />
            {staffIntakeEnabled && (
              <Button type="primary" icon={<FormOutlined />} onClick={() => setStaffIntakeOpen(true)}>
                {t('intake.title')}
              </Button>
            )}
            {canViewManual && (
              <Button className="app-manual-entry" type="text" icon={<BookOutlined />} onClick={() => navigate('/user-manual')}>
                {t('header.manual')}
              </Button>
            )}
            <LangSwitch />
            <NotificationBell />
            {userControl}
          </Space>
        </Header>
        {environment?.show_marker && environment.label !== 'production' && <div className="environment-ribbon">{environment.label.toUpperCase()}</div>}
        {announcementActive && <Alert banner closable={branding?.announcement.dismissible} type={branding?.announcement.type === 'maintenance' ? 'warning' : branding.announcement.type} message={announcement} />}
        <Content className="app-content">
          <main className="app-content__inner"><Outlet /></main>
        </Content>
        <StaffIntakeDrawer open={staffIntakeOpen} onClose={() => setStaffIntakeOpen(false)} />
      </Layout>
    </Layout>
  );
}
