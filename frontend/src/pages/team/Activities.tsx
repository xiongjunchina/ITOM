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
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
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
  const t = useT();
  const et = useEnums();
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
        .getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' })
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
      message.success(t('team.activities.registered'));
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
      title: t('team.activities.col.type'),
      dataIndex: 'activity_type',
      width: 120,
      render: (v: string) => <Tag color={TYPE_COLORS[v] ?? 'default'}>{et.trainingType(v)}</Tag>,
    },
    { title: t('team.activities.col.topic'), dataIndex: 'topic', width: 240, ellipsis: true },
    {
      title: t('team.col.date'),
      dataIndex: 'activity_date',
      width: 110,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD') : '-'),
    },
    { title: t('team.activities.col.host'), dataIndex: 'host_name', width: 110, render: (v) => v || '-' },
    {
      title: t('team.activities.col.participants'),
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
      title: t('team.activities.col.output'),
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
    { title: t('common.remark'), dataIndex: 'remarks', ellipsis: true, render: (v) => v || '-' },
  ];

  return (
    <Card
      title={t('team.activities.title')}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            {t('common.refresh')}
          </Button>
          {canCreate && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              {t('team.activities.register')}
            </Button>
          )}
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('team.activities.pointsHint')}
      />
      <Table<TrainingRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        sticky
        scroll={{ x: 1200 }}
        pagination={{ pageSize: 20, showTotal: (n) => t('team.total', { n }) }}
      />

      <Drawer
        title={t('team.activities.register')}
        width={480}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => setDrawerOpen(false)}>{t('common.cancel')}</Button>
            <Button type="primary" loading={saving} onClick={() => void handleSave()}>
              {t('common.save')}
            </Button>
          </Space>
        }
      >
        <Form<TrainingFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="activity_type" label={t('team.activities.form.type')} rules={[{ required: true, message: t('team.activities.form.typeRequired') }]}>
            <Select options={ACTIVITY_TYPES.map((v) => ({ value: v, label: et.trainingType(v) }))} placeholder={t('team.activities.form.typePlaceholder')} />
          </Form.Item>
          <Form.Item
            name="topic"
            label={t('team.activities.col.topic')}
            rules={[{ required: true, message: t('team.activities.form.topicRequired') }, { min: 2, message: t('team.minChars', { n: 2 }) }]}
          >
            <Input maxLength={200} placeholder={t('team.activities.form.topicPlaceholder')} />
          </Form.Item>
          <Form.Item name="activity_date" label={t('team.activities.form.date')} rules={[{ required: true, message: t('team.activities.form.dateRequired') }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="host_id" label={t('team.activities.form.host')}>
            <Select allowClear showSearch optionFilterProp="label" placeholder={t('team.activities.form.hostPlaceholder')} options={memberOptions} />
          </Form.Item>
          <Form.Item name="participant_ids" label={t('team.activities.col.participants')}>
            <Select
              mode="multiple"
              allowClear
              showSearch
              optionFilterProp="label"
              maxTagCount="responsive"
              placeholder={t('team.activities.form.participantsPlaceholder')}
              options={memberOptions}
            />
          </Form.Item>
          <Form.Item name="output_link" label={t('team.activities.form.output')}>
            <Input maxLength={500} placeholder={t('team.activities.form.outputPlaceholder')} />
          </Form.Item>
          <Form.Item name="remarks" label={t('common.remark')}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Drawer>
    </Card>
  );
}
