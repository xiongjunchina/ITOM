import PermTabs from '../../components/PermTabs';
import Roles from './Roles';
import ProvisionRules from './ProvisionRules';
import Permissions from './Permissions';

/** 角色与权限复合页：角色定义 | 预分配规则 | 权限配置 */
export default function Access() {
  return (
    <PermTabs
      tabs={[
        { key: 'roles', label: '角色定义', modules: ['admin_roles'], children: <Roles /> },
        {
          key: 'provision',
          label: '预分配规则',
          modules: ['admin_provision'],
          children: <ProvisionRules />,
        },
        {
          key: 'permissions',
          label: '权限配置',
          modules: ['admin_permissions'],
          children: <Permissions />,
        },
      ]}
    />
  );
}
