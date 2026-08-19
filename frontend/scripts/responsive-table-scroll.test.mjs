import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const appRoot = await readFile(new URL('../src/i18n/AppRoot.tsx', import.meta.url), 'utf8');
const styles = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8');
const enhancer = await readFile(new URL('../src/components/ResponsiveTableEnhancer.tsx', import.meta.url), 'utf8');
const sortableTable = await readFile(new URL('../src/components/SortableTable.tsx', import.meta.url), 'utf8');
const appTableContainerRule = styles.match(/\.app-content \.ant-table-wrapper \.ant-table-container \{[^}]*\}/)?.[0] ?? '';

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.(?:ts|tsx)$/.test(entry.name) ? [path] : [];
  }));
  return nested.flat();
}

test('wide business tables use one browser-native floating scrollbar with a table-native fallback', () => {
  assert.match(appRoot, /<ResponsiveTableEnhancer\s*\/>/);
  assert.match(enhancer, /bottom\.addEventListener\('scroll', onBottomScroll/);
  assert.match(enhancer, /scroll\.addEventListener\('scroll', onBodyScroll/);
  assert.match(enhancer, /wrapper\.classList\.toggle\('responsive-table--floating-scroll-active', visible\)/);
  assert.match(styles, /\.responsive-table__bottom-scroll \{[\s\S]*?overflow-x: auto;/);
  assert.match(styles, /\.responsive-table--enhanced \.ant-table-body,[\s\S]*?overflow-x: auto !important;/);
  assert.match(styles, /\.responsive-table--floating-scroll-active \.ant-table-body,[\s\S]*?overflow-x: hidden !important;/);
  assert.match(styles, /\.responsive-table--floating-scroll-active \.ant-table-sticky-scroll \{[\s\S]*?display: none !important;/);
  assert.doesNotMatch(styles, /\.app-content \.ant-table-wrapper\.responsive-table--enhanced/);
});

test('the Ant Design container remains unclipped for sticky headers while the fallback remains available', () => {
  assert.match(styles, /\.app-content \.ant-table-wrapper \{[\s\S]*?overflow: visible;/);
  assert.match(appTableContainerRule, /overflow: visible;/);
  assert.doesNotMatch(appTableContainerRule, /overflow: hidden;/);
  assert.match(styles, /\.sticky-table__body \.ant-table-body,[\s\S]*?overflow-x: hidden !important;/);
  assert.match(styles, /\.responsive-table--enhanced \.ant-table-body,[\s\S]*?overflow-x: auto !important;/);
});

test('business-list sticky header and scrollbar bind to the real app-content viewport', () => {
  assert.match(sortableTable, /closest<HTMLElement>\('\.app-content'\)/);
  assert.match(sortableTable, /if \(props\.sticky === false\) return false/);
  assert.match(sortableTable, /getContainer: props\.sticky\.getContainer \?\? \(\(\) => appScrollContainer \?\? window\)/);
  assert.match(sortableTable, /if \(appScrollContainer\)[\s\S]*?getContainer: \(\) => appScrollContainer/);
  assert.match(sortableTable, /sticky=\{resolvedSticky\}/);
});

test('every page that requests table scroll X enters the shared browser-native scrollbar path', async () => {
  const files = await sourceFiles(fileURLToPath(new URL('../src/pages', import.meta.url)));
  const wideTablePages = await Promise.all(files.map(async (file) => ({
    file,
    source: await readFile(file, 'utf8'),
  })));
  const matches = wideTablePages.filter(({ source }) => /scroll=\{\{[\s\S]{0,240}\bx\s*:/.test(source));

  assert.equal(matches.length, 29, 'the production inventory must retain all 29 current wide-table pages');
  for (const { file, source } of matches) {
    assert.match(
      source,
      /from ['"][^'"]*components\/(?:SortableTable|StickyTable)['"]/,
      `${file} bypasses the shared wide-table scrollbar implementation`,
    );
  }
});
