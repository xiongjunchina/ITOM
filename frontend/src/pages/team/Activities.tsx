import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Drawer,
  Form,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { hasPermission, useAuthStore } from '../../stores/auth';
import type { Member, TrainingRow } from '../../api/types';

const ACTIVITY_TYPES = ['内部交叉培训', '外部技术交流', '新技术研究'] as const;

const TYPE_COLORS: Record<string, string> = {
  内部交叉培训: 'blue',
  外部技术交流: 'purple',
  新技术研究: 'cyan',
};

interface TrainingFormValues {
  activity_type: string;
  topic: string;
  activity_date: Dayjs;
  host_id?: string;
  participant_ids?: string[];
  output_link?: string;
  remarks?: string;
}

/** 培训发展：内部交叉培训 / 外部技术交流 / 新技术研究 登记（登记即自动计分） */
export default function Activities() {
  const user = useAuthStore((s) => s.user);
  const canCreate = user?.permissions ? hasPermission(user, 'activities', 'create') : true;

  const [items, setItems] = useState<TrainingRow[]>([]);
  const [loading, setLoading] = useState(false);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<TrainingFormValues>();
  const [members, setMembers] = useState<Member[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<TrainingRow>('/trainings');
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

  const openCreate = () => {
    form.resetFields();
    setDrawerOpen(true);
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 999 })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      await api.post('/trainings', {
        activity_type: values.activity_type,
        topic: values.topic,
        activity_date: values.activity_date.format('YYYY-MM-DD'),
        host_id: values.host_id ?? null,
        participant_ids: values.participant_ids ?? [],
        output_link: values.output_link || null,
        remarks: values.remarks || null,
      });
      message.success('活动已登记，主讲与参与人已自动计分');
      setDrawerOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const memberOptions = members.map((m) => ({
    value: m.id,
    label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
  }));

  const columns: ColumnsType<TrainingRow> = [
    {
      title: '类型',
      dataIndex: 'activity_type',
      width: 120,
      render: (v: string) => <Tag color={TYPE_COLORS[v] ?? 'default'}>{v}</Tag>,
    },
    { title: '主题', dataIndex: 'topic', width: 240, ellipsis: true },
    {
      title: '日期',
      dataIndex: 'activity_date',
      width: 110,
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD') : '-'),
    },
    { title: '主讲/组织', dataIndex: 'host_name', width: 110, render: (v) => v || '-' },
    {
      title: '参与人',
      dataIndex: 'participant_names',
      width: 240,
      render: (names: string[]) =>
        names.length > 0 ? (
          <Space size={4} wrap>
            {names.map((n, i) => (
              <Tag key={`${n}-${i}`}>{n}</Tag>
            ))}
          </Space>
        ) : (
          '-'
        ),
    },
    {
      title: '产出链接',
      dataIndex: 'output_link',
      width: 180,
      ellipsis: true,
      render: (v: string | null) =>
        v ? (
          <Typography.Link href={v} target="_blank" rel="noreferrer">
            {v}
          </Typography.Link>
        ) : (
          '-'
        ),
    },
    { title: '备注', dataIndex: 'remarks', ellipsis: true, render: (v) => v || '-' },
  ];

  return (
    <Card
      title="培训发展"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新
          </Button>
          {canCreate && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              登记活动
            </Button>
          )}
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="登记后自动计分：主讲 +15 / 参与 +3（实际分值以「活动积分 → 积分规则」页配置为准）。"
      />
      <Table<TrainingRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1200 }}
        pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
      />

      <Drawer
        title="登记活动"
        width={480}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => setDrawerOpen(false)}>取消</Button>
            <Button type="primary" loading={saving} onClick={() => void handleSave()}>
              保存
            </Button>
          </Space>
        }
      >
        <Form<TrainingFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="activity_type" label="活动类型" rules={[{ required: true, message: '请选择活动类型' }]}>
            <Select options={ACTIVITY_TYPES.map((t) => ({ value: t, label: t }))} placeholder="选择类型" />
          </Form.Item>
          <Form.Item
            name="topic"
            label="主题"
            rules={[{ required: true, message: '请输入主题' }, { min: 2, message: '至少 2 个字符' }]}
          >
            <Input maxLength={200} placeholder="如：K8s 故障排查实战分享" />
          </Form.Item>
          <Form.Item name="activity_date" label="活动日期" rules={[{ required: true, message: '请选择日期' }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="host_id" label="主讲/组织人">
            <Select allowClear showSearch optionFilterProp="label" placeholder="选择主讲人" options={memberOptions} />
          </Form.Item>
          <Form.Item name="participant_ids" label="参与人">
            <Select
              mode="multiple"
              allowClear
              showSearch
              optionFilterProp="label"
              maxTagCount="responsive"
              placeholder="选择参与人员（可多选）"
              options={memberOptions}
            />
          </Form.Item>
          <Form.Item name="output_link" label="产出链接">
            <Input maxLength={500} placeholder="课件/纪要/知识库文章链接" />
          </Form.Item>
          <Form.Item name="remarks" label="备注">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Drawer>
    </Card>
  );
}
