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
  assert.match(source, /headerCell\.closest\('\.ant-table-wrapper'\)/);
  assert.match(source, /fixedFollowers: Array<\{ element: HTMLElement; startLeft: number \}>;/);
  assert.match(source, /querySelectorAll<HTMLTableColElement>\('colgroup col'\)\[columnIndex\]/);
  assert.match(source, /column\.style\.width = `\$\{nextWidth\}px`;/);
  assert.match(source, /element\.style\.left = `\$\{startLeft \+ delta\}px`;/);
  assert.match(source, /if \(drag\.lastWidth !== drag\.startWidth\) \{/);
  assert.match(source, /onClick=\{\(event\) => \{/);
  assert.match(source, /tableLayout=\{props\.tableLayout \?\? 'fixed'\}/);
  assert.match(source, /const headerCell = props\.components\?\.header\?\.cell \?\? ResizableHeaderCell/);
});

test('default widths follow rendered header and current row content without spare-column stretching', () => {
  assert.match(source, /function estimatedContentColumnWidth<T extends object>/);
  assert.match(source, /function measureRenderedColumnWidths\(anchor: HTMLElement, actionKeys: Set<string>\)/);
  assert.match(source, /querySelectorAll<HTMLElement>\('\[data-sortable-column-key\]'\)/);
  assert.match(source, /clone\.classList\.remove\([\s\S]*?'ant-table-cell-ellipsis'/);
  assert.match(source, /'width:max-content'/);
  assert.match(source, /setMeasuredAutoWidths\(\(current\) => sameWidths\(current, nextWidths\) \? current : nextWidths\)/);
  assert.match(source, /measuredAutoWidths\[key\] \?\? estimatedContentColumnWidth\(column, rows\)/);
  assert.match(source, /ellipsis: manuallySized \? source\.ellipsis : false/);
  assert.match(source, /'sortable-table__auto-width-cell'/);
  assert.doesNotMatch(source, /widths\[stretch\.key\] \+= extra/);
  assert.match(source, /const measuredWidth = Object\.values\(displayWidths\)\.reduce/);
  assert.match(source, /x: Math\.max\(1, measuredWidth\)/);
  assert.match(source, /scroll=\{resolvedScroll\}/);
  assert.match(styles, /\.sortable-table--unified \.ant-table-thead > tr > th \{[\s\S]*?white-space: nowrap;/);
  assert.match(styles, /\.sortable-table--unified \.ant-table-container table \{[\s\S]*?min-width: 0 !important;/);
  assert.match(styles, /\.sortable-table--unified \.sortable-table__auto-width-cell \{[\s\S]*?white-space: nowrap;/);
  assert.match(styles, /\.sortable-table__measure-host \{/);
});

test('only explicit user resizing overrides later data-driven defaults', () => {
  assert.match(source, /manual_widths\?: string\[\];/);
  assert.match(source, /manualWidthKeys\.has\(key\)/);
  assert.match(source, /manual_widths: Array\.from\(new Set\(\[\.\.\.\(viewConfigRef\.current\.manual_widths \?\? \[\]\), key\]\)\)/);
  assert.match(source, /saved\?\.manual_widths != null/);
  assert.match(source, /Math\.abs\(saved\.widths\[key\] - \(legacyDefaultWidths\[key\] \?\? 0\)\) > 1/);
  assert.match(source, /manual_widths: \[\]/);
});

test('wide business lists freeze the first two business columns and keep selection fixed', () => {
  assert.match(source, /freezeColumns = 2/);
  assert.match(source, /slice\(0, Math\.max\(0, freezeColumns\)\)/);
  assert.match(source, /source\.fixed \?\? \(defaultFrozenKeys\.includes\(key\) \? 'left' : undefined\)/);
  assert.match(source, /rowSelection=\{props\.rowSelection \? \{ \.\.\.props\.rowSelection, fixed: props\.rowSelection\.fixed \?\? true \} : undefined\}/);
  assert.match(styles, /\.sortable-table__fixed-left-cell\.ant-table-cell-fix-left \{[\s\S]*?background: #fff;/);
  assert.match(styles, /\.sortable-table__fixed-left-cell\.ant-table-cell-fix-left-last \{[\s\S]*?box-shadow:/);
});

test('column separator remains visually quiet until the user hovers or focuses it', () => {
  assert.match(styles, /background: transparent;/);
  assert.match(styles, /right: 0;/);
  assert.match(styles, /\.sortable-table__column-resize-handle:hover::after \{ background: rgba\(31, 41, 55, \.35\); \}/);
  assert.doesNotMatch(styles, /background: rgba\(36, 87, 214, \.56\);/);
});
