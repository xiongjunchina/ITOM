import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  Collapse,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ImportOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { useAuthStore, hasPermission } from '../../stores/auth';
import type { Member, Portfolio, ProjectRow, ProjectStatus, ServiceItem } from '../../api/types';
import { PROJECT_STATUS } from '../../api/types';
import { HealthDot, StatusBadge } from './shared';
import CharterImportModal from './CharterImportModal';

const STATUS_OPTIONS = (Object.keys(PROJECT_STATUS) as ProjectStatus[]).map((s) => ({
  value: s,
  label: PROJECT_STATUS[s].label,
}));

/** 写权限：优先权限矩阵；存量会话缺失 permissions 时放行（后端仍会校验并中文提示） */
function useProjectPerm(action: 'create' | 'edit'): boolean {
  const user = useAuthStore((s) => s.user);
  return user?.permissions ? hasPermission(user, 'projects', action) : true;
}

// ---------------- 项目列表 ----------------

interface ProjectFormValues {
  name: string;
  pm: string;
  planned: [Dayjs, Dayjs];
  portfolio_id?: string;
  service_item_id?: string;
  budget_10k?: number;
  description?: string;
}

function ProjectList() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const canCreate = useProjectPerm('create');

  const [items, setItems] = useState<ProjectRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);

  // 筛选
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<string | undefined>();
  const [portfolioId, setPortfolioId] = useState<string | undefined>();
  const [mineOnly, setMineOnly] = useState(false);
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);

  // 新建项目 / 章程导入
  const [createOpen, setCreateOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<ProjectFormValues>();
  const [members, setMembers] = useState<Member[]>([]);
  const [serviceItems, setServiceItems] = useState<ServiceItem[]>([]);
  const [charterOpen, setCharterOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<ProjectRow>('/projects', {
        page,
        page_size: pageSize,
        q: q || undefined,
        status: status || undefined,
        portfolio_id: portfolioId || undefined,
        scope: mineOnly ? 'mine' : undefined,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, q, status, portfolioId, mineOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  // 从组合 tab 的「项目数」链接跳入：?portfolio=xxx 预置组合筛选
  const portfolioParam = searchParams.get('portfolio');
  useEffect(() => {
    if (portfolioParam) {
      setPortfolioId(portfolioParam);
      setPage(1);
    }
  }, [portfolioParam]);

  useEffect(() => {
    api
      .getList<Portfolio>('/portfolios')
      .then((res) => setPortfolios(res.items))
      .catch(() => undefined);
  }, []);

  const openCreate = () => {
    form.resetFields();
    setCreateOpen(true);
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 999 })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
    if (serviceItems.length === 0) {
      api
        .getList<ServiceItem>('/service-items')
        .then((res) => setServiceItems(res.items.filter((i) => i.status === '上架')))
        .catch(() => undefined);
    }
  };

  const submitCreate = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const created = await api.post<ProjectRow>('/projects', {
        name: values.name,
        pm: values.pm,
        planned_start: values.planned[0].format('YYYY-MM-DD'),
        planned_end: values.planned[1].format('YYYY-MM-DD'),
        portfolio_id: values.portfolio_id ?? null,
        service_item_id: values.service_item_id ?? null,
        budget_10k: values.budget_10k ?? null,
        description: values.description || null,
      });
      message.success(`项目 ${created.project_code ?? ''} 已创建`);
      setCreateOpen(false);
      if (created?.id) {
        navigate(`/projects/${created.id}`);
      } else {
        void load();
      }
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<ProjectRow> = [
    {
      title: '编号',
      dataIndex: 'project_code',
      width: 110,
      fixed: 'left',
      render: (v: string, r) => <Link to={`/projects/${r.id}`}>{v}</Link>,
    },
    { title: '名称', dataIndex: 'name', width: 220, ellipsis: true },
    { title: '组合', dataIndex: 'portfolio_name', width: 140, ellipsis: true, render: (v) => v || '-' },
    { title: '项目经理', dataIndex: 'pm_name', width: 100, render: (v) => v || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (_, r) => <StatusBadge status={r.status} name={r.status_name} />,
    },
    {
      title: '健康度',
      dataIndex: 'health',
      width: 90,
      render: (v: ProjectRow['health']) => <HealthDot health={v} />,
    },
    {
      title: '进度',
      dataIndex: 'progress',
      width: 140,
      render: (v: number | null) =>
        v == null ? '-' : <Progress percent={v} size="small" format={(p) => `${p ?? 0}%`} />,
    },
    {
      title: '计划起止',
      key: 'planned',
      width: 190,
      render: (_, r) => `${r.planned_start} ~ ${r.planned_end}`,
    },
    {
      title: '预算执行',
      dataIndex: 'budget_usage',
      width: 100,
      render: (v: number | null) =>
        v == null ? '-' : <span style={v > 100 ? { color: '#ff4d4f', fontWeight: 600 } : undefined}>{v}%</span>,
    },
    {
      title: '里程碑',
      key: 'milestones',
      width: 90,
      render: (_, r) => (
        <Badge count={r.milestone_overdue} size="small" offset={[8, -2]} title={`逾期 ${r.milestone_overdue} 个`}>
          <span>{r.milestone_total}</span>
        </Badge>
      ),
    },
  ];

  return (
    <>
      <Space wrap style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Space wrap>
          <Input.Search
            placeholder="搜索编号/名称"
            allowClear
            style={{ width: 220 }}
            onSearch={(v) => {
              setPage(1);
              setQ(v);
            }}
          />
          <Select
            placeholder="状态"
            allowClear
            style={{ width: 120 }}
            value={status}
            onChange={(v) => {
              setPage(1);
              setStatus(v);
            }}
            options={STATUS_OPTIONS}
          />
          <Select
            placeholder="项目组合"
            allowClear
            showSearch
            optionFilterProp="label"
            style={{ width: 180 }}
            value={portfolioId}
            onChange={(v) => {
              setPage(1);
              setPortfolioId(v);
            }}
            options={portfolios.map((p) => ({ value: p.id, label: p.name }))}
          />
          <span>
            只看我的{' '}
            <Switch
              checked={mineOnly}
              onChange={(v) => {
                setPage(1);
                setMineOnly(v);
              }}
            />
          </span>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新
          </Button>
        </Space>
        {canCreate && (
          <Space>
            <Button icon={<ImportOutlined />} onClick={() => setCharterOpen(true)}>
              章程导入
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新建项目
            </Button>
          </Space>
        )}
      </Space>

      <Table<ProjectRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1280 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />

      {/* 新建项目 Modal */}
      <Modal
        title="新建项目"
        open={createOpen}
        width={560}
        onOk={() => void submitCreate()}
        confirmLoading={saving}
        onCancel={() => setCreateOpen(false)}
        destroyOnClose
      >
        <Form<ProjectFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label="项目名称"
            rules={[
              { required: true, message: '请输入项目名称' },
              { min: 2, message: '至少 2 个字符' },
            ]}
          >
            <Input maxLength={200} placeholder="项目名称" />
          </Form.Item>
          <Form.Item name="pm" label="项目经理" rules={[{ required: true, message: '请选择项目经理' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择人员"
              options={members.map((m) => ({
                value: m.id,
                label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="planned"
            label="计划起止"
            rules={[{ required: true, message: '请选择计划起止日期' }]}
          >
            <DatePicker.RangePicker style={{ width: '100%' }} />
          </Form.Item>
          <Collapse
            ghost
            items={[
              {
                key: 'more',
                label: '更多选项',
                children: (
                  <>
                    <Form.Item name="portfolio_id" label="所属组合">
                      <Select
                        allowClear
                        showSearch
                        optionFilterProp="label"
                        placeholder="选择项目组合"
                        options={portfolios.map((p) => ({ value: p.id, label: p.name }))}
                      />
                    </Form.Item>
                    <Form.Item name="service_item_id" label="关联服务项">
                      <Select
                        allowClear
                        showSearch
                        optionFilterProp="label"
                        placeholder="选择服务项"
                        options={serviceItems.map((i) => ({
                          value: i.id,
                          label: `${i.name}（${i.catalog_name ?? i.item_code}）`,
                        }))}
                      />
                    </Form.Item>
                    <Form.Item name="budget_10k" label="预算（万元）">
                      <InputNumber min={0} precision={2} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item name="description" label="描述">
                      <Input.TextArea rows={3} maxLength={2000} />
                    </Form.Item>
                  </>
                ),
              },
            ]}
          />
        </Form>
      </Modal>

      <CharterImportModal open={charterOpen} onClose={() => setCharterOpen(false)} />
    </>
  );
}

// ---------------- 项目组合 ----------------

interface PortfolioFormValues {
  name: string;
  owner_id?: string;
  year?: string;
  description?: string;
  sort?: number;
}

function PortfolioPane() {
  const canCreate = useProjectPerm('create');
  const canEdit = useProjectPerm('edit');

  const [items, setItems] = useState<Portfolio[]>([]);
  const [loading, setLoading] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);

  const [editing, setEditing] = useState<Portfolio | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<PortfolioFormValues>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<Portfolio>('/portfolios');
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

  const openModal = (row: Portfolio | null) => {
    setEditing(row);
    form.resetFields();
    if (row) {
      form.setFieldsValue({
        name: row.name,
        owner_id: row.owner_id ?? undefined,
        year: row.year ?? undefined,
        description: row.description ?? undefined,
        sort: row.sort,
      });
    }
    setModalOpen(true);
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 999 })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
  };

  const submit = async () => {
    const values = await form.validateFields();
    const payload = {
      name: values.name,
      owner_id: values.owner_id ?? null,
      year: values.year ?? null,
      description: values.description || null,
      sort: values.sort ?? 0,
    };
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/portfolios/${editing.id}`, payload);
        message.success('组合已更新');
      } else {
        await api.post('/portfolios', payload);
        message.success('组合已创建');
      }
      setModalOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<Portfolio> = [
    { title: '名称', dataIndex: 'name', width: 220, ellipsis: true },
    { title: '负责人', dataIndex: 'owner_name', width: 120, render: (v) => v || '-' },
    { title: '年度', dataIndex: 'year', width: 100, render: (v) => v || '-' },
    {
      title: '项目数',
      dataIndex: 'project_count',
      width: 90,
      render: (v: number, r) =>
        v > 0 ? <Link to={`/projects?portfolio=${r.id}`}>{v}</Link> : v,
    },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
    ...(canEdit
      ? [
          {
            title: '操作',
            key: 'action',
            width: 90,
            render: (_: unknown, r: Portfolio) => (
              <Button type="link" size="small" onClick={() => openModal(r)}>
                编辑
              </Button>
            ),
          } as ColumnsType<Portfolio>[number],
        ]
      : []),
  ];

  return (
    <>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          刷新
        </Button>
        {canCreate && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal(null)}>
            新建组合
          </Button>
        )}
      </Space>
      <Table<Portfolio> rowKey="id" loading={loading} columns={columns} dataSource={items} pagination={false} />

      <Modal
        title={editing ? '编辑组合' : '新建组合'}
        open={modalOpen}
        onOk={() => void submit()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<PortfolioFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label="组合名称" rules={[{ required: true, message: '请输入组合名称' }]}>
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item name="owner_id" label="负责人">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="选择人员"
              options={members.map((m) => ({
                value: m.id,
                label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
              }))}
            />
          </Form.Item>
          <Form.Item name="year" label="年度">
            <Input maxLength={16} placeholder="如 2026" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} maxLength={1000} />
          </Form.Item>
          <Form.Item name="sort" label="排序">
            <InputNumber min={0} style={{ width: 120 }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ---------------- 页面：Tabs ----------------

export default function Projects() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get('tab') === 'portfolios' ? 'portfolios' : 'list';

  return (
    <Card title="项目管理">
      <Tabs
        activeKey={tab}
        onChange={(k) => setSearchParams(k === 'portfolios' ? { tab: 'portfolios' } : {})}
        items={[
          { key: 'list', label: '项目列表', children: <ProjectList /> },
          { key: 'portfolios', label: '项目组合', children: <PortfolioPane /> },
        ]}
      />
    </Card>
  );
}
