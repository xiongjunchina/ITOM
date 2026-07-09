import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import { ALL_ROLES, ROLE_LABELS } from '../../api/types';
import type { AdminUser, Member, Role } from '../../api/types';

interface UserForm {
  username: string;
  password?: string;
  roles: Role[];
  person_id?: number | null;
}

const ROLE_OPTIONS = ALL_ROLES.map((r) => ({ value: r, label: ROLE_LABELS[r] }));

export default function Users() {
  const [items, setItems] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<UserForm>();

  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
  const [resetForm] = Form.useForm<{ password: string }>();
  const [resetting, setResetting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<AdminUser>('/admin/users', {
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
      .getList<Member>('/members', { page: 1, page_size: 999 })
      .then((res) => setMembers(res.items))
      .catch(() => undefined);
  }, []);

  const memberName = useMemo(() => {
    const map = new Map<number, string>();
    members.forEach((m) => map.set(m.id, m.name));
    return map;
  }, [members]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: AdminUser) => {
    setEditing(record);
    form.setFieldsValue({
      username: record.username,
      roles: record.roles,
      person_id: record.person_id ?? undefined,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/admin/users/${editing.id}`, {
          username: values.username,
          roles: values.roles,
          person_id: values.person_id ?? null,
        });
        message.success('用户已更新');
      } else {
        await api.post('/admin/users', { ...values, person_id: values.person_id ?? null });
        message.success('用户已创建');
      }
      setModalOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (record: AdminUser, checked: boolean) => {
    try {
      await api.patch(`/admin/users/${record.id}`, { is_active: checked });
      message.success(checked ? '已启用' : '已禁用');
      setItems((prev) =>
        prev.map((u) => (u.id === record.id ? { ...u, is_active: checked } : u)),
      );
    } catch {
      // 已统一提示
    }
  };

  const handleReset = async () => {
    if (!resetTarget) return;
    const { password } = await resetForm.validateFields();
    setResetting(true);
    try {
      await api.patch(`/admin/users/${resetTarget.id}`, { password });
      message.success('密码已重置');
      setResetTarget(null);
    } catch {
      // 已统一提示
    } finally {
      setResetting(false);
    }
  };

  const columns: ColumnsType<AdminUser> = [
    { title: '用户名', dataIndex: 'username', width: 160 },
    {
      title: '角色',
      dataIndex: 'roles',
      render: (roles: Role[]) => (
        <>
          {(roles ?? []).map((r) => (
            <Tag key={r} color="blue">
              {ROLE_LABELS[r] ?? r}
            </Tag>
          ))}
        </>
      ),
    },
    {
      title: '关联人员',
      dataIndex: 'person_id',
      width: 140,
      render: (id: number | null) => (id != null ? memberName.get(id) ?? `#${id}` : '-'),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 100,
      render: (_, record) => (
        <Switch
          checked={record.is_active}
          checkedChildren="启用"
          unCheckedChildren="禁用"
          onChange={(checked) => void toggleActive(record, checked)}
        />
      ),
    },
    {
      title: '最后登录',
      dataIndex: 'last_login_at',
      width: 170,
      render: (v: string | null | undefined) =>
        v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            onClick={() => {
              resetForm.resetFields();
              setResetTarget(record);
            }}
          >
            重置密码
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="用户管理"
      extra={
        <Space>
          <Input.Search
            placeholder="搜索用户名"
            allowClear
            onSearch={(v) => {
              setPage(1);
              setQ(v);
            }}
            style={{ width: 220 }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建用户
          </Button>
        </Space>
      }
    >
      <Table<AdminUser>
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
        title={editing ? '编辑用户' : '新建用户'}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<UserForm> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input maxLength={50} autoComplete="off" />
          </Form.Item>
          {!editing && (
            <Form.Item
              name="password"
              label="初始密码"
              rules={[{ required: true, message: '请输入初始密码' }]}
            >
              <Input.Password maxLength={64} autoComplete="new-password" />
            </Form.Item>
          )}
          <Form.Item
            name="roles"
            label="角色"
            rules={[{ required: true, message: '请选择至少一个角色' }]}
          >
            <Select mode="multiple" options={ROLE_OPTIONS} placeholder="可多选" />
          </Form.Item>
          <Form.Item name="person_id" label="关联人员">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="从人员主数据中选择"
              options={members.map((m) => ({ value: m.id, label: m.name }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`重置密码：${resetTarget?.username ?? ''}`}
        open={!!resetTarget}
        onOk={() => void handleReset()}
        confirmLoading={resetting}
        onCancel={() => setResetTarget(null)}
        destroyOnClose
      >
        <Form form={resetForm} layout="vertical" preserve={false}>
          <Form.Item
            name="password"
            label="新密码"
            rules={[{ required: true, message: '请输入新密码' }]}
          >
            <Input.Password maxLength={64} autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
