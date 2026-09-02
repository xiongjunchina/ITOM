import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const [page, menu, router, reports, zhEn, locale] = await Promise.all([
  readFile(new URL('../src/pages/platform/PlatformOperations.tsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/components/menu.tsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/router.tsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/pages/reports/ReportCenter.tsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/i18n/dict.ts', import.meta.url), 'utf8'),
  readFile(new URL('../src/i18n/locales/platform.ts', import.meta.url), 'utf8'),
]);

test('platform operations routes stay permission-gated and report center remains the last sidebar item', () => {
  assert.match(menu, /key: 'platform'[\s\S]*?module: 'platform_portfolio'[\s\S]*?module: 'platform_capacity'/);
  assert.ok(menu.indexOf("key: 'team'") < menu.indexOf("key: 'platform'"));
  assert.ok(menu.indexOf("key: 'platform'") < menu.indexOf("key: 'process'"));
  assert.ok(menu.lastIndexOf("key: '/reports'") > menu.indexOf("key: 'admin'"));
  assert.match(router, /function PlatformGate/);
  assert.match(router, /path: 'platform\/services'/);
  assert.match(router, /path: 'platform\/demands'/);
  assert.match(router, /path: 'platform\/capacity'/);
});

test('platform lists preserve shared wide-table, fixed-column and server-pagination behavior', () => {
  assert.match(page, /from '\.\.\/\.\.\/components\/SortableTable'/);
  assert.match(page, /freezeColumns=\{2\}/);
  assert.match(page, /scroll=\{\{ x: 'max-content' \}\}/);
  assert.match(page, /pageSizeOptions: \[20, 50, 100, 200\]/);
  assert.match(page, /tableKey="platform\.services"/);
  assert.match(page, /tableKey="platform\.demands"/);
  assert.match(page, /tableKey="platform\.capacity"/);
});

test('capacity workflow exposes idempotent create, commitment, review, approval and revision controls', () => {
  assert.match(page, /Idempotency-Key/);
  assert.match(page, /\/platform\/capacity-plans\/\$\{selectedPlan\.id\}\/commitments/);
  assert.match(page, /\/platform\/capacity-plans\/\$\{row\.id\}\/submit/);
  assert.match(page, /\/platform\/capacity-plans\/\$\{selectedPlan\.id\}\/approve/);
  assert.match(page, /\/platform\/capacity-plans\/\$\{selectedPlan\.id\}\/revisions/);
  assert.match(page, /allow_overcommit/);
  assert.match(page, /role === 'cio' \|\| role === 'it_pdm_leader'/);
  assert.match(page, /roles\.includes\('cio'\)/);
  assert.match(page, /selectedPlan\.status === 'review' && canApproveCapacity/);
  assert.match(page, /canOverrideCapacity && <Form\.Item name="allow_overcommit"/);
});

test('platform analytics and bilingual permission labels are connected to the existing report center', () => {
  assert.match(reports, /'platform' \| 'library'/);
  assert.match(reports, /platform: \['platform'\]/);
  assert.match(reports, /report\.tab\.platform/);
  assert.match(zhEn, /'module\.platform_portfolio'/);
  assert.match(zhEn, /'group\.平台运营'/);
  assert.match(zhEn, /'menu\.\/platform\/capacity'/);
  for (const key of ['platform.title.services', 'platform.title.demands', 'platform.title.capacity', 'platform.approvalReason']) {
    assert.equal((locale.match(new RegExp(`'${key.replaceAll('.', '\\.')}'`, 'g')) ?? []).length, 2, `${key} must exist in zh and en`);
  }
});
