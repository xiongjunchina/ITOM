import { useCallback, useEffect, useState } from 'react';
import { Badge } from 'antd';
import PermTabs from '../../components/PermTabs';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import Users from './Users';
import Groups from './Groups';
import Onboarding from './Onboarding';

/** 用户与组管理复合页：用户 | 用户组 | 登录开通 */
export default function Identity() {
  const t = useT();
  const [pending, setPending] = useState(0);

  const loadCount = useCallback(() => {
    api
      .get<{ pending: number }>('/auth/onboarding/pending-count')
      .then((d) => setPending(d?.pending ?? 0))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    loadCount();
  }, [loadCount]);

  return (
    <PermTabs
      tabs={[
        { key: 'users', label: t('admin.identity.tabUsers'), modules: ['admin_users'], children: <Users /> },
        { key: 'groups', label: t('admin.identity.tabGroups'), modules: ['admin_groups'], children: <Groups /> },
        {
          key: 'onboarding',
          label: (
            <Badge count={pending} size="small" offset={[10, -2]}>
              {t('onboarding.tab')}
            </Badge>
          ),
          modules: ['admin_users'],
          children: <Onboarding onChanged={loadCount} />,
        },
      ]}
    />
  );
}
