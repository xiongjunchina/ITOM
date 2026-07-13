import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Key } from 'react';
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
  Table,
  Tag,
  TreeSelect,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { DEPT_TYPE_COLORS, DEPT_TYPE_LABELS } from '../../api/types';
import type { Department, DeptType } from '../../api/types';
import { buildDeptTree, buildDeptTreeSelectData } from '../../utils/dept';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';

interface DeptForm {
  code: string;
  name: string;
  parent_id?: string | null;
  dept_type: DeptType;
  sort?: number;
}

type DeptRow = Department & { children?: DeptRow[] };

export default function Departments() {
  const t = useT();
  const et = useEnums();
  const DEPT_TYPE_OPTIONS = (Object.keys(DEPT_TYPE_LABELS) as DeptType[]).map((k) => ({
    value: k,
    label: et.deptType(k),
  }));
  const [items, setItems] = useState<Department[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedKeys, setExpandedKeys] = useState<readonly Key[]>([]);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Department | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<DeptForm>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<Department>('/admin/departments');
      setItems(res.items);
      setExpandedKeys(res.items.map((d) => d.id));
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const treeRows = useMemo(
    () =>
      buildDeptTree<DeptRow>(items, (d, children) =>
        children.length > 0 ? { ...d, children } : { ...d },
      ),
    [items],
  );

  const parentTreeData = useMemo(
    () => buildDeptTreeSelectData(items, editing?.id),
    [items, editing],
  );

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: Department) => {
    setEditing(record);
    form.setFieldsValue({
      code: record.code,
      name: record.name,
      parent_id: record.parent_id ?? undefined,
      dept_type: record.dept_type,
      sort: record.sort,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/admin/departments/${editing.id}`, {
          name: values.name,
          parent_id: values.parent_id ?? null,
          dept_type: values.dept_type,
          sort: values.sort ?? 0,
        });
        message.success(t('admin.dept.updated'));
      } else {
        await api.post('/admin/departments', {
          code: values.code,
          name: values.name,
          parent_id: values.parent_id ?? null,
          dept_type: values.dept_type,
          sort: values.sort ?? 0,
        });
        message.success(t('admin.dept.created'));
      }
      setModalOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (record: Department) => {
    try {
      await api.delete(`/admin/departments/${record.id}`);
      message.success(t('admin.dept.deleted'));
      void load();
    } catch {
      // 有人员或下级时后端返回 400 中文错误，已统一提示
    }
  };

  const toggleActive = async (record: Department, checked: boolean) => {
    try {
      await api.patch(`/admin/departments/${record.id}`, { active: checked });
      message.success(checked ? t('admin.common.enabledMsg') : t('admin.common.disabledMsg'));
      setItems((prev) =>
        prev.map((d) => (d.id === record.id ? { ...d, active: checked } : d)),
      );
    } catch {
      // 已统一提示
    }
  };

  const columns: ColumnsType<DeptRow> = [
    { title: t('admin.common.code'), dataIndex: 'code', width: 220 },
    { title: t('admin.common.name'), dataIndex: 'name', width: 200 },
    {
      title: t('admin.common.type'),
      dataIndex: 'dept_type',
      width: 90,
      render: (v: DeptType) => <Tag color={DEPT_TYPE_COLORS[v]}>{et.deptType(v)}</Tag>,
    },
    {
      title: t('admin.common.syncSource'),
      dataIndex: 'external_source',
      width: 100,
      render: (v: string | null | undefined) => v || '-',
    },
    { title: t('admin.common.memberCount'), dataIndex: 'member_count', width: 80, align: 'right' },
    { title: t('admin.common.sort'), dataIndex: 'sort', width: 80, align: 'right' },
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
      width: 140,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => openEdit(record)}>
            {t('common.edit')}
          </Button>
          <Popconfirm title={t('admin.dept.deleteConfirm')} onConfirm={() => void handleDelete(record)}>
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
      title={t('admin.dept.title')}
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          {t('admin.dept.new')}
        </Button>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('admin.dept.alert')}
      />
      <Table<DeptRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={treeRows}
        pagination={false}
        expandable={{
          expandedRowKeys: [...expandedKeys],
          onExpandedRowsChange: (keys) => setExpandedKeys(keys),
        }}
      />

      <Modal
        title={editing ? t('admin.dept.edit') : t('admin.dept.new')}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<DeptForm>
          form={form}
          layout="vertical"
          preserve={false}
          initialValues={{ dept_type: 'it', sort: 0 }}
        >
          <Form.Item
            name="code"
            label={t('admin.common.code')}
            rules={[
              { required: true, message: t('admin.dept.codeRequired') },
              { pattern: /^[a-zA-Z0-9_.-]{2,64}$/, message: t('admin.dept.codePattern') },
            ]}
          >
            <Input maxLength={64} disabled={!!editing} placeholder={t('admin.dept.codePlaceholder')} />
          </Form.Item>
          <Form.Item
            name="name"
            label={t('admin.common.name')}
            rules={[{ required: true, message: t('admin.dept.nameRequired') }]}
          >
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="parent_id" label={t('admin.common.parentDept')}>
            <TreeSelect
              allowClear
              showSearch
              treeDefaultExpandAll
              treeNodeFilterProp="title"
              placeholder={t('admin.dept.parentPlaceholder')}
              treeData={parentTreeData}
            />
          </Form.Item>
          <Space.Compact block>
            <Form.Item
              name="dept_type"
              label={t('admin.common.type')}
              style={{ width: '50%', marginRight: 8 }}
              rules={[{ required: true, message: t('admin.dept.typeRequired') }]}
            >
              <Select options={DEPT_TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item name="sort" label={t('admin.common.sort')} style={{ width: '50%' }}>
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
          </Space.Compact>
        </Form>
      </Modal>
    </Card>
  );
}
