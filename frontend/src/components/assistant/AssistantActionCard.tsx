import { useEffect, useMemo, useRef } from 'react';
import { Alert, Button, Card, Descriptions, Space, Tag, Typography } from 'antd';
import { CheckOutlined, CloseOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { assistantApi, assistantErrorCode, assistantErrorStatus } from '../../api/assistant';
import type { AssistantActionPayload, AssistantActionStatus } from '../../api/types';
import { useT } from '../../i18n';
import { safeAssistantNavigationPath } from './AssistantContext';

export interface AssistantActionView extends AssistantActionPayload {
  status: AssistantActionStatus;
  confirmation_expires_at: string | null;
}

interface Props {
  action: AssistantActionView;
  interactionDisabled?: boolean;
  onChange: (next: AssistantActionView) => void;
  onNavigate: (path: string) => void;
}

const TERMINAL = new Set<AssistantActionStatus>(['succeeded', 'cancelled', 'expired', 'conflict', 'failed']);

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return '-';
  }
}

export default function AssistantActionCard({ action, interactionDisabled = false, onChange, onNavigate }: Props) {
  const t = useT();
  const busy = useRef(false);
  const expiresAt = action.confirmation_expires_at ? Date.parse(action.confirmation_expires_at) : NaN;
  const disabled = interactionDisabled || TERMINAL.has(action.status) || action.status === 'confirming' || action.status === 'cancelling';
  const payload = action.status === 'succeeded' ? action.result : action.preview;
  const navigationTarget = safeAssistantNavigationPath(action.result?.target_path);

  useEffect(() => {
    if (action.status !== 'prepared' || !Number.isFinite(expiresAt)) return;
    const remaining = expiresAt - Date.now();
    if (remaining <= 0) {
      onChange({ ...action, status: 'expired', confirmation_token: undefined });
      return;
    }
    const timer = window.setTimeout(
      () => onChange({ ...action, status: 'expired', confirmation_token: undefined }),
      Math.min(remaining, 2_147_000_000),
    );
    return () => window.clearTimeout(timer);
  }, [action, expiresAt, onChange]);

  const status = useMemo(() => {
    const colors: Record<AssistantActionStatus, string> = {
      prepared: 'warning', confirming: 'processing', cancelling: 'processing', succeeded: 'success',
      cancelled: 'default', expired: 'default', conflict: 'error', failed: 'error',
    };
    return <Tag color={colors[action.status]}>{t(`assistant.action.status.${action.status}`)}</Tag>;
  }, [action.status, t]);

  const failState = (error: unknown): AssistantActionStatus => {
    const code = assistantErrorCode(error);
    if (code === 'AI_ACTION_EXPIRED') return 'expired';
    if (assistantErrorStatus(error) === 409 || code?.includes('CONFLICT') || code === 'AI_ACTION_NOT_PREPARED' || code === 'AI_ASSISTANT_RUNTIME_CHANGED') return 'conflict';
    return 'failed';
  };

  const confirm = async () => {
    if (busy.current || disabled) return;
    if (!action.confirmation_token || (Number.isFinite(expiresAt) && expiresAt <= Date.now())) {
      onChange({ ...action, status: action.confirmation_token ? 'expired' : 'conflict', confirmation_token: undefined });
      return;
    }
    busy.current = true;
    onChange({ ...action, status: 'confirming' });
    try {
      const result = await assistantApi.confirmAction(action.action_id, action.confirmation_token);
      onChange({
        ...action,
        ...result,
        confirmation_token: undefined,
        confirmation_expires_at: result.confirmation_expires_at ?? action.confirmation_expires_at,
        status: result.status === 'succeeded' ? 'succeeded' : 'failed',
      });
    } catch (error) {
      onChange({ ...action, confirmation_token: undefined, status: failState(error) });
    } finally {
      busy.current = false;
    }
  };

  const cancel = async () => {
    if (busy.current || disabled) return;
    if (Number.isFinite(expiresAt) && expiresAt <= Date.now()) {
      onChange({ ...action, status: 'expired', confirmation_token: undefined });
      return;
    }
    busy.current = true;
    onChange({ ...action, status: 'cancelling' });
    try {
      const result = await assistantApi.cancelAction(action.action_id);
      onChange({
        ...action,
        ...result,
        confirmation_token: undefined,
        confirmation_expires_at: result.confirmation_expires_at ?? action.confirmation_expires_at,
        status: result.status === 'cancelled' ? 'cancelled' : 'failed',
      });
    } catch (error) {
      onChange({ ...action, confirmation_token: undefined, status: failState(error) });
    } finally {
      busy.current = false;
    }
  };

  const rows = Object.entries(payload ?? {}).slice(0, 30).map(([key, value]) => ({
    key,
    label: key,
    children: <Typography.Text className="assistant-action__value">{displayValue(value)}</Typography.Text>,
  }));

  return (
    <Card
      size="small"
      className={`assistant-action assistant-action--${action.status}`}
      title={<Space><SafetyCertificateOutlined />{t('assistant.action.title')}</Space>}
      extra={status}
      aria-live="polite"
    >
      <Alert
        showIcon
        type={action.status === 'succeeded' ? 'success' : action.status === 'prepared' ? 'warning' : 'info'}
        message={t(action.status === 'succeeded' ? 'assistant.action.authoritativeResult' : 'assistant.action.previewNotice')}
      />
      {rows.length > 0 && <Descriptions className="assistant-action__preview" size="small" column={1} items={rows} />}
      {action.status === 'conflict' && <Typography.Text type="danger">{t('assistant.action.conflictNotice')}</Typography.Text>}
      {action.status === 'failed' && <Typography.Text type="danger">{t('assistant.action.failedNotice')}</Typography.Text>}
      <Space wrap className="assistant-action__footer">
        {action.status === 'prepared' && (
          <>
            <Button type="primary" icon={<CheckOutlined />} disabled={disabled} onClick={() => void confirm()}>
              {t('assistant.action.confirm')}
            </Button>
            <Button icon={<CloseOutlined />} disabled={disabled} onClick={() => void cancel()}>
              {t('assistant.action.cancel')}
            </Button>
          </>
        )}
        {action.status === 'confirming' && <Button type="primary" loading>{t('assistant.action.confirming')}</Button>}
        {action.status === 'cancelling' && <Button loading>{t('assistant.action.cancelling')}</Button>}
        {navigationTarget && action.status === 'succeeded' && (
          <Button onClick={() => onNavigate(navigationTarget)}>{t('assistant.action.openResult')}</Button>
        )}
      </Space>
    </Card>
  );
}
