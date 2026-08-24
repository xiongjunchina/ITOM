import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('requirement overview exports every server-filtered row with the visible filter contract', () => {
  const source = read('../src/pages/requirements/Requirements.tsx');

  assert.match(source, /api\.download\(`\/requirements\/export\$\{query \? `\?\$\{query\}` : ''\}`\)/);
  assert.match(source, /params\.set\('q', q\)/);
  assert.match(source, /params\.set\('business_domain_id', domainId\)/);
  assert.match(source, /params\.set\('moscow', moscow\)/);
  assert.match(source, /params\.set\('scope', 'mine'\)/);
  assert.match(source, /view === 'table' && status/);
  assert.match(source, /view === 'table' && decision/);
});

test('requirement export remains available to view-only users and has bilingual text', () => {
  const source = read('../src/pages/requirements/Requirements.tsx');
  const overview = source.slice(source.indexOf('const overviewTab'));
  const exportButton = overview.indexOf("t('req.exportAll')");
  const createOnlyActions = overview.indexOf('{canCreate && (', exportButton);

  assert.ok(exportButton >= 0, 'export button should be rendered in the overview toolbar');
  assert.ok(createOnlyActions > exportButton, 'export must not be hidden inside the create-permission actions');

  const locale = read('../src/i18n/locales/requirements.ts');
  assert.match(locale, /'req\.exportAll': '导出全部数据'/);
  assert.match(locale, /'req\.exportAll': 'Export All Data'/);
});
