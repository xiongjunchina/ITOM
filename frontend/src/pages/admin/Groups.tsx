import { useCallback, useEffect, useState } from 'react';
import {
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
import type { Member, UserGroup } from '../../api/types';

interface GroupForm {
  code: string;
  name: string;
  description?: string;
}

export default function Groups() {
  const [items, setItems] = useState<UserGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<UserGroup | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<GroupForm>();

  const [memberTarget, setMemberTarget] = useState<UserGroup | null>(null);
  const [memberIds, setMemberIds] = useState<string[]>([]);
  const [savingMembers, setSavingMembers] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<UserGroup>('/admin/groups');
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

  useEffect(() => {
    api
      .getList<Member>('/members', { page: 1, page_size: 999 })
      .then((res) => setMembers(res.items))
      .catch(() => undefined);
  }, []);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: UserGroup) => {
    setEditing(record);
    form.setFieldsValue({
      code: record.code,
      name: record.name,
      description: record.description ?? undefined,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/admin/groups/${editing.id}`, {
          name: values.name,
          description: values.description ?? null,
        });
        message.success('用户组已更新');
      } else {
        await api.post('/admin/groups', {
          code: values.code,
          name: values.name,
          description: values.description ?? null,
        });
        message.success('用户组已创建');
      }
      setModalOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (record: UserGroup) => {
    try {
      await api.delete(`/admin/groups/${record.id}`);
      message.success('用户组已删除');
      void load();
    } catch {
      // 已统一提示（在用被拒的中文错误由后端返回）
    }
  };

  const openMembers = (record: UserGroup) => {
    setMemberTarget(record);
    setMemberIds(record.members.map((m) => m.id));
  };

  const handleSaveMembers = async () => {
    if (!memberTarget) return;
    setSavingMembers(true);
    try {
      await api.put(`/admin/groups/${memberTarget.id}/members`, {
        person_ids: memberIds,
      });
      message.success('组成员已更新');
      setMemberTarget(null);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSavingMembers(false);
    }
  };

  const columns: ColumnsType<UserGroup> = [
    { title: '代码', dataIndex: 'code', width: 160 },
    { title: '名称', dataIndex: 'name', width: 180 },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
    {
      title: '成员',
      dataIndex: 'members',
      render: (list: UserGroup['members']) =>
        list.length === 0 ? (
          '-'
        ) : (
          <>
            {list.map((m) => (
              <Tag key={m.id}>{m.name}</Tag>
            ))}
          </>
        ),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Button type="link" size="small" onClick={() => openMembers(record)}>
            管理成员
          </Button>
          <Popconfirm
            title="确定删除该用户组？"
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
      title="用户组"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建用户组
        </Button>
      }
    >
      <Table<UserGroup>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={false}
      />

      <Modal
        title={editing ? '编辑用户组' : '新建用户组'}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<GroupForm> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="code"
            label="代码"
            rules={[
              { required: true, message: '请输入组代码' },
              {
                pattern: /^[a-z0-9_]{2,32}$/,
                message: '2-32 位小写字母、数字或下划线',
              },
            ]}
          >
            <Input maxLength={32} disabled={!!editing} placeholder="如 dba_team" />
          </Form.Item>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入组名称' }]}
          >
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`管理成员：${memberTarget?.name ?? ''}`}
        open={!!memberTarget}
        onOk={() => void handleSaveMembers()}
        confirmLoading={savingMembers}
        onCancel={() => setMemberTarget(null)}
        destroyOnClose
      >
        <Select
          mode="multiple"
          style={{ width: '100%' }}
          value={memberIds}
          onChange={setMemberIds}
          optionFilterProp="label"
          placeholder="从人员主数据中选择成员"
          options={members.map((m) => ({
            value: m.id,
            label: m.dept ? `${m.name}（${m.dept}）` : m.name,
          }))}
        />
      </Modal>
    </Card>
  );
}
