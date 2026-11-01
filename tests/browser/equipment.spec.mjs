import { test, expect } from '@playwright/test';

const disclosure = 'As an Amazon Associate I earn from qualifying purchases.';

async function checkAffiliateLinks(container) {
  const links = container.locator('a[href*="amazon.com"]');
  expect(await links.count()).toBeGreaterThan(1);
  for (const link of await links.all()) {
    const url = new URL(await link.getAttribute('href'));
    expect(url.hostname).toBe('www.amazon.com');
    expect(url.pathname).toBe('/s');
    expect(url.searchParams.get('tag')).toBe('hardkore26-20');
    expect(url.searchParams.get('k')).toBeTruthy();
    await expect(link).toHaveAttribute('target', '_blank');
    expect((await link.getAttribute('rel')).split(/\s+/)).toEqual(expect.arrayContaining(['sponsored', 'noopener', 'noreferrer']));
  }
}

test('landing links to the complete equipment guide with a clear disclosure', async ({ page }) => {
  await page.goto('/');
  const equipment = page.locator('#equipment');
  await expect(equipment).toContainText(disclosure);
  await checkAffiliateLinks(equipment);
  await equipment.getByRole('link', { name: 'Open the complete equipment guide' }).click();
  await expect(page).toHaveURL(/web\/index\.html#equipment$/);
  await expect(page.locator('#equipment')).toBeVisible();
  await expect(page.locator('#pageTitle')).toHaveText('Equipment guide');
});

test('workstation guide covers listed makes and transport differences without contacting Amazon', async ({ page }) => {
  const amazonRequests = [];
  page.on('request', (request) => { if (new URL(request.url()).hostname.endsWith('amazon.com')) amazonRequests.push(request.url()); });
  await page.goto('/web/index.html');
  await page.locator('[data-view="equipment"]').click();
  const guide = page.locator('#equipment');
  await expect(guide).toBeVisible();
  await expect(guide).toContainText(disclosure);
  for (const name of ['Moto Guzzi', 'Harley-Davidson', 'Honda', 'Kawasaki', 'Ducati', 'Suzuki', 'Yamaha', 'Aprilia', 'Triumph', 'Buell']) {
    await expect(guide).toContainText(name);
  }
  for (const topic of ['K-Line transceiver', 'SLCAN', 'SocketCAN', 'PCAN', 'J1850 VPW', 'TTL', 'pinout', 'synthetic-tested', 'Physical 5AM writing remains disabled']) {
    await expect(guide).toContainText(topic);
  }
  await checkAffiliateLinks(guide);
  expect(amazonRequests).toEqual([]);
  await page.locator('[data-view="garage"]').click();
  await page.locator('#garageEquipmentLink').click();
  await expect(guide).toBeVisible();
  await page.locator('[data-view="garage"]').click();
  await page.locator('#garageEquipmentLink').click();
  await expect(guide).toBeVisible();
});

test('equipment guide fits a narrow screen', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  for (const path of ['/#equipment', '/web/index.html#equipment']) {
    await page.goto(path);
    await expect(page.locator('#equipment')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  }
});
