import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Tag, Tooltip, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import { CheckOutlined, CloseOutlined, DeleteOutlined, DownloadOutlined, EditFilled, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
import PermTabs from '../../components/PermTabs';
import ImportButtons from '../../components/ImportButtons';
import { hasPermission, useAuthStore } from '../../stores/auth';
import type { HiringNeedRow, Position } from '../../api/types';
import { HIRING_LEVELS, HIRING_LEVEL_COLORS, HIRING_STATUSES, HIRING_STATUS_COLORS } from '../../api/types';

/** 写权限：优先权限矩阵；存量会话缺失 permissions 时放行（后端仍会校验并中文提示） */
function usePositionsPerm(action: 'create' | 'edit' | 'delete'): boolean {
  const user = useAuthStore((s) => s.user);
  return user?.permissions ? hasPermission(user, 'positions', action) : true;
}

function splitList(value?: string): string[] {
  return (value ?? '')
    .replace(/[、,，]/g, '；')
    .split('；')
    .map((v) => v.trim())
    .filter(Boolean);
}

// ---------------- Tab 1：岗位定义 ----------------

interface PositionForm {
  position_code?: string;
  name: string;
  position_family?: string;
  duties?: string;
  headcount?: number;
  service_domains?: string;
  primary_roles?: string;
  level_framework?: string;
  location_scope?: string;
  skills?: string;
  contractor_allowed?: boolean;
  status?: string;
  sort?: number;
}

function PositionsTab() {
  const t = useT();
  const canCreate = usePositionsPerm('create');
  const canEdit = usePositionsPerm('edit');
  const canDelete = usePositionsPerm('delete');
  const [items, setItems] = useState<Position[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Position | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<PositionForm>();
  const [inlineEditingId, setInlineEditingId] = useState<string | null>(null);
  const [inlineDraft, setInlineDraft] = useState<Partial<PositionForm>>({});
  const [inlineSaving, setInlineSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<Position>('/positions', {
        page,
        page_size: pageSize,
        q: q || undefined,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, q]);

  useEffect(() => {
    void load();
  }, [load]);

  const startInlineEdit = (record: Position) => {
    setInlineEditingId(record.id);
    setInlineDraft({
      position_code: record.position_code ?? undefined,
      name: record.name,
      position_family: record.position_family ?? undefined,
      duties: record.duties ?? undefined,
      headcount: record.headcount ?? 0,
      status: record.status ?? '启用',
      sort: record.sort ?? 0,
      service_domains: record.service_domains?.join('；'),
      primary_roles: record.primary_roles?.join('；'),
      level_framework: record.level_framework ?? undefined,
      location_scope: record.location_scope ?? undefined,
      skills: record.skills ?? undefined,
      contractor_allowed: record.contractor_allowed ?? false,
    });
  };

  const cancelInlineEdit = () => {
    setInlineEditingId(null);
    setInlineDraft({});
  };

  const saveInlineEdit = async (record: Position) => {
    if (!inlineDraft.name?.trim()) {
      message.error(t('team.positions.form.nameRequired'));
      return;
    }
    setInlineSaving(true);
    try {
      await api.patch(`/positions/${record.id}`, {
        ...inlineDraft,
        name: inlineDraft.name.trim(),
        service_domains: splitList(inlineDraft.service_domains),
        primary_roles: splitList(inlineDraft.primary_roles),
      });
      message.success(t('team.positions.def.updated'));
      cancelInlineEdit();
      void load();
    } catch {
      // 已统一提示
    } finally {
      setInlineSaving(false);
    }
  };

  const deletePosition = async (record: Position) => {
    try {
      await api.delete(`/positions/${record.id}`);
      message.success(t('common.deleted'));
      if (inlineEditingId === record.id) cancelInlineEdit();
      void load();
    } catch {
      // 已统一提示
    }
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ headcount: 0, contractor_allowed: false, status: '启用', sort: 0 });
    setModalOpen(true);
  };

  const openEdit = (record: Position) => {
    setEditing(record);
    form.setFieldsValue({
      position_code: record.position_code ?? undefined,
      name: record.name,
      position_family: record.position_family ?? undefined,
      duties: record.duties ?? undefined,
      headcount: record.headcount ?? 0,
      status: record.status ?? '启用',
      sort: record.sort ?? 0,
      service_domains: record.service_domains?.join('；'),
      primary_roles: record.primary_roles?.join('；'),
      level_framework: record.level_framework ?? undefined,
      location_scope: record.location_scope ?? undefined,
      skills: record.skills ?? undefined,
      contractor_allowed: record.contractor_allowed ?? false,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const payload = {
        ...values,
        service_domains: splitList(values.service_domains),
        primary_roles: splitList(values.primary_roles),
      };
      if (editing) {
        await api.patch(`/positions/${editing.id}`, payload);
        message.success(t('team.positions.def.updated'));
      } else {
        await api.post('/positions', payload);
        message.success(t('team.positions.def.created'));
      }
      setModalOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<Position> = [
    {
      title: t('team.positions.col.code'), dataIndex: 'position_code', width: 150,
      render: (v, record) => inlineEditingId === record.id ? <Input size="small" value={inlineDraft.position_code} onChange={(e) => setInlineDraft((d) => ({ ...d, position_code: e.target.value }))} /> : v || '-',
    },
    {
      title: t('team.positions.col.name'), dataIndex: 'name', width: 200,
      render: (v, record) => inlineEditingId === record.id ? <Input size="small" value={inlineDraft.name} onChange={(e) => setInlineDraft((d) => ({ ...d, name: e.target.value }))} /> : v,
    },
    {
      title: t('team.positions.col.family'), dataIndex: 'position_family', width: 140,
      render: (v, record) => inlineEditingId === record.id ? <Input size="small" value={inlineDraft.position_family} onChange={(e) => setInlineDraft((d) => ({ ...d, position_family: e.target.value }))} /> : v || '-',
    },
    {
      title: t('team.positions.col.duties'), dataIndex: 'duties', width: 260, ellipsis: true,
      render: (v, record) => inlineEditingId === record.id ? <Input size="small" value={inlineDraft.duties} onChange={(e) => setInlineDraft((d) => ({ ...d, duties: e.target.value }))} /> : v || '-',
    },
    {
      title: t('team.positions.col.headcount'), dataIndex: 'headcount', width: 110,
      render: (v, record) => inlineEditingId === record.id ? <InputNumber size="small" min={0} value={inlineDraft.headcount} onChange={(value) => setInlineDraft((d) => ({ ...d, headcount: value ?? 0 }))} /> : v,
    },
    { title: t('team.positions.col.onboard'), dataIndex: 'formal_onboard', width: 90 },
    { title: t('team.positions.col.gap'), dataIndex: 'gap', width: 75, render: (v) => <Tag color={v > 0 ? 'orange' : 'green'}>{v}</Tag> },
    {
      title: t('team.positions.col.status'), dataIndex: 'status', width: 110,
      render: (v, record) => inlineEditingId === record.id ? <Select size="small" value={inlineDraft.status} options={[{ value: '启用', label: '启用' }, { value: '停用', label: '停用' }]} onChange={(value) => setInlineDraft((d) => ({ ...d, status: value }))} /> : <Tag color={v === '启用' ? 'green' : 'default'}>{v || '-'}</Tag>,
    },
    {
      title: t('common.actions'),
      key: 'action',
      width: 160,
      fixed: 'right',
      render: (_, record) => {
        const editingRow = inlineEditingId === record.id;
        return (
          <Space size={0}>
            {canEdit && <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>{t('common.edit')}</Button>}
            {canEdit && (editingRow ? (
              <>
                <Button type="link" size="small" icon={<CheckOutlined />} loading={inlineSaving} onClick={() => void saveInlineEdit(record)}>{t('common.save')}</Button>
                <Button type="link" size="small" icon={<CloseOutlined />} onClick={cancelInlineEdit}>{t('common.cancel')}</Button>
              </>
            ) : <Button type="link" size="small" icon={<EditFilled />} onClick={() => startInlineEdit(record)}>{t('team.positions.inlineEdit')}</Button>)}
            {canDelete && <Popconfirm title={t('common.deleteConfirm')} onConfirm={() => void deletePosition(record)}>
              <Button type="link" size="small" danger icon={<DeleteOutlined />} aria-label={t('common.delete')}>{t('common.delete')}</Button>
            </Popconfirm>}
          </Space>
        );
      },
    },
  ];

  return (
    <Card
      title={t('team.positions.def.title')}
      extra={
        <Space>
          <Input.Search
            placeholder={t('team.positions.def.searchPlaceholder')}
            allowClear
            onSearch={(v) => {
              setPage(1);
              setQ(v);
            }}
            style={{ width: 220 }}
          />
          <Button icon={<DownloadOutlined />} onClick={() => void api.download('/positions/export')}>
            {t('team.positions.export')}
          </Button>
          {canCreate && <ImportButtons templateUrl="/positions/template" importUrl="/positions/import" onDone={() => void load()} />}
          {canCreate && <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>{t('team.positions.def.create')}</Button>}
        </Space>
      }
    >
      <Table<Position>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1250 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: [10, 20, 50, 100],
          showTotal: (n) => t('team.total', { n }),
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />
      <Modal
        title={editing ? t('team.positions.def.editTitle') : t('team.positions.def.create')}
        open={modalOpen}
        width={760}
        styles={{ body: { maxHeight: '68vh', overflowY: 'auto', paddingInlineEnd: 8 } }}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<PositionForm> form={form} layout="vertical" preserve={false}>
          <Form.Item name="position_code" label={t('team.positions.col.code')}>
            <Input maxLength={32} placeholder={t('team.positions.form.codePlaceholder')} />
          </Form.Item>
          <Form.Item
            name="name"
            label={t('team.positions.col.name')}
            rules={[{ required: true, message: t('team.positions.form.nameRequired') }]}
          >
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="position_family" label={t('team.positions.col.family')}>
            <Input maxLength={32} placeholder={t('team.positions.form.familyPlaceholder')} />
          </Form.Item>
          <Form.Item name="service_domains" label={t('team.positions.col.serviceDomains')}>
            <Input placeholder={t('team.positions.form.listPlaceholder')} />
          </Form.Item>
          <Form.Item name="primary_roles" label={t('team.positions.col.primaryRoles')}>
            <Input placeholder={t('team.positions.form.rolesPlaceholder')} />
          </Form.Item>
          <Form.Item name="level_framework" label={t('team.positions.col.levelFramework')}>
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item name="location_scope" label={t('team.positions.col.locationScope')}>
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item name="skills" label={t('team.positions.col.skills')}>
            <Input placeholder={t('team.positions.form.listPlaceholder')} />
          </Form.Item>
          <Form.Item name="duties" label={t('team.positions.col.duties')}>
            <Input.TextArea rows={3} maxLength={500} />
          </Form.Item>
          <Form.Item name="headcount" label={t('team.positions.col.headcount')}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="contractor_allowed" label={t('team.positions.col.contractorAllowed')}>
            <Select options={[{ value: false, label: t('common.no') }, { value: true, label: t('common.yes') }]} />
          </Form.Item>
          <Form.Item name="status" label={t('team.positions.col.status')}>
            <Select options={[{ value: '启用', label: '启用' }, { value: '停用', label: '停用' }]} />
          </Form.Item>
          <Form.Item name="sort" label={t('team.positions.col.sort')}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

// ---------------- Tab 2：招聘需求 ----------------

interface HiringFormValues {
  position_id: string;
  level: string;
  headcount: number;
  qualification?: string;
  status: string;
  progress_note?: string;
}

function HiringTab() {
  const t = useT();
  const et = useEnums();
  const canCreate = usePositionsPerm('create');
  const canEdit = usePositionsPerm('edit');
  const canDelete = usePositionsPerm('delete');

  const [items, setItems] = useState<HiringNeedRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [positions, setPositions] = useState<Position[]>([]);
  const [tablePage, setTablePage] = useState(1);
  const [tablePageSize, setTablePageSize] = useState(20);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<HiringNeedRow | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<HiringFormValues>();
  const [inlineEditingId, setInlineEditingId] = useState<string | null>(null);
  const [inlineDraft, setInlineDraft] = useState<Partial<HiringFormValues>>({});
  const [inlineSaving, setInlineSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<HiringNeedRow>('/hiring-needs');
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

  const startInlineEdit = (record: HiringNeedRow) => {
    ensurePositions();
    setInlineEditingId(record.id);
    setInlineDraft({
      position_id: record.position_id,
      level: record.level || '中级',
      headcount: record.headcount,
      qualification: record.qualification ?? '',
      status: record.status || '待招聘',
      progress_note: record.progress_note ?? '',
    });
  };

  const cancelInlineEdit = () => {
    setInlineEditingId(null);
    setInlineDraft({});
  };

  const saveInlineEdit = async (record: HiringNeedRow) => {
    if (!inlineDraft.position_id || !inlineDraft.qualification?.trim() || (inlineDraft.qualification?.trim().length ?? 0) < 5) {
      message.error(t('team.positions.hiring.form.qualRequired'));
      return;
    }
    setInlineSaving(true);
    try {
      await api.patch(`/hiring-needs/${record.id}`, {
        position_id: inlineDraft.position_id,
        level: inlineDraft.level || '中级',
        headcount: inlineDraft.headcount ?? 1,
        qualification: inlineDraft.qualification.trim(),
        status: inlineDraft.status || '待招聘',
        progress_note: inlineDraft.progress_note?.trim() || null,
      });
      message.success(t('team.positions.hiring.updated'));
      cancelInlineEdit();
      void load();
    } catch {
      // 已统一提示
    } finally {
      setInlineSaving(false);
    }
  };

  const deleteHiring = async (record: HiringNeedRow) => {
    try {
      await api.delete(`/hiring-needs/${record.id}`);
      message.success(t('common.deleted'));
      if (inlineEditingId === record.id) cancelInlineEdit();
      void load();
    } catch {
      // 已统一提示
    }
  };

  const ensurePositions = () => {
    if (positions.length === 0) {
      api
        .getList<Position>('/positions', { page: 1, page_size: 999 })
        .then((res) => setPositions(res.items.filter((p) => p.status !== '停用')))
        .catch(() => undefined);
    }
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ headcount: 1, status: '待招聘', level: '中级' });
    ensurePositions();
    setModalOpen(true);
  };

  const openEdit = (record: HiringNeedRow) => {
    ensurePositions();
    setEditing(record);
    form.setFieldsValue({
      position_id: record.position_id,
      level: record.level || '中级',
      headcount: record.headcount ?? 1,
      qualification: record.qualification ?? '',
      status: record.status || '待招聘',
      progress_note: record.progress_note ?? '',
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    // PATCH 需带全字段（position_id/level/headcount/qualification/status/progress_note）
    const payload = {
      position_id: values.position_id,
      level: values.level,
      headcount: values.headcount,
      qualification: values.qualification || null,
      status: values.status,
      progress_note: values.progress_note || null,
    };
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/hiring-needs/${editing.id}`, payload);
        message.success(t('team.positions.hiring.updated'));
      } else {
        await api.post('/hiring-needs', payload);
        message.success(t('team.positions.hiring.created'));
      }
      setModalOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<HiringNeedRow> = [
    {
      title: t('team.positions.hiring.col.position'), dataIndex: 'position_name', width: 210,
      render: (v, record) => inlineEditingId === record.id ? <Select size="small" showSearch optionFilterProp="label" value={inlineDraft.position_id} options={[...(record.position_id && record.position_name ? [{ value: record.position_id, label: record.position_name }] : []), ...positions.filter((p) => p.id !== record.position_id).map((p) => ({ value: p.id, label: p.name }))]} onChange={(value) => setInlineDraft((d) => ({ ...d, position_id: value }))} style={{ width: '100%' }} /> : v || '-',
    },
    {
      title: t('team.positions.hiring.col.level'),
      dataIndex: 'level',
      width: 80,
      render: (v: string, record) => inlineEditingId === record.id ? <Select size="small" value={inlineDraft.level} options={HIRING_LEVELS.map((l) => ({ value: l, label: et.hiringLevel(l) }))} onChange={(value) => setInlineDraft((d) => ({ ...d, level: value }))} /> : <Tag color={HIRING_LEVEL_COLORS[v] ?? 'default'}>{et.hiringLevel(v || '中级')}</Tag>,
    },
    {
      title: t('team.positions.hiring.col.headcount'), dataIndex: 'headcount', width: 90,
      render: (v, record) => inlineEditingId === record.id ? <InputNumber size="small" min={1} value={inlineDraft.headcount} onChange={(value) => setInlineDraft((d) => ({ ...d, headcount: value ?? 1 }))} /> : v,
    },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 100,
      render: (v: string, record) => inlineEditingId === record.id ? <Select size="small" value={inlineDraft.status} options={HIRING_STATUSES.map((s) => ({ value: s, label: et.hiringStatus(s) }))} onChange={(value) => setInlineDraft((d) => ({ ...d, status: value }))} /> : <Tag color={HIRING_STATUS_COLORS[v] ?? 'default'}>{et.hiringStatus(v)}</Tag>,
    },
    {
      title: t('team.positions.hiring.col.qualification'),
      dataIndex: 'qualification',
      ellipsis: { showTitle: false },
      render: (v: string | null, record) =>
        inlineEditingId === record.id ? <Input size="small" value={inlineDraft.qualification} onChange={(e) => setInlineDraft((d) => ({ ...d, qualification: e.target.value }))} /> : v ? (
          <Tooltip placement="topLeft" title={v}>
            {v}
          </Tooltip>
        ) : (
          '-'
        ),
    },
    {
      title: t('team.positions.hiring.col.progressNote'), dataIndex: 'progress_note', ellipsis: true,
      render: (v, record) => inlineEditingId === record.id ? <Input size="small" value={inlineDraft.progress_note} onChange={(e) => setInlineDraft((d) => ({ ...d, progress_note: e.target.value }))} /> : v || '-',
    },
    ...(canEdit
      ? [
          {
            title: t('common.actions'),
            key: 'action',
            width: 180,
            fixed: 'right' as const,
            render: (_: unknown, r: HiringNeedRow) => {
              const editingRow = inlineEditingId === r.id;
              return <Space size={0}>
                <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>{t('common.edit')}</Button>
                {editingRow ? <>
                  <Button type="link" size="small" icon={<CheckOutlined />} loading={inlineSaving} onClick={() => void saveInlineEdit(r)}>{t('common.save')}</Button>
                  <Button type="link" size="small" icon={<CloseOutlined />} onClick={cancelInlineEdit}>{t('common.cancel')}</Button>
                </> : <Button type="link" size="small" icon={<EditFilled />} onClick={() => startInlineEdit(r)}>{t('team.positions.inlineEdit')}</Button>}
                {canDelete && <Popconfirm title={t('common.deleteConfirm')} onConfirm={() => void deleteHiring(r)}>
                  <Button type="link" size="small" danger icon={<DeleteOutlined />} aria-label={t('common.delete')}>{t('common.delete')}</Button>
                </Popconfirm>}
              </Space>;
            },
          } as ColumnsType<HiringNeedRow>[number],
        ]
      : canDelete ? [{
          title: t('common.actions'), key: 'action', width: 100, fixed: 'right' as const,
          render: (_: unknown, r: HiringNeedRow) => <Popconfirm title={t('common.deleteConfirm')} onConfirm={() => void deleteHiring(r)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} aria-label={t('common.delete')}>{t('common.delete')}</Button>
          </Popconfirm>,
        } as ColumnsType<HiringNeedRow>[number]] : []),
  ];

  return (
    <Card
      title={t('team.positions.hiring.title')}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            {t('common.refresh')}
          </Button>
          <Button icon={<DownloadOutlined />} onClick={() => void api.download('/hiring-needs/export')}>
            {t('team.positions.export')}
          </Button>
          {canCreate && <ImportButtons templateUrl="/hiring-needs/template" importUrl="/hiring-needs/import" onDone={() => void load()} />}
          {canCreate && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              {t('team.positions.hiring.create')}
            </Button>
          )}
        </Space>
      }
    >
      <Table<HiringNeedRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1250 }}
        pagination={{
          current: tablePage,
          pageSize: tablePageSize,
          showSizeChanger: true,
          pageSizeOptions: [10, 20, 50, 100],
          showTotal: (n) => t('team.total', { n }),
          onChange: (page, pageSize) => {
            setTablePage(page);
            setTablePageSize(pageSize);
          },
        }}
      />

      <Modal
        title={editing ? t('team.positions.hiring.editTitle') : t('team.positions.hiring.create')}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<HiringFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="position_id" label={t('team.positions.hiring.col.position')} rules={[{ required: true, message: t('team.positions.hiring.form.positionRequired') }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={t('team.positions.hiring.form.positionPlaceholder')}
              options={positions.map((p) => ({ value: p.id, label: p.name }))}
            />
          </Form.Item>
          <Form.Item name="level" label={t('team.positions.hiring.col.level')} rules={[{ required: true, message: t('team.positions.hiring.form.levelRequired') }]}>
            <Select options={HIRING_LEVELS.map((l) => ({ value: l, label: et.hiringLevel(l) }))} />
          </Form.Item>
          <Form.Item name="headcount" label={t('team.positions.hiring.form.headcountLabel')} rules={[{ required: true, message: t('team.positions.hiring.form.headcountRequired') }]}>
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="qualification"
            label={t('team.positions.hiring.col.qualification')}
            rules={[
              { required: true, message: t('team.positions.hiring.form.qualRequired') },
              { min: 5, message: t('team.minChars', { n: 5 }) },
            ]}
          >
            <Input.TextArea
              rows={3}
              maxLength={500}
              placeholder={t('team.positions.hiring.form.qualPlaceholder')}
            />
          </Form.Item>
          <Form.Item name="status" label={t('common.status')} rules={[{ required: true, message: t('team.positions.hiring.form.statusRequired') }]}>
            <Select options={HIRING_STATUSES.map((s) => ({ value: s, label: et.hiringStatus(s) }))} />
          </Form.Item>
          <Form.Item name="progress_note" label={t('team.positions.hiring.col.progressNote')}>
            <Input.TextArea rows={2} maxLength={500} placeholder={t('team.positions.hiring.form.progressPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

// ---------------- 页面 ----------------

/** 岗位编制复合页：岗位定义 | 招聘需求 */
export default function Positions() {
  const t = useT();
  return (
    <PermTabs
      tabs={[
        { key: 'definition', label: t('team.positions.def.title'), modules: ['positions'], children: <PositionsTab /> },
        { key: 'hiring', label: t('team.positions.hiring.title'), modules: ['positions'], children: <HiringTab /> },
      ]}
    />
  );
}
