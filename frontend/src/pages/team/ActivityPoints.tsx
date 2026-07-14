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
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
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
import { CAMPAIGN_STATUS_COLORS, IDEA_STATUS_COLORS } from '../../api/types';

/** 写权限：优先权限矩阵；存量会话缺失 permissions 时放行（后端仍会校验并中文提示） */
function useIdeasPerm(action: 'create' | 'edit'): boolean {
  const user = useAuthStore((s) => s.user);
  return user?.permissions ? hasPermission(user, 'ideas', action) : true;
}

const fmtDay = (v?: string | null) => (v ? dayjs(v).format('YYYY-MM-DD') : '-');
const fmtTime = (v?: string | null) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-');

// ---------------- 我的积分卡片 ----------------

function MyPointsCard() {
  const t = useT();
  const et = useEnums();
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
    { title: t('team.col.time'), dataIndex: 'created_at', width: 150, onCell: () => ({ className: 'cell-nowrap' }), render: (v: string) => fmtTime(v) },
    {
      title: t('team.points.source'),
      dataIndex: 'source_type',
      width: 110,
      render: (v: string) => <Tag>{et.pointSource(v)}</Tag>,
    },
    {
      title: t('team.col.points'),
      dataIndex: 'points',
      width: 80,
      render: (v: number) => (
        <Typography.Text strong style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f' }}>
          {v >= 0 ? `+${v}` : v}
        </Typography.Text>
      ),
    },
    { title: t('team.points.period'), dataIndex: 'period', width: 90 },
    { title: t('common.remark'), dataIndex: 'note', ellipsis: true, render: (v) => v || '-' },
  ];

  return (
    <Card loading={loading} style={{ marginBottom: 16 }}>
      <Space size={48} wrap align="center">
        <Statistic
          title={t('team.points.periodPoints', { period: periodLabel(data?.period ?? currentPeriod()) })}
          value={data?.period_total ?? 0}
          precision={1}
          prefix={<TrophyOutlined />}
          valueStyle={{ color: '#1677ff' }}
        />
        <Statistic title={t('team.points.total')} value={data?.total ?? 0} precision={1} />
        <Button onClick={() => setOpen(true)}>{t('team.points.detail')}</Button>
      </Space>
      <Drawer
        title={t('team.points.myDetail')}
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
          locale={{ emptyText: t('team.points.empty') }}
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

function CampaignsTab() {
  const t = useT();
  const et = useEnums();
  const canManage = useIdeasPerm('edit');

  const taskColumns: ColumnsType<CampaignTaskRow> = [
    { title: t('team.campaign.col.taskName'), dataIndex: 'name', width: 180 },
    { title: t('team.campaign.col.taskDesc'), dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
    { title: t('team.campaign.col.pointsEach'), dataIndex: 'points', width: 90 },
    {
      title: t('team.campaign.col.maxTimes'),
      dataIndex: 'max_times',
      width: 90,
      render: (v: number) => (v === 0 ? t('team.campaign.unlimited') : t('team.campaign.times', { n: v })),
    },
  ];

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
        message.success(t('team.campaign.updated'));
      } else {
        await api.post('/campaigns', payload);
        message.success(t('team.campaign.created'));
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
      message.success(status === 'active' ? t('team.campaign.setActive') : status === 'offline' ? t('team.campaign.setOffline') : t('team.campaign.setDraft'));
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
      message.success(t('team.campaign.awardedMsg', { n: res.awarded }));
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
      <Popconfirm key="offline" title={t('team.campaign.offlineConfirm')} onConfirm={() => void setStatus(c, 'offline')}>
        <Button type="link" size="small" danger onClick={(e) => e.stopPropagation()}>
          {t('team.campaign.offline')}
        </Button>
      </Popconfirm>
    ) : (
      <Popconfirm key="active" title={t('team.campaign.onlineConfirm')} onConfirm={() => void setStatus(c, 'active')}>
        <Button type="link" size="small" onClick={(e) => e.stopPropagation()}>
          {t('team.campaign.online')}
        </Button>
      </Popconfirm>
    );

  const awardColumns: ColumnsType<CampaignDetail['awards'][number]> = [
    { title: t('team.col.person'), dataIndex: 'person_name', width: 100, render: (v) => v || '-' },
    { title: t('team.campaign.col.task'), dataIndex: 'task_name', width: 160, ellipsis: true, render: (v) => v || '-' },
    { title: t('team.col.points'), dataIndex: 'points', width: 70 },
    { title: t('common.remark'), dataIndex: 'note', ellipsis: true, render: (v) => v || '-' },
    { title: t('team.col.time'), dataIndex: 'created_at', width: 150, onCell: () => ({ className: 'cell-nowrap' }), render: (v: string) => fmtTime(v) },
  ];

  const boardColumns: ColumnsType<CampaignDetail['leaderboard'][number]> = [
    { title: t('team.col.rank'), key: 'rank', width: 60, render: (_, __, i) => i + 1 },
    { title: t('team.col.person'), dataIndex: 'person_name', render: (v) => v || '-' },
    { title: t('team.col.points'), dataIndex: 'points', width: 90 },
    { title: t('team.campaign.col.perf'), dataIndex: 'performance', width: 100 },
  ];

  return (
    <>
      <Space wrap style={{ marginBottom: 16 }}>
        {canManage && (
          <Segmented
            value={statusFilter}
            onChange={(v) => setStatusFilter(v as string)}
            options={[
              { value: 'all', label: t('common.all') },
              { value: 'active', label: et.campaignStatus('active') },
              { value: 'draft', label: et.campaignStatus('draft') },
              { value: 'offline', label: et.campaignStatus('offline') },
            ]}
          />
        )}
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          {t('common.refresh')}
        </Button>
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            {t('team.campaign.create')}
          </Button>
        )}
      </Space>

      <Spin spinning={loading}>
        {filtered.length === 0 && !loading ? (
          <Empty description={t('team.campaign.empty')} />
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
                            {t('common.edit')}
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
                    {c.description || t('team.campaign.noDesc')}
                  </Typography.Paragraph>
                  <Space direction="vertical" size={4} style={{ display: 'flex' }}>
                    <Typography.Text type="secondary">
                      {t('team.campaign.periodPrefix')} {c.period_label} · {fmtDay(c.start_date)} ~ {fmtDay(c.end_date)}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      {t('team.campaign.ratioLine', { ratio: c.performance_ratio, n: c.tasks.length })}
                    </Typography.Text>
                    <Typography.Text>
                      {t('team.campaign.myPoints')} <Typography.Text strong style={{ color: '#1677ff' }}>{c.my_points ?? 0}</Typography.Text>
                      {' · '}{t('team.campaign.myPerf')} <Typography.Text strong>{c.my_performance ?? 0}</Typography.Text>
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
            t('team.campaign.detailTitle')
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
                  {t('team.campaign.award')}
                </Button>
              )}
              <Button onClick={() => openEdit(detail)}>{t('common.edit')}</Button>
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
                <Descriptions.Item label={t('team.points.period')}>{detail.period_label}</Descriptions.Item>
                <Descriptions.Item label={t('team.campaign.dateRange')}>
                  {fmtDay(detail.start_date)} ~ {fmtDay(detail.end_date)}
                </Descriptions.Item>
                <Descriptions.Item label={t('team.campaign.ratio')}>{t('team.campaign.ratioValue', { ratio: detail.performance_ratio })}</Descriptions.Item>
                <Descriptions.Item label={t('team.campaign.totalAwarded')}>{t('team.campaign.points', { n: detail.total_awarded })}</Descriptions.Item>
                <Descriptions.Item label={t('team.campaign.myPoints')}>{detail.my_points ?? 0}</Descriptions.Item>
                <Descriptions.Item label={t('team.campaign.myPerfFull')}>{detail.my_performance ?? 0}</Descriptions.Item>
              </Descriptions>
              {detail.description && (
                <Alert
                  type="info"
                  message={t('team.campaign.descTitle')}
                  description={
                    <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                      {detail.description}
                    </Typography.Paragraph>
                  }
                />
              )}

              <div>
                <Typography.Title level={5}>{t('team.campaign.tasks')}</Typography.Title>
                <Table<CampaignTaskRow>
                  rowKey="id"
                  size="small"
                  columns={taskColumns}
                  dataSource={detail.tasks}
                  pagination={false}
                />
              </div>

              <div>
                <Typography.Title level={5}>{t('team.campaign.leaderboard')}</Typography.Title>
                <Table
                  rowKey={(r, i) => `${i}-${r.person_name ?? ''}`}
                  size="small"
                  columns={boardColumns}
                  dataSource={detail.leaderboard}
                  pagination={false}
                  locale={{ emptyText: t('team.campaign.noAward') }}
                />
              </div>

              <div>
                <Typography.Title level={5}>{t('team.campaign.awardRecords')}</Typography.Title>
                <Table
                  rowKey={(r, i) => r.id ?? String(i)}
                  size="small"
                  columns={awardColumns}
                  dataSource={detail.awards}
                  pagination={false}
                  locale={{ emptyText: t('team.campaign.noAwardRecord') }}
                />
              </div>
            </Space>
          )}
        </Spin>
      </Drawer>

      {/* 新建/编辑活动 */}
      <Drawer
        title={editing ? t('team.campaign.editTitle', { name: editing.name }) : t('team.campaign.create')}
        width={640}
        open={formOpen}
        onClose={() => setFormOpen(false)}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => setFormOpen(false)}>{t('common.cancel')}</Button>
            <Button type="primary" loading={saving} onClick={() => void handleSave()}>
              {t('common.save')}
            </Button>
          </Space>
        }
      >
        {editing && editing.total_awarded > 0 && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message={t('team.campaign.editWarn')}
          />
        )}
        <Form<CampaignFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label={t('team.campaign.nameLabel')} rules={[{ required: true, message: t('team.campaign.nameRequired') }, { min: 2, message: t('team.minChars', { n: 2 }) }]}>
            <Input maxLength={200} placeholder={t('team.campaign.namePlaceholder')} />
          </Form.Item>
          <Form.Item name="description" label={t('team.campaign.descTitle')}>
            <Input.TextArea rows={3} maxLength={2000} placeholder={t('team.campaign.descPlaceholder')} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="period_label" label={t('team.points.period')} rules={[{ required: true, message: t('team.campaign.periodRequired') }]}>
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
              <Form.Item name="start_date" label={t('team.campaign.startLabel')} rules={[{ required: true, message: t('team.campaign.startRequired') }]}>
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="end_date"
                label={t('team.campaign.endLabel')}
                dependencies={['start_date']}
                rules={[
                  { required: true, message: t('team.campaign.endRequired') },
                  ({ getFieldValue }) => ({
                    validator(_, v: Dayjs | undefined) {
                      const s: Dayjs | undefined = getFieldValue('start_date');
                      if (!v || !s || !v.isBefore(s, 'day')) return Promise.resolve();
                      return Promise.reject(new Error(t('team.campaign.endBeforeStart')));
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
            label={t('team.campaign.ratioCoef')}
            rules={[{ required: true, message: t('team.campaign.ratioRequired') }]}
          >
            <InputNumber min={0.01} step={0.05} style={{ width: 200 }} />
          </Form.Item>

          <Typography.Title level={5}>{t('team.campaign.tasks')}</Typography.Title>
          <Form.List
            name="tasks"
            rules={[
              {
                validator: async (_, tasks?: CampaignTaskForm[]) => {
                  if (!tasks || tasks.length < 1) throw new Error(t('team.campaign.taskMin'));
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
                            rules={[{ required: true, message: t('team.campaign.taskNameRequired') }]}
                            style={{ marginBottom: 8 }}
                          >
                            <Input placeholder={t('team.campaign.taskNamePlaceholder')} maxLength={200} />
                          </Form.Item>
                        </Col>
                        <Col span={7}>
                          <Form.Item
                            name={[field.name, 'points']}
                            rules={[{ required: true, message: t('team.campaign.taskPointsRequired') }]}
                            style={{ marginBottom: 8 }}
                          >
                            <InputNumber min={0.5} step={0.5} placeholder={t('team.campaign.taskPointsPlaceholder')} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                        <Col span={8}>
                          <Form.Item name={[field.name, 'max_times']} style={{ marginBottom: 8 }}>
                            <InputNumber min={0} placeholder={t('team.campaign.taskMaxPlaceholder')} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                      </Row>
                      <Form.Item name={[field.name, 'description']} style={{ marginBottom: 8 }}>
                        <Input placeholder={t('team.campaign.taskDescPlaceholder')} maxLength={500} />
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
                  {t('team.campaign.addTask')}
                </Button>
                <Form.ErrorList errors={errors} />
              </>
            )}
          </Form.List>
        </Form>
      </Drawer>

      {/* 发放积分 */}
      <Modal
        title={detail ? t('team.campaign.awardTitle', { name: detail.name }) : t('team.campaign.award')}
        open={awardOpen}
        onOk={() => void handleAward()}
        confirmLoading={awarding}
        onCancel={() => setAwardOpen(false)}
        destroyOnClose
      >
        <Form<AwardFormValues> form={awardForm} layout="vertical" preserve={false}>
          <Form.Item name="person_id" label={t('team.col.person')} rules={[{ required: true, message: t('team.campaign.personRequired') }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={t('team.campaign.personPlaceholder')}
              options={members.map((m) => ({
                value: m.id,
                label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
              }))}
            />
          </Form.Item>
          <Form.Item name="task_id" label={t('team.campaign.taskLabel')} rules={[{ required: true, message: t('team.campaign.taskRequired') }]}>
            <Select
              placeholder={t('team.campaign.taskPlaceholder')}
              options={(detail?.tasks ?? []).map((tk) => ({
                value: tk.id,
                label: t('team.campaign.awardTaskOption', {
                  name: tk.name,
                  points: tk.points,
                  limit: tk.max_times ? t('team.campaign.awardLimit', { n: tk.max_times }) : '',
                }),
              }))}
            />
          </Form.Item>
          <Form.Item name="times" label={t('team.campaign.timesLabel')} rules={[{ required: true, message: t('team.campaign.timesRequired') }]}>
            <InputNumber min={1} max={10} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="note" label={t('common.remark')}>
            <Input maxLength={200} placeholder={t('team.campaign.notePlaceholder')} />
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
  const t = useT();
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
      message.success(t('team.idea.submitted'));
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
    message.success(t('team.idea.statusUpdated'));
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
      message.success(t('team.idea.ruleUpdated'));
      void loadRules();
    } catch {
      // 已统一提示
    }
  };

  const columns: ColumnsType<IdeaRow> = [
    {
      title: t('team.col.title'),
      dataIndex: 'title',
      ellipsis: true,
      render: (v: string, r) => (
        <Space size={4}>
          <Typography.Text>{v}</Typography.Text>
          {r.is_example && <ExampleTag />}
        </Space>
      ),
    },
    { title: t('team.idea.proposer'), dataIndex: 'proposer_name', width: 100, render: (v) => v || '-' },
    {
      title: t('team.col.time'),
      dataIndex: 'created_at',
      width: 110,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string) => fmtDay(v),
    },
    {
      title: t('common.status'),
      dataIndex: 'status_name',
      width: 90,
      render: (v: string, r) => (
        <Tag color={IDEA_STATUS_COLORS[r.status as IdeaStatus] ?? 'default'}>{v || r.status}</Tag>
      ),
    },
    {
      title: t('team.idea.likeCol'),
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
            title: t('common.actions'),
            key: 'actions',
            width: 150,
            render: (_: unknown, r: IdeaRow) => {
              if (r.is_example) return null;
              return (
                <Space size={0}>
                  {r.status === 'submitted' && (
                    <>
                      <Popconfirm title={t('team.idea.adoptConfirm')} onConfirm={() => void setIdeaStatus(r, 'adopted').catch(() => undefined)}>
                        <Button type="link" size="small">
                          {t('team.idea.adopt')}
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
                        {t('team.idea.decline')}
                      </Button>
                    </>
                  )}
                  {r.status === 'adopted' && (
                    <Popconfirm title={t('team.idea.implementConfirm')} onConfirm={() => void setIdeaStatus(r, 'implemented').catch(() => undefined)}>
                      <Button type="link" size="small">
                        {t('team.idea.implemented')}
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
    { title: t('team.rule.col.name'), dataIndex: 'name', ellipsis: true },
    {
      title: t('team.rule.col.points'),
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
      title: t('team.enableCol'),
      dataIndex: 'active',
      width: 70,
      render: (v: boolean, r) =>
        canManage ? (
          <Switch size="small" checked={v} onChange={(checked) => void saveRule(r.code, r.points, checked)} />
        ) : (
          <Tag color={v ? 'green' : 'default'}>{v ? t('team.enabled') : t('team.disabled')}</Tag>
        ),
    },
  ];

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={16}>
        <Card
          title={t('team.idea.title')}
          extra={
            <Space>
              <Button icon={<TrophyOutlined />} onClick={openBoard}>
                {t('team.idea.leaderboard')}
              </Button>
              {canCreate && (
                <Button type="primary" icon={<PlusOutlined />} onClick={() => {
                  form.resetFields();
                  setCreateOpen(true);
                }}>
                  {t('team.idea.submit')}
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
            pagination={{ pageSize: 10, showTotal: (n) => t('team.total', { n }) }}
            expandable={{
              expandedRowRender: (r) => (
                <Space direction="vertical" size={8} style={{ display: 'flex' }}>
                  <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                    {r.content}
                  </Typography.Paragraph>
                  {r.status === 'declined' && r.decline_reason && (
                    <Typography.Text type="secondary">{t('team.idea.declineReasonExpand', { reason: r.decline_reason })}</Typography.Text>
                  )}
                  {r.adopted_at && (
                    <Typography.Text type="secondary">{t('team.idea.adoptedAt', { time: fmtTime(r.adopted_at) })}</Typography.Text>
                  )}
                </Space>
              ),
            }}
          />
        </Card>
      </Col>
      <Col xs={24} lg={8}>
        <Card
          title={t('team.rule.title')}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {canManage ? t('team.rule.blurHint') : ''}
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
        title={t('team.idea.submit')}
        open={createOpen}
        onOk={() => void handleCreate()}
        confirmLoading={saving}
        onCancel={() => setCreateOpen(false)}
        destroyOnClose
      >
        <Form<IdeaFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="title"
            label={t('team.col.title')}
            rules={[{ required: true, message: t('team.idea.titleRequired') }, { min: 2, message: t('team.minChars', { n: 2 }) }]}
          >
            <Input maxLength={200} placeholder={t('team.idea.titlePlaceholder')} />
          </Form.Item>
          <Form.Item name="content" label={t('team.idea.contentLabel')} rules={[{ required: true, message: t('team.idea.contentRequired') }]}>
            <Input.TextArea rows={5} maxLength={2000} placeholder={t('team.idea.contentPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 婉拒原因 */}
      <Modal
        title={declineTarget ? t('team.idea.declineTitle', { title: declineTarget.title }) : t('team.idea.declineTitlePlain')}
        open={!!declineTarget}
        onOk={() => void handleDecline()}
        confirmLoading={declining}
        onCancel={() => setDeclineTarget(null)}
        destroyOnClose
      >
        <Form form={declineForm} layout="vertical" preserve={false}>
          <Form.Item name="reason" label={t('team.idea.declineReasonLabel')} rules={[{ required: true, message: t('team.idea.declineReasonRequired') }]}>
            <Input.TextArea rows={3} maxLength={500} placeholder={t('team.idea.declineReasonPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 本期积分排行榜 */}
      <Drawer
        title={`${t('team.overview.widget.pointsBoard')}${board ? `（${board.period}）` : ''}`}
        width={420}
        open={boardOpen}
        onClose={() => setBoardOpen(false)}
      >
        <Spin spinning={boardLoading}>
          <Table
            rowKey={(r, i) => `${i}-${r.person_name ?? ''}`}
            size="small"
            columns={[
              { title: t('team.col.rank'), key: 'rank', width: 70, render: (_, __, i) => i + 1 },
              { title: t('team.col.person'), dataIndex: 'person_name', render: (v) => v || '-' },
              { title: t('team.col.points'), dataIndex: 'points', width: 100 },
            ]}
            dataSource={board?.board ?? []}
            pagination={false}
            locale={{ emptyText: t('team.overview.board.empty') }}
          />
        </Spin>
      </Drawer>
    </Row>
  );
}

// ---------------- 页面 ----------------

/** 活动积分复合页：专项活动 | 建言献策（顶部我的积分卡片） */
export default function ActivityPoints() {
  const t = useT();
  return (
    <div>
      <MyPointsCard />
      <PermTabs
        tabs={[
          { key: 'campaigns', label: t('team.campaign.tab'), modules: ['ideas'], children: <CampaignsTab /> },
          { key: 'ideas', label: t('team.idea.title'), modules: ['ideas'], children: <IdeasTab /> },
        ]}
      />
    </div>
  );
}
