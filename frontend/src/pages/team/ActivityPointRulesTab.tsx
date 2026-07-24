import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Form, InputNumber, Modal, Space, Switch, Tag, Typography, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { EditOutlined, SaveOutlined } from '@ant-design/icons';
import Table from '../../components/SortableTable';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import { useAuthStore } from '../../stores/auth';
import type { PerformanceContributionConfig, PointRule } from '../../api/types';

interface RuleFormValues {
  points: number;
  active: boolean;
}

const DIMENSIONS = [
  'special_activity',
  'learning_growth',
  'training_knowledge',
  'suggestion_improvement',
  'knowledge_asset',
  'cross_team_support',
] as const;

/** 活动积分页的团队贡献规则：只呈现 team_contribution，不呈现 role_result。 */
export default function ActivityPointRulesTab() {
  const t = useT();
  const user = useAuthStore((s) => s.user);
  const canEdit = !!user?.roles.some((role) => role === 'admin' || role === 'cio');
  const [rules, setRules] = useState<PointRule[]>([]);
  const [config, setConfig] = useState<PerformanceContributionConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [editing, setEditing] = useState<PointRule | null>(null);
  const [savingRule, setSavingRule] = useState(false);
  const [form] = Form.useForm<RuleFormValues>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ruleResult, configResult] = await Promise.all([
        api.getList<PointRule>('/point-rules'),
        api.get<PerformanceContributionConfig>('/point-rules/team-config'),
      ]);
      setRules(ruleResult.items);
      setConfig(configResult);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openEdit = (row: PointRule) => {
    setEditing(row);
    form.setFieldsValue({ points: row.points, active: row.active });
  };

  const saveRule = async () => {
    if (!editing) return;
    const values = await form.validateFields();
    setSavingRule(true);
    try {
      await api.patch(`/admin/point-rules/${editing.code}`, values);
      message.success(t('team.pointRules.updated'));
      setEditing(null);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSavingRule(false);
    }
  };

  const saveConfig = async () => {
    if (!config) return;
    const weightTotal = DIMENSIONS.reduce((sum, code) => sum + Number(config.weights[code] ?? 0), 0);
    const satisfactionTotal = Number(config.internal_satisfaction_weight ?? 0) + Number(config.external_satisfaction_weight ?? 0);
    if (Math.abs(weightTotal - 100) > 0.01 || Math.abs(satisfactionTotal - 100) > 0.01) {
      message.error(t('team.pointRules.totalWeightInvalid'));
      return;
    }
    setSavingConfig(true);
    try {
      await api.put('/point-rules/team-config', config);
      message.success(t('team.pointRules.configSaved'));
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSavingConfig(false);
    }
  };

  const columns: ColumnsType<PointRule> = [
    { title: t('admin.pointRules.col.name'), dataIndex: 'name', ellipsis: true },
    { title: t('admin.pointRules.col.code'), dataIndex: 'code', width: 190, ellipsis: true },
    { title: t('admin.pointRules.col.dimension'), dataIndex: 'contribution_dimension', width: 180, render: (value: string | null) => value || '-' },
    { title: t('admin.pointRules.col.points'), dataIndex: 'points', width: 90 },
    {
      title: t('admin.pointRules.col.active'),
      dataIndex: 'active',
      width: 90,
      render: (active: boolean) => <Tag color={active ? 'green' : 'default'}>{active ? t('admin.pointRules.enabled') : t('admin.pointRules.disabled')}</Tag>,
    },
    ...(canEdit
      ? [{
          title: t('common.actions'),
          key: 'actions',
          width: 90,
          render: (_: unknown, row: PointRule) => (
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
              {t('common.edit')}
            </Button>
          ),
        } as ColumnsType<PointRule>[number]]
      : []),
  ];

  return (
    <Space direction="vertical" size={16} style={{ display: 'flex' }}>
      <Card title={t('team.pointRules.title')}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          {t('team.pointRules.description')}
        </Typography.Paragraph>
        <Alert type="info" showIcon message={t('team.pointRules.effectHint')} style={{ marginBottom: 12 }} />
        <Table<PointRule>
          rowKey="code"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={rules}
          standardToolbar={{ exportFileName: t('team.pointRules.title'), searchPlaceholder: t('team.pointRules.searchPlaceholder') }}
          pagination={false}
        />
      </Card>

      <Card
        title={t('team.pointRules.contributionConfigTitle')}
        extra={canEdit ? <Button type="primary" icon={<SaveOutlined />} loading={savingConfig} onClick={() => void saveConfig()}>{t('team.pointRules.saveConfig')}</Button> : null}
      >
        <Alert type="info" showIcon message={t('team.pointRules.contributionConfigHint')} style={{ marginBottom: 12 }} />
        {config && (
          <Space direction="vertical" size={12} style={{ display: 'flex' }}>
            <Space wrap>
              {DIMENSIONS.map((code) => (
                <Space key={code} align="center">
                  <Typography.Text>{t(`team.pointRules.dimension.${code}`)}</Typography.Text>
                  <InputNumber
                    min={0}
                    max={100}
                    precision={2}
                    addonAfter="%"
                    value={config.weights[code]}
                    disabled={!canEdit}
                    onChange={(value) => setConfig((current) => current ? ({ ...current, weights: { ...current.weights, [code]: Number(value ?? 0) } }) : current)}
                  />
                </Space>
              ))}
            </Space>
            <Space wrap>
              {DIMENSIONS.map((code) => (
                <Space key={code} align="center">
                  <Typography.Text>{t(`team.pointRules.dimension.${code}`)}{t('team.pointRules.targetSuffix')}</Typography.Text>
                  <InputNumber
                    min={0.1}
                    precision={2}
                    addonAfter={t('team.pointRules.pointsSuffix')}
                    value={config.targets[code]}
                    disabled={!canEdit}
                    onChange={(value) => setConfig((current) => current ? ({ ...current, targets: { ...current.targets, [code]: Number(value ?? 0) } }) : current)}
                  />
                </Space>
              ))}
            </Space>
            <Space wrap>
              <Typography.Text>{t('team.pointRules.internalSatisfaction')}</Typography.Text>
              <InputNumber min={0} max={100} precision={2} addonAfter="%" value={config.internal_satisfaction_weight} disabled={!canEdit} onChange={(value) => setConfig((current) => current ? ({ ...current, internal_satisfaction_weight: Number(value ?? 0) }) : current)} />
              <Typography.Text>{t('team.pointRules.externalSatisfaction')}</Typography.Text>
              <InputNumber min={0} max={100} precision={2} addonAfter="%" value={config.external_satisfaction_weight} disabled={!canEdit} onChange={(value) => setConfig((current) => current ? ({ ...current, external_satisfaction_weight: Number(value ?? 0) }) : current)} />
            </Space>
          </Space>
        )}
      </Card>

      <Modal
        title={editing ? t('admin.pointRules.editTitle', { name: editing.name }) : t('admin.pointRules.title')}
        open={!!editing}
        onOk={() => void saveRule()}
        confirmLoading={savingRule}
        onCancel={() => setEditing(null)}
        destroyOnClose
      >
        <Form<RuleFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="points" label={t('admin.pointRules.col.points')} rules={[{ required: true, message: t('admin.pointRules.pointsRequired') }]}>
            <InputNumber min={0} step={0.5} precision={2} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="active" label={t('admin.pointRules.col.active')} valuePropName="checked">
            <Switch checkedChildren={t('admin.pointRules.enabled')} unCheckedChildren={t('admin.pointRules.disabled')} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}
