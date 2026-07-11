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

interface DeptForm {
  code: string;
  name: string;
  parent_id?: string | null;
  dept_type: DeptType;
  sort?: number;
}

type DeptRow = Department & { children?: DeptRow[] };

const DEPT_TYPE_OPTIONS = (Object.keys(DEPT_TYPE_LABELS) as DeptType[]).map((k) => ({
  value: k,
  label: DEPT_TYPE_LABELS[k],
}));

export default function Departments() {
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
        message.success('部门已更新');
      } else {
        await api.post('/admin/departments', {
          code: values.code,
          name: values.name,
          parent_id: values.parent_id ?? null,
          dept_type: values.dept_type,
          sort: values.sort ?? 0,
        });
        message.success('部门已创建');
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
      message.success('部门已删除');
      void load();
    } catch {
      // 有人员或下级时后端返回 400 中文错误，已统一提示
    }
  };

  const toggleActive = async (record: Department, checked: boolean) => {
    try {
      await api.patch(`/admin/departments/${record.id}`, { active: checked });
      message.success(checked ? '已启用' : '已停用');
      setItems((prev) =>
        prev.map((d) => (d.id === record.id ? { ...d, active: checked } : d)),
      );
    } catch {
      // 已统一提示
    }
  };

  const columns: ColumnsType<DeptRow> = [
    { title: '编码', dataIndex: 'code', width: 220 },
    { title: '名称', dataIndex: 'name', width: 200 },
    {
      title: '类型',
      dataIndex: 'dept_type',
      width: 90,
      render: (v: DeptType) => <Tag color={DEPT_TYPE_COLORS[v]}>{DEPT_TYPE_LABELS[v]}</Tag>,
    },
    {
      title: '同步来源',
      dataIndex: 'external_source',
      width: 100,
      render: (v: string | null | undefined) => v || '-',
    },
    { title: '人数', dataIndex: 'member_count', width: 80, align: 'right' },
    { title: '排序', dataIndex: 'sort', width: 80, align: 'right' },
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
      width: 140,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除该部门？" onConfirm={() => void handleDelete(record)}>
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
      title="部门管理"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建部门
        </Button>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="部门是公司组织架构（一人一部门），仅作数据归属不带权限；上线前可切换为飞书/AD 同步（external_source 显示同步来源，本地维护为空）"
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
        title={editing ? '编辑部门' : '新建部门'}
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
            label="编码"
            rules={[
              { required: true, message: '请输入部门编码' },
              { pattern: /^[a-zA-Z0-9_.-]{2,64}$/, message: '2-64 位字母、数字、下划线、点或中划线' },
            ]}
          >
            <Input maxLength={64} disabled={!!editing} placeholder="如 it.ops" />
          </Form.Item>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入部门名称' }]}
          >
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="parent_id" label="上级部门">
            <TreeSelect
              allowClear
              showSearch
              treeDefaultExpandAll
              treeNodeFilterProp="title"
              placeholder="不选则为顶级部门"
              treeData={parentTreeData}
            />
          </Form.Item>
          <Space.Compact block>
            <Form.Item
              name="dept_type"
              label="类型"
              style={{ width: '50%', marginRight: 8 }}
              rules={[{ required: true, message: '请选择部门类型' }]}
            >
              <Select options={DEPT_TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item name="sort" label="排序" style={{ width: '50%' }}>
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
          </Space.Compact>
        </Form>
      </Modal>
    </Card>
  );
}
