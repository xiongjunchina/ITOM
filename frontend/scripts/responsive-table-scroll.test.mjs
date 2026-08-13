import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/components/ResponsiveTableEnhancer.tsx', import.meta.url), 'utf8');
const styles = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8');

test('wide tables are measured only after the enhancer has created controllers', () => {
  const controllerCreation = source.indexOf('controllers.set(wrapper, createController');
  const overflowMeasurement = source.indexOf('const wideWrappers = wrappers.filter');
  assert.ok(controllerCreation >= 0, 'controller creation must exist');
  assert.ok(overflowMeasurement > controllerCreation, 'overflow must be measured after enhanced styles are active');
});

test('native horizontal scrolling remains available until the floating scrollbar is visible', () => {
  assert.match(source, /wrapper\.classList\.toggle\('responsive-table--floating-scroll-active', visible\)/);
  assert.match(styles, /\.responsive-table--enhanced \.ant-table-body,[\s\S]*?overflow-x: auto !important;/);
  assert.match(styles, /\.responsive-table--floating-scroll-active \.ant-table-body,[\s\S]*?overflow-x: hidden !important;/);
  assert.doesNotMatch(styles, /^\.responsive-table--enhanced \.ant-table-body::/m);
  assert.doesNotMatch(styles, /^\.responsive-table--enhanced \.ant-table-sticky-scroll/m);
  assert.match(styles, /^\.responsive-table--floating-scroll-active \.ant-table-sticky-scroll/m);
});
