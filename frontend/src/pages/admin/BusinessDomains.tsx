import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Tag,
  TreeSelect,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import type { BusinessDomain, Department, Member } from '../../api/types';
import { useT } from '../../i18n';
import Table from '../../components/SortableTable';

interface DomainForm {
  code: string;
  name: string;
  description?: string;
  owner_id?: string | null;
  backup_owner_id?: string | null;
  department_ids: string[];
  include_children: boolean;
  sort?: number;
}

export default function BusinessDomains() {
  const t = useT();
  const [items, setItems] = useState<BusinessDomain[]>([]);
  const [loading, setLoading] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<BusinessDomain | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<DomainForm>();

  const [teamTarget, setTeamTarget] = useState<BusinessDomain | null>(null);
  const [teamIds, setTeamIds] = useState<string[]>([]);
  const [savingTeam, setSavingTeam] = useState(false);
  const [departmentTarget, setDepartmentTarget] = useState<BusinessDomain | null>(null);
  const [departmentIds, setDepartmentIds] = useState<string[]>([]);
  const [includeChildren, setIncludeChildren] = useState(true);
  const [savingDepartments, setSavingDepartments] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<BusinessDomain>('/admin/business-domains');
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
    void Promise.all([
      api.getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' }).then((res) => setMembers(res.items)),
      api.getList<Department>('/admin/departments').then((res) => setDepartments(res.items)),
    ]).catch(() => undefined);
  }, []);

  const ownerOptions = useMemo(
    () =>
      members.map((m) => ({
        value: m.id,
        label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
      })),
    [members],
  );
  const departmentTree = useMemo(() => {
    const selectable = departments.filter((d) => d.active && d.dept_type === 'business');
    const ids = new Set(selectable.map((d) => d.id));
    return selectable.map((d) => ({
      id: d.id,
      pId: d.parent_id && ids.has(d.parent_id) ? d.parent_id : null,
      value: d.id,
      title: d.name,
    }));
  }, [departments]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: BusinessDomain) => {
    setEditing(record);
    form.setFieldsValue({
      code: record.code,
      name: record.name,
      description: record.description ?? undefined,
      owner_id: record.owner_id ?? undefined,
      backup_owner_id: record.backup_owner_id ?? undefined,
      department_ids: (record.departments ?? []).map((d) => d.id),
      include_children: (record.departments ?? []).some((d) => d.include_children) || (record.departments ?? []).length === 0,
      sort: record.sort,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    const payload = {
      name: values.name,
      description: values.description ?? null,
      owner_id: values.owner_id ?? null,
      backup_owner_id: values.backup_owner_id ?? null,
      department_ids: values.department_ids ?? [],
      include_children: values.include_children ?? true,
      sort: values.sort ?? 0,
    };
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/admin/business-domains/${editing.id}`, payload);
        message.success(t('admin.domains.updated'));
      } else {
        await api.post('/admin/business-domains', { code: values.code, ...payload });
        message.success(t('admin.domains.created'));
      }
      setModalOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const openTeam = (record: BusinessDomain) => {
    setTeamTarget(record);
    setTeamIds((record.members ?? []).map((m) => m.id));
  };

  const handleSaveTeam = async () => {
    if (!teamTarget) return;
    setSavingTeam(true);
    try {
      await api.put(`/admin/business-domains/${teamTarget.id}/members`, {
        person_ids: teamIds,
      });
      message.success(t('admin.domains.teamUpdated'));
      setTeamTarget(null);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSavingTeam(false);
    }
  };

  const openDepartments = (record: BusinessDomain) => {
    const assigned = record.departments ?? [];
    setDepartmentTarget(record);
    setDepartmentIds(assigned.map((d) => d.id));
    setIncludeChildren(assigned.some((d) => d.include_children) || assigned.length === 0);
  };

  const handleSaveDepartments = async () => {
    if (!departmentTarget) return;
    setSavingDepartments(true);
    try {
      await api.put(`/admin/business-domains/${departmentTarget.id}/departments`, {
        department_ids: departmentIds,
        include_children: includeChildren,
      });
      message.success(t('admin.domains.departmentsUpdated'));
      setDepartmentTarget(null);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSavingDepartments(false);
    }
  };

  const toggleActive = async (record: BusinessDomain, checked: boolean) => {
    try {
      await api.patch(`/admin/business-domains/${record.id}`, { active: checked });
      message.success(checked ? t('admin.common.enabledMsg') : t('admin.common.disabledMsg'));
      setItems((prev) =>
        prev.map((d) => (d.id === record.id ? { ...d, active: checked } : d)),
      );
    } catch {
      // 已统一提示
    }
  };

  const handleDelete = async (record: BusinessDomain) => {
    await api.delete(`/admin/business-domains/${record.id}`);
    message.success(t('admin.domains.deleted'));
    void load();
  };

  const columns: ColumnsType<BusinessDomain> = [
    { title: t('admin.common.code'), dataIndex: 'code', width: 140 },
    { title: t('admin.common.name'), dataIndex: 'name', width: 180 },
    {
      title: t('admin.domains.owner'),
      dataIndex: 'owner_name',
      width: 130,
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: t('admin.domains.backupOwner'),
      dataIndex: 'backup_owner_name',
      width: 120,
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: t('admin.domains.team'),
      dataIndex: 'members',
      render: (list: BusinessDomain['members']) =>
        (list ?? []).length === 0 ? (
          '-'
        ) : (
          <>
            {(list ?? []).map((m) => (
              <Tag key={m.id}>{m.name}</Tag>
            ))}
          </>
        ),
    },
    {
      title: t('admin.domains.departments'),
      dataIndex: 'departments',
      width: 300,
      render: (list: BusinessDomain['departments']) =>
        (list ?? []).length === 0 ? '-' : (list ?? []).map((d) => (
          <Tag key={d.id} color={d.active ? undefined : 'default'}>
            {d.name}{d.include_children ? t('admin.domains.childrenSuffix') : ''}
          </Tag>
        )),
    },
    {
      title: t('admin.common.description'),
      dataIndex: 'description',
      ellipsis: true,
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: t('admin.common.on'),
      dataIndex: 'active',
      width: 100,
      render: (_, record) => (
        <Switch
          checked={record.active}
          checkedChildren={t('admin.common.on')}
          unCheckedChildren={t('admin.common.off')}
          onChange={(checked) => void toggleActive(record, checked)}
        />
      ),
    },
    {
      title: t('common.actions'),
      key: 'action',
      width: 240,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => openEdit(record)}>
            {t('common.edit')}
          </Button>
          <Button type="link" size="small" onClick={() => openTeam(record)}>
            {t('admin.domains.manageTeam')}
          </Button>
          <Button type="link" size="small" onClick={() => openDepartments(record)}>
            {t('admin.domains.manageDepartments')}
          </Button>
          <Popconfirm title={t('admin.domains.deleteConfirm')} onConfirm={() => void handleDelete(record)}>
            <Button type="link" danger size="small" icon={<DeleteOutlined />}>
              {t('common.delete')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title={t('admin.domains.title')}
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          {t('admin.domains.new')}
        </Button>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('admin.domains.alert')}
      />
      <Table<BusinessDomain>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        standardToolbar={{ exportFileName: '业务服务域', searchPlaceholder: '搜索编码、名称、负责人或部门' }}
        pagination={false}
      />

      <Modal
        title={editing ? t('admin.domains.edit') : t('admin.domains.new')}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<DomainForm> form={form} layout="vertical" preserve={false} initialValues={{ sort: 0, department_ids: [], include_children: true }}>
          <Form.Item
            name="code"
            label={t('admin.common.code')}
            rules={[
              { required: true, message: t('admin.domains.codeRequired') },
              { pattern: /^[a-z0-9_-]{2,32}$/, message: t('admin.domains.codePattern') },
            ]}
          >
            <Input maxLength={32} disabled={!!editing} placeholder={t('admin.domains.codePlaceholder')} />
          </Form.Item>
          <Form.Item
            name="name"
            label={t('admin.common.name')}
            rules={[{ required: true, message: t('admin.domains.nameRequired') }]}
          >
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="owner_id" label={t('admin.domains.ownerLabel')}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={t('admin.domains.selectDigitalTeam')}
              options={ownerOptions}
            />
          </Form.Item>
          <Form.Item name="backup_owner_id" label={t('admin.domains.backupOwner')}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={t('admin.domains.selectDigitalTeam')}
              options={ownerOptions}
            />
          </Form.Item>
          <Form.Item name="department_ids" label={t('admin.domains.departments')}>
            <TreeSelect
              treeDataSimpleMode
              treeData={departmentTree}
              treeCheckable
              showCheckedStrategy={TreeSelect.SHOW_PARENT}
              showSearch
              treeNodeFilterProp="title"
              maxTagCount="responsive"
              placeholder={t('admin.domains.selectDepartments')}
              style={{ width: '100%' }}
            />
          </Form.Item>
          <Form.Item name="include_children" label={t('admin.domains.includeChildren')} valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="description" label={t('admin.common.description')}>
            <Input.TextArea rows={2} maxLength={200} />
          </Form.Item>
          <Form.Item name="sort" label={t('admin.common.sort')}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t('admin.domains.teamTitle', { name: teamTarget?.name ?? '' })}
        open={!!teamTarget}
        onOk={() => void handleSaveTeam()}
        confirmLoading={savingTeam}
        onCancel={() => setTeamTarget(null)}
        destroyOnClose
      >
        <Select
          mode="multiple"
          style={{ width: '100%' }}
          value={teamIds}
          onChange={setTeamIds}
          optionFilterProp="label"
          placeholder={t('admin.domains.selectTeam')}
          options={members.map((m) => ({
            value: m.id,
            label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
          }))}
        />
      </Modal>

      <Modal
        title={t('admin.domains.departmentsTitle', { name: departmentTarget?.name ?? '' })}
        open={!!departmentTarget}
        onOk={() => void handleSaveDepartments()}
        confirmLoading={savingDepartments}
        onCancel={() => setDepartmentTarget(null)}
        destroyOnClose
      >
        <Alert type="info" showIcon message={t('admin.domains.departmentsHint')} style={{ marginBottom: 16 }} />
        <TreeSelect
          treeDataSimpleMode
          treeData={departmentTree}
          treeCheckable
          showCheckedStrategy={TreeSelect.SHOW_PARENT}
          value={departmentIds}
          onChange={setDepartmentIds}
          showSearch
          treeNodeFilterProp="title"
          maxTagCount="responsive"
          placeholder={t('admin.domains.selectDepartments')}
          style={{ width: '100%', marginBottom: 20 }}
        />
        <Space style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>{t('admin.domains.includeChildren')}</span>
          <Switch checked={includeChildren} onChange={setIncludeChildren} />
        </Space>
      </Modal>
    </Card>
  );
}
