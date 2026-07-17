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

/** 语言随 store 响应式驱动 antd 组件文案（分页/日期/空态）与 dayjs 本地化。 */
export default function AppRoot() {
  const lang = useLangStore((s) => s.lang);
  const preferences = useAuthStore((s) => s.user?.preferences);
  const systemDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  const dark = preferences?.theme === 'dark' || (preferences?.theme === 'system' && systemDark);
  useEffect(() => {
    dayjs.locale(lang === 'en' ? 'en' : 'zh-cn');
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.documentElement.dataset.density = preferences?.density ?? 'default';
  }, [lang, dark, preferences?.density]);
  return (
    <ConfigProvider
      locale={lang === 'en' ? enUS : zhCN}
      componentSize={preferences?.density === 'compact' ? 'small' : 'middle'}
      theme={{ algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm }}
    >
      <RouterProvider router={router} />
    </ConfigProvider>
  );
}
