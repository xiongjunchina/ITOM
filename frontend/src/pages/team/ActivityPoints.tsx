import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  LikeFilled,
  LikeOutlined,
  MinusCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import PermTabs from '../../components/PermTabs';
import { ExampleAlert, ExampleTag } from '../../components/ExampleTag';
import { hasPermission, useAuthStore } from '../../stores/auth';
import { currentPeriod, periodLabel } from '../../utils/period';
import type {
  CampaignDetail,
  CampaignRow,
  CampaignStatus,
  CampaignTaskRow,
  IdeaRow,
  IdeaStatus,
  Member,
  MyPoints,
  PointRule,
  PointsLeaderboard,
} from '../../api/types';
import { CAMPAIGN_STATUS_COLORS, IDEA_STATUS_COLORS, POINT_SOURCE_LABELS } from '../../api/types';

/** 写权限：优先权限矩阵；存量会话缺失 permissions 时放行（后端仍会校验并中文提示） */
function useIdeasPerm(action: 'create' | 'edit'): boolean {
  const user = useAuthStore((s) => s.user);
  return user?.permissions ? hasPermission(user, 'ideas', action) : true;
}

const fmtDay = (v?: string | null) => (v ? dayjs(v).format('YYYY-MM-DD') : '-');
const fmtTime = (v?: string | null) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-');

// ---------------- 我的积分卡片 ----------------

function MyPointsCard() {
  const [data, setData] = useState<MyPoints | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api
      .get<MyPoints>('/points/mine')
      .then(setData)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const entryColumns: ColumnsType<MyPoints['entries'][number]> = [
    { title: '时间', dataIndex: 'created_at', width: 150, render: (v: string) => fmtTime(v) },
    {
      title: '来源',
      dataIndex: 'source_type',
      width: 110,
      render: (v: string) => <Tag>{POINT_SOURCE_LABELS[v] ?? v}</Tag>,
    },
    {
      title: '积分',
      dataIndex: 'points',
      width: 80,
      render: (v: number) => (
        <Typography.Text strong style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f' }}>
          {v >= 0 ? `+${v}` : v}
        </Typography.Text>
      ),
    },
    { title: '考核期', dataIndex: 'period', width: 90 },
    { title: '备注', dataIndex: 'note', ellipsis: true, render: (v) => v || '-' },
  ];

  return (
    <Card loading={loading} style={{ marginBottom: 16 }}>
      <Space size={48} wrap align="center">
        <Statistic
          title={`本期积分（${periodLabel(data?.period ?? currentPeriod())}）`}
          value={data?.period_total ?? 0}
          precision={1}
          prefix={<TrophyOutlined />}
          valueStyle={{ color: '#1677ff' }}
        />
        <Statistic title="累计积分" value={data?.total ?? 0} precision={1} />
        <Button onClick={() => setOpen(true)}>积分明细</Button>
      </Space>
      <Drawer
        title="我的积分明细（最近 100 条）"
        width={640}
        open={open}
        onClose={() => setOpen(false)}
      >
        <Table<MyPoints['entries'][number]>
          rowKey={(r, i) => r.id ?? String(i)}
          size="small"
          columns={entryColumns}
          dataSource={data?.entries ?? []}
          pagination={false}
          locale={{ emptyText: '暂无积分流水' }}
        />
      </Drawer>
    </Card>
  );
}

// ---------------- Tab A：专项活动 ----------------

interface CampaignTaskForm {
  name: string;
  description?: string;
  points: number;
  max_times: number;
}

interface CampaignFormValues {
  name: string;
  description?: string;
  period_label: string;
  start_date: Dayjs;
  end_date: Dayjs;
  performance_ratio: number;
  tasks: CampaignTaskForm[];
}

interface AwardFormValues {
  person_id: string;
  task_id: string;
  times: number;
  note?: string;
}

const taskColumns: ColumnsType<CampaignTaskRow> = [
  { title: '任务名', dataIndex: 'name', width: 180 },
  { title: '说明', dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
  { title: '每次积分', dataIndex: 'points', width: 90 },
  {
    title: '每人上限',
    dataIndex: 'max_times',
    width: 90,
    render: (v: number) => (v === 0 ? '不限' : `${v} 次`),
  },
];

function CampaignsTab() {
  const canManage = useIdeasPerm('edit');

  const [items, setItems] = useState<CampaignRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('all');

  // 详情
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<CampaignDetail | null>(null);

  // 新建/编辑
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<CampaignRow | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<CampaignFormValues>();

  // 发放积分
  const [awardOpen, setAwardOpen] = useState(false);
  const [awarding, setAwarding] = useState(false);
  const [awardForm] = Form.useForm<AwardFormValues>();
  const [members, setMembers] = useState<Member[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<CampaignRow>('/campaigns');
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

  const filtered = useMemo(
    () => (statusFilter === 'all' ? items : items.filter((c) => c.status === statusFilter)),
    [items, statusFilter],
  );

  const loadDetail = useCallback(async (id: string) => {
    setDetailLoading(true);
    try {
      setDetail(await api.get<CampaignDetail>(`/campaigns/${id}`));
    } catch {
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const openDetail = (id: string) => {
    setDetail(null);
    setDetailOpen(true);
    void loadDetail(id);
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      period_label: currentPeriod(),
      performance_ratio: 1,
      tasks: [{ max_times: 1 } as CampaignTaskForm],
    });
    setFormOpen(true);
  };

  const openEdit = (c: CampaignRow) => {
    setEditing(c);
    form.resetFields();
    form.setFieldsValue({
      name: c.name,
      description: c.description ?? undefined,
      period_label: c.period_label,
      start_date: dayjs(c.start_date),
      end_date: dayjs(c.end_date),
      performance_ratio: c.performance_ratio,
      tasks: c.tasks.map((t) => ({
        name: t.name,
        description: t.description ?? undefined,
        points: t.points,
        max_times: t.max_times,
      })),
    });
    setFormOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    const payload = {
      name: values.name,
      description: values.description || null,
      period_label: values.period_label,
      start_date: values.start_date.format('YYYY-MM-DD'),
      end_date: values.end_date.format('YYYY-MM-DD'),
      performance_ratio: values.performance_ratio,
      tasks: values.tasks.map((t) => ({
        name: t.name,
        description: t.description || null,
        points: t.points,
        max_times: t.max_times ?? 1,
      })),
    };
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/campaigns/${editing.id}`, payload);
        message.success('活动已更新');
      } else {
        await api.post('/campaigns', payload);
        message.success('活动已创建（草稿），上架后对全员可见');
      }
      setFormOpen(false);
      void load();
      if (detailOpen && editing) void loadDetail(editing.id);
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const setStatus = async (c: { id: string }, status: CampaignStatus) => {
    try {
      await api.post(`/campaigns/${c.id}/status`, { status });
      message.success(status === 'active' ? '活动已上架' : status === 'offline' ? '活动已下架' : '已转为草稿');
      void load();
      if (detailOpen && detail?.id === c.id) void loadDetail(c.id);
    } catch {
      // 已统一提示
    }
  };

  const openAward = () => {
    awardForm.resetFields();
    awardForm.setFieldsValue({ times: 1 });
    setAwardOpen(true);
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 999 })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
  };

  const handleAward = async () => {
    if (!detail) return;
    const values = await awardForm.validateFields();
    setAwarding(true);
    try {
      const res = await api.post<{ awarded: number }>(`/campaigns/${detail.id}/awards`, {
        person_id: values.person_id,
        task_id: values.task_id,
        times: values.times,
        note: values.note || null,
      });
      message.success(`已发放 ${res.awarded} 分`);
      setAwardOpen(false);
      void loadDetail(detail.id);
      void load();
    } catch {
      // 已统一提示（如超上限）
    } finally {
      setAwarding(false);
    }
  };

  /** 上架/下架按钮（列表卡片与详情复用）；示例活动不显示 */
  const statusActions = (c: { id: string; status: CampaignRow['status'] }) =>
    c.status === 'active' ? (
      <Popconfirm key="offline" title="下架该活动？下架后普通成员不再可见" onConfirm={() => void setStatus(c, 'offline')}>
        <Button type="link" size="small" danger onClick={(e) => e.stopPropagation()}>
          下架
        </Button>
      </Popconfirm>
    ) : (
      <Popconfirm key="active" title="上架该活动？上架后对全员可见" onConfirm={() => void setStatus(c, 'active')}>
        <Button type="link" size="small" onClick={(e) => e.stopPropagation()}>
          上架
        </Button>
      </Popconfirm>
    );

  const awardColumns: ColumnsType<CampaignDetail['awards'][number]> = [
    { title: '人员', dataIndex: 'person_name', width: 100, render: (v) => v || '-' },
    { title: '任务', dataIndex: 'task_name', width: 160, ellipsis: true, render: (v) => v || '-' },
    { title: '积分', dataIndex: 'points', width: 70 },
    { title: '备注', dataIndex: 'note', ellipsis: true, render: (v) => v || '-' },
    { title: '时间', dataIndex: 'created_at', width: 150, render: (v: string) => fmtTime(v) },
  ];

  const boardColumns: ColumnsType<CampaignDetail['leaderboard'][number]> = [
    { title: '名次', key: 'rank', width: 60, render: (_, __, i) => i + 1 },
    { title: '人员', dataIndex: 'person_name', render: (v) => v || '-' },
    { title: '积分', dataIndex: 'points', width: 90 },
    { title: '折算绩效', dataIndex: 'performance', width: 100 },
  ];

  return (
    <>
      <Space wrap style={{ marginBottom: 16 }}>
        {canManage && (
          <Segmented
            value={statusFilter}
            onChange={(v) => setStatusFilter(v as string)}
            options={[
              { value: 'all', label: '全部' },
              { value: 'active', label: '上架中' },
              { value: 'draft', label: '草稿' },
              { value: 'offline', label: '已下架' },
            ]}
          />
        )}
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          刷新
        </Button>
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建活动
          </Button>
        )}
      </Space>

      <Spin spinning={loading}>
        {filtered.length === 0 && !loading ? (
          <Empty description="暂无专项活动" />
        ) : (
          <List
            grid={{ gutter: 16, xs: 1, sm: 2, xl: 3 }}
            dataSource={filtered}
            renderItem={(c) => (
              <List.Item>
                <Card
                  hoverable
                  onClick={() => openDetail(c.id)}
                  title={
                    <Space size={4}>
                      <Typography.Text strong ellipsis style={{ maxWidth: 200 }}>
                        {c.name}
                      </Typography.Text>
                      {c.is_example && <ExampleTag />}
                    </Space>
                  }
                  extra={<Tag color={CAMPAIGN_STATUS_COLORS[c.status as CampaignStatus] ?? 'default'}>{c.status_name}</Tag>}
                  actions={
                    canManage && !c.is_example
                      ? [
                          <Button
                            key="edit"
                            type="link"
                            size="small"
                            onClick={(e) => {
                              e.stopPropagation();
                              openEdit(c);
                            }}
                          >
                            编辑
                          </Button>,
                          <span key="status" onClick={(e) => e.stopPropagation()}>
                            {statusActions(c)}
                          </span>,
                        ]
                      : undefined
                  }
                >
                  <Typography.Paragraph
                    type="secondary"
                    ellipsis={{ rows: 2 }}
                    style={{ whiteSpace: 'pre-wrap', minHeight: 44 }}
                  >
                    {c.description || '（暂无活动说明）'}
                  </Typography.Paragraph>
                  <Space direction="vertical" size={4} style={{ display: 'flex' }}>
                    <Typography.Text type="secondary">
                      考核期 {c.period_label} · {fmtDay(c.start_date)} ~ {fmtDay(c.end_date)}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      绩效折算：积分 × {c.performance_ratio} · 激励任务 {c.tasks.length} 项
                    </Typography.Text>
                    <Typography.Text>
                      我的积分 <Typography.Text strong style={{ color: '#1677ff' }}>{c.my_points ?? 0}</Typography.Text>
                      {' · '}折算绩效 <Typography.Text strong>{c.my_performance ?? 0}</Typography.Text>
                    </Typography.Text>
                  </Space>
                </Card>
              </List.Item>
            )}
          />
        )}
      </Spin>

      {/* 活动详情 */}
      <Drawer
        title={
          detail ? (
            <Space size={4}>
              {detail.name}
              {detail.is_example && <ExampleTag />}
              <Tag color={CAMPAIGN_STATUS_COLORS[detail.status as CampaignStatus] ?? 'default'}>
                {detail.status_name}
              </Tag>
            </Space>
          ) : (
            '活动详情'
          )
        }
        width={720}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        extra={
          detail?.can_manage && (
            <Space>
              {detail.status === 'active' && (
                <Button type="primary" onClick={openAward}>
                  发放积分
                </Button>
              )}
              <Button onClick={() => openEdit(detail)}>编辑</Button>
              {statusActions(detail)}
            </Space>
          )
        }
      >
        <Spin spinning={detailLoading}>
          {detail && (
            <Space direction="vertical" size={16} style={{ display: 'flex' }}>
              {detail.is_example && <ExampleAlert />}
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="考核期">{detail.period_label}</Descriptions.Item>
                <Descriptions.Item label="起止日期">
                  {fmtDay(detail.start_date)} ~ {fmtDay(detail.end_date)}
                </Descriptions.Item>
                <Descriptions.Item label="绩效折算">积分 × {detail.performance_ratio}</Descriptions.Item>
                <Descriptions.Item label="已发放合计">{detail.total_awarded} 分</Descriptions.Item>
                <Descriptions.Item label="我的积分">{detail.my_points ?? 0}</Descriptions.Item>
                <Descriptions.Item label="我的折算绩效">{detail.my_performance ?? 0}</Descriptions.Item>
              </Descriptions>
              {detail.description && (
                <Alert
                  type="info"
                  message="活动说明"
                  description={
                    <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                      {detail.description}
                    </Typography.Paragraph>
                  }
                />
              )}

              <div>
                <Typography.Title level={5}>激励任务</Typography.Title>
                <Table<CampaignTaskRow>
                  rowKey="id"
                  size="small"
                  columns={taskColumns}
                  dataSource={detail.tasks}
                  pagination={false}
                />
              </div>

              <div>
                <Typography.Title level={5}>活动排行榜（折算后绩效分）</Typography.Title>
                <Table
                  rowKey={(r, i) => `${i}-${r.person_name ?? ''}`}
                  size="small"
                  columns={boardColumns}
                  dataSource={detail.leaderboard}
                  pagination={false}
                  locale={{ emptyText: '暂无积分发放' }}
                />
              </div>

              <div>
                <Typography.Title level={5}>发放记录（最近 100 条）</Typography.Title>
                <Table
                  rowKey={(r, i) => r.id ?? String(i)}
                  size="small"
                  columns={awardColumns}
                  dataSource={detail.awards}
                  pagination={false}
                  locale={{ emptyText: '暂无发放记录' }}
                />
              </div>
            </Space>
          )}
        </Spin>
      </Drawer>

      {/* 新建/编辑活动 */}
      <Drawer
        title={editing ? `编辑活动：${editing.name}` : '新建活动'}
        width={640}
        open={formOpen}
        onClose={() => setFormOpen(false)}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => setFormOpen(false)}>取消</Button>
            <Button type="primary" loading={saving} onClick={() => void handleSave()}>
              保存
            </Button>
          </Space>
        }
      >
        {editing && editing.total_awarded > 0 && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="该活动已有积分发放记录：激励任务只增不删，已有任务的改动不会生效（保护积分台账引用）。"
          />
        )}
        <Form<CampaignFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label="活动名称" rules={[{ required: true, message: '请输入活动名称' }, { min: 2, message: '至少 2 个字符' }]}>
            <Input maxLength={200} placeholder="如：2026 下半年知识分享季" />
          </Form.Item>
          <Form.Item name="description" label="活动说明">
            <Input.TextArea rows={3} maxLength={2000} placeholder="活动背景、参与方式与激励说明" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="period_label" label="考核期" rules={[{ required: true, message: '请选择考核期' }]}>
                <Select
                  options={[0, 1]
                    .flatMap((offset) => {
                      const y = new Date().getFullYear() + offset;
                      return [`${y}-Q1`, `${y}-Q2`, `${y}-Q3`, `${y}-All`];
                    })
                    .map((p) => ({ value: p, label: periodLabel(p) }))}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="start_date" label="开始日期" rules={[{ required: true, message: '请选择开始日期' }]}>
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="end_date"
                label="结束日期"
                dependencies={['start_date']}
                rules={[
                  { required: true, message: '请选择结束日期' },
                  ({ getFieldValue }) => ({
                    validator(_, v: Dayjs | undefined) {
                      const s: Dayjs | undefined = getFieldValue('start_date');
                      if (!v || !s || !v.isBefore(s, 'day')) return Promise.resolve();
                      return Promise.reject(new Error('结束日期不能早于开始日期'));
                    },
                  }),
                ]}
              >
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="performance_ratio"
            label="绩效折算系数（绩效分 = 积分 × 系数）"
            rules={[{ required: true, message: '请输入折算系数' }]}
          >
            <InputNumber min={0.01} step={0.05} style={{ width: 200 }} />
          </Form.Item>

          <Typography.Title level={5}>激励任务</Typography.Title>
          <Form.List
            name="tasks"
            rules={[
              {
                validator: async (_, tasks?: CampaignTaskForm[]) => {
                  if (!tasks || tasks.length < 1) throw new Error('至少添加 1 条激励任务');
                },
              },
            ]}
          >
            {(fields, { add, remove }, { errors }) => (
              <>
                {fields.map((field, index) => (
                  <Row
                    gutter={8}
                    key={field.key}
                    align="top"
                    wrap={false}
                    style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: '8px 8px 0', marginBottom: 8 }}
                  >
                    <Col flex="24px" style={{ paddingTop: 5 }}>
                      <Typography.Text type="secondary">{index + 1}</Typography.Text>
                    </Col>
                    <Col flex="auto">
                      <Row gutter={8}>
                        <Col span={9}>
                          <Form.Item
                            name={[field.name, 'name']}
                            rules={[{ required: true, message: '任务名必填' }]}
                            style={{ marginBottom: 8 }}
                          >
                            <Input placeholder="任务名" maxLength={200} />
                          </Form.Item>
                        </Col>
                        <Col span={7}>
                          <Form.Item
                            name={[field.name, 'points']}
                            rules={[{ required: true, message: '积分必填' }]}
                            style={{ marginBottom: 8 }}
                          >
                            <InputNumber min={0.5} step={0.5} placeholder="每次积分" style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                        <Col span={8}>
                          <Form.Item name={[field.name, 'max_times']} style={{ marginBottom: 8 }}>
                            <InputNumber min={0} placeholder="每人上限（0=不限）" style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                      </Row>
                      <Form.Item name={[field.name, 'description']} style={{ marginBottom: 8 }}>
                        <Input placeholder="任务说明（可选）" maxLength={500} />
                      </Form.Item>
                    </Col>
                    <Col flex="24px" style={{ paddingTop: 5 }}>
                      {fields.length > 1 && (
                        <MinusCircleOutlined
                          style={{ color: '#999' }}
                          onClick={() => remove(field.name)}
                        />
                      )}
                    </Col>
                  </Row>
                ))}
                <Button
                  type="dashed"
                  block
                  icon={<PlusOutlined />}
                  onClick={() => add({ max_times: 1 })}
                >
                  添加激励任务
                </Button>
                <Form.ErrorList errors={errors} />
              </>
            )}
          </Form.List>
        </Form>
      </Drawer>

      {/* 发放积分 */}
      <Modal
        title={detail ? `发放积分：${detail.name}` : '发放积分'}
        open={awardOpen}
        onOk={() => void handleAward()}
        confirmLoading={awarding}
        onCancel={() => setAwardOpen(false)}
        destroyOnClose
      >
        <Form<AwardFormValues> form={awardForm} layout="vertical" preserve={false}>
          <Form.Item name="person_id" label="人员" rules={[{ required: true, message: '请选择人员' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择获得积分的人员"
              options={members.map((m) => ({
                value: m.id,
                label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
              }))}
            />
          </Form.Item>
          <Form.Item name="task_id" label="激励任务" rules={[{ required: true, message: '请选择任务' }]}>
            <Select
              placeholder="选择完成的任务"
              options={(detail?.tasks ?? []).map((t) => ({
                value: t.id,
                label: `${t.name}（${t.points} 分/次${t.max_times ? `，上限 ${t.max_times} 次` : ''}）`,
              }))}
            />
          </Form.Item>
          <Form.Item name="times" label="次数" rules={[{ required: true, message: '请输入次数' }]}>
            <InputNumber min={1} max={10} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input maxLength={200} placeholder="如：7 月技术分享《xxx》" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ---------------- Tab B：建言献策 ----------------

interface IdeaFormValues {
  title: string;
  content: string;
}

function IdeasTab() {
  const canCreate = useIdeasPerm('create');
  const canManage = useIdeasPerm('edit');

  const [items, setItems] = useState<IdeaRow[]>([]);
  const [loading, setLoading] = useState(false);

  // 提交建言
  const [createOpen, setCreateOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<IdeaFormValues>();

  // 婉拒
  const [declineTarget, setDeclineTarget] = useState<IdeaRow | null>(null);
  const [declining, setDeclining] = useState(false);
  const [declineForm] = Form.useForm<{ reason: string }>();

  // 积分规则
  const [rules, setRules] = useState<PointRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(false);

  // 排行榜
  const [boardOpen, setBoardOpen] = useState(false);
  const [board, setBoard] = useState<PointsLeaderboard | null>(null);
  const [boardLoading, setBoardLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<IdeaRow>('/ideas', { page: 1, page_size: 200 });
      setItems(res.items);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRules = useCallback(async () => {
    setRulesLoading(true);
    try {
      const res = await api.getList<PointRule>('/point-rules');
      setRules(res.items);
    } catch {
      // 已统一提示
    } finally {
      setRulesLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    void loadRules();
  }, [load, loadRules]);

  const handleCreate = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      await api.post('/ideas', values);
      message.success('建言已提交，自动获得建言积分');
      setCreateOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const handleLike = async (r: IdeaRow) => {
    try {
      await api.post(`/ideas/${r.id}/like`);
      void load();
    } catch {
      // 已统一提示（SELF_LIKE / EXAMPLE_READONLY 等）
    }
  };

  const setIdeaStatus = async (r: IdeaRow, status: IdeaStatus, reason?: string) => {
    await api.patch(`/ideas/${r.id}/status`, { status, reason });
    message.success('状态已更新');
    void load();
  };

  const handleDecline = async () => {
    if (!declineTarget) return;
    const values = await declineForm.validateFields();
    setDeclining(true);
    try {
      await setIdeaStatus(declineTarget, 'declined', values.reason);
      setDeclineTarget(null);
    } catch {
      // 已统一提示
    } finally {
      setDeclining(false);
    }
  };

  const openBoard = () => {
    setBoardOpen(true);
    setBoardLoading(true);
    api
      .get<PointsLeaderboard>('/points/leaderboard')
      .then(setBoard)
      .catch(() => undefined)
      .finally(() => setBoardLoading(false));
  };

  const saveRule = async (code: string, points: number, active: boolean) => {
    try {
      await api.patch(`/point-rules/${code}`, { points, active });
      message.success('积分规则已更新');
      void loadRules();
    } catch {
      // 已统一提示
    }
  };

  const columns: ColumnsType<IdeaRow> = [
    {
      title: '标题',
      dataIndex: 'title',
      ellipsis: true,
      render: (v: string, r) => (
        <Space size={4}>
          <Typography.Text>{v}</Typography.Text>
          {r.is_example && <ExampleTag />}
        </Space>
      ),
    },
    { title: '提出人', dataIndex: 'proposer_name', width: 100, render: (v) => v || '-' },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 110,
      render: (v: string) => fmtDay(v),
    },
    {
      title: '状态',
      dataIndex: 'status_name',
      width: 90,
      render: (v: string, r) => (
        <Tag color={IDEA_STATUS_COLORS[r.status as IdeaStatus] ?? 'default'}>{v || r.status}</Tag>
      ),
    },
    {
      title: '点赞',
      key: 'like',
      width: 80,
      render: (_, r) =>
        r.liked ? (
          <Space size={4} style={{ color: '#1677ff' }}>
            <LikeFilled />
            {r.like_count}
          </Space>
        ) : (
          <Button type="text" size="small" icon={<LikeOutlined />} onClick={() => void handleLike(r)}>
            {r.like_count}
          </Button>
        ),
    },
    ...(canManage
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 150,
            render: (_: unknown, r: IdeaRow) => {
              if (r.is_example) return null;
              return (
                <Space size={0}>
                  {r.status === 'submitted' && (
                    <>
                      <Popconfirm title="采纳该建言？提出人将获得采纳积分" onConfirm={() => void setIdeaStatus(r, 'adopted').catch(() => undefined)}>
                        <Button type="link" size="small">
                          采纳
                        </Button>
                      </Popconfirm>
                      <Button
                        type="link"
                        size="small"
                        onClick={() => {
                          declineForm.resetFields();
                          setDeclineTarget(r);
                        }}
                      >
                        婉拒
                      </Button>
                    </>
                  )}
                  {r.status === 'adopted' && (
                    <Popconfirm title="标记为已实现？" onConfirm={() => void setIdeaStatus(r, 'implemented').catch(() => undefined)}>
                      <Button type="link" size="small">
                        已实现
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              );
            },
          } as ColumnsType<IdeaRow>[number],
        ]
      : []),
  ];

  const ruleColumns: ColumnsType<PointRule> = [
    { title: '规则', dataIndex: 'name', ellipsis: true },
    {
      title: '分值',
      dataIndex: 'points',
      width: 100,
      render: (v: number, r) =>
        canManage ? (
          <InputNumber
            key={`${r.code}-${v}`}
            size="small"
            min={0}
            step={0.5}
            defaultValue={v}
            style={{ width: 80 }}
            onBlur={(e) => {
              const raw = e.target.value.trim();
              if (raw === '') return;
              const next = Number(raw);
              if (!Number.isNaN(next) && next !== r.points) void saveRule(r.code, next, r.active);
            }}
          />
        ) : (
          v
        ),
    },
    {
      title: '启用',
      dataIndex: 'active',
      width: 70,
      render: (v: boolean, r) =>
        canManage ? (
          <Switch size="small" checked={v} onChange={(checked) => void saveRule(r.code, r.points, checked)} />
        ) : (
          <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag>
        ),
    },
  ];

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={16}>
        <Card
          title="建言献策"
          extra={
            <Space>
              <Button icon={<TrophyOutlined />} onClick={openBoard}>
                排行榜
              </Button>
              {canCreate && (
                <Button type="primary" icon={<PlusOutlined />} onClick={() => {
                  form.resetFields();
                  setCreateOpen(true);
                }}>
                  提交建言
                </Button>
              )}
            </Space>
          }
        >
          <Table<IdeaRow>
            rowKey="id"
            size="middle"
            loading={loading}
            columns={columns}
            dataSource={items}
            pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 条` }}
            expandable={{
              expandedRowRender: (r) => (
                <Space direction="vertical" size={8} style={{ display: 'flex' }}>
                  <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                    {r.content}
                  </Typography.Paragraph>
                  {r.status === 'declined' && r.decline_reason && (
                    <Typography.Text type="secondary">婉拒原因：{r.decline_reason}</Typography.Text>
                  )}
                  {r.adopted_at && (
                    <Typography.Text type="secondary">采纳时间：{fmtTime(r.adopted_at)}</Typography.Text>
                  )}
                </Space>
              ),
            }}
          />
        </Card>
      </Col>
      <Col xs={24} lg={8}>
        <Card
          title="积分规则（自动计分）"
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {canManage ? '分值失焦保存' : ''}
            </Typography.Text>
          }
        >
          <Table<PointRule>
            rowKey="code"
            size="small"
            loading={rulesLoading}
            columns={ruleColumns}
            dataSource={rules}
            pagination={false}
          />
        </Card>
      </Col>

      {/* 提交建言 */}
      <Modal
        title="提交建言"
        open={createOpen}
        onOk={() => void handleCreate()}
        confirmLoading={saving}
        onCancel={() => setCreateOpen(false)}
        destroyOnClose
      >
        <Form<IdeaFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, message: '请输入标题' }, { min: 2, message: '至少 2 个字符' }]}
          >
            <Input maxLength={200} placeholder="一句话说清你的建议" />
          </Form.Item>
          <Form.Item name="content" label="内容" rules={[{ required: true, message: '请输入内容' }]}>
            <Input.TextArea rows={5} maxLength={2000} placeholder="现状问题、改进建议与预期收益" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 婉拒原因 */}
      <Modal
        title={declineTarget ? `婉拒建言：${declineTarget.title}` : '婉拒建言'}
        open={!!declineTarget}
        onOk={() => void handleDecline()}
        confirmLoading={declining}
        onCancel={() => setDeclineTarget(null)}
        destroyOnClose
      >
        <Form form={declineForm} layout="vertical" preserve={false}>
          <Form.Item name="reason" label="婉拒原因" rules={[{ required: true, message: '请填写婉拒原因' }]}>
            <Input.TextArea rows={3} maxLength={500} placeholder="向提出人说明暂不采纳的原因" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 本期积分排行榜 */}
      <Drawer
        title={`本期积分榜${board ? `（${board.period}）` : ''}`}
        width={420}
        open={boardOpen}
        onClose={() => setBoardOpen(false)}
      >
        <Spin spinning={boardLoading}>
          <Table
            rowKey={(r, i) => `${i}-${r.person_name ?? ''}`}
            size="small"
            columns={[
              { title: '名次', key: 'rank', width: 70, render: (_, __, i) => i + 1 },
              { title: '人员', dataIndex: 'person_name', render: (v) => v || '-' },
              { title: '积分', dataIndex: 'points', width: 100 },
            ]}
            dataSource={board?.board ?? []}
            pagination={false}
            locale={{ emptyText: '本期暂无积分记录' }}
          />
        </Spin>
      </Drawer>
    </Row>
  );
}

// ---------------- 页面 ----------------

/** 活动积分复合页：专项活动 | 建言献策（顶部我的积分卡片） */
export default function ActivityPoints() {
  return (
    <div>
      <MyPointsCard />
      <PermTabs
        tabs={[
          { key: 'campaigns', label: '专项活动', modules: ['ideas'], children: <CampaignsTab /> },
          { key: 'ideas', label: '建言献策', modules: ['ideas'], children: <IdeasTab /> },
        ]}
      />
    </div>
  );
}
