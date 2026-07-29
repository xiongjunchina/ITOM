import { useEffect, useRef, useState } from 'react';
import { Alert, Card, Spin, Typography } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { useAuthStore } from '../stores/auth';

type EntryAction = 'service_request' | 'requirement';

interface IntakeHandoffResult {
  status: 'issued' | 'linked';
  action: EntryAction;
  ticket_id: string;
  entry_url: string;
}

/**
 * 飞书服务台原会话中的稳定入口。
 *
 * 链接本身不携带一次性令牌；用户完成 ITOM 登录后，后端重新读取飞书工单、
 * 核验 open_id，再签发十分钟交接令牌并直接跳转到预填的新建页面。
 */
export default function FeishuHelpdeskEntry() {
  const [params] = useSearchParams();
  const intakeId = params.get('intake') || '';
  const rawAction = params.get('action') || '';
  const action = rawAction === 'service_request' || rawAction === 'requirement' ? rawAction : null;
  const authToken = useAuthStore((state) => state.token);
  const [error, setError] = useState('');
  const requestStarted = useRef(false);

  useEffect(() => {
    if (authToken || !intakeId || !action) return;
    const next = `${window.location.pathname}${window.location.search}`;
    window.location.replace(`/login?next=${encodeURIComponent(next)}`);
  }, [action, authToken, intakeId]);

  useEffect(() => {
    if (!authToken || !intakeId || !action) return;
    if (requestStarted.current) return;
    requestStarted.current = true;
    let active = true;
    api
      .post<IntakeHandoffResult>(
        `/integrations/feishu/helpdesk/intakes/${encodeURIComponent(intakeId)}/handoff`,
        { action },
      )
      .then((result) => {
        if (active) window.location.replace(result.entry_url);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : '无法生成 ITOM 交接入口');
      });
    return () => {
      active = false;
    };
  }, [action, authToken, intakeId]);

  if (!intakeId || !action) {
    return <Alert type="error" showIcon message="飞书服务台入口参数不完整" />;
  }
  if (error) {
    return (
      <Card style={{ maxWidth: 640, margin: '18vh auto' }}>
        <Alert type="error" showIcon message="无法进入 ITOM" description={error} />
      </Card>
    );
  }
  return (
    <Card style={{ maxWidth: 520, margin: '18vh auto', textAlign: 'center' }}>
      <Spin size="large" />
      <Typography.Paragraph style={{ marginTop: 20 }}>
        正在核验飞书工单身份并打开 ITOM 新建页面…
      </Typography.Paragraph>
    </Card>
  );
}
