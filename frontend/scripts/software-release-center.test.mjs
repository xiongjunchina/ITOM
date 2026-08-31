import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const about = read('../src/pages/About.tsx');
const layout = read('../src/components/MainLayout.tsx');
const login = read('../src/pages/Login.tsx');
const router = read('../src/router.tsx');
const branding = read('../src/pages/admin/UiBranding.tsx');
const menu = read('../src/components/menu.tsx');
const vite = read('../vite.config.ts');
const manifest = JSON.parse(read('../../release/releases/v1.2.0-rc.1.json'));
const pkg = JSON.parse(read('../package.json'));

test('software release identity is embedded from the canonical manifest and exposed through About', () => {
  assert.equal(pkg.version, manifest.release.version);
  assert.match(vite, /releaseRoot = resolve\(frontendDir, '\.\.\/release'\)/);
  assert.match(vite, /resolve\(releaseRoot, 'current\.json'\)/);
  assert.match(vite, /__ITOM_RELEASE__/);
  assert.match(about, /\/public\/releases\/current/);
  assert.match(about, /\/public\/releases/);
  assert.match(about, /runtime\.release\.version !== buildRelease\.release\.version/);
});

test('About stays outside the sidebar and remains reachable from the user menu and login surface', () => {
  assert.match(router, /path: 'about', element: <About/);
  assert.match(layout, /key: 'about'/);
  assert.match(layout, /navigate\('\/about'\)/);
  assert.match(login, /buildRelease\.release\.version/);
  assert.doesNotMatch(menu, /path:\s*['"]\/about['"]/);
});

test('developer and legal presentation is branding-controlled while software version stays read-only', () => {
  assert.match(branding, /key:'legal'/);
  assert.match(branding, /developer_name_zh/);
  assert.match(branding, /软件版本号由 Git 发布清单只读生成/);
  assert.match(about, /localized\(branding, 'legal', 'developer_name'/);
  assert.match(about, /软件版本只读且来自 Git 发布清单/);
});

test('public About rendering never asks for infrastructure build fields', () => {
  for (const privateField of ['git_sha', 'image_digest', 'database_revision', 'registry']) {
    assert.doesNotMatch(about, new RegExp(privateField));
  }
});
