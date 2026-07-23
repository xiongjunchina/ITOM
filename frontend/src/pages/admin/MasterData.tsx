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
  Tag,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import Table from '../../components/SortableTable';
import type { MasterDataItem } from '../../api/types';

interface ItemForm {
  category: string;
  code: string;
  name: string;
  sort?: number;
  active: boolean;
}

export default function MasterData() {
  const t = useT();
  const [items, setItems] = useState<MasterDataItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [category, setCategory] = useState<string | null>(null);
  const [tablePage, setTablePage] = useState(1);
  const [tablePageSize, setTablePageSize] = useState(20);

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

  useEffect(() => {
    setTablePage(1);
  }, [activeCategory]);

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
        message.success(t('admin.masterData.updated'));
      } else {
        await api.post('/admin/master-data', values);
        message.success(t('admin.masterData.created'));
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
    { title: t('admin.common.code'), dataIndex: 'code', width: 160 },
    { title: t('admin.common.name'), dataIndex: 'name' },
    { title: t('admin.common.sort'), dataIndex: 'sort', width: 80 },
    {
      title: t('common.status'),
      dataIndex: 'active',
      width: 90,
      render: (v: boolean) =>
        v ? <Tag color="green">{t('admin.common.on')}</Tag> : <Tag>{t('admin.common.off')}</Tag>,
    },
    {
      title: t('common.actions'),
      key: 'action',
      width: 90,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => openEdit(record)}>
          {t('common.edit')}
        </Button>
      ),
    },
  ];

  return (
    <Card
      title={t('admin.masterData.title')}
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          {t('admin.masterData.newItem')}
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
            standardToolbar={{ exportFileName: '主数据', searchPlaceholder: '搜索分类、编码、名称或值' }}
            pagination={{
              current: tablePage,
              pageSize: tablePageSize,
              showSizeChanger: true,
              pageSizeOptions: [10, 20, 50, 100],
              showTotal: (n) => t('admin.total', { n }),
              onChange: (page, pageSize) => {
                setTablePage(page);
                setTablePageSize(pageSize);
              },
            }}
          />
        </Col>
      </Row>

      <Modal
        title={editing ? t('admin.masterData.editItem') : t('admin.masterData.newItem')}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<ItemForm> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="category"
            label={t('admin.masterData.category')}
            rules={[{ required: true, message: t('admin.masterData.categoryRequired') }]}
            extra={t('admin.masterData.categoryHint')}
          >
            <Input maxLength={50} disabled={!!editing} />
          </Form.Item>
          <Space.Compact block>
            <Form.Item
              name="code"
              label={t('admin.common.code')}
              style={{ width: '50%', marginRight: 8 }}
              rules={[{ required: true, message: t('admin.masterData.codeRequired') }]}
            >
              <Input maxLength={50} />
            </Form.Item>
            <Form.Item
              name="name"
              label={t('admin.common.name')}
              style={{ width: '50%' }}
              rules={[{ required: true, message: t('admin.masterData.nameRequired') }]}
            >
              <Input maxLength={50} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="sort" label={t('admin.common.sort')}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="active" label={t('admin.common.on')} valuePropName="checked" initialValue={true}>
            <Switch checkedChildren={t('admin.common.on')} unCheckedChildren={t('admin.common.off')} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
