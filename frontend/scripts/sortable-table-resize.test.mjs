import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/components/SortableTable.tsx', import.meta.url), 'utf8');
const styles = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8');

test('generic lists retain both pointer and mouse resize interactions across React rerenders', () => {
  assert.match(source, /event\.currentTarget\.setPointerCapture\(event\.pointerId\)/);
  assert.match(source, /onPointerMove=\{resizePointer\}/);
  assert.match(source, /onPointerUp=\{stopPointerResize\}/);
  assert.match(source, /onLostPointerCapture=\{stopPointerResize\}/);
  assert.match(source, /onMouseDown=\{startMouseResize\}/);
  assert.match(source, /document\.addEventListener\('mousemove', move\)/);
  assert.match(source, /document\.addEventListener\('mouseup', up, \{ once: true \}\)/);
  assert.match(source, /kind: 'pointer' \| 'mouse';/);
  assert.match(source, /columnElements: HTMLTableColElement\[\];/);
  assert.match(source, /querySelectorAll<HTMLTableColElement>\('colgroup col'\)\[columnIndex\]/);
  assert.match(source, /column\.style\.width = `\$\{nextWidth\}px`;/);
  assert.match(source, /if \(drag\.lastWidth !== drag\.startWidth\) \{/);
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
