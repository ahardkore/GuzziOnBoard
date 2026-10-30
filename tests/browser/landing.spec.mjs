import { test, expect } from '@playwright/test';

test('landing page explains multi-brand scope, safety and paths into the product', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/Motorcycle diagnostics/);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('your machine');
  await expect(page.locator('#coverage')).toContainText('Harley-Davidson');
  await expect(page.locator('#coverage')).toContainText('physical ECU writing remains blocked');
  await expect(page.locator('.console')).toHaveAttribute('aria-label', /simulated/);
  await page.getByRole('link', { name: 'Try the browser demo' }).click();
  await expect(page).toHaveURL(/\/web\/index\.html$/);
  await expect(page.locator('#garage')).toBeVisible();
});

test('tour explains simulator and setup without suggesting physical flashing works', async ({ page }) => {
  await page.goto('/web/tour.html');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('garage');
  await expect(page.locator('.notice')).toContainText('physical ECU writing remains blocked');
  await expect(page.getByRole('link', { name: 'Project home', exact: true })).toHaveAttribute('href', '../');
  await page.getByRole('link', { name: 'Open the workstation demo' }).click();
  await expect(page).toHaveURL(/\/web\/index\.html$/);
});

test('landing and tour fit narrow screens', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  for (const path of ['/', '/web/tour.html']) {
    await page.goto(path);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  }
});
