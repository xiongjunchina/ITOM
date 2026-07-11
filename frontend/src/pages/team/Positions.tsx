import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import PermTabs from '../../components/PermTabs';
import { hasPermission, useAuthStore } from '../../stores/auth';
import type { HiringNeedRow, Position } from '../../api/types';
import { HIRING_STATUSES, HIRING_STATUS_COLORS } from '../../api/types';

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
        message.success('岗位已更新');
      } else {
        await api.post('/positions', values);
        message.success('岗位已创建');
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
    { title: '岗位名称', dataIndex: 'name', width: 200 },
    { title: '职责', dataIndex: 'duties', ellipsis: true },
    { title: '编制数', dataIndex: 'headcount', width: 100 },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => openEdit(record)}>
          编辑
        </Button>
      ),
    },
  ];

  return (
    <Card
      title="岗位定义"
      extra={
        <Space>
          <Input.Search
            placeholder="搜索岗位"
            allowClear
            onSearch={(v) => {
              setPage(1);
              setQ(v);
            }}
            style={{ width: 220 }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建岗位
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
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />
      <Modal
        title={editing ? '编辑岗位' : '新建岗位'}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<PositionForm> form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label="岗位名称" rules={[{ required: true, message: '请输入岗位名称' }]}>
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="duties" label="职责">
            <Input.TextArea rows={3} maxLength={500} />
          </Form.Item>
          <Form.Item name="headcount" label="编制数">
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
  headcount: number;
  status: string;
  progress_note?: string;
}

function HiringTab() {
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
    form.setFieldsValue({ headcount: 1, status: '待招聘' });
    ensurePositions();
    setModalOpen(true);
  };

  const openEdit = (r: HiringNeedRow) => {
    setEditing(r);
    form.resetFields();
    form.setFieldsValue({
      position_id: r.position_id,
      headcount: r.headcount,
      status: r.status,
      progress_note: r.progress_note ?? undefined,
    });
    ensurePositions();
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    // PATCH 需带全字段（position_id/headcount/status/progress_note）
    const payload = {
      position_id: values.position_id,
      headcount: values.headcount,
      status: values.status,
      progress_note: values.progress_note || null,
    };
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/hiring-needs/${editing.id}`, payload);
        message.success('招聘需求已更新');
      } else {
        await api.post('/hiring-needs', payload);
        message.success('招聘需求已创建');
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
    { title: '岗位', dataIndex: 'position_name', width: 200, render: (v) => v || '-' },
    { title: '人数', dataIndex: 'headcount', width: 80 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => <Tag color={HIRING_STATUS_COLORS[v] ?? 'default'}>{v}</Tag>,
    },
    { title: '进度备注', dataIndex: 'progress_note', ellipsis: true, render: (v) => v || '-' },
    ...(canEdit
      ? [
          {
            title: '操作',
            key: 'action',
            width: 90,
            render: (_: unknown, r: HiringNeedRow) => (
              <Button type="link" size="small" onClick={() => openEdit(r)}>
                更新
              </Button>
            ),
          } as ColumnsType<HiringNeedRow>[number],
        ]
      : []),
  ];

  return (
    <Card
      title="招聘需求"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新
          </Button>
          {canCreate && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新增招聘需求
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
        pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
      />

      <Modal
        title={editing ? '更新招聘需求' : '新增招聘需求'}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<HiringFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="position_id" label="岗位" rules={[{ required: true, message: '请选择岗位' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择岗位"
              options={positions.map((p) => ({ value: p.id, label: p.name }))}
            />
          </Form.Item>
          <Form.Item name="headcount" label="招聘人数" rules={[{ required: true, message: '请输入人数' }]}>
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="status" label="状态" rules={[{ required: true, message: '请选择状态' }]}>
            <Select options={HIRING_STATUSES.map((s) => ({ value: s, label: s }))} />
          </Form.Item>
          <Form.Item name="progress_note" label="进度备注">
            <Input.TextArea rows={2} maxLength={500} placeholder="如：已约 3 位候选人下周二面" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

// ---------------- 页面 ----------------

/** 岗位编制复合页：岗位定义 | 招聘需求 */
export default function Positions() {
  return (
    <PermTabs
      tabs={[
        { key: 'definition', label: '岗位定义', modules: ['positions'], children: <PositionsTab /> },
        { key: 'hiring', label: '招聘需求', modules: ['positions'], children: <HiringTab /> },
      ]}
    />
  );
}
