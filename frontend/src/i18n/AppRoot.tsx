import { useEffect } from 'react';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import 'dayjs/locale/en';
import { RouterProvider } from 'react-router-dom';
import { router } from '../router';
import { useLangStore } from './store';

/** 语言随 store 响应式驱动 antd 组件文案（分页/日期/空态）与 dayjs 本地化。 */
export default function AppRoot() {
  const lang = useLangStore((s) => s.lang);
  useEffect(() => {
    dayjs.locale(lang === 'en' ? 'en' : 'zh-cn');
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
  }, [lang]);
  return (
    <ConfigProvider locale={lang === 'en' ? enUS : zhCN}>
      <RouterProvider router={router} />
    </ConfigProvider>
  );
}
