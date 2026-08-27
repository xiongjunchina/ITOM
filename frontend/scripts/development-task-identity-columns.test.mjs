import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('requirement development exposes sortable task code and registration time', () => {
  const source = read('../src/pages/requirements/ActiveTaskList.tsx');
  assert.match(source, /dataIndex: 'task_code'[\s\S]*?sorter:/);
  assert.match(source, /dataIndex: 'created_at'[\s\S]*?sorter:/);
});

test('project development exposes sortable task code and registration time', () => {
  const source = read('../src/pages/task-management/ProjectDevelopmentTasksPage.tsx');
  assert.match(source, /dataIndex: 'task_code'[\s\S]*?sorter:/);
  assert.match(source, /dataIndex: 'created_at'[\s\S]*?sorter:/);
});

test('Bug and its fix tasks expose sortable grouping or task code and registration time', () => {
  const source = read('../src/pages/task-management/BugListPage.tsx');
  assert.match(source, /dataIndex: 'bug_code'[\s\S]*?sorter:/);
  assert.match(source, /dataIndex: 'created_at'[\s\S]*?sorter:/);
  assert.match(source, /dataIndex: 'task_code'[\s\S]*?sorter:/);
  assert.ok((source.match(/dataIndex: 'created_at'/g) || []).length >= 2);
});
