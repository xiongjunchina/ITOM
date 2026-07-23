import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, TrophyOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { useAuthStore } from '../../stores/auth';
import { currentPeriod, periodLabel, recentPeriods } from '../../utils/period';
import type { LearningGrowthGoal } from '../../api/types';

interface GoalFormValues {
  goal: string;
  target_description?: string;
  progress: number;
  evidence?: string;
  note?: string;
}

/** 学习成长目标：员工按周期自填，完成比例自动折算为团队贡献积分。 */
export default function LearningGrowth() {
  const user = useAuthStore((state) => state.user);
  const canTeam = !!user?.roles.some((role) => ['admin', 'cio', 'it_tm'].includes(role));
  const [period, setPeriod] = useState(currentPeriod());
  const [scope, setScope] = useState<'mine' | 'team'>('mine');
  const [items, setItems] = useState<LearningGrowthGoal[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<LearningGrowthGoal | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm<GoalFormValues>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await api.get<LearningGrowthGoal[]>('/team/learning-growth', { period, scope }));
    } catch {
      // 统一错误拦截器已提示
    } finally {
      setLoading(false);
    }
  }, [period, scope]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    form.setFieldsValue({ progress: 0 });
    setModalOpen(true);
  };

  const openEdit = (item: LearningGrowthGoal) => {
    setEditing(item);
    form.setFieldsValue({
      goal: item.goal,
      target_description: item.target_description ?? undefined,
      progress: item.progress,
      evidence: item.evidence ?? undefined,
      note: item.note ?? undefined,
    });
    setModalOpen(true);
  };

  const save = async () => {
    const values = await form.validateFields();
    if (editing) {
      await api.patch(`/team/learning-growth/${editing.id}`, values);
      message.success('学习任务已更新');
    } else {
      await api.post('/team/learning-growth', { ...values, period });
      message.success('学习任务已保存，积分已自动更新');
    }
    setModalOpen(false);
    form.resetFields();
    void load();
  };

  const remove = async (item: LearningGrowthGoal) => {
    await api.delete(`/team/learning-growth/${item.id}`);
    message.success('学习任务已删除，积分已自动回算');
    void load();
  };

  const totalPoints = useMemo(() => items.reduce((sum, item) => sum + item.points, 0), [items]);
  const averageProgress = items.length ? items.reduce((sum, item) => sum + item.progress, 0) / items.length : 0;

  const columns: ColumnsType<LearningGrowthGoal> = [
    ...(scope === 'team' ? [{ title: '人员', dataIndex: 'person_name', width: 110 }] : []),
    { title: '学习任务', dataIndex: 'goal', width: 240, ellipsis: true },
    { title: '目标说明/验收标准', dataIndex: 'target_description', width: 260, ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '完成进度', dataIndex: 'progress', width: 180,
      render: (value: number) => <Progress percent={value} size="small" />,
    },
    { title: '自动积分', dataIndex: 'points', width: 90, render: (value: number) => <Tag color={value > 0 ? 'blue' : 'default'}>{value.toFixed(2)}</Tag> },
    { title: '佐证', dataIndex: 'evidence', width: 240, ellipsis: true, render: (v: string | null) => v || '-' },
    { title: '补充说明', dataIndex: 'note', width: 220, ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '操作', key: 'actions', width: 120, fixed: 'right',
      render: (_, item) => (
        <Space>
          {(scope === 'mine' || canTeam) && <Button type="link" icon={<EditOutlined />} onClick={() => openEdit(item)}>编辑</Button>}
          {(scope === 'mine' || canTeam) && (
            <Popconfirm title="确认删除这条目标吗？" onConfirm={() => void remove(item)}>
              <Button type="link" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card
        title="学习任务"
        extra={(
          <Space>
            <Select value={period} onChange={setPeriod} options={recentPeriods(2).map((p) => ({ value: p, label: periodLabel(p) }))} />
            {canTeam && <Segmented value={scope} onChange={(value) => setScope(value as 'mine' | 'team')} options={[{ label: '我的目标', value: 'mine' }, { label: '团队目标', value: 'team' }]} />}
            <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增目标</Button>
          </Space>
        )}
      >
        <Typography.Paragraph type="secondary">
          填写本考核周期内可验证的学习、认证、技术研究、轮岗或实验任务；完成进度按任务等权平均，并自动折算到团队贡献中的“学习成长”维度（本期目标积分 30 分）。
        </Typography.Paragraph>
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col xs={24} sm={8}><Statistic title="目标数" value={items.length} /></Col>
          <Col xs={24} sm={8}><Statistic title="平均完成度" value={averageProgress} precision={1} suffix="%" /></Col>
          <Col xs={24} sm={8}><Statistic title="已折算积分" value={totalPoints} precision={2} suffix="/ 30" prefix={<TrophyOutlined />} /></Col>
        </Row>
        <Table<LearningGrowthGoal>
          rowKey="id"
          loading={loading}
          dataSource={items}
          columns={columns}
          standardToolbar={{ exportFileName: '学习任务', searchPlaceholder: '搜索学习任务、人员、佐证或说明' }}
          scroll={{ x: 1550 }}
          pagination={{ pageSize: 20, showSizeChanger: true }}
          locale={{ emptyText: '本考核周期还没有学习任务' }}
        />
      </Card>

      <Modal
        open={modalOpen}
        title={editing ? '编辑学习任务' : `新增学习任务（${periodLabel(period)}）`}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        onOk={() => void save()}
        okText="保存并自动计分"
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={{ progress: 0 }}>
          <Form.Item name="goal" label="学习任务" rules={[{ required: true, message: '请输入任务' }, { min: 2, message: '任务至少 2 个字符' }]}>
            <Input maxLength={200} placeholder="如：完成 PostgreSQL 性能调优实验并输出报告" />
          </Form.Item>
          <Form.Item name="target_description" label="目标说明/验收标准">
            <Input.TextArea rows={3} maxLength={4000} placeholder="说明目标范围、预期产出和可验证的验收标准" />
          </Form.Item>
          <Form.Item name="progress" label="实际完成进度" rules={[{ required: true, message: '请输入完成进度' }]}>
            <InputNumber min={0} max={100} precision={1} addonAfter="%" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="evidence" label="相关佐证">
            <Input.TextArea rows={3} maxLength={4000} placeholder="填写证书、报告、代码仓库、知识文章、演示记录等链接或说明" />
          </Form.Item>
          <Form.Item name="note" label="补充说明">
            <Input.TextArea rows={3} maxLength={4000} placeholder="补充完成情况、遇到的问题或后续计划" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
