import PermTabs from '../../components/PermTabs';
import FeishuIntegration from './FeishuIntegration';
import EmailIntegration from './EmailIntegration';
import LdapIntegration from './LdapIntegration';

export default function SystemIntegrations() {
  return <PermTabs tabs={[
    { key: 'feishu', label: '飞书集成', modules: ['admin_feishu'], children: <FeishuIntegration /> },
    { key: 'email', label: '邮件服务器', modules: ['admin_feishu'], children: <EmailIntegration /> },
    { key: 'ldap', label: 'AD/LDAP', modules: ['admin_feishu'], children: <LdapIntegration /> },
  ]} />;
}
