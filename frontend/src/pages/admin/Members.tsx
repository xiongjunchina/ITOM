import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import type { Member, Position } from '../../api/types';

interface MemberForm {
  name: string;
  dept?: string;
  team?: string;
  position_id?: string | null;
  status?: '在岗' | '离职';
  hire_date?: Dayjs | null;
  email?: string;
  skills?: string[];
  remarks?: string;
}

export default function Members() {
  const [items, setItems] = useState<Member[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);
  const [positions, setPositions] = useState<Position[]>([]);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Member | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<MemberForm>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<Member>('/members', {
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

  useEffect(() => {
    api
      .getList<Position>('/positions', { page: 1, page_size: 999 })
      .then((res) => setPositions(res.items))
      .catch(() => undefined);
  }, []);

  const positionName = useMemo(() => {
    const map = new Map<string, string>();
    positions.forEach((p) => map.set(p.id, p.name));
    return map;
  }, [positions]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: Member) => {
    setEditing(record);
    form.setFieldsValue({
      name: record.name,
      dept: record.dept ?? undefined,
      team: record.team ?? undefined,
      position_id: record.position_id ?? undefined,
      status: record.status ?? undefined,
      hire_date: record.hire_date ? dayjs(record.hire_date) : undefined,
      email: record.email ?? undefined,
      skills: record.skills ?? undefined,
      remarks: record.remarks ?? undefined,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    const payload = {
      ...values,
      position_id: values.position_id ?? null,
      hire_date: values.hire_date ? values.hire_date.format('YYYY-MM-DD') : null,
    };
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/members/${editing.id}`, payload);
        message.success('人员信息已更新');
      } else {
        await api.post('/members', payload);
        message.success('人员已创建');
      }
      setModalOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<Member> = [
    { title: '姓名', dataIndex: 'name', width: 110 },
    { title: '部门', dataIndex: 'dept', width: 130 },
    { title: '团队', dataIndex: 'team', width: 130 },
    {
      title: '岗位',
      dataIndex: 'position_id',
      width: 130,
      render: (id: string | null) => (id != null ? positionName.get(id) ?? id : '-'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: Member['status']) =>
        v ? <Tag color={v === '在岗' ? 'green' : 'default'}>{v}</Tag> : '-',
    },
    { title: '入职日期', dataIndex: 'hire_date', width: 120 },
    { title: '邮箱', dataIndex: 'email', width: 200, ellipsis: true },
    {
      title: '技能',
      dataIndex: 'skills',
      render: (skills: string[] | null) => (
        <>
          {(skills ?? []).map((s) => (
            <Tag key={s}>{s}</Tag>
          ))}
        </>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => openEdit(record)}>
          编辑
        </Button>
      ),
    },
  ];

  return (
    <Card
      title="人员主数据"
      extra={
        <Space>
          <Input.Search
            placeholder="搜索姓名/部门"
            allowClear
            onSearch={(v) => {
              setPage(1);
              setQ(v);
            }}
            style={{ width: 220 }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建人员
          </Button>
        </Space>
      }
    >
      <Table<Member>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1100 }}
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
        title={editing ? '编辑人员' : '新建人员'}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
        width={560}
      >
        <Form<MemberForm> form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}>
            <Input maxLength={50} />
          </Form.Item>
          <Space.Compact block>
            <Form.Item name="dept" label="部门" style={{ width: '50%', marginRight: 8 }}>
              <Input maxLength={50} />
            </Form.Item>
            <Form.Item name="team" label="团队" style={{ width: '50%' }}>
              <Input maxLength={50} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="position_id" label="岗位">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="从岗位编制中选择"
              options={positions.map((p) => ({ value: p.id, label: p.name }))}
            />
          </Form.Item>
          <Space.Compact block>
            <Form.Item name="status" label="状态" style={{ width: '50%', marginRight: 8 }}>
              <Select
                allowClear
                options={[
                  { value: '在岗', label: '在岗' },
                  { value: '离职', label: '离职' },
                ]}
              />
            </Form.Item>
            <Form.Item name="hire_date" label="入职日期" style={{ width: '50%' }}>
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="email" label="邮箱" rules={[{ type: 'email', message: '邮箱格式不正确' }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="skills" label="技能标签">
            <Select mode="tags" placeholder="输入后回车添加" open={false} suffixIcon={null} />
          </Form.Item>
          <Form.Item name="remarks" label="备注">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
