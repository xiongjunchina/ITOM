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
import type { Member, RoleDef, UserGroup } from '../../api/types';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';

interface GroupForm {
  code: string;
  name: string;
  description?: string;
  owner_id?: string | null;
  roles?: string[];
}

export default function Groups() {
  const t = useT();
  const et = useEnums();
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
        message.success(t('admin.groups.updated'));
      } else {
        await api.post('/admin/groups', {
          code: values.code,
          name: values.name,
          description: values.description ?? null,
          owner_id: values.owner_id ?? null,
          roles: values.roles ?? [],
        });
        message.success(t('admin.groups.created'));
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
      message.success(t('admin.groups.deleted'));
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
      message.success(t('admin.groups.membersUpdated'));
      setMemberTarget(null);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSavingMembers(false);
    }
  };

  const columns: ColumnsType<UserGroup> = [
    { title: t('admin.common.codeShort'), dataIndex: 'code', width: 140 },
    { title: t('admin.common.name'), dataIndex: 'name', width: 160 },
    {
      title: t('admin.groups.owner'),
      dataIndex: 'owner_name',
      width: 110,
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: t('admin.groups.grantedRoles'),
      dataIndex: 'roles',
      width: 220,
      render: (roles: string[] | undefined) =>
        (roles ?? []).length === 0 ? (
          '-'
        ) : (
          <>
            {(roles ?? []).map((code) => (
              <Tag key={code} color="geekblue">
                {roleName.get(code) ?? et.role(code) ?? code}
              </Tag>
            ))}
          </>
        ),
    },
    { title: t('admin.common.description'), dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
    {
      title: t('admin.groups.members'),
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
      title: t('common.actions'),
      key: 'action',
      width: 200,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => openEdit(record)}>
            {t('common.edit')}
          </Button>
          <Button type="link" size="small" onClick={() => openMembers(record)}>
            {t('admin.groups.manageMembers')}
          </Button>
          <Popconfirm
            title={t('admin.groups.deleteConfirm')}
            onConfirm={() => void handleDelete(record)}
          >
            <Button type="link" size="small" danger>
              {t('common.delete')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title={t('admin.groups.title')}
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          {t('admin.groups.new')}
        </Button>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('admin.groups.alert')}
      />
      <Table<UserGroup>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={false}
      />

      <Modal
        title={editing ? t('admin.groups.edit') : t('admin.groups.new')}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<GroupForm> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="code"
            label={t('admin.common.codeShort')}
            rules={[
              { required: true, message: t('admin.groups.codeRequired') },
              {
                pattern: /^[a-z0-9_]{2,32}$/,
                message: t('admin.common.codePattern232'),
              },
            ]}
          >
            <Input maxLength={32} disabled={!!editing} placeholder={t('admin.groups.codePlaceholder')} />
          </Form.Item>
          <Form.Item
            name="name"
            label={t('admin.common.name')}
            rules={[{ required: true, message: t('admin.groups.nameRequired') }]}
          >
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="owner_id" label={t('admin.groups.ownerLabel')}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={t('admin.common.selectFromPeople')}
              options={ownerOptions}
            />
          </Form.Item>
          <Form.Item
            name="roles"
            label={t('admin.groups.grantedRoles')}
            extra={t('admin.groups.rolesExtra')}
          >
            <Select
              mode="multiple"
              allowClear
              optionFilterProp="label"
              placeholder={t('admin.groups.rolesPlaceholder')}
              options={roleOptions}
            />
          </Form.Item>
          <Form.Item name="description" label={t('admin.common.description')}>
            <Input.TextArea rows={2} maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t('admin.groups.manageMembersTitle', { name: memberTarget?.name ?? '' })}
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
          placeholder={t('admin.groups.selectMembers')}
          options={members.map((m) => ({
            value: m.id,
            label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
          }))}
        />
      </Modal>
    </Card>
  );
}
