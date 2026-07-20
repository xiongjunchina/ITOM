import { useEffect, useState } from 'react';
import { Alert, Button, Card, Form, Input, Space, Switch, message } from 'antd';
import { ApiOutlined, SaveOutlined } from '@ant-design/icons';
import { api } from '../../api/client';

interface LdapConfig { enabled: boolean; server_url: string; bind_dn: string; bind_password?: string; base_dn: string; user_dn_template: string; use_ssl: boolean }
export default function LdapIntegration() {
  const [form] = Form.useForm<LdapConfig>(); const [saving, setSaving] = useState(false); const [testing, setTesting] = useState(false);
  useEffect(() => { api.get<LdapConfig>('/admin/integrations/ldap').then((v) => form.setFieldsValue({ ...v, user_dn_template: v.user_dn_template || '{username}' })).catch(() => undefined); }, [form]);
  const save = async () => { setSaving(true); try { await api.put('/admin/integrations/ldap', await form.validateFields()); message.success('AD/LDAP 配置已保存'); } finally { setSaving(false); } };
  const test = async () => { setTesting(true); try { await api.post('/admin/integrations/ldap/test'); message.success('AD/LDAP 连接成功'); } finally { setTesting(false); } };
  return <Card title="AD/LDAP 认证" extra={<Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={() => void save()}>保存</Button>}>
    <Alert type="info" showIcon message="LDAP 登录用户需先在 ITOM 创建同名账号；角色和权限仍由 ITOM 统一管理。绑定密码加密保存。" style={{ marginBottom: 16 }} />
    <Form form={form} layout="vertical" style={{ maxWidth: 620 }} initialValues={{ enabled: false, use_ssl: false, user_dn_template: '{username}' }}>
      <Form.Item name="enabled" label="启用 AD/LDAP 登录" valuePropName="checked"><Switch /></Form.Item>
      <Form.Item name="server_url" label="服务器地址" rules={[{ required: true }]}><Input placeholder="ldap.company.com" /></Form.Item>
      <Form.Item name="use_ssl" label="使用 LDAPS" valuePropName="checked"><Switch /></Form.Item>
      <Form.Item name="base_dn" label="Base DN"><Input placeholder="DC=company,DC=com" /></Form.Item>
      <Form.Item name="bind_dn" label="绑定账号 DN" rules={[{ required: true }]}><Input placeholder="CN=svc_itom,OU=Service,DC=company,DC=com" /></Form.Item>
      <Form.Item name="bind_password" label="绑定密码" extra="留空表示保持原密码不变"><Input.Password autoComplete="new-password" /></Form.Item>
      <Form.Item name="user_dn_template" label="用户 DN 模板" extra="使用 {username} 作为登录名占位符" rules={[{ required: true }]}><Input placeholder="{username}@company.com" /></Form.Item>
      <Space><Button icon={<ApiOutlined />} loading={testing} onClick={() => void test()}>测试连接</Button></Space>
    </Form>
  </Card>;
}
