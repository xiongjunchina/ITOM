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
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
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
import { useT } from '../../i18n';
import PermTabs from '../../components/PermTabs';
import { hasPermission, useAuthStore } from '../../stores/auth';
import { currentPeriod, periodLabel, recentPeriods } from '../../utils/period';
import type {
  PerfDimension,
  PerfScheme,
  PerformanceData,
  PerformanceRow,
  Position,
} from '../../api/types';
import { ExternalInputWorkbench, MyPerformanceResult, ReviewWorkbench } from './BplusPerformance';
import PerformanceRulesWorkbench from './PerformanceRulesWorkbench';

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
  const t = useT();
  const [period, setPeriod] = useState(currentPeriod());
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [tablePage, setTablePage] = useState(1);
  const [tablePageSize, setTablePageSize] = useState(20);

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
      message.success(score == null ? t('team.performance.overrideCleared') : t('team.performance.overrideSaved'));
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
      message.success(t('team.performance.adjAdded'));
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
      message.success(t('team.performance.adjRemoved'));
      void load();
    } catch {
      // 已统一提示
    }
  };

  if (forbidden) {
    return (
      <Card>
        <Result status="403" title={t('team.performance.noPermTitle')} subTitle={t('team.performance.noPermDesc')} />
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
        placeholder={t('team.performance.editorPlaceholder')}
      />
      <Space>
        <Button
          type="primary"
          size="small"
          loading={editorSaving}
          onClick={() => {
            if (editorValue == null) {
              message.warning(t('team.performance.editorWarn'));
              return;
            }
            void saveOverride(editorValue);
          }}
        >
          {t('team.performance.saveOverride')}
        </Button>
        <Button
          size="small"
          disabled={editor?.override == null}
          loading={editorSaving && editor?.override != null}
          onClick={() => void saveOverride(null)}
        >
          {t('team.performance.clearOverride')}
        </Button>
      </Space>
    </Space>
  );

  const columns: ColumnsType<PerformanceRow> = [
    { title: t('team.col.name'), dataIndex: 'person_name', width: 100, fixed: 'left' },
    { title: t('team.performance.col.position'), dataIndex: 'position_name', width: 130, render: (v: string | null) => v || '-' },
    {
      title: t('team.performance.col.scheme'),
      dataIndex: 'scheme_name',
      width: 150,
      render: (v: string | null) => (v ? v : <Tag>{t('team.performance.noScheme')}</Tag>),
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
                ? t('team.performance.cellOverridden', { score: cell.score ?? t('team.performance.noValue') })
                : t('team.performance.weight', { weight: cell.weight }) +
                  (canEdit ? t('team.performance.clickToOverride') : '')
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
            title={t('team.performance.editorTitle', { name: r.person_name, dim: d.name })}
            content={editorContent}
          >
            {inner}
          </Popover>
        );
      },
    })),
    {
      title: t('team.performance.col.bonus'),
      dataIndex: 'bonus',
      width: 80,
      render: (v: number) =>
        v > 0 ? <span style={{ color: '#52c41a', fontWeight: 600 }}>+{v}</span> : <span style={{ color: GRAY }}>-</span>,
    },
    {
      title: t('team.performance.col.penalty'),
      dataIndex: 'penalty',
      width: 80,
      render: (v: number) =>
        v > 0 ? <span style={{ color: '#ff4d4f', fontWeight: 600 }}>−{v}</span> : <span style={{ color: GRAY }}>-</span>,
    },
    {
      title: t('team.performance.col.adjReasons'),
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
      title: t('team.performance.col.total'),
      dataIndex: 'total',
      width: 90,
      sorter: (a, b) => (a.total ?? -1) - (b.total ?? -1),
      defaultSortOrder: 'descend',
      render: (v: number | null, r) => (
        <Tooltip title={t('team.performance.totalTip', { base: r.base_score ?? '—', bonus: r.bonus ?? 0, penalty: r.penalty ?? 0 })}>
          {v == null ? EMPTY_CELL : <Typography.Text strong>{v}</Typography.Text>}
        </Tooltip>
      ),
    },
    ...(canEdit
      ? [
          {
            title: t('common.actions'),
            key: 'action',
            width: 90,
            fixed: 'right',
            render: (_: unknown, r: PerformanceRow) => (
              <Button type="link" size="small" onClick={() => setAdjPersonId(r.person_id)}>
                {t('team.performance.adjust')}
              </Button>
            ),
          } as ColumnsType<PerformanceRow>[number],
        ]
      : []),
  ];

  return (
    <Card
      title={t('team.performance.overviewTitle')}
      extra={
        <Select
          value={period}
          style={{ width: 130 }}
          onChange={(p) => {
            setPeriod(p);
            setEditor(null);
          }}
          options={recentPeriods(2).map((p) => ({ value: p, label: periodLabel(p) }))}
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
            label: t('team.performance.dimSpec'),
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
        standardToolbar={{ exportFileName: '人效评分结果', searchPlaceholder: '搜索员工、角色或评分状态' }}
        sticky
        scroll={{ x: 810 + dimensions.length * 110 + (canEdit ? 90 : 0) }}
        pagination={{
          current: tablePage,
          pageSize: tablePageSize,
          showSizeChanger: true,
          pageSizeOptions: [10, 20, 50, 100],
          showTotal: (n) => t('team.totalPeople', { n }),
          onChange: (page, pageSize) => {
            setTablePage(page);
            setTablePageSize(pageSize);
          },
        }}
      />

      <Drawer
        title={t('team.performance.adjDrawerTitle', { name: adjRow?.person_name ?? '', period })}
        width={440}
        open={adjPersonId != null}
        onClose={() => setAdjPersonId(null)}
        destroyOnClose
      >
        <List
          size="small"
          header={
            <Typography.Text type="secondary">
              {t('team.performance.periodItems', { n: adjRow?.adjustments.length ?? 0 })}
            </Typography.Text>
          }
          dataSource={adjRow?.adjustments ?? []}
          locale={{ emptyText: t('team.performance.adjEmpty') }}
          renderItem={(a) => (
            <List.Item
              actions={[
                <Popconfirm
                  key="del"
                  title={t('team.performance.delAdjConfirm')}
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
                      {a.kind === 'bonus' ? t('team.performance.bonus') : t('team.performance.penalty')}
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
        <Divider style={{ margin: '16px 0 12px' }}>{t('team.performance.addItem')}</Divider>
        <Form<AdjFormValues> form={adjForm} layout="vertical" preserve={false} initialValues={{ kind: 'bonus' }}>
          <Form.Item name="kind" label={t('team.performance.typeLabel')} rules={[{ required: true, message: t('team.performance.typeRequired') }]}>
            <Radio.Group
              optionType="button"
              buttonStyle="solid"
              options={[
                { value: 'bonus', label: t('team.performance.bonus') },
                { value: 'penalty', label: t('team.performance.penalty') },
              ]}
            />
          </Form.Item>
          <Form.Item name="points" label={t('team.performance.pointsLabel')} rules={[{ required: true, message: t('team.performance.pointsRequired') }]}>
            <InputNumber min={0.1} max={1000} style={{ width: '100%' }} placeholder={t('team.performance.pointsPlaceholder')} />
          </Form.Item>
          <Form.Item
            name="reason"
            label={t('team.performance.reasonLabel')}
            rules={[
              { required: true, message: t('team.performance.reasonRequired') },
              { min: 2, message: t('team.minChars', { n: 2 }) },
            ]}
          >
            <Input.TextArea
              rows={3}
              maxLength={200}
              showCount
              placeholder={t('team.performance.reasonPlaceholder')}
            />
          </Form.Item>
          <Button
            type="primary"
            block
            icon={<PlusOutlined />}
            loading={adjSaving}
            onClick={() => void submitAdjustment()}
          >
            {t('team.add')}
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

/** 旧版岗位计分方案保留作数据兼容，不再挂载到“计分规则”页面；页面使用角色规则工作台。 */
export function PerfSchemes() {
  const t = useT();
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
        message.success(t('team.performance.schemeUpdated'));
      } else {
        await api.post('/perf/schemes', payload);
        message.success(t('team.performance.schemeCreated'));
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
      message.success(active ? t('team.performance.schemeEnabled') : t('team.performance.schemeDisabled'));
      void load();
    } catch {
      // 已统一提示
    }
  };

  const handleDelete = async (s: PerfScheme) => {
    try {
      await api.delete(`/perf/schemes/${s.id}`);
      message.success(t('team.performance.schemeDeleted'));
      void load();
    } catch {
      // 已统一提示
    }
  };

  const columns: ColumnsType<PerfScheme> = [
    {
      title: t('team.performance.col.schemeName'),
      dataIndex: 'name',
      width: 200,
      render: (v: string, r) => (
        <Space size={4}>
          <span>{v}</span>
          {r.is_default && <Tag color="blue">{t('team.performance.defaultScheme')}</Tag>}
        </Space>
      ),
    },
    {
      title: t('team.performance.col.positions'),
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
          <Typography.Text type="secondary">{t('team.performance.defaultFallback')}</Typography.Text>
        ) : (
          <span style={{ color: GRAY }}>{t('team.performance.noPosition')}</span>
        );
      },
    },
    { title: t('team.performance.col.dimCount'), width: 80, render: (_, r) => r.dimensions.length },
    {
      title: t('team.performance.col.weightTotal'),
      dataIndex: 'weight_total',
      width: 100,
      render: (v: number) =>
        v === 100 ? (
          v
        ) : (
          <Tooltip title={t('team.performance.weightTip')}>
            <span style={{ color: '#fa8c16' }}>{v}</span>
          </Tooltip>
        ),
    },
    {
      title: t('team.enableCol'),
      dataIndex: 'active',
      width: 80,
      render: (v: boolean, r) => <Switch checked={v} onChange={(next) => void toggleActive(r, next)} />,
    },
    {
      title: t('common.actions'),
      key: 'action',
      width: 140,
      render: (_, r) => (
        <Space size={0}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>
            {t('common.edit')}
          </Button>
          <Popconfirm title={t('team.performance.delSchemeConfirm')} onConfirm={() => void handleDelete(r)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              {t('common.delete')}
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
      title={t('team.performance.schemesTitle')}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            {t('common.refresh')}
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            {t('team.performance.createScheme')}
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('team.performance.schemeAlert')}
      />
      <Table<PerfScheme>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        standardToolbar={{ exportFileName: '计分方案', searchPlaceholder: '搜索方案名称、适用岗位或说明' }}
        sticky
        scroll={{ x: 900 }}
        pagination={false}
      />

      <Drawer
        title={drawer.editing ? t('team.performance.editScheme') : t('team.performance.createScheme')}
        open={drawer.open}
        width={560}
        onClose={() => setDrawer({ open: false, editing: null })}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => setDrawer({ open: false, editing: null })}>{t('common.cancel')}</Button>
            <Button type="primary" loading={saving} onClick={() => void handleSave()}>
              {t('common.save')}
            </Button>
          </Space>
        }
      >
        <Form<SchemeFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t('team.performance.schemeNameLabel')}
            rules={[{ required: true, message: t('team.performance.schemeNameRequired') }, { min: 2, message: t('team.minChars', { n: 2 }) }]}
          >
            <Input maxLength={128} placeholder={t('team.performance.schemeNamePlaceholder')} />
          </Form.Item>
          <Form.Item name="description" label={t('team.performance.descLabel')}>
            <Input.TextArea rows={2} maxLength={500} placeholder={t('team.performance.descPlaceholder')} />
          </Form.Item>
          <Form.Item
            name="is_default"
            label={t('team.performance.defaultSchemeLabel')}
            valuePropName="checked"
            extra={t('team.performance.defaultSchemeExtra')}
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="position_ids"
            label={t('team.performance.col.positions')}
            extra={t('team.performance.positionExtra')}
          >
            <Select
              mode="multiple"
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={t('team.performance.positionPlaceholder')}
              options={positions.map((p) => ({ value: p.id, label: p.name }))}
            />
          </Form.Item>

          <Form.Item label={t('team.performance.dimWeight')} required style={{ marginBottom: 0 }}>
            <Form.List
              name="dimensions"
              rules={[
                {
                  validator: async (_, value: unknown[]) => {
                    if (!value || value.length === 0) throw new Error(t('team.performance.dimMin'));
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
                        rules={[{ required: true, message: t('team.performance.dimRequired') }]}
                        style={{ width: 300 }}
                      >
                        <Select
                          placeholder={t('team.performance.dimPlaceholder')}
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
                        rules={[{ required: true, message: t('team.performance.weightRequired') }]}
                      >
                        <InputNumber min={0.1} max={1000} placeholder={t('team.performance.weightPlaceholder')} style={{ width: 110 }} />
                      </Form.Item>
                      <MinusCircleOutlined onClick={() => remove(field.name)} />
                    </Space>
                  ))}
                  <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add({})}>
                    {t('team.performance.addDim')}
                  </Button>
                  <Form.ErrorList errors={errors} />
                </>
              )}
            </Form.List>
          </Form.Item>
          <Typography.Text
            style={weightTotal === 100 ? undefined : { color: '#fa8c16' }}
          >{t('team.performance.weightSum', { n: Math.round(weightTotal * 10) / 10 })}</Typography.Text>
        </Form>
      </Drawer>
    </Card>
  );
}

// ============ 页面（PermTabs 复合页） ============

/** 人效评分（M6.1）：总览（按方案加权计分） | 计分规则（方案 CRUD） */
export default function Performance() {
  const t = useT();
  return (
    <PermTabs
      tabs={[
        { key: 'overview', label: t('team.performance.tabOverview'), modules: ['performance'], children: <PerfOverview /> },
        { key: 'schemes', label: t('team.performance.schemesTitle'), modules: ['performance_admin'], children: <PerformanceRulesWorkbench /> },
        { key: 'bplus-review', label: '分级评审', modules: ['performance_review'], children: <ReviewWorkbench /> },
        { key: 'external-input', label: '外部原数据', modules: ['performance_external'], children: <ExternalInputWorkbench /> },
        { key: 'my-result', label: '我的最终结果', modules: ['performance_result'], children: <MyPerformanceResult /> },
      ]}
    />
  );
}
