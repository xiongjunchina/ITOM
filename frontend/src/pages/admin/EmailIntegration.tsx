import { useEffect, useState } from 'react';
import { Alert, Button, Card, Form, Input, InputNumber, Space, Switch, message } from 'antd';
import { ApiOutlined, SaveOutlined } from '@ant-design/icons';
import { api } from '../../api/client';

interface EmailConfig { enabled: boolean; host: string; port: number; username: string; password?: string; has_secret?: boolean; from_email: string; from_name: string; use_tls: boolean }

export default function EmailIntegration() {
  const [form] = Form.useForm<EmailConfig>();
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  useEffect(() => { api.get<EmailConfig>('/admin/integrations/email').then((v) => form.setFieldsValue({ ...v, port: v.port ?? 587, use_tls: v.use_tls ?? true })).catch(() => undefined); }, [form]);
  const save = async () => { setSaving(true); try { const v = await form.validateFields(); await api.put('/admin/integrations/email', v); message.success('邮件服务器配置已保存'); } finally { setSaving(false); } };
  const test = async () => { setTesting(true); try { const r = await api.post<{ sent_to: string }>('/admin/integrations/email/test'); message.success(`测试邮件已发送至 ${r.sent_to}`); } finally { setTesting(false); } };
  return <Card title="邮件服务器" extra={<Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={() => void save()}>保存</Button>}>
    <Alert type="info" showIcon message="SMTP 密码加密保存，页面不会回显明文。" style={{ marginBottom: 16 }} />
    <Form form={form} layout="vertical" style={{ maxWidth: 560 }} initialValues={{ enabled: false, port: 587, use_tls: true, from_name: 'ITOM' }}>
      <Form.Item name="enabled" label="启用邮件服务" valuePropName="checked"><Switch /></Form.Item>
      <Form.Item name="host" label="SMTP 服务器" rules={[{ required: true }]}><Input placeholder="smtp.example.com" /></Form.Item>
      <Form.Item name="port" label="端口" rules={[{ required: true }]}><InputNumber min={1} max={65535} style={{ width: '100%' }} /></Form.Item>
      <Form.Item name="username" label="登录账号"><Input autoComplete="off" /></Form.Item>
      <Form.Item name="password" label="登录密码" extra="留空表示保持原密码不变"><Input.Password autoComplete="new-password" /></Form.Item>
      <Form.Item name="from_email" label="发件邮箱" rules={[{ required: true, type: 'email' }]}><Input /></Form.Item>
      <Form.Item name="from_name" label="发件人名称"><Input /></Form.Item>
      <Form.Item name="use_tls" label="启用 STARTTLS" valuePropName="checked"><Switch /></Form.Item>
      <Space><Button icon={<ApiOutlined />} loading={testing} onClick={() => void test()}>发送测试邮件</Button></Space>
    </Form>
  </Card>;
}
