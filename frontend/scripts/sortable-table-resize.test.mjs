import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/components/SortableTable.tsx', import.meta.url), 'utf8');
const styles = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8');

test('generic lists retain a pointer-captured resize interaction across React rerenders', () => {
  assert.match(source, /event\.currentTarget\.setPointerCapture\(event\.pointerId\)/);
  assert.match(source, /onPointerMove=\{resize\}/);
  assert.match(source, /onPointerUp=\{stopResize\}/);
  assert.match(source, /onLostPointerCapture=\{stopResize\}/);
  assert.match(source, /onClick=\{\(event\) => \{/);
  assert.match(source, /tableLayout=\{props\.tableLayout \?\? 'fixed'\}/);
  assert.match(source, /const headerCell = props\.components\?\.header\?\.cell \?\? ResizableHeaderCell/);
});

test('column separator remains visually quiet until the user hovers or focuses it', () => {
  assert.match(styles, /background: transparent;/);
  assert.match(styles, /right: 0;/);
  assert.match(styles, /\.sortable-table__column-resize-handle:hover::after \{ background: rgba\(31, 41, 55, \.35\); \}/);
  assert.doesNotMatch(styles, /background: rgba\(36, 87, 214, \.56\);/);
});
