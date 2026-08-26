import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('report center keeps the unified seven-domain metric, snapshot, approval, publication and export workflow', () => {
  const page = read('../src/pages/reports/ReportCenter.tsx');
  assert.match(page, /'itsm\.ticket_count'/);
  assert.match(page, /'project\.active_count'/);
  assert.match(page, /'requirement\.avg_lead_days'/);
  assert.match(page, /'operations\.incurred_cost_cny'/);
  assert.match(page, /'operations\.effort_days'/);
  assert.match(page, /'people\.effort_days'/);
  assert.match(page, /'task\.completed_count'/);
  assert.match(page, /'process\.avg_cycle_hours'/);
  assert.match(page, /api\.postWithHeaders\(`\/reports\/\$\{created\.id\}\/generate`/);
  assert.match(page, /`\/reports\/\$\{row\.id\}\/submit-review`/);
  assert.match(page, /`\/reports\/\$\{publishTarget\.id\}\/publish`/);
  assert.match(page, /api\.download\(`\/reports\/\$\{row\.id\}\/export`\)/);
  assert.match(page, /Table<ReportRow>/);
  assert.match(page, /scroll=\{\{ x: 'max-content' \}\}/);
  assert.match(page, /subjectType="shared_operations"/);
  assert.match(page, /lifecycleStage="run"/);
});

test('B-OPS ledger is available from demand and ticket details with guarded actual dates and daily effort', () => {
  const panel = read('../src/components/investment/InvestmentPanel.tsx');
  const requirement = read('../src/pages/requirements/RequirementDetail.tsx');
  const ticket = read('../src/pages/itsm/TicketDetail.tsx');
  assert.match(panel, /'\/investments\/summary'/);
  assert.match(panel, /'\/investments\/budgets'/);
  assert.match(panel, /'\/investments\/costs'/);
  assert.match(panel, /'\/investments\/worklogs'/);
  assert.match(panel, /current\.isAfter\(dayjs\(\), 'day'\)/);
  assert.match(panel, /max=\{2\}/);
  assert.match(panel, /management_total_cny == null/);
  assert.match(requirement, /subjectType="requirement"/);
  assert.match(requirement, /lifecycleStage="demand"/);
  assert.match(ticket, /subjectType="ticket"/);
  assert.match(ticket, /lifecycleStage="run"/);
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
  const adminIndex = menu.indexOf("key: 'admin'");
  const reportIndex = menu.indexOf("key: '/reports'");
  const menuTreeEnd = menu.indexOf('\n];', reportIndex);
  assert.ok(adminIndex >= 0 && reportIndex > adminIndex, 'Report Center must follow System Management');
  assert.ok(menuTreeEnd > reportIndex, 'Report Center must remain inside MENU_TREE');
  assert.doesNotMatch(menu.slice(reportIndex, menuTreeEnd), /\n\s{4}key:/, 'Report Center must be the final top-level menu item');
  assert.match(
    menu,
    /if \(user\?\.permissions\) return mods\.some\(\(m\) => hasPermission\(user, m, 'view'\)\)/,
    'users without reports.view must continue to lose the Report Center entry',
  );
  assert.match(router, /path: 'reports', element: <ReportGate \/>/);
  assert.match(locale, /'report\.title': '统一报表中心'/);
  assert.match(locale, /'report\.title': 'Unified Report Center'/);
});
