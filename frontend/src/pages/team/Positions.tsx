import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Form, Input, InputNumber, Modal, Space, Table, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import type { Position } from '../../api/types';

interface PositionForm {
  name: string;
  duties?: string;
  headcount?: number;
}

export default function Positions() {
  const [items, setItems] = useState<Position[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Position | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<PositionForm>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<Position>('/positions', {
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

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: Position) => {
    setEditing(record);
    form.setFieldsValue({
      name: record.name,
      duties: record.duties ?? undefined,
      headcount: record.headcount ?? undefined,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/positions/${editing.id}`, values);
        message.success('岗位已更新');
      } else {
        await api.post('/positions', values);
        message.success('岗位已创建');
      }
      setModalOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<Position> = [
    { title: '岗位名称', dataIndex: 'name', width: 200 },
    { title: '职责', dataIndex: 'duties', ellipsis: true },
    { title: '编制数', dataIndex: 'headcount', width: 100 },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => openEdit(record)}>
          编辑
        </Button>
      ),
    },
  ];

  return (
    <Card
      title="岗位编制"
      extra={
        <Space>
          <Input.Search
            placeholder="搜索岗位"
            allowClear
            onSearch={(v) => {
              setPage(1);
              setQ(v);
            }}
            style={{ width: 220 }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建岗位
          </Button>
        </Space>
      }
    >
      <Table<Position>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />
      <Modal
        title={editing ? '编辑岗位' : '新建岗位'}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<PositionForm> form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label="岗位名称" rules={[{ required: true, message: '请输入岗位名称' }]}>
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="duties" label="职责">
            <Input.TextArea rows={3} maxLength={500} />
          </Form.Item>
          <Form.Item name="headcount" label="编制数">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
