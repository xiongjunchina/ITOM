import assert from 'node:assert/strict';
import test from 'node:test';

import { selectHierarchySafeWbsRows } from '../src/pages/projects/wbsDisplayLimit.ts';

test('WBS display limit keeps source order and adds ancestors beyond the selected limit', () => {
  const rows = [
    { id: 'root-a', parent_task_id: null },
    { id: 'child-b', parent_task_id: 'parent-b' },
    { id: 'unselected', parent_task_id: null },
    { id: 'parent-b', parent_task_id: 'root-b' },
    { id: 'root-b', parent_task_id: null },
  ];

  const visible = selectHierarchySafeWbsRows(rows, 2);

  assert.deepEqual(visible.map((row) => row.id), ['root-a', 'child-b', 'parent-b', 'root-b']);
});

test('WBS display limit returns the selected count when no extra ancestors are needed', () => {
  const rows = Array.from({ length: 205 }, (_, index) => ({
    id: `task-${index + 1}`,
    parent_task_id: null,
  }));

  assert.equal(selectHierarchySafeWbsRows(rows, 50).length, 50);
  assert.equal(selectHierarchySafeWbsRows(rows, 100).length, 100);
  assert.equal(selectHierarchySafeWbsRows(rows, 200).length, 200);
  assert.equal(selectHierarchySafeWbsRows(rows, 'all').length, 205);
});

test('WBS display limit stops safely when persisted hierarchy contains a cycle or missing parent', () => {
  const rows = [
    { id: 'child', parent_task_id: 'missing' },
    { id: 'cycle-a', parent_task_id: 'cycle-b' },
    { id: 'cycle-b', parent_task_id: 'cycle-a' },
  ];

  assert.deepEqual(
    selectHierarchySafeWbsRows(rows, 50).map((row) => row.id),
    ['child', 'cycle-a', 'cycle-b'],
  );
});
