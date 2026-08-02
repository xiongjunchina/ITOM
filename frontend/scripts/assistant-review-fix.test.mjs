import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { after, before, test } from 'node:test';
import { createServer } from 'vite';

let api;
let authStore;
let dict;
let drawer;
let adminPage;
let assistantLocale;
let adminLocale;
let server;

before(async () => {
  server = await createServer({
    root: process.cwd(),
    appType: 'custom',
    logLevel: 'silent',
    server: { middlewareMode: true },
  });
  api = await server.ssrLoadModule('/src/api/assistant.ts');
  ({ useAuthStore: authStore } = await server.ssrLoadModule('/src/stores/auth.ts'));
  ({ DICT: dict } = await server.ssrLoadModule('/src/i18n/dict.ts'));
  assistantLocale = await server.ssrLoadModule('/src/i18n/locales/assistant.ts');
  adminLocale = await server.ssrLoadModule('/src/i18n/locales/admin.ts');
  drawer = await server.ssrLoadModule('/src/components/assistant/AssistantDrawer.tsx');
  adminPage = await server.ssrLoadModule('/src/pages/admin/AiAssistant.tsx');
  authStore.setState({ token: 'focused-test-token' });
});

after(async () => {
  await server?.close();
});

function frame(type, data) {
  return `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
}

function messageEvent({
  text = 'Advice only. No ITOM action was executed.',
  advisoryText = 'Check the service request status first.',
  authority = 'advisory',
  operationStatus = authority === 'advisory' ? 'not_executed' : 'prepared_not_executed',
  role = 'assistant',
  status = 'completed',
} = {}) {
  return {
    type: 'message',
    data: {
      message: {
        id: '01ASSISTANTMESSAGE0000000000',
        role,
        content: {
          text,
          advisory_text: advisoryText,
          authority,
          operation_status: operationStatus,
        },
        status,
      },
    },
  };
}

function serverPreviewMessageEvent({
  text = 'A server preview was prepared. Nothing has been executed.',
  actionId = '01ARZ3NDEKTSV4RRFFQ69G5FAV',
  authority = 'server_preview',
  operationStatus = 'prepared_not_executed',
  role = 'assistant',
  status = 'completed',
} = {}) {
  const event = messageEvent({
    text,
    advisoryText: undefined,
    authority,
    operationStatus,
    role,
    status,
  });
  delete event.data.message.content.advisory_text;
  event.data.message.content.action_id = actionId;
  return event;
}

function actionEvent({
  actionId = '01ARZ3NDEKTSV4RRFFQ69G5FAV',
  risk = 'L3',
} = {}) {
  return {
    type: 'action',
    data: {
      action_id: actionId,
      risk,
      preview: { title: 'Server-owned preview' },
      confirmation_token: 'one-time-confirmation-token',
      expires_at: '2026-08-02T12:00:00Z',
    },
  };
}

async function runStream(events) {
  const body = events.map((event) => frame(event.type, event.data)).join('');
  globalThis.fetch = async () => new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
  });
  const delivered = [];
  await api.streamAssistantMessage({
    conversationId: '01CONVERSATION00000000000000',
    content: 'help',
    clientMessageId: '01CLIENTMESSAGE0000000000000',
    pageContext: { route: '/', selected_ids: [] },
    onEvent: (event) => delivered.push(event),
  });
  return delivered;
}

async function runPresentedStream(events) {
  const body = events.map((event) => frame(event.type, event.data)).join('');
  globalThis.fetch = async () => new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
  });
  const delivered = [];
  await api.streamAssistantMessage({
    conversationId: '01CONVERSATION00000000000000',
    content: 'help',
    clientMessageId: '01CLIENTMESSAGE0000000000000',
    pageContext: { route: '/', selected_ids: [] },
    onEvent: (event) => {
      if (event.type === 'message') drawer.presentAssistantServerMessage(event.data.message);
      delivered.push(event);
    },
  });
  return delivered;
}

function expectStreamError(code) {
  return (error) => error instanceof api.AssistantStreamError && error.code === code;
}

function preparedActionItem(id, token) {
  return {
    kind: 'action',
    id,
    action: {
      action_id: id.replace(/^action-/, ''),
      risk: 'L3',
      preview: { title: id },
      confirmation_token: token,
      confirmation_expires_at: null,
      status: 'prepared',
    },
  };
}

test('failed-turn cleanup removes only explicitly tracked provisional output and its token', () => {
  assert.equal(
    typeof drawer.discardFailedAssistantTurn,
    'function',
    'AssistantDrawer does not yet expose explicit failed-turn cleanup',
  );
  const priorMessage = { kind: 'message', id: 'assistant-prior', role: 'assistant', text: 'Prior complete answer.' };
  const priorAction = preparedActionItem('action-prior', 'prior-token');
  const currentUser = { kind: 'message', id: 'user-current', role: 'user', text: 'Current question.' };
  const currentDelta = { kind: 'message', id: 'stream-current', role: 'assistant', text: 'The operation succeeded.', streaming: true };
  const currentMessage = { kind: 'message', id: 'assistant-current', role: 'assistant', text: 'The operation succeeded.' };
  const currentAction = preparedActionItem('action-current', 'current-turn-raw-token');
  const safeNotice = { kind: 'message', id: 'stream-error-current', role: 'system', text: 'This turn stopped safely. No action is proven.', error: true };

  const cleaned = drawer.discardFailedAssistantTurn(
    [priorMessage, priorAction, currentUser, currentDelta, currentMessage, currentAction],
    new Set(['stream-current', 'assistant-current', 'action-current']),
    safeNotice,
  );

  assert.deepEqual(cleaned, [priorMessage, priorAction, currentUser, safeNotice]);
  assert.equal(JSON.stringify(cleaned).includes('current-turn-raw-token'), false);
});

test('repeated failed-turn cleanup keeps exactly one safe notice', () => {
  assert.equal(typeof drawer.discardFailedAssistantTurn, 'function');
  const prior = { kind: 'message', id: 'assistant-prior', role: 'assistant', text: 'Prior complete answer.' };
  const currentUser = { kind: 'message', id: 'user-current', role: 'user', text: 'Current question.' };
  const safeNotice = { kind: 'message', id: 'stream-error-current', role: 'system', text: 'This turn stopped safely. No action is proven.', error: true };
  const first = drawer.discardFailedAssistantTurn(
    [prior, currentUser, { kind: 'message', id: 'stream-current', role: 'assistant', text: 'partial', streaming: true }],
    new Set(['stream-current']),
    safeNotice,
  );
  const second = drawer.discardFailedAssistantTurn(first, new Set(['stream-current']), safeNotice);

  assert.deepEqual(second, [prior, currentUser, safeNotice]);
  assert.equal(second.filter((item) => item.id === safeNotice.id).length, 1);
});

test('conversation timeline maps each current sending state to action interaction state', () => {
  assert.equal(
    typeof drawer.AssistantConversationTimeline,
    'function',
    'AssistantDrawer does not yet expose the production timeline boundary',
  );
  const props = {
    items: [preparedActionItem('action-current', 'current-token')],
    onStart() {},
    onActionChange() {},
    onNavigate() {},
  };

  assert.equal(drawer.AssistantConversationTimeline({ ...props, sending: true }).props.actionInteractionDisabled, true);
  assert.equal(drawer.AssistantConversationTimeline({ ...props, sending: false }).props.actionInteractionDisabled, false);
});

test('advisory presentation keeps the real answer and the no-action authority notice visible', () => {
  assert.equal(
    typeof drawer.presentAssistantServerMessage,
    'function',
    'AssistantDrawer does not yet expose the production advisory presentation contract',
  );
  const presentation = drawer.presentAssistantServerMessage(messageEvent().data.message);
  assert.deepEqual(presentation, {
    text: 'Check the service request status first.',
    authority: 'advisory',
    authorityNotice: 'Advice only. No ITOM action was executed.',
  });
});

test('server preview presentation accepts only the server-owned prepared but unexecuted message', () => {
  assert.deepEqual(
    drawer.presentAssistantServerMessage(serverPreviewMessageEvent().data.message),
    {
      text: 'A server preview was prepared. Nothing has been executed.',
      authority: 'server_preview',
    },
  );
});

test('the production action-expiry boundary rejects naive UTC and preserves a ten-minute UTC deadline for Asia/Shanghai', () => {
  assert.equal(
    typeof drawer.parseAssistantActionExpiry,
    'function',
    'AssistantDrawer does not yet expose the production action-expiry boundary',
  );
  const serverNow = Date.parse('2030-01-01T00:00:00Z');
  const originalNaiveUtc = '2030-01-01T00:10:00';
  const canonicalUtc = '2030-01-01T00:10:00Z';

  // A browser in Asia/Shanghai treats the old offset-free server value as local time.
  assert.equal(Date.parse(`${originalNaiveUtc}+08:00`) - serverNow, -470 * 60 * 1000);
  assert.throws(
    () => drawer.parseAssistantActionExpiry(originalNaiveUtc),
    expectStreamError('AI_ASSISTANT_STREAM_PAYLOAD'),
  );
  assert.equal(drawer.parseAssistantActionExpiry(canonicalUtc) - serverNow, 10 * 60 * 1000);
});

test('replayed previews reject an invalid action id before rendering and in the completed-message presenter', async () => {
  const invalid = serverPreviewMessageEvent({ actionId: 'not-a-valid-action-id' });
  await assert.rejects(
    runPresentedStream([
      { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
      invalid,
      { type: 'done', data: { finish_reason: 'replay' } },
    ]),
    expectStreamError('AI_ASSISTANT_STREAM_PAYLOAD'),
  );
  assert.throws(
    () => drawer.presentAssistantServerMessage(invalid.data.message),
    expectStreamError('AI_ASSISTANT_STREAM_PAYLOAD'),
  );
});

for (const [name, mutation] of [
  ['unexpected authority', { authority: 'unexpected', operationStatus: 'succeeded' }],
  ['advisory with succeeded status', { operationStatus: 'succeeded' }],
  ['non-completed message', { status: 'streaming' }],
  ['non-assistant message', { role: 'user' }],
]) {
  test(`${name} fails the production message path closed`, async () => {
    await assert.rejects(
      runPresentedStream([
        { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
        messageEvent(mutation),
        { type: 'done', data: { finish_reason: 'stop' } },
      ]),
      expectStreamError('AI_ASSISTANT_STREAM_PAYLOAD'),
    );
  });
}

for (const [name, field] of [
  ['missing authority', 'authority'],
  ['advisory with missing operation status', 'operation_status'],
]) {
  test(`${name} fails the production message path closed`, async () => {
    const event = messageEvent();
    delete event.data.message.content[field];
    await assert.rejects(
      runPresentedStream([
        { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
        event,
        { type: 'done', data: { finish_reason: 'stop' } },
      ]),
      expectStreamError('AI_ASSISTANT_STREAM_PAYLOAD'),
    );
  });
}

test('server preview rejects model advisory prose instead of rendering it as authority', async () => {
  const event = serverPreviewMessageEvent();
  event.data.message.content.advisory_text = 'The model says the operation succeeded.';
  await assert.rejects(
    runPresentedStream([
      { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
      event,
      { type: 'done', data: { finish_reason: 'stop' } },
    ]),
    expectStreamError('AI_ASSISTANT_STREAM_PAYLOAD'),
  );
});

test('server preview with an executed status fails closed', async () => {
  await assert.rejects(
    runPresentedStream([
      { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
      serverPreviewMessageEvent({ operationStatus: 'succeeded' }),
      { type: 'done', data: { finish_reason: 'stop' } },
    ]),
    expectStreamError('AI_ASSISTANT_STREAM_PAYLOAD'),
  );
});

for (const [name, mutate] of [
  ['empty message id', (message) => { message.id = '   '; }],
  ['extra message envelope field', (message) => { message.unexpected = 'accepted'; }],
  ['extra advisory content field', (message) => { message.content.unexpected = 'accepted'; }],
  ['empty advisory answer', (message) => { message.content.advisory_text = '   '; }],
  ['empty no-execution notice', (message) => { message.content.text = '   '; }],
  ['server preview without action id', (message) => { delete message.content.action_id; }],
]) {
  test(`${name} is rejected by the exact completed assistant envelope`, async () => {
    const event = name.startsWith('server preview') ? serverPreviewMessageEvent() : messageEvent();
    mutate(event.data.message);
    await assert.rejects(
      runPresentedStream([
        { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
        event,
        { type: 'done', data: { finish_reason: 'stop' } },
      ]),
      expectStreamError('AI_ASSISTANT_STREAM_PAYLOAD'),
    );
  });
}

test('stream error presentation ignores raw server details and uses the localized safe text', () => {
  assert.equal(
    typeof drawer.safeAssistantStreamErrorDetail,
    'function',
    'AssistantDrawer does not yet expose the safe error presentation contract',
  );
  assert.equal(
    drawer.safeAssistantStreamErrorDetail(
      { code: 'AI_ASSISTANT_UNAVAILABLE', message: '数据库口令与中文内部错误详情' },
      'This turn stopped safely.',
    ),
    'This turn stopped safely.',
  );
});

test('valid normal stream with meta, message and stop terminal passes', async () => {
  const events = [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    { type: 'delta', data: { text: 'Advice only. No ITOM action was executed.' } },
    messageEvent(),
    { type: 'done', data: { finish_reason: 'stop' } },
  ];
  assert.deepEqual(await runStream(events), events);
});

test('valid post-start error stream accepts meta, error and error terminal', async () => {
  const events = [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    { type: 'error', data: { code: 'AI_ASSISTANT_UNAVAILABLE', message: 'raw detail', fallback_path: '/intake' } },
    { type: 'done', data: { finish_reason: 'error' } },
  ];
  assert.deepEqual(await runStream(events), events);
});

test('valid replay stream requires and accepts the persisted message', async () => {
  const events = [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    messageEvent(),
    { type: 'done', data: { finish_reason: 'replay' } },
  ];
  assert.deepEqual(await runStream(events), events);
});

test('valid replayed server preview stays informational without an action or token', async () => {
  const events = [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    serverPreviewMessageEvent(),
    { type: 'done', data: { finish_reason: 'replay' } },
  ];
  const delivered = await runPresentedStream(events);
  assert.deepEqual(delivered, events);
  assert.equal(delivered.some((event) => event.type === 'action'), false);
  assert.equal(JSON.stringify(delivered).includes('confirmation_token'), false);
});

test('valid error terminal passes without being treated as success', async () => {
  const events = [
    { type: 'error', data: { code: 'AI_ASSISTANT_UNAVAILABLE', message: 'raw detail' } },
    { type: 'done', data: { finish_reason: 'error' } },
  ];
  assert.deepEqual(await runStream(events), events);
});

for (const [name, events] of [
  ['error after delta', [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    { type: 'delta', data: { text: 'provisional text' } },
    { type: 'error', data: { code: 'AI_ASSISTANT_UNAVAILABLE' } },
    { type: 'done', data: { finish_reason: 'error' } },
  ]],
  ['error after action', [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    actionEvent(),
    { type: 'error', data: { code: 'AI_ASSISTANT_UNAVAILABLE' } },
    { type: 'done', data: { finish_reason: 'error' } },
  ]],
  ['error after completed message', [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    messageEvent(),
    { type: 'error', data: { code: 'AI_ASSISTANT_UNAVAILABLE' } },
    { type: 'done', data: { finish_reason: 'error' } },
  ]],
  ['post-start error with success terminal', [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    { type: 'error', data: { code: 'AI_ASSISTANT_UNAVAILABLE' } },
    { type: 'done', data: { finish_reason: 'stop' } },
  ]],
  ['preview replay containing an action', [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    actionEvent(),
    serverPreviewMessageEvent(),
    { type: 'done', data: { finish_reason: 'replay' } },
  ]],
  ['preview replay containing a delta', [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    { type: 'delta', data: { text: 'must not be replayed' } },
    serverPreviewMessageEvent(),
    { type: 'done', data: { finish_reason: 'replay' } },
  ]],
]) {
  test(`${name} fails the exact error and replay grammar closed`, async () => {
    await assert.rejects(
      runStream(events),
      expectStreamError('AI_ASSISTANT_STREAM_TERMINAL'),
    );
  });
}

test('valid L3 preview binds one action to the matching server preview', async () => {
  const events = [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    actionEvent(),
    { type: 'delta', data: { text: 'A preview is ready.' } },
    serverPreviewMessageEvent(),
    { type: 'done', data: { finish_reason: 'stop' } },
  ];
  assert.deepEqual(await runPresentedStream(events), events);
});

for (const [name, events] of [
  ['action followed by advisory terminal', [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    actionEvent(),
    messageEvent(),
    { type: 'done', data: { finish_reason: 'stop' } },
  ]],
  ['action and preview with different action ids', [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    actionEvent({ actionId: '01ARZ3NDEKTSV4RRFFQ69G5FAV' }),
    serverPreviewMessageEvent({ actionId: '01BX5ZZKBKACTAV9WEVGEMMVS0' }),
    { type: 'done', data: { finish_reason: 'stop' } },
  ]],
  ['two actions before one preview', [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    actionEvent({ actionId: '01ARZ3NDEKTSV4RRFFQ69G5FAV' }),
    actionEvent({ actionId: '01BX5ZZKBKACTAV9WEVGEMMVS0' }),
    serverPreviewMessageEvent({ actionId: '01BX5ZZKBKACTAV9WEVGEMMVS0' }),
    { type: 'done', data: { finish_reason: 'stop' } },
  ]],
  ['preview without an action', [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    serverPreviewMessageEvent(),
    { type: 'done', data: { finish_reason: 'stop' } },
  ]],
  ['action after advisory delta', [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    { type: 'delta', data: { text: 'Advice first.' } },
    actionEvent(),
    serverPreviewMessageEvent(),
    { type: 'done', data: { finish_reason: 'stop' } },
  ]],
  ['action with non-L3 risk', [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    actionEvent({ risk: 'L2' }),
    serverPreviewMessageEvent(),
    { type: 'done', data: { finish_reason: 'stop' } },
  ]],
  ['action with invalid action id', [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    actionEvent({ actionId: 'not-a-valid-id' }),
    serverPreviewMessageEvent({ actionId: 'not-a-valid-id' }),
    { type: 'done', data: { finish_reason: 'stop' } },
  ]],
]) {
  test(`${name} fails the complete turn grammar closed`, async () => {
    await assert.rejects(
      runStream(events),
      expectStreamError('AI_ASSISTANT_STREAM_TERMINAL'),
    );
  });
}

test('latest-request guard rejects stale success, error and finally writes', () => {
  assert.equal(
    typeof adminPage.createLatestRequestGuard,
    'function',
    'AI admin panels do not yet expose a shared request-generation guard',
  );
  const guard = adminPage.createLatestRequestGuard();
  const older = guard.begin();
  const latest = guard.begin();
  const state = { data: 'latest-pending', error: false, loading: true };

  assert.equal(guard.runIfCurrent(older, () => { state.data = 'stale-success'; }), false);
  assert.equal(guard.runIfCurrent(older, () => { state.error = true; }), false);
  assert.equal(guard.runIfCurrent(older, () => { state.loading = false; }), false);
  assert.deepEqual(state, { data: 'latest-pending', error: false, loading: true });

  assert.equal(guard.runIfCurrent(latest, () => { state.data = 'latest-success'; }), true);
  assert.equal(guard.runIfCurrent(latest, () => { state.loading = false; }), true);
  assert.deepEqual(state, { data: 'latest-success', error: false, loading: false });
});

test('latest-request guard invalidation blocks writes after unmount', () => {
  assert.equal(typeof adminPage.createLatestRequestGuard, 'function');
  const guard = adminPage.createLatestRequestGuard();
  const request = guard.begin();
  let writes = 0;
  guard.invalidate();

  assert.equal(guard.runIfCurrent(request, () => { writes += 1; }), false);
  assert.equal(writes, 0);
});

test('known action-audit statuses map to explicit bilingual translation keys', () => {
  assert.equal(
    typeof adminPage.actionAuditStatusTranslationKey,
    'function',
    'Action audit statuses do not yet use explicit translation keys',
  );
  const expected = {
    prepared: 'admin.ai.audit.status.prepared',
    executing: 'admin.ai.audit.status.executing',
    succeeded: 'admin.ai.audit.status.succeeded',
    cancelled: 'admin.ai.audit.status.cancelled',
    expired: 'admin.ai.audit.status.expired',
    failed: 'admin.ai.audit.status.failed',
  };
  for (const [status, key] of Object.entries(expected)) {
    assert.equal(adminPage.actionAuditStatusTranslationKey(status), key);
    assert.equal(typeof adminLocale.zh[key], 'string');
    assert.equal(typeof adminLocale.en[key], 'string');
  }
  assert.equal(adminPage.actionAuditStatusTranslationKey('future_server_status'), undefined);
  assert.equal(adminPage.actionAuditStatusTranslationKey('__proto__'), undefined);
});

test('lone done terminal is rejected as premature', async () => {
  await assert.rejects(
    runStream([{ type: 'done', data: { finish_reason: 'stop' } }]),
    expectStreamError('AI_ASSISTANT_STREAM_TERMINAL'),
  );
});

test('done without a finish reason is rejected', async () => {
  await assert.rejects(
    runStream([
      { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
      messageEvent(),
      { type: 'done', data: {} },
    ]),
    expectStreamError('AI_ASSISTANT_STREAM_TERMINAL'),
  );
});

test('done with an unknown finish reason is rejected', async () => {
  await assert.rejects(
    runStream([
      { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
      messageEvent(),
      { type: 'done', data: { finish_reason: 'length' } },
    ]),
    expectStreamError('AI_ASSISTANT_STREAM_TERMINAL'),
  );
});

test('done with an extra terminal key is rejected', async () => {
  await assert.rejects(
    runStream([
      { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
      messageEvent(),
      { type: 'done', data: { finish_reason: 'stop', unexpected: 'accepted' } },
    ]),
    expectStreamError('AI_ASSISTANT_STREAM_TERMINAL'),
  );
});

test('error followed by a non-error terminal is rejected', async () => {
  await assert.rejects(
    runStream([
      { type: 'error', data: { code: 'AI_ASSISTANT_UNAVAILABLE', message: 'raw detail' } },
      { type: 'done', data: { finish_reason: 'stop' } },
    ]),
    expectStreamError('AI_ASSISTANT_STREAM_TERMINAL'),
  );
});

test('replay terminal without a prior replay message is rejected', async () => {
  await assert.rejects(
    runStream([
      { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
      { type: 'done', data: { finish_reason: 'replay' } },
    ]),
    expectStreamError('AI_ASSISTANT_STREAM_TERMINAL'),
  );
});

test('events after a terminal remain rejected', async () => {
  await assert.rejects(
    runStream([
      { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
      messageEvent(),
      { type: 'done', data: { finish_reason: 'stop' } },
      { type: 'delta', data: { text: 'late' } },
    ]),
    expectStreamError('AI_ASSISTANT_STREAM_AFTER_DONE'),
  );
});

test('assistant Chinese and English dictionaries have exact key parity', () => {
  assert.deepEqual(
    Object.keys(assistantLocale.zh).sort(),
    Object.keys(assistantLocale.en).sort(),
  );
});

test('literal translation keys used by corrected assistant components exist in both dictionaries', async () => {
  const files = [
    'src/components/assistant/AssistantDrawer.tsx',
    'src/components/assistant/AssistantMessageList.tsx',
  ];
  const keys = new Set();
  const literalCall = /\bt\(\s*(['"])([^'"]+)\1/g;
  for (const file of files) {
    const source = await readFile(file, 'utf8');
    for (const match of source.matchAll(literalCall)) keys.add(match[2]);
  }
  const missing = [...keys].filter((key) => !(key in dict.zh) || !(key in dict.en)).sort();
  assert.deepEqual(missing, []);
});
