import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Spin, Typography, message } from 'antd';
import type { Envelope, FeishuScanResult } from '../api/types';
import { useAuthStore } from '../stores/auth';
import { firstAccessiblePath } from '../components/menu';
import { useT } from '../i18n';
import { api } from '../api/client';

/**
 * 真实飞书 OAuth 回调页（公开路由，不在 MainLayout 内）：
 * 飞书扫码授权后跳回 /login/feishu-callback?code=xxx&state=yyy，
 * 用原生 fetch 兑换 code（绕过 axios 的 token 注入与全局 401 跳转，同 Login.onFeishuScan）。
 * 结果与模拟扫码一致：active → 直接进系统；pending → 存 pending 凭据进开通过渡页。
 */
export default function FeishuCallback() {
  const t = useT();
  const navigate = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);
  const ranRef = useRef(false);

  useEffect(() => {
    // StrictMode 下 effect 会双调用，而 code 只能兑换一次，须防重复提交
    if (ranRef.current) return;
    ranRef.current = true;

    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');
    const binding = params.get('mode') === 'bind';
    if (!code || !state) {
      message.error(t('login.feishuCallbackMissing'));
      navigate('/login', { replace: true });
      return;
    }

    const run = async () => {
      try {
        if (binding) {
          await api.post('/auth/me/feishu-binding', { code, state });
          message.success(t('profile.feishuBindSuccess'));
          navigate('/profile?tab=binding', { replace: true });
          return;
        }
        const res = await fetch('/api/auth/feishu/callback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code, state }),
        });
        const env = (await res.json()) as Envelope<FeishuScanResult>;
        if (!res.ok || !env.success || !env.data) {
          // 401 INVALID_STATE / 502 上游错误等：提示后端消息并回登录页
          message.error(env?.error?.message || t('login.feishuFailed'));
          navigate('/login', { replace: true });
          return;
        }
        const data = env.data;
        if (data.status === 'active') {
          setAuth(data.token, data.user);
          const next = localStorage.getItem('aom-login-next');
          localStorage.removeItem('aom-login-next');
          navigate(next && next.startsWith('/') ? next : firstAccessiblePath(data.user), { replace: true });
        } else {
          // pending：暂存 pending 凭据，进过渡页轮询开通结果（与模拟扫码一致）
          localStorage.setItem('aom-pending-token', data.pending_token);
          localStorage.setItem('aom-pending-name', data.display_name);
          navigate('/onboarding/pending', { replace: true });
        }
      } catch {
        message.error(t('login.feishuFailed'));
        navigate('/login', { replace: true });
      }
    };
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
        background: '#f0f2f5',
      }}
    >
      <Spin size="large" />
      <Typography.Text type="secondary">{t('login.feishuCompleting')}</Typography.Text>
    </div>
  );
}
