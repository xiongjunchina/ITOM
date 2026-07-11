import PermTabs from '../../components/PermTabs';
import Users from './Users';
import Groups from './Groups';

/** 用户与组管理复合页：用户 | 用户组 */
export default function Identity() {
  return (
    <PermTabs
      tabs={[
        { key: 'users', label: '用户', modules: ['admin_users'], children: <Users /> },
        { key: 'groups', label: '用户组', modules: ['admin_groups'], children: <Groups /> },
      ]}
    />
  );
}
