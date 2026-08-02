import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { after, before, test } from 'node:test';
import { createServer } from 'vite';

let api;
let authStore;
let dict;
let drawer;
let assistantLocale;
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
  drawer = await server.ssrLoadModule('/src/components/assistant/AssistantDrawer.tsx');
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
  event.data.message.content.action_id = '01ASSISTANTACTION000000000000';
  return event;
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

test('valid post-meta error terminal also passes without being treated as success', async () => {
  const events = [
    { type: 'meta', data: { conversation_id: '01CONVERSATION00000000000000' } },
    { type: 'error', data: { code: 'AI_ASSISTANT_UNAVAILABLE', message: 'raw detail' } },
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

test('valid error terminal passes without being treated as success', async () => {
  const events = [
    { type: 'error', data: { code: 'AI_ASSISTANT_UNAVAILABLE', message: 'raw detail' } },
    { type: 'done', data: { finish_reason: 'error' } },
  ];
  assert.deepEqual(await runStream(events), events);
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
