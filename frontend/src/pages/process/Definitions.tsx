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
  Steps,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
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
  ProcessStepDef,
  RoleDef,
  TicketType,
  UserGroup,
  WorkflowEntityType,
} from '../../api/types';
import { hasAnyRole, useAuthStore } from '../../stores/auth';

type DrawerMode = 'create' | 'edit' | 'new-version';

interface StepFormRow {
  name: string;
  default_role?: string | null;
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

const ENTITY_OPTIONS = (
  Object.keys(WORKFLOW_ENTITY_LABELS) as WorkflowEntityType[]
).map((k) => ({ value: k, label: WORKFLOW_ENTITY_LABELS[k] }));

const TICKET_TYPE_OPTIONS = (
  Object.keys(TICKET_TYPE_LABELS) as TicketType[]
).map((k) => ({ value: k, label: TICKET_TYPE_LABELS[k] }));

const AUTONOMY_OPTIONS = (
  Object.keys(AUTONOMY_LABELS) as AutonomyLevel[]
).map((k) => ({ value: k, label: AUTONOMY_LABELS[k] }));

const DRAWER_TITLES: Record<DrawerMode, string> = {
  create: '新建流程',
  edit: '编辑流程',
  'new-version': '另存新版本',
};

export default function Definitions() {
  const user = useAuthStore((s) => s.user);
  const isAdmin = hasAnyRole(user, ['admin']);

  const [items, setItems] = useState<ProcessDefinition[]>([]);
  const [loading, setLoading] = useState(false);

  const [roleOptions, setRoleOptions] = useState<
    { value: string; label: string }[]
  >([]);

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

  useEffect(() => {
    void Promise.all([
      api.getList<RoleDef>('/admin/roles').catch(() => ({ items: [] as RoleDef[], total: 0 })),
      api.getList<UserGroup>('/admin/groups').catch(() => ({ items: [] as UserGroup[], total: 0 })),
    ]).then(([roles, groups]) => {
      setRoleOptions([
        ...roles.items.map((r) => ({ value: r.code, label: r.name })),
        ...groups.items.map((g) => ({ value: `group:${g.code}`, label: `组：${g.name}` })),
      ]);
    });
  }, []);

  const roleLabel = useMemo(() => {
    const map = new Map(roleOptions.map((o) => [o.value, o.label]));
    return (v?: string | null) => (v ? map.get(v) ?? v : '未指派');
  }, [roleOptions]);

  /** 步骤是否可编辑：新建/另存新版本总是可编辑；编辑时受 steps_locked 限制 */
  const stepsEditable = mode !== 'edit' || !target?.steps_locked;

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
          default_role: s.default_role ?? undefined,
          autonomy_level: s.autonomy_level,
          sla_hours: s.sla_hours ?? undefined,
          description: s.description ?? undefined,
        })),
      });
    } else {
      form.setFieldsValue({
        entity_type: 'ticket',
        trigger_json: '',
        steps: [{ name: '', autonomy_level: 'L4' }],
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
      throw new Error('触发条件不是合法的 JSON 对象，请检查“高级 JSON”内容');
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
      default_role: s.default_role ?? null,
      autonomy_level: s.autonomy_level,
      sla_hours: s.sla_hours ?? null,
      description: s.description ?? null,
    }));
    setSaving(true);
    try {
      if (mode === 'create') {
        if (steps.length === 0) {
          message.error('请至少配置一个步骤');
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
        message.success('流程已创建');
      } else if (mode === 'edit' && target) {
        await api.patch(`/admin/process-definitions/${target.id}`, {
          name: values.name,
          trigger_condition: trigger,
          description: values.description ?? null,
          ...(stepsEditable ? { steps } : {}),
        });
        message.success('流程已更新');
      } else if (mode === 'new-version' && target) {
        await api.post(`/admin/process-definitions/${target.id}/new-version`, {
          name: values.name,
          trigger_condition: trigger,
          description: values.description ?? null,
          steps,
        });
        message.success('新版本已创建，旧版本已停用');
      }
      setDrawerOpen(false);
      void load();
    } catch {
      // TRIGGER_CONFLICT / STEPS_LOCKED 等中文错误已由拦截器统一提示
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (record: ProcessDefinition, checked: boolean) => {
    try {
      await api.patch(`/admin/process-definitions/${record.id}`, { active: checked });
      message.success(checked ? '流程已激活' : '流程已停用');
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
    { title: '名称', dataIndex: 'name' },
    {
      title: '默认指派',
      dataIndex: 'default_role',
      render: (v: string | null | undefined) => roleLabel(v),
    },
    {
      title: '自治级别',
      dataIndex: 'autonomy_level',
      width: 160,
      render: (v: AutonomyLevel) => AUTONOMY_LABELS[v] ?? v,
    },
    {
      title: 'SLA(小时)',
      dataIndex: 'sla_hours',
      width: 100,
      render: (v: number | null) => v ?? '-',
    },
    { title: '说明', dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
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
              checkedChildren="激活"
              unCheckedChildren="停用"
              disabled={!isAdmin}
              onChange={(checked) => void toggleActive(def, checked)}
            />
            {isAdmin && (
              <Button type="link" size="small" onClick={() => openDrawer('edit', def)}>
                编辑
              </Button>
            )}
            {isAdmin && def.steps_locked && (
              <Button
                type="link"
                size="small"
                onClick={() => openDrawer('new-version', def)}
              >
                另存新版本
              </Button>
            )}
          </Space>
        }
      >
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          <Space wrap size={16}>
            <Typography.Text type="secondary">
              实例数：{def.instance_count}
              {def.steps_locked && (
                <Tag color="orange" style={{ marginLeft: 8 }}>
                  步骤已锁定
                </Tag>
              )}
            </Typography.Text>
            <Typography.Text type="secondary">
              触发条件：
              {def.trigger_condition && Object.keys(def.trigger_condition).length > 0 ? (
                <Typography.Text code>
                  {JSON.stringify(def.trigger_condition)}
                </Typography.Text>
              ) : (
                '（无）'
              )}
            </Typography.Text>
          </Space>
          {def.description && (
            <Typography.Text type="secondary">{def.description}</Typography.Text>
          )}
          <div style={{ overflowX: 'auto', paddingTop: 4 }}>
            <Steps
              size="small"
              current={-1}
              items={def.steps.map((s) => ({
                title: s.name,
                description: `${roleLabel(s.default_role)} · ${s.autonomy_level}`,
              }))}
            />
          </div>
        </Space>
      </Card>
    </Col>
  );

  const grouped = (Object.keys(WORKFLOW_ENTITY_LABELS) as WorkflowEntityType[]).map(
    (et) => ({
      et,
      label: WORKFLOW_ENTITY_LABELS[et],
      defs: items.filter((d) => d.entity_type === et),
    }),
  );

  return (
    <Card
      title="流程定义"
      extra={
        isAdmin && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openDrawer('create')}>
            新建流程
          </Button>
        )
      }
    >
      <Spin spinning={loading}>
        {items.length === 0 && !loading ? (
          <Empty description="暂无流程定义" />
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
        title={DRAWER_TITLES[mode]}
        width={760}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => setDrawerOpen(false)}>取消</Button>
            <Button type="primary" loading={saving} onClick={() => void handleSave()}>
              保存
            </Button>
          </Space>
        }
      >
        {mode === 'edit' && target?.steps_locked && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message={`该流程已有 ${target.instance_count} 个实例，步骤已锁定`}
            description="如需调整步骤，请使用“另存新版本”。"
          />
        )}
        {mode === 'new-version' && target && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message={`将基于 v${target.version} 创建新版本（code 自动变更，如 ${target.code}@v${target.version + 1}），并停用旧版本`}
          />
        )}
        <Form<DefinitionForm> form={form} layout="vertical" preserve={false}>
          <Typography.Title level={5}>基本信息</Typography.Title>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="code"
                label="代码"
                rules={
                  mode === 'create'
                    ? [
                        { required: true, message: '请输入流程代码' },
                        {
                          pattern: /^[a-z0-9_]{2,32}$/,
                          message: '2-32 位小写字母、数字或下划线',
                        },
                      ]
                    : []
                }
              >
                <Input maxLength={32} disabled={mode !== 'create'} placeholder="如 incident_std" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="name"
                label="名称"
                rules={[{ required: true, message: '请输入流程名称' }]}
              >
                <Input maxLength={50} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="entity_type"
                label="单据类型"
                rules={[{ required: true, message: '请选择单据类型' }]}
              >
                <Select options={ENTITY_OPTIONS} disabled={mode !== 'create'} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="trigger_ticket_type"
                label="触发条件（工单类型）"
                tooltip='选择后自动生成 {"ticket_type": ...}；留空表示不按工单类型过滤'
              >
                <Select
                  allowClear
                  options={TICKET_TYPE_OPTIONS}
                  placeholder="不限"
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
                label="高级 JSON（触发条件，可直接编辑；留空 = 无条件）"
              >
                <Input.TextArea rows={2} placeholder='如 {"ticket_type": "incident"}' />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={200} />
          </Form.Item>

          <Typography.Title level={5}>步骤定义</Typography.Title>
          {stepsEditable ? (
            <Form.List name="steps">
              {(fields, { add, remove, move }) => (
                <>
                  {fields.map((field, index) => (
                    <Row gutter={8} key={field.key} align="top" wrap={false}>
                      <Col flex="30px" style={{ paddingTop: 5 }}>
                        <Typography.Text type="secondary">{index + 1}</Typography.Text>
                      </Col>
                      <Col flex="auto">
                        <Row gutter={8}>
                          <Col span={6}>
                            <Form.Item
                              name={[field.name, 'name']}
                              rules={[{ required: true, message: '步骤名称必填' }]}
                              style={{ marginBottom: 8 }}
                            >
                              <Input placeholder="步骤名称" maxLength={50} />
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
                                placeholder="默认指派（角色/组）"
                                options={roleOptions}
                              />
                            </Form.Item>
                          </Col>
                          <Col span={5}>
                            <Form.Item
                              name={[field.name, 'autonomy_level']}
                              rules={[{ required: true, message: '必选' }]}
                              style={{ marginBottom: 8 }}
                            >
                              <Select placeholder="自治级别" options={AUTONOMY_OPTIONS} />
                            </Form.Item>
                          </Col>
                          <Col span={3}>
                            <Form.Item
                              name={[field.name, 'sla_hours']}
                              style={{ marginBottom: 8 }}
                            >
                              <InputNumber
                                min={0}
                                placeholder="SLA(h)"
                                style={{ width: '100%' }}
                              />
                            </Form.Item>
                          </Col>
                          <Col span={4}>
                            <Form.Item
                              name={[field.name, 'description']}
                              style={{ marginBottom: 8 }}
                            >
                              <Input placeholder="说明" maxLength={100} />
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
                    onClick={() => add({ name: '', autonomy_level: 'L4' })}
                  >
                    添加步骤
                  </Button>
                  <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
                    步骤顺序即执行顺序（保存时自动按当前顺序编号）。自治级别：L1 全自动 ~ L4 纯人工。
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
