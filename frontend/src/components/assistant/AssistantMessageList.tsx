import { useEffect, useRef } from 'react';
import { Avatar, Button, Empty, Space, Tag, Typography } from 'antd';
import { RobotOutlined, SendOutlined, UserOutlined, WarningOutlined } from '@ant-design/icons';
import { useT } from '../../i18n';
import AssistantActionCard, { type AssistantActionView } from './AssistantActionCard';

export interface AssistantMessageItem {
  kind: 'message';
  id: string;
  role: 'user' | 'assistant' | 'system';
  text: string;
  authority?: string;
  streaming?: boolean;
  error?: boolean;
}

export interface AssistantActionItem {
  kind: 'action';
  id: string;
  action: AssistantActionView;
}

export type AssistantTimelineItem = AssistantMessageItem | AssistantActionItem;

interface Props {
  items: AssistantTimelineItem[];
  actionInteractionDisabled?: boolean;
  onStart: () => void;
  onActionChange: (action: AssistantActionView) => void;
  onNavigate: (path: string) => void;
}

export default function AssistantMessageList({ items, actionInteractionDisabled = false, onStart, onActionChange, onNavigate }: Props) {
  const t = useT();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    endRef.current?.scrollIntoView({ block: 'end', behavior: reducedMotion ? 'auto' : 'smooth' });
  }, [items]);

  if (items.length === 0) {
    return (
      <div className="assistant-empty">
        <Empty
          image={<RobotOutlined className="assistant-empty__icon" />}
          description={
            <Space direction="vertical" size={4}>
              <Typography.Text strong>{t('assistant.empty.title')}</Typography.Text>
              <Typography.Text type="secondary">{t('assistant.empty.description')}</Typography.Text>
            </Space>
          }
        >
          <Button type="primary" icon={<SendOutlined />} onClick={onStart}>{t('assistant.empty.action')}</Button>
        </Empty>
      </div>
    );
  }

  return (
    <section className="assistant-messages" aria-label={t('assistant.messages.label')} aria-live="polite">
      {items.map((item) => {
        if (item.kind === 'action') {
          return (
            <AssistantActionCard
              key={item.id}
              action={item.action}
              interactionDisabled={actionInteractionDisabled}
              onChange={onActionChange}
              onNavigate={onNavigate}
            />
          );
        }
        return (
          <article key={item.id} className={`assistant-message assistant-message--${item.role}${item.error ? ' assistant-message--error' : ''}`}>
            <Avatar
              size={30}
              icon={item.error ? <WarningOutlined /> : item.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
              className="assistant-message__avatar"
            />
            <div className="assistant-message__body">
              <Space size={6} wrap>
                <Typography.Text strong>{t(`assistant.role.${item.role}`)}</Typography.Text>
                {item.authority === 'advisory' && <Tag>{t('assistant.authority.advisory')}</Tag>}
                {item.authority === 'server_preview' && <Tag color="warning">{t('assistant.authority.preview')}</Tag>}
              </Space>
              <Typography.Paragraph className="assistant-message__text">{item.text}</Typography.Paragraph>
              {item.streaming && <span className="assistant-message__cursor" aria-label={t('assistant.streaming')} />}
            </div>
          </article>
        );
      })}
      <div ref={endRef} />
    </section>
  );
}
