import PermTabs from '../../components/PermTabs';
import OrgArchitecture from './OrgArchitecture';
import BusinessDomains from './BusinessDomains';

/** 组织管理复合页：组织架构（部门+人员） | 业务服务域 */
export default function OrgManagement() {
  return (
    <PermTabs
      tabs={[
        {
          key: 'architecture',
          label: '组织架构',
          modules: ['admin_departments', 'admin_members'],
          children: <OrgArchitecture />,
        },
        {
          key: 'domains',
          label: '业务服务域',
          modules: ['admin_business_domains'],
          children: <BusinessDomains />,
        },
      ]}
    />
  );
}
