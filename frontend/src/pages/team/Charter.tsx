import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Col, Form, Input, Row, Space, Spin, Typography, message } from 'antd';
import { EditOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import { hasPermission, useAuthStore } from '../../stores/auth';
import type { TeamCharterData } from '../../api/types';

interface CharterFormValues {
  vision?: string;
  goals?: string;
  principles?: string;
}

const SECTIONS: { key: keyof CharterFormValues; titleKey: string; hintKey: string }[] = [
  { key: 'vision', titleKey: 'team.charter.vision.title', hintKey: 'team.charter.vision.hint' },
  { key: 'goals', titleKey: 'team.charter.goals.title', hintKey: 'team.charter.goals.hint' },
  { key: 'principles', titleKey: 'team.charter.principles.title', hintKey: 'team.charter.principles.hint' },
];

/** 团队文化（单例）：愿景 / 年度目标 / 行为准则 */
export default function Charter() {
  const t = useT();
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
      message.success(t('team.charter.saved'));
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
      title={t('team.charter.title')}
      extra={
        <Space>
          {data?.updated_at && !editing && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t('team.charter.lastUpdated', { time: dayjs(data.updated_at).format('YYYY-MM-DD HH:mm') })}
            </Typography.Text>
          )}
          {canEdit &&
            (editing ? (
              <>
                <Button onClick={() => setEditing(false)}>{t('common.cancel')}</Button>
                <Button type="primary" loading={saving} onClick={() => void handleSave()}>
                  {t('common.save')}
                </Button>
              </>
            ) : (
              <Button icon={<EditOutlined />} onClick={startEdit}>
                {t('common.edit')}
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
                <Card type="inner" title={t(s.titleKey)} style={{ height: '100%' }}>
                  {editing ? (
                    <Form.Item name={s.key} noStyle>
                      <Input.TextArea rows={8} maxLength={2000} placeholder={t(s.hintKey)} />
                    </Form.Item>
                  ) : data?.[s.key] ? (
                    <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                      {data[s.key]}
                    </Typography.Paragraph>
                  ) : (
                    <Typography.Text type="secondary">
                      {canEdit
                        ? t('team.charter.emptyEditable', { hint: t(s.hintKey) })
                        : t('team.charter.empty')}
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
