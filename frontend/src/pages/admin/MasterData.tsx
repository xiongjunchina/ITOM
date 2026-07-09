import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Menu,
  Modal,
  Row,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import type { MasterDataItem } from '../../api/types';

interface ItemForm {
  category: string;
  code: string;
  name: string;
  sort?: number;
  active: boolean;
}

export default function MasterData() {
  const [items, setItems] = useState<MasterDataItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [category, setCategory] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<MasterDataItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<ItemForm>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // 不带 category 拉全量，用于左侧类目去重
      const res = await api.getList<MasterDataItem>('/admin/master-data', {
        page: 1,
        page_size: 999,
      });
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

  const categories = useMemo(
    () => Array.from(new Set(items.map((i) => i.category))).sort(),
    [items],
  );

  const activeCategory = category ?? categories[0] ?? null;
  const rows = useMemo(
    () =>
      items
        .filter((i) => i.category === activeCategory)
        .sort((a, b) => (a.sort ?? 0) - (b.sort ?? 0)),
    [items, activeCategory],
  );

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ category: activeCategory ?? '', active: true });
    setModalOpen(true);
  };

  const openEdit = (record: MasterDataItem) => {
    setEditing(record);
    form.setFieldsValue({
      category: record.category,
      code: record.code,
      name: record.name,
      sort: record.sort ?? undefined,
      active: record.active,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/admin/master-data/${editing.id}`, values);
        message.success('条目已更新');
      } else {
        await api.post('/admin/master-data', values);
        message.success('条目已创建');
      }
      setModalOpen(false);
      setCategory(values.category);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<MasterDataItem> = [
    { title: '编码', dataIndex: 'code', width: 160 },
    { title: '名称', dataIndex: 'name' },
    { title: '排序', dataIndex: 'sort', width: 80 },
    {
      title: '状态',
      dataIndex: 'active',
      width: 90,
      render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
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
      title="数据字典"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建条目
        </Button>
      }
    >
      <Row gutter={16}>
        <Col xs={24} sm={6} md={5}>
          <Menu
            mode="inline"
            style={{ borderInlineEnd: 'none' }}
            selectedKeys={activeCategory ? [activeCategory] : []}
            items={categories.map((c) => ({ key: c, label: c }))}
            onClick={({ key }) => setCategory(key)}
          />
        </Col>
        <Col xs={24} sm={18} md={19}>
          <Table<MasterDataItem>
            rowKey="id"
            loading={loading}
            columns={columns}
            dataSource={rows}
            pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
          />
        </Col>
      </Row>

      <Modal
        title={editing ? '编辑条目' : '新建条目'}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<ItemForm> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="category"
            label="类目"
            rules={[{ required: true, message: '请输入类目' }]}
            extra="输入新类目名称即可创建新类目"
          >
            <Input maxLength={50} disabled={!!editing} />
          </Form.Item>
          <Space.Compact block>
            <Form.Item
              name="code"
              label="编码"
              style={{ width: '50%', marginRight: 8 }}
              rules={[{ required: true, message: '请输入编码' }]}
            >
              <Input maxLength={50} />
            </Form.Item>
            <Form.Item
              name="name"
              label="名称"
              style={{ width: '50%' }}
              rules={[{ required: true, message: '请输入名称' }]}
            >
              <Input maxLength={50} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="sort" label="排序">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="active" label="启用" valuePropName="checked" initialValue={true}>
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
