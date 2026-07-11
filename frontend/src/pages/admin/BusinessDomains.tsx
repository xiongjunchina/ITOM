import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Switch,
  Table,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import type { BusinessDomain, Member } from '../../api/types';

interface DomainForm {
  code: string;
  name: string;
  description?: string;
  owner_id?: string | null;
  backup_owner_id?: string | null;
  sort?: number;
}

export default function BusinessDomains() {
  const [items, setItems] = useState<BusinessDomain[]>([]);
  const [loading, setLoading] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<BusinessDomain | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<DomainForm>();

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
    api
      .getList<Member>('/members', { page: 1, page_size: 999 })
      .then((res) => setMembers(res.items))
      .catch(() => undefined);
  }, []);

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

  const openEdit = (record: BusinessDomain) => {
    setEditing(record);
    form.setFieldsValue({
      code: record.code,
      name: record.name,
      description: record.description ?? undefined,
      owner_id: record.owner_id ?? undefined,
      backup_owner_id: record.backup_owner_id ?? undefined,
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
      sort: values.sort ?? 0,
    };
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/admin/business-domains/${editing.id}`, payload);
        message.success('业务域已更新');
      } else {
        await api.post('/admin/business-domains', { code: values.code, ...payload });
        message.success('业务域已创建');
      }
      setModalOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (record: BusinessDomain, checked: boolean) => {
    try {
      await api.patch(`/admin/business-domains/${record.id}`, { active: checked });
      message.success(checked ? '已启用' : '已停用');
      setItems((prev) =>
        prev.map((d) => (d.id === record.id ? { ...d, active: checked } : d)),
      );
    } catch {
      // 已统一提示
    }
  };

  const columns: ColumnsType<BusinessDomain> = [
    { title: '编码', dataIndex: 'code', width: 140 },
    { title: '名称', dataIndex: 'name', width: 180 },
    {
      title: '负责人（BP）',
      dataIndex: 'owner_name',
      width: 140,
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: '备份负责人',
      dataIndex: 'backup_owner_name',
      width: 140,
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: '描述',
      dataIndex: 'description',
      ellipsis: true,
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: '启用',
      dataIndex: 'active',
      width: 100,
      render: (_, record) => (
        <Switch
          checked={record.active}
          checkedChildren="启用"
          unCheckedChildren="停用"
          onChange={(checked) => void toggleActive(record, checked)}
        />
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
      title="业务域"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建业务域
        </Button>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="业务域负责人是数据字段而非角色：it_bp 角色给权限，此处指定某人负责哪条业务线"
      />
      <Table<BusinessDomain>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={false}
      />

      <Modal
        title={editing ? '编辑业务域' : '新建业务域'}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<DomainForm> form={form} layout="vertical" preserve={false} initialValues={{ sort: 0 }}>
          <Form.Item
            name="code"
            label="编码"
            rules={[
              { required: true, message: '请输入业务域编码' },
              { pattern: /^[a-z0-9_-]{2,32}$/, message: '2-32 位小写字母、数字、下划线或中划线' },
            ]}
          >
            <Input maxLength={32} disabled={!!editing} placeholder="如 finance" />
          </Form.Item>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入业务域名称' }]}
          >
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="owner_id" label="负责人（BP）">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="从人员主数据中选择"
              options={ownerOptions}
            />
          </Form.Item>
          <Form.Item name="backup_owner_id" label="备份负责人">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="从人员主数据中选择"
              options={ownerOptions}
            />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={200} />
          </Form.Item>
          <Form.Item name="sort" label="排序">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
