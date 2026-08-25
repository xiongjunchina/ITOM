import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const appRoot = await readFile(new URL('../src/i18n/AppRoot.tsx', import.meta.url), 'utf8');
const styles = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8');
const enhancer = await readFile(new URL('../src/components/ResponsiveTableEnhancer.tsx', import.meta.url), 'utf8');
const sortableTable = await readFile(new URL('../src/components/SortableTable.tsx', import.meta.url), 'utf8');
const stickyTable = await readFile(new URL('../src/components/StickyTable.tsx', import.meta.url), 'utf8');
const projectDetail = await readFile(new URL('../src/pages/projects/ProjectDetail.tsx', import.meta.url), 'utf8');
const projects = await readFile(new URL('../src/pages/projects/Projects.tsx', import.meta.url), 'utf8');
const slaBoard = await readFile(new URL('../src/pages/itsm/SlaBoard.tsx', import.meta.url), 'utf8');
const catalogPage = await readFile(new URL('../src/pages/itsm/CatalogPage.tsx', import.meta.url), 'utf8');
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
  assert.match(enhancer, /const viewportTop = Math\.max\(rect\.top, viewport\.top\)/);
  assert.match(enhancer, /const viewportBottom = Math\.min\(rect\.bottom, viewport\.bottom\)/);
  assert.match(enhancer, /viewportBottom > viewportTop/);
  assert.match(styles, /\.responsive-table__bottom-scroll \{[\s\S]*?overflow-x: auto;/);
  assert.match(styles, /\.responsive-table--enhanced \.ant-table-body,[\s\S]*?overflow-x: auto !important;/);
  assert.match(styles, /\.responsive-table--floating-scroll-active \.ant-table-body,[\s\S]*?overflow-x: auto !important;/);
  assert.doesNotMatch(styles, /\.responsive-table--floating-scroll-active \.ant-table-body,[\s\S]*?overflow-x: hidden !important;/);
  assert.match(styles, /\.responsive-table--floating-scroll-active \.ant-table-sticky-scroll \{[\s\S]*?display: none !important;/);
  assert.doesNotMatch(styles, /\.app-content \.ant-table-wrapper\.responsive-table--enhanced/);
  assert.doesNotMatch(enhancer, /!wrapper\.closest\('\.sticky-table'\)/);
});

test('StickyTable keeps sticky headers and reuses the global scrollbar controller', () => {
  assert.match(styles, /\.app-content \.ant-table-wrapper \{[\s\S]*?overflow: visible;/);
  assert.match(appTableContainerRule, /overflow: visible;/);
  assert.doesNotMatch(appTableContainerRule, /overflow: hidden;/);
  assert.match(styles, /\.sticky-table__body \.ant-table-body,[\s\S]*?overflow-x: auto !important;/);
  assert.match(styles, /\.responsive-table--enhanced \.ant-table-body,[\s\S]*?overflow-x: auto !important;/);
  assert.doesNotMatch(stickyTable, /className="sticky-table__bottom-scroll"/);
  assert.doesNotMatch(stickyTable, /bottom\.addEventListener\('scroll', onBottomScroll/);
});

test('business-list sticky header and scrollbar bind to the real app-content viewport', () => {
  assert.match(sortableTable, /closest<HTMLElement>\('\.app-content'\)/);
  assert.match(sortableTable, /if \(props\.sticky === false\) return false/);
  assert.match(sortableTable, /getContainer: props\.sticky\.getContainer \?\? \(\(\) => appScrollContainer \?\? window\)/);
  assert.match(sortableTable, /if \(appScrollContainer\)[\s\S]*?getContainer: \(\) => appScrollContainer/);
  assert.match(sortableTable, /sticky=\{resolvedSticky\}/);
});

test('operation columns use compact icon buttons with hover and accessible labels', () => {
  assert.match(sortableTable, /function isActionColumn/);
  assert.match(sortableTable, /const MIN_ACTION_COLUMN_WIDTH = 64/);
  assert.match(sortableTable, /function actionControlCount/);
  assert.match(sortableTable, /function compactActionColumnWidth/);
  assert.match(sortableTable, /compactActionColumnWidth\(source, rows\)/);
  assert.match(sortableTable, /sortable-table__action-cell/);
  assert.match(sortableTable, /iconifyActionRender/);
  assert.match(sortableTable, /<Tooltip title=\{label\}>\{converted\}<\/Tooltip>/);
  assert.match(sortableTable, /'aria-label': element\.props\['aria-label'\] \?\? label/);
  assert.match(sortableTable, /sortable-table__action-icon-button/);
  assert.match(styles, /\.sortable-table__action-icon-button \{[\s\S]*?width: 28px;[\s\S]*?height: 28px;/);
  assert.match(styles, /\.sortable-table__action-cell\.ant-table-cell \{[\s\S]*?padding-inline: 2px !important;/);
  assert.match(styles, /\.sortable-table__action-cell \.ant-space \{[\s\S]*?column-gap: 0 !important;/);
});

test('right-fixed cells are opaque isolated overlays instead of exposing scrolled columns underneath', () => {
  assert.match(sortableTable, /sortable-table__fixed-right-cell/);
  assert.match(styles, /\.ant-table-wrapper \.ant-table-container \{[\s\S]*?isolation: isolate;/);
  assert.match(styles, /\.sortable-table__fixed-right-cell\.ant-table-cell-fix-right \{[\s\S]*?background:/);
  assert.match(styles, /\.sortable-table__fixed-right-cell\.ant-table-cell-fix-right-first \{[\s\S]*?box-shadow:/);
  assert.match(styles, /html\[data-theme='dark'\][\s\S]*?\.sortable-table__fixed-right-cell\.ant-table-cell-fix-right/);
});

test('reported dense-page defaults avoid vertical catalog names and oversized short-field columns', () => {
  assert.match(catalogPage, /catalog-management-card__layout/);
  assert.match(catalogPage, /catalog-management-card__name/);
  assert.match(styles, /\.catalog-management-card__layout \{[\s\S]*?flex-direction: column;[\s\S]*?gap: 4px;/);
  assert.match(styles, /\.catalog-management-card__name \{[\s\S]*?min-width: 72px;[\s\S]*?white-space: nowrap;/);
  assert.match(styles, /\.catalog-management-card__metadata \{[\s\S]*?text-overflow: ellipsis;[\s\S]*?white-space: nowrap;/);
  assert.match(styles, /\.catalog-management-card__actions \{[\s\S]*?flex-wrap: nowrap;/);
  assert.match(slaBoard, /dataIndex: 'ticket_code', width: 140/);
  assert.match(slaBoard, /dataIndex: 'title', width: 360, ellipsis: true/);
  assert.match(projects, /dataIndex: 'name',[\s\S]{0,80}?width: 200,[\s\S]{0,80}?ellipsis: true/);
  assert.match(projects, /dataIndex: 'description', width: 320, ellipsis: true/);
});

test('all current page action columns enter the shared icon-action implementation', async () => {
  const files = await sourceFiles(fileURLToPath(new URL('../src/pages', import.meta.url)));
  const pages = await Promise.all(files.map(async (file) => ({
    file,
    source: await readFile(file, 'utf8'),
  })));
  const actionColumnPages = pages.filter(({ source }) => (
    /title:\s*(?:t\([^\n]*actions|['"]操作['"])/.test(source)
    || /dataIndex:\s*['"]actions?['"]/.test(source)
  ));

  assert.ok(actionColumnPages.length > 0, 'the production inventory must contain action-column pages');
  for (const { file, source } of actionColumnPages) {
    assert.match(
      source,
      /from ['"][^'"]*components\/(?:SortableTable|StickyTable)['"]/,
      `${file} bypasses the shared icon-action implementation`,
    );
  }
  for (const { file, source } of pages) {
    assert.doesNotMatch(
      source,
      /import\s*\{[^}]*\bTable\b[^}]*\}\s*from\s*['"]antd['"]/,
      `${file} imports antd Table directly and can bypass shared action and scrollbar behavior`,
    );
  }
});

test('WBS rows support select-all and contextual batch delete without unlocking completed work', () => {
  assert.match(projectDetail, /<BatchDeleteToolbar/);
  assert.match(projectDetail, /endpoint=\{id \? `\/projects\/\$\{id\}\/wbs\/batch-delete` : undefined\}/);
  assert.match(projectDetail, /rowSelection=\{\{/);
  assert.match(projectDetail, /checkStrictly: true/);
  assert.match(projectDetail, /toggleWbsBranchSelection\(wbs, current, record\.id, selected\)/);
  assert.match(projectDetail, /preserveSelectedRowKeys: true/);
  assert.match(projectDetail, /disabled: record\.completed_locked/);
  assert.match(projectDetail, /`\/projects\/\$\{id\}\/wbs\/batch-move`/);
  assert.match(projectDetail, /normalizeWbsMoveRoots\(wbs, selectedWbsIds, draggedId\)/);
  assert.match(projectDetail, /wbs-table__drop-\$\{wbsDropTarget\.position\}/);
  assert.match(stickyTable, /const content = originalRender \? originalRender\(value, record, renderIndex\) : value as ReactNode/);
  assert.match(stickyTable, /className="sticky-table__row-resize-handle"/);
  assert.match(stickyTable, /\{rowProps\.children\}/);
  assert.doesNotMatch(stickyTable, /cloneElement\(cell/);
  assert.match(projectDetail, /storageKey=\{`project-wbs-layout-v3:\$\{id\}`\}/);
  assert.match(projectDetail, /dataIndex: 'stage',[\s\S]{0,180}?width: 64[\s\S]{0,100}?wbs-table__stage-cell/);
  assert.match(projectDetail, /title: t\('common\.actions'\),[\s\S]{0,220}?width: 120[\s\S]{0,120}?wbs-table__action-cell/);
  assert.match(projectDetail, /icon=\{<EditOutlined \/>\}/);
  assert.match(projectDetail, /icon=\{<PlusOutlined \/>\}/);
  assert.match(projectDetail, /icon=\{<SwapOutlined \/>\}/);
  assert.match(projectDetail, /icon=\{<DeleteOutlined \/>\}/);
  assert.match(styles, /\.wbs-table__stage-cell\.ant-table-cell \{[\s\S]*?padding-inline: 4px !important;/);
  assert.match(styles, /\.wbs-table__action-cell\.ant-table-cell \{[\s\S]*?padding-inline: 2px !important;/);
  assert.match(projectDetail, /await Promise\.all\(\[loadWbs\(\), loadMilestoneTracking\(\), loadDetail\(\)\]\)/);
});

test('WBS display sizing and actual-date controls stay integrated with the existing tree table', () => {
  assert.match(projectDetail, /useState<WbsDisplayLimit>\(50\)/);
  assert.match(projectDetail, /useState\(1\)/);
  assert.match(projectDetail, /selectHierarchySafeWbsPage\(wbs, wbsDisplayLimit, wbsPage\)/);
  assert.match(projectDetail, /<Pagination/);
  assert.match(projectDetail, /current=\{wbsPageResult\.page\}/);
  assert.match(projectDetail, /onChange=\{setWbsPage\}/);
  assert.match(projectDetail, /dataSource=\{wbsTree\}/);
  assert.match(projectDetail, /t\('proj\.wbs\.displayCount', \{ shown: visibleWbs\.length, total: wbs\.length \}\)/);
  assert.match(projectDetail, /\{ value: 50, label: '50' \}/);
  assert.match(projectDetail, /\{ value: 100, label: '100' \}/);
  assert.match(projectDetail, /\{ value: 200, label: '200' \}/);
  assert.match(projectDetail, /\{ value: 'all', label: t\('proj\.wbs\.displayAll'\) \}/);
  assert.match(projectDetail, /if \(!taskModal\.task\.completed_locked\) \{/);
  assert.match(projectDetail, /disabled=\{Boolean\(taskModal\.task\?\.completed_locked\)\}/);
  assert.match(projectDetail, /disabledDate=\{\(current\) => current\.isAfter\(dayjs\(\), 'day'\)\}/);
  assert.match(projectDetail, /value\.isBefore\(actualStart, 'day'\)/);
});

test('every page that requests table scroll X enters the shared browser-native scrollbar path', async () => {
  const files = await sourceFiles(fileURLToPath(new URL('../src/pages', import.meta.url)));
  const wideTablePages = await Promise.all(files.map(async (file) => ({
    file,
    source: await readFile(file, 'utf8'),
  })));
  const matches = wideTablePages.filter(({ source }) => /scroll=\{\{[\s\S]{0,240}\bx\s*:/.test(source));

  assert.equal(matches.length, 30, 'the production inventory must retain all 30 current wide-table pages');
  for (const { file, source } of matches) {
    assert.match(
      source,
      /from ['"][^'"]*components\/(?:SortableTable|StickyTable)['"]/,
      `${file} bypasses the shared wide-table scrollbar implementation`,
    );
  }
});
