import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const appRoot = await readFile(new URL('../src/i18n/AppRoot.tsx', import.meta.url), 'utf8');
const styles = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8');

test('the global floating scrollbar enhancer is not mounted', () => {
  assert.doesNotMatch(appRoot, /ResponsiveTableEnhancer/);
  assert.doesNotMatch(styles, /responsive-table__bottom-scroll/);
});

test('all business tables keep the Ant Design sticky scrollbar outside the clipped table container', () => {
  assert.match(styles, /\.app-content \.ant-table-wrapper \{[\s\S]*?overflow: visible;/);
  assert.match(styles, /\.app-content \.ant-table-wrapper \.ant-table-container \{[\s\S]*?overflow: hidden;/);
  assert.match(styles, /\.app-content \.ant-table-wrapper \.ant-table-sticky-scroll \{[\s\S]*?display: block;/);
  assert.match(styles, /\.sticky-table__body \.ant-table-sticky-scroll \{[\s\S]*?display: block;/);
  assert.doesNotMatch(styles, /\.ant-table-sticky-scroll[\s\S]{0,160}display: none !important/);
});
