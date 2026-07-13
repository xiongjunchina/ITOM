import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Tooltip, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
import PermTabs from '../../components/PermTabs';
import { hasPermission, useAuthStore } from '../../stores/auth';
import type { HiringNeedRow, Position } from '../../api/types';
import { HIRING_LEVELS, HIRING_LEVEL_COLORS, HIRING_STATUSES, HIRING_STATUS_COLORS } from '../../api/types';

/** 写权限：优先权限矩阵；存量会话缺失 permissions 时放行（后端仍会校验并中文提示） */
function usePositionsPerm(action: 'create' | 'edit'): boolean {
  const user = useAuthStore((s) => s.user);
  return user?.permissions ? hasPermission(user, 'positions', action) : true;
}

// ---------------- Tab 1：岗位定义 ----------------

interface PositionForm {
  name: string;
  duties?: string;
  headcount?: number;
}

function PositionsTab() {
  const t = useT();
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

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: Position) => {
    setEditing(record);
    form.setFieldsValue({
      name: record.name,
      duties: record.duties ?? undefined,
      headcount: record.headcount ?? undefined,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/positions/${editing.id}`, values);
        message.success(t('team.positions.def.updated'));
      } else {
        await api.post('/positions', values);
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
    { title: t('team.positions.col.name'), dataIndex: 'name', width: 200 },
    { title: t('team.positions.col.duties'), dataIndex: 'duties', ellipsis: true },
    { title: t('team.positions.col.headcount'), dataIndex: 'headcount', width: 100 },
    {
      title: t('common.actions'),
      key: 'action',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => openEdit(record)}>
          {t('common.edit')}
        </Button>
      ),
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
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            {t('team.positions.def.create')}
          </Button>
        </Space>
      }
    >
      <Table<Position>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
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
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<PositionForm> form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label={t('team.positions.col.name')} rules={[{ required: true, message: t('team.positions.form.nameRequired') }]}>
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="duties" label={t('team.positions.col.duties')}>
            <Input.TextArea rows={3} maxLength={500} />
          </Form.Item>
          <Form.Item name="headcount" label={t('team.positions.col.headcount')}>
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

  const [items, setItems] = useState<HiringNeedRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [positions, setPositions] = useState<Position[]>([]);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<HiringNeedRow | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<HiringFormValues>();

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

  const ensurePositions = () => {
    if (positions.length === 0) {
      api
        .getList<Position>('/positions', { page: 1, page_size: 999 })
        .then((res) => setPositions(res.items))
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

  const openEdit = (r: HiringNeedRow) => {
    setEditing(r);
    form.resetFields();
    form.setFieldsValue({
      position_id: r.position_id,
      level: r.level || '中级',
      headcount: r.headcount,
      qualification: r.qualification ?? undefined,
      status: r.status,
      progress_note: r.progress_note ?? undefined,
    });
    ensurePositions();
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
    { title: t('team.positions.hiring.col.position'), dataIndex: 'position_name', width: 180, render: (v) => v || '-' },
    {
      title: t('team.positions.hiring.col.level'),
      dataIndex: 'level',
      width: 80,
      render: (v: string) => <Tag color={HIRING_LEVEL_COLORS[v] ?? 'default'}>{et.hiringLevel(v || '中级')}</Tag>,
    },
    { title: t('team.positions.hiring.col.headcount'), dataIndex: 'headcount', width: 70 },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 100,
      render: (v: string) => <Tag color={HIRING_STATUS_COLORS[v] ?? 'default'}>{et.hiringStatus(v)}</Tag>,
    },
    {
      title: t('team.positions.hiring.col.qualification'),
      dataIndex: 'qualification',
      ellipsis: { showTitle: false },
      render: (v: string | null) =>
        v ? (
          <Tooltip placement="topLeft" title={v}>
            {v}
          </Tooltip>
        ) : (
          '-'
        ),
    },
    { title: t('team.positions.hiring.col.progressNote'), dataIndex: 'progress_note', ellipsis: true, render: (v) => v || '-' },
    ...(canEdit
      ? [
          {
            title: t('common.actions'),
            key: 'action',
            width: 90,
            render: (_: unknown, r: HiringNeedRow) => (
              <Button type="link" size="small" onClick={() => openEdit(r)}>
                {t('team.positions.hiring.update')}
              </Button>
            ),
          } as ColumnsType<HiringNeedRow>[number],
        ]
      : []),
  ];

  return (
    <Card
      title={t('team.positions.hiring.title')}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            {t('common.refresh')}
          </Button>
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
        pagination={{ pageSize: 20, showTotal: (n) => t('team.total', { n }) }}
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
