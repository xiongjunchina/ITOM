import PermTabs from '../../components/PermTabs';
import { useT } from '../../i18n';
import Roles from './Roles';
import ProvisionRules from './ProvisionRules';
import Permissions from './Permissions';

/** 角色与权限复合页：角色定义 | 预分配规则 | 权限配置 */
export default function Access() {
  const t = useT();
  return (
    <PermTabs
      tabs={[
        { key: 'roles', label: t('admin.access.tabRoles'), modules: ['admin_roles'], children: <Roles /> },
        {
          key: 'provision',
          label: t('admin.access.tabProvision'),
          modules: ['admin_provision'],
          children: <ProvisionRules />,
        },
        {
          key: 'permissions',
          label: t('admin.access.tabPermissions'),
          modules: ['admin_permissions'],
          children: <Permissions />,
        },
      ]}
    />
  );
}
