import axios from 'axios';
import { api } from './client';
import type {
  AiActionAuditRow,
  AiHealthSummary,
  AiProfileDraft,
  AiProfileVersion,
  AiProviderConfig,
  AiProviderWrite,
  AiUsageSummary,
  AssistantActionPayload,
  AssistantBootstrap,
  AssistantConversation,
  AssistantPageContext,
  AssistantSseEvent,
  Envelope,
} from './types';
import { useLangStore } from '../i18n/store';
import { useAuthStore } from '../stores/auth';

const SSE_EVENT_TYPES = new Set<AssistantSseEvent['type']>([
  'meta', 'delta', 'message', 'action', 'error', 'done',
]);
const ASSISTANT_ACTION_ID = /^[0-9A-HJKMNP-TV-Z]{26}$/;

export function isAssistantActionId(value: unknown): value is string {
  return typeof value === 'string' && ASSISTANT_ACTION_ID.test(value);
}

/** A single final message may be large; both limits remain finite and fail closed. */
export const ASSISTANT_SSE_MAX_FRAME_CHARS = 1024 * 1024;
export const ASSISTANT_SSE_MAX_BUFFER_CHARS = ASSISTANT_SSE_MAX_FRAME_CHARS * 2;

/** A prepared action needs the one-time raw value, never a redaction sentinel or whitespace variant. */
export function isAssistantConfirmationToken(value: unknown): value is string {
  return typeof value === 'string'
    && value.length > 0
    && value.length <= 512
    && value.trim() === value
    && value !== '[REDACTED]';
}

export class AssistantStreamError extends Error {
  constructor(public readonly code: string, message: string) {
    super(message);
    this.name = 'AssistantStreamError';
  }
}

function frameSeparator(buffer: string): { index: number; length: number } | null {
  const candidates = [
    { index: buffer.indexOf('\r\n\r\n'), length: 4 },
    { index: buffer.indexOf('\n\n'), length: 2 },
    { index: buffer.indexOf('\r\r'), length: 2 },
  ].filter((item) => item.index >= 0);
  return candidates.sort((a, b) => a.index - b.index)[0] ?? null;
}

/** Parse one strict server frame; unknown names, duplicate fields and non-object JSON are rejected. */
export function parseAssistantSseFrame(frame: string): AssistantSseEvent {
  if (!frame || frame.length > ASSISTANT_SSE_MAX_FRAME_CHARS) {
    throw new AssistantStreamError('AI_ASSISTANT_STREAM_FRAME_TOO_LARGE', 'Assistant stream frame is invalid');
  }
  const lines = frame.split(/\r\n|\n|\r/);
  if (lines.length !== 2 || !lines[0].startsWith('event:') || !lines[1].startsWith('data:')) {
    throw new AssistantStreamError('AI_ASSISTANT_STREAM_PROTOCOL', 'Assistant stream frame is invalid');
  }
  const type = lines[0].slice(6).trim() as AssistantSseEvent['type'];
  if (!SSE_EVENT_TYPES.has(type)) {
    throw new AssistantStreamError('AI_ASSISTANT_STREAM_EVENT_UNKNOWN', 'Assistant stream event is not allowed');
  }
  let data: unknown;
  try {
    data = JSON.parse(lines[1].slice(5).trim());
  } catch {
    throw new AssistantStreamError('AI_ASSISTANT_STREAM_JSON', 'Assistant stream payload is invalid');
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new AssistantStreamError('AI_ASSISTANT_STREAM_PAYLOAD', 'Assistant stream payload is invalid');
  }
  return { type, data } as AssistantSseEvent;
}

/** Incremental parser kept independent from React so fragmentation/multi-frame behavior is reviewable. */
export function createAssistantSseParser() {
  let buffer = '';
  let closed = false;

  return {
    push(fragment: string): AssistantSseEvent[] {
      if (closed) throw new AssistantStreamError('AI_ASSISTANT_STREAM_CLOSED', 'Assistant stream is closed');
      buffer += fragment;
      if (buffer.length > ASSISTANT_SSE_MAX_BUFFER_CHARS) {
        throw new AssistantStreamError('AI_ASSISTANT_STREAM_BUFFER_TOO_LARGE', 'Assistant stream buffer exceeded its limit');
      }
      const events: AssistantSseEvent[] = [];
      for (;;) {
        const separator = frameSeparator(buffer);
        if (!separator) break;
        const frame = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator.length);
        if (!frame.trim()) continue;
        events.push(parseAssistantSseFrame(frame));
      }
      return events;
    },
    finish(): AssistantSseEvent[] {
      closed = true;
      if (!buffer.trim()) return [];
      throw new AssistantStreamError('AI_ASSISTANT_STREAM_TRUNCATED', 'Assistant stream ended with an incomplete frame');
    },
  };
}

/** Validate the server-owned event order separately from frame parsing. */
export function createAssistantStreamSequenceValidator() {
  let terminal = false;
  let eventCount = 0;
  let sawMeta = false;
  let sawDelta = false;
  let sawMessage = false;
  let sawError = false;
  let actionId: string | null = null;
  let messageAuthority: 'advisory' | 'server_preview' | null = null;

  const invalidTerminal = () => {
    throw new AssistantStreamError('AI_ASSISTANT_STREAM_TERMINAL', 'Assistant stream terminal sequence is invalid');
  };
  const invalidPayload = () => {
    throw new AssistantStreamError('AI_ASSISTANT_STREAM_PAYLOAD', 'Assistant stream payload is invalid');
  };

  return {
    accept(event: AssistantSseEvent): void {
      if (terminal) {
        throw new AssistantStreamError('AI_ASSISTANT_STREAM_AFTER_DONE', 'Assistant stream continued after completion');
      }
      if (sawError && event.type !== 'done') {
        throw new AssistantStreamError('AI_ASSISTANT_STREAM_AFTER_ERROR', 'Assistant stream continued after an error');
      }

      if (event.type === 'meta') {
        if (eventCount !== 0 || sawMeta) invalidTerminal();
        sawMeta = true;
      } else if (event.type === 'delta') {
        if (!sawMeta || sawMessage || sawError) invalidTerminal();
        sawDelta = true;
      } else if (event.type === 'action') {
        if (
          !sawMeta
          || sawDelta
          || sawMessage
          || sawError
          || actionId !== null
          || event.data.risk !== 'L3'
          || !isAssistantActionId(event.data.action_id)
        ) invalidTerminal();
        actionId = event.data.action_id;
      } else if (event.type === 'message') {
        if (!sawMeta || sawMessage || sawError) invalidTerminal();
        const content = event.data.message?.content;
        const advisoryPair = content?.authority === 'advisory'
          && content.operation_status === 'not_executed';
        const previewPair = content?.authority === 'server_preview'
          && content.operation_status === 'prepared_not_executed'
          && isAssistantActionId(content.action_id);
        if (!advisoryPair && !previewPair) invalidPayload();
        if (previewPair && Object.prototype.hasOwnProperty.call(content, 'advisory_text')) invalidPayload();
        if (actionId === null && !advisoryPair && !previewPair) invalidTerminal();
        if (actionId !== null && (!previewPair || content?.action_id !== actionId)) invalidTerminal();
        messageAuthority = advisoryPair ? 'advisory' : 'server_preview';
        sawMessage = true;
      } else if (event.type === 'error') {
        if (
          sawError
          || sawMessage
          || sawDelta
          || actionId !== null
          || (sawMeta ? eventCount !== 1 : eventCount !== 0)
        ) invalidTerminal();
        sawError = true;
      } else {
        const terminalKeys = Object.keys(event.data);
        if (terminalKeys.length !== 1 || terminalKeys[0] !== 'finish_reason') invalidTerminal();
        const reason = event.data.finish_reason;
        if (typeof reason !== 'string') invalidTerminal();
        if (reason === 'error') {
          if (!sawError || sawMessage || sawDelta || actionId !== null) invalidTerminal();
        } else if (reason === 'stop') {
          if (
            sawError
            || !sawMeta
            || !sawMessage
            || (actionId === null && messageAuthority !== 'advisory')
            || (actionId !== null && messageAuthority !== 'server_preview')
          ) invalidTerminal();
        } else if (reason === 'replay') {
          if (
            sawError
            || !sawMeta
            || !sawMessage
            || sawDelta
            || actionId !== null
            || !['advisory', 'server_preview'].includes(messageAuthority ?? '')
          ) invalidTerminal();
        } else {
          invalidTerminal();
        }
        terminal = true;
      }
      eventCount += 1;
    },
    finish(): void {
      if (!terminal) {
        throw new AssistantStreamError('AI_ASSISTANT_STREAM_TRUNCATED', 'Assistant stream ended before completion');
      }
    },
  };
}

function forceExistingUnauthorizedBehavior() {
  useAuthStore.getState().logout();
  if (window.location.pathname !== '/login') window.location.href = '/login';
}

async function responseError(response: Response): Promise<AssistantStreamError> {
  if (response.status === 401) forceExistingUnauthorizedBehavior();
  let envelope: Envelope | undefined;
  try {
    envelope = await response.json() as Envelope;
  } catch {
    // A non-JSON proxy error stays generic and never exposes its raw body.
  }
  const code = envelope?.error?.code || `HTTP_${response.status}`;
  const message = envelope?.error?.message || 'Assistant request failed';
  return new AssistantStreamError(code, message);
}

export interface StreamAssistantMessageInput {
  conversationId: string;
  content: string;
  clientMessageId: string;
  pageContext: AssistantPageContext;
  signal?: AbortSignal;
  onEvent: (event: AssistantSseEvent) => void;
}

/** Native fetch is required for POST response streaming; credentials remain only in the Authorization header. */
export async function streamAssistantMessage(input: StreamAssistantMessageInput): Promise<void> {
  const token = useAuthStore.getState().token;
  if (!token) {
    forceExistingUnauthorizedBehavior();
    throw new AssistantStreamError('HTTP_401', 'Authentication required');
  }
  const response = await fetch(`/api/assistant/conversations/${encodeURIComponent(input.conversationId)}/messages`, {
    method: 'POST',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      'X-Lang': useLangStore.getState().lang,
    },
    cache: 'no-store',
    credentials: 'same-origin',
    signal: input.signal,
    body: JSON.stringify({
      content: input.content,
      client_message_id: input.clientMessageId,
      page_context: input.pageContext,
    }),
  });
  if (!response.ok) throw await responseError(response);
  if (!response.headers.get('content-type')?.toLowerCase().startsWith('text/event-stream')) {
    throw new AssistantStreamError('AI_ASSISTANT_STREAM_CONTENT_TYPE', 'Assistant stream content type is invalid');
  }
  if (!response.body) throw new AssistantStreamError('AI_ASSISTANT_STREAM_EMPTY', 'Assistant stream is unavailable');

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  const parser = createAssistantSseParser();
  const sequence = createAssistantStreamSequenceValidator();
  const deliver = (events: AssistantSseEvent[]) => {
    for (const event of events) {
      sequence.accept(event);
      input.onEvent(event);
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      deliver(parser.push(decoder.decode(value, { stream: true })));
    }
    deliver(parser.push(decoder.decode()));
    deliver(parser.finish());
    sequence.finish();
  } catch (error) {
    try {
      await reader.cancel();
    } catch {
      // Cancellation is best effort; the original safe parser/transport error remains authoritative.
    }
    throw error;
  } finally {
    reader.releaseLock();
  }
}

export function assistantErrorCode(error: unknown): string | undefined {
  if (error instanceof AssistantStreamError) return error.code;
  if (axios.isAxiosError<Envelope>(error)) return error.response?.data?.error?.code;
  return undefined;
}

export function assistantErrorStatus(error: unknown): number | undefined {
  return axios.isAxiosError(error) ? error.response?.status : undefined;
}

export const assistantApi = {
  bootstrap: () => api.get<AssistantBootstrap>('/assistant/bootstrap'),
  createConversation: (language: string, pageContext: AssistantPageContext) =>
    api.post<AssistantConversation>('/assistant/conversations', { language, page_context: pageContext }),
  listConversations: () => api.getList<AssistantConversation>('/assistant/conversations'),
  getConversation: (id: string) => api.get<AssistantConversation>(`/assistant/conversations/${encodeURIComponent(id)}`),
  archiveConversation: (id: string) => api.post<AssistantConversation>(`/assistant/conversations/${encodeURIComponent(id)}/archive`),
  confirmAction: (id: string, confirmationToken: string) =>
    api.post<AssistantActionPayload>(`/assistant/actions/${encodeURIComponent(id)}/confirm`, { confirmation_token: confirmationToken }),
  cancelAction: (id: string) => api.post<AssistantActionPayload>(`/assistant/actions/${encodeURIComponent(id)}/cancel`),
};

export const adminAiApi = {
  providers: () => api.get<AiProviderConfig[]>('/admin/ai/providers'),
  createProvider: (values: AiProviderWrite) => api.post<AiProviderConfig>('/admin/ai/providers', values),
  updateProvider: (id: string, values: Partial<AiProviderWrite>) =>
    api.patch<AiProviderConfig>(`/admin/ai/providers/${encodeURIComponent(id)}`, values),
  deleteProvider: (id: string) => api.delete<{ id: string }>(`/admin/ai/providers/${encodeURIComponent(id)}`),
  testProvider: (id: string) => api.post<AiProviderConfig>(`/admin/ai/providers/${encodeURIComponent(id)}/test`),
  profileDraft: (code: AiProfileDraft['code']) => api.get<AiProfileDraft>(`/admin/ai/profiles/${code}/draft`),
  updateProfileDraft: (code: AiProfileDraft['code'], values: Record<string, unknown>) =>
    api.patch<AiProfileDraft>(`/admin/ai/profiles/${code}/draft`, values),
  publishProfile: (code: AiProfileDraft['code'], expectedDraftUpdatedAt: string) =>
    api.post<AiProfileVersion>(`/admin/ai/profiles/${code}/publish`, { expected_draft_updated_at: expectedDraftUpdatedAt }),
  rollbackProfile: (code: AiProfileDraft['code'], version: number, expectedLatestVersion: number) =>
    api.post<AiProfileVersion>(`/admin/ai/profiles/${code}/rollback`, {
      version,
      expected_latest_version: expectedLatestVersion,
    }),
  health: () => api.get<AiHealthSummary>('/admin/ai/health'),
  usage: (days: number) => api.get<AiUsageSummary>('/admin/ai/usage', { days }),
  actionAudits: (params: Record<string, unknown>) => api.getList<AiActionAuditRow>('/admin/ai/action-audits', params),
};
