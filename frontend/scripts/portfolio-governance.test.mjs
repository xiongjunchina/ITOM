import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../', import.meta.url);
const [page, router, context, locales] = await Promise.all([
  readFile(new URL('src/pages/projects/PortfolioGovernance.tsx', root), 'utf8'),
  readFile(new URL('src/router.tsx', root), 'utf8'),
  readFile(new URL('src/components/assistant/AssistantContext.ts', root), 'utf8'),
  readFile(new URL('src/i18n/locales/projects.ts', root), 'utf8'),
]);

test('portfolio governance route and assistant page context are registered', () => {
  assert.match(router, /path: 'projects\/portfolios\/:id'/);
  assert.match(router, /<PortfolioGovernance\s*\/>/);
  assert.match(context, /portfolio_detail/);
});

test('portfolio governance visible translation keys have exact Chinese and English entries', () => {
  assert.doesNotMatch(page, /t\('common\.name'\)/);
  for (const key of ['portfolio.ruleName', 'portfolio.action.objectives_updated']) {
    assert.equal(locales.match(new RegExp(`'${key.replaceAll('.', '\\.')}':`, 'g'))?.length, 2, key);
  }
  assert.match(page, /portfolio\.ruleName/);
  assert.match(page, /portfolio\.action\.\$\{value\}/);
});
