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
import { ALL_ROLES } from '../../api/types';
import type { Role, RoleDef } from '../../api/types';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';

interface RoleForm {
  code: string;
  name: string;
  base_role?: Role;
  description?: string;
}

export default function Roles() {
  const t = useT();
  const et = useEnums();
  /** 可作为权限模板的内置角色：排除 admin（隐式全权，无矩阵可复制） */
  const BASE_ROLE_OPTIONS = ALL_ROLES.filter((r) => r !== 'admin').map((r) => ({
    value: r,
    label: et.role(r),
  }));
  const [items, setItems] = useState<RoleDef[]>([]);
  const [loading, setLoading] = useState(false);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<RoleDef | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<RoleForm>();

  const editingBuiltin = !!editing?.is_builtin;

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
        // 内置角色仅可改名称/描述（携带 base_role 会被后端 BUILTIN_ROLE 拒绝）
        const payload: Record<string, unknown> = {
          name: values.name,
          description: values.description ?? null,
        };
        if (!editing.is_builtin) payload.base_role = values.base_role;
        await api.patch(`/admin/roles/${editing.id}`, payload);
        message.success(t('admin.roles.updated'));
      } else {
        await api.post('/admin/roles', {
          code: values.code,
          name: values.name,
          base_role: values.base_role,
          description: values.description ?? null,
        });
        message.success(t('admin.roles.created'));
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
      message.success(t('admin.roles.deleted'));
      void load();
    } catch {
      // 已统一提示（内置/在用角色的中文错误由后端返回）
    }
  };

  const columns: ColumnsType<RoleDef> = [
    { title: t('admin.common.codeShort'), dataIndex: 'code', width: 160 },
    { title: t('admin.common.name'), dataIndex: 'name', width: 160 },
    {
      title: t('admin.common.type'),
      dataIndex: 'is_builtin',
      width: 100,
      render: (v: boolean) =>
        v ? <Tag color="blue">{t('admin.roles.builtin')}</Tag> : <Tag color="green">{t('admin.roles.custom')}</Tag>,
    },
    {
      title: t('admin.roles.permTemplate'),
      dataIndex: 'base_role',
      width: 160,
      render: (v: Role | null | undefined, record) =>
        record.is_builtin || !v ? '—' : et.role(v) || v,
    },
    { title: t('admin.common.description'), dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
    { title: t('admin.roles.userCount'), dataIndex: 'user_count', width: 110 },
    {
      title: t('common.actions'),
      key: 'action',
      width: 140,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => openEdit(record)}>
            {t('common.edit')}
          </Button>
          {!record.is_builtin && (
            <Popconfirm
              title={t('admin.roles.deleteConfirm')}
              onConfirm={() => void handleDelete(record)}
            >
              <Button type="link" size="small" danger>
                {t('common.delete')}
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Card
      title={t('admin.roles.title')}
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          {t('admin.roles.new')}
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
        title={editing ? t('admin.roles.edit') : t('admin.roles.new')}
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
          message={
            editingBuiltin
              ? t('admin.roles.alertBuiltin')
              : t('admin.roles.alertCustom')
          }
        />
        <Form<RoleForm> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="code"
            label={t('admin.common.codeShort')}
            rules={[
              { required: true, message: t('admin.roles.codeRequired') },
              {
                pattern: /^[a-z0-9_]{2,32}$/,
                message: t('admin.common.codePattern232'),
              },
            ]}
          >
            <Input maxLength={32} disabled={!!editing} placeholder={t('admin.roles.codePlaceholder')} />
          </Form.Item>
          <Form.Item
            name="name"
            label={t('admin.common.name')}
            rules={[{ required: true, message: t('admin.roles.nameRequired') }]}
          >
            <Input maxLength={50} />
          </Form.Item>
          {editingBuiltin ? (
            <Form.Item label={t('admin.roles.permTemplate')}>
              <Input disabled value={t('admin.roles.permTemplateNone')} />
            </Form.Item>
          ) : (
            <Form.Item
              name="base_role"
              label={t('admin.roles.permTemplateBuiltin')}
              rules={[{ required: true, message: t('admin.roles.permTemplateRequired') }]}
            >
              <Select options={BASE_ROLE_OPTIONS} placeholder={t('admin.roles.selectBuiltin')} />
            </Form.Item>
          )}
          <Form.Item name="description" label={t('admin.common.description')}>
            <Input.TextArea rows={2} maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
