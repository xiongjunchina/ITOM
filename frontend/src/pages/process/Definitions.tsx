import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
  message,
  Popconfirm} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { api } from '../../api/client';
import {
  AUTONOMY_LABELS,
  TICKET_TYPE_LABELS,
  WORKFLOW_ENTITY_LABELS,
} from '../../api/types';
import type {
  AutonomyLevel,
  ProcessDefinition,
  ProcessNodeType,
  ProcessStepDef,
  TicketType,
  WorkflowEntityType,
} from '../../api/types';
import FlowDiagram from '../../components/FlowDiagram';
import type { FlowDiagramStep } from '../../components/FlowDiagram';
import { useRoleOptions } from '../../utils/roleOptions';
import { hasAnyRole, useAuthStore } from '../../stores/auth';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';

type DrawerMode = 'create' | 'edit' | 'new-version';

interface StepFormRow {
  name: string;
  node_type: ProcessNodeType;
  default_role?: string | null;
  cc_roles?: string[];
  autonomy_level: AutonomyLevel;
  sla_hours?: number | null;
  description?: string | null;
}

interface DefinitionForm {
  code: string;
  name: string;
  entity_type: WorkflowEntityType;
  trigger_ticket_type?: TicketType;
  trigger_json?: string;
  description?: string;
  steps: StepFormRow[];
}

export default function Definitions() {
  const t = useT();
  const et = useEnums();
  const user = useAuthStore((s) => s.user);
  const isAdmin = hasAnyRole(user, ['admin']);

  const entityOptions = (Object.keys(WORKFLOW_ENTITY_LABELS) as WorkflowEntityType[]).map((k) => ({
    value: k,
    label: et.workflowEntity(k),
  }));
  const ticketTypeOptions = (Object.keys(TICKET_TYPE_LABELS) as TicketType[]).map((k) => ({
    value: k,
    label: et.ticketType(k),
  }));
  const autonomyOptions = (Object.keys(AUTONOMY_LABELS) as AutonomyLevel[]).map((k) => ({
    value: k,
    label: et.autonomy(k),
  }));
  const nodeTypeOptions = [
    { value: 'processing' as const, label: t('proc.node.processing') },
    { value: 'approval' as const, label: t('proc.node.approval') },
  ];

  const [items, setItems] = useState<ProcessDefinition[]>([]);
  const [loading, setLoading] = useState(false);

  /** 角色 + 用户组选项（default_role / cc_roles 共用词表）与中文名映射 */
  const { roleOptions, roleLabel } = useRoleOptions();

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [mode, setMode] = useState<DrawerMode>('create');
  const [target, setTarget] = useState<ProcessDefinition | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<DefinitionForm>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<ProcessDefinition>('/admin/process-definitions');
      setItems(res.items);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** 步骤是否可编辑：新建/另存新版本总是可编辑；编辑时受 steps_locked 限制 */
  const stepsEditable = mode !== 'edit' || !target?.steps_locked;

  /** Drawer 实时预览：Form.List 值驱动示意图即时更新；步骤锁定时用 target.steps */
  const stepsWatch = Form.useWatch('steps', form) as StepFormRow[] | undefined;
  const previewSteps: FlowDiagramStep[] = useMemo(() => {
    const rows: (StepFormRow | ProcessStepDef | undefined)[] = stepsEditable
      ? stepsWatch ?? []
      : target?.steps ?? [];
    return rows
      .filter((r): r is StepFormRow | ProcessStepDef => !!r)
      .map((s, i) => ({
        seq: i + 1,
        name: (s.name ?? '').trim(),
        node_type: s.node_type ?? 'processing',
        default_role: s.default_role ?? null,
        cc_roles: s.cc_roles ?? [],
        autonomy_level: s.autonomy_level,
        sla_hours: s.sla_hours ?? null,
      }));
  }, [stepsEditable, stepsWatch, target]);

  const openDrawer = (m: DrawerMode, record?: ProcessDefinition) => {
    setMode(m);
    setTarget(record ?? null);
    form.resetFields();
    if (record) {
      const trigger = record.trigger_condition ?? null;
      form.setFieldsValue({
        code: record.code,
        name: record.name,
        entity_type: record.entity_type,
        trigger_ticket_type:
          trigger && typeof trigger.ticket_type === 'string'
            ? (trigger.ticket_type as TicketType)
            : undefined,
        trigger_json: trigger ? JSON.stringify(trigger) : '',
        description: record.description ?? undefined,
        steps: record.steps.map((s) => ({
          name: s.name,
          node_type: s.node_type ?? 'processing',
          default_role: s.default_role ?? undefined,
          cc_roles: s.cc_roles ?? [],
          autonomy_level: s.autonomy_level,
          sla_hours: s.sla_hours ?? undefined,
          description: s.description ?? undefined,
        })),
      });
    } else {
      form.setFieldsValue({
        entity_type: 'ticket',
        trigger_json: '',
        steps: [{ name: '', node_type: 'processing', autonomy_level: 'L4', cc_roles: [] }],
      });
    }
    setDrawerOpen(true);
  };

  const parseTrigger = (raw?: string): Record<string, unknown> | null => {
    const text = (raw ?? '').trim();
    if (!text) return null;
    try {
      const parsed: unknown = JSON.parse(text);
      if (parsed === null) return null;
      if (typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('not an object');
      }
      return parsed as Record<string, unknown>;
    } catch {
      throw new Error(t('proc.triggerInvalid'));
    }
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    let trigger: Record<string, unknown> | null;
    try {
      trigger = parseTrigger(values.trigger_json);
    } catch (e) {
      message.error((e as Error).message);
      return;
    }
    const steps = (values.steps ?? []).map((s, i) => ({
      seq: i + 1,
      name: s.name,
      node_type: s.node_type ?? 'processing',
      default_role: s.default_role ?? null,
      cc_roles: s.cc_roles ?? [],
      autonomy_level: s.autonomy_level,
      sla_hours: s.sla_hours ?? null,
      description: s.description ?? null,
    }));
    setSaving(true);
    try {
      if (mode === 'create') {
        if (steps.length === 0) {
          message.error(t('proc.stepAtLeastOne'));
          return;
        }
        await api.post('/admin/process-definitions', {
          code: values.code,
          name: values.name,
          entity_type: values.entity_type,
          trigger_condition: trigger,
          description: values.description ?? null,
          steps,
        });
        message.success(t('proc.created'));
      } else if (mode === 'edit' && target) {
        await api.patch(`/admin/process-definitions/${target.id}`, {
          name: values.name,
          trigger_condition: trigger,
          description: values.description ?? null,
          ...(stepsEditable ? { steps } : {}),
        });
        message.success(t('proc.updated'));
      } else if (mode === 'new-version' && target) {
        await api.post(`/admin/process-definitions/${target.id}/new-version`, {
          name: values.name,
          trigger_condition: trigger,
          description: values.description ?? null,
          steps,
        });
        message.success(t('proc.newVersionCreated'));
      }
      setDrawerOpen(false);
      void load();
    } catch {
      // TRIGGER_CONFLICT / STEPS_LOCKED 等中文错误已由拦截器统一提示
    } finally {
      setSaving(false);
    }
  };

  const deleteDefinition = async (def: ProcessDefinition) => {
    try {
      await api.delete(`/admin/process-definitions/${def.id}`);
      message.success(t('proc.deleted'));
      void load();
    } catch {
      // 已统一提示（PROCESS_ACTIVE / PROCESS_IN_USE）
    }
  };

  const toggleActive = async (record: ProcessDefinition, checked: boolean) => {
    try {
      await api.patch(`/admin/process-definitions/${record.id}`, { active: checked });
      message.success(checked ? t('proc.activated') : t('proc.deactivated'));
      setItems((prev) =>
        prev.map((d) => (d.id === record.id ? { ...d, active: checked } : d)),
      );
    } catch {
      // 已统一提示
      void load();
    }
  };

  const lockedStepColumns: ColumnsType<ProcessStepDef> = [
    { title: '#', dataIndex: 'seq', width: 50 },
    { title: t('proc.col.name'), dataIndex: 'name' },
    {
      title: t('proc.col.nodeType'),
      dataIndex: 'node_type',
      width: 120,
      render: (v: ProcessNodeType) => t(v === 'approval' ? 'proc.node.approval' : 'proc.node.processing'),
    },
    {
      title: t('proc.col.defaultAssign'),
      dataIndex: 'default_role',
      render: (v: string | null | undefined) => roleLabel(v),
    },
    {
      title: t('proc.col.cc'),
      dataIndex: 'cc_roles',
      render: (v: string[] | undefined) =>
        v && v.length > 0 ? v.map((k) => roleLabel(k)).join('、') : '-',
    },
    {
      title: t('proc.col.autonomy'),
      dataIndex: 'autonomy_level',
      width: 160,
      render: (v: AutonomyLevel) => et.autonomy(v),
    },
    {
      title: t('proc.col.sla'),
      dataIndex: 'sla_hours',
      width: 100,
      render: (v: number | null) => v ?? '-',
    },
    { title: t('proc.col.desc'), dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
  ];

  const renderCard = (def: ProcessDefinition) => (
    <Col xs={24} xl={12} key={def.id}>
      <Card
        size="small"
        title={
          <Space>
            <span>{def.name}</span>
            <Tag>{def.code}</Tag>
            <Tag color="geekblue">v{def.version}</Tag>
          </Space>
        }
        extra={
          <Space>
            <Switch
              size="small"
              checked={def.active}
              checkedChildren={t('proc.active')}
              unCheckedChildren={t('proc.inactive')}
              disabled={!isAdmin}
              onChange={(checked) => void toggleActive(def, checked)}
            />
            {isAdmin && (
              <Button type="link" size="small" onClick={() => openDrawer('edit', def)}>
                {t('common.edit')}
              </Button>
            )}
            {isAdmin && def.steps_locked && (
              <Button
                type="link"
                size="small"
                onClick={() => openDrawer('new-version', def)}
              >
                {t('proc.drawer.new-version')}
              </Button>
            )}
            {isAdmin && !def.active && def.instance_count === 0 && (
              <Popconfirm
                title={t('proc.deleteConfirm', { name: def.name })}
                description={t('proc.deleteDesc')}
                okText={t('common.delete')}
                okButtonProps={{ danger: true }}
                cancelText={t('common.cancel')}
                onConfirm={() => void deleteDefinition(def)}
              >
                <Button type="link" size="small" danger>
                  {t('common.delete')}
                </Button>
              </Popconfirm>
            )}
          </Space>
        }
      >
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          <Space wrap size={16}>
            <Typography.Text type="secondary">
              {t('proc.instanceCount', { n: def.instance_count })}
              {def.steps_locked && (
                <Tag color="orange" style={{ marginLeft: 8 }}>
                  {t('proc.stepsLocked')}
                </Tag>
              )}
            </Typography.Text>
            <Typography.Text type="secondary">
              {t('proc.triggerLabel')}
              {def.trigger_condition && Object.keys(def.trigger_condition).length > 0 ? (
                <Typography.Text code>
                  {JSON.stringify(def.trigger_condition)}
                </Typography.Text>
              ) : (
                t('proc.triggerNone')
              )}
            </Typography.Text>
          </Space>
          {def.description && (
            <Typography.Text type="secondary">{def.description}</Typography.Text>
          )}
          <div style={{ paddingTop: 4 }}>
            <FlowDiagram steps={def.steps} roleLabel={roleLabel} />
          </div>
        </Space>
      </Card>
    </Col>
  );

  // 分组：工单类按触发条件 ticket_type 拆为 ITSM(服务请求/变更/事件)（2026-07-14 用户要求，
  // 顺序同 ITSM 子菜单）；无触发条件的工单流程归「工单(其他)」；其余实体沿用实体标签。
  const groupKeyOf = (d: ProcessDefinition): string => {
    if (d.entity_type === 'ticket') {
      const tt = d.trigger_condition?.ticket_type;
      if (tt === 'service_request') return 'itsm_sr';
      if (tt === 'incident') return 'itsm_incident';
      return 'itsm_other';
    }
    if (d.entity_type === 'ticket_change') return 'itsm_change';
    return d.entity_type;
  };
  const groupMeta: { key: string; label: string }[] = [
    { key: 'itsm_sr', label: t('proc.group.itsmSr') },
    { key: 'itsm_change', label: t('proc.group.itsmChange') },
    { key: 'itsm_incident', label: t('proc.group.itsmIncident') },
    { key: 'itsm_other', label: t('proc.group.itsmOther') },
    ...(Object.keys(WORKFLOW_ENTITY_LABELS) as WorkflowEntityType[])
      .filter((e) => e !== 'ticket' && e !== 'ticket_change')
      .map((e) => ({ key: e as string, label: et.workflowEntity(e) })),
  ];
  const grouped = groupMeta.map((g) => ({
    et: g.key,
    label: g.label,
    defs: items.filter((d) => groupKeyOf(d) === g.key),
  }));

  return (
    <Card
      title={t('proc.title')}
      extra={
        isAdmin && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openDrawer('create')}>
            {t('proc.drawer.create')}
          </Button>
        )
      }
    >
      <Spin spinning={loading}>
        {items.length === 0 && !loading ? (
          <Empty description={t('proc.emptyDefs')} />
        ) : (
          grouped
            .filter((g) => g.defs.length > 0)
            .map((g) => (
              <div key={g.et} style={{ marginBottom: 24 }}>
                <Typography.Title level={5}>{g.label}</Typography.Title>
                <Row gutter={[16, 16]}>{g.defs.map(renderCard)}</Row>
              </div>
            ))
        )}
      </Spin>

      <Drawer
        title={t('proc.drawer.' + mode)}
        width={760}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => setDrawerOpen(false)}>{t('common.cancel')}</Button>
            <Button type="primary" loading={saving} onClick={() => void handleSave()}>
              {t('common.save')}
            </Button>
          </Space>
        }
      >
        {mode === 'edit' && target?.steps_locked && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message={t('proc.lockedAlertMsg', { n: target.instance_count })}
            description={t('proc.lockedAlertDesc')}
          />
        )}
        {mode === 'new-version' && target && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message={t('proc.newVersionAlert', {
              version: target.version,
              code: target.code,
              next: target.version + 1,
            })}
          />
        )}
        <Card
          size="small"
          title={t('proc.preview')}
          style={{ marginBottom: 16 }}
          styles={{ body: { background: '#fafafa' } }}
        >
          <FlowDiagram steps={previewSteps} roleLabel={roleLabel} />
        </Card>
        <Form<DefinitionForm> form={form} layout="vertical" preserve={false}>
          <Typography.Title level={5}>{t('proc.basicInfo')}</Typography.Title>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="code"
                label={t('proc.code')}
                rules={
                  mode === 'create'
                    ? [
                        { required: true, message: t('proc.codeRequired') },
                        {
                          pattern: /^[a-z0-9_]{2,32}$/,
                          message: t('proc.codePattern'),
                        },
                      ]
                    : []
                }
              >
                <Input maxLength={32} disabled={mode !== 'create'} placeholder={t('proc.codePlaceholder')} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="name"
                label={t('proc.name')}
                rules={[{ required: true, message: t('proc.nameRequired') }]}
              >
                <Input maxLength={50} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="entity_type"
                label={t('proc.entityType')}
                rules={[{ required: true, message: t('proc.entityTypeRequired') }]}
              >
                <Select options={entityOptions} disabled={mode !== 'create'} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="trigger_ticket_type"
                label={t('proc.triggerTicketType')}
                tooltip={t('proc.triggerTooltip')}
              >
                <Select
                  allowClear
                  options={ticketTypeOptions}
                  placeholder={t('proc.triggerAny')}
                  onChange={(v: TicketType | undefined) => {
                    form.setFieldValue(
                      'trigger_json',
                      v ? JSON.stringify({ ticket_type: v }) : '',
                    );
                  }}
                />
              </Form.Item>
            </Col>
            <Col span={16}>
              <Form.Item
                name="trigger_json"
                label={t('proc.advancedJson')}
              >
                <Input.TextArea rows={2} placeholder={t('proc.advancedJsonPlaceholder')} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="description" label={t('proc.desc')}>
            <Input.TextArea rows={2} maxLength={200} />
          </Form.Item>

          <Typography.Title level={5}>{t('proc.stepDef')}</Typography.Title>
          {stepsEditable ? (
            <Form.List name="steps">
              {(fields, { add, remove, move }) => (
                <>
                  {fields.map((field, index) => (
                    <Row
                      gutter={8}
                      key={field.key}
                      align="top"
                      wrap={false}
                      style={{
                        border: '1px solid #f0f0f0',
                        borderRadius: 8,
                        padding: '8px 8px 0',
                        marginBottom: 8,
                      }}
                    >
                      <Col flex="30px" style={{ paddingTop: 5 }}>
                        <Typography.Text type="secondary">{index + 1}</Typography.Text>
                      </Col>
                      <Col flex="auto">
                        <Row gutter={8}>
                          <Col span={5}>
                            <Form.Item
                              name={[field.name, 'name']}
                              rules={[{ required: true, message: t('proc.stepNameRequired') }]}
                              style={{ marginBottom: 8 }}
                            >
                              <Input placeholder={t('proc.stepNamePlaceholder')} maxLength={50} />
                            </Form.Item>
                          </Col>
                          <Col span={5}>
                            <Form.Item
                              name={[field.name, 'node_type']}
                              rules={[{ required: true, message: t('proc.required') }]}
                              style={{ marginBottom: 8 }}
                            >
                              <Select placeholder={t('proc.node.placeholder')} options={nodeTypeOptions} />
                            </Form.Item>
                          </Col>
                          <Col span={6}>
                            <Form.Item
                              name={[field.name, 'default_role']}
                              style={{ marginBottom: 8 }}
                            >
                              <Select
                                allowClear
                                showSearch
                                optionFilterProp="label"
                                placeholder={t('proc.defaultAssignPlaceholder')}
                                options={roleOptions}
                              />
                            </Form.Item>
                          </Col>
                          <Col span={5}>
                            <Form.Item
                              name={[field.name, 'autonomy_level']}
                              rules={[{ required: true, message: t('proc.required') }]}
                              style={{ marginBottom: 8 }}
                            >
                              <Select placeholder={t('proc.autonomyPlaceholder')} options={autonomyOptions} />
                            </Form.Item>
                          </Col>
                          <Col span={3}>
                            <Form.Item
                              name={[field.name, 'sla_hours']}
                              style={{ marginBottom: 8 }}
                            >
                              <InputNumber
                                min={0}
                                placeholder={t('proc.slaPlaceholder')}
                                style={{ width: '100%' }}
                              />
                            </Form.Item>
                          </Col>
                        </Row>
                        <Row gutter={8}>
                          <Col span={14}>
                            <Form.Item
                              name={[field.name, 'cc_roles']}
                              style={{ marginBottom: 8 }}
                            >
                              <Select
                                mode="multiple"
                                allowClear
                                showSearch
                                optionFilterProp="label"
                                maxTagCount="responsive"
                                placeholder={t('proc.ccPlaceholder')}
                                options={roleOptions}
                              />
                            </Form.Item>
                          </Col>
                          <Col span={10}>
                            <Form.Item
                              name={[field.name, 'description']}
                              style={{ marginBottom: 8 }}
                            >
                              <Input placeholder={t('proc.stepDescPlaceholder')} maxLength={100} />
                            </Form.Item>
                          </Col>
                        </Row>
                      </Col>
                      <Col flex="96px">
                        <Space size={0}>
                          <Button
                            type="text"
                            size="small"
                            icon={<ArrowUpOutlined />}
                            disabled={index === 0}
                            onClick={() => move(index, index - 1)}
                          />
                          <Button
                            type="text"
                            size="small"
                            icon={<ArrowDownOutlined />}
                            disabled={index === fields.length - 1}
                            onClick={() => move(index, index + 1)}
                          />
                          <Button
                            type="text"
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            onClick={() => remove(index)}
                          />
                        </Space>
                      </Col>
                    </Row>
                  ))}
                  <Button
                    type="dashed"
                    block
                    icon={<PlusOutlined />}
                    onClick={() => add({ name: '', node_type: 'processing', autonomy_level: 'L4', cc_roles: [] })}
                  >
                    {t('proc.addStep')}
                  </Button>
                  <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
                    {t('proc.stepHint')}
                  </Typography.Paragraph>
                </>
              )}
            </Form.List>
          ) : (
            <Table<ProcessStepDef>
              rowKey="seq"
              size="small"
              columns={lockedStepColumns}
              dataSource={target?.steps ?? []}
              pagination={false}
            />
          )}
        </Form>
      </Drawer>
    </Card>
  );
}
