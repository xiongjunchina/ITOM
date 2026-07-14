import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Divider, Input, Space, Spin, Switch, Tag, Typography, message } from 'antd';
import { ApiOutlined, SaveOutlined, SyncOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import { useAuthStore } from '../../stores/auth';
import type { FeishuConfig, FeishuSyncStats } from '../../api/types';

const DEFAULT_API_BASE = 'https://open.feishu.cn';

/** 同步统计字段 → 文案键 + Tag 颜色（新增绿 / 更新蓝 / 停用橙 / 离职红） */
const STAT_META: { key: keyof FeishuSyncStats; label: string; color: string }[] = [
  { key: 'dept_created', label: 'feishu.statDeptCreated', color: 'green' },
  { key: 'dept_updated', label: 'feishu.statDeptUpdated', color: 'blue' },
  { key: 'dept_deactivated', label: 'feishu.statDeptDeactivated', color: 'orange' },
  { key: 'member_created', label: 'feishu.statMemberCreated', color: 'green' },
  { key: 'member_updated', label: 'feishu.statMemberUpdated', color: 'blue' },
  { key: 'member_left', label: 'feishu.statMemberLeft', color: 'red' },
];

/** POST /admin/feishu-config/test 结果 */
interface FeishuTestResult {
  connected: boolean;
  it_department_name?: string | null;
}

export default function FeishuIntegration() {
  const t = useT();
  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user?.permissions?.['*'] || !!user?.roles?.includes('admin');

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [config, setConfig] = useState<FeishuConfig | null>(null);

  // 表单态（app_secret 仅本地输入：留空 = 保持后端已存密钥不变）
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [appId, setAppId] = useState('');
  const [appSecret, setAppSecret] = useState('');
  const [itDeptId, setItDeptId] = useState('');
  const [enabled, setEnabled] = useState(false);

  // 需在飞书开放平台登记的重定向 URL（动态取当前站点）
  const redirectUri = window.location.origin + '/login/feishu-callback';

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const c = await api.get<FeishuConfig>('/admin/feishu-config');
      setConfig(c);
      setApiBase(c.api_base || DEFAULT_API_BASE);
      setAppId(c.app_id ?? '');
      setItDeptId(c.it_department_id ?? '');
      setEnabled(!!c.enabled);
      setAppSecret(''); // 密钥不回显，输入框留空
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        api_base: apiBase.trim() || DEFAULT_API_BASE,
        app_id: appId.trim(),
        it_department_id: itDeptId.trim(),
        enabled,
      };
      const secret = appSecret.trim();
      if (secret) body.app_secret = secret; // 留空不传 = 不修改已存密钥
      await api.put('/admin/feishu-config', body);
      message.success(t('feishu.saved'));
      void load();
    } catch {
      // FEISHU_CONFIG_INCOMPLETE 等后端错误已由拦截器统一提示
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    try {
      const r = await api.post<FeishuTestResult>('/admin/feishu-config/test');
      const dept = r.it_department_name ? t('feishu.testOkDept', { name: r.it_department_name }) : '';
      message.success(t('feishu.testOk') + dept);
    } catch {
      // 失败已统一提示（msg 带飞书上游错误）
    } finally {
      setTesting(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    try {
      await api.post('/admin/org-sync', { source: 'feishu' });
      message.success(t('feishu.syncDone'));
      void load(); // 刷新 last_sync_at / last_sync_stats 展示本次统计
    } catch {
      // 已统一提示
    } finally {
      setSyncing(false);
    }
  };

  if (loading) {
    return (
      <Card title={t('feishu.title')}>
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin size="large" />
        </div>
      </Card>
    );
  }

  const disabled = !isAdmin;
  const stats = config?.last_sync_stats;

  return (
    <Card
      title={t('feishu.title')}
      extra={
        isAdmin && (
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={() => void handleSave()}>
            {t('common.save')}
          </Button>
        )
      }
    >
      {!isAdmin && <Alert type="info" showIcon style={{ marginBottom: 16 }} message={t('feishu.readonly')} />}

      {/* 应用配置 */}
      <Typography.Title level={5}>{t('feishu.appConfig')}</Typography.Title>
      <Alert type="info" showIcon style={{ marginBottom: 12, maxWidth: 720 }} message={t('feishu.sharedHint')} />
      <Space direction="vertical" size={12} style={{ width: '100%', maxWidth: 480 }}>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text>{t('feishu.apiBase')}</Typography.Text>
          <Input
            value={apiBase}
            disabled={disabled}
            placeholder={DEFAULT_API_BASE}
            onChange={(e) => setApiBase(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text>App ID</Typography.Text>
          <Input
            value={appId}
            disabled={disabled}
            placeholder="cli_xxx"
            onChange={(e) => setAppId(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text>App Secret</Typography.Text>
          <Input.Password
            value={appSecret}
            disabled={disabled}
            placeholder={config?.has_secret ? t('feishu.secretConfigured') : 'App Secret'}
            onChange={(e) => setAppSecret(e.target.value)}
            autoComplete="new-password"
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text>{t('feishu.itDeptId')}</Typography.Text>
          <Input
            value={itDeptId}
            disabled={disabled}
            placeholder="od-xxx"
            onChange={(e) => setItDeptId(e.target.value)}
            autoComplete="off"
          />
          <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
            {t('feishu.itDeptIdHint')}
          </Typography.Text>
        </div>
        <Space>
          <Switch checked={enabled} disabled={disabled} onChange={setEnabled} />
          <Typography.Text>{t('feishu.enabled')}</Typography.Text>
        </Space>
      </Space>

      <Divider />

      {/* 连接与同步 */}
      <Typography.Title level={5}>{t('feishu.connSync')}</Typography.Title>
      <Space wrap>
        <Button icon={<ApiOutlined />} loading={testing} disabled={disabled} onClick={() => void handleTest()}>
          {t('feishu.test')}
        </Button>
        <Button
          icon={<SyncOutlined />}
          loading={syncing}
          disabled={disabled || !config?.enabled}
          onClick={() => void handleSync()}
        >
          {t('feishu.syncNow')}
        </Button>
        {!config?.enabled && <Typography.Text type="secondary">{t('feishu.syncNeedEnabled')}</Typography.Text>}
      </Space>
      <div style={{ marginTop: 12 }}>
        <Typography.Text type="secondary">
          {config?.last_sync_at
            ? t('feishu.lastSyncAt', { time: dayjs(config.last_sync_at).format('YYYY-MM-DD HH:mm:ss') })
            : t('feishu.neverSynced')}
        </Typography.Text>
        {stats && (
          <div style={{ marginTop: 8 }}>
            <Space wrap size={8}>
              {STAT_META.map((m) => (
                <Tag key={m.key} color={m.color}>
                  {t(m.label)} {stats[m.key] ?? 0}
                </Tag>
              ))}
            </Space>
          </div>
        )}
      </div>

      <Divider />

      {/* 接入说明 */}
      <Typography.Title level={5}>{t('feishu.guide')}</Typography.Title>
      <Alert
        type="info"
        message={
          <ol style={{ margin: 0, paddingInlineStart: 20 }}>
            <li>{t('feishu.guide1')}</li>
            <li>{t('feishu.guide2')}</li>
            <li>
              {t('feishu.guide3')}{' '}
              <Typography.Text code copyable={{ text: redirectUri }}>
                {redirectUri}
              </Typography.Text>
            </li>
            <li>{t('feishu.guide4')}</li>
          </ol>
        }
      />
    </Card>
  );
}
