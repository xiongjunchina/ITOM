import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Col, Form, Input, Row, Space, Spin, Typography, message } from 'antd';
import { EditOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import { hasPermission, useAuthStore } from '../../stores/auth';
import type { TeamCharterData } from '../../api/types';

interface CharterFormValues {
  vision?: string;
  goals?: string;
  principles?: string;
}

const SECTIONS: { key: keyof CharterFormValues; title: string; hint: string }[] = [
  { key: 'vision', title: '愿景', hint: '我们为什么存在：用一段话说清团队的长期方向与价值主张。' },
  { key: 'goals', title: '年度目标', hint: '今年要达成的 3-5 条可衡量目标，建议一行一条。' },
  { key: 'principles', title: '行为准则', hint: '团队协作的基本约定：如响应时限、评审规则、值班纪律等，一行一条。' },
];

/** 团队文化（单例）：愿景 / 年度目标 / 行为准则 */
export default function Charter() {
  const user = useAuthStore((s) => s.user);
  const canEdit = user?.permissions ? hasPermission(user, 'charter', 'edit') : true;

  const [data, setData] = useState<TeamCharterData | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<CharterFormValues>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.get<TeamCharterData>('/team-charter'));
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const startEdit = () => {
    form.setFieldsValue({
      vision: data?.vision ?? '',
      goals: data?.goals ?? '',
      principles: data?.principles ?? '',
    });
    setEditing(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      await api.put('/team-charter', {
        vision: values.vision?.trim() || null,
        goals: values.goals?.trim() || null,
        principles: values.principles?.trim() || null,
      });
      message.success('团队文化已保存');
      setEditing(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card
      title="团队文化"
      extra={
        <Space>
          {data?.updated_at && !editing && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              最近更新：{dayjs(data.updated_at).format('YYYY-MM-DD HH:mm')}
            </Typography.Text>
          )}
          {canEdit &&
            (editing ? (
              <>
                <Button onClick={() => setEditing(false)}>取消</Button>
                <Button type="primary" loading={saving} onClick={() => void handleSave()}>
                  保存
                </Button>
              </>
            ) : (
              <Button icon={<EditOutlined />} onClick={startEdit}>
                编辑
              </Button>
            ))}
        </Space>
      }
    >
      <Spin spinning={loading}>
        <Form<CharterFormValues> form={form} layout="vertical">
          <Row gutter={[16, 16]}>
            {SECTIONS.map((s) => (
              <Col key={s.key} xs={24} lg={8}>
                <Card type="inner" title={s.title} style={{ height: '100%' }}>
                  {editing ? (
                    <Form.Item name={s.key} noStyle>
                      <Input.TextArea rows={8} maxLength={2000} placeholder={s.hint} />
                    </Form.Item>
                  ) : data?.[s.key] ? (
                    <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                      {data[s.key]}
                    </Typography.Paragraph>
                  ) : (
                    <Typography.Text type="secondary">
                      {canEdit ? `尚未填写。点击右上角「编辑」开始：${s.hint}` : '尚未填写。'}
                    </Typography.Text>
                  )}
                </Card>
              </Col>
            ))}
          </Row>
        </Form>
      </Spin>
    </Card>
  );
}
