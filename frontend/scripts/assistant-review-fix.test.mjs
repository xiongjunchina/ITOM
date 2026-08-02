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
} = {}) {
  return {
    type: 'message',
    data: {
      message: {
        id: '01ASSISTANTMESSAGE0000000000',
        role: 'assistant',
        content: {
          text,
          advisory_text: advisoryText,
          authority,
          operation_status: authority === 'advisory' ? 'not_executed' : 'prepared_not_executed',
        },
        status: 'completed',
      },
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
