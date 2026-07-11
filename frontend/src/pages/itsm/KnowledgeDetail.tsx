import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button, Card, Space, Spin, Tag, Typography, message } from 'antd';
import { ArrowLeftOutlined, EditOutlined, EyeOutlined, LikeOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import DOMPurify from 'dompurify';
import { api } from '../../api/client';
import { hasAnyRole, useAuthStore } from '../../stores/auth';
import type { KnowledgeDetail as KnowledgeDetailData } from '../../api/types';
import './knowledge-html.css';

/**
 * 极简 Markdown 渲染（不引第三方库）：
 * 支持 #/##/### 标题、> 引用、``` 代码块，其余按 pre-wrap 段落输出。
 */
function renderContent(content: string): JSX.Element[] {
  const nodes: JSX.Element[] = [];
  const lines = content.split('\n');
  let para: string[] = [];
  let code: string[] | null = null;

  const flushPara = (key: number) => {
    if (para.length === 0) return;
    nodes.push(
      <Typography.Paragraph key={`p${key}`} style={{ whiteSpace: 'pre-wrap', marginBottom: 12 }}>
        {para.join('\n')}
      </Typography.Paragraph>,
    );
    para = [];
  };

  lines.forEach((line, i) => {
    if (line.trimStart().startsWith('```')) {
      if (code === null) {
        flushPara(i);
        code = [];
      } else {
        nodes.push(
          <pre
            key={`c${i}`}
            style={{
              background: '#f5f5f5',
              padding: 12,
              borderRadius: 4,
              overflowX: 'auto',
              marginBottom: 12,
            }}
          >
            {code.join('\n')}
          </pre>,
        );
        code = null;
      }
      return;
    }
    if (code !== null) {
      code.push(line);
      return;
    }
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      flushPara(i);
      const level = (heading[1].length + 2) as 3 | 4 | 5;
      nodes.push(
        <Typography.Title key={`h${i}`} level={level} style={{ marginTop: 16 }}>
          {heading[2]}
        </Typography.Title>,
      );
      return;
    }
    if (line.startsWith('> ')) {
      flushPara(i);
      nodes.push(
        <div
          key={`q${i}`}
          style={{
            borderLeft: '3px solid #d9d9d9',
            paddingLeft: 12,
            color: 'rgba(0,0,0,0.55)',
            marginBottom: 12,
            whiteSpace: 'pre-wrap',
          }}
        >
          {line.slice(2)}
        </div>,
      );
      return;
    }
    if (line.trim() === '') {
      flushPara(i);
      return;
    }
    para.push(line);
  });
  flushPara(lines.length);
  if (code !== null) {
    nodes.push(
      <pre key="ctail" style={{ background: '#f5f5f5', padding: 12, borderRadius: 4 }}>
        {(code as string[]).join('\n')}
      </pre>,
    );
  }
  return nodes;
}

export default function KnowledgeDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);

  const [detail, setDetail] = useState<KnowledgeDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [voting, setVoting] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const data = await api.get<KnowledgeDetailData>(`/knowledge/${id}`);
      setDetail(data);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const vote = async () => {
    setVoting(true);
    try {
      const res = await api.post<{ helpful_count: number }>(`/knowledge/${id}/vote`);
      message.success('感谢反馈');
      setDetail((d) => (d ? { ...d, voted: true, helpful_count: res.helpful_count ?? d.helpful_count + 1 } : d));
    } catch {
      // 已统一提示（SELF_VOTE / DUPLICATE）
    } finally {
      setVoting(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }
  if (!detail) {
    return (
      <Card>
        <Typography.Text type="secondary">文章不存在或无权查看</Typography.Text>
      </Card>
    );
  }

  const canEdit =
    hasAnyRole(user, ['admin', 'cio']) || (!!user && !!detail.author && detail.author === user.id);

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <Space size="middle" wrap>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/itsm/knowledge')}>
              返回
            </Button>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {detail.title}
            </Typography.Title>
            {detail.status === 'draft' && <Tag>草稿</Tag>}
          </Space>
          <Space wrap>
            <Button
              icon={<LikeOutlined />}
              disabled={detail.voted || detail.status === 'draft'}
              loading={voting}
              onClick={() => void vote()}
            >
              有用（{detail.helpful_count}）
            </Button>
            {canEdit && (
              <Button icon={<EditOutlined />} onClick={() => navigate(`/itsm/knowledge/${detail.id}/edit`)}>
                编辑
              </Button>
            )}
          </Space>
        </Space>
        <Space size="middle" wrap style={{ marginTop: 8 }}>
          <Typography.Text type="secondary">{detail.article_code}</Typography.Text>
          <Typography.Text type="secondary">作者：{detail.author_name ?? '-'}</Typography.Text>
          <Typography.Text type="secondary">
            更新于 {detail.updated_at ? dayjs(detail.updated_at).format('YYYY-MM-DD HH:mm') : '-'}
          </Typography.Text>
          <Typography.Text type="secondary">
            <EyeOutlined /> {detail.view_count}
          </Typography.Text>
          {detail.tags?.map((t) => (
            <Tag key={t}>{t}</Tag>
          ))}
        </Space>
      </Card>

      <Card>
        {detail.content_format === 'html' ? (
          // 文档导入的 HTML：后端已 bleach 白名单净化，前端再过一层 DOMPurify 防御
          <div
            className="kb-html-content"
            dangerouslySetInnerHTML={{
              __html: DOMPurify.sanitize(detail.content || '', { USE_PROFILES: { html: true } }),
            }}
          />
        ) : (
          renderContent(detail.content || '')
        )}
      </Card>

      {detail.linked_tickets?.length > 0 && (
        <Card title="关联工单" size="small">
          <Space direction="vertical">
            {detail.linked_tickets.map((t) => (
              <Link key={t.id} to={`/itsm/tickets/${t.id}`}>
                {t.ticket_code} {t.title}
              </Link>
            ))}
          </Space>
        </Card>
      )}
    </Space>
  );
}
