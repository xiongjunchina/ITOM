import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Divider, Input, Select, Space, Spin, Switch, Table, Tag, Typography, message } from 'antd';
import { ApiOutlined, SaveOutlined, SyncOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import { runOrgSyncAndWait } from '../../utils/orgSync';
import { useT } from '../../i18n';
import { useAuthStore } from '../../stores/auth';
import type { FeishuConfig, FeishuHelpdeskIntake, FeishuHelpdeskSyncEvent, FeishuSyncStats, OrgSettings } from '../../api/types';

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
  scope_names?: string[] | null;
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
  const [helpdeskId, setHelpdeskId] = useState('');
  const [helpdeskToken, setHelpdeskToken] = useState('');
  const [helpdeskEnabled, setHelpdeskEnabled] = useState(false);
  const [helpdeskVerificationToken, setHelpdeskVerificationToken] = useState('');
  const [helpdeskEventUrl, setHelpdeskEventUrl] = useState('');
  const [helpdeskTicketId, setHelpdeskTicketId] = useState('');
  const [helpdeskTesting, setHelpdeskTesting] = useState(false);
  const [helpdeskSubscribing, setHelpdeskSubscribing] = useState(false);
  const [syncScope, setSyncScope] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [autoSyncEnabled, setAutoSyncEnabled] = useState(false);
  const [autoSyncInterval, setAutoSyncInterval] = useState(1440);
  const [intakes, setIntakes] = useState<FeishuHelpdeskIntake[]>([]);
  const [syncEvents, setSyncEvents] = useState<FeishuHelpdeskSyncEvent[]>([]);
  const [queueLoading, setQueueLoading] = useState(false);

  // 需在飞书开放平台登记的重定向 URL（动态取当前站点）
  const redirectUri = window.location.origin + '/login/feishu-callback';
  const defaultHelpdeskEventUrl = window.location.origin + '/api/integrations/feishu/helpdesk/events';

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, settings] = await Promise.all([
        api.get<FeishuConfig>('/admin/feishu-config'),
        api.get<OrgSettings>('/admin/org-settings'),
      ]);
      setConfig(c);
      setApiBase(c.api_base || DEFAULT_API_BASE);
      setAppId(c.app_id ?? '');
      setHelpdeskId(c.helpdesk_id ?? '');
      setHelpdeskEnabled(!!c.helpdesk_enabled);
      setHelpdeskEventUrl(c.helpdesk_event_url || defaultHelpdeskEventUrl);
      setSyncScope(c.sync_scope ?? '');
      setEnabled(!!c.enabled);
      setAutoSyncEnabled(settings.feishu_auto_sync_enabled);
      setAutoSyncInterval(settings.feishu_auto_sync_interval_minutes);
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

  const loadQueue = useCallback(async () => {
    if (!isAdmin) return;
    setQueueLoading(true);
    try {
      const [intakeResult, eventResult] = await Promise.all([
        api.getList<FeishuHelpdeskIntake>('/integrations/feishu/helpdesk/intakes', { page: 1, page_size: 20 }),
        api.getList<FeishuHelpdeskSyncEvent>('/integrations/feishu/helpdesk/sync-events', { page: 1, page_size: 20 }),
      ]);
      setIntakes(intakeResult.items);
      setSyncEvents(eventResult.items);
    } catch {
      // 非 IT 管理角色无权查看队列时，配置页仍可正常使用。
    } finally {
      setQueueLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        api_base: apiBase.trim() || DEFAULT_API_BASE,
        app_id: appId.trim(),
        sync_scope: syncScope.trim(),
        enabled,
        helpdesk_id: helpdeskId.trim() || null,
        helpdesk_enabled: helpdeskEnabled,
        helpdesk_event_url: helpdeskEventUrl.trim() || defaultHelpdeskEventUrl,
      };
      const secret = appSecret.trim();
      if (secret) body.app_secret = secret; // 留空不传 = 不修改已存密钥
      const serviceDeskToken = helpdeskToken.trim();
      if (serviceDeskToken) body.helpdesk_token = serviceDeskToken;
      const verificationToken = helpdeskVerificationToken.trim();
      if (verificationToken) body.helpdesk_event_verification_token = verificationToken;
      await api.put('/admin/feishu-config', body);
      await api.patch('/admin/org-settings', {
        feishu_auto_sync_enabled: autoSyncEnabled,
        feishu_auto_sync_interval_minutes: autoSyncInterval,
      });
      message.success(t('feishu.saved'));
      void load();
      void loadQueue();
    } catch {
      // FEISHU_CONFIG_INCOMPLETE 等后端错误已由拦截器统一提示
    } finally {
      setSaving(false);
    }
  };

  const handleHelpdeskTest = async () => {
    const ticketId = helpdeskTicketId.trim();
    if (!ticketId) {
      message.warning('请输入飞书工单 ID');
      return;
    }
    setHelpdeskTesting(true);
    try {
      const r = await api.post<{ title?: string; status?: string; stage?: string; guest?: { name?: string }; field_keys?: string[] }>(
        '/admin/feishu-config/test-helpdesk',
        { ticket_id: ticketId },
      );
      message.success(`服务台连接成功：${r.title || ticketId}（${r.guest?.name || '未知用户'}）`);
    } catch {
      // 统一错误提示
    } finally {
      setHelpdeskTesting(false);
    }
  };

  const handleHelpdeskSubscribe = async () => {
    setHelpdeskSubscribing(true);
    try {
      const result = await api.post<{ subscribed: boolean; status: string; error?: string }>(
        '/admin/feishu-config/subscribe-helpdesk-events',
      );
      if (result.subscribed) {
        message.success('服务台事件订阅成功；请确认飞书事件已添加并发布应用');
      } else {
        message.error(`服务台事件订阅未成功：${result.error || result.status}`);
      }
      await load();
    } finally {
      setHelpdeskSubscribing(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    try {
      const r = await api.post<FeishuTestResult>('/admin/feishu-config/test');
      const scope = r.scope_names?.length ? t('feishu.testOkDept', { name: r.scope_names.join('、') }) : '';
      message.success(t('feishu.testOk') + scope);
    } catch {
      // 失败已统一提示（msg 带飞书上游错误）
    } finally {
      setTesting(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    message.info(t('admin.org.syncStarted'));
    try {
      // M35：后台执行+轮询完成（全公司同步耗时较长）
      await runOrgSyncAndWait('feishu');
      message.success(t('feishu.syncDone'));
      void load(); // 刷新 last_sync_at / last_sync_stats 展示本次统计
    } catch (e) {
      message.error((e as Error).message || t('common.requestFailed'));
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
          <Typography.Text>{t('feishu.syncScope')}</Typography.Text>
          <Input.TextArea
            value={syncScope}
            disabled={disabled}
            placeholder="od-xxx, od-yyy 或 0"
            autoSize={{ minRows: 1, maxRows: 3 }}
            onChange={(e) => setSyncScope(e.target.value)}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
            {t('feishu.syncScopeHint')}
          </Typography.Text>
        </div>
        <Space>
          <Switch checked={enabled} disabled={disabled} onChange={setEnabled} />
          <Typography.Text>{t('feishu.enabled')}</Typography.Text>
        </Space>
        <Space>
          <Switch checked={autoSyncEnabled} disabled={disabled || !enabled} onChange={setAutoSyncEnabled} />
          <Typography.Text>{t('feishu.autoSync')}</Typography.Text>
        </Space>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text>{t('feishu.syncFrequency')}</Typography.Text>
          <Select
            value={autoSyncInterval}
            disabled={disabled || !autoSyncEnabled || !enabled}
            onChange={setAutoSyncInterval}
            options={[
              { value: 60, label: t('feishu.everyHour') },
              { value: 360, label: t('feishu.every6Hours') },
              { value: 720, label: t('feishu.every12Hours') },
              { value: 1440, label: t('feishu.everyDay') },
            ]}
          />
        </div>
      </Space>

      <Divider />

      {/* 服务台接入 */}
      <Typography.Title level={5}>飞书 IT 服务台</Typography.Title>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12, maxWidth: 720 }}
        message="服务台 Token 仅保存于后端并加密，不会返回浏览器；事件回调地址需在飞书开放平台配置。"
      />
      <Space direction="vertical" size={12} style={{ width: '100%', maxWidth: 720 }}>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text>服务台 ID</Typography.Text>
          <Input value={helpdeskId} disabled={disabled} placeholder="例如 7667139085051383050" onChange={(e) => setHelpdeskId(e.target.value)} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text>服务台 Token</Typography.Text>
          <Input.Password
            value={helpdeskToken}
            disabled={disabled}
            placeholder={config?.has_helpdesk_token ? '已配置，留空表示不修改' : 'Helpdesk Token'}
            onChange={(e) => setHelpdeskToken(e.target.value)}
            autoComplete="new-password"
          />
        </div>
        <Space>
          <Switch checked={helpdeskEnabled} disabled={disabled} onChange={setHelpdeskEnabled} />
          <Typography.Text>启用服务台 API 接入</Typography.Text>
        </Space>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text>事件回调地址</Typography.Text>
          <Input value={helpdeskEventUrl} disabled={disabled} placeholder={defaultHelpdeskEventUrl} onChange={(e) => setHelpdeskEventUrl(e.target.value)} />
          <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
            ITOM 已按当前访问域名生成默认地址；如通过反向代理对外提供服务，请确认该地址能从飞书公网访问。
          </Typography.Text>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text>事件订阅 Verification Token</Typography.Text>
          <Input.Password value={helpdeskVerificationToken} disabled={disabled} placeholder="已配置时留空表示不修改" onChange={(e) => setHelpdeskVerificationToken(e.target.value)} autoComplete="new-password" />
        </div>
        <Space.Compact style={{ width: '100%' }}>
          <Input value={helpdeskTicketId} disabled={disabled} placeholder="输入一张真实飞书工单 ID 进行连接测试" onChange={(e) => setHelpdeskTicketId(e.target.value)} />
          <Button icon={<ApiOutlined />} loading={helpdeskTesting} disabled={disabled || !helpdeskEnabled} onClick={() => void handleHelpdeskTest()}>测试服务台</Button>
        </Space.Compact>
        <Space wrap>
          <Button icon={<ApiOutlined />} loading={helpdeskSubscribing} disabled={disabled || !helpdeskEnabled} onClick={() => void handleHelpdeskSubscribe()}>
            订阅服务台事件
          </Button>
          <Tag color={config?.helpdesk_event_subscription_status === 'subscribed' ? 'green' : config?.helpdesk_event_subscription_status === 'failed' ? 'red' : 'default'}>
            事件订阅：{config?.helpdesk_event_subscription_status === 'subscribed' ? '已成功' : config?.helpdesk_event_subscription_status === 'failed' ? '失败' : config?.helpdesk_event_subscription_status === 'waiting_config' ? '等待应用配置' : '未注册'}
          </Tag>
          {config?.helpdesk_event_subscription_at && <Typography.Text type="secondary">{dayjs(config.helpdesk_event_subscription_at).format('YYYY-MM-DD HH:mm:ss')}</Typography.Text>}
        </Space>
        {config?.helpdesk_event_subscription_error && (
          <Alert type="warning" showIcon style={{ maxWidth: 720 }} message={config.helpdesk_event_subscription_error} />
        )}
        <Typography.Text type="secondary" style={{ fontSize: 12, maxWidth: 720 }}>
          订阅成功后，还需在飞书开放平台添加并发布：helpdesk.ticket.created_v1、helpdesk.ticket.updated_v1、helpdesk.ticket_message.created_v1。飞书目前没有独立的 rated 事件，评价会随工单更新事件重新读取。
        </Typography.Text>
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

      {/* 待分流与可靠同步队列：只对 IT 管理角色展示，便于运营人员处理人工客服后的分流。 */}
      {isAdmin && (
        <>
          <Typography.Title level={5}>待分流记录与同步队列</Typography.Title>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12, maxWidth: 900 }}
            message="人工客服完成初步沟通后，记录保持为“待分流”；员工在飞书选择创建服务请求或登记 IT 需求后，才会建立 ITOM 正式单据。队列失败会自动重试。"
          />
          <Space style={{ marginBottom: 12 }}>
            <Button icon={<SyncOutlined />} loading={queueLoading} onClick={() => void loadQueue()}>刷新队列</Button>
            <Typography.Text type="secondary">待分流 {intakes.filter((item) => item.classification === 'pending').length} 条 · 入站事件 {syncEvents.length} 条</Typography.Text>
          </Space>
          <Table<FeishuHelpdeskIntake>
            rowKey="id"
            size="small"
            loading={queueLoading}
            dataSource={intakes}
            pagination={false}
            scroll={{ x: 1160 }}
            columns={[
              { title: '飞书工单', dataIndex: 'ticket_id', width: 180 },
              { title: '申请人', dataIndex: 'guest_name', width: 120, render: (value: string | null) => value || '-' },
              { title: '客服', dataIndex: 'agent_name', width: 120, render: (value: string | null) => value || '待分派' },
              {
                title: '分流状态', dataIndex: 'classification', width: 120,
                render: (value: string) => <Tag color={value === 'pending' ? 'gold' : value === 'cancelled' ? 'default' : 'green'}>{value === 'pending' ? '待分流' : value === 'service_request' ? '服务请求' : value === 'requirement' ? 'IT需求' : value === 'cancelled' ? '已取消' : value}</Tag>,
              },
              { title: '飞书阶段', dataIndex: 'feishu_stage', width: 120, render: (value: string | null) => value || '-' },
              {
                title: '分流入口', dataIndex: 'routing_prompt_channel', width: 190,
                render: (value: string | null, row) => {
                  const label = value === 'helpdesk_post' ? '原会话富文本' : value === 'helpdesk_text' ? '原会话文本' : value === 'im_card_fallback' ? '独立机器人兜底' : '待发送';
                  return <Space direction="vertical" size={0}><Tag color={value === 'im_card_fallback' ? 'orange' : value ? 'blue' : 'default'}>{label}</Tag><Typography.Text type="secondary">{row.routing_prompt_sent_at ? dayjs(row.routing_prompt_sent_at).format('YYYY-MM-DD HH:mm:ss') : '-'}</Typography.Text></Space>;
                },
              },
              { title: 'ITOM关联单据', dataIndex: 'linked_entity_id', width: 220, render: (value: string | null, row) => value ? `${row.linked_entity_type === 'ticket' ? '服务请求' : 'IT需求'} · ${value}` : '-' },
              { title: '最近同步', dataIndex: 'last_synced_at', width: 180, render: (value: string | null) => value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-' },
            ]}
          />
          <Typography.Title level={5} style={{ marginTop: 20 }}>最近入站事件</Typography.Title>
          <Table<FeishuHelpdeskSyncEvent>
            rowKey="id"
            size="small"
            loading={queueLoading}
            dataSource={syncEvents}
            pagination={false}
            scroll={{ x: 980 }}
            columns={[
              { title: '事件类型', dataIndex: 'event_type', width: 260 },
              { title: '飞书工单', dataIndex: 'ticket_id', width: 180, render: (value: string | null) => value || '-' },
              { title: '状态', dataIndex: 'status', width: 120, render: (value: string) => <Tag color={value === 'processed' ? 'green' : value === 'failed' ? 'red' : 'blue'}>{value}</Tag> },
              { title: '重试次数', dataIndex: 'attempts', width: 100 },
              { title: '错误', dataIndex: 'last_error', render: (value: string | null) => value || '-' },
            ]}
          />
          <Divider />
        </>
      )}

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
