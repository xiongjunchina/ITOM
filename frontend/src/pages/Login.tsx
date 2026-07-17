import { useEffect, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Button, Card, Divider, Form, Input, Modal, Typography, message } from 'antd';
import { LockOutlined, QrcodeOutlined, UserOutlined } from '@ant-design/icons';
import { isAxiosError } from 'axios';
import { api } from '../api/client';
import type { Envelope, FeishuScanResult, LoginResult } from '../api/types';
import { useAuthStore } from '../stores/auth';
import { firstAccessiblePath } from '../components/menu';
import { useT } from '../i18n';
import LangSwitch from '../components/LangSwitch';

interface LoginForm {
  username: string;
  password: string;
}

interface FeishuForm {
  display_name: string;
  external_id: string;
}

/** 飞书客户端内免登（M36 工作台应用）：动态加载 H5 JSSDK → requestAuthCode → 后端换身份 */
async function tryFeishuAppLogin(): Promise<
  | { status: 'active'; token: string; user: import('../api/types').AuthUser }
  | { status: 'pending'; pending_token: string; display_name: string }
  | null
> {
  if (!/Lark|Feishu/i.test(navigator.userAgent)) return null;
  try {
    const cfgRes = await fetch('/api/auth/feishu/client-config');
    const cfg = (await cfgRes.json())?.data;
    if (!cfg?.enabled || !cfg?.app_id) return null;
    await new Promise<void>((resolve, reject) => {
      if ((window as any).h5sdk) return resolve();
      const sc = document.createElement('script');
      sc.src = 'https://lf-scm-cn.feishucdn.com/lark/op/h5-js-sdk-1.5.35.js';
      sc.onload = () => resolve();
      sc.onerror = () => reject(new Error('sdk load failed'));
      document.head.appendChild(sc);
    });
    const code = await new Promise<string>((resolve, reject) => {
      const h5sdk = (window as any).h5sdk;
      const tt = (window as any).tt;
      if (!h5sdk || !tt) return reject(new Error('sdk unavailable'));
      h5sdk.error(reject);
      h5sdk.ready(() => {
        tt.requestAuthCode({
          appId: cfg.app_id,
          success: (r: { code: string }) => resolve(r.code),
          fail: reject,
        });
      });
    });
    const res = await fetch('/api/auth/feishu/app-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    });
    const env = await res.json();
    if (!res.ok || !env?.success) return null;
    return env.data;
  } catch {
    return null; // 免登失败静默回退普通登录页
  }
}

export default function Login() {
  const [loading, setLoading] = useState(false);
  const [feishuOpen, setFeishuOpen] = useState(false);
  const [feishuLoading, setFeishuLoading] = useState(false);
  const [feishuStarting, setFeishuStarting] = useState(false);
  const [feishuForm] = Form.useForm<FeishuForm>();
  const navigate = useNavigate();
  const { token, user, setAuth } = useAuthStore();
  const t = useT();
  const [appLoginTrying, setAppLoginTrying] = useState(/Lark|Feishu/i.test(navigator.userAgent));

  useEffect(() => {
    if (token || !appLoginTrying) return;
    void tryFeishuAppLogin().then((data) => {
      if (!data) {
        setAppLoginTrying(false);
        return;
      }
      if (data.status === 'active') {
        setAuth(data.token, data.user);
        navigate(firstAccessiblePath(data.user), { replace: true });
      } else {
        localStorage.setItem('aom-pending-token', data.pending_token);
        localStorage.setItem('aom-pending-name', data.display_name);
        navigate('/onboarding/pending', { replace: true });
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (token) {
    return <Navigate to={firstAccessiblePath(user)} replace />;
  }

  const onFinish = async (values: LoginForm) => {
    setLoading(true);
    try {
      const result = await api.post<LoginResult>('/auth/login', values);
      setAuth(result.token, result.user);
      // M19：落到该用户第一个有权限的页面（业务用户=服务请求），而不是写死总览
      navigate(firstAccessiblePath(result.user), { replace: true });
    } catch (err) {
      // 401 由拦截器静默处理（登录页不跳转），在此提示；其余错误拦截器已提示
      if (isAxiosError<Envelope>(err) && err.response?.status === 401) {
        message.error(err.response.data?.error?.message || t('login.failed'));
      }
    } finally {
      setLoading(false);
    }
  };

  // 飞书扫码入口：真实飞书优先——取授权 URL 整页跳转；未启用(501/FEISHU_NOT_ENABLED)则回退模拟扫码 Modal
  const onFeishuClick = async () => {
    setFeishuStarting(true);
    try {
      const redirectUri = window.location.origin + '/login/feishu-callback';
      const res = await fetch('/api/auth/feishu/authorize-url?redirect_uri=' + encodeURIComponent(redirectUri));
      const env = (await res.json().catch(() => undefined)) as Envelope<{ url: string }> | undefined;
      if (res.ok && env?.success && env.data?.url) {
        window.location.href = env.data.url; // 整页跳转飞书扫码授权页
        return;
      }
      if (res.status === 501 || env?.error?.code === 'FEISHU_NOT_ENABLED') {
        setFeishuOpen(true); // 真实飞书未启用：打开模拟扫码
      } else {
        message.error(env?.error?.message || t('common.requestFailed'));
      }
    } catch {
      message.error(t('common.requestFailed'));
    } finally {
      setFeishuStarting(false);
    }
  };

  // 飞书扫码（模拟）：原生 fetch 调用公共端点，绕过 axios 的 token 注入与全局 401 跳转
  const onFeishuScan = async () => {
    const values = await feishuForm.validateFields();
    setFeishuLoading(true);
    try {
      const res = await fetch('/api/auth/feishu/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          external_id: values.external_id.trim(),
          display_name: values.display_name.trim(),
        }),
      });
      const env = (await res.json()) as Envelope<FeishuScanResult>;
      if (!res.ok || !env.success || !env.data) {
        message.error(env?.error?.message || t('common.requestFailed'));
        return;
      }
      const data = env.data;
      if (data.status === 'active') {
        setFeishuOpen(false);
        setAuth(data.token, data.user);
        navigate(firstAccessiblePath(data.user), { replace: true });
      } else {
        // pending：暂存 pending 凭据，进过渡页轮询开通结果
        localStorage.setItem('aom-pending-token', data.pending_token);
        localStorage.setItem('aom-pending-name', data.display_name);
        setFeishuOpen(false);
        navigate('/onboarding/pending');
      }
    } catch {
      message.error(t('common.requestFailed'));
    } finally {
      setFeishuLoading(false);
    }
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
      <Card style={{ width: 380, boxShadow: '0 2px 8px rgba(0,0,0,0.09)' }}>
        <Typography.Title level={3} style={{ textAlign: 'center', marginBottom: 8 }}>
          {t('app.title')}
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center' }}>
          {t('app.subtitle')}
        </Typography.Paragraph>
        <Form<LoginForm> onFinish={(v) => void onFinish(v)} size="large">
          <Form.Item name="username" rules={[{ required: true, message: t('login.usernameRequired') }]}>
            <Input prefix={<UserOutlined />} placeholder={t('login.username')} autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: t('login.passwordRequired') }]}>
            <Input.Password
              prefix={<LockOutlined />}
              placeholder={t('login.password')}
              autoComplete="current-password"
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" block loading={loading}>
              {t('login.submit')}
            </Button>
          </Form.Item>
        </Form>

        <Divider plain style={{ color: 'rgba(0,0,0,0.45)' }}>
          {t('login.orDivider')}
        </Divider>
        <Button block icon={<QrcodeOutlined />} loading={feishuStarting} onClick={() => void onFeishuClick()}>
          {t('login.feishu')}
        </Button>
      </Card>

      <Modal
        title={t('login.feishuScanTitle')}
        open={feishuOpen}
        onOk={() => void onFeishuScan()}
        okText={t('login.feishuGo')}
        cancelText={t('common.cancel')}
        confirmLoading={feishuLoading}
        onCancel={() => setFeishuOpen(false)}
        destroyOnClose
      >
        <Typography.Paragraph type="secondary">{t('login.feishuScanHint')}</Typography.Paragraph>
        <Form<FeishuForm> form={feishuForm} layout="vertical" preserve={false}>
          <Form.Item
            name="display_name"
            label={t('login.feishuName')}
            rules={[{ required: true, message: t('login.feishuName') }]}
          >
            <Input maxLength={50} autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="external_id"
            label={t('login.feishuId')}
            rules={[{ required: true, message: t('login.feishuId') }]}
          >
            <Input maxLength={100} autoComplete="off" placeholder={t('login.feishuIdPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
