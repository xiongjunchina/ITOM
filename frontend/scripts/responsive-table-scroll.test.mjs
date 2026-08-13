import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const appRoot = await readFile(new URL('../src/i18n/AppRoot.tsx', import.meta.url), 'utf8');
const styles = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8');
const sortableTable = await readFile(new URL('../src/components/SortableTable.tsx', import.meta.url), 'utf8');
const appTableContainerRule = styles.match(/\.app-content \.ant-table-wrapper \.ant-table-container \{[^}]*\}/)?.[0] ?? '';

test('the global floating scrollbar enhancer is not mounted', () => {
  assert.doesNotMatch(appRoot, /ResponsiveTableEnhancer/);
  assert.doesNotMatch(styles, /responsive-table__bottom-scroll/);
});

test('all business tables keep the Ant Design sticky scrollbar outside the clipped table container', () => {
  assert.match(styles, /\.app-content \.ant-table-wrapper \{[\s\S]*?overflow: visible;/);
  assert.match(appTableContainerRule, /overflow: visible;/);
  assert.doesNotMatch(appTableContainerRule, /overflow: hidden;/);
  assert.match(styles, /\.app-content \.ant-table-wrapper \.ant-table-sticky-scroll \{[\s\S]*?display: block;/);
  assert.match(styles, /\.sticky-table__body \.ant-table-sticky-scroll \{[\s\S]*?display: block;/);
  assert.doesNotMatch(styles, /\.ant-table-sticky-scroll[\s\S]{0,160}display: none !important/);
});

test('business-list sticky header and scrollbar bind to the real app-content viewport', () => {
  assert.match(sortableTable, /closest<HTMLElement>\('\.app-content'\)/);
  assert.match(sortableTable, /if \(props\.sticky === false\) return false/);
  assert.match(sortableTable, /getContainer: props\.sticky\.getContainer \?\? \(\(\) => appScrollContainer \?\? window\)/);
  assert.match(sortableTable, /if \(appScrollContainer\)[\s\S]*?getContainer: \(\) => appScrollContainer/);
  assert.match(sortableTable, /sticky=\{resolvedSticky\}/);
});
