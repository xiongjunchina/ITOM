import { useCallback, useEffect, useMemo, useState } from 'react';
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
import { ROLE_LABELS } from '../../api/types';
import type { Member, Role, RoleDef, UserGroup } from '../../api/types';

interface GroupForm {
  code: string;
  name: string;
  description?: string;
  owner_id?: string | null;
  roles?: string[];
}

export default function Groups() {
  const [items, setItems] = useState<UserGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [roleDefs, setRoleDefs] = useState<RoleDef[]>([]);

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
    api
      .getList<RoleDef>('/admin/roles')
      .then((res) => setRoleDefs(res.items))
      .catch(() => undefined);
  }, []);

  /** 组可授予的角色选项（不允许 admin，后端亦会拒绝） */
  const roleOptions = useMemo(
    () =>
      roleDefs
        .filter((r) => r.code !== 'admin')
        .map((r) => ({ value: r.code, label: r.name })),
    [roleDefs],
  );

  const roleName = useMemo(() => {
    const map = new Map<string, string>();
    roleDefs.forEach((r) => map.set(r.code, r.name));
    return map;
  }, [roleDefs]);

  /** 负责人（专业线 TM）候选：人员主数据，"姓名（部门）" */
  const ownerOptions = useMemo(
    () =>
      members.map((m) => ({
        value: m.id,
        label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
      })),
    [members],
  );

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
      owner_id: record.owner_id ?? undefined,
      roles: record.roles ?? [],
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
          owner_id: values.owner_id ?? null,
          roles: values.roles ?? [],
        });
        message.success('用户组已更新');
      } else {
        await api.post('/admin/groups', {
          code: values.code,
          name: values.name,
          description: values.description ?? null,
          owner_id: values.owner_id ?? null,
          roles: values.roles ?? [],
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
    { title: '代码', dataIndex: 'code', width: 140 },
    { title: '名称', dataIndex: 'name', width: 160 },
    {
      title: '负责人',
      dataIndex: 'owner_name',
      width: 110,
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: '授予角色',
      dataIndex: 'roles',
      width: 220,
      render: (roles: string[] | undefined) =>
        (roles ?? []).length === 0 ? (
          '-'
        ) : (
          <>
            {(roles ?? []).map((code) => (
              <Tag key={code} color="geekblue">
                {roleName.get(code) ?? ROLE_LABELS[code as Role] ?? code}
              </Tag>
            ))}
          </>
        ),
    },
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
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="用户组既是派单/协作单位，也是矩阵组织的纵向专业线（资源池）：指定负责人(TM)、配置组授予角色（如开发资源池授予 it_dev），人进组自动继承"
      />
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
          <Form.Item name="owner_id" label="负责人（专业线 TM）">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="从人员主数据中选择"
              options={ownerOptions}
            />
          </Form.Item>
          <Form.Item
            name="roles"
            label="授予角色"
            extra="人进组自动继承这些角色（ServiceNow 式）"
          >
            <Select
              mode="multiple"
              allowClear
              optionFilterProp="label"
              placeholder="可多选（不含系统管理员）"
              options={roleOptions}
            />
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
            label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
          }))}
        />
      </Modal>
    </Card>
  );
}
