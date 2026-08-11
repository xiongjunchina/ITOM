import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { after, before, test } from 'node:test';
import { createServer } from 'vite';

let server;
let tabs;
let assistantContext;
let developmentPageSource;

before(async () => {
  server = await createServer({
    root: process.cwd(),
    appType: 'custom',
    logLevel: 'silent',
    server: { middlewareMode: true },
  });
  tabs = await server.ssrLoadModule('/src/pages/task-management/developmentTaskTabs.ts');
  assistantContext = await server.ssrLoadModule('/src/components/assistant/AssistantContext.ts');
  developmentPageSource = await readFile(
    new URL('../src/pages/task-management/DevelopmentTasksPage.tsx', import.meta.url),
    'utf8',
  );
});

after(async () => {
  await server?.close();
});

test('project query selects the project development panel', () => {
  assert.equal(tabs.resolveDevelopmentTaskTab('project'), 'project');
  assert.equal(tabs.resolveDevelopmentTaskTab('bug'), 'bug');
  assert.equal(tabs.resolveDevelopmentTaskTab('requirement'), 'requirement');
});

test('the development page wires the resolved project tab to the project task component', () => {
  assert.match(
    developmentPageSource,
    /const active = resolveDevelopmentTaskTab\(searchParams\.get\('tab'\)\);/,
  );
  assert.match(
    developmentPageSource,
    /key: 'project',[\s\S]*children: <ProjectDevelopmentTasksPage \/>/,
  );
});

test('missing or unknown development tab safely falls back to requirement development', () => {
  assert.equal(tabs.resolveDevelopmentTaskTab(null), 'requirement');
  assert.equal(tabs.resolveDevelopmentTaskTab('unknown'), 'requirement');
});

test('the web assistant preserves project as an approved development-task tab', () => {
  assert.deepEqual(
    assistantContext.buildAssistantPageContext('/task-management/development', { tab: 'project' }),
    {
      route: '/task-management/development',
      page_type: 'development_tasks',
      selected_ids: [],
      tab: 'project',
    },
  );
});
