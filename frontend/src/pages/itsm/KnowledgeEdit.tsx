import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Alert, Button, Card, Form, Input, Select, Space, Spin, Typography, message } from 'antd';
import { ArrowLeftOutlined, SaveOutlined, SendOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import type { KnowledgeDetail as KnowledgeDetailData, KnowledgeStatus } from '../../api/types';

interface ArticleFormValues {
  title: string;
  content: string;
  tags?: string[];
}

/** 知识文章编辑页：/itsm/knowledge/new 新建；/itsm/knowledge/:id/edit 编辑 */
export default function KnowledgeEdit() {
  const { id } = useParams<{ id?: string }>();
  const navigate = useNavigate();
  const t = useT();
  const isEdit = !!id;

  const [form] = Form.useForm<ArticleFormValues>();
  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState<KnowledgeStatus | null>(null);
  const [origin, setOrigin] = useState<KnowledgeDetailData | null>(null);
  /** 文档导入的 HTML 格式文章：编辑的是 HTML 源码（保存仍走 PATCH content，格式不变） */
  const isHtml = origin?.content_format === 'html';

  useEffect(() => {
    if (!isEdit) return;
    setLoading(true);
    api
      .get<KnowledgeDetailData>(`/knowledge/${id}`)
      .then((data) => {
        setOrigin(data);
        form.setFieldsValue({ title: data.title, content: data.content, tags: data.tags ?? [] });
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, [isEdit, id, form]);

  const save = async (status: KnowledgeStatus) => {
    const values = await form.validateFields();
    setSaving(status);
    try {
      let articleId = id;
      if (isEdit) {
        await api.patch(`/knowledge/${id}`, {
          title: values.title,
          content: values.content,
          tags: values.tags ?? [],
          status,
        });
      } else {
        const created = await api.post<KnowledgeDetailData>('/knowledge', {
          title: values.title,
          content: values.content,
          tags: values.tags ?? [],
          status,
        });
        articleId = created?.id;
      }
      message.success(status === 'published' ? t('itsm.kb.publishedMsg') : t('itsm.kb.draftSaved'));
      navigate(articleId ? `/itsm/knowledge/${articleId}` : '/itsm/knowledge');
    } catch {
      // 已统一提示
    } finally {
      setSaving(null);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }
  if (isEdit && !origin) {
    return (
      <Card>
        <Typography.Text type="secondary">{t('itsm.kb.notFoundEdit')}</Typography.Text>
      </Card>
    );
  }

  return (
    <Card
      title={
        <Space>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate(isEdit ? `/itsm/knowledge/${id}` : '/itsm/knowledge')}
          >
            {t('itsm.back')}
          </Button>
          {isEdit ? t('itsm.kb.editTitle', { code: origin?.article_code ?? '' }) : t('itsm.kb.write')}
        </Space>
      }
      extra={
        <Space>
          <Button
            icon={<SaveOutlined />}
            loading={saving === 'draft'}
            disabled={saving === 'published'}
            onClick={() => void save('draft')}
          >
            {t('itsm.kb.saveDraft')}
          </Button>
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={saving === 'published'}
            disabled={saving === 'draft'}
            onClick={() => void save('published')}
          >
            {t('itsm.kb.publish')}
          </Button>
        </Space>
      }
    >
      {isHtml && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('itsm.kb.htmlAlert')}
        />
      )}
      <Form<ArticleFormValues> form={form} layout="vertical">
        <Form.Item name="title" label={t('itsm.f.title')} rules={[{ required: true, message: t('itsm.rule.title') }]}>
          <Input maxLength={200} placeholder={t('itsm.kb.titlePlaceholder')} />
        </Form.Item>
        <Form.Item
          name="content"
          label={isHtml ? t('itsm.kb.contentHtml') : t('itsm.kb.contentMd')}
          rules={[{ required: true, message: t('itsm.kb.contentRequired') }]}
          extra={isHtml ? undefined : t('itsm.kb.mdHint')}
        >
          <Input.TextArea
            rows={18}
            placeholder={isHtml ? undefined : t('itsm.kb.contentPlaceholder')}
            style={{ fontFamily: 'monospace' }}
          />
        </Form.Item>
        <Form.Item name="tags" label={t('itsm.f.tags')}>
          <Select mode="tags" placeholder={t('itsm.kb.tagsPlaceholder')} open={false} tokenSeparators={[',', '，']} />
        </Form.Item>
      </Form>
    </Card>
  );
}
