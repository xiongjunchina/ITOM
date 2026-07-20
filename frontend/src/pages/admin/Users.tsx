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
  Popconfirm,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { EyeInvisibleOutlined, EyeOutlined, MailOutlined, PlusOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import type { AdminUser, Member, Role, RoleDef, UserGroup } from '../../api/types';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';

interface UserForm {
  username: string;
  password?: string;
  roles?: Role[];
  person_id?: string | null;
  group_ids?: string[];
}

export default function Users() {
  const t = useT();
  const et = useEnums();
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
  const [revealedPassword, setRevealedPassword] = useState<string | null>(null);
  const [revealing, setRevealing] = useState(false);
  const [sendingPassword, setSendingPassword] = useState(false);

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

  const [roleDefs, setRoleDefs] = useState<RoleDef[]>([]);
  const [groups, setGroups] = useState<UserGroup[]>([]);

  const loadGroups = useCallback(() => {
    api
      .getList<UserGroup>('/admin/groups')
      .then((res) => setGroups(res.items))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    api
      .getList<Member>('/members', { page: 1, page_size: 2000 })
      .then((res) => setMembers(res.items))
      .catch(() => undefined);
    api
      .getList<RoleDef>('/admin/roles')
      .then((res) => setRoleDefs(res.items))
      .catch(() => undefined);
    loadGroups();
  }, [loadGroups]);

  const memberName = useMemo(() => {
    const map = new Map<string, string>();
    members.forEach((m) => map.set(m.id, m.name));
    return map;
  }, [members]);

  /** 人员 → 所属组名列表（由组成员数据反推，用于列表列展示） */
  const personGroups = useMemo(() => {
    const map = new Map<string, string[]>();
    groups.forEach((g) => {
      g.members.forEach((m) => {
        map.set(m.id, [...(map.get(m.id) ?? []), g.name]);
      });
    });
    return map;
  }, [groups]);

  const roleOptions = useMemo(
    () =>
      roleDefs.map((r) => ({
        value: r.code,
        label: r.is_builtin ? r.name : `${r.name}${t('admin.users.customSuffix')}`,
      })),
    [roleDefs],
  );

  const roleName = useMemo(() => {
    const map = new Map<string, string>();
    roleDefs.forEach((r) => map.set(r.code, r.name));
    return map;
  }, [roleDefs]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: AdminUser) => {
    setEditing(record);
    setRevealedPassword(null);
    form.setFieldsValue({
      username: record.username,
      roles: record.roles,
      person_id: record.person_id ?? undefined,
      group_ids: record.person_id
        ? groups.filter((g) => g.members.some((m) => m.id === record.person_id)).map((g) => g.id)
        : [],
    });
    setModalOpen(true);
  };

  const revealInitialPassword = async () => {
    if (!editing) return;
    if (revealedPassword) { setRevealedPassword(null); return; }
    setRevealing(true);
    try { const r = await api.get<{ password: string }>(`/admin/users/${editing.id}/initial-password`); setRevealedPassword(r.password); }
    finally { setRevealing(false); }
  };

  const sendInitialPassword = async () => {
    if (!editing) return;
    setSendingPassword(true);
    try { const r = await api.post<{ sent_to: string }>(`/admin/users/${editing.id}/initial-password/email`); message.success(`初始密码已发送至 ${r.sent_to}`); void load(); }
    finally { setSendingPassword(false); }
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/admin/users/${editing.id}`, {
          username: values.username,
          roles: values.roles ?? [],
          person_id: values.person_id ?? null,
        });
      } else {
        await api.post('/admin/users', {
          username: values.username,
          password: values.password,
          roles: values.roles ?? [],
          person_id: values.person_id ?? null,
        });
      }
      if (values.person_id) {
        await api.put(`/admin/members/${values.person_id}/groups`, {
          group_ids: values.group_ids ?? [],
        });
      }
      message.success(editing ? t('admin.users.updated') : t('admin.users.created'));
      setModalOpen(false);
      loadGroups();
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
      message.success(checked ? t('admin.common.enabledMsg') : t('admin.users.disabledMsg'));
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
      message.success(t('admin.users.passwordReset'));
      setResetTarget(null);
    } catch {
      // 已统一提示
    } finally {
      setResetting(false);
    }
  };

  const columns: ColumnsType<AdminUser> = [
    { title: t('admin.users.username'), dataIndex: 'username', width: 160 },
    {
      title: t('admin.users.role'),
      dataIndex: 'roles',
      render: (roles: Role[]) => (
        <>
          {(roles ?? []).map((r) => (
            <Tag key={r} color="blue">
              {roleName.get(r) ?? et.role(r) ?? r}
            </Tag>
          ))}
        </>
      ),
    },
    {
      title: t('admin.users.linkedPerson'),
      dataIndex: 'person_id',
      width: 140,
      render: (id: string | null) => (id != null ? memberName.get(id) ?? id : "-"),
    },
    {
      title: t('admin.users.authSource'),
      dataIndex: 'auth_source',
      width: 90,
      render: (v: AdminUser['auth_source'] | undefined) =>
        v === 'local' ? t('admin.users.authLocal') : v || '-',
    },
    {
      title: t('admin.users.group'),
      key: 'groups',
      width: 180,
      render: (_, record) =>
        record.person_id && personGroups.get(record.person_id)?.length ? (
          <>
            {personGroups.get(record.person_id)!.map((name) => (
              <Tag key={name} color="purple">
                {name}
              </Tag>
            ))}
          </>
        ) : (
          '-'
        ),
    },
    {
      title: t('common.status'),
      dataIndex: 'is_active',
      width: 100,
      render: (_, record) => (
        <Switch
          checked={record.is_active}
          checkedChildren={t('admin.common.on')}
          unCheckedChildren={t('admin.users.switchOff')}
          onChange={(checked) => void toggleActive(record, checked)}
        />
      ),
    },
    {
      title: t('admin.users.lastLogin'),
      dataIndex: 'last_login_at',
      width: 170,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string | null | undefined) =>
        v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: t('common.actions'),
      key: 'action',
      width: 160,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => openEdit(record)}>
            {t('common.edit')}
          </Button>
          <Button
            type="link"
            size="small"
            onClick={() => {
              resetForm.resetFields();
              setResetTarget(record);
            }}
          >
            {t('admin.users.resetPassword')}
          </Button>
          {record.username !== 'admin' && (
            <Popconfirm
              title={t('admin.users.deleteConfirm')}
              onConfirm={async () => {
                await api.delete(`/admin/users/${record.id}`);
                message.success(t('common.deleted'));
                void load();
              }}
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
      title={t('admin.users.title')}
      extra={
        <Space>
          <Input.Search
            placeholder={t('admin.users.searchPlaceholder')}
            allowClear
            onSearch={(v) => {
              setPage(1);
              setQ(v);
            }}
            style={{ width: 220 }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            {t('admin.users.new')}
          </Button>
        </Space>
      }
    >
      <Table<AdminUser>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        sticky
        scroll={{ x: 'max-content' }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (n) => t('admin.total', { n }),
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />

      <Modal
        title={editing ? t('admin.users.edit') : t('admin.users.new')}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<UserForm> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="username"
            label={t('admin.users.username')}
            rules={[{ required: true, message: t('admin.users.usernameRequired') }]}
          >
            <Input maxLength={50} autoComplete="off" />
          </Form.Item>
          {!editing && (
            <Form.Item
              name="password"
              label={t('admin.users.initialPassword')}
              rules={[{ required: true, message: t('admin.users.initialPasswordRequired') }]}
            >
              <Input.Password maxLength={64} autoComplete="new-password" />
            </Form.Item>
          )}
          <Form.Item
            name="roles"
            label={t('admin.users.role')}
            extra={t('admin.users.roleExtra')}
          >
            <Select
              mode="multiple"
              allowClear
              options={roleOptions}
              placeholder={t('admin.users.rolePlaceholder')}
            />
          </Form.Item>
          <Form.Item name="person_id" label={t('admin.users.linkedPerson')}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={t('admin.common.selectFromPeople')}
              options={members.map((m) => ({
                value: m.id,
                label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
              }))}
            />
          </Form.Item>
          {editing?.initial_password_available && (
            <Form.Item label="初始密码" extra="查看和发送操作都会记录审计日志">
              <Space.Compact style={{ width: '100%' }}>
                <Input readOnly value={revealedPassword ?? '••••••••••••'} />
                <Button
                  aria-label={revealedPassword ? '隐藏初始密码' : '查看初始密码'}
                  icon={revealedPassword ? <EyeOutlined /> : <EyeInvisibleOutlined />}
                  loading={revealing}
                  onClick={() => void revealInitialPassword()}
                />
                <Button icon={<MailOutlined />} loading={sendingPassword} onClick={() => void sendInitialPassword()}>
                  邮件发送
                </Button>
              </Space.Compact>
            </Form.Item>
          )}
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.person_id !== cur.person_id}>
            {({ getFieldValue }) => (
              <Form.Item
                name="group_ids"
                label={t('admin.users.groupLabel')}
                extra={
                  getFieldValue('person_id')
                    ? t('admin.users.groupExtraHas')
                    : t('admin.users.groupExtraNo')
                }
              >
                <Select
                  mode="multiple"
                  allowClear
                  disabled={!getFieldValue('person_id')}
                  placeholder={t('admin.common.selectMultiple')}
                  options={groups.map((g) => ({ value: g.id, label: g.name }))}
                />
              </Form.Item>
            )}
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t('admin.users.resetTitle', { name: resetTarget?.username ?? '' })}
        open={!!resetTarget}
        onOk={() => void handleReset()}
        confirmLoading={resetting}
        onCancel={() => setResetTarget(null)}
        destroyOnClose
      >
        <Form form={resetForm} layout="vertical" preserve={false}>
          <Form.Item
            name="password"
            label={t('admin.users.newPassword')}
            rules={[{ required: true, message: t('admin.users.newPasswordRequired') }]}
          >
            <Input.Password maxLength={64} autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
