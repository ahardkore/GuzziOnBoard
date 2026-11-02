import { test, expect } from '@playwright/test';

/* The Tools bench is organised by manufacturer: a Brand dropdown in the
 * organizer bar, a grouping heading per brand inside the bench, and an
 * "Only <brand>" shortcut on each heading. The Help center mirrors the same
 * grouping in its generated tool directory. */

const BRANDS = [
  'general', 'bajaj', 'buell', 'cfmoto', 'harley', 'honda', 'yamaha',
  'britek', 'dynojet', 'rusefi',
];

test.beforeEach(async ({ page }) => {
  await page.goto('/web/index.html');
  await page.locator('[data-view="tools"]').click();
  await expect(page.locator('#tools')).toBeVisible();
});

test('the bench is grouped into general tools first, then one group per brand', async ({ page }) => {
  await expect(page.locator('#toolsBrandSelect')).toBeVisible();
  await expect(page.locator('#toolsCountBadge')).toHaveText('29 of 29 tools');
  await expect(page.locator('#toolsBrandBadge')).toHaveText('All brands');

  const headings = page.locator('#tools > [data-brand-heading]');
  await expect(headings).toHaveCount(BRANDS.length);
  const order = await headings.evaluateAll((nodes) => nodes.map((node) => node.dataset.brandHeading));
  expect(order).toEqual(BRANDS);

  // General tools come first in the document, then Bajaj, Buell, ... rusEFI.
  const panelOrder = await page.locator('#tools > article.panel[data-tool-cat]').evaluateAll(
    (panels) => panels.map((panel) => panel.dataset.toolBrand),
  );
  const firstBrandChange = panelOrder.findIndex((brand) => brand !== 'general');
  expect(panelOrder.slice(0, firstBrandChange).every((brand) => brand === 'general')).toBe(true);
  expect(new Set(panelOrder)).toEqual(new Set(BRANDS));

  await expect(page.locator('[data-brand-heading="general"]')).toContainText('General');
  await expect(page.locator('[data-brand-heading="general"] [data-brand-count]')).toContainText('16 tools');
  await expect(page.locator('[data-brand-heading="harley"]')).toContainText('Harley-Davidson');
});

test('the Brand dropdown narrows the bench to one manufacturer', async ({ page }) => {
  await page.locator('#toolsBrandSelect').selectOption('harley');
  const visible = page.locator('#tools > article.panel[data-tool-cat]:not(.hidden)');
  await expect(visible).toHaveCount(4);
  const ids = await visible.evaluateAll((panels) => panels.map((panel) => panel.id).sort());
  expect(ids).toEqual(['centurionResearch', 'harleyMemory', 'harleyRegion', 'pvvEditor']);
  await expect(page.locator('#toolsCountBadge')).toHaveText('4 of 29 tools');
  await expect(page.locator('#toolsBrandBadge')).toHaveText('Harley-Davidson · 4 tools');
  await expect(page.locator('#tools > [data-brand-heading]:not(.hidden)')).toHaveCount(1);
  await expect(page.locator('[data-brand-heading="harley"]')).toBeVisible();
  await expect(page.locator('[data-brand-heading="general"]')).toBeHidden();

  await page.locator('#toolsBrandSelect').selectOption('honda');
  await expect(page.locator('#tools > article.panel[data-tool-cat]:not(.hidden)')).toHaveCount(2);
  await expect(page.locator('#hondaVfrChecksum')).toBeVisible();
  await expect(page.locator('#hondaOffline')).toBeVisible();

  await page.locator('#toolsBrandSelect').selectOption('general');
  await expect(page.locator('#tools > article.panel[data-tool-cat]:not(.hidden)')).toHaveCount(16);
  await expect(page.locator('#toolsBrandBadge')).toHaveText('General · 16 tools');

  await page.locator('#toolsBrandSelect').selectOption('all');
  await expect(page.locator('#tools > article.panel[data-tool-cat]:not(.hidden)')).toHaveCount(29);
});

test('an "Only <brand>" heading button filters and clears the brand', async ({ page }) => {
  await page.locator('[data-brand-heading="yamaha"] [data-brand-only="yamaha"]').click();
  await expect(page.locator('#toolsBrandSelect')).toHaveValue('yamaha');
  await expect(page.locator('#tools > article.panel[data-tool-cat]:not(.hidden)')).toHaveCount(1);
  await expect(page.locator('#yamahaResearch')).toBeVisible();

  // Pressing the same toggle again returns to every brand.
  await page.locator('[data-brand-heading="yamaha"] [data-brand-only="yamaha"]').click();
  await expect(page.locator('#toolsBrandSelect')).toHaveValue('all');
  await expect(page.locator('#tools > article.panel[data-tool-cat]:not(.hidden)')).toHaveCount(29);
});

test('brand, category and search combine, and an empty combination says so', async ({ page }) => {
  // Category alone: Workshop & Service is six general tools.
  await page.locator('[data-tool-filter="workshop"]').click();
  await expect(page.locator('#tools > article.panel[data-tool-cat]:not(.hidden)')).toHaveCount(6);

  // Brand + category with no overlap: Honda has no workshop module.
  await page.locator('#toolsBrandSelect').selectOption('honda');
  await expect(page.locator('#tools > article.panel[data-tool-cat]:not(.hidden)')).toHaveCount(0);
  await expect(page.locator('#toolsEmptyNote')).toBeVisible();

  // Category + search inside one brand.
  await page.locator('[data-tool-filter="calibration"]').click();
  await page.locator('#toolsSearchInput').fill('checksum');
  await expect(page.locator('#tools > article.panel[data-tool-cat]:not(.hidden)')).toHaveCount(1);
  await expect(page.locator('#hondaVfrChecksum')).toBeVisible();

  // Clearing resets brand, category and search.
  await page.locator('#toolsSearchClear').click();
  await expect(page.locator('#toolsBrandSelect')).toHaveValue('all');
  await expect(page.locator('#toolsSearchInput')).toHaveValue('');
  await expect(page.locator('#toolsCountBadge')).toHaveText('29 of 29 tools');
});

test('a Tools menu command clears any active brand filter before jumping', async ({ page }) => {
  await page.locator('#toolsBrandSelect').selectOption('harley');
  await expect(page.locator('#tools > article.panel[data-tool-cat]:not(.hidden)')).toHaveCount(4);

  await page.locator('#toolsMenuBtn').click();
  await page.locator('[data-menu-tool="#gearingPanel"]').click();
  await expect(page.locator('#pageTitle')).toHaveText('Tools');
  await expect(page.locator('#toolsBrandSelect')).toHaveValue('all');
  await expect(page.locator('#gearingPanel')).toBeVisible();
});

test('the Help center groups its tool directory by brand and filters with its own picker', async ({ page }) => {
  await page.goto('/web/index.html#help/tools-directory');
  await expect(page.locator('#helpBrandSelect')).toBeVisible();

  const groups = page.locator('#helpToolDirectory [data-help-brand-group]');
  await expect(groups).toHaveCount(BRANDS.length + 1); // + the workspace group
  const groupOrder = await groups.evaluateAll((nodes) => nodes.map((node) => node.dataset.helpBrandGroup));
  expect(groupOrder).toEqual(['workspaces', ...BRANDS]);
  await expect(page.locator('#helpToolDirectory [data-help-brand-group="harley"] h3')).toContainText('Harley-Davidson');

  await page.locator('#helpBrandSelect').selectOption('harley');
  await expect(page.locator('#helpToolDirectory [data-help-brand-group]')).toHaveCount(1);
  const cards = page.locator('#helpToolDirectory [data-help-tool-card]');
  await expect(cards).toHaveCount(4);
  const ids = await cards.evaluateAll((nodes) => nodes.map((node) => node.dataset.helpToolCard).sort());
  expect(ids).toEqual(['centurion-research', 'harley-memory', 'harley-region', 'pvv-editor']);

  await page.locator('#helpBrandSelect').selectOption('all');
  await expect(page.locator('#helpToolDirectory [data-help-brand-group]')).toHaveCount(BRANDS.length + 1);
});

test('a brand-specific tool article names its brand and the help search honours the brand filter', async ({ page }) => {
  await page.goto('/web/index.html#help/tool/harley-memory');
  await expect(page.locator('#helpArticlePane .help-brand-chip').first()).toContainText('Harley-Davidson');
  await expect(page.locator('#helpArticlePane')).toContainText('all Harley-Davidson tools');

  await page.locator('#helpBrandSelect').selectOption('buell');
  await page.locator('#helpSearchInput').fill('serial');
  await expect(page.locator('#helpSearchResultsPanel .help-result')).not.toHaveCount(0);
  const kinds = await page.locator('#helpSearchResultsPanel .help-result .help-result-title').allTextContents();
  // Only Buell/General tool entries survive a brand filter; guides stay.
  const hasBuell = kinds.some((text) => /DDFI/.test(text));
  expect(hasBuell).toBe(true);
});
