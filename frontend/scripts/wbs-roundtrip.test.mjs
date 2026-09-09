import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('project progress keeps append import and adds previewed WBS round-trip import', () => {
  const page = read('../src/pages/projects/ProjectDetail.tsx');
  const controls = read('../src/components/WbsRoundtripButtons.tsx');

  assert.match(page, /ImportButtons/);
  assert.match(page, /WbsRoundtripButtons/);
  assert.match(page, /\/projects\/\$\{id\}\/wbs\/export/);
  assert.match(page, /\/projects\/\$\{id\}\/wbs\/import\/preview/);
  assert.match(page, /\/projects\/\$\{id\}\/wbs\/import\/commit/);
  assert.match(controls, /api\.download\(exportUrl\)/);
  assert.match(controls, /api\s*\.upload<WbsRoundtripPreview>\(previewUrl, selected\)/);
  assert.match(controls, /api\.upload<WbsRoundtripCommitResult>\(commitUrl, file\)/);
  assert.match(controls, /disabled=\{!preview\?\.can_commit\}/);
  assert.match(controls, /summary\.omitted/);
});
