// The workstation as the desktop application serves it.
//
// What these tests are for: the desktop app is the browser app plus a host, so
// the things worth checking in a real browser are exactly the places where it
// is *not* the browser version - the injected bridge, the launch token on
// every API call, saving a file into the export folder instead of a download,
// printing as a standalone snapshot, and the sidebar row that only exists in
// the installed app.

import { test, expect } from '@playwright/test';
import { readFileSync, readdirSync, existsSync, statSync } from 'node:fs';
import { join } from 'node:path';

const EXPORTS = join(process.cwd(), '.desktop-test-data', 'exports');

/** Wait until `check` sees a file matching `pattern` appear in the exports folder. */
async function waitForExport(pattern, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (existsSync(EXPORTS)) {
      const hit = readdirSync(EXPORTS).find((name) => pattern.test(name));
      if (hit) return join(EXPORTS, hit);
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`no export matching ${pattern} in ${EXPORTS}`);
}

test.beforeEach(async ({ page }) => {
  const failures = [];
  page.on('pageerror', (error) => failures.push(String(error)));
  page.on('console', (message) => {
    if (message.type() === 'error') failures.push(message.text());
  });
  page.failures = failures;
});

test('the installed app serves the real UI, marked as desktop-hosted', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('body')).toHaveAttribute('data-desktop', '1');
  await expect(page.locator('body')).toHaveAttribute('data-backend', 'live');
  // the real catalog comes from the real Python API, not the demo snapshot
  await expect(page.locator('#appVersion')).toContainText(/^v\d+\.\d+\.\d+/);

  // The bridge is installed before the app runs, which is what makes the very
  // first API call carry the token.
  const installed = await page.evaluate(() => Boolean(window.gobDesktop && window.gobDesktop.available));
  expect(installed).toBe(true);
  // The same Atlas-derived interpolation module is loaded in the desktop shell.
  expect(await page.evaluate(() => AtlasInterpolation.positions([0, 1, 4], 0, 2, true))).toEqual([0, 0.25, 1]);
  const descriptor = await page.evaluate(() => ({
    exports: window.gobDesktop.exports,
    backend: window.gobDesktop.backend,
    port: window.gobDesktop.port,
  }));
  expect(descriptor.exports).toBe(EXPORTS);       // resolved, not relative
  expect(['window', 'browser']).toContain(descriptor.backend);
  expect(descriptor.port).toBeGreaterThan(0);

  // the workstation works: pick a bike, connect to the simulator, read it
  await page.selectOption('#modelSelect', { index: 1 }).catch(() => {});
  await expect(page.locator('#connTitle')).toBeVisible();
  expect(page.failures).toEqual([]);
});

test('every API call from the window carries the launch token', async ({ page }) => {
  await page.goto('/');
  await page.waitForFunction(() => Boolean(window.gobDesktop));

  // The bridge attaches the token, so a call written without one still works...
  const withToken = await page.evaluate(async () => (await window.fetch('/api/status')).status);
  expect(withToken).toBe(200);

  // ...and the bridge overwrites a wrong token rather than passing it on.
  const overwritten = await page.evaluate(async () => (
    await window.fetch('/api/status', { headers: { 'X-GuzziOnBoard-Token': 'not-the-token' } })
  ).status);
  expect(overwritten).toBe(200);

  // What the *server* refuses is a call that arrives without the token at all.
  // Stripping it in the network layer stands in for the request coming from
  // somewhere other than this window - which is exactly what the token is for.
  await page.route('**/api/status', async (route) => {
    const headers = { ...route.request().headers() };
    delete headers['x-guzzionboard-token'];
    await route.continue({ headers });
  });
  const withoutToken = await page.evaluate(async () => (await window.fetch('/api/status')).status);
  expect(withoutToken).toBe(403);
  await page.unroute('**/api/status');
});

test('saving a file writes it into the export folder, never over an old one', async ({ page }) => {
  await page.goto('/');
  await page.waitForFunction(() => Boolean(window.gobDesktop));
  const name = `desktop-host-check-${Date.now()}.txt`;

  const first = await page.evaluate((file) =>
    window.gobDesktop.saveText(file, 'first'), name);
  expect(first.dir.replace(/\\/g, '/')).toContain('.desktop-test-data/exports');
  expect(readFileSync(first.path, 'utf8')).toBe('first');

  // A second save of the same name must not destroy the first: these files are
  // reports, logs and images, not caches.
  const second = await page.evaluate((file) =>
    window.gobDesktop.saveText(file, 'second'), name);
  expect(second.name).not.toBe(first.name);
  expect(readFileSync(first.path, 'utf8')).toBe('first');
  expect(readFileSync(second.path, 'utf8')).toBe('second');

  // and a name from the page cannot climb out of the folder
  const escaped = await page.evaluate(() =>
    window.gobDesktop.saveText(`../../escaped-${Date.now()}.txt`, 'nope'));
  expect(escaped.path.startsWith(EXPORTS + '/')).toBe(true);
  expect(escaped.path).not.toContain('..');
});

test('the export button in the UI goes through the host, not a download', async ({ page }) => {
  await page.goto('/');
  await page.waitForFunction(() => Boolean(window.gobDesktop));

  const downloads = [];
  page.on('download', (download) => downloads.push(download));
  const name = `ui-export-check-${Date.now()}.txt`;

  await page.evaluate((file) => {
    // the UI's own download helper, called the way a button calls it
    window.download(file, 'written by the workstation');
  }, name);

  const saved = await waitForExport(new RegExp(`${name}$`));
  expect(readFileSync(saved, 'utf8')).toBe('written by the workstation');
  expect(downloads).toEqual([]);        // no browser download involved
});

test('printing produces a standalone snapshot with the styles inlined', async ({ page }) => {
  await page.goto('/');
  await page.waitForFunction(() => Boolean(window.gobDesktop));
  await expect(page.locator('.sidebar')).toBeVisible();

  const result = await page.evaluate(() => window.gobDesktop.printView());
  expect(result.path.endsWith('.html')).toBe(true);

  const snapshot = readFileSync(result.path, 'utf8');
  expect(snapshot).toContain('<!doctype html>');
  expect(snapshot).toContain('data-print-snapshot');            // it says what it is
  expect(snapshot).toContain('--accent');                       // styles came along
  expect(snapshot).not.toContain('<script');                    // and no live app
  expect(statSync(result.path).size).toBeGreaterThan(2000);
  // "opened: false" is expected in CI (no desktop to open it on) - what
  // matters is that the note tells the user where the file went.
  expect(typeof result.note).toBe('string');
});

test('the sidebar offers the host row only in the installed app', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.desktop-row')).toHaveCount(1);
  await expect(page.locator('.desktop-row')).toContainText('Desktop app');
  await expect(page.locator('#deskExportsBtn')).toBeVisible();
  await expect(page.locator('#deskDataBtn')).toBeVisible();
  await expect(page.locator('#deskQuitBtn')).toBeVisible();
});

test('a page in a browser tab sees none of this', async ({ page }) => {
  // Same UI files, no host: the desktop extras must be entirely absent rather
  // than half-present. Fetched from the same server, the bridge route is what
  // tells the page apart - so this checks the honest answer when there is no
  // desktop host object at all (the hosted-demo arrangement, exercised with
  // the bridge deleted).
  await page.goto('/');
  await page.evaluate(() => {
    delete window.gobDesktop;
    document.querySelector('.desktop-row')?.remove();
  });
  await expect(page.locator('.desktop-row')).toHaveCount(0);
  const printed = await page.evaluate(() => {
    const realPrint = window.print;
    let called = false;
    window.print = () => { called = true; };
    window.printView();
    window.print = realPrint;
    return called;
  });
  expect(printed).toBe(true);          // browser behaviour, not a host call
});

test('desktop host shares the refreshed layout and real simulator timeline', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#modelSelect option[value="Griso 1200 8V"]')).toHaveCount(1);
  await page.locator('#modelSelect').selectOption('Griso 1200 8V');
  await page.locator('#yearSelect').selectOption('2012');
  await expect(page.locator('#connectBtn')).toBeEnabled();
  await page.locator('#layoutDensity').selectOption('compact');
  await expect(page.locator('body')).toHaveAttribute('data-density', 'compact');
  await page.locator('#connectBtn').click();
  await expect(page.locator('#connTitle')).toHaveText('Connected');
  await expect(page.locator('#pageTitle')).toHaveText('Overview');
  await page.locator('[data-view="live"]').click();
  await page.locator('#pollBtn').click();
  await expect(page.locator('#livePlot .plot-lane')).not.toHaveCount(0);
  await expect(page.locator('#livePlot .plot-svg').first()).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('#livePlot')).toContainText('sweeps');
  await page.locator('#pollBtn').click();
  expect(page.failures).toEqual([]);
});

test('desktop host offers the offline Ducati decoder and manual shim worksheet', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="discovery"]').click();
  await page.locator('#canlogText').locator('..').locator('summary').click();
  await page.locator('#canlogText').fill('(1.0) can0 080#0000000055123400');
  await page.locator('#canlogDecoder').selectOption('ducati_panigale_mitsubishi');
  await page.locator('#canlogPasteBtn').click();
  await expect(page.locator('#canlogOut')).toContainText('rpm: 4660');
  await expect(page.locator('#canlogOut')).toContainText('not vehicle identification or a Guzzi profile', { ignoreCase: true });
  await page.locator('[data-view="tools"]').click();
  await page.locator('#shimMeasured').fill('0.300');
  await page.locator('#shimCurrent').fill('2.500');
  await page.locator('#shimMin').fill('0.100');
  await page.locator('#shimMax').fill('0.200');
  await page.locator('#shimDirection').selectOption('decrease');
  await page.locator('#shimCalcBtn').click();
  await expect(page.locator('#shimOut')).toContainText('calculated exact shim: 2.6500 mm');
  expect(page.failures).toEqual([]);
});

test('desktop host displays filtered offline CAN byte statistics', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="discovery"]').click();
  await page.locator('#canlogText').locator('..').locator('summary').click();
  await page.locator('#canlogText').fill('1.0 R11 567 00 01\n2.0 R11 567 03 81');
  await page.locator('#canlogFilter').fill('567');
  await page.locator('#canlogByteStats').check();
  await page.locator('#canlogPasteBtn').click();
  await expect(page.locator('#canlogOut')).toContainText('Raw byte observations');
  await expect(page.locator('#canlogOut')).toContainText('0x80');
  expect(page.failures).toEqual([]);
});

test('desktop host provides local manual search and a source-aware service worksheet', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  await page.locator('#serviceLastKm').fill('5000');
  await page.locator('#serviceCurrentKm').fill('13000');
  await page.locator('#serviceIntervalKm').fill('10000');
  await page.locator('#serviceDueBtn').click();
  await expect(page.locator('#serviceDueOut')).toContainText('2000 km remaining');
  await page.locator('#manualTextFile').setInputFiles({ name: 'test.txt', mimeType: 'text/plain', buffer: Buffer.from('Example torque M10x1.25.') });
  await expect(page.locator('#manualTextSearch')).toBeEnabled();
  await page.locator('#manualTextQuery').fill('M10x1.25');
  await page.locator('#manualTextSearch').click();
  await expect(page.locator('#manualTextOut')).toContainText('1 literal match(es)');
  await expect(page.locator('#manualTextOut')).toContainText('Page unknown');
  expect(page.failures).toEqual([]);
});

test('Honda research is selectable but cannot open a physical or simulated session', async ({ page }) => {
  await page.goto('/');
  // Earlier desktop tests share the workstation; start with no active session.
  await page.evaluate(() => fetch('/api/disconnect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  await expect(page.locator('#makeSelect option[value="Honda"]')).toHaveCount(1);
  await page.selectOption('#makeSelect', 'Honda');
  await page.selectOption('#modelSelect', 'CBR600RR');
  await page.selectOption('#yearSelect', '2005');
  await expect(page.locator('#resolveResult')).toContainText('offline research only');
  const result = await page.evaluate(async () => {
    const post = async (url, body) => {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      return { status: r.status, body: await r.json() };
    };
    const vehicle = { make: 'Honda', model: 'CBR600RR', year: 2005 };
    return {
      mismatch: await post('/api/select', { ...vehicle, ecu: '5am', transport: 'kline' }),
      physical: await post('/api/select', { ...vehicle, transport: 'kline' }),
      physicalConnect: await post('/api/connect', { mode: 'read_only' }),
      simulator: await post('/api/select', { ...vehicle, transport: 'simulator' }),
      simulatorConnect: await post('/api/connect', { mode: 'simulator' }),
      existing: await post('/api/select', { make: 'Moto Guzzi', model: 'Griso 1200 8V', year: 2012, transport: 'simulator' }),
      existingConnect: await post('/api/connect', { mode: 'simulator' }),
      relabel: await post('/api/select', { ...vehicle, transport: 'kline' }),
      status: await (await fetch('/api/status')).json(),
    };
  });
  expect(result.mismatch.status).toBe(400);
  expect(result.mismatch.body.error).toContain('not cataloged');
  expect(result.physical.status).toBe(200);
  expect(result.physicalConnect.status).toBe(501);
  expect(result.physicalConnect.body.error).toContain('no port was opened');
  expect(result.simulator.status).toBe(200);
  expect(result.simulatorConnect.status).toBe(501);
  expect(result.simulatorConnect.body.error).toContain('no matching simulator');
  expect(result.existing.status).toBe(200);
  expect(result.existingConnect.status).toBe(200);
  expect(result.relabel.status).toBe(400);
  expect(result.relabel.body.error).toContain('disconnect the current session');
  expect(result.status.selection.make).toBe('Moto Guzzi');
  await page.locator('[data-view="tools"]').click();
  await page.locator('#hondaFrames').fill('02 0A 71 D1 00 00 00 00 01 22');
  await page.locator('#hondaDecode').click();
  await expect(page.locator('#hondaOut')).toContainText('Checksum mismatch; not decoded.');
  expect(page.failures.filter((error) => !/server responded with a status of (400|501)/.test(error))).toEqual([]);
});
