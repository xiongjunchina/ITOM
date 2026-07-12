import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Result, Space, Spin, Typography, message } from 'antd';
import { useT } from '../i18n';
import { useAuthStore } from '../stores/auth';
import type { Envelope, OnboardingStatusResult } from '../api/types';
import LangSwitch from '../components/LangSwitch';

const POLL_MS = 3000;

const PENDING_TOKEN_KEY = 'aom-pending-token';
const PENDING_NAME_KEY = 'aom-pending-name';

function clearPending() {
  localStorage.removeItem(PENDING_TOKEN_KEY);
  localStorage.removeItem(PENDING_NAME_KEY);
}

/**
 * 飞书扫码后未开通的过渡页（公开路由，不在 MainLayout 内）：
 * 携带 pending_token 每 3 秒轮询 /auth/onboarding/status；管理员开通→拿正式 token 进系统，
 * 驳回→展示原因并可返回登录，pending_token 失效(401)→回登录页。
 */
export default function OnboardingPending() {
  const t = useT();
  const navigate = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [rejected, setRejected] = useState<string | null>(null); // 驳回原因（null=未驳回）
  const name = localStorage.getItem(PENDING_NAME_KEY) || '';

  const stoppedRef = useRef(false);

  useEffect(() => {
    const pendingToken = localStorage.getItem(PENDING_TOKEN_KEY);
    if (!pendingToken) {
      navigate('/login', { replace: true });
      return;
    }

    let timer: number | undefined;
    const stop = () => {
      stoppedRef.current = true;
      if (timer) window.clearInterval(timer);
    };

    const poll = async () => {
      if (stoppedRef.current) return;
      try {
        const res = await fetch('/api/auth/onboarding/status', {
          headers: { Authorization: 'Bearer ' + pendingToken },
        });
        if (res.status === 401) {
          // pending_token 失效：清凭据回登录（勿死循环）
          stop();
          clearPending();
          message.warning(t('onboarding.pendingExpired'));
          navigate('/login', { replace: true });
          return;
        }
        const env = (await res.json()) as Envelope<OnboardingStatusResult>;
        if (!env?.success || !env.data) return; // 异常响应：继续下次轮询
        const data = env.data;
        if (data.status === 'approved') {
          stop();
          clearPending();
          setAuth(data.token, data.user);
          message.success(t('onboarding.approved'));
          navigate('/dashboard', { replace: true });
        } else if (data.status === 'rejected') {
          stop();
          setRejected(data.note || '');
        }
        // pending：保持等待
      } catch {
        // 网络抖动：忽略，等待下次轮询
      }
    };

    void poll();
    timer = window.setInterval(() => void poll(), POLL_MS);
    return stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const backToLogin = () => {
    clearPending();
    navigate('/login', { replace: true });
  };

  return (
    <div
      style={{
        position: 'relative',
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f0f2f5',
      }}
    >
      <div style={{ position: 'absolute', top: 16, right: 16 }}>
        <LangSwitch />
      </div>
      <Card style={{ width: 480, boxShadow: '0 2px 8px rgba(0,0,0,0.09)' }}>
        {rejected !== null ? (
          <Result
            status="warning"
            title={t('onboarding.rejectedTitle')}
            subTitle={rejected ? t('onboarding.rejectedReason', { reason: rejected }) : undefined}
            extra={
              <Button type="primary" onClick={backToLogin}>
                {t('onboarding.backToLogin')}
              </Button>
            }
          />
        ) : (
          <Space direction="vertical" size="large" align="center" style={{ width: '100%', padding: '16px 0' }}>
            <Spin size="large" />
            <Typography.Title level={4} style={{ textAlign: 'center', margin: 0 }}>
              {t('onboarding.waitingTitle')}
            </Typography.Title>
            {name && (
              <Typography.Text strong>{t('onboarding.hello', { name })}</Typography.Text>
            )}
            <Typography.Paragraph type="secondary" style={{ textAlign: 'center', marginBottom: 0 }}>
              {t('onboarding.waitingDesc')}
            </Typography.Paragraph>
            <Typography.Text type="secondary">{t('onboarding.statusPending')}</Typography.Text>
            <Button type="link" onClick={backToLogin}>
              {t('onboarding.backToLogin')}
            </Button>
          </Space>
        )}
      </Card>
    </div>
  );
}
