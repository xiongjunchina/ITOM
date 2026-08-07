import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Skeleton,
  Space,
  Statistic,
  Switch,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ApiOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { useSearchParams } from 'react-router-dom';
import { adminAiApi } from '../../api/assistant';
import type {
  AiActionAuditRow,
  AiHealthSummary,
  AiProfileDraft,
  AiProviderConfig,
  AiProviderWrite,
  AiUsageSummary,
} from '../../api/types';
import { useT } from '../../i18n';
import { hasPermission, useAuthStore } from '../../stores/auth';
import SortableTable from '../../components/SortableTable';

const PROFILE_CODES: AiProfileDraft['code'][] = ['requester', 'bdo', 'it_staff', 'admin'];
const TAB_KEYS = ['providers', 'profiles', 'health', 'usage', 'audits'] as const;
type TabKey = typeof TAB_KEYS[number];

export function createLatestRequestGuard() {
  let currentGeneration = 0;
  return {
    begin(): number {
      currentGeneration += 1;
      return currentGeneration;
    },
    runIfCurrent(generation: number, update: () => void): boolean {
      if (generation !== currentGeneration) return false;
      update();
      return true;
    },
    invalidate(): void {
      currentGeneration += 1;
    },
  };
}

const ACTION_AUDIT_STATUS_KEYS = {
  prepared: 'admin.ai.audit.status.prepared',
  executing: 'admin.ai.audit.status.executing',
  succeeded: 'admin.ai.audit.status.succeeded',
  cancelled: 'admin.ai.audit.status.cancelled',
  expired: 'admin.ai.audit.status.expired',
  failed: 'admin.ai.audit.status.failed',
} as const;

export function actionAuditStatusTranslationKey(value: string): string | undefined {
  if (!Object.prototype.hasOwnProperty.call(ACTION_AUDIT_STATUS_KEYS, value)) return undefined;
  return ACTION_AUDIT_STATUS_KEYS[value as keyof typeof ACTION_AUDIT_STATUS_KEYS];
}

function DelayedSkeleton({ loading, children }: { loading: boolean; children: React.ReactNode }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!loading) { setVisible(false); return; }
    const timer = window.setTimeout(() => setVisible(true), 300);
    return () => window.clearTimeout(timer);
  }, [loading]);
  if (!loading) return <>{children}</>;
  return visible ? <Skeleton active paragraph={{ rows: 6 }} /> : <div style={{ minHeight: 240 }} />;
}

function ProvidersPanel() {
  const t = useT();
  const user = useAuthStore((state) => state.user);
  const canEdit = hasPermission(user, 'admin_ai', 'edit');
  const canDelete = hasPermission(user, 'admin_ai', 'delete');
  const [form] = Form.useForm<AiProviderWrite>();
  const [providers, setProviders] = useState<AiProviderConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [editing, setEditing] = useState<AiProviderConfig | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [inlineError, setInlineError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setInlineError(false);
    try {
      setProviders(await adminAiApi.providers());
    } catch {
      setProviders([]);
      setInlineError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const openEditor = (provider?: AiProviderConfig) => {
    setEditing(provider ?? null);
    form.resetFields();
    form.setFieldsValue(provider ? {
      code: provider.code,
      name: provider.name,
      provider_type: provider.provider_type,
      api_base_url: provider.api_base_url,
      model: provider.model,
      timeout_seconds: provider.timeout_seconds,
      max_output_tokens: provider.max_output_tokens,
      temperature: provider.temperature,
      is_primary: provider.is_primary,
      fallback_provider_id: provider.fallback_provider_id,
      enabled: provider.enabled,
    } : {
      provider_type: 'openai_compatible',
      timeout_seconds: 30,
      max_output_tokens: 2048,
      is_primary: false,
      enabled: false,
    });
    setModalOpen(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const values = await form.validateFields();
      const payload: AiProviderWrite = {
        name: values.name,
        provider_type: 'openai_compatible',
        api_base_url: values.api_base_url,
        model: values.model,
        timeout_seconds: values.timeout_seconds,
        max_output_tokens: values.max_output_tokens,
        temperature: values.temperature ?? null,
        is_primary: values.is_primary,
        fallback_provider_id: values.fallback_provider_id ?? null,
        enabled: values.enabled,
      };
      if (values.api_key) payload.api_key = values.api_key;
      if (editing) {
        await adminAiApi.updateProvider(editing.id, payload);
      } else {
        payload.code = values.code;
        await adminAiApi.createProvider(payload);
      }
      message.success(t(editing ? 'admin.ai.provider.updated' : 'admin.ai.provider.created'));
      setModalOpen(false);
      form.resetFields();
      await load();
    } catch {
      // The shared API client renders the server's safe error envelope.
    } finally {
      setSaving(false);
    }
  };

  const testProvider = async (provider: AiProviderConfig) => {
    setTestingId(provider.id);
    try {
      await adminAiApi.testProvider(provider.id);
      message.success(t('admin.ai.provider.testSucceeded'));
      await load();
    } catch {
      // The shared API client renders the server's safe error envelope.
    } finally {
      setTestingId(null);
    }
  };

  const deleteProvider = async (provider: AiProviderConfig) => {
    try {
      await adminAiApi.deleteProvider(provider.id);
      message.success(t('admin.ai.provider.deleted'));
      await load();
    } catch {
      // The shared API client renders the server's safe error envelope.
    }
  };

  const columns: ColumnsType<AiProviderConfig> = [
    {
      title: t('admin.ai.provider.name'),
      dataIndex: 'name',
      render: (_, row) => <Space direction="vertical" size={0}><Typography.Text strong>{row.name}</Typography.Text><Typography.Text code>{row.code}</Typography.Text></Space>,
    },
    { title: t('admin.ai.provider.model'), dataIndex: 'model', ellipsis: true },
    {
      title: t('admin.ai.provider.probe'),
      dataIndex: 'probe_status',
      render: (value: string | null) => <Tag color={value === 'success' ? 'success' : value === 'failed' ? 'error' : 'default'}>{t(`admin.ai.probe.${value || 'unverified'}`)}</Tag>,
    },
    {
      title: t('admin.ai.provider.capabilities'),
      render: (_, row) => <Space size={[4, 4]} wrap>
        {(['supports_streaming', 'supports_tools', 'supports_json_schema'] as const).map((key) => (
          <Tag key={key} color={row.capability_probe[key] === true ? 'success' : 'default'}>{t(`admin.ai.capability.${key}`)}</Tag>
        ))}
      </Space>,
    },
    {
      title: t('common.status'),
      render: (_, row) => <Space wrap>
        {row.is_primary && <Tag color="blue">{t('admin.ai.provider.primary')}</Tag>}
        <Tag color={row.enabled ? 'success' : 'default'}>{t(row.enabled ? 'admin.common.on' : 'admin.common.off')}</Tag>
        <Tag>{t(row.has_secret ? 'admin.ai.provider.secretConfigured' : 'admin.ai.provider.secretMissing')}</Tag>
      </Space>,
    },
    {
      title: t('common.actions'),
      width: 220,
      render: (_, row) => <Space wrap>
        <Button size="small" icon={<ApiOutlined />} loading={testingId === row.id} disabled={!canEdit} onClick={() => void testProvider(row)}>{t('admin.ai.provider.test')}</Button>
        <Button size="small" icon={<EditOutlined />} disabled={!canEdit} onClick={() => openEditor(row)}>{t('common.edit')}</Button>
        <Popconfirm title={t('admin.ai.provider.deleteConfirm')} onConfirm={() => void deleteProvider(row)}>
          <Button size="small" danger icon={<DeleteOutlined />} disabled={!canDelete}>{t('common.delete')}</Button>
        </Popconfirm>
      </Space>,
    },
  ];

  return (
    <>
      <div className="ai-admin-toolbar">
        <Typography.Text type="secondary">{t('admin.ai.provider.description')}</Typography.Text>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>{t('common.refresh')}</Button>
          {canEdit && <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor()}>{t('admin.ai.provider.new')}</Button>}
        </Space>
      </div>
      {inlineError && <Alert showIcon type="error" message={t('admin.ai.loadError')} action={<Button onClick={() => void load()}>{t('common.refresh')}</Button>} style={{ marginBottom: 16 }} />}
      <DelayedSkeleton loading={loading}>
        {!inlineError && (providers.length === 0 ? (
          <Empty description={t('admin.ai.provider.empty')}>
            {canEdit && <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor()}>{t('admin.ai.provider.new')}</Button>}
          </Empty>
        ) : (
          <SortableTable rowKey="id" columns={columns} dataSource={providers} pagination={false} scroll={{ x: 1050 }} />
        ))}
      </DelayedSkeleton>
      <Modal
        title={t(editing ? 'admin.ai.provider.edit' : 'admin.ai.provider.new')}
        open={modalOpen}
        width={720}
        okText={t('common.save')}
        cancelText={t('common.cancel')}
        confirmLoading={saving}
        onOk={() => void save()}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        destroyOnClose
      >
        <Alert showIcon type="info" message={t('admin.ai.provider.secretWriteOnly')} style={{ marginBottom: 16 }} />
        <Form form={form} layout="vertical" requiredMark="optional">
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item name="code" label={t('admin.ai.provider.code')} rules={editing ? [] : [{ required: true }, { pattern: /^[a-z][a-z0-9_-]*$/ }]}>
                <Input disabled={!!editing} maxLength={64} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="name" label={t('admin.ai.provider.name')} rules={[{ required: true, whitespace: true }]}>
                <Input maxLength={128} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="provider_type" label={t('admin.ai.provider.type')}>
            <Select disabled options={[{ value: 'openai_compatible', label: 'OpenAI-compatible' }]} />
          </Form.Item>
          <Form.Item name="api_base_url" label={t('admin.ai.provider.baseUrl')} rules={[{ required: true }, { pattern: /^https:\/\//, message: t('admin.ai.provider.httpsRequired') }]}>
            <Input maxLength={300} />
          </Form.Item>
          <Form.Item
            name="api_key"
            label={t('admin.ai.provider.secret')}
            extra={editing?.has_secret ? t('admin.ai.provider.secretKeepHint') : t('admin.ai.provider.secretNewHint')}
          >
            <Input.Password autoComplete="new-password" maxLength={8192} />
          </Form.Item>
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item name="model" label={t('admin.ai.provider.model')} rules={[{ required: true, whitespace: true }]}><Input maxLength={128} /></Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item name="timeout_seconds" label={t('admin.ai.provider.timeout')} rules={[{ required: true }]}><InputNumber min={1} max={300} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item name="max_output_tokens" label={t('admin.ai.provider.maxTokens')} rules={[{ required: true }]}><InputNumber min={1} max={65536} style={{ width: '100%' }} /></Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item name="temperature" label={t('admin.ai.provider.temperature')}><InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col xs={24} md={16}>
              <Form.Item name="fallback_provider_id" label={t('admin.ai.provider.fallback')}>
                <Select allowClear options={providers.filter((item) => item.id !== editing?.id).map((item) => ({ value: item.id, label: `${item.name} (${item.code})` }))} />
              </Form.Item>
            </Col>
          </Row>
          <Space size="large" wrap>
            <Form.Item name="is_primary" label={t('admin.ai.provider.primary')} valuePropName="checked"><Switch /></Form.Item>
            <Form.Item name="enabled" label={t('admin.ai.provider.enabled')} valuePropName="checked"><Switch /></Form.Item>
          </Space>
        </Form>
      </Modal>
    </>
  );
}

interface ProfileFormValues {
  name: string;
  default_provider_id: string | null;
  retention_days: number;
  enabled: boolean;
  system_prompt_zh: string;
  system_prompt_en: string;
  enabled_capabilities: string[];
  knowledge_scope: string[];
  max_risk_level: 'L1' | 'L2' | 'L3';
}

const KNOWLEDGE_SCOPE: Record<AiProfileDraft['audience'], string[]> = {
  requester: ['public', 'service_catalog', 'own_records'],
  bdo: ['public', 'service_catalog', 'own_records', 'own_requirements'],
  it: ['public', 'service_catalog', 'own_records', 'internal_knowledge', 'authorized_records'],
  admin: ['public', 'service_catalog', 'own_records', 'own_requirements', 'internal_knowledge', 'authorized_records', 'governance'],
};

function ProfilesPanel() {
  const t = useT();
  const user = useAuthStore((state) => state.user);
  const canEdit = hasPermission(user, 'admin_ai', 'edit');
  const [form] = Form.useForm<ProfileFormValues>();
  const [code, setCode] = useState<AiProfileDraft['code']>('requester');
  const [draft, setDraft] = useState<AiProfileDraft | null>(null);
  const [providers, setProviders] = useState<AiProviderConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [rollbackVersion, setRollbackVersion] = useState<number | null>(null);
  const [inlineError, setInlineError] = useState(false);
  const loadRequestRef = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++loadRequestRef.current;
    setLoading(true);
    setInlineError(false);
    setDraft(null);
    setProviders([]);
    form.resetFields();
    try {
      const [profile, providerRows] = await Promise.all([adminAiApi.profileDraft(code), adminAiApi.providers()]);
      if (requestId !== loadRequestRef.current) return;
      setDraft(profile);
      setProviders(providerRows);
      form.setFieldsValue({
        name: profile.name,
        default_provider_id: profile.default_provider_id,
        retention_days: profile.retention_days,
        enabled: profile.enabled,
        system_prompt_zh: profile.system_prompt_zh,
        system_prompt_en: profile.system_prompt_en,
        enabled_capabilities: profile.enabled_capabilities,
        knowledge_scope: profile.knowledge_scope,
        max_risk_level: profile.max_risk_level,
      });
    } catch {
      if (requestId !== loadRequestRef.current) return;
      setInlineError(true);
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false);
    }
  }, [code, form]);

  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const values = await form.validateFields();
      const updated = await adminAiApi.updateProfileDraft(code, { expected_updated_at: draft.draft_updated_at, ...values });
      setDraft(updated);
      form.setFieldsValue(values);
      message.success(t('admin.ai.profile.saved'));
    } catch {
      // The shared API client renders the server's safe error envelope.
    } finally {
      setSaving(false);
    }
  };

  const publish = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      await adminAiApi.publishProfile(code, draft.draft_updated_at);
      message.success(t('admin.ai.profile.published'));
      await load();
    } catch {
      // The shared API client renders the server's safe error envelope.
    } finally {
      setSaving(false);
    }
  };

  const rollback = async () => {
    if (!draft?.latest_published_version || !rollbackVersion) return;
    setSaving(true);
    try {
      await adminAiApi.rollbackProfile(code, rollbackVersion, draft.latest_published_version);
      message.success(t('admin.ai.profile.rolledBack'));
      setRollbackVersion(null);
      await load();
    } catch {
      // The shared API client renders the server's safe error envelope.
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="ai-admin-toolbar">
        <Space wrap>
          <Typography.Text>{t('admin.ai.profile.select')}</Typography.Text>
          <Select
            disabled={saving}
            value={code}
            style={{ minWidth: 220 }}
            onChange={(value) => {
              loadRequestRef.current += 1;
              setDraft(null);
              setProviders([]);
              form.resetFields();
              setCode(value);
            }}
            options={PROFILE_CODES.map((value) => ({ value, label: t(`admin.ai.profile.${value}`) }))}
          />
          {draft && <Tag color={draft.status === 'published' ? 'success' : 'default'}>{t(`admin.ai.profile.status.${draft.status}`)}</Tag>}
          {draft?.latest_published_version && <Tag>{t('admin.ai.profile.version', { n: draft.latest_published_version })}</Tag>}
        </Space>
        <Button icon={<ReloadOutlined />} disabled={saving} onClick={() => void load()}>{t('common.refresh')}</Button>
      </div>
      {inlineError && <Alert showIcon type="error" message={t('admin.ai.loadError')} action={<Button onClick={() => void load()}>{t('common.refresh')}</Button>} style={{ marginBottom: 16 }} />}
      <DelayedSkeleton loading={loading}>
        {!inlineError && (draft ? (
          <Form form={form} layout="vertical" className="ai-admin-form" disabled={!canEdit || saving} requiredMark="optional">
            <Alert showIcon type="info" message={t('admin.ai.profile.description')} style={{ marginBottom: 16 }} />
            <Row gutter={16}>
              <Col xs={24} md={12}><Form.Item name="name" label={t('admin.ai.profile.name')} rules={[{ required: true, whitespace: true }]}><Input maxLength={128} /></Form.Item></Col>
              <Col xs={24} md={12}><Form.Item name="default_provider_id" label={t('admin.ai.profile.provider')}><Select allowClear options={providers.map((item) => ({ value: item.id, label: `${item.name} (${item.code})` }))} /></Form.Item></Col>
            </Row>
            <Row gutter={16}>
              <Col xs={24} md={8}><Form.Item name="retention_days" label={t('admin.ai.profile.retention')} rules={[{ required: true }]}><InputNumber min={0} max={90} style={{ width: '100%' }} /></Form.Item></Col>
              <Col xs={24} md={8}><Form.Item name="max_risk_level" label={t('admin.ai.profile.maxRisk')} rules={[{ required: true }]}><Select options={['L1', 'L2', 'L3'].map((value) => ({ value, label: value }))} /></Form.Item></Col>
              <Col xs={24} md={8}><Form.Item name="enabled" label={t('admin.ai.profile.enabled')} valuePropName="checked"><Switch /></Form.Item></Col>
            </Row>
            <Form.Item name="enabled_capabilities" label={t('admin.ai.profile.capabilities')} extra={t('admin.ai.profile.capabilitiesHint')}>
              <Select mode="tags" tokenSeparators={[',', ' ']} options={(draft.enabled_capabilities ?? []).map((value) => ({ value, label: value }))} />
            </Form.Item>
            <Form.Item name="knowledge_scope" label={t('admin.ai.profile.knowledge')}>
              <Select mode="multiple" options={KNOWLEDGE_SCOPE[draft.audience].map((value) => ({ value, label: value }))} />
            </Form.Item>
            <Form.Item name="system_prompt_zh" label={t('admin.ai.profile.promptZh')}><Input.TextArea rows={6} maxLength={20000} showCount /></Form.Item>
            <Form.Item name="system_prompt_en" label={t('admin.ai.profile.promptEn')}><Input.TextArea rows={6} maxLength={20000} showCount /></Form.Item>
            {canEdit && (
              <Space className="ai-admin-form__actions" wrap>
                <Button type="primary" loading={saving} onClick={() => void save()}>{t('admin.ai.profile.saveDraft')}</Button>
                <Button icon={<SendOutlined />} loading={saving} onClick={() => void publish()}>{t('admin.ai.profile.publish')}</Button>
                <InputNumber min={1} value={rollbackVersion} placeholder={t('admin.ai.profile.rollbackVersion')} onChange={setRollbackVersion} />
                <Button disabled={!rollbackVersion || !draft.latest_published_version} loading={saving} onClick={() => void rollback()}>{t('admin.ai.profile.rollback')}</Button>
              </Space>
            )}
          </Form>
        ) : <Empty description={t('admin.ai.profile.empty')} />)}
      </DelayedSkeleton>
    </>
  );
}

function HealthPanel() {
  const t = useT();
  const [data, setData] = useState<AiHealthSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try { setData(await adminAiApi.health()); } catch { setData(null); setLoadError(true); } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  return <DelayedSkeleton loading={loading}>{loadError ? (
    <Alert showIcon type="error" message={t('admin.ai.loadError')} action={<Button onClick={() => void load()}>{t('common.refresh')}</Button>} />
  ) : data ? <>
    <div className="ai-admin-toolbar"><Typography.Text type="secondary">{t('admin.ai.health.description')}</Typography.Text><Button icon={<ReloadOutlined />} onClick={() => void load()}>{t('common.refresh')}</Button></div>
    <div className="ai-admin-stat-grid">
      <Card><Statistic title={t('admin.ai.health.providersTotal')} value={data.providers.total} /></Card>
      <Card><Statistic title={t('admin.ai.health.providersHealthy')} value={data.providers.healthy} /></Card>
      <Card><Statistic title={t('admin.ai.health.providersFailed')} value={data.providers.failed} /></Card>
      <Card><Statistic title={t('admin.ai.health.profilesTotal')} value={data.profiles.fixed_total} /></Card>
      <Card><Statistic title={t('admin.ai.health.profilesPublished')} value={data.profiles.published} /></Card>
      <Card><Statistic title={t('admin.ai.health.profilesEnabled')} value={data.profiles.enabled} /></Card>
    </div>
    <Descriptions bordered column={1} items={[
      { key: 'enabled', label: t('admin.ai.health.providersEnabled'), children: data.providers.enabled },
      { key: 'unverified', label: t('admin.ai.health.providersUnverified'), children: data.providers.unverified },
    ]} />
  </> : <Empty description={t('common.noData')}><Button icon={<ReloadOutlined />} onClick={() => void load()}>{t('common.refresh')}</Button></Empty>}</DelayedSkeleton>;
}

function UsagePanel() {
  const t = useT();
  const requestGuard = useRef(createLatestRequestGuard());
  const [days, setDays] = useState(30);
  const [data, setData] = useState<AiUsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const load = useCallback(async () => {
    const generation = requestGuard.current.begin();
    setLoading(true);
    setLoadError(false);
    setData(null);
    try {
      const result = await adminAiApi.usage(days);
      requestGuard.current.runIfCurrent(generation, () => setData(result));
    } catch {
      requestGuard.current.runIfCurrent(generation, () => {
        setData(null);
        setLoadError(true);
      });
    } finally {
      requestGuard.current.runIfCurrent(generation, () => setLoading(false));
    }
  }, [days]);
  useEffect(() => {
    void load();
    return () => requestGuard.current.invalidate();
  }, [load]);
  const changeDays = (value: number) => {
    requestGuard.current.invalidate();
    setData(null);
    setLoadError(false);
    setLoading(true);
    setDays(value);
  };
  return <>
    <div className="ai-admin-toolbar">
      <Typography.Text type="secondary">{t('admin.ai.usage.description')}</Typography.Text>
      <Space><Select value={days} onChange={changeDays} options={[7, 30, 90].map((value) => ({ value, label: t('admin.ai.usage.days', { n: value }) }))} /><Button icon={<ReloadOutlined />} onClick={() => void load()}>{t('common.refresh')}</Button></Space>
    </div>
    <DelayedSkeleton loading={loading}>{loadError ? (
      <Alert showIcon type="error" message={t('admin.ai.loadError')} action={<Button onClick={() => void load()}>{t('common.refresh')}</Button>} />
    ) : data ? <>
      <div className="ai-admin-stat-grid">
        <Card><Statistic title={t('admin.ai.usage.total')} value={data.total_calls} /></Card>
        <Card><Statistic title={t('admin.ai.usage.completed')} value={data.completed_calls} /></Card>
        <Card><Statistic title={t('admin.ai.usage.failed')} value={data.failed_calls} /></Card>
        <Card><Statistic title={t('admin.ai.usage.inputTokens')} value={data.input_tokens} /></Card>
        <Card><Statistic title={t('admin.ai.usage.outputTokens')} value={data.output_tokens} /></Card>
        <Card><Statistic title={t('admin.ai.usage.averageDuration')} value={data.average_duration_ms} suffix="ms" precision={2} /></Card>
      </div>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}><Card title={t('admin.ai.usage.byProvider')}><SortableTable rowKey="provider_code" pagination={false} dataSource={data.by_provider} columns={[
          { title: t('admin.ai.usage.provider'), dataIndex: 'provider_code' },
          { title: t('admin.ai.usage.calls'), dataIndex: 'calls' },
          { title: t('admin.ai.usage.inputTokens'), dataIndex: 'input_tokens' },
          { title: t('admin.ai.usage.outputTokens'), dataIndex: 'output_tokens' },
        ]} /></Card></Col>
        <Col xs={24} lg={10}><Card title={t('admin.ai.usage.byResult')}><SortableTable rowKey="result_code" pagination={false} dataSource={data.by_result_code} columns={[
          { title: t('admin.ai.audit.resultCode'), dataIndex: 'result_code' },
          { title: t('admin.ai.usage.count'), dataIndex: 'count' },
        ]} /></Card></Col>
      </Row>
    </> : <Empty description={t('common.noData')}><Button icon={<ReloadOutlined />} onClick={() => void load()}>{t('common.refresh')}</Button></Empty>}</DelayedSkeleton>
  </>;
}

function AuditsPanel() {
  const t = useT();
  const requestGuard = useRef(createLatestRequestGuard());
  const [rows, setRows] = useState<AiActionAuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [status, setStatus] = useState<string | undefined>();
  const [capability, setCapability] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const load = useCallback(async () => {
    const generation = requestGuard.current.begin();
    setLoading(true);
    setLoadError(false);
    setRows([]);
    setTotal(0);
    try {
      const result = await adminAiApi.actionAudits({ page, page_size: pageSize, status, capability_code: capability || undefined });
      requestGuard.current.runIfCurrent(generation, () => {
        setRows(result.items);
        setTotal(result.total);
      });
    } catch {
      requestGuard.current.runIfCurrent(generation, () => {
        setRows([]);
        setTotal(0);
        setLoadError(true);
      });
    } finally {
      requestGuard.current.runIfCurrent(generation, () => setLoading(false));
    }
  }, [capability, page, pageSize, status]);
  useEffect(() => {
    void load();
    return () => requestGuard.current.invalidate();
  }, [load]);

  const resetVisibleResults = () => {
    requestGuard.current.invalidate();
    setRows([]);
    setTotal(0);
    setLoadError(false);
    setLoading(true);
  };
  const auditStatusLabel = (value: string) => {
    const key = actionAuditStatusTranslationKey(value);
    return key ? t(key) : value;
  };

  const columns: ColumnsType<AiActionAuditRow> = [
    { title: t('admin.ai.audit.time'), dataIndex: 'created_at', width: 170, render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm:ss') },
    { title: t('admin.ai.audit.capability'), dataIndex: 'capability_code', ellipsis: true },
    { title: t('admin.ai.audit.risk'), dataIndex: 'risk_level', width: 80 },
    { title: t('common.status'), dataIndex: 'status', width: 110, render: (value: string) => <Tag>{auditStatusLabel(value)}</Tag> },
    { title: t('admin.ai.audit.resultCode'), dataIndex: 'result_code', ellipsis: true },
    { title: t('admin.ai.audit.entity'), render: (_, row) => [row.result_entity_type, row.result_entity_id].filter(Boolean).join(' / ') || '-' },
    { title: t('admin.ai.audit.consumedAt'), dataIndex: 'consumed_at', width: 170, render: (value: string | null) => value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-' },
  ];
  return <>
    <div className="ai-admin-toolbar">
      <Space wrap>
        <Select allowClear placeholder={t('admin.ai.audit.status')} style={{ width: 160 }} value={status} onChange={(value) => { resetVisibleResults(); setStatus(value); setPage(1); }} options={Object.keys(ACTION_AUDIT_STATUS_KEYS).map((value) => ({ value, label: auditStatusLabel(value) }))} />
        <Input.Search allowClear placeholder={t('admin.ai.audit.capabilityPlaceholder')} style={{ width: 280 }} onSearch={(value) => { resetVisibleResults(); setCapability(value.trim()); setPage(1); }} />
      </Space>
      <Button icon={<ReloadOutlined />} onClick={() => void load()}>{t('common.refresh')}</Button>
    </div>
    <DelayedSkeleton loading={loading}>
      {loadError ? (
        <Alert showIcon type="error" message={t('admin.ai.loadError')} action={<Button onClick={() => void load()}>{t('common.refresh')}</Button>} />
      ) : <SortableTable
        rowKey="id"
        columns={columns}
        dataSource={rows}
        locale={{ emptyText: <Empty description={t('admin.ai.audit.empty')} /> }}
        scroll={{ x: 1000 }}
        pagination={{ current: page, pageSize, total, showSizeChanger: true, showTotal: (value) => t('admin.total', { n: value }), onChange: (next, size) => { resetVisibleResults(); setPage(next); setPageSize(size); } }}
      />}
    </DelayedSkeleton>
  </>;
}

export default function AiAssistant() {
  const t = useT();
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get('tab') as TabKey | null;
  const active = requested && TAB_KEYS.includes(requested) ? requested : 'providers';
  const items = useMemo(() => [
    { key: 'providers', label: t('admin.ai.tab.providers'), children: <ProvidersPanel /> },
    { key: 'profiles', label: t('admin.ai.tab.profiles'), children: <ProfilesPanel /> },
    { key: 'health', label: t('admin.ai.tab.health'), children: <HealthPanel /> },
    { key: 'usage', label: t('admin.ai.tab.usage'), children: <UsagePanel /> },
    { key: 'audits', label: t('admin.ai.tab.audits'), children: <AuditsPanel /> },
  ], [t]);

  return (
    <Card
      className="ai-admin-page"
      title={<Space><SafetyCertificateOutlined />{t('admin.ai.title')}</Space>}
    >
      <Alert showIcon type="warning" message={t('admin.ai.boundary')} style={{ marginBottom: 16 }} />
      <Tabs
        activeKey={active}
        items={items}
        onChange={(tab) => setSearchParams({ tab })}
      />
    </Card>
  );
}
