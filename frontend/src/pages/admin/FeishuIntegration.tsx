import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Divider,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
  message,
} from 'antd';
import { ApiOutlined, DeleteOutlined, PlusOutlined, SaveOutlined, SyncOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import { runOrgSyncAndWait } from '../../utils/orgSync';
import { useT } from '../../i18n';
import { useAuthStore } from '../../stores/auth';
import SortableTable from '../../components/SortableTable';
import type {
  AdminUser,
  AilyConfig,
  AilyExternalIdentity,
  FeishuConfig,
  FeishuSyncStats,
  OrgSettings,
} from '../../api/types';

const DEFAULT_API_BASE = 'https://open.feishu.cn';

const normalizePublicBaseUrl = (value: string): string => {
  const trimmed = value.trim();
  if (!trimmed) return '';
  const parsed = new URL(trimmed);
  if (
    !['http:', 'https:'].includes(parsed.protocol)
    || !parsed.hostname
    || parsed.username
    || parsed.password
    || !['', '/'].includes(parsed.pathname)
    || parsed.search
    || parsed.hash
    || (parsed.port && (Number(parsed.port) < 1 || Number(parsed.port) > 65535))
  ) {
    throw new Error('公网访问根地址只能填写 http/https + 域名或 IP + 可选端口，不能包含路径、参数或片段');
  }
  return parsed.origin;
};

const STAT_META: { key: keyof FeishuSyncStats; label: string; color: string }[] = [
  { key: 'dept_created', label: 'feishu.statDeptCreated', color: 'green' },
  { key: 'dept_updated', label: 'feishu.statDeptUpdated', color: 'blue' },
  { key: 'dept_deactivated', label: 'feishu.statDeptDeactivated', color: 'orange' },
  { key: 'member_created', label: 'feishu.statMemberCreated', color: 'green' },
  { key: 'member_updated', label: 'feishu.statMemberUpdated', color: 'blue' },
  { key: 'member_left', label: 'feishu.statMemberLeft', color: 'red' },
];

interface FeishuTestResult {
  connected: boolean;
  scope_names?: string[] | null;
}

interface IdentityFormValues {
  tenant_id: string;
  app_id: string;
  subject_type: 'open_id' | 'user_id' | 'union_id';
  subject_id: string;
  auth_user_id: string;
}

const lines = (value: string): string[] =>
  value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);

export default function FeishuIntegration() {
  const t = useT();
  const user = useAuthStore((state) => state.user);
  const isAdmin = !!user?.permissions?.['*'] || !!user?.roles?.includes('admin');
  const disabled = !isAdmin;

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [config, setConfig] = useState<FeishuConfig | null>(null);
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [appId, setAppId] = useState('');
  const [appSecret, setAppSecret] = useState('');
  const [syncScope, setSyncScope] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [autoSyncEnabled, setAutoSyncEnabled] = useState(false);
  const [autoSyncInterval, setAutoSyncInterval] = useState(1440);

  const [ailySaving, setAilySaving] = useState(false);
  const [ailyConfig, setAilyConfig] = useState<AilyConfig | null>(null);
  const [ailyEnabled, setAilyEnabled] = useState(false);
  const [publicBaseUrl, setPublicBaseUrl] = useState('');
  const [publicBaseUrlError, setPublicBaseUrlError] = useState('');
  const [jwtSecret, setJwtSecret] = useState('');
  const [tenantIds, setTenantIds] = useState('');
  const [agentIds, setAgentIds] = useState('');
  const [origins, setOrigins] = useState('https://aily.feishu.cn');
  const [botAppId, setBotAppId] = useState('');
  const [botAppSecret, setBotAppSecret] = useState('');
  const [messageEnabled, setMessageEnabled] = useState(false);
  const [cardCallbackVerificationToken, setCardCallbackVerificationToken] = useState('');
  const [cardCallbackEncryptKey, setCardCallbackEncryptKey] = useState('');
  const [identities, setIdentities] = useState<AilyExternalIdentity[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [identityOpen, setIdentityOpen] = useState(false);
  const [identityEditingId, setIdentityEditingId] = useState<string>();
  const [identitySaving, setIdentitySaving] = useState(false);
  const [identityForm] = Form.useForm<IdentityFormValues>();
  const [testIdentityId, setTestIdentityId] = useState<string>();
  const [messageTesting, setMessageTesting] = useState(false);

  const publicBase = publicBaseUrl.trim().replace(/\/+$/, '');
  const publicMcpUrl = publicBase ? `${publicBase}${ailyConfig?.mcp_path || '/mcp/'}` : '';
  const redirectUri = publicBase ? `${publicBase}/login/feishu-callback` : '';
  const cardCallbackUrl = publicBase ? `${publicBase}${ailyConfig?.card_callback_path || '/api/integrations/feishu/card-actions'}` : '';

  const applyAilyConfig = (value: AilyConfig) => {
    setAilyConfig(value);
    setAilyEnabled(value.enabled);
    setPublicBaseUrl(value.public_base_url || '');
    setPublicBaseUrlError('');
    setTenantIds(value.allowed_tenant_ids.join('\n'));
    setAgentIds(value.allowed_agent_ids.join('\n'));
    setOrigins(value.allowed_origins.join('\n'));
    setBotAppId(value.bot_app_id || '');
    setMessageEnabled(value.message_enabled);
    setJwtSecret('');
    setBotAppSecret('');
    setCardCallbackVerificationToken('');
    setCardCallbackEncryptKey('');
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [feishu, settings, aily, identityRows, userRows] = await Promise.all([
        api.get<FeishuConfig>('/admin/feishu-config'),
        api.get<OrgSettings>('/admin/org-settings'),
        api.get<AilyConfig>('/admin/integrations/aily'),
        api.get<AilyExternalIdentity[]>('/admin/integrations/aily/identities'),
        api.getList<AdminUser>('/admin/users', { page: 1, page_size: 200 }),
      ]);
      setConfig(feishu);
      setApiBase(feishu.api_base || DEFAULT_API_BASE);
      setAppId(feishu.app_id || '');
      setSyncScope(feishu.sync_scope || '');
      setEnabled(feishu.enabled);
      setAutoSyncEnabled(settings.feishu_auto_sync_enabled);
      setAutoSyncInterval(settings.feishu_auto_sync_interval_minutes);
      setAppSecret('');
      applyAilyConfig(aily);
      setIdentities(identityRows);
      setUsers(userRows.items.filter((item) => item.is_active));
      setTestIdentityId((current) => current || identityRows.find((item) => item.status === 'active')?.id);
    } catch {
      // API 客户端已统一提示。
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
        sync_scope: syncScope.trim(),
        enabled,
      };
      if (appSecret.trim()) body.app_secret = appSecret.trim();
      await api.put('/admin/feishu-config', body);
      await api.patch('/admin/org-settings', {
        feishu_auto_sync_enabled: autoSyncEnabled,
        feishu_auto_sync_interval_minutes: autoSyncInterval,
      });
      message.success(t('feishu.saved'));
      await load();
    } catch {
      // API 客户端已统一提示。
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    try {
      const result = await api.post<FeishuTestResult>('/admin/feishu-config/test');
      const scope = result.scope_names?.length ? t('feishu.testOkDept', { name: result.scope_names.join('、') }) : '';
      message.success(t('feishu.testOk') + scope);
    } catch {
      // API 客户端已统一提示。
    } finally {
      setTesting(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    message.info(t('admin.org.syncStarted'));
    try {
      await runOrgSyncAndWait('feishu');
      message.success(t('feishu.syncDone'));
      await load();
    } catch (error) {
      message.error((error as Error).message || t('common.requestFailed'));
    } finally {
      setSyncing(false);
    }
  };

  const handleAilySave = async () => {
    let normalizedPublicBaseUrl = '';
    try {
      normalizedPublicBaseUrl = normalizePublicBaseUrl(publicBaseUrl);
      setPublicBaseUrlError('');
    } catch (error) {
      const detail = (error as Error).message || '公网访问根地址格式不正确';
      setPublicBaseUrlError(detail);
      message.error(detail);
      return;
    }
    setAilySaving(true);
    try {
      const body: Record<string, unknown> = {
        enabled: ailyEnabled,
        allowed_tenant_ids: lines(tenantIds),
        allowed_agent_ids: lines(agentIds),
        allowed_origins: lines(origins),
        bot_app_id: botAppId.trim() || null,
        api_base: DEFAULT_API_BASE,
        public_base_url: normalizedPublicBaseUrl || null,
        message_enabled: messageEnabled,
      };
      if (jwtSecret.trim()) body.mcp_jwt_secret = jwtSecret.trim();
      if (botAppSecret.trim()) body.bot_app_secret = botAppSecret.trim();
      if (cardCallbackVerificationToken.trim()) {
        body.card_callback_verification_token = cardCallbackVerificationToken.trim();
      }
      if (cardCallbackEncryptKey.trim()) {
        body.card_callback_encrypt_key = cardCallbackEncryptKey.trim();
      }
      const saved = await api.put<AilyConfig>('/admin/integrations/aily', body);
      applyAilyConfig(saved);
      message.success('Aily MCP 配置已保存');
    } catch {
      // API 客户端已统一提示。
    } finally {
      setAilySaving(false);
    }
  };

  const handleIdentityCreate = async () => {
    const values = await identityForm.validateFields();
    setIdentitySaving(true);
    try {
      if (identityEditingId) {
        await api.patch(`/admin/integrations/aily/identities/${identityEditingId}`, {
          auth_user_id: values.auth_user_id,
          status: 'active',
        });
        message.success('待映射身份已关联到 ITOM 账号；请确认其租户 ID 已加入白名单');
      } else {
        await api.post('/admin/integrations/aily/identities', { provider: 'feishu', ...values });
        message.success('外部身份映射已创建');
      }
      setIdentityOpen(false);
      setIdentityEditingId(undefined);
      identityForm.resetFields();
      await load();
    } catch {
      // 表单或 API 错误已由组件/API 客户端提示。
    } finally {
      setIdentitySaving(false);
    }
  };

  const openIdentityModal = (row?: AilyExternalIdentity) => {
    setIdentityEditingId(row?.id);
    if (row) {
      identityForm.setFieldsValue({
        tenant_id: row.tenant_id,
        app_id: row.app_id,
        subject_type: row.subject_type,
        subject_id: row.subject_id,
        auth_user_id: row.auth_user_id || undefined,
      });
    } else {
      identityForm.resetFields();
      identityForm.setFieldValue('subject_type', 'user_id');
    }
    setIdentityOpen(true);
  };

  const handleIdentityDelete = async (identityId: string) => {
    try {
      await api.delete(`/admin/integrations/aily/identities/${identityId}`);
      message.success('外部身份映射已删除');
      await load();
    } catch {
      // API 客户端已统一提示。
    }
  };

  const handleMessageTest = async () => {
    if (!testIdentityId) {
      message.warning('请先选择一个有效身份映射');
      return;
    }
    setMessageTesting(true);
    try {
      await api.post('/admin/integrations/aily/test-message', { identity_id: testIdentityId });
      message.success('Aily 主动消息发送成功');
      await load();
    } catch {
      // API 客户端已统一提示。
    } finally {
      setMessageTesting(false);
    }
  };

  if (loading) {
    return (
      <Card title={t('feishu.title')}>
        <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
      </Card>
    );
  }

  const stats = config?.last_sync_stats;

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {!isAdmin && <Alert type="info" showIcon message={t('feishu.readonly')} />}

      <Card
        title="飞书基础应用与组织同步"
        extra={isAdmin && <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={() => void handleSave()}>{t('common.save')}</Button>}
      >
        <Alert type="info" showIcon style={{ marginBottom: 12 }} message="此处管理飞书登录、通讯录与组织同步；Aily + MCP 使用下方独立配置。" />
        <Space direction="vertical" size={12} style={{ width: '100%', maxWidth: 720 }}>
          <Typography.Text>{t('feishu.apiBase')}</Typography.Text>
          <Input value={apiBase} disabled={disabled} onChange={(event) => setApiBase(event.target.value)} />
          <Typography.Text>App ID</Typography.Text>
          <Input value={appId} disabled={disabled} placeholder="cli_xxx" onChange={(event) => setAppId(event.target.value)} />
          <Typography.Text>App Secret</Typography.Text>
          <Input.Password value={appSecret} disabled={disabled} placeholder={config?.has_secret ? t('feishu.secretConfigured') : 'App Secret'} onChange={(event) => setAppSecret(event.target.value)} autoComplete="new-password" />
          <Typography.Text>{t('feishu.syncScope')}</Typography.Text>
          <Input.TextArea value={syncScope} disabled={disabled} placeholder="od-xxx, od-yyy 或 0" autoSize={{ minRows: 1, maxRows: 3 }} onChange={(event) => setSyncScope(event.target.value)} />
          <Space><Switch checked={enabled} disabled={disabled} onChange={setEnabled} /><Typography.Text>{t('feishu.enabled')}</Typography.Text></Space>
          <Space><Switch checked={autoSyncEnabled} disabled={disabled || !enabled} onChange={setAutoSyncEnabled} /><Typography.Text>{t('feishu.autoSync')}</Typography.Text></Space>
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
          <Space wrap>
            <Button icon={<ApiOutlined />} loading={testing} disabled={disabled} onClick={() => void handleTest()}>{t('feishu.test')}</Button>
            <Button icon={<SyncOutlined />} loading={syncing} disabled={disabled || !config?.enabled} onClick={() => void handleSync()}>{t('feishu.syncNow')}</Button>
          </Space>
          <Typography.Text type="secondary">
            {config?.last_sync_at ? t('feishu.lastSyncAt', { time: dayjs(config.last_sync_at).format('YYYY-MM-DD HH:mm:ss') }) : t('feishu.neverSynced')}
          </Typography.Text>
          {stats && <Space wrap>{STAT_META.map((meta) => <Tag key={meta.key} color={meta.color}>{t(meta.label)} {stats[meta.key] ?? 0}</Tag>)}</Space>}
          <Typography.Text type="secondary">
            飞书登录回调：<Typography.Text code copyable={redirectUri ? { text: redirectUri } : false}>{redirectUri || '请在下方填写公网访问根地址'}</Typography.Text>
          </Typography.Text>
        </Space>
      </Card>

      <Card
        title="Aily Agent + MCP Server"
        extra={isAdmin && <Button type="primary" icon={<SaveOutlined />} loading={ailySaving} onClick={() => void handleAilySave()}>保存 MCP 配置</Button>}
      >
        <Alert
          type={ailyConfig?.mcp_tool_calls_ready ? 'success' : 'warning'}
          showIcon
          style={{ marginBottom: 16 }}
          message={ailyConfig?.mcp_tool_calls_ready
            ? 'MCP 协议发现与用户工具调用均已就绪。'
            : '首次接入可只启用 MCP 并配置 Origin，让 Aily 完成协议校验；Aily 创建后再回填 JWT 密钥、租户/Agent 白名单和身份映射。密钥只写入后端，不会回显。'}
        />
        <Space direction="vertical" size={12} style={{ width: '100%', maxWidth: 760 }}>
          <Typography.Text strong>公网访问根地址（域名/IP + 服务端口）</Typography.Text>
          <Input
            value={publicBaseUrl}
            disabled={disabled}
            placeholder="例如 https://itom.snnc.cc:30443"
            onChange={(event) => { setPublicBaseUrl(event.target.value); setPublicBaseUrlError(''); }}
            onBlur={() => {
              try {
                setPublicBaseUrl(normalizePublicBaseUrl(publicBaseUrl));
                setPublicBaseUrlError('');
              } catch {
                // 保存时会再次校验并给出明确提示。
              }
            }}
            aria-label="公网访问根地址"
          />
          <Typography.Text type="secondary">
            填写外部实际访问入口，不要填写 /mcp/ 或任何回调路径；使用非 443 端口时必须保留端口号。清空后下方地址不再生成。
          </Typography.Text>
          {publicBaseUrlError && <Typography.Text type="danger">{publicBaseUrlError}</Typography.Text>}
          <Typography.Text>MCP 公网地址</Typography.Text>
          <Typography.Text code copyable={publicMcpUrl ? { text: publicMcpUrl } : false}>{publicMcpUrl || '请先填写公网访问根地址'}</Typography.Text>
          <Space><Switch checked={ailyEnabled} disabled={disabled} onChange={setAilyEnabled} /><Typography.Text>启用 Aily MCP</Typography.Text></Space>
          <Typography.Text>x-aily-jwt HS256 Secret</Typography.Text>
          <Input.Password value={jwtSecret} disabled={disabled} placeholder={ailyConfig?.has_mcp_jwt_secret ? '已配置，留空表示不修改' : '至少 16 个字符'} onChange={(event) => setJwtSecret(event.target.value)} autoComplete="new-password" />
          <Typography.Text>允许的飞书租户 ID（每行一个）</Typography.Text>
          <Input.TextArea value={tenantIds} disabled={disabled} rows={3} onChange={(event) => setTenantIds(event.target.value)} />
          <Typography.Text>允许的 Aily Agent ID（每行一个）</Typography.Text>
          <Input.TextArea value={agentIds} disabled={disabled} rows={3} onChange={(event) => setAgentIds(event.target.value)} />
          <Typography.Text>允许的 Origin（每行一个，仅协议与主机）</Typography.Text>
          <Input.TextArea value={origins} disabled={disabled} rows={3} onChange={(event) => setOrigins(event.target.value)} />
          <Divider style={{ margin: '8px 0' }} />
          <Typography.Text strong>主动消息机器人（P0 联调）</Typography.Text>
          <Input value={botAppId} disabled={disabled} placeholder="Bot App ID" onChange={(event) => setBotAppId(event.target.value)} />
          <Input.Password value={botAppSecret} disabled={disabled} placeholder={ailyConfig?.has_bot_app_secret ? 'Bot App Secret 已配置，留空表示不修改' : 'Bot App Secret'} onChange={(event) => setBotAppSecret(event.target.value)} autoComplete="new-password" />
          <Space><Switch checked={messageEnabled} disabled={disabled} onChange={setMessageEnabled} /><Typography.Text>启用主动消息</Typography.Text></Space>
          <Divider style={{ margin: '8px 0' }} />
          <Typography.Text strong>飞书交互卡片回调（关闭、重开、评价按钮）</Typography.Text>
          <Alert
            type="info"
            showIcon
            message="普通对话仍只使用 Aily + MCP；卡片按钮是唯一例外，由 ITOM 验证飞书签名和点击人身份后调用同一领域服务。"
          />
          <Typography.Text>公网回调地址（由上方公网访问根地址自动生成）</Typography.Text>
          <Typography.Text code copyable={cardCallbackUrl ? { text: cardCallbackUrl } : false}>{cardCallbackUrl || '请先填写公网访问根地址'}</Typography.Text>
          <Typography.Text>Verification Token</Typography.Text>
          <Input.Password
            value={cardCallbackVerificationToken}
            disabled={disabled}
            placeholder={ailyConfig?.has_card_callback_verification_token ? '已配置，留空表示不修改' : '飞书开放平台「事件与回调 > 加密策略」中的 Verification Token'}
            onChange={(event) => setCardCallbackVerificationToken(event.target.value)}
            autoComplete="new-password"
          />
          <Typography.Text>Encrypt Key</Typography.Text>
          <Input.Password
            value={cardCallbackEncryptKey}
            disabled={disabled}
            placeholder={ailyConfig?.has_card_callback_encrypt_key ? '已配置，留空表示不修改' : '飞书开放平台「事件与回调 > 加密策略」中的 Encrypt Key'}
            onChange={(event) => setCardCallbackEncryptKey(event.target.value)}
            autoComplete="new-password"
          />
          <Typography.Text type={ailyConfig?.interactive_cards_ready ? 'success' : 'secondary'}>
            {ailyConfig?.interactive_cards_ready
              ? '交互卡片已就绪：解决确认、未解决原因和星级评价将使用飞书原生交互。'
              : '交互卡片未就绪：需同时配置机器人凭证、Verification Token 与 Encrypt Key；未就绪时继续发送纯文本。'}
          </Typography.Text>
          <Space.Compact style={{ width: '100%' }}>
            <Select
              style={{ flex: 1 }}
              value={testIdentityId}
              disabled={disabled || !messageEnabled}
              placeholder="选择接收测试消息的身份映射"
              onChange={setTestIdentityId}
              options={identities.filter((item) => item.status === 'active').map((item) => ({ value: item.id, label: `${item.display_name || item.username || item.subject_id} · ${item.subject_type}` }))}
            />
            <Button icon={<ApiOutlined />} loading={messageTesting} disabled={disabled || !messageEnabled} onClick={() => void handleMessageTest()}>发送测试消息</Button>
          </Space.Compact>
          {ailyConfig?.last_test_status && (
            <Typography.Text type={ailyConfig.last_test_status === 'success' ? 'success' : 'danger'}>
              最近测试：{ailyConfig.last_test_status}{ailyConfig.last_test_at ? ` · ${dayjs(ailyConfig.last_test_at).format('YYYY-MM-DD HH:mm:ss')}` : ''}{ailyConfig.last_error_redacted ? ` · ${ailyConfig.last_error_redacted}` : ''}
            </Typography.Text>
          )}
        </Space>

        <Divider />
        <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }}>
          <Typography.Title level={5} style={{ margin: 0 }}>外部身份映射</Typography.Title>
          {isAdmin && <Button icon={<PlusOutlined />} onClick={() => openIdentityModal()}>新增映射</Button>}
        </Space>
        <SortableTable<AilyExternalIdentity>
          rowKey="id"
          size="small"
          dataSource={identities}
          pagination={false}
          scroll={{ x: 1050 }}
          columns={[
            { title: 'ITOM 用户', key: 'user', width: 180, render: (_, row) => row.display_name || row.username || row.auth_user_id },
            { title: '租户 ID', dataIndex: 'tenant_id', width: 180, ellipsis: true },
            { title: '应用 ID', dataIndex: 'app_id', width: 180, ellipsis: true },
            { title: '标识类型', dataIndex: 'subject_type', width: 110 },
            { title: '飞书用户标识', dataIndex: 'subject_id', width: 200, ellipsis: true },
            { title: '状态', dataIndex: 'status', width: 100, render: (value: string) => <Tag color={value === 'active' ? 'green' : value === 'pending' ? 'orange' : 'default'}>{value === 'active' ? '有效' : value === 'pending' ? '待映射' : '停用'}</Tag> },
            { title: '最近使用', dataIndex: 'last_used_at', width: 170, render: (value: string | null) => value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-' },
            {
              title: '操作', key: 'actions', width: 150, fixed: 'right',
              render: (_, row) => isAdmin ? (
                <Space size={4}>
                  {row.status === 'pending' && <Button type="link" size="small" onClick={() => openIdentityModal(row)}>确认映射</Button>}
                  <Popconfirm title="确认删除该身份映射？" onConfirm={() => void handleIdentityDelete(row.id)}>
                    <Button type="text" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              ) : null,
            },
          ]}
        />
      </Card>

      <Modal title={identityEditingId ? '确认 Aily 外部身份映射' : '新增 Aily 外部身份映射'} open={identityOpen} confirmLoading={identitySaving} onOk={() => void handleIdentityCreate()} onCancel={() => { setIdentityOpen(false); setIdentityEditingId(undefined); }} destroyOnClose>
        <Form form={identityForm} layout="vertical" preserve={false} initialValues={{ subject_type: 'open_id' }}>
          <Form.Item name="tenant_id" label="飞书租户 ID" rules={[{ required: true }]}><Input disabled={!!identityEditingId} /></Form.Item>
          <Form.Item name="app_id" label="Aily 应用 ID" rules={[{ required: true }]}><Input disabled={!!identityEditingId} /></Form.Item>
          <Form.Item name="subject_type" label="用户标识类型" rules={[{ required: true }]}>
            <Select disabled={!!identityEditingId} options={['open_id', 'user_id', 'union_id'].map((value) => ({ value, label: value }))} />
          </Form.Item>
          <Form.Item name="subject_id" label="飞书用户标识" rules={[{ required: true }]}><Input disabled={!!identityEditingId} /></Form.Item>
          <Form.Item name="auth_user_id" label="映射到 ITOM 账号" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" options={users.map((item) => ({ value: item.id, label: `${item.name || item.username}（${item.username}）` }))} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}
