import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Collapse,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  List,
  Popconfirm,
  Popover,
  Radio,
  Result,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  DeleteOutlined,
  EditFilled,
  EditOutlined,
  MinusCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import PermTabs from '../../components/PermTabs';
import { hasPermission, useAuthStore } from '../../stores/auth';
import { currentPeriod, recentPeriods } from '../../utils/period';
import type {
  PerfDimension,
  PerfScheme,
  PerformanceData,
  PerformanceRow,
  Position,
} from '../../api/types';

const GRAY = 'rgba(0, 0, 0, 0.25)';

/** 空值单元格：无数据不计入 */
const EMPTY_CELL = <span style={{ color: GRAY }}>—</span>;

// ============ Tab A 总览 ============

interface AdjFormValues {
  kind: 'bonus' | 'penalty';
  points: number;
  reason: string;
}

function PerfOverview() {
  const [period, setPeriod] = useState(currentPeriod());
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);

  const user = useAuthStore((s) => s.user);
  // 写权限：优先权限矩阵；存量会话缺失 permissions 时放行（后端仍会校验并中文提示）
  const canEdit = user?.permissions ? hasPermission(user, 'performance', 'edit') : true;

  // 维度核定编辑器（Popover 锚定在被点击的单元格上）
  const [editor, setEditor] = useState<{
    personId: string;
    code: string;
    /** 当前已核定分（null=未核定，清除按钮置灰） */
    override: number | null;
  } | null>(null);
  const [editorValue, setEditorValue] = useState<number | null>(null);
  const [editorSaving, setEditorSaving] = useState(false);

  // 加减分 Drawer：仅存 person_id，行数据从最新 data 派生（增删后随表格一起刷新）
  const [adjPersonId, setAdjPersonId] = useState<string | null>(null);
  const [adjSaving, setAdjSaving] = useState(false);
  const [adjForm] = Form.useForm<AdjFormValues>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.get<PerformanceData>('/team/performance', { period }));
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 403) setForbidden(true);
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    void load();
  }, [load]);

  const saveOverride = async (score: number | null) => {
    if (!editor) return;
    setEditorSaving(true);
    try {
      await api.put('/perf/overrides', {
        period,
        person_id: editor.personId,
        dimension_code: editor.code,
        score,
      });
      message.success(score == null ? '已清除核定，恢复系统参考值' : '核定分已保存');
      setEditor(null);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setEditorSaving(false);
    }
  };

  const submitAdjustment = async () => {
    const values = await adjForm.validateFields();
    if (!adjPersonId) return;
    setAdjSaving(true);
    try {
      await api.post('/perf/adjustments', { period, person_id: adjPersonId, ...values });
      message.success('加减分事项已添加');
      adjForm.resetFields();
      void load();
    } catch {
      // 已统一提示
    } finally {
      setAdjSaving(false);
    }
  };

  const removeAdjustment = async (id: string) => {
    try {
      await api.delete(`/perf/adjustments/${id}`);
      message.success('加减分事项已删除');
      void load();
    } catch {
      // 已统一提示
    }
  };

  if (forbidden) {
    return (
      <Card>
        <Result status="403" title="无权限" subTitle="您没有人效评分的查看权限，请联系管理员开通。" />
      </Card>
    );
  }

  const dimensions = data?.dimensions ?? [];
  const adjRow = data?.rows.find((r) => r.person_id === adjPersonId) ?? null;

  // 核定编辑弹层内容（同一时刻只有一个单元格打开）
  const editorContent = (
    <Space direction="vertical" size={8} style={{ width: 240 }}>
      <InputNumber
        min={0}
        max={100}
        value={editorValue}
        onChange={(v) => setEditorValue(v)}
        style={{ width: '100%' }}
        placeholder="核定分（0-100）"
      />
      <Space>
        <Button
          type="primary"
          size="small"
          loading={editorSaving}
          onClick={() => {
            if (editorValue == null) {
              message.warning('请输入 0-100 的核定分');
              return;
            }
            void saveOverride(editorValue);
          }}
        >
          保存核定
        </Button>
        <Button
          size="small"
          disabled={editor?.override == null}
          loading={editorSaving && editor?.override != null}
          onClick={() => void saveOverride(null)}
        >
          清除核定（恢复系统值）
        </Button>
      </Space>
    </Space>
  );

  const columns: ColumnsType<PerformanceRow> = [
    { title: '姓名', dataIndex: 'person_name', width: 100, fixed: 'left' },
    { title: '岗位', dataIndex: 'position_name', width: 130, render: (v: string | null) => v || '-' },
    {
      title: '适用方案',
      dataIndex: 'scheme_name',
      width: 150,
      render: (v: string | null) => (v ? v : <Tag>未配置方案</Tag>),
    },
    {
      title: '加分项',
      dataIndex: 'bonus',
      width: 80,
      render: (v: number) =>
        v > 0 ? <span style={{ color: '#52c41a', fontWeight: 600 }}>+{v}</span> : <span style={{ color: GRAY }}>-</span>,
    },
    {
      title: '扣分项',
      dataIndex: 'penalty',
      width: 80,
      render: (v: number) =>
        v > 0 ? <span style={{ color: '#ff4d4f', fontWeight: 600 }}>−{v}</span> : <span style={{ color: GRAY }}>-</span>,
    },
    {
      title: '加减分说明',
      key: 'adj_reasons',
      width: 180,
      ellipsis: { showTitle: false },
      render: (_, r) => {
        const text = (r.adjustments ?? []).map((a) => a.reason).join('；');
        if (!text) return EMPTY_CELL;
        return (
          <Tooltip placement="topLeft" title={text}>
            {text}
          </Tooltip>
        );
      },
    },
    {
      title: '总分',
      dataIndex: 'total',
      width: 90,
      sorter: (a, b) => (a.total ?? -1) - (b.total ?? -1),
      defaultSortOrder: 'descend',
      render: (v: number | null, r) => (
        <Tooltip title={`基础分 ${r.base_score ?? '—'} + 加分 ${r.bonus ?? 0} − 扣分 ${r.penalty ?? 0}`}>
          {v == null ? EMPTY_CELL : <Typography.Text strong>{v}</Typography.Text>}
        </Tooltip>
      ),
    },
    ...dimensions.map<ColumnsType<PerformanceRow>[number]>((d) => ({
      title: (
        <Tooltip title={d.description}>
          <span>{d.name}</span>
        </Tooltip>
      ),
      key: d.code,
      width: 110,
      render: (_, r) => {
        const cell = r.dims[d.code];
        if (!cell) return EMPTY_CELL;
        const overridden = cell.override != null;
        const inner = (
          <Tooltip
            title={
              overridden
                ? `系统参考值：${cell.score ?? '无数据'}，已人工核定`
                : `权重 ${cell.weight}${canEdit ? '，点击可人工核定' : ''}`
            }
          >
            <span
              style={{
                cursor: canEdit ? 'pointer' : undefined,
                color: overridden ? '#1677ff' : undefined,
                fontWeight: overridden ? 600 : undefined,
              }}
            >
              {cell.effective == null ? <span style={{ color: GRAY }}>—</span> : cell.effective}
              {overridden && <EditFilled style={{ fontSize: 11, marginLeft: 4, color: '#1677ff' }} />}
            </span>
          </Tooltip>
        );
        if (!canEdit) return inner;
        return (
          <Popover
            trigger="click"
            open={editor?.personId === r.person_id && editor?.code === d.code}
            onOpenChange={(open) => {
              if (open) {
                setEditor({ personId: r.person_id, code: d.code, override: cell.override });
                setEditorValue(cell.effective);
              } else {
                // 仅当当前打开的就是本单元格时才关闭，避免点击其他单元格时相互覆盖
                setEditor((prev) =>
                  prev?.personId === r.person_id && prev?.code === d.code ? null : prev,
                );
              }
            }}
            title={`核定维度分：${r.person_name} · ${d.name}`}
            content={editorContent}
          >
            {inner}
          </Popover>
        );
      },
    })),
    ...(canEdit
      ? [
          {
            title: '操作',
            key: 'action',
            width: 90,
            fixed: 'right',
            render: (_: unknown, r: PerformanceRow) => (
              <Button type="link" size="small" onClick={() => setAdjPersonId(r.person_id)}>
                加减分
              </Button>
            ),
          } as ColumnsType<PerformanceRow>[number],
        ]
      : []),
  ];

  return (
    <Card
      title="人效总览"
      extra={
        <Select
          value={period}
          style={{ width: 130 }}
          onChange={(p) => {
            setPeriod(p);
            setEditor(null);
          }}
          options={recentPeriods(2).map((p) => ({ value: p, label: p }))}
        />
      }
    >
      {data?.note && <Alert type="info" showIcon style={{ marginBottom: 8 }} message={data.note} />}
      <Collapse
        ghost
        style={{ marginBottom: 8 }}
        items={[
          {
            key: 'dims',
            label: '维度口径说明',
            children: (
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {dimensions.map((d) => (
                  <li key={d.code} style={{ marginBottom: 4 }}>
                    <Typography.Text strong>{d.name}</Typography.Text>
                    <Typography.Text type="secondary">：{d.description}</Typography.Text>
                  </li>
                ))}
              </ul>
            ),
          },
        ]}
      />
      <Table<PerformanceRow>
        rowKey="person_id"
        loading={loading}
        columns={columns}
        dataSource={data?.rows ?? []}
        scroll={{ x: 810 + dimensions.length * 110 + (canEdit ? 90 : 0) }}
        pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 人` }}
      />

      <Drawer
        title={`加减分事项：${adjRow?.person_name ?? ''}（${period}）`}
        width={440}
        open={adjPersonId != null}
        onClose={() => setAdjPersonId(null)}
        destroyOnClose
      >
        <List
          size="small"
          header={
            <Typography.Text type="secondary">
              本期事项（{adjRow?.adjustments.length ?? 0} 条）
            </Typography.Text>
          }
          dataSource={adjRow?.adjustments ?? []}
          locale={{ emptyText: '本期暂无加减分事项' }}
          renderItem={(a) => (
            <List.Item
              actions={[
                <Popconfirm
                  key="del"
                  title="确定删除该加减分事项？"
                  onConfirm={() => void removeAdjustment(a.id)}
                >
                  <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={8}>
                    <Tag color={a.kind === 'bonus' ? 'green' : 'red'}>
                      {a.kind === 'bonus' ? '加分' : '扣分'}
                    </Tag>
                    <span style={{ color: a.kind === 'bonus' ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>
                      {a.kind === 'bonus' ? `+${a.points}` : `−${a.points}`}
                    </span>
                  </Space>
                }
                description={
                  <>
                    <div>{a.reason}</div>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {a.created_at ? dayjs(a.created_at).format('YYYY-MM-DD HH:mm') : ''}
                    </Typography.Text>
                  </>
                }
              />
            </List.Item>
          )}
        />
        <Divider style={{ margin: '16px 0 12px' }}>添加事项</Divider>
        <Form<AdjFormValues> form={adjForm} layout="vertical" preserve={false} initialValues={{ kind: 'bonus' }}>
          <Form.Item name="kind" label="类型" rules={[{ required: true, message: '请选择类型' }]}>
            <Radio.Group
              optionType="button"
              buttonStyle="solid"
              options={[
                { value: 'bonus', label: '加分' },
                { value: 'penalty', label: '扣分' },
              ]}
            />
          </Form.Item>
          <Form.Item name="points" label="分值" rules={[{ required: true, message: '请输入分值' }]}>
            <InputNumber min={0.1} max={1000} style={{ width: '100%' }} placeholder="须大于 0" />
          </Form.Item>
          <Form.Item
            name="reason"
            label="事项说明"
            rules={[
              { required: true, message: '请填写事项说明' },
              { min: 2, message: '至少 2 个字符' },
            ]}
          >
            <Input.TextArea
              rows={3}
              maxLength={200}
              showCount
              placeholder="如：重保期间通宵处置故障 / 违规操作生产库"
            />
          </Form.Item>
          <Button
            type="primary"
            block
            icon={<PlusOutlined />}
            loading={adjSaving}
            onClick={() => void submitAdjustment()}
          >
            添加
          </Button>
        </Form>
      </Drawer>
    </Card>
  );
}

// ============ Tab B 计分规则 ============

interface SchemeFormValues {
  name: string;
  description?: string;
  is_default?: boolean;
  position_ids?: string[];
  dimensions?: { code?: string; weight?: number }[];
}

function PerfSchemes() {
  const [items, setItems] = useState<PerfScheme[]>([]);
  const [loading, setLoading] = useState(true);
  const [dims, setDims] = useState<PerfDimension[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);

  const [drawer, setDrawer] = useState<{ open: boolean; editing: PerfScheme | null }>({
    open: false,
    editing: null,
  });
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<SchemeFormValues>();
  const watchDims = Form.useWatch('dimensions', form);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<PerfScheme>('/perf/schemes');
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
    api
      .getList<PerfDimension>('/perf/dimensions')
      .then((res) => setDims(res.items))
      .catch(() => undefined);
    api
      .getList<Position>('/positions', { page: 1, page_size: 999 })
      .then((res) => setPositions(res.items))
      .catch(() => undefined);
  }, []);

  const openCreate = () => {
    setDrawer({ open: true, editing: null });
    form.resetFields();
    form.setFieldsValue({ dimensions: [{}] });
  };

  const openEdit = (s: PerfScheme) => {
    setDrawer({ open: true, editing: s });
    form.setFieldsValue({
      name: s.name,
      description: s.description ?? undefined,
      is_default: s.is_default,
      position_ids: s.position_ids,
      dimensions: s.dimensions.map((d) => ({ code: d.code, weight: d.weight })),
    });
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    const payload = {
      name: values.name,
      description: values.description || null,
      position_ids: values.position_ids ?? [],
      dimensions: (values.dimensions ?? []).map((d) => ({ code: d.code, weight: d.weight })),
      is_default: values.is_default ?? false,
      // 启停由列表 Switch 控制，编辑不改动；新建默认启用
      active: drawer.editing ? drawer.editing.active : true,
    };
    setSaving(true);
    try {
      if (drawer.editing) {
        await api.patch(`/perf/schemes/${drawer.editing.id}`, payload);
        message.success('方案已更新');
      } else {
        await api.post('/perf/schemes', payload);
        message.success('方案已创建');
      }
      setDrawer({ open: false, editing: null });
      void load();
    } catch {
      // POSITION_CONFLICT / INVALID_DIMENSION / DUPLICATE_DIMENSION 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (s: PerfScheme, active: boolean) => {
    try {
      await api.patch(`/perf/schemes/${s.id}`, {
        name: s.name,
        description: s.description,
        position_ids: s.position_ids,
        dimensions: s.dimensions,
        is_default: s.is_default,
        active,
      });
      message.success(active ? '方案已启用' : '方案已停用');
      void load();
    } catch {
      // 已统一提示
    }
  };

  const handleDelete = async (s: PerfScheme) => {
    try {
      await api.delete(`/perf/schemes/${s.id}`);
      message.success('方案已删除');
      void load();
    } catch {
      // 已统一提示
    }
  };

  const columns: ColumnsType<PerfScheme> = [
    {
      title: '方案名',
      dataIndex: 'name',
      width: 200,
      render: (v: string, r) => (
        <Space size={4}>
          <span>{v}</span>
          {r.is_default && <Tag color="blue">默认兜底</Tag>}
        </Space>
      ),
    },
    {
      title: '适用岗位',
      dataIndex: 'position_names',
      render: (names: string[], r) => {
        if (names.length > 0) {
          return (
            <Space size={4} wrap>
              {names.map((n) => (
                <Tag key={n}>{n}</Tag>
              ))}
            </Space>
          );
        }
        return r.is_default ? (
          <Typography.Text type="secondary">（未匹配方案的人员兜底）</Typography.Text>
        ) : (
          <span style={{ color: GRAY }}>未绑定岗位（不生效）</span>
        );
      },
    },
    { title: '维度数', width: 80, render: (_, r) => r.dimensions.length },
    {
      title: '权重合计',
      dataIndex: 'weight_total',
      width: 100,
      render: (v: number) =>
        v === 100 ? (
          v
        ) : (
          <Tooltip title="权重合计非 100：计分时按各维度权重占比归一">
            <span style={{ color: '#fa8c16' }}>{v}</span>
          </Tooltip>
        ),
    },
    {
      title: '启用',
      dataIndex: 'active',
      width: 80,
      render: (v: boolean, r) => <Switch checked={v} onChange={(next) => void toggleActive(r, next)} />,
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_, r) => (
        <Space size={0}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>
            编辑
          </Button>
          <Popconfirm title="确定删除该计分方案？" onConfirm={() => void handleDelete(r)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // 表单实时权重合计（建议 100，非强制）
  const weightTotal = (watchDims ?? []).reduce((sum, d) => sum + (Number(d?.weight) || 0), 0);
  const chosenCodes = (watchDims ?? []).map((d) => d?.code);

  return (
    <Card
      title="计分规则"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建方案
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="不同岗位可配置不同的评分维度与权重；未匹配任何方案的人员按默认兜底方案计分。维度口径为 v1 默认实现，正式口径确认后可调整。"
      />
      <Table<PerfScheme>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 900 }}
        pagination={false}
      />

      <Drawer
        title={drawer.editing ? '编辑方案' : '新建方案'}
        open={drawer.open}
        width={560}
        onClose={() => setDrawer({ open: false, editing: null })}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => setDrawer({ open: false, editing: null })}>取消</Button>
            <Button type="primary" loading={saving} onClick={() => void handleSave()}>
              保存
            </Button>
          </Space>
        }
      >
        <Form<SchemeFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label="方案名称"
            rules={[{ required: true, message: '请输入方案名称' }, { min: 2, message: '至少 2 个字符' }]}
          >
            <Input maxLength={128} placeholder="如：开发岗计分方案" />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} maxLength={500} placeholder="方案适用范围与说明" />
          </Form.Item>
          <Form.Item
            name="is_default"
            label="默认兜底方案"
            valuePropName="checked"
            extra="全局唯一：勾选后原默认方案自动取消，未匹配任何方案的人员按本方案计分"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="position_ids"
            label="适用岗位"
            extra="非默认方案不绑定岗位时不生效；同一岗位只能命中一个启用方案"
          >
            <Select
              mode="multiple"
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="从岗位编制中多选"
              options={positions.map((p) => ({ value: p.id, label: p.name }))}
            />
          </Form.Item>

          <Form.Item label="评分维度与权重" required style={{ marginBottom: 0 }}>
            <Form.List
              name="dimensions"
              rules={[
                {
                  validator: async (_, value: unknown[]) => {
                    if (!value || value.length === 0) throw new Error('至少配置一个维度');
                  },
                },
              ]}
            >
              {(fields, { add, remove }, { errors }) => (
                <>
                  {fields.map((field) => (
                    <Space key={field.key} align="baseline" style={{ display: 'flex' }}>
                      <Form.Item
                        name={[field.name, 'code']}
                        rules={[{ required: true, message: '请选择维度' }]}
                        style={{ width: 300 }}
                      >
                        <Select
                          placeholder="评分维度"
                          popupMatchSelectWidth={420}
                          options={dims.map((d) => ({
                            value: d.code,
                            label: d.name,
                            // 已被其他行选中的维度置灰（同一维度只能配置一次）
                            disabled:
                              chosenCodes.includes(d.code) && chosenCodes[field.name] !== d.code,
                          }))}
                          optionRender={(opt) => {
                            const d = dims.find((x) => x.code === opt.value);
                            return (
                              <div>
                                <div>{opt.label}</div>
                                {d && (
                                  <div
                                    style={{
                                      fontSize: 12,
                                      color: 'rgba(0, 0, 0, 0.45)',
                                      whiteSpace: 'normal',
                                    }}
                                  >
                                    {d.description}
                                  </div>
                                )}
                              </div>
                            );
                          }}
                        />
                      </Form.Item>
                      <Form.Item
                        name={[field.name, 'weight']}
                        rules={[{ required: true, message: '请输入权重' }]}
                      >
                        <InputNumber min={0.1} max={1000} placeholder="权重" style={{ width: 110 }} />
                      </Form.Item>
                      <MinusCircleOutlined onClick={() => remove(field.name)} />
                    </Space>
                  ))}
                  <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add({})}>
                    添加维度
                  </Button>
                  <Form.ErrorList errors={errors} />
                </>
              )}
            </Form.List>
          </Form.Item>
          <Typography.Text
            style={weightTotal === 100 ? undefined : { color: '#fa8c16' }}
          >{`权重合计：${Math.round(weightTotal * 10) / 10}（建议 100，非强制；计分时按占比归一）`}</Typography.Text>
        </Form>
      </Drawer>
    </Card>
  );
}

// ============ 页面（PermTabs 复合页） ============

/** 人效评分（M6.1）：总览（按方案加权计分） | 计分规则（方案 CRUD） */
export default function Performance() {
  return (
    <PermTabs
      tabs={[
        { key: 'overview', label: '总览', modules: ['performance'], children: <PerfOverview /> },
        { key: 'schemes', label: '计分规则', modules: ['performance'], children: <PerfSchemes /> },
      ]}
    />
  );
}
