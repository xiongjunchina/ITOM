import assert from 'node:assert/strict';
import test from 'node:test';

import { selectHierarchySafeWbsPage, selectHierarchySafeWbsRows } from '../src/pages/projects/wbsDisplayLimit.ts';
import {
  normalizeWbsMoveRoots,
  resolveWbsDropDestination,
  toggleWbsBranchSelection,
  wbsDropPositionFromRatio,
  wbsSelectionState,
} from '../src/pages/projects/wbsHierarchySelection.ts';

test('WBS display limit uses the rendered depth-first hierarchy instead of interleaved API rows', () => {
  const rows = [
    { id: 'root-a', parent_task_id: null },
    { id: 'child-b', parent_task_id: 'parent-b' },
    { id: 'unselected', parent_task_id: null },
    { id: 'parent-b', parent_task_id: 'root-b' },
    { id: 'root-b', parent_task_id: null },
  ];

  const visible = selectHierarchySafeWbsRows(rows, 2);

  assert.deepEqual(visible.map((row) => row.id), ['root-a', 'unselected']);
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

test('WBS pagination exposes rows 51-75 and adds only the ancestors needed by page two', () => {
  const rows = [
    { id: 'phase', parent_task_id: null },
    ...Array.from({ length: 74 }, (_, index) => ({ id: `task-${index + 1}`, parent_task_id: 'phase' })),
  ];

  const page = selectHierarchySafeWbsPage(rows, 50, 2);

  assert.equal(page.page, 2);
  assert.equal(page.pageCount, 2);
  assert.equal(page.targetCount, 25);
  assert.equal(page.rows.length, 26);
  assert.equal(page.rows[0].id, 'phase');
  assert.equal(page.rows[1].id, 'task-50');
  assert.equal(page.rows.at(-1).id, 'task-74');
});

test('WBS pagination clamps stale pages and all mode returns one complete hierarchy', () => {
  const rows = Array.from({ length: 75 }, (_, index) => ({ id: `task-${index}`, parent_task_id: null }));
  assert.equal(selectHierarchySafeWbsPage(rows, 50, 9).page, 2);
  assert.deepEqual(selectHierarchySafeWbsPage(rows, 'all', 9), {
    rows,
    page: 1,
    pageCount: 1,
    targetCount: 75,
  });
});

test('selecting a WBS parent cascades across the complete hierarchy and keeps locked rows disabled', () => {
  const rows = [
    { id: 'root', parent_task_id: null },
    { id: 'child-a', parent_task_id: 'root' },
    { id: 'grandchild', parent_task_id: 'child-a' },
    { id: 'child-locked', parent_task_id: 'root', completed_locked: true },
    { id: 'other', parent_task_id: null },
  ];

  const selected = toggleWbsBranchSelection(rows, ['other'], 'root', true);
  assert.deepEqual(selected, ['root', 'child-a', 'grandchild', 'other']);
  assert.deepEqual(wbsSelectionState(rows, selected, 'root'), { checked: true, indeterminate: false });
  assert.deepEqual(toggleWbsBranchSelection(rows, selected, 'child-a', false), ['other']);
  assert.deepEqual(wbsSelectionState(rows, ['grandchild'], 'root'), { checked: false, indeterminate: true });
  assert.deepEqual(toggleWbsBranchSelection(rows, [], 'grandchild', true), ['root', 'child-a', 'grandchild']);
});

test('multi-row dragging collapses selected descendants to stable root tasks', () => {
  const rows = [
    { id: 'root-a', parent_task_id: null },
    { id: 'child-a', parent_task_id: 'root-a' },
    { id: 'root-b', parent_task_id: null },
    { id: 'child-b', parent_task_id: 'root-b' },
  ];

  assert.deepEqual(normalizeWbsMoveRoots(rows, ['root-a', 'child-a', 'child-b'], 'child-a'), ['root-a', 'child-b']);
  assert.deepEqual(normalizeWbsMoveRoots(rows, ['root-a'], 'root-b'), ['root-b']);
});

test('WBS row drop zones resolve before, child and after positions without anchoring to moved rows', () => {
  const rows = [
    { id: 'root-a', parent_task_id: null },
    { id: 'root-b', parent_task_id: null },
    { id: 'root-c', parent_task_id: null },
  ];
  const moved = new Set(['root-a']);

  assert.equal(wbsDropPositionFromRatio(0.1), 'before');
  assert.equal(wbsDropPositionFromRatio(0.5), 'inside');
  assert.equal(wbsDropPositionFromRatio(0.9), 'after');
  assert.deepEqual(resolveWbsDropDestination(rows, moved, 'root-b', 'before'), {
    parentTaskId: null, beforeTaskId: 'root-b',
  });
  assert.deepEqual(resolveWbsDropDestination(rows, moved, 'root-b', 'inside'), {
    parentTaskId: 'root-b', beforeTaskId: null,
  });
  assert.deepEqual(resolveWbsDropDestination(rows, moved, 'root-b', 'after'), {
    parentTaskId: null, beforeTaskId: 'root-c',
  });
  assert.equal(resolveWbsDropDestination(rows, moved, 'root-a', 'after'), null);
});
