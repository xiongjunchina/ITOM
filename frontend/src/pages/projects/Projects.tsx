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
  Tooltip,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DownloadOutlined, ImportOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import { ExampleTag } from '../../components/ExampleTag';
import { useAuthStore, hasPermission } from '../../stores/auth';
import type {
  Member,
  Portfolio,
  ProjectDetail,
  ProjectRow,
  ProjectStatus,
  RequirementRow,
  ServiceItem,
} from '../../api/types';
import { PROJECT_STATUS } from '../../api/types';
import { useEnums } from '../../i18n/enums';
import { HealthDot, StatusBadge, fetchLinkableRequirements } from './shared';
import CharterImportModal from './CharterImportModal';
import ReasonModal from './ReasonModal';
import ProjectEditModal, { type ProjectEditModalProject } from './ProjectEditModal';

const STATUS_KEYS = Object.keys(PROJECT_STATUS) as ProjectStatus[];

/** 写权限：优先权限矩阵；存量会话缺失 permissions 时放行（后端仍会校验并中文提示） */
function useProjectPerm(action: 'create' | 'edit' | 'delete'): boolean {
  const user = useAuthStore((s) => s.user);
  return user?.permissions ? hasPermission(user, 'projects', action) : true;
}

// ---------------- 项目列表 ----------------

interface ProjectFormValues {
  name: string;
  pm: string;
  planned: [Dayjs, Dayjs];
  /** M16：关联来源需求（转项目管理且未挂接项目），项目验收关闭自动闭环该需求 */
  requirement_id?: string;
  portfolio_id?: string;
  service_item_id?: string;
  budget_10k?: number;
  description?: string;
}

function ProjectList() {
  const t = useT();
  const et = useEnums();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const canCreate = useProjectPerm('create');
  const canEdit = useProjectPerm('edit');
  const canDelete = useProjectPerm('delete');

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
  const [linkableReqs, setLinkableReqs] = useState<RequirementRow[]>([]);
  const [charterOpen, setCharterOpen] = useState(false);

  // 行内编辑（共享编辑弹窗）：列表行缺 service_item_id/description，先取详情再打开
  const [editing, setEditing] = useState<ProjectEditModalProject | null>(null);

  const openRowEdit = async (r: ProjectRow) => {
    try {
      const d = await api.get<ProjectDetail>(`/projects/${r.id}`);
      setEditing({
        id: d.id,
        name: d.name,
        pm: d.pm,
        planned_start: d.planned_start,
        planned_end: d.planned_end,
        portfolio_id: d.portfolio_id,
        service_item_id: d.service_item_id,
        budget_10k: d.budget_10k,
        description: d.description,
        actual_start: d.actual_start,
        actual_end: d.actual_end,
        background: d.background,
        goals: d.goals,
        scope_in: d.scope_in,
        scope_out: d.scope_out,
        resource_note: d.resource_note,
        org_members: d.org_members ?? [],
        stakeholders: d.stakeholders ?? [],
      });
    } catch {
      // 已统一提示
    }
  };

  // 列表快捷操作（M14；M14.1 暂停/关闭必填理由，删除不限状态）
  const [reasonOp, setReasonOp] = useState<{ project: ProjectRow; to: string; label: string } | null>(null);

  const runTransition = (r: ProjectRow, to: string, label: string) => {
    if (to === 'paused' || to === 'closed') {
      setReasonOp({ project: r, to, label });
      return;
    }
    Modal.confirm({
      title: t('proj.op.confirmTitle', { op: label, name: r.name }),
      content: to === 'active' ? t('proj.op.restartHint') : undefined,
      okText: t('common.confirm'),
      cancelText: t('common.cancel'),
      onOk: async () => {
        await api.post(`/projects/${r.id}/transition`, { to, fields: {} });
        message.success(t('proj.actionOk'));
        void load();
      },
    });
  };
  const runDelete = (r: ProjectRow) => {
    Modal.confirm({
      title: t('proj.op.deleteTitle', { name: r.name }),
      content: t('proj.op.deleteCascade'),
      okText: t('common.delete'),
      okButtonProps: { danger: true },
      cancelText: t('common.cancel'),
      onOk: async () => {
        await api.delete(`/projects/${r.id}`);
        message.success(t('proj.op.deleted'));
        void load();
      },
    });
  };

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
    // 关联需求候选每次打开都刷新（挂接状态随建项目实时变化）
    fetchLinkableRequirements()
      .then(setLinkableReqs)
      .catch(() => undefined);
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
        requirement_id: values.requirement_id ?? null,
        portfolio_id: values.portfolio_id ?? null,
        service_item_id: values.service_item_id ?? null,
        budget_10k: values.budget_10k ?? null,
        description: values.description || null,
      });
      message.success(t('proj.projectCreated', { code: created.project_code ?? '' }));
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
      title: t('proj.col.code'),
      dataIndex: 'project_code',
      width: 150,
      fixed: 'left',
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string, r) => (
        <Space size={4}>
          <Link to={`/projects/${r.id}`}>{v}</Link>
          {r.is_example && <ExampleTag />}
        </Space>
      ),
    },
    { title: t('proj.col.name'), dataIndex: 'name', width: 220, ellipsis: true },
    { title: t('proj.col.portfolio'), dataIndex: 'portfolio_name', width: 140, ellipsis: true, render: (v) => v || '-' },
    { title: t('proj.col.pm'), dataIndex: 'pm_name', width: 100, render: (v) => v || '-' },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 100,
      render: (_, r) => <StatusBadge status={r.status} name={r.status_name} />,
    },
    {
      title: t('proj.col.health'),
      dataIndex: 'health',
      width: 90,
      render: (v: ProjectRow['health']) => <HealthDot health={v} />,
    },
    {
      title: t('proj.col.progress'),
      dataIndex: 'progress',
      width: 140,
      render: (v: number | null) =>
        v == null ? '-' : <Progress percent={v} size="small" format={(p) => `${p ?? 0}%`} />,
    },
    {
      title: t('proj.col.planned'),
      key: 'planned',
      width: 200,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (_, r) => `${r.planned_start} ~ ${r.planned_end}`,
    },
    {
      title: t('proj.col.budgetUsage'),
      dataIndex: 'budget_usage',
      width: 100,
      render: (v: number | null) =>
        v == null ? '-' : <span style={v > 100 ? { color: '#ff4d4f', fontWeight: 600 } : undefined}>{v}%</span>,
    },
    {
      title: t('proj.col.milestones'),
      key: 'milestones',
      width: 90,
      render: (_, r) => (
        <Badge
          count={r.milestone_overdue}
          size="small"
          offset={[8, -2]}
          title={t('proj.milestoneOverdueTitle', { n: r.milestone_overdue })}
        >
          <span>{r.milestone_total}</span>
        </Badge>
      ),
    },
    ...(canEdit
      ? [
          {
            title: t('common.actions'),
            key: 'action',
            width: 236,
            fixed: 'right' as const,
            render: (_: unknown, r: ProjectRow) => {
              if (r.is_example) return null;
              const st = r.status;
              const isFinal = st === 'closed' || st === 'cancelled';
              const linkBtn = (
                label: string,
                enabled: boolean,
                onClick: () => void,
                tip: string,
                danger = false,
              ) => {
                const b = (
                  <Button
                    type="link"
                    size="small"
                    danger={danger}
                    disabled={!enabled}
                    style={{ paddingInline: 4 }}
                    onClick={onClick}
                  >
                    {label}
                  </Button>
                );
                return enabled ? b : <Tooltip title={tip}>{b}</Tooltip>;
              };
              return (
                <span style={{ whiteSpace: 'nowrap' }}>
                  {linkBtn(t('common.edit'), !isFinal, () => void openRowEdit(r), t('proj.editFinalTooltip'))}
                  {linkBtn(t('proj.op.pause'), st === 'active', () => runTransition(r, 'paused', t('proj.op.pause')), t('proj.op.onlyActive'))}
                  {linkBtn(t('proj.op.close'), ['active', 'paused', 'completed'].includes(st), () => runTransition(r, 'closed', t('proj.op.close')), t('proj.op.closeDisabled'))}
                  {linkBtn(t('proj.op.restart'), ['paused', 'closed', 'completed'].includes(st), () => runTransition(r, 'active', t('proj.op.restart')), t('proj.op.restartDisabled'))}
                  {canDelete && linkBtn(t('common.delete'), true, () => runDelete(r), '', true)}
                </span>
              );
            },
          } as ColumnsType<ProjectRow>[number],
        ]
      : []),
  ];

  return (
    <>
      <Space wrap style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Space wrap>
          <Input.Search
            placeholder={t('proj.searchPlaceholder')}
            allowClear
            style={{ width: 220 }}
            onSearch={(v) => {
              setPage(1);
              setQ(v);
            }}
          />
          <Select
            placeholder={t('common.status')}
            allowClear
            style={{ width: 120 }}
            value={status}
            onChange={(v) => {
              setPage(1);
              setStatus(v);
            }}
            options={STATUS_KEYS.map((s) => ({ value: s, label: et.projectStatus(s) }))}
          />
          <Select
            placeholder={t('proj.portfolio')}
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
            {t('proj.mineOnly')}{' '}
            <Switch
              checked={mineOnly}
              onChange={(v) => {
                setPage(1);
                setMineOnly(v);
              }}
            />
          </span>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            {t('common.refresh')}
          </Button>
        </Space>
        {canCreate && (
          <Space>
            <Button
              icon={<DownloadOutlined />}
              onClick={() => void api.download('/projects/charter/template')}
            >
              {t('proj.charterTemplate')}
            </Button>
            <Button icon={<ImportOutlined />} onClick={() => setCharterOpen(true)}>
              {t('proj.charterImport')}
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              {t('proj.newProject')}
            </Button>
          </Space>
        )}
      </Space>

      <Table<ProjectRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        sticky
        scroll={{ x: 'max-content' }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (n) => t('proj.totalN', { n }),
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />

      {/* 新建项目 Modal */}
      <Modal
        title={t('proj.newProject')}
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
            label={t('proj.projectName')}
            rules={[
              { required: true, message: t('proj.projectNameRequired') },
              { min: 2, message: t('proj.min2') },
            ]}
          >
            <Input maxLength={200} placeholder={t('proj.projectName')} />
          </Form.Item>
          <Form.Item name="pm" label={t('proj.pm')} rules={[{ required: true, message: t('proj.pmRequired') }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={t('proj.selectMember')}
              options={members.map((m) => ({
                value: m.id,
                label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="planned"
            label={t('proj.planned')}
            rules={[{ required: true, message: t('proj.plannedRequired') }]}
          >
            <DatePicker.RangePicker style={{ width: '100%' }} />
          </Form.Item>
          {/* M16 关联来源需求：仅列 转项目管理 且未挂接项目的实现中需求 */}
          <Form.Item name="requirement_id" label={t('proj.linkReq')} extra={t('proj.linkReqHint')}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={t('proj.linkReqPlaceholder')}
              options={linkableReqs.map((r) => ({
                value: r.id,
                label: `${r.requirement_code} ${r.title}`,
              }))}
            />
          </Form.Item>
          <Collapse
            ghost
            items={[
              {
                key: 'more',
                label: t('proj.moreOptions'),
                children: (
                  <>
                    <Form.Item name="portfolio_id" label={t('proj.belongPortfolio')}>
                      <Select
                        allowClear
                        showSearch
                        optionFilterProp="label"
                        placeholder={t('proj.selectPortfolio')}
                        options={portfolios.map((p) => ({ value: p.id, label: p.name }))}
                      />
                    </Form.Item>
                    <Form.Item name="service_item_id" label={t('proj.linkedService')}>
                      <Select
                        allowClear
                        showSearch
                        optionFilterProp="label"
                        placeholder={t('proj.selectService')}
                        options={serviceItems.map((i) => ({
                          value: i.id,
                          label: `${i.name}（${i.catalog_name ?? i.item_code}）`,
                        }))}
                      />
                    </Form.Item>
                    <Form.Item name="budget_10k" label={t('proj.budgetWan')}>
                      <InputNumber min={0} precision={2} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item name="description" label={t('proj.desc')}>
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

      <ReasonModal
        open={!!reasonOp}
        opLabel={reasonOp?.label ?? ''}
        projectName={reasonOp?.project.name ?? ''}
        onClose={() => setReasonOp(null)}
        onSubmit={async (reason) => {
          if (!reasonOp) return;
          await api.post(`/projects/${reasonOp.project.id}/transition`, {
            to: reasonOp.to,
            fields: { reason },
          });
          message.success(t('proj.actionOk'));
          setReasonOp(null);
          void load();
        }}
      />
      {/* 行内编辑（共享编辑弹窗） */}
      <ProjectEditModal
        project={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          void load();
        }}
      />
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
  const t = useT();
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
        message.success(t('proj.portfolioUpdated'));
      } else {
        await api.post('/portfolios', payload);
        message.success(t('proj.portfolioCreated'));
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
    {
      title: t('proj.col.name'),
      dataIndex: 'name',
      width: 220,
      ellipsis: true,
      render: (v: string, r) => (
        <Space size={4}>
          {v}
          {r.is_example && <ExampleTag />}
        </Space>
      ),
    },
    { title: t('proj.col.owner'), dataIndex: 'owner_name', width: 120, render: (v) => v || '-' },
    { title: t('proj.col.year'), dataIndex: 'year', width: 100, render: (v) => v || '-' },
    {
      title: t('proj.col.projectCount'),
      dataIndex: 'project_count',
      width: 90,
      render: (v: number, r) =>
        v > 0 ? <Link to={`/projects?portfolio=${r.id}`}>{v}</Link> : v,
    },
    { title: t('proj.col.desc'), dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
    ...(canEdit
      ? [
          {
            title: t('common.actions'),
            key: 'action',
            width: 90,
            render: (_: unknown, r: Portfolio) =>
              r.is_example ? null : (
                <Button type="link" size="small" onClick={() => openModal(r)}>
                  {t('common.edit')}
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
          {t('common.refresh')}
        </Button>
        {canCreate && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal(null)}>
            {t('proj.newPortfolio')}
          </Button>
        )}
      </Space>
      <Table<Portfolio> rowKey="id" loading={loading} columns={columns} dataSource={items} pagination={false} />

      <Modal
        title={editing ? t('proj.editPortfolio') : t('proj.newPortfolio')}
        open={modalOpen}
        onOk={() => void submit()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<PortfolioFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label={t('proj.portfolioName')} rules={[{ required: true, message: t('proj.portfolioNameRequired') }]}>
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item name="owner_id" label={t('proj.owner')}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={t('proj.selectMember')}
              options={members.map((m) => ({
                value: m.id,
                label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
              }))}
            />
          </Form.Item>
          <Form.Item name="year" label={t('proj.year')}>
            <Input maxLength={16} placeholder={t('proj.yearPlaceholder')} />
          </Form.Item>
          <Form.Item name="description" label={t('proj.desc')}>
            <Input.TextArea rows={3} maxLength={1000} />
          </Form.Item>
          <Form.Item name="sort" label={t('proj.sort')}>
            <InputNumber min={0} style={{ width: 120 }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ---------------- 页面：Tabs ----------------

/** 二级菜单页（M17）：项目列表 / 项目组合 由左侧导航直达，不再用页内 Tabs */
export default function Projects({ pane }: { pane: 'list' | 'portfolios' }) {
  const t = useT();
  return (
    <Card title={t(pane === 'portfolios' ? 'proj.tab.portfolios' : 'proj.tab.list')}>
      {pane === 'portfolios' ? <PortfolioPane /> : <ProjectList />}
    </Card>
  );
}
