import { test, expect } from '@playwright/test';

/* The Help & Reference module: the guide center, the per-tool manual, the
 * generated ECU/XDF explorers, deep links and the Ctrl+K global search
 * spotlight. Runs on the static host, so /api/catalog and /api/maps are
 * answered by demo-api.js/demo-lab.js exactly as on GitHub Pages. */

test.beforeEach(async ({ page }) => {
  await page.goto('/web/index.html');
});

test('help center lists topics and opens a guide with a working permalink', async ({ page }) => {
  await page.locator('[data-view="help"]').click();
  await expect(page.locator('#pageTitle')).toHaveText('Help & guides');
  await expect(page.locator('#helpCategoryPills')).toBeVisible();

  const tree = page.locator('#helpTopicTree .help-tree-item');
  expect(await tree.count()).toBeGreaterThan(20);

  await page.locator('#helpTopicTree [data-help-route="topic/howto-backup-basemap"]').click();
  await expect(page.locator('#helpArticlePane')).toContainText('verified backup');
  await expect(page.locator('#helpArticlePane')).toContainText('dual-read');
  expect(page.url()).toContain('#help/howto-backup-basemap');

  await page.locator('#helpCopyLinkBtn').click();
  await expect(page.locator('#helpCopyStatus')).toContainText('copied');
  const clipboard = await page.evaluate(() => navigator.clipboard.readText());
  expect(clipboard).toContain('#help/howto-backup-basemap');
});

test('help search covers guides, tools, ECUs and glossary terms', async ({ page }) => {
  await page.locator('[data-view="help"]').click();
  await page.locator('#helpSearchInput').fill('5am');
  await expect(page.locator('#helpSearchResultsPanel')).toBeVisible();
  await expect(page.locator('#helpSearchResultsPanel')).toContainText('IAW 5AM');

  await page.locator('#helpSearchResultsPanel [data-help-route="topic/ecu-5am"]').click();
  await expect(page.locator('#helpArticlePane .help-article-title')).toContainText('IAW 5AM / 5AM2 deep dive');

  await page.locator('#helpSearchInput').fill('testerpresent');
  await expect(page.locator('#helpSearchResultsPanel')).toContainText('TesterPresent');
  await page.locator('#helpSearchResultsPanel [data-help-route="glossary/testerpresent"]').click();
  await expect(page.locator('#helpArticlePane')).toContainText('Keep-alive message');
  expect(page.url()).toContain('#help/glossary/testerpresent');
});

test('a #help deep link opens the protocol article on first load', async ({ page }) => {
  await page.goto('/web/index.html#help/protocol/kwp2000');
  await expect(page.locator('#help')).toBeVisible();
  await expect(page.locator('#pageTitle')).toHaveText('Help & guides');
  await expect(page.locator('#helpArticlePane .help-article-title')).toContainText('KWP2000');
  const body = page.locator('#helpArticlePane');
  await expect(body).toContainText('Fast initialisation');
  await expect(body).toContainText('24–26 ms');
  await expect(body).toContainText('0x81');
});

test('Ctrl+K spotlight searches the whole program and opens a result with the keyboard', async ({ page }) => {
  await page.keyboard.press('Control+k');
  await expect(page.locator('#helpSpotlightModal')).toBeVisible();
  expect(await page.locator('#helpSpotlightResults .help-spot-result').count()).toBeGreaterThan(5);

  await page.locator('#helpSpotlightInput').fill('checksum');
  await expect(page.locator('#helpSpotlightResults')).toContainText('Checksums');
  await page.locator('#helpSpotlightInput').press('ArrowDown');
  await page.locator('#helpSpotlightInput').press('Enter');

  await expect(page.locator('#helpSpotlightModal')).toBeHidden();
  await expect(page.locator('#help')).toBeVisible();
  expect(page.url()).toContain('#help/');
  await expect(page.locator('#helpArticlePane .help-article-title')).toBeVisible();

  await page.keyboard.press('Control+k');
  await expect(page.locator('#helpSpotlightModal')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('#helpSpotlightModal')).toBeHidden();
});

test('a tool article explains the panel and its jump button opens the live workspace', async ({ page }) => {
  await page.goto('/web/index.html#help/tool/maps-panel');
  await expect(page.locator('#helpArticlePane .help-article-title')).toContainText('Maps & tables');
  await expect(page.locator('#helpArticlePane')).toContainText('Flags & Switches');
  await page.locator('#helpArticlePane [data-help-jump]').first().click();
  await expect(page.locator('#pageTitle')).toHaveText('ECU memory');
  await expect(page.locator('#mapsCard')).toBeVisible();
});

test('the Help menu and F1 both reach the center', async ({ page }) => {
  await page.keyboard.press('F1');
  await expect(page.locator('#pageTitle')).toHaveText('Help & guides');

  await page.locator('#helpMenuBtn').click();
  await page.locator('[data-help-topic="glossary"]').click();
  await expect(page.locator('#helpArticlePane .help-article-title')).toContainText('Glossary');
  await expect(page.locator('#helpArticlePane .help-glossary-term').first()).toBeVisible();
});

test('the generated ECU catalog and XDF library explorers render live catalog data', async ({ page }) => {
  await page.goto('/web/index.html#help/ecus-overview');
  await expect(page.locator('#helpEcuCatalog .help-ecu-card').first()).toBeVisible();
  expect(await page.locator('#helpEcuCatalog .help-ecu-card').count()).toBeGreaterThan(30);
  await page.locator('#helpEcuCatalog [href="#help/ecu/5am"]').click();
  await expect(page.locator('#helpArticlePane')).toContainText('IAW 5AM');
  await expect(page.locator('#helpArticlePane')).toContainText('Capture-verified');

  await page.goto('/web/index.html#help/ecus-xdf-library');
  await expect(page.locator('#helpXdfLibrary .help-xdf-card').first()).toBeVisible();
  expect(await page.locator('#helpXdfLibrary .help-xdf-card').count()).toBeGreaterThan(50);
});

test('search also finds menu commands and runs them', async ({ page }) => {
  await page.locator('[data-view="help"]').click();
  await page.locator('#helpSearchInput').fill('preferences');
  await expect(page.locator('#helpSearchResultsPanel')).toContainText('COMMAND');
  const command = page.locator('#helpSearchResultsPanel .help-result')
    .filter({ has: page.locator('.kind-action') })
    .filter({ hasText: 'Preferences' })
    .first();
  await command.click();
  await expect(page.locator('#prefsModal')).toBeVisible();
});


test('the tool directory lists every documented tool exactly once', async ({ page }) => {
  await page.goto('/web/index.html#help/tools-directory');
  await expect(page.locator('#helpToolDirectory .help-directory-card').first()).toBeVisible();
  const tools = await page.evaluate(() => window.GOB_HELP.tools.length);
  expect(tools).toBeGreaterThan(45);
  await expect(page.locator('#helpToolDirectory .help-directory-card')).toHaveCount(tools);
  const ids = await page.locator('#helpToolDirectory .help-directory-card').evaluateAll(
    (cards) => cards.map((card) => card.dataset.helpToolCard),
  );
  expect(new Set(ids).size).toBe(ids.length);
});

test('a glossary term is linkable and the glossary lists every term', async ({ page }) => {
  await page.goto('/web/index.html#help/glossary/testerpresent');
  await expect(page.locator('#helpArticlePane .help-glossary-term')).toHaveCount(1);
  await expect(page.locator('#helpArticlePane')).toContainText('Keep-alive message');

  await page.goto('/web/index.html#help/glossary');
  const terms = await page.evaluate(() => window.GOB_HELP.glossary.length);
  expect(terms).toBeGreaterThan(60);
  await expect(page.locator('#helpArticlePane .help-glossary-term')).toHaveCount(terms);
});
