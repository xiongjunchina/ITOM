import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { after, before, test } from 'node:test';
import { createServer } from 'vite';

let server;
let options;
let activeTaskSource;
let requirementDetailSource;

before(async () => {
  server = await createServer({
    root: process.cwd(),
    appType: 'custom',
    logLevel: 'silent',
    server: { middlewareMode: true },
  });
  options = await server.ssrLoadModule('/src/pages/requirements/developmentTaskOptions.ts');
  activeTaskSource = await readFile(
    new URL('../src/pages/requirements/ActiveTaskList.tsx', import.meta.url),
    'utf8',
  );
  requirementDetailSource = await readFile(
    new URL('../src/pages/requirements/RequirementDetail.tsx', import.meta.url),
    'utf8',
  );
});

after(async () => {
  await server?.close();
});

function requirement(overrides = {}) {
  return {
    status: 'implementing',
    is_example: false,
    implementation_route: null,
    project_id: null,
    can_manage_tasks: true,
    ...overrides,
  };
}

test('an implementing requirement remains selectable when it only has a project association', () => {
  assert.equal(
    options.isRequirementDevelopmentTaskCandidate(requirement({ project_id: 'project-1' })),
    true,
  );
});

test('an explicitly project-routed requirement is excluded from requirement development', () => {
  assert.equal(
    options.isRequirementDevelopmentTaskCandidate(
      requirement({ project_id: 'project-1', implementation_route: '转项目管理' }),
    ),
    false,
  );
});

test('task maintainers load IT assignees even when workflow editing is locked', () => {
  assert.equal(options.shouldLoadRequirementTaskMembers(false, true), true);
  assert.equal(options.shouldLoadRequirementTaskMembers(false, false), false);
});

test('the two user interfaces wire the shared candidate and assignee rules', () => {
  assert.match(activeTaskSource, /\.filter\(isRequirementDevelopmentTaskCandidate\)/);
  assert.match(
    requirementDetailSource,
    /shouldLoadRequirementTaskMembers\(canEdit, canManageTasks\)/,
  );
});
