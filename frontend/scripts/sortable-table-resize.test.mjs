import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/components/SortableTable.tsx', import.meta.url), 'utf8');
const styles = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8');

test('generic lists use the standard mouse column-resize interaction and fixed table layout', () => {
  assert.match(source, /onMouseDown=\{startResize\}/);
  assert.match(source, /document\.addEventListener\('mousemove', move\)/);
  assert.match(source, /tableLayout=\{props\.tableLayout \?\? 'fixed'\}/);
  assert.match(source, /const headerCell = props\.components\?\.header\?\.cell \?\? ResizableHeaderCell/);
});

test('column separator remains visually quiet until the user hovers or focuses it', () => {
  assert.match(styles, /background: transparent;/);
  assert.match(styles, /\.sortable-table__column-resize-handle:hover::after \{ background: rgba\(31, 41, 55, \.35\); \}/);
  assert.doesNotMatch(styles, /background: rgba\(36, 87, 214, \.56\);/);
});
