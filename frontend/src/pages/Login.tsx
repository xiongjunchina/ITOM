import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Button, Card, Form, Input, Typography, message } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { isAxiosError } from 'axios';
import { api } from '../api/client';
import type { Envelope, LoginResult } from '../api/types';
import { useAuthStore } from '../stores/auth';

interface LoginForm {
  username: string;
  password: string;
}

export default function Login() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { token, setAuth } = useAuthStore();

  if (token) {
    return <Navigate to="/dashboard" replace />;
  }

  const onFinish = async (values: LoginForm) => {
    setLoading(true);
    try {
      const result = await api.post<LoginResult>('/auth/login', values);
      setAuth(result.token, result.user);
      navigate('/dashboard', { replace: true });
    } catch (err) {
      // 401 由拦截器静默处理（登录页不跳转），在此提示；其余错误拦截器已提示
      if (isAxiosError<Envelope>(err) && err.response?.status === 401) {
        message.error(err.response.data?.error?.message || '用户名或密码错误');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f0f2f5',
      }}
    >
      <Card style={{ width: 380, boxShadow: '0 2px 8px rgba(0,0,0,0.09)' }}>
        <Typography.Title level={3} style={{ textAlign: 'center', marginBottom: 8 }}>
          IT运营管理平台
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center' }}>
          IT服务、项目、需求、团队一站式管理平台
        </Typography.Paragraph>
        <Form<LoginForm> onFinish={(v) => void onFinish(v)} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="密码"
              autoComplete="current-password"
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
