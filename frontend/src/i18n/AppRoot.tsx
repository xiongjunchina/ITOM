import { useEffect } from 'react';
import { ConfigProvider, theme as antdTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import 'dayjs/locale/en';
import { RouterProvider } from 'react-router-dom';
import { router } from '../router';
import { useLangStore } from './store';
import { useAuthStore } from '../stores/auth';
import { useBrandingStore } from '../stores/branding';

/** 语言随 store 响应式驱动 antd 组件文案（分页/日期/空态）与 dayjs 本地化。 */
export default function AppRoot() {
  const lang = useLangStore((s) => s.lang);
  const preferences = useAuthStore((s) => s.user?.preferences);
  const branding = useBrandingStore((s) => s.current?.config);
  const loadBranding = useBrandingStore((s) => s.load);
  useEffect(() => { void loadBranding(); }, [loadBranding]);
  const systemDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  const selectedTheme = preferences?.theme ?? branding?.appearance.default_theme ?? 'light';
  const dark = selectedTheme === 'dark' || (selectedTheme === 'system' && systemDark);
  const density = preferences?.density ?? branding?.appearance.default_density ?? 'default';
  useEffect(() => {
    dayjs.locale(lang === 'en' ? 'en' : 'zh-cn');
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.documentElement.dataset.density = density;
    const favicon = branding?.brand.favicon_url;
    if (favicon) document.querySelector<HTMLLinkElement>('link[rel="icon"]')?.setAttribute('href', favicon);
    const name = lang === 'en' ? branding?.brand.system_name_en : branding?.brand.system_name_zh;
    const suffix = branding?.brand.browser_title_suffix;
    document.title = [name, suffix].filter(Boolean).join(' · ') || 'ITOM';
  }, [lang, dark, density, branding]);
  return (
    <ConfigProvider
      locale={lang === 'en' ? enUS : zhCN}
      componentSize={density === 'compact' ? 'small' : 'middle'}
      theme={{
        algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: branding?.appearance.primary_color || '#2457d6',
          borderRadius: 10,
          fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif",
          colorBgLayout: dark ? '#101318' : '#f4f6f9',
          colorBorderSecondary: dark ? '#2b3038' : '#e8ebf0',
        },
        components: {
          Card: { headerFontSize: 15, paddingLG: 20 },
          Table: { headerBg: dark ? '#20242b' : '#f7f8fa', headerColor: dark ? '#d5d9e0' : '#596273' },
          Menu: { itemBorderRadius: 8, itemMarginInline: 10, itemHeight: 42 },
        },
      }}
    >
      <RouterProvider router={router} />
    </ConfigProvider>
  );
}
