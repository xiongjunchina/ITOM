import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { before, test } from 'node:test';

let source;

before(async () => {
  source = await readFile(
    new URL('../src/pages/task-management/ProjectDevelopmentTasksPage.tsx', import.meta.url),
    'utf8',
  );
});

test('project task list separates authoritative status from completion percentage', () => {
  assert.match(source, /title: t\('task\.status'\), dataIndex: 'status'/);
  assert.match(source, /title: t\('task\.progress\.percent'\), dataIndex: 'completion_percent'/);
  assert.doesNotMatch(source, /dataIndex: 'latest_progress'/);
});

test('regular progress cannot imply completion and completion is explicit', () => {
  assert.match(source, /<InputNumber min=\{0\} max=\{99\}/);
  assert.match(source, /\{ progress_percent: 100, comment: values\.comment, complete: true \}/);
  assert.match(source, /detail\.capabilities\.complete/);
  assert.doesNotMatch(source, /name="completion_note"/);
});
