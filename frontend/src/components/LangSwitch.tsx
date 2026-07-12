import { Button, Dropdown } from 'antd';
import type { MenuProps } from 'antd';
import { CheckOutlined, GlobalOutlined } from '@ant-design/icons';
import { useT } from '../i18n';
import { useLangStore, type Lang } from '../i18n/store';
import { useAuthStore } from '../stores/auth';
import { api } from '../api/client';

/**
 * 语言切换器：GlobalOutlined + 下拉（中文 / English，当前项打勾）。
 * 登录前仅切本地 store；已登录时同时持久化到后端偏好并同步 user.language。
 */
export default function LangSwitch() {
  const t = useT();
  const lang = useLangStore((s) => s.lang);

  const choose = (next: Lang) => {
    if (next === lang) return;
    useLangStore.getState().setLang(next);
    const { token, user, setUser } = useAuthStore.getState();
    if (token && user) {
      // 已登录：持久化到后端（失败不阻塞，本地已切换；拦截器会提示错误）
      void api.patch('/auth/me/preferences', { language: next }).catch(() => undefined);
      setUser({ ...user, language: next });
    }
  };

  const items: MenuProps['items'] = (['zh', 'en'] as Lang[]).map((l) => ({
    key: l,
    label: t('lang.' + l),
    icon:
      l === lang ? (
        <CheckOutlined />
      ) : (
        <span style={{ display: 'inline-block', width: 14 }} />
      ),
  }));

  return (
    <Dropdown
      menu={{ items, selectable: true, selectedKeys: [lang], onClick: ({ key }) => choose(key as Lang) }}
      placement="bottomRight"
      trigger={['click', 'hover']}
    >
      <Button type="text" icon={<GlobalOutlined style={{ fontSize: 16 }} />} aria-label={t('lang.switch')} />
    </Dropdown>
  );
}
