import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Card, Form, Input, Select, Space, Spin, Typography, message } from 'antd';
import { ArrowLeftOutlined, SaveOutlined, SendOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
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
  const isEdit = !!id;

  const [form] = Form.useForm<ArticleFormValues>();
  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState<KnowledgeStatus | null>(null);
  const [origin, setOrigin] = useState<KnowledgeDetailData | null>(null);

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
      message.success(status === 'published' ? '文章已发布' : '草稿已保存');
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
        <Typography.Text type="secondary">文章不存在或无权编辑</Typography.Text>
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
            返回
          </Button>
          {isEdit ? `编辑文章：${origin?.article_code ?? ''}` : '写文章'}
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
            保存草稿
          </Button>
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={saving === 'published'}
            disabled={saving === 'draft'}
            onClick={() => void save('published')}
          >
            发布
          </Button>
        </Space>
      }
    >
      <Form<ArticleFormValues> form={form} layout="vertical">
        <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
          <Input maxLength={200} placeholder="文章标题" />
        </Form.Item>
        <Form.Item
          name="content"
          label="内容（Markdown）"
          rules={[{ required: true, message: '请输入内容' }]}
          extra="支持 #/##/### 标题、> 引用、``` 代码块 等简单 Markdown 语法"
        >
          <Input.TextArea
            rows={18}
            placeholder={'## 问题现象\n\n…\n\n## 解决方案\n\n…'}
            style={{ fontFamily: 'monospace' }}
          />
        </Form.Item>
        <Form.Item name="tags" label="标签">
          <Select mode="tags" placeholder="输入后回车添加标签" open={false} tokenSeparators={[',', '，']} />
        </Form.Item>
      </Form>
    </Card>
  );
}
