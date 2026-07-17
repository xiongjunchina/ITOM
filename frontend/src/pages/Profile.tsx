import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Alert,
  Avatar,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Select,
  Space,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import { UserOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../api/client';
import type { ProfileData } from '../api/types';
import { useAuthStore } from '../stores/auth';
import { useLangStore, type Lang } from '../i18n/store';
import { useT } from '../i18n';

/** 头像本地压缩：居中裁方 → 256px JPEG data URL（后端仅兜底校验大小/格式） */
function fileToAvatar(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const size = 256;
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        URL.revokeObjectURL(url);
        reject(new Error('canvas'));
        return;
      }
      const min = Math.min(img.width, img.height);
      ctx.drawImage(img, (img.width - min) / 2, (img.height - min) / 2, min, min, 0, 0, size, size);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL('image/jpeg', 0.85));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('bad image'));
    };
    img.src = url;
  });
}

export default function Profile() {
  const t = useT();
  const { user, setUser } = useAuthStore();
  const setLang = useLangStore((s) => s.setLang);
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<ProfileData | null>(null);
  const [prefForm] = Form.useForm<{ bio?: string; language: Lang }>();
  const [savingPref, setSavingPref] = useState(false);
  const [pwdForm] = Form.useForm<{ current_password?: string; new_password: string; confirm: string }>();
  const [savingPwd, setSavingPwd] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.get<ProfileData>('/auth/me/profile');
      setData(res);
      prefForm.setFieldsValue({ bio: res.preferences.bio ?? undefined, language: res.preferences.language });
    } catch {
      // 已统一提示
    }
  }, [prefForm]);

  useEffect(() => {
    void load();
  }, [load]);

  const displayName = data?.person?.name || user?.name || user?.username || '';

  const saveAvatar = async (avatar: string | null) => {
    try {
      await api.patch('/auth/me/preferences', { avatar });
      if (user) setUser({ ...user, avatar });
      setData((prev) => (prev ? { ...prev, preferences: { ...prev.preferences, avatar } } : prev));
      message.success(t('profile.saved'));
    } catch {
      // 已统一提示
    }
  };

  const onPickAvatar = async (file: File) => {
    if (file.size > 10 * 1024 * 1024) {
      message.error(t('profile.avatarTooLarge'));
      return false;
    }
    try {
      const avatar = await fileToAvatar(file);
      await saveAvatar(avatar);
    } catch {
      message.error(t('profile.avatarBad'));
    }
    return false; // 阻止 antd 默认上传
  };

  const savePreferences = async () => {
    const values = await prefForm.validateFields();
    setSavingPref(true);
    try {
      await api.patch('/auth/me/preferences', { bio: values.bio ?? '', language: values.language });
      setLang(values.language); // 立即生效，与登录时应用逻辑一致
      message.success(t('profile.saved'));
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSavingPref(false);
    }
  };

  const changePassword = async () => {
    const values = await pwdForm.validateFields();
    setSavingPwd(true);
    try {
      await api.post('/auth/me/password', {
        current_password: values.current_password || undefined,
        new_password: values.new_password,
      });
      message.success(t('profile.passwordChanged'));
      pwdForm.resetFields();
      void load(); // password_set 状态翻转（首设后再改需验当前密码）
    } catch {
      // 已统一提示
    } finally {
      setSavingPwd(false);
    }
  };

  const account = data?.account;
  const person = data?.person;

  const basicTab = (
    <Space direction="vertical" size={16} style={{ display: 'flex' }}>
      <Card>
        <Space size={24} align="center">
          {data?.preferences.avatar ? (
            <Avatar size={80} src={data.preferences.avatar} />
          ) : (
            <Avatar size={80} style={{ backgroundColor: '#1677ff', fontSize: 32 }}>
              {displayName ? displayName[0] : <UserOutlined />}
            </Avatar>
          )}
          <Space direction="vertical" size={4}>
            <Space size={8}>
              <Typography.Title level={4} style={{ margin: 0 }}>
                {displayName}
              </Typography.Title>
              {account?.feishu_bound && <Tag color="blue">{t('profile.feishuBound')}</Tag>}
            </Space>
            {data?.preferences.bio ? (
              <Typography.Text type="secondary">{data.preferences.bio}</Typography.Text>
            ) : null}
            <Space size={8}>
              <Upload accept="image/*" showUploadList={false} beforeUpload={(f) => onPickAvatar(f)}>
                <Button size="small">{t('profile.avatarUpload')}</Button>
              </Upload>
              {data?.preferences.avatar && (
                <Button size="small" onClick={() => void saveAvatar(null)}>
                  {t('profile.avatarRemove')}
                </Button>
              )}
            </Space>
          </Space>
        </Space>
      </Card>

      <Card title={t('profile.account')}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label={t('profile.username')}>{account?.username || '-'}</Descriptions.Item>
          <Descriptions.Item label={t('profile.authSource')}>
            {account?.auth_source === 'feishu' ? t('profile.authFeishu') : t('profile.authLocal')}
          </Descriptions.Item>
          <Descriptions.Item label={t('profile.roles')} span={2}>
            {account?.roles.length
              ? account.roles.map((r) => (
                  <Tag key={r} color="blue">
                    {account.role_names[r] ?? r}
                  </Tag>
                ))
              : '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('profile.createdAt')}>
            {account?.created_at ? dayjs(account.created_at).format('YYYY-MM-DD HH:mm') : '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('profile.lastLogin')}>
            {account?.last_login_at ? dayjs(account.last_login_at).format('YYYY-MM-DD HH:mm') : '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('profile.passwordState')} span={2}>
            {account?.password_set ? (
              <Tag color="green">{t('profile.passwordSetYes')}</Tag>
            ) : (
              <Space size={8}>
                <Tag>{t('profile.passwordSetNo')}</Tag>
                <Typography.Text type="secondary">{t('profile.passwordSetNoHint')}</Typography.Text>
              </Space>
            )}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title={t('profile.person')} extra={<Typography.Text type="secondary">{person ? t('profile.personHint') : ''}</Typography.Text>}>
        {person ? (
          <Descriptions column={2} size="small">
            <Descriptions.Item label={t('profile.name')}>{person.name}</Descriptions.Item>
            <Descriptions.Item label={t('profile.employeeNo')}>{person.employee_no || '-'}</Descriptions.Item>
            <Descriptions.Item label={t('profile.department')}>{person.department_name || '-'}</Descriptions.Item>
            <Descriptions.Item label={t('profile.position')}>{person.position_name || '-'}</Descriptions.Item>
            <Descriptions.Item label={t('profile.email')}>{person.email || '-'}</Descriptions.Item>
            <Descriptions.Item label={t('profile.mobile')}>{person.mobile || '-'}</Descriptions.Item>
            <Descriptions.Item label={t('profile.hireDate')}>
              {person.hire_date ? dayjs(person.hire_date).format('YYYY-MM-DD') : '-'}
            </Descriptions.Item>
          </Descriptions>
        ) : (
          <Typography.Text type="secondary">{t('profile.noPerson')}</Typography.Text>
        )}
      </Card>

      <Card title={t('profile.personalization')}>
        <Form form={prefForm} layout="vertical" style={{ maxWidth: 480 }}>
          <Form.Item name="bio" label={t('profile.bio')}>
            <Input.TextArea rows={3} maxLength={500} showCount placeholder={t('profile.bioPlaceholder')} />
          </Form.Item>
          <Form.Item name="language" label={t('profile.language')} initialValue="zh">
            <Select
              options={[
                { value: 'zh', label: t('lang.zh') },
                { value: 'en', label: t('lang.en') },
              ]}
              style={{ width: 200 }}
            />
          </Form.Item>
          <Button type="primary" loading={savingPref} onClick={() => void savePreferences()}>
            {t('common.save')}
          </Button>
        </Form>
      </Card>
    </Space>
  );

  const securityTab = (
    <Card title={account?.password_set ? t('profile.changePassword') : t('profile.setPassword')} style={{ maxWidth: 560 }}>
      {account && !account.password_set && (
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message={t('profile.firstSetHint')} />
      )}
      <Form form={pwdForm} layout="vertical" style={{ maxWidth: 400 }}>
        {account?.password_set && (
          <Form.Item
            name="current_password"
            label={t('profile.currentPassword')}
            rules={[{ required: true, message: t('profile.currentPasswordRequired') }]}
          >
            <Input.Password maxLength={64} autoComplete="current-password" />
          </Form.Item>
        )}
        <Form.Item
          name="new_password"
          label={t('profile.newPassword')}
          extra={t('profile.passwordRule')}
          rules={[
            { required: true, message: t('profile.passwordRule') },
            { pattern: /^(?=.*[A-Za-z])(?=.*\d).{8,64}$/, message: t('profile.passwordRule') },
          ]}
        >
          <Input.Password maxLength={64} autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm"
          label={t('profile.confirmPassword')}
          dependencies={['new_password']}
          rules={[
            { required: true, message: t('profile.confirmPassword') },
            ({ getFieldValue }) => ({
              validator: (_, v) =>
                !v || v === getFieldValue('new_password')
                  ? Promise.resolve()
                  : Promise.reject(new Error(t('profile.passwordMismatch'))),
            }),
          ]}
        >
          <Input.Password maxLength={64} autoComplete="new-password" />
        </Form.Item>
        <Button type="primary" loading={savingPwd} onClick={() => void changePassword()}>
          {t('common.save')}
        </Button>
      </Form>
    </Card>
  );

  return (
    <Card title={t('profile.title')} styles={{ body: { paddingTop: 8 } }}>
      <Tabs
        activeKey={params.get('tab') === 'security' ? 'security' : 'basic'}
        onChange={(k) => setParams(k === 'security' ? { tab: 'security' } : {}, { replace: true })}
        items={[
          { key: 'basic', label: t('profile.tabBasic'), children: basicTab },
          { key: 'security', label: t('profile.tabSecurity'), children: securityTab },
        ]}
      />
    </Card>
  );
}
