import PermTabs from '../../components/PermTabs';
import { useT } from '../../i18n';
import OrgArchitecture from './OrgArchitecture';
import BusinessDomains from './BusinessDomains';

/** 组织管理复合页：组织架构（部门+人员） | 业务服务域 */
export default function OrgManagement() {
  const t = useT();
  return (
    <PermTabs
      tabs={[
        {
          key: 'architecture',
          label: t('admin.org.tabArchitecture'),
          modules: ['admin_departments', 'admin_members'],
          children: <OrgArchitecture />,
        },
        {
          key: 'domains',
          label: t('admin.org.tabDomains'),
          modules: ['admin_business_domains'],
          children: <BusinessDomains />,
        },
      ]}
    />
  );
}
