import { test, expect } from '@playwright/test';

test('Power Vision AFR columns require explicit cylinder selection; lambda is not auto-mapped', async ({ page }) => {
  await page.goto('/web/index.html');
  await expect(page.locator('#connectBtn')).toBeEnabled({ timeout: 20_000 });
  await page.locator('[data-view="firmware"]').click();
  await page.locator('.map-log-tools > summary').click();
  await page.locator('#mapLogFile').setInputFiles({
    name: 'synthetic-pv.csv', mimeType: 'text/csv',
    buffer: Buffer.from('RPM,MAP,TP,AFR1,AFR2,Set AFR\n2000,60,20,15,14.8,14.2\n'),
  });
  await expect(page.locator('#mapLogSummary')).toContainText('synthetic-pv.csv');
  await expect(page.locator('#mapLogX')).toHaveValue('RPM');
  await expect(page.locator('#mapLogMeasured')).toHaveValue('');
  await expect(page.locator('#mapLogTarget')).toHaveValue('Set AFR');
  await page.locator('#mapLogMeasured').selectOption('AFR2');
  await expect(page.locator('#mapLogMeasured')).toHaveValue('AFR2');

  await page.locator('#mapLogFile').setInputFiles({
    name: 'synthetic-lambda.csv', mimeType: 'text/csv',
    buffer: Buffer.from('RPM,MAP,Lambda measured,Lambda target\n2000,60,1.0,0.9\n'),
  });
  await expect(page.locator('#mapLogSummary')).toContainText('synthetic-lambda.csv');
  await expect(page.locator('#mapLogMeasured')).toHaveValue('');
  await expect(page.locator('#mapLogTarget')).toHaveValue('');
  await expect(page.locator('.map-log-tools')).toContainText('no lambda conversion is performed');
});
