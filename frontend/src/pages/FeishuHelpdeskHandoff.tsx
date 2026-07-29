import { useEffect, useState } from 'react';
import { Alert, Button, Card, Descriptions, Spin, Space, Tag, Typography, message } from 'antd';
import { ArrowRightOutlined, CustomerServiceOutlined, FileTextOutlined } from '@ant-design/icons';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { useAuthStore } from '../stores/auth';

interface HandoffPayload {
  action: 'service_request' | 'requirement';
  ticket_id: string;
  expires_at: string;
  prefill: {
    title?: string;
    description?: string;
    priority?: string;
    service_category?: string;
    other_info?: string;
  };
  source: { guest_name?: string; agent_name?: string };
}

/** 飞书服务台动态卡片进入 ITOM 的安全交接确认页。 */
export default function FeishuHelpdeskHandoff() {
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const authToken = useAuthStore((s) => s.token);
  const navigate = useNavigate();
  const [data, setData] = useState<HandoffPayload | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (authToken) return;
    const next = `/feishu/helpdesk/handoff?token=${encodeURIComponent(token)}`;
    window.location.replace(`/login?next=${encodeURIComponent(next)}`);
  }, [authToken, token]);

  useEffect(() => {
    if (!authToken) return;
    if (!token) {
      message.error('交接链接缺少令牌');
      setLoading(false);
      return;
    }
    api
      .get<HandoffPayload>(`/integrations/feishu/helpdesk/handoffs/${encodeURIComponent(token)}`)
      .then(setData)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, [authToken, token]);

  if (!authToken) {
    return <Spin style={{ display: 'block', margin: '20vh auto' }} size="large" />;
  }

  if (loading) return <Spin style={{ display: 'block', margin: '20vh auto' }} size="large" />;
  if (!data) return <Alert type="error" showIcon message="交接链接无效、已过期，或当前账号不是工单申请人" />;

  const isTicket = data.action === 'service_request';
  const priorityLabel: Record<string, string> = { P1: '紧急', P2: '高', P3: '一般', P4: '低' };
  return (
    <Card title="飞书服务台交接" style={{ maxWidth: 760, margin: '24px auto' }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 20 }}
        message="以下内容来自飞书服务台询前单，提交前仍可在 ITOM 创建页面补充或修改。"
      />
      <Descriptions bordered column={1}>
        <Descriptions.Item label="飞书工单 ID">{data.ticket_id}</Descriptions.Item>
        <Descriptions.Item label="申请人">{data.source.guest_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="飞书客服">{data.source.agent_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="标题">{data.prefill.title || '-'}</Descriptions.Item>
        <Descriptions.Item label="紧急程度">
          {priorityLabel[data.prefill.priority || ''] || data.prefill.priority || '-'}
        </Descriptions.Item>
        <Descriptions.Item label="服务类别">
          {data.prefill.service_category ? <Tag color="blue">{data.prefill.service_category}</Tag> : '未填写'}
        </Descriptions.Item>
        <Descriptions.Item label="问题描述">{data.prefill.description || '-'}</Descriptions.Item>
        <Descriptions.Item label="其他补充信息">{data.prefill.other_info || '-'}</Descriptions.Item>
      </Descriptions>
      <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>
        服务类别只用于匹配 ITSM 服务目录/服务项，不会自动写入 IT 需求的业务域；需求业务域请在登记页另行选择。
      </Typography.Paragraph>
      <Space>
        <Button
          type="primary"
          icon={isTicket ? <CustomerServiceOutlined /> : <FileTextOutlined />}
          onClick={() => navigate(isTicket ? `/itsm/tickets?handoff=${encodeURIComponent(token)}` : `/requirements/overview?handoff=${encodeURIComponent(token)}`)}
        >
          {isTicket ? '创建 IT 服务请求' : '登记 IT 需求'} <ArrowRightOutlined />
        </Button>
      </Space>
    </Card>
  );
}
