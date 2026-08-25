import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('report center keeps the five-domain metric, snapshot, approval, publication and export workflow', () => {
  const page = read('../src/pages/reports/ReportCenter.tsx');
  assert.match(page, /'itsm\.ticket_count'/);
  assert.match(page, /'project\.active_count'/);
  assert.match(page, /'requirement\.avg_lead_days'/);
  assert.match(page, /'task\.completed_count'/);
  assert.match(page, /'process\.avg_cycle_hours'/);
  assert.match(page, /api\.postWithHeaders\(`\/reports\/\$\{created\.id\}\/generate`/);
  assert.match(page, /`\/reports\/\$\{row\.id\}\/submit-review`/);
  assert.match(page, /`\/reports\/\$\{publishTarget\.id\}\/publish`/);
  assert.match(page, /api\.download\(`\/reports\/\$\{row\.id\}\/export`\)/);
  assert.match(page, /Table<ReportRow>/);
  assert.match(page, /scroll=\{\{ x: 'max-content' \}\}/);
});

test('project cost tab captures precise budget, categorized cost, and effort entries', () => {
  const detail = read('../src/pages/projects/ProjectDetail.tsx');
  assert.match(detail, /`\/projects\/\$\{id\}\/budget-items`/);
  assert.match(detail, /`\/projects\/\$\{id\}\/effort-entries`/);
  assert.match(detail, /`\/projects\/\$\{id\}\/investment-summary`/);
  assert.match(detail, /amount_cny: v\.amount_cny/);
  assert.match(detail, /standard_rate_cny_per_day/);
  assert.match(detail, /<Table<ProjectBudgetItem>/);
  assert.match(detail, /<Table<ProjectEffortEntry>/);
});

test('report navigation, permissions and bilingual copy stay synchronized', () => {
  const menu = read('../src/components/menu.tsx');
  const router = read('../src/router.tsx');
  const locale = read('../src/i18n/locales/reports.ts');
  assert.match(menu, /key: '\/reports'/);
  assert.match(menu, /module: 'reports'/);
  assert.match(router, /path: 'reports', element: <ReportGate \/>/);
  assert.match(locale, /'report\.title': '统一报表中心'/);
  assert.match(locale, /'report\.title': 'Unified Report Center'/);
});
