import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Drawer, Empty, Grid, Input, Skeleton, Space, Typography } from 'antd';
import type { TextAreaRef } from 'antd/es/input/TextArea';
import { DeleteOutlined, RobotOutlined, SendOutlined } from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  AssistantStreamError,
  assistantApi,
  isAssistantConfirmationToken,
  streamAssistantMessage,
} from '../../api/assistant';
import type { AssistantBootstrap, AssistantServerMessage, AssistantSseEvent } from '../../api/types';
import { useT } from '../../i18n';
import { useLangStore } from '../../i18n/store';
import AssistantMessageList, { type AssistantMessageItem, type AssistantTimelineItem } from './AssistantMessageList';
import type { AssistantActionView } from './AssistantActionCard';
import {
  buildAssistantPageContext,
  redactAssistantInputForDisplay,
  safeAssistantNavigationPath,
} from './AssistantContext';

interface Props {
  open: boolean;
  onClose: () => void;
}

interface AssistantConversationTimelineProps {
  items: AssistantTimelineItem[];
  sending: boolean;
  onStart: () => void;
  onActionChange: (action: AssistantActionView) => void;
  onNavigate: (path: string) => void;
}

const MAX_VISIBLE_RESPONSE_CHARS = 512 * 1024;

type AssistantMessagePresentation = Pick<AssistantMessageItem, 'text' | 'authority' | 'authorityNotice'>;

function hasExactKeys(value: object, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function isNonEmptyText(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

/** Accept only the two completed, server-owned authority envelopes. */
export function presentAssistantServerMessage(message: AssistantServerMessage | undefined): AssistantMessagePresentation {
  if (
    !message
    || !hasExactKeys(message, ['content', 'id', 'role', 'status'])
    || !isNonEmptyText(message.id)
    || message.role !== 'assistant'
    || message.status !== 'completed'
    || !message.content
    || typeof message.content !== 'object'
    || Array.isArray(message.content)
  ) {
    throw new AssistantStreamError('AI_ASSISTANT_STREAM_PAYLOAD', 'Invalid message');
  }
  const {
    action_id: actionId,
    advisory_text: advisoryText,
    authority,
    operation_status: operationStatus,
    text: authorityNotice,
  } = message.content;
  if (authority === 'advisory') {
    if (
      operationStatus !== 'not_executed'
      || !hasExactKeys(message.content, ['advisory_text', 'authority', 'operation_status', 'text'])
      || !isNonEmptyText(advisoryText)
      || !isNonEmptyText(authorityNotice)
    ) {
      throw new AssistantStreamError('AI_ASSISTANT_STREAM_PAYLOAD', 'Invalid advisory message');
    }
    return { text: advisoryText, authority, authorityNotice };
  }
  if (
    authority === 'server_preview'
    && operationStatus === 'prepared_not_executed'
    && hasExactKeys(message.content, ['action_id', 'authority', 'operation_status', 'text'])
    && isNonEmptyText(actionId)
    && isNonEmptyText(authorityNotice)
  ) {
    return { text: authorityNotice, authority };
  }
  throw new AssistantStreamError('AI_ASSISTANT_STREAM_PAYLOAD', 'Invalid message');
}

/** Server error details are untrusted; only the fixed localized client fallback is displayable. */
export function safeAssistantStreamErrorDetail(
  _data: Extract<AssistantSseEvent, { type: 'error' }>['data'],
  localizedFallback: string,
): string {
  return localizedFallback;
}

/** Remove only output created by the failed turn, then keep one safe no-action notice. */
export function discardFailedAssistantTurn(
  current: AssistantTimelineItem[],
  turnItemIds: ReadonlySet<string>,
  safeNotice: AssistantMessageItem,
): AssistantTimelineItem[] {
  return [
    ...current.filter((item) => !turnItemIds.has(item.id) && item.id !== safeNotice.id),
    safeNotice,
  ];
}

/** Keep action interaction tied directly to the current send state. */
export function AssistantConversationTimeline({
  items,
  sending,
  onStart,
  onActionChange,
  onNavigate,
}: AssistantConversationTimelineProps) {
  return (
    <AssistantMessageList
      items={items}
      actionInteractionDisabled={sending}
      onStart={onStart}
      onActionChange={onActionChange}
      onNavigate={onNavigate}
    />
  );
}

function clientMessageId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

export default function AssistantDrawer({ open, onClose }: Props) {
  const t = useT();
  const lang = useLangStore((state) => state.lang);
  const location = useLocation();
  const navigate = useNavigate();
  const screens = Grid.useBreakpoint();
  const inputRef = useRef<TextAreaRef>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [bootstrap, setBootstrap] = useState<AssistantBootstrap | null>(null);
  const [bootstrapLoading, setBootstrapLoading] = useState(false);
  const [showSkeleton, setShowSkeleton] = useState(false);
  const [bootstrapError, setBootstrapError] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [items, setItems] = useState<AssistantTimelineItem[]>([]);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [fallbackPath, setFallbackPath] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setBootstrapLoading(true);
    setBootstrapError(false);
    assistantApi.bootstrap()
      .then((value) => { if (active) setBootstrap(value); })
      .catch(() => { if (active) setBootstrapError(true); })
      .finally(() => { if (active) setBootstrapLoading(false); });
    return () => { active = false; };
  }, [open]);

  useEffect(() => {
    if (!bootstrapLoading) {
      setShowSkeleton(false);
      return;
    }
    const timer = window.setTimeout(() => setShowSkeleton(true), 300);
    return () => window.clearTimeout(timer);
  }, [bootstrapLoading]);

  const close = () => {
    abortRef.current?.abort();
    onClose();
  };

  const go = useCallback((path: string) => {
    const safe = safeAssistantNavigationPath(path);
    if (!safe) return;
    onClose();
    navigate(safe);
  }, [navigate, onClose]);

  const updateAction = useCallback((next: AssistantActionView) => {
    setItems((current) => current.map((item) => (
      item.kind === 'action' && item.action.action_id === next.action_id ? { ...item, action: next } : item
    )));
  }, []);

  const send = async () => {
    const content = draft.trim();
    if (!content || sending || !bootstrap?.enabled) return;
    const pageContext = buildAssistantPageContext(location.pathname, {
      tab: new URLSearchParams(location.search).get('tab') ?? undefined,
    });
    const id = clientMessageId();
    const streamId = `stream-${id}`;
    const failureNoticeId = `stream-error-${id}`;
    const turnItemIds = new Set<string>();
    const appendBrokenStream = (detail?: string) => {
      const safeNotice: AssistantMessageItem = {
        kind: 'message',
        id: failureNoticeId,
        role: 'system',
        text: [detail, t('assistant.stream.noAction')].filter(Boolean).join(' '),
        error: true,
      };
      setItems((current) => discardFailedAssistantTurn(current, turnItemIds, safeNotice));
    };
    setDraft('');
    setFallbackPath(null);
    setSending(true);
    setItems((current) => [...current, {
      kind: 'message',
      id: `user-${id}`,
      role: 'user',
      text: redactAssistantInputForDisplay(content),
    }]);

    try {
      let activeConversationId = conversationId;
      if (!activeConversationId) {
        const created = await assistantApi.createConversation(lang === 'en' ? 'en' : 'zh-CN', pageContext);
        activeConversationId = created.id;
        setConversationId(created.id);
      }
      const controller = new AbortController();
      abortRef.current = controller;
      let visibleText = '';

      const onEvent = (event: AssistantSseEvent) => {
        if (event.type === 'delta') {
          if (typeof event.data.text !== 'string') throw new AssistantStreamError('AI_ASSISTANT_STREAM_PAYLOAD', 'Invalid delta');
          visibleText += event.data.text;
          if (visibleText.length > MAX_VISIBLE_RESPONSE_CHARS) {
            throw new AssistantStreamError('AI_ASSISTANT_STREAM_TEXT_TOO_LARGE', 'Assistant response exceeded its display limit');
          }
          turnItemIds.add(streamId);
          setItems((current) => {
            const existing = current.some((item) => item.kind === 'message' && item.id === streamId);
            if (!existing) return [...current, { kind: 'message', id: streamId, role: 'assistant', text: visibleText, streaming: true }];
            return current.map((item) => item.kind === 'message' && item.id === streamId
              ? { ...item, text: visibleText, streaming: true }
              : item);
          });
        }
        if (event.type === 'message') {
          const serverMessage = event.data.message;
          const presentation = presentAssistantServerMessage(serverMessage);
          const serverMessageItemId = `message-${id}-${serverMessage!.id}`;
          turnItemIds.add(streamId);
          turnItemIds.add(serverMessageItemId);
          setItems((current) => [
            ...current.filter((item) => !(item.kind === 'message' && item.id === streamId)),
            {
              kind: 'message',
              id: serverMessageItemId,
              role: 'assistant',
              ...presentation,
            },
          ]);
        }
        if (event.type === 'action') {
          const payload = event.data;
          if (
            typeof payload.action_id !== 'string'
            || payload.risk !== 'L3'
            || !payload.preview
            || typeof payload.preview !== 'object'
            || Array.isArray(payload.preview)
            || (payload.confirmation_token !== undefined && typeof payload.confirmation_token !== 'string')
          ) {
            throw new AssistantStreamError('AI_ASSISTANT_STREAM_PAYLOAD', 'Invalid action');
          }
          const expires = payload.confirmation_expires_at ?? payload.expires_at ?? null;
          if (expires !== null && (typeof expires !== 'string' || !Number.isFinite(Date.parse(expires)))) {
            throw new AssistantStreamError('AI_ASSISTANT_STREAM_PAYLOAD', 'Invalid action expiry');
          }
          const confirmationToken = isAssistantConfirmationToken(payload.confirmation_token)
            ? payload.confirmation_token
            : undefined;
          const action: AssistantActionView = {
            ...payload,
            confirmation_token: confirmationToken,
            status: confirmationToken ? 'prepared' : 'conflict',
            confirmation_expires_at: expires,
          };
          const actionItemId = `action-${id}-${action.action_id}`;
          turnItemIds.add(actionItemId);
          setItems((current) => [...current, { kind: 'action', id: actionItemId, action }]);
        }
        if (event.type === 'error') {
          const safeFallback = safeAssistantNavigationPath(event.data.fallback_path);
          if (safeFallback) setFallbackPath(safeFallback);
          appendBrokenStream(safeAssistantStreamErrorDetail(event.data, t('assistant.stream.error')));
        }
        if (event.type === 'done') {
          setItems((current) => current.map((item) => turnItemIds.has(item.id) && item.kind === 'message' && item.streaming
            ? { ...item, streaming: false }
            : item));
        }
      };

      await streamAssistantMessage({
        conversationId: activeConversationId,
        content,
        clientMessageId: id,
        pageContext,
        signal: controller.signal,
        onEvent,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        appendBrokenStream(t('assistant.stream.interrupted'));
      } else {
        appendBrokenStream(t('assistant.stream.broken'));
      }
    } finally {
      abortRef.current = null;
      setSending(false);
    }
  };

  const resetConversation = async () => {
    abortRef.current?.abort();
    if (conversationId) {
      setResetting(true);
      try {
        await assistantApi.archiveConversation(conversationId);
      } catch {
        setResetting(false);
        return;
      }
    }
    setConversationId(null);
    setItems([]);
    setFallbackPath(null);
    setResetting(false);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  };

  const body = useMemo(() => {
    if (bootstrapLoading) return showSkeleton ? <Skeleton active paragraph={{ rows: 7 }} /> : <div className="assistant-loading-placeholder" />;
    if (bootstrapError) {
      return <Alert showIcon type="error" message={t('assistant.bootstrap.error')} action={<Button onClick={close}>{t('common.close')}</Button>} />;
    }
    if (!bootstrap?.enabled) {
      return (
        <div className="assistant-unavailable">
          <Empty
            image={<RobotOutlined className="assistant-empty__icon" />}
            description={
              <Space direction="vertical" size={4}>
                <Typography.Text strong>{t('assistant.unavailable.title')}</Typography.Text>
                <Typography.Text type="secondary">{t('assistant.unavailable.description')}</Typography.Text>
              </Space>
            }
          >
            <Button type="primary" onClick={close}>{t('assistant.unavailable.action')}</Button>
          </Empty>
        </div>
      );
    }
    return (
      <AssistantConversationTimeline
        items={items}
        sending={sending}
        onStart={() => inputRef.current?.focus()}
        onActionChange={updateAction}
        onNavigate={go}
      />
    );
  }, [bootstrap, bootstrapError, bootstrapLoading, go, items, sending, showSkeleton, t, updateAction]);

  const composerDisabled = bootstrapLoading || bootstrapError || !bootstrap?.enabled;

  return (
    <Drawer
      className="assistant-drawer"
      title={
        <Space>
          <RobotOutlined />
          <span>{t('assistant.title')}</span>
        </Space>
      }
      extra={
        <Button
          type="text"
          icon={<DeleteOutlined />}
          aria-label={t('assistant.newConversation')}
          loading={resetting}
          disabled={sending || resetting || items.length === 0}
          onClick={() => void resetConversation()}
        >
          {screens.md ? t('assistant.newConversation') : null}
        </Button>
      }
      width={screens.sm ? 480 : '100%'}
      open={open}
      onClose={close}
      destroyOnClose={false}
      keyboard
      footer={
        <div className="assistant-composer">
          {fallbackPath && (
            <Alert
              type="info"
              showIcon
              message={t('assistant.fallback.message')}
              action={<Button size="small" onClick={() => go(fallbackPath)}>{t('assistant.fallback.action')}</Button>}
            />
          )}
          <label className="assistant-visually-hidden" htmlFor="assistant-message-input">{t('assistant.input.label')}</label>
          <Input.TextArea
            ref={inputRef}
            id="assistant-message-input"
            value={draft}
            rows={3}
            maxLength={8000}
            showCount
            disabled={composerDisabled}
            placeholder={t('assistant.input.placeholder')}
            onChange={(event) => setDraft(event.target.value)}
            onPressEnter={(event) => {
              if (!event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
          />
          <div className="assistant-composer__footer">
            <Typography.Text type="secondary">{t('assistant.input.securityHint')}</Typography.Text>
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={sending}
              disabled={composerDisabled || !draft.trim()}
              onClick={() => void send()}
            >
              {t('assistant.send')}
            </Button>
          </div>
        </div>
      }
    >
      {body}
    </Drawer>
  );
}
