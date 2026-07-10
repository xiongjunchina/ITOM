import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { ALL_ROLES, ROLE_LABELS } from '../../api/types';
import type { Role, RoleDef } from '../../api/types';

interface RoleForm {
  code: string;
  name: string;
  base_role: Role;
  description?: string;
}

/** 可继承的内置角色：排除 admin */
const BASE_ROLE_OPTIONS = ALL_ROLES.filter((r) => r !== 'admin').map((r) => ({
  value: r,
  label: ROLE_LABELS[r],
}));

export default function Roles() {
  const [items, setItems] = useState<RoleDef[]>([]);
  const [loading, setLoading] = useState(false);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<RoleDef | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<RoleForm>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<RoleDef>('/admin/roles');
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

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: RoleDef) => {
    setEditing(record);
    form.setFieldsValue({
      code: record.code,
      name: record.name,
      base_role: (record.base_role ?? undefined) as Role,
      description: record.description ?? undefined,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/admin/roles/${editing.id}`, {
          name: values.name,
          base_role: values.base_role,
          description: values.description ?? null,
        });
        message.success('角色已更新');
      } else {
        await api.post('/admin/roles', {
          code: values.code,
          name: values.name,
          base_role: values.base_role,
          description: values.description ?? null,
        });
        message.success('角色已创建');
      }
      setModalOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (record: RoleDef) => {
    try {
      await api.delete(`/admin/roles/${record.id}`);
      message.success('角色已删除');
      void load();
    } catch {
      // 已统一提示（内置/在用角色的中文错误由后端返回）
    }
  };

  const columns: ColumnsType<RoleDef> = [
    { title: '代码', dataIndex: 'code', width: 160 },
    { title: '名称', dataIndex: 'name', width: 160 },
    {
      title: '类型',
      dataIndex: 'is_builtin',
      width: 100,
      render: (v: boolean) =>
        v ? <Tag color="blue">内置</Tag> : <Tag color="green">自定义</Tag>,
    },
    {
      title: '继承自',
      dataIndex: 'base_role',
      width: 160,
      render: (v: Role | null | undefined, record) =>
        record.is_builtin || !v ? '—' : ROLE_LABELS[v] ?? v,
    },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
    { title: '持有用户数', dataIndex: 'user_count', width: 110 },
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_, record) =>
        record.is_builtin ? null : (
          <Space>
            <Button type="link" size="small" onClick={() => openEdit(record)}>
              编辑
            </Button>
            <Popconfirm
              title="确定删除该角色？"
              onConfirm={() => void handleDelete(record)}
            >
              <Button type="link" size="small" danger>
                删除
              </Button>
            </Popconfirm>
          </Space>
        ),
    },
  ];

  return (
    <Card
      title="角色管理"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建角色
        </Button>
      }
    >
      <Table<RoleDef>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={false}
      />

      <Modal
        title={editing ? '编辑角色' : '新建角色'}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="自定义角色将继承所选内置角色的系统权限，并可在状态机与流程配置中被精确引用"
        />
        <Form<RoleForm> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="code"
            label="代码"
            rules={[
              { required: true, message: '请输入角色代码' },
              {
                pattern: /^[a-z0-9_]{2,32}$/,
                message: '2-32 位小写字母、数字或下划线',
              },
            ]}
          >
            <Input maxLength={32} disabled={!!editing} placeholder="如 db_admin" />
          </Form.Item>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入角色名称' }]}
          >
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item
            name="base_role"
            label="继承自（内置角色）"
            rules={[{ required: true, message: '请选择要继承的内置角色' }]}
          >
            <Select options={BASE_ROLE_OPTIONS} placeholder="选择内置角色" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
