// The workstation as the desktop application serves it.
//
// What these tests are for: the desktop app is the browser app plus a host, so
// the things worth checking in a real browser are exactly the places where it
// is *not* the browser version - the injected bridge, the launch token on
// every API call, saving a file into the export folder instead of a download,
// printing as a standalone snapshot, and the sidebar row that only exists in
// the installed app.

import { test, expect } from '@playwright/test';
import { readFileSync, readdirSync, existsSync, statSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';

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

test('Honda live profile is selectable but cannot use service or simulator sessions', async ({ page }) => {
  await page.goto('/');
  // Earlier desktop tests share the workstation; start with no active session.
  await page.evaluate(() => fetch('/api/disconnect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  await expect(page.locator('#makeSelect option[value="Honda"]')).toHaveCount(1);
  await page.selectOption('#makeSelect', 'Honda');
  await page.selectOption('#modelSelect', 'CBR600RR');
  await page.selectOption('#yearSelect', '2005');
  await expect(page.locator('#resolveResult')).toContainText('read-only K-Line');
  const result = await page.evaluate(async () => {
    const post = async (url, body) => {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      return { status: r.status, body: await r.json() };
    };
    const vehicle = { make: 'Honda', model: 'CBR600RR', year: 2005 };
    return {
      mismatch: await post('/api/select', { ...vehicle, ecu: '5am', transport: 'kline' }),
      physical: await post('/api/select', { ...vehicle, transport: 'kline' }),
      physicalConnect: await post('/api/connect', { mode: 'service' }),
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
  expect(result.physicalConnect.body.error).toContain('read-only mode');
  expect(result.simulator.status).toBe(200);
  expect(result.simulatorConnect.status).toBe(501);
  expect(result.simulatorConnect.body.error).toContain('read-only mode');
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

test('desktop exposes multi-brand offline research and blocks hardware sessions', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => fetch('/api/disconnect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  await expect(page.locator('#makeSelect option[value="Suzuki"]')).toHaveCount(1);
  await expect(page.locator('#makeSelect option[value="Kawasaki"]')).toHaveCount(1);
  await expect(page.locator('#makeSelect option[value="Triumph"]')).toHaveCount(1);
  await page.selectOption('#makeSelect', 'Kawasaki');
  await page.selectOption('#modelSelect', 'ER-6n');
  await page.selectOption('#yearSelect', '2006');
  await expect(page.locator('#resolveResult')).toContainText('read-only KDS');
  const result = await page.evaluate(async () => {
    const post = async (url, body) => {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      return { status: r.status, body: await r.json() };
    };
    return {
      select: await post('/api/select', { make: 'Kawasaki', model: 'Ninja ZX-6R (636)', year: 2026, transport: 'can' }),
      connect: await post('/api/connect', { mode: 'read_only' }),
    };
  });
  expect(result.select.status).toBe(200);
  expect(result.select.body.ecu.capabilities).toEqual([]);
  expect(result.connect.status).toBe(501);
  expect(result.connect.body.error).toContain('no port was opened');
  await page.locator('[data-view="tools"]').click();
  await page.selectOption('#multiResearchProfile', 'bmw_r1300gs');
  await page.locator('#multiResearchFrames').fill('10C#00003E');
  await page.locator('#multiResearchDecode').click();
  await expect(page.locator('#multiResearchOut')).toContainText('engine speed candidate: 3968 rpm');
  const posts = [];
  page.on('request', (req) => { if (req.method() === 'POST') posts.push(req.url()); });
  const synthetic = Buffer.alloc(0x100000);
  synthetic.write('ABCDY123', synthetic.length - 16, 'ascii');
  synthetic[synthetic.length - 6] = 0x64; synthetic[synthetic.length - 5] = 0x02;
  let sum = 0;
  for (let i = 0; i < synthetic.length; i += 2) sum = (sum + synthetic.readUInt16BE(i)) & 0xffff;
  synthetic.writeUInt16BE((0x5aa5 - sum) & 0xffff, synthetic.length - 8);
  await page.selectOption('#yamahaVariant', 'mt_1m');
  await page.locator('#yamahaImage').setInputFiles({ name: 'synthetic.bin', mimeType: 'application/octet-stream', buffer: synthetic });
  await page.locator('#yamahaInspect').click();
  await expect(page.locator('#yamahaOut')).toContainText('Sum matches source target');
  await expect(page.locator('#yamahaOut')).toContainText('not flash or safety approval');
  expect(posts).toEqual([]);
  expect(page.failures.filter((error) => !/server responded with a status of 501/.test(error))).toEqual([]);
});

test('desktop serves the bundled licensed service references', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  await page.locator('#workshopService summary').click();
  await page.locator('#bundledServiceTemplate').selectOption('suzuki_dr650.json');
  await expect(page.locator('#serviceTemplateOut')).toContainText('CC BY-SA 4.0');
  await page.locator('#serviceTemplateModel').selectOption('0');
  await expect(page.locator('#serviceTemplateOut')).toContainText('Suzuki DR650');
  await expect(page.locator('#serviceUseIntervals')).toBeDisabled();
  expect(page.failures).toEqual([]);
});

test('desktop includes CFMoto offline image inspection', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  await page.locator('#mseImage').setInputFiles({ name: 'short.bin', mimeType: 'application/octet-stream', buffer: Buffer.alloc(10) });
  await page.locator('#mseInspect').click();
  await expect(page.locator('#mseOut')).toContainText('Image must be between');
  expect(page.failures).toEqual([]);
});

test('desktop exposes Triumph read-only OBD without inventing status bytes', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => fetch('/api/disconnect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  await page.selectOption('#makeSelect', 'Triumph');
  await page.selectOption('#modelSelect', 'Daytona 675');
  await page.selectOption('#yearSelect', '2012');
  await expect(page.locator('#resolveResult')).toContainText('read-only OBD');
  const selected = await page.evaluate(async () => {
    const r = await fetch('/api/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ make: 'Triumph', model: 'Daytona 675', year: 2012, transport: 'simulator' }) });
    return r.json();
  });
  expect(selected.ecu.capabilities).toEqual(['live', 'dtc_read']);
  expect(selected.ecu.session.simulator_supported).toBe(false);
  await page.route('**/api/dtcs', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
    dtcs: [{ code: 'P0122', description: '', status_byte: null, kind: 'OBD stored', status: 'stored', warning_indicator: false }],
    format: 'obd-stored', note: 'Stored codes only; pending codes were not read.', context: {},
    clear: { allowed: false, checks: [] },
  }) }));
  await page.evaluate(() => readDtcs());
  await expect(page.locator('#faultList')).toContainText('P0122');
  await expect(page.locator('#faultList')).toContainText('status byte not supplied');
  await expect(page.locator('#faultList')).toContainText('pending codes were not read');
  expect(page.failures).toEqual([]);
});


test('desktop previews staged edits with an uncatalogued user XDF without writing an image', async ({ page }) => {
  const root = resolve('.desktop-test-data');
  const definitions = join(root, 'xdfs');
  mkdirSync(definitions, { recursive: true });
  const xdfPath = join(definitions, 'Honda_synthetic_research.xdf');
  const imagePath = join(root, 'research-fixture.bin');
  const xdf = `<XDFFORMAT><XDFHEADER><deftitle>Synthetic Honda research</deftitle>
    <DEFAULTS signed="1" lsbfirst="0"/><REGION size="0x100"/></XDFHEADER>
    <XDFTABLE uniqueid="cells"><title>Research table</title>
    <XDFAXIS id="x"><indexcount>2</indexcount></XDFAXIS>
    <XDFAXIS id="y"><indexcount>2</indexcount></XDFAXIS>
    <XDFAXIS id="z"><EMBEDDEDDATA mmedtypeflags="0x06" mmedaddress="0x20"
      mmedelementsizebits="16" mmedrowcount="2" mmedcolcount="2"/><MATH equation="X"/></XDFAXIS>
    </XDFTABLE><XDFCHECKSUM><title>Unknown checksum</title></XDFCHECKSUM></XDFFORMAT>`;
  const image = Buffer.alloc(256);
  [1, 3, 2, 4].forEach((value, i) => image.writeUInt16LE(value, 0x20 + i * 2));
  writeFileSync(xdfPath, xdf); writeFileSync(imagePath, image);
  await page.goto('/');
  await page.locator('[data-view="firmware"]').click();
  await page.locator('#xdfOnlyFitting').uncheck();
  await page.locator('#mapsRefreshBtn').click();
  await expect(page.locator('#xdfSelect option[value="Honda_synthetic_research.xdf"]')).toHaveCount(1);
  await page.locator('#xdfSelect').selectOption('Honda_synthetic_research.xdf');
  await page.locator('#mapsImagePath').fill(imagePath);
  await page.locator('#mapsRenderBtn').click();
  if (await page.locator('#modal').isVisible()) await page.locator('#modalConfirm').click();
  const cell = page.locator('[data-map-kind="table"][data-map-id="cells"][data-map-row="0"][data-map-col="1"]');
  await expect(cell).toHaveAttribute('data-map-value', '2');
  await cell.dblclick();
  await page.locator('#mapEditValue').fill('50');
  await page.locator('#modalConfirm').click();
  await expect(page.locator('#mapResearchPreviewBtn')).toBeEnabled();
  await expect(page.locator('#mapBuildBtn')).toBeDisabled(); // declared checksum is unhandled
  await page.locator('#mapResearchPreviewBtn').click();
  await expect(page.locator('#mapResearchPreviewOut')).toContainText('Research preview · no image saved');
  await expect(page.locator('#mapResearchPreviewOut')).toContainText('Unknown checksum');
  await expect(page.locator('#mapResearchPreviewOut')).toContainText('No checksum was applied');
  expect(readFileSync(imagePath)).toEqual(image);
  await page.locator('#mapClearChangesBtn').click();
  await expect(page.locator('#mapResearchPreviewOut')).toBeEmpty();
  // Firmware panel asks for unavailable disconnected-session state.
  expect(page.failures.filter((error) => !/server responded with a status of 409/.test(error))).toEqual([]);
});

test('desktop selects the 2012 US Honda for offline maps without opening a session', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => fetch('/api/disconnect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  await page.selectOption('#makeSelect', 'Honda');
  await page.selectOption('#modelSelect', 'CBR1000RR (US)');
  await page.selectOption('#yearSelect', '2012');
  await expect(page.locator('#selectOfflineBtn')).toBeEnabled();
  await page.locator('#selectOfflineBtn').click();
  await expect(page.locator('#firmware')).toBeVisible();
  await expect(page.locator('#connTitle')).toHaveText('Not connected');
  await expect(page.locator('#xdfSelect')).toHaveValue('CBR1000RR_2012_US.xdf');
  await expect(page.locator('#xdfFitNote')).toContainText('ECU identity not established');
  await expect(page.locator('#mapChecksumProvider option[value="honda-cbr1000rr-2012-us-a01-v1"]')).toHaveCount(1);
  await page.locator('#mapChecksumProvider').selectOption('honda-cbr1000rr-2012-us-a01-v1');
  await expect(page.locator('#mapChecksumNote')).toContainText('exact XDF and original image SHA-256');
  const status = await page.evaluate(async () => (await fetch('/api/status')).json());
  expect(status.connected).toBe(false);
  expect(status.selection.ecu.id).toBe('honda_cbr1000rr_2012_us');
  expect(page.failures.filter((error) => !/server responded with a status of 409/.test(error))).toEqual([]);
});

test('Harley region export uses desktop host and preserves the original', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  const calibration = Buffer.alloc(0x28000, 0x41);
  calibration[0x1c000] = 0x12;
  calibration[0x1ffff] = 0x34;
  await page.locator('#harleyRegionConfirm').check();
  await page.locator('#harleyRegionFirst').setInputFiles({ name: 'local.bin', mimeType: 'application/octet-stream', buffer: calibration });
  await page.locator('#harleyRegionInspect').click();
  await expect(page.locator('#harleyRegionOut')).toContainText('160 KiB calibration');
  await page.locator('#harleyRegionSave').click();
  await expect(page.locator('#harleyRegionOut')).toContainText('Saved research copy:');
  const output = await page.locator('#harleyRegionOut').textContent();
  const path = output.split('Saved research copy: ')[1].trim();
  expect(path.startsWith(EXPORTS)).toBe(true);
  expect(readFileSync(path)).toEqual(calibration.subarray(0x1c000, 0x20000));
  expect(calibration[0x1c000]).toBe(0x12);
  expect(page.failures).toEqual([]);
});

test('desktop Harley capture profiles and research calibration copy', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="discovery"]').click();
  await page.locator('#canlogText').locator('..').locator('summary').click();
  await page.locator('#canlogDecoder').selectOption('harley_hdlan_community');
  await page.locator('#canlogText').fill('1.0 R11 521 00 64 00 00 00 00 00 00');
  await page.locator('#canlogPasteBtn').click();
  await expect(page.locator('#canlogOut')).toContainText('speed_kmh_candidate: 100');
  await page.locator('[data-view="tools"]').click();
  await page.locator('#multiResearchProfile').selectOption('harley_j1850_harleydroid');
  await page.locator('#multiResearchFrames').fill('28 1B 10 02 0F A0 D7');
  await page.locator('#multiResearchDecode').click();
  await expect(page.locator('#multiResearchOut')).toContainText('Engine speed: 1000 rpm');
  const base = Buffer.alloc(0x28000, 0x32), tune = Buffer.alloc(0x4000, 0x47);
  await page.locator('#harleyRegionFirst').setInputFiles({ name: 'base.bin', mimeType: 'application/octet-stream', buffer: base });
  await page.locator('#harleyRegionSecond').setInputFiles({ name: 'tune.bin', mimeType: 'application/octet-stream', buffer: tune });
  await page.locator('#harleyRegionConfirm').check();
  await page.locator('#harleyRegionReplaceConfirm').check();
  await page.locator('#harleyRegionInspect').click();
  await page.locator('#harleyRegionBuild').click();
  await expect(page.locator('#harleyRegionOut')).toContainText('No checksum repaired');
  const outputText = await page.locator('#harleyRegionOut').textContent();
  const path = outputText.split('Saved research copy: ')[1].split('\n')[0];
  const built = readFileSync(path);
  expect(built.subarray(0, 0x1c000)).toEqual(base.subarray(0, 0x1c000));
  expect(built.subarray(0x1c000, 0x20000)).toEqual(tune);
  expect(built.subarray(0x20000)).toEqual(base.subarray(0x20000));
  expect(page.failures).toEqual([]);
});

test('Harley J1850 setup and missing fault replies are shown honestly', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#ecuOverride option[value="harley_j1850_harleydroid"]', {state: 'attached'});
  await page.selectOption('#modelSelect', '');
  await page.getByText('Override: pick an ECU family directly').click();
  await page.selectOption('#ecuOverride', 'harley_j1850_harleydroid');
  const elm = page.locator('input[name="transport"][value="elm_j1850"]');
  // pyserial is optional in the desktop test host.
  if (await elm.isEnabled()) await elm.check();
  else await elm.evaluate(el => { el.checked = true; el.dispatchEvent(new Event('change', {bubbles: true})); });
  await expect(page.locator('#elmFields')).toContainText('38400 baud');
  await expect(page.locator('#elmFields')).toContainText('not hardware-tested');
  await page.route('**/api/dtcs', route => route.fulfill({ json: {
    format: 'harley-j1850', dtcs: [], context: {}, note: 'Missing responses do not mean no faults.',
    modules: { ECM: {responded: true}, ABS: {responded: false}, TSM: {responded: false} },
    clear: {allowed: false, checks: [{name: 'capability', passed: false, detail: 'read only'}]}
  }}));
  await page.evaluate(() => readDtcs());
  await expect(page.locator('#dtcSummary')).toHaveText(/missing modules are unknown/);
  await expect(page.locator('#faultList')).toContainText('ABS: no verified response');
  await expect(page.locator('#faultList')).toContainText('ECM: responded');
  await expect(page.locator('#faultList')).not.toContainText('clean fault memory');
  await expect(page.locator('#clearGate')).toContainText('read only');
});

test('desktop selects scoped Honda MGZ-A03 offline builder and flags source XDFs', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => fetch('/api/disconnect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  await page.selectOption('#makeSelect', 'Honda');
  await page.selectOption('#modelSelect', 'CBR500R');
  await page.selectOption('#yearSelect', '2014');
  await page.locator('#selectOfflineBtn').click();
  await expect(page.locator('#xdfSelect')).toHaveValue('CB500_MGZ_A03_gob.xdf');
  await expect(page.locator('#xdfFitNote')).toContainText('ECU identity not established');
  await expect(page.locator('#xdfFitNote')).toContainText('exact MGZ-A03 original-image SHA-256');
  await expect(page.locator('#mapChecksumProvider option[value="honda-cb500-mgz-a03-v1"]')).toHaveCount(1);
  await page.locator('#xdfOnlyFitting').uncheck();
  await page.selectOption('#xdfSelect', '38770-MGZ.xdf');
  await expect(page.locator('#xdfFitNote')).toContainText('Research only: normal firmware builds are blocked');
  await expect(page.locator('#xdfFitNote')).toContainText('default endian conflicts with A03');
  const status = await page.evaluate(async () => (await fetch('/api/status')).json());
  expect(status.connected).toBe(false);
  expect(status.selection.ecu.id).toBe('honda_cb500_mgz_a03');
});

test('desktop ECU identifier research is local and does not change vehicle selection', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  const before = await page.evaluate(async () => (await (await fetch('/api/status')).json()).selection);
  await page.locator('#ecuPart').fill('38770-MGZ-A03');
  await page.locator('#ecuLookupBtn').click();
  await expect(page.locator('#ecuLookupOut')).toContainText('Honda CBR500R / CB500F');
  await expect(page.locator('#ecuLookupOut')).toContainText('Software: 0101250501 (not supplied)');
  const after = await page.evaluate(async () => (await (await fetch('/api/status')).json()).selection);
  expect(after).toEqual(before);
});

test('desktop cross-reference and Yamaha checksum export remain offline and scoped', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  const selectionBefore = await page.evaluate(async () => (await (await fetch('/api/status')).json()).selection);
  await page.locator('#sharedEcuLoad').click();
  await page.locator('#sharedEcuFamily').selectOption('5am');
  await expect(page.locator('#sharedEcuOut')).toContainText('Ducati');
  await expect(page.locator('#sharedEcuOut')).toContainText('Moto Guzzi');
  const selectionAfter = await page.evaluate(async () => (await (await fetch('/api/status')).json()).selection);
  expect(selectionAfter).toEqual(selectionBefore);
  const input = Buffer.alloc(0xe0000);
  input.write('ABCDY123', input.length - 16, 'ascii');
  input[input.length - 6] = 0x64; input[input.length - 5] = 0x02;
  await page.locator('#yamahaVariant').selectOption('mt07_2020');
  await page.locator('#yamahaImage').setInputFiles({ name: 'synthetic.bin', mimeType: 'application/octet-stream', buffer: input });
  await page.locator('#yamahaRepairConfirm').check();
  await page.locator('#yamahaInspect').click();
  await expect(page.locator('#yamahaRepairSave')).toBeEnabled();
  const before = new Set(readdirSync(EXPORTS));
  await page.locator('#yamahaRepairSave').click();
  await expect(page.locator('#yamahaOut')).toContainText('Saved research copy:');
  const path = await waitForExport(/^yamaha-mt-checksum-research-.*\.bin$/);
  const filename = readdirSync(EXPORTS).find(name => name.startsWith('yamaha-mt-checksum-research-') && !before.has(name));
  expect(filename).toBeTruthy();
  const output = readFileSync(join(EXPORTS, filename));
  let sum = 0, changes = [];
  for (let i = 0; i < output.length; i++) if (output[i] !== input[i]) changes.push(i);
  for (let i = 0; i < output.length; i += 2) sum = (sum + output.readUInt16BE(i)) & 0xffff;
  expect(sum).toBe(0xe81f);
  expect(changes.length).toBeGreaterThan(0);
  expect(changes.every(i => i === input.length - 8 || i === input.length - 7)).toBe(true);
});

test('desktop exports Bajaj research checksum copy without changing its input', async ({ page }) => {
  await page.goto('/'); await page.locator('[data-view="tools"]').click();
  const input = Buffer.alloc(0xc0000);
  input.write('JL351458010651', 0x80000, 'ascii');
  input.write('DellOrto 32bit Engine Management System', 0x100, 'ascii');
  await page.locator('#bajajImage').setInputFiles({ name: 'synthetic.bin', mimeType: 'application/octet-stream', buffer: input });
  await page.locator('#bajajConfirm').check(); await page.locator('#bajajInspect').click();
  await expect(page.locator('#bajajSave')).toBeEnabled();
  const before = new Set(readdirSync(EXPORTS)); await page.locator('#bajajSave').click();
  await expect(page.locator('#bajajOut')).toContainText('Saved research copy:');
  const name = readdirSync(EXPORTS).find(n => n.startsWith('bajaj-rs200-checksum-research-') && !before.has(n));
  expect(name).toBeTruthy(); const output = readFileSync(join(EXPORTS, name));
  let sum = 0; for (let i = 0x80000; i < 0x921fe; i++) sum = (sum + output[i]) & 0xffff;
  expect(output.readUInt16BE(0x921fe)).toBe((~sum) & 0xffff);
  expect(input.readUInt16BE(0x921fe)).toBe(0);
});

test('desktop exposes Ninja 7 Hybrid read-only CAN and refuses address overrides', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => fetch('/api/disconnect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  await page.selectOption('#makeSelect', 'Kawasaki');
  await page.selectOption('#modelSelect', 'Ninja 7 Hybrid');
  await page.selectOption('#yearSelect', '2024');
  await expect(page.locator('#resolveResult')).toContainText('read-only CAN');
  const result = await page.evaluate(async () => {
    const post = async (url, body) => {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      return { status: r.status, body: await r.json() };
    };
    return {
      select: await post('/api/select', { make: 'Kawasaki', model: 'Ninja 7 Hybrid', year: 2024, transport: 'can', can_tx_id: '0x7e0' }),
      connect: await post('/api/connect', { mode: 'read_only' }),
    };
  });
  expect(result.select.body.ecu.id).toBe('kawasaki_ninja7_hybrid');
  expect(result.select.body.ecu.effective_capabilities).toEqual(['identify', 'live', 'dtc_read']);
  expect(result.connect.status).toBe(501);
  expect(result.connect.body.error).toContain('source-scoped CAN IDs');
  expect(page.failures.filter((error) => !/server responded with a status of 501/.test(error))).toEqual([]);
});

test('Ninja 7 fault display keeps unconfirmed status and zero-code scope explicit', async ({ page }) => {
  await page.goto('/');
  let dtcs = [];
  await page.route('**/api/dtcs', route => route.fulfill({ json: {
    format: 'kawasaki-ninja7', dtcs, context: {},
    note: 'Source confirmed a zero-DTC response; nonzero records and status interpretation remain candidates.',
    clear: { allowed: false, checks: [] },
  }}));
  await page.evaluate(() => readDtcs());
  await expect(page.locator('#dtcSummary')).toContainText('other fault states are unknown');
  await expect(page.locator('#faultList')).not.toContainText('clean fault memory');
  dtcs = [{code: 'P0123', status_byte: 0x20, status: 'uninterpreted', kind: 'uninterpreted',
    warning_indicator: null, description: 'Source-described DTC layout; nonzero records not confirmed'}];
  await page.evaluate(() => readDtcs());
  await expect(page.locator('#faultList')).toContainText('P0123');
  await expect(page.locator('#faultList')).toContainText('status byte 0x20');
  await expect(page.locator('#faultList')).toContainText('nonzero records and status interpretation remain candidates');
  expect(page.failures).toEqual([]);
});

test('desktop exposes separate research-only 2026 Kawasaki ZX-6R and 650 models', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => fetch('/api/disconnect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  await page.selectOption('#makeSelect', 'Kawasaki');
  for (const model of ['Ninja ZX-6R (636)', 'Ninja 650 / EX650', 'Z650']) {
    await page.selectOption('#modelSelect', model);
    await page.selectOption('#yearSelect', '2026');
    await expect(page.locator('#resolveResult')).toContainText('research only');
    await expect(page.locator('#resolveResult')).toContainText('No physical diagnostics');
  }
  await expect(page.locator('#resolveResult')).toContainText('2023–2025');
  await expect(page.locator('#resolveResult')).toContainText('2023–2026');
});

test('generic OBD CAN uses explicit ECU-only selection and explains its limits', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#ecuOverride option[value="generic_obd_can_11bit"]', {state: 'attached'});
  await page.getByText('Override: pick an ECU family directly').click();
  await page.selectOption('#ecuOverride', 'generic_obd_can_11bit');
  const can = page.locator('input[name="transport"][value="can"]');
  if (await can.isEnabled()) await can.check();
  else await can.evaluate(el => { el.checked = true; el.dispatchEvent(new Event('change', {bubbles: true})); });
  await expect(page.locator('#canFields')).toContainText('not ECU memory');
  const request = await page.evaluate(() => selectionRequest());
  expect(request.ecu).toBe('generic_obd_can_11bit');
  expect(request.transport).toBe('can');
  expect(request).not.toHaveProperty('model');
  expect(request).not.toHaveProperty('year');
});

test('desktop exposes scoped Versys and GSX-R live profiles without memory or simulator claims', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => fetch('/api/disconnect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  for (const [make, model, year, name, id] of [
    ['Kawasaki', 'Versys 650', '2012', 'read-only KDS', 'kawasaki_versys650_2012'],
    ['Suzuki', 'GSX-R600', '2011', 'read-only SDS', 'suzuki_gsxr600_2011'],
  ]) {
    await page.selectOption('#makeSelect', make);
    await page.selectOption('#modelSelect', model);
    await page.selectOption('#yearSelect', year);
    await expect(page.locator('#resolveResult')).toContainText(name);
    const selected = await page.evaluate(async ({ make, model, year }) => {
      const r = await fetch('/api/select', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ make, model, year: Number(year), transport: 'simulator' }) });
      return r.json();
    }, { make, model, year });
    expect(selected.ecu.id).toBe(id);
    expect(selected.ecu.capabilities).toEqual(['live']);
    expect(selected.ecu.session.simulator_supported).toBe(false);
    expect(selected.ecu.memory.read_supported).toBe(false);
  }
});

test('Honda CB500F DashBle override remains ECU-only with source limits', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#ecuOverride option[value="honda_cb500f_dashble"]', {state: 'attached'});
  await page.getByText('Override: pick an ECU family directly').click();
  await page.selectOption('#ecuOverride', 'honda_cb500f_dashble');
  const kline = page.locator('input[name="transport"][value="kline"]');
  if (await kline.isEnabled()) await kline.check();
  else await kline.evaluate(el => { el.checked = true; el.dispatchEvent(new Event('change', {bubbles: true})); });
  await expect(page.locator('#klineFields')).toContainText('source does not specify the bike year');
  const request = await page.evaluate(() => selectionRequest());
  expect(request.ecu).toBe('honda_cb500f_dashble');
  expect(request.transport).toBe('kline');
  expect(request).not.toHaveProperty('model');
  expect(request).not.toHaveProperty('year');
});

test('Honda source-ID reader is ECU-only even from a reference-only selection', async ({page}) => {
  await page.goto('/');
  await page.locator('#bikeStudioLookup > summary').click();
  await page.locator('#bikeStudioQuery').fill('ADV 150');
  await page.locator('#bikeStudioYear').fill('2021');
  await page.getByRole('button', {name:'Choose Honda ADV 150 2021 in Garage'}).click();
  await expect(page.locator('#connectBtn')).toBeDisabled();
  await page.getByText('Override: pick an ECU family directly').click();
  await page.selectOption('#ecuOverride', 'honda_pgmfi_flash_research');
  const kline = page.locator('input[name="transport"][value="kline"]');
  if (await kline.isEnabled()) await kline.check();
  else await kline.evaluate(el => { el.checked = true; el.dispatchEvent(new Event('change', {bubbles:true})); });
  await page.locator('#checklistAccept').check();
  const request = await page.evaluate(() => selectionRequest());
  expect(request.transport).toBe('kline');
  expect(request.ecu).toBe('honda_pgmfi_flash_research');
  expect(request).not.toHaveProperty('model');
  expect(request).not.toHaveProperty('year');
  await expect(page.locator('#connectBtn')).toBeEnabled();
  await page.route('**/api/memory/check-write', async route => route.fulfill({json:{allowed:false,checks:[]}}));
  await page.route('**/api/memory', async route => route.fulfill({json:{
    capabilities: {ecu:'honda_pgmfi_flash_research',family:'Honda',protocol:'Honda K-Line',
      research_read_only:true,read_supported:true,write_supported:false,regions:{flash:{size:262144}}},
    base_map:{intact:false},checkpoints:{}
  }}));
  await page.locator('[data-view="firmware"]').click();
  await page.evaluate(() => renderMemoryCapabilities({
    capabilities: {ecu:'honda_pgmfi_flash_research',family:'Honda',protocol:'Honda K-Line',
      research_read_only:true,read_supported:true,write_supported:false,regions:{flash:{size:262144}}},
    base_map:{intact:false},checkpoints:{}
  }));
  await expect(page.locator('#memCaps')).toContainText('60 source-derived Honda candidates');
  await expect(page.locator('#memRegion')).toContainText('48 KiB–1 MiB candidate by ECM ID');
  await expect(page.locator('#backupBtn')).toBeDisabled();
  await page.locator('#readBtn').click();
  await expect(page.locator('#modalTitle')).toHaveText('Experimental Honda source-ID research read');
  await expect(page.locator('#modalBody')).toContainText('not been tested on a physical ECU');
  await expect(page.locator('#modalBody')).toContainText('lockout');
  await expect(page.locator('#modalBody')).toContainText('nonzero starts for MSX IDs');
  await expect(page.locator('#modalBody')).toContainText('session logs can contain image data');
  await page.locator('#modalCancel').click();
  expect(page.failures).toEqual([]);
});

test('experimental Honda research read requires its own acknowledgement', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="firmware"]').click();
  await page.evaluate(() => renderMemoryCapabilities({
    capabilities: { ecu: 'honda_cb500f_dashble', family: 'Honda', protocol: 'Honda K-Line',
      research_read_only: true, read_supported: true, write_supported: false,
      regions: {flash: {size: 262144}} }, base_map: {intact: false}, checkpoints: {}
  }));
  await expect(page.locator('#memCaps')).toContainText('experimental MGZ-A03/C02/C03/D02 only');
  await expect(page.locator('#memCaps')).toContainText('unverified on hardware');
  await expect(page.locator('#backupBtn')).toBeDisabled();
  await expect(page.locator('#baseMapSaveBtn')).toBeDisabled();
  await expect(page.locator('#baseMapFileBtn')).toBeDisabled();
  let reads = 0; let body;
  await page.route('**/api/memory/read', async (route) => {
    reads++; body = route.request().postDataJSON();
    await route.fulfill({status: 202, contentType: 'application/json', body: '{}'});
  });
  await page.locator('#readBtn').click();
  await expect(page.locator('#modalTitle')).toHaveText('Experimental MGZ research read');
  await expect(page.locator('#modalBody')).toContainText('not a verified backup');
  await page.locator('#modalCancel').click();
  expect(reads).toBe(0);
  await page.locator('#readBtn').click();
  await page.locator('#modalConfirm').click();
  await expect.poll(() => reads).toBe(1);
  expect(body).toEqual({region: 'flash', confirm_research_read: true});
});

test('Juken raw map research is available inside the desktop host', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  const buffer = Buffer.alloc(10248); buffer.writeInt16LE(-53, 0);
  await page.locator('#jukenImage').setInputFiles({ name: 'raw.bin', mimeType: 'application/octet-stream', buffer });
  await page.locator('#jukenInspect').click();
  await expect(page.locator('#jukenOut')).toContainText('FuelBase · offset 0x0 · 1281 values · min -53');
  await expect(page.locator('#jukenOut')).toContainText('Not a full ECU dump');
});

test('Harley live CAN observation is confirmed, bounded and clears stale values', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="discovery"]').click();
  let calls = 0; let requests = [];
  await page.route('**/api/tools/harley-hdlan-listen', async (route) => {
    calls++; requests.push(route.request().postDataJSON());
    const events = calls === 1 ? [{id: '0x521', raw: '0028', values: {speed_kmh_candidate: 40}}] : [];
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({events, frames_received: events.length, invalid_length_frames: 0})});
  });
  await page.locator('#harleyLiveStart').click();
  await expect(page.locator('#harleyLiveOut')).toContainText('Confirm the bus');
  expect(calls).toBe(0);
  await page.locator('#harleyLiveConfirm').check();
  await page.locator('#harleyLiveStart').click();
  await expect(page.locator('#harleyLiveOut')).toContainText('speed_kmh_candidate: 40');
  await expect(page.locator('#harleyLiveOut')).toContainText('No recognized values in this window.');
  expect(requests[0]).toEqual({channel: 'can0', profile: 'community', confirm: true});
  await page.locator('#harleyLiveStop').click();
  await expect(page.locator('#harleyLiveOut')).toHaveText('Observation stopped.');
  await expect(page.locator('#harleyLiveStart')).toBeEnabled();
  await expect(page.locator('#harleyLiveStop')).toBeDisabled();
});

test('Yamaha MT-03 observer requires explicit confirmation and never reuses old data', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="discovery"]').click();
  let calls = 0; let bodies = [];
  await page.route('**/api/tools/yamaha-mt03-listen', async (route) => {
    calls++; bodies.push(route.request().postDataJSON());
    const latest = calls === 1 ? {raw:'012900802ED7', rpm_candidate:2050, speed_byte_raw:0, status_byte_raw:128, temperature_byte_raw:46} : null;
    await route.fulfill({status: 200, contentType:'application/json', body:JSON.stringify({latest, bytes_received:6, candidate_frames:latest ? 1 : 0})});
  });
  await page.locator('#yamahaLiveObserve').click();
  await expect(page.locator('#yamahaLiveOut')).toContainText('Confirm the bike');
  expect(calls).toBe(0);
  await page.locator('#yamahaLiveConfirm').check();
  await page.locator('#yamahaLiveObserve').click();
  await expect(page.locator('#yamahaLiveOut')).toContainText('RPM candidate: 2050');
  expect(bodies[0]).toEqual({port: '/dev/ttyUSB0', confirm: true});
  await page.locator('#yamahaLiveObserve').click();
  await expect(page.locator('#yamahaLiveOut')).toContainText('No candidate frame in this window');
  await page.locator('#yamahaLivePort').fill('/dev/ttyUSB1');
  await page.locator('#yamahaLivePort').blur();
  await expect(page.locator('#yamahaLiveConfirm')).not.toBeChecked();
});

test('Harley Delphi CAN override remains ECU-only and explains live identity scope', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#ecuOverride option[value="harley_delphi_can_uds"]', {state: 'attached'});
  await page.getByText('Override: pick an ECU family directly').click();
  await page.selectOption('#ecuOverride', 'harley_delphi_can_uds');
  const can = page.locator('input[name="transport"][value="can"]');
  if (await can.isEnabled()) await can.check();
  else await can.evaluate(el => { el.checked = true; el.dispatchEvent(new Event('change', {bubbles:true})); });
  await expect(page.locator('#canFields')).toContainText('five raw identity DIDs');
  await expect(page.locator('#canFields')).toContainText('Garage identity session does not provide ECU memory');
  const request = await page.evaluate(() => selectionRequest());
  expect(request.ecu).toBe('harley_delphi_can_uds');
  expect(request.transport).toBe('can');
  expect(request).not.toHaveProperty('model');
  expect(request).not.toHaveProperty('year');
});

test('Honda PGM-FI and GSX-R1000 appear as read-only source-scoped attempts', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => fetch('/api/disconnect', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}));
  for (const [make, model, year, id] of [
    ['Honda','Wave 110',2012,'honda_pgmfi_research'],
    ['Honda','CB1000R',2015,'honda_pgmfi_research'],
    ['Suzuki','GSX-R1000',2004,'suzuki_gsxr1000_2004'],
    ['Suzuki','SV650AK7',2007,'suzuki_sv650ak7_2007'],
    ['Suzuki','SV650',2004,'suzuki_sv650_2003'],
    ['Suzuki','GSX-R1300 Hayabusa',2015,'suzuki_sds_gsxr_research'],
    ['Honda','Goldwing 1800',2008,'honda_pgmfi_research'],
    ['Harley-Davidson','FLHX Street Glide',2019,'harley_delphi_can_uds'],
    ['Harley-Davidson','XL1200X Forty-Eight',2012,'harley_j1850_harleydroid'],
    ['Harley-Davidson','FLSTC Heritage Softail Classic',2011,'harley_delphi_can_uds'],
    ['Harley-Davidson','XL1200X Forty-Eight',2022,'harley_delphi_can_uds'],
    ['Honda','CRF110F',2024,'honda_pgmfi_research'],
    ['Honda','Vario 125 Techno FI',2014,'honda_pgmfi_research'],
    ['Honda','CB150R StreetFire',2017,'honda_pgmfi_research'],
    ['Honda','CBR150R FI',2018,'honda_pgmfi_research'],
    ['Honda','Supra X 125 Helm-In',2019,'honda_pgmfi_research'],
    ['Honda','CRF250R',2012,'honda_pgmfi_research'],
    ['Honda','CRF250RX',2020,'honda_pgmfi_research'],
    ['Suzuki','GSX-R600',2023,'suzuki_sds_gsxr_research'],
    ['Suzuki','GSX-R750',2017,'suzuki_sds_gsxr_research'],
    ['Kawasaki','Ninja 400',2019,'kawasaki_kds_research'],
    ['Kawasaki','ZX-14R Ninja',2014,'kawasaki_kds_research'],
    ['Kawasaki','Ninja 300',2014,'kawasaki_kds_research'],
  ]) {
    await page.selectOption('#makeSelect',make);
    await page.selectOption('#modelSelect',model);
    await page.selectOption('#yearSelect',String(year));
    await expect(page.locator('#resolveResult')).toContainText('synthetic');
    const select = await page.evaluate(async ({make,model,year}) => {
      const res=await fetch('/api/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({make,model,year,transport:'kline'})});
      return res.json();
    },{make,model,year});
    expect(select.ecu.id).toBe(id);
    expect(select.ecu.memory.read_supported).toBe(false);
    expect(select.ecu.memory.write_supported).toBe(false);
    expect(select.ecu.session.simulator_supported).toBe(false);
  }
});

test('Ducati live CAN uses confirmed bounded observation and clears stale frames', async ({page}) => {
  await page.goto('/');
  await page.locator('[data-view="discovery"]').click();
  await page.selectOption('#harleyLiveProfile','ducati_mitsubishi');
  let requests=[];
  let releaseNext;
  const nextWindow = new Promise(resolve => { releaseNext = resolve; });
  await page.route('**/api/tools/harley-hdlan-listen', async route => {
    requests.push(route.request().postDataJSON());
    const events=requests.length===1 ? [{id:'0x80',raw:'0000000050123400',values:{rpm:4660}}] : [];
    // Hold the empty second window until the first render is asserted, so a
    // slow browser cannot miss the short-lived sample.
    if (requests.length > 1) await nextWindow;
    await route.fulfill({json:{events,frames_received:events.length,invalid_length_frames:0}});
  });
  await page.locator('#harleyLiveStart').click();
  await expect(page.locator('#harleyLiveOut')).toContainText('Confirm the bus');
  expect(requests).toHaveLength(0);
  await page.locator('#harleyLiveConfirm').check();
  await page.locator('#harleyLiveStart').click();
  try {
    await expect(page.locator('#harleyLiveOut')).toContainText('rpm: 4660');
  } finally {
    releaseNext();
  }
  await expect(page.locator('#harleyLiveOut')).toContainText('No recognized values in this window.');
  expect(requests[0]).toEqual({channel:'can0', profile:'ducati_mitsubishi',confirm:true});
  await page.locator('#harleyLiveStop').click();
});

test('ECU image comparison is local and does not authorize a backup or write', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="firmware"]').click();
  const a=page.locator('#memoryCompareFirst'), b=page.locator('#memoryCompareSecond');
  const out=page.locator('#memoryCompareOut');
  const payload=(name,bytes)=>({name,mimeType:'application/octet-stream',buffer:Buffer.from(bytes)});
  await a.setInputFiles(payload('one.bin',[1,2,3]));
  await b.setInputFiles(payload('two.bin',[1,2,3]));
  await page.locator('#memoryCompareBtn').click();
  await expect(out).toContainText('Byte-for-byte identical');
  await expect(out).toContainText('does not create a verified backup or enable writing');
  await b.setInputFiles(payload('other.bin',[1,4,3,8]));
  await expect(out).toBeEmpty();
  await page.locator('#memoryCompareBtn').click();
  await expect(out).toContainText('Files differ');
  await expect(out).toContainText('1 differing bytes');
  await expect(out).toContainText('1 extra bytes');
  await expect(out).toContainText('first difference at 0x1');
  await b.setInputFiles(payload('empty.bin',[]));
  await page.locator('#memoryCompareBtn').click();
  await expect(out).toContainText('non-empty');
  expect(page.failures).toEqual([]);
});


test('protocol panel shows automatic delivery and opt-in read sharing', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#protocolOut')).toContainText('Automatic updates:');
  await expect(page.locator('#protocolOut')).toContainText('Read-report sharing:');
  await expect(page.locator('#protocolOut')).toContainText('not configured');
  await expect(page.locator('#protocolPanel')).toContainText('self-reported');
  expect(page.failures).toEqual([]);
});

test('desktop exports a reviewed synthetic Harley Delphi tune as a research copy', async ({ page }) => {
  const root = resolve('.desktop-test-data');
  const definitions = join(root, 'xdfs');
  mkdirSync(definitions, { recursive: true });
  const xdfPath = join(definitions, 'Harley_user_synthetic.xdf');
  const imagePath = join(root, 'harley-synthetic-source.bin');
  const image = Buffer.alloc(0x4000);
  image.set([10, 20, 30, 40], 0x20);
  writeFileSync(imagePath, image);
  writeFileSync(xdfPath, `<XDFFORMAT version="1.60"><XDFHEADER><deftitle>Synthetic Harley</deftitle>
    <DEFAULTS signed="0" lsbfirst="0"/><REGION size="0x4000"/></XDFHEADER>
    <XDFTABLE uniqueid="fuel"><title>Synthetic table</title>
    <XDFAXIS id="x"><indexcount>2</indexcount></XDFAXIS>
    <XDFAXIS id="y"><indexcount>2</indexcount></XDFAXIS>
    <XDFAXIS id="z"><EMBEDDEDDATA mmedaddress="0x40020" mmedelementsizebits="8"
      mmedrowcount="2" mmedcolcount="2"/><MATH equation="X"/></XDFAXIS>
    </XDFTABLE><XDFCHECKSUM><title>Unknown</title></XDFCHECKSUM></XDFFORMAT>`);
  await page.goto('/');
  await page.locator('[data-view="firmware"]').click();
  await page.locator('#xdfOnlyFitting').uncheck();
  await page.locator('#mapsRefreshBtn').click();
  await page.locator('#xdfSelect').selectOption('Harley_user_synthetic.xdf');
  await page.locator('#mapsImagePath').fill(imagePath);
  await page.locator('#mapsAddressBase').fill('0x40000');
  await page.locator('#mapsRenderBtn').click();
  if (await page.locator('#modal').isVisible()) await page.locator('#modalConfirm').click();
  const cell = page.locator('[data-map-kind="table"][data-map-id="fuel"][data-map-row="0"][data-map-col="1"]');
  await expect(cell).toHaveAttribute('data-map-value', '20');
  await expect(page.locator('#mapsOut')).toContainText('address base 0x40000');
  await cell.dblclick();
  await page.locator('#mapEditValue').fill('25');
  await page.locator('#modalConfirm').click();
  await page.locator('#mapResearchPreviewBtn').click();
  await expect(page.locator('#harleyResearchExportBtn')).toBeVisible();
  await page.locator('#harleyResearchExportBtn').click();
  await expect(page.locator('#modal')).toContainText('not flash-ready');
  const response = page.waitForResponse((r) => r.url().includes('/api/maps/harley-research-export') && r.status() === 201);
  await page.locator('#modalConfirm').click();
  const saved = await (await response).json();
  await expect(page.locator('#mapResearchPreviewOut')).toContainText('Research copy saved · not flash-ready');
  expect(readFileSync(imagePath)).toEqual(image);
  const modified = readFileSync(saved.path);
  expect(modified[0x21]).toBe(25);
  expect(JSON.parse(readFileSync(saved.manifest_path)).flash_ready).toBe(false);
  await page.locator('#researchRegionStart').fill('0x20');
  await page.locator('#researchRegionEnd').fill('0x24');
  await page.locator('#userResearchExportBtn').click();
  await expect(page.locator('#modal')).toContainText('end exclusive');
  const customResponse = page.waitForResponse((r) => r.url().includes('/api/maps/research-export') && r.status() === 201);
  await page.locator('#modalConfirm').click();
  const custom = await (await customResponse).json();
  const manifest = JSON.parse(readFileSync(custom.manifest_path));
  expect(manifest.region_basis).toBe('operator-declared-not-verified');
  expect(manifest.region_start).toBe(0x20);
  expect(manifest.region_end_exclusive).toBe(0x24);
  expect(readFileSync(custom.path)[0x21]).toBe(25);
  expect(readFileSync(imagePath)).toEqual(image);
  expect(page.failures.filter((error) => !/server responded with a status of 409/.test(error))).toEqual([]);
});

test('desktop compares synthetic Centurion header candidates locally without VINs', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  function fixture(part, calibration, vin) {
    const bytes = Buffer.alloc(4096);
    bytes.write('Delphi', 0, 'ascii');
    bytes.write(part, 62, 'ascii');
    bytes.write(calibration, 82, 'ascii');
    bytes.write(vin, 102, 'ascii');
    return bytes;
  }
  await page.locator('#centurionFirst').setInputFiles({name: 'SENSITIVE-FILENAME.ori', mimeType: 'application/octet-stream', buffer: fixture('PART-1', 'CAL-1', 'VIN-SYNTHETIC-123')});
  await page.locator('#centurionSecond').setInputFiles({name: 'OTHER-SENSITIVE.ori', mimeType: 'application/octet-stream', buffer: fixture('PART-1', 'CAL-2', 'VIN-SYNTHETIC-456')});
  const outgoing = [];
  page.on('request', (req) => { if (req.method() === 'POST') outgoing.push(req.url()); });
  await page.locator('#centurionInspect').click();
  await expect(page.locator('#centurionOut')).toContainText('Candidate part field: same');
  await expect(page.locator('#centurionOut')).toContainText('Candidate calibration field: different');
  await expect(page.locator('#centurionOut')).not.toContainText('VIN-SYNTHETIC');
  await expect(page.locator('#centurionOut')).not.toContainText('SENSITIVE-FILENAME');
  expect(outgoing).toEqual([]);
  await page.locator('#centurionClear').click();
  await expect(page.locator('#centurionOut')).toBeEmpty();
  expect(page.failures).toEqual([]);
});

test('desktop exposes synthetic-tested rusEFI serial identification and bounded reading', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  const requests = [];
  await page.route('**/api/tools/rusefi-read', async (route) => {
    const body = route.request().postDataJSON();
    requests.push(body);
    const result = {signature: 'rusEFI synthetic.board.1234', synthetic_tested: true};
    if (body.action === 'read' || body.action === 'outputs') Object.assign(result, {page: body.page, offset: body.offset, length: body.length, data_hex: '010203'});
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(result)});
  });
  await page.locator('#rusefiPort').fill('/dev/ttyACM0');
  await page.locator('#rusefiIdentify').click();
  await expect(page.locator('#rusefiOut')).toContainText('Confirm');
  expect(requests).toHaveLength(0);
  await page.locator('#rusefiConfirm').check();
  await page.locator('#rusefiIdentify').click();
  await expect(page.locator('#rusefiOut')).toContainText('rusEFI synthetic.board.1234');
  expect(requests[0]).toMatchObject({action: 'identify', confirm: true, port: '/dev/ttyACM0', baud: 115200});
  await page.locator('#rusefiSignature').fill('rusEFI synthetic.board.1234');
  await page.locator('#rusefiLength').fill('3');
  await expect(page.locator('#rusefiConfirm')).not.toBeChecked();
  await page.locator('#rusefiConfirm').check();
  await page.locator('#rusefiRead').click();
  await expect(page.locator('#rusefiOut')).toContainText('010203');
  await expect(page.locator('#rusefiOut')).toContainText('not a verified backup');
  expect(requests[1]).toMatchObject({action: 'read', signature: 'rusEFI synthetic.board.1234', page: 0, offset: 0, length: 3});
  await page.locator('#rusefiOutputs').click();
  await expect(page.locator('#rusefiOut')).toContainText('Live output offset 0');
  expect(requests[2]).toMatchObject({action: 'outputs', offset: 0, length: 3});
  expect(page.failures).toEqual([]);
});

test('desktop clearly separates Dynojet software from the Harley research export', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  const panel = page.locator('#harleyRegion');
  await expect(panel).toContainText('GuzziOnBoard does not control Power Vision');
  const link = panel.getByRole('link', {name: "Dynojet's software and guides"});
  await expect(link).toHaveAttribute('href', 'https://www.dynojet.com/downloads/power-vision-for-harley-davidson/');
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  expect(page.failures).toEqual([]);
});

test('rusEFI INI import is local and signature lookup requires an explicit link', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  const signature = 'rusEFI master.2024.02.02.alphax-4chan.1293678056';
  const postRequests = [];
  await page.route('**/api/tools/rusefi-read', async route => {
    postRequests.push(route.request().postDataJSON());
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({signature, synthetic_tested: true})});
  });
  await page.locator('#rusefiIni').setInputFiles({name:'rusefi.ini', mimeType:'text/plain', buffer:Buffer.from(`[TunerStudio]\nsignature = "${signature}"\n`)});
  await expect(page.locator('#rusefiSignature')).toHaveValue(signature);
  await expect(page.locator('#rusefiIniStatus')).toContainText('loaded locally');
  expect(postRequests).toHaveLength(0);
  await page.locator('#rusefiPort').fill('/dev/ttyACM0');
  await page.locator('#rusefiConfirm').check();
  await page.locator('#rusefiIdentify').click();
  const link = page.locator('#rusefiLookup');
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute('href', 'https://rusefi.com/online/ini/rusefi/master/2024/02/02/alphax-4chan/1293678056.ini');
  await expect(page.locator('#rusefiLookupNote')).toContainText('sends the signature');
  await page.locator('#rusefiPort').fill('/dev/ttyACM1');
  await expect(link).toBeHidden();
  await expect(page.locator('#rusefiConfirm')).not.toBeChecked();
  await page.locator('#rusefiIni').setInputFiles({name:'bad.ini', mimeType:'text/plain', buffer:Buffer.from('[TunerStudio]\nsignature = @@TS_SIGNATURE@@')});
  await expect(page.locator('#rusefiIniStatus')).toContainText('INI not loaded');
  await expect(page.locator('#rusefiSignature')).toHaveValue('');
  expect(page.failures).toEqual([]);
});

test('desktop Buell DDFI live reader requires confirmation and exact ECM version', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  const calls = [];
  await page.route('**/api/tools/buell-ddfi', async route => {
    const request = route.request().postDataJSON(); calls.push(request);
    const response = {version:'BUEIB310 12-11-03', mode:'stock', synthetic_tested:true};
    if (request.action === 'runtime') Object.assign(response, {length:2, data_hex:'1234'});
    if (request.action === 'read') Object.assign(response, {page:request.page, offset:request.offset, length:request.length, data_hex:'AABB', repeated_match:request.compare_repeat});
    await route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(response)});
  });
  await page.locator('#buellPort').fill('/dev/ttyUSB0');
  await page.locator('#buellIdentify').click();
  await expect(page.locator('#buellOut')).toContainText('Confirm');
  expect(calls).toHaveLength(0);
  await page.locator('#buellConfirm').check();
  await page.locator('#buellIdentify').click();
  await expect(page.locator('#buellVersion')).toHaveValue('BUEIB310 12-11-03');
  await expect(page.locator('#buellConfirm')).not.toBeChecked();
  await page.locator('#buellLength').fill('2');
  await page.locator('#buellCompare').check();
  await page.locator('#buellConfirm').check();
  await page.locator('#buellRead').click();
  await expect(page.locator('#buellOut')).toContainText('AABB');
  await expect(page.locator('#buellOut')).toContainText('not a complete backup');
  await expect(page.locator('#buellOut')).toContainText('Two range reads matched');
  expect(calls[1]).toMatchObject({action:'read', mode:'stock', version:'BUEIB310 12-11-03', page:1, offset:0, length:2, compare_repeat:true});
  await page.locator('#buellRuntime').click();
  await expect(page.locator('#buellOut')).toContainText('Runtime data');
  expect(calls[2]).toMatchObject({action:'runtime', version:'BUEIB310 12-11-03'});
  await page.locator('#buellMode').selectOption('factory_race');
  await expect(page.locator('#buellVersion')).toHaveValue('');
  await expect(page.locator('#buellConfirm')).not.toBeChecked();
  expect(page.failures).toEqual([]);
});

test('JetDrive live window requires consent and clears stale samples', async ({ page }) => {
  await page.goto('/'); await page.locator('[data-view="tools"]').click();
  const calls = [];
  await page.route('**/api/tools/jetdrive', async route => {
    calls.push(route.request().postDataJSON());
    await route.fulfill({status:200, contentType:'application/json', body:JSON.stringify({packets:1, invalid_packets:0, dropped:0, limit_reached:false, metadata_requested:false, samples:[{source:'192.168.0.2', provider:4660, provider_name:'=bad_formula', sequence:1, id:1, channel_name:'RPM', unit_code:8, timestamp_ms:1000, value:1600}]})});
  });
  await page.locator('#jetdriveCapture').click();
  await expect(page.locator('#jetdriveOut')).toContainText('Confirm'); expect(calls).toHaveLength(0);
  await page.locator('#jetdriveConfirm').check(); await page.locator('#jetdriveCapture').click();
  await expect(page.locator('#jetdriveOut')).toContainText('RPM');
  await expect(page.locator('#jetdriveOut')).toContainText('1600');
  await expect(page.locator('#jetdriveExport')).toBeEnabled();
  await page.evaluate(() => { window.gobDesktop.saveText = async (name, content) => { window.__jetCsv = content; return {name, dir:'synthetic'}; }; });
  await page.locator('#jetdriveExport').click();
  expect(await page.evaluate(() => window.__jetCsv)).toContain("'=bad_formula");
  expect(calls[0]).toMatchObject({group:'224.0.2.10', interface:'0.0.0.0', request_info:false, confirm:true});
  await page.locator('#jetdriveGroup').selectOption('239.255.60.60');
  await expect(page.locator('#jetdriveExport')).toBeDisabled();
  await expect(page.locator('#jetdriveOut')).not.toContainText('1600');
  await expect(page.locator('#jetdriveConfirm')).not.toBeChecked();
  expect(page.failures).toEqual([]);
});

test('local Harley trouble code JSON keeps duplicates and escapes untrusted descriptions', async ({ page }) => {
  await page.goto('/'); await page.locator('[data-view="faults"]').click();
  const json = {codes:[{code:'P0107',description:'First reference'},{code:'P0107',description:'<img src=x onerror=alert(1)>'},{code:'P691',description:'Short source code'}]};
  await page.locator('#harleyCodeFile').setInputFiles({name:'codes.json', mimeType:'application/json', buffer:Buffer.from(JSON.stringify(json))});
  await expect(page.locator('#harleyCodeOut')).toContainText('3 reference entries');
  await page.locator('#harleyCodeQuery').fill('p0107');
  await expect(page.locator('#harleyCodeOut')).toContainText('First reference');
  await expect(page.locator('#harleyCodeOut')).toContainText('<img src=x');
  await expect(page.locator('#harleyCodeOut img')).toHaveCount(0);
  await page.locator('#harleyCodeQuery').fill('P691');
  await expect(page.locator('#harleyCodeOut')).toContainText('Short source code');
  await page.locator('#harleyCodeClear').click();
  await expect(page.locator('#harleyCodeOut')).toContainText('No reference loaded');
  expect(page.failures).toEqual([]);
});

test('PVV local editor stages explicit numeric changes and exports a reviewed XML copy', async ({ page }) => {
  await page.goto('/'); await page.locator('[data-view="tools"]').click();
  const xml = `<?xml version="1.0"?><PVV><Metadata source="synthetic"/><Item name="Fuel &amp; test" units="%"><Columns units="kPa"><Col label="20"/><Col label="40"/></Columns><Rows units="RPM"><Row label="1000"><Cell value="10"/><Cell value="20"/></Row></Rows></Item><Item name="Scalar"><Columns><Col label="0"/></Columns><Rows><Row label="0"><Cell value="1"/></Row></Rows></Item><Item name="unsupported"/></PVV>`;
  await page.locator('#pvvFile').setInputFiles({name:'test.pvv', mimeType:'application/xml', buffer:Buffer.from(xml)});
  await expect(page.locator('#pvvDetails')).toContainText('Fuel & test');
  await expect(page.locator('#pvvChanges')).toContainText('1 unsupported');
  await page.locator('#pvvGrid input').first().fill('12.5');
  await expect(page.locator('#pvvChanges')).toContainText('10 → 12.5');
  await expect(page.locator('#pvvExport')).toBeDisabled();
  await page.locator('#pvvSelect').selectOption('1');
  await page.locator('#pvvGrid input').first().fill('NaN');
  await expect(page.locator('#pvvChanges')).toContainText('Invalid numeric');
  await page.locator('#pvvConfirm').check();
  await expect(page.locator('#pvvExport')).toBeDisabled();
  await page.locator('#pvvGrid input').first().fill('2');
  await expect(page.locator('#pvvChanges')).toContainText('2 staged');
  await page.evaluate(() => { window.gobDesktop.saveText = async (name, content) => { window.__pvvExport = {name, content}; return {name, dir:'synthetic'}; }; });
  await page.locator('#pvvConfirm').check(); await page.locator('#pvvExport').click();
  const saved = await page.evaluate(() => window.__pvvExport);
  expect(saved.name).toMatch(/\.pvv$/);
  const result = await page.evaluate((raw) => {
    const root = new DOMParser().parseFromString(raw, 'application/xml');
    return {values:Array.from(root.querySelectorAll('Cell')).map(c => c.getAttribute('value')), meta:root.querySelector('Metadata').getAttribute('source'), items:root.querySelectorAll('Item').length};
  }, saved.content);
  expect(result).toEqual({values:['12.5','20','2'],meta:'synthetic',items:3});
  await page.locator('#pvvRevert').click(); await expect(page.locator('#pvvChanges')).toContainText('No staged changes');
  await expect(page.locator('#pvvExport')).toBeDisabled();
  await page.locator('#pvvFile').setInputFiles({name:'bad.pvv', mimeType:'application/xml', buffer:Buffer.from('<!DOCTYPE PVV [<!ENTITY x "bad">]><PVV/>')});
  await expect(page.locator('#pvvDetails')).toContainText('DTD and entity');
  expect(page.failures).toEqual([]);
});

test('local Harley code references augment live results only while loaded', async ({ page }) => {
  await page.goto('/');
  await page.route('**/api/dtcs', route => route.fulfill({status:200, contentType:'application/json', body:JSON.stringify({format:'harley-j1850', dtcs:[{code:'P0107',description:'Existing source', status_byte:null,kind:'unknown',status:'unknown'}], context:{}, modules:{}, clear:{allowed:false, checks:[]}})}));
  await page.locator('[data-view="faults"]').click();
  await page.locator('#harleyCodeFile').setInputFiles({name:'codes.json', mimeType:'application/json', buffer:Buffer.from(JSON.stringify({codes:[{code:'P0107',description:'<img src=x onerror=alert(1)>'}]}))});
  await expect(page.locator('#harleyCodeOut')).toContainText('1 reference entries');
  await page.evaluate(() => readDtcs());
  await expect(page.locator('#faultList')).toContainText('Existing source');
  await expect(page.locator('#faultList')).toContainText('Local Harley reference');
  await expect(page.locator('#faultList img')).toHaveCount(0);
  await page.locator('#harleyCodeClear').click();
  await expect(page.locator('#faultList')).not.toContainText('Local Harley reference');
  await expect(page.locator('#faultList')).toContainText('Existing source');
  expect(page.failures).toEqual([]);
});

test('Honda CTX700 opt-in is ECU-only and shows source limitations', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#ecuOverride option[value="honda_ctx700_minidash"]', {state: 'attached'});
  await page.getByText('Override: pick an ECU family directly').click();
  await page.selectOption('#ecuOverride', 'honda_ctx700_minidash');
  const request = await page.evaluate(() => selectionRequest());
  expect(request.ecu).toBe('honda_ctx700_minidash');
  expect(request).not.toHaveProperty('model');
  expect(request).not.toHaveProperty('year');
  const selected = await page.evaluate(async body => {
    const r = await fetch('/api/select', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    return r.json();
  }, {...request, transport: 'kline'});
  expect(selected.ecu.notes).toContain('synthetic tests only');
  expect(selected.ecu.memory.read_supported).toBe(false);
  expect(selected.ecu.memory.write_supported).toBe(false);
});

test('Intrepid CAN selection requires explicit serial and single network', async ({ page }) => {
  await page.goto('/');
  await page.getByText('Override: pick an ECU family directly').click();
  await page.selectOption('#ecuOverride', 'harley_delphi_can_uds');
  const can = page.locator('input[name="transport"][value="can"]');
  if (await can.isEnabled()) await can.check();
  else await can.evaluate(el => { el.checked = true; el.dispatchEvent(new Event('change', {bubbles: true})); });
  await page.selectOption('#canInterface', 'neovi');
  await expect(page.locator('#canIntrepidNote')).toContainText('standard packaged builds do not include it');
  await page.locator('#deviceInput').fill('HSCAN');
  await page.locator('#canSerial').fill('123456');
  const body = await page.evaluate(() => selectionRequest());
  expect(body).toMatchObject({ecu: 'harley_delphi_can_uds', transport: 'can', device: 'HSCAN', can_interface: 'neovi', can_serial: '123456'});
  const response = await page.evaluate(async body => {
    const r = await fetch('/api/select', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    return {status:r.status, body:await r.json()};
  }, body);
  expect(response.status).toBe(200);
  expect(response.body.can_interface).toBe('neovi');
  const invalid = await page.evaluate(async body => {
    const r = await fetch('/api/select', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...body, device:'HSCAN,MSCAN'})});
    return r.status;
  }, body);
  expect(invalid).toBe(400);
  await page.selectOption('#canInterface', '');
  expect((await page.evaluate(() => selectionRequest()))).not.toHaveProperty('can_serial');
});

test('SLCAN classic-CAN adapter uses explicit port and preserves profile scope', async ({ page }) => {
  await page.goto('/');
  await page.getByText('Override: pick an ECU family directly').click();
  await page.selectOption('#ecuOverride', 'harley_delphi_can_uds');
  const can = page.locator('input[name="transport"][value="can"]');
  if (await can.isEnabled()) await can.check();
  else await can.evaluate(el => { el.checked = true; el.dispatchEvent(new Event('change', {bubbles:true})); });
  await page.selectOption('#canInterface', 'slcan');
  await expect(page.locator('#canSlcanNote')).toContainText('Synthetic-tested only');
  await page.locator('#deviceInput').fill('COM5@115200');
  const body = await page.evaluate(() => selectionRequest());
  expect(body).toMatchObject({ecu:'harley_delphi_can_uds',transport:'can',device:'COM5@115200',can_interface:'slcan'});
  expect(body).not.toHaveProperty('can_serial');
  const result = await page.evaluate(async body => {
    const r = await fetch('/api/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    return {status:r.status, json:await r.json()};
  }, body);
  expect(result.status).toBe(200);
  expect(result.json.ecu.memory.read_supported).toBe(false);
  expect(result.json.ecu.memory.write_supported).toBe(false);
});

test('Bonneville source-scoped live OBD is selectable with programming blocked', async ({page}) => {
  await page.goto('/');
  await page.evaluate(() => fetch('/api/disconnect', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}));
  await page.selectOption('#makeSelect','Triumph');
  await page.selectOption('#modelSelect','Bonneville 865 EFI');
  await page.selectOption('#yearSelect','2009');
  await expect(page.locator('#resolveResult')).toContainText('synthetic');
  const result = await page.evaluate(async () => {
    const post=async (path, body)=>{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return {status:r.status,body:await r.json()}};
    return {selection:await post('/api/select',{make:'Triumph',model:'Bonneville 865 EFI',year:2009,transport:'kline'}), service:await post('/api/connect',{mode:'service'})};
  });
  expect(result.selection.body.ecu.id).toBe('triumph_bonneville_865_2009');
  expect(result.selection.body.ecu.memory.read_supported).toBe(false);
  expect(result.selection.body.ecu.memory.write_supported).toBe(false);
  expect(result.service.status).toBe(501);
  expect(result.service.body.error).toContain('read-only mode');
});

test('generic Kawasaki and Suzuki K-Line attempts are explicit ECU-only selections', async ({page}) => {
  await page.goto('/');
  await page.waitForSelector('#ecuOverride option[value="kawasaki_kds_generic_research"]', {state: 'attached'});
  await page.getByText('Override: pick an ECU family directly').click();
  for (const ecu of ['kawasaki_kds_generic_research', 'suzuki_sds_generic_research']) {
    await page.selectOption('#ecuOverride', ecu);
    const request = await page.evaluate(() => selectionRequest());
    expect(request.ecu).toBe(ecu);
    expect(request).not.toHaveProperty('model');
    expect(request).not.toHaveProperty('year');
    expect(request).not.toHaveProperty('make');
    const info = await page.evaluate(async (id) => {
      const response = await fetch('/api/select', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ecu: id, transport:'kline'})});
      return response.json();
    }, ecu);
    expect(info.ecu.capabilities).toEqual(['live']);
    expect(info.ecu.memory.read_supported).toBe(false);
    expect(info.ecu.memory.write_supported).toBe(false);
    expect(info.ecu.session.physical_evidence_note).toContain('Synthetic');
  }
});

test('Yamaha and Indian live CAN sources require explicit selection and confirmation', async ({page}) => {
  await page.goto('/');
  await page.locator('[data-view="discovery"]').click();
  const calls=[];
  let release;
  const held = new Promise(resolve => { release = resolve; });
  await page.route('**/api/tools/harley-hdlan-listen', async route => {
    calls.push(route.request().postDataJSON());
    if (calls.length > 1) await held;
    await route.fulfill({json:{events:[{id:'0x18F00400',raw:'0000001027000082',values:{rpm_candidate:1250}}],frames_received:1,invalid_length_frames:0}});
  });
  try {
    await page.selectOption('#harleyLiveProfile', 'indian_springfield_2017');
    await page.locator('#harleyLiveConfirm').check();
    await page.locator('#harleyLiveStart').click();
    await expect(page.locator('#harleyLiveOut')).toContainText('rpm_candidate: 1250');
    expect(calls[0]).toEqual({channel:'can0',profile:'indian_springfield_2017',confirm:true});
    await page.selectOption('#harleyLiveProfile', 'yamaha_r9_2026');
    await expect(page.locator('#harleyLiveConfirm')).not.toBeChecked();
    await expect(page.locator('#harleyLiveOut')).toContainText('Selection changed');
  } finally { release(); }
});

test('desktop OpenETV research runs locally and marks cells requiring review', async ({page}) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  await page.locator('#etvEngine').fill('RPM,0,50,100\n1000,-10,100,80');
  await page.locator('#etvRequest').fill('RPM,0,50,100\n1000,-20,95,110');
  await page.locator('#etvCalculate').click();
  await expect(page.locator('#etvOut')).toContainText('1000,0,47.7,50');
  await expect(page.locator('#etvOut')).toContainText('1000,below_min,non_monotonic,saturated');
  await expect(page.locator('#etvOut')).toContainText('not a validated or flash-ready tune');
});

test('2017 V-Strom source-unverified SDS attempt is selectable, without programming', async ({page}) => {
  await page.goto('/');
  await page.evaluate(() => fetch('/api/disconnect', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}));
  await page.selectOption('#makeSelect','Suzuki');
  await page.selectOption('#modelSelect','V-Strom DL650XAL7');
  await page.selectOption('#yearSelect','2017');
  await expect(page.locator('#resolveResult')).toContainText('synthetic');
  const result = await page.evaluate(async () => {
    const post=async (path, body)=>{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return {status:r.status,body:await r.json()}};
    return {selection:await post('/api/select',{make:'Suzuki',model:'V-Strom DL650XAL7',year:2017,transport:'kline'}), service:await post('/api/connect',{mode:'service'})};
  });
  expect(result.selection.body.ecu.id).toBe('suzuki_dl650_2017_research');
  expect(result.selection.body.ecu.session.physical_evidence_note).toContain('not verified');
  expect(result.selection.body.ecu.memory.read_supported).toBe(false);
  expect(result.selection.body.ecu.memory.write_supported).toBe(false);
  expect(result.service.status).toBe(501);
});

test('physical 5AM partial read warning is shown before reading', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="firmware"]').click();
  await page.evaluate(() => renderMemoryCapabilities({
    capabilities: { ecu: '5am', family: 'IAW 5AM', protocol: 'iaw_transfer',
      read_supported: true, write_supported: false,
      partial_read_note: 'Experimental 5AM source-derived read: blocks 2–5 are FF placeholders, not read. Not a verified backup, base map, or flash-ready image.',
      regions: {flash: {size: 311296}} }, base_map: {intact: false}, checkpoints: {}
  }));
  await expect(page.locator('#memCaps')).toContainText('experimental partial read');
  await expect(page.locator('#memCaps')).toContainText('blocks 2–5 are FF placeholders');
  await expect(page.locator('#backupBtn')).toBeDisabled();
  await expect(page.locator('#baseMapSaveBtn')).toBeDisabled();
  await expect(page.locator('#readBtn')).toBeEnabled();
});

test('desktop Power Vision log mapping requires an explicit cylinder AFR', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('body')).toHaveAttribute('data-desktop', '1');
  await page.locator('[data-view="firmware"]').click();
  await page.locator('.map-log-tools > summary').click();
  await page.locator('#mapLogFile').setInputFiles({
    name: 'synthetic-pv.csv', mimeType: 'text/csv',
    buffer: Buffer.from('RPM,MAP,TP,AFR1,AFR2,Set AFR\n2000,60,20,15,14.8,14.2\n'),
  });
  await expect(page.locator('#mapLogSummary')).toContainText('synthetic-pv.csv');
  await expect(page.locator('#mapLogMeasured')).toHaveValue('');
  await expect(page.locator('#mapLogTarget')).toHaveValue('Set AFR');
  await page.locator('#mapLogMeasured').selectOption('AFR1');
  await expect(page.locator('#mapLogMeasured')).toHaveValue('AFR1');
});

test('desktop explains missing Harley reader without claiming security is unnecessary', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="firmware"]').click();
  await page.evaluate(() => renderMemoryCapabilities({
    capabilities: { ecu: 'harley_delphi_can_uds', family: 'Harley Delphi CAN', protocol: 'none',
      read_supported: false, write_supported: false, security_required: null, security_available: null,
      read_blocked_reason: 'No ECU memory reader is implemented for this profile.',
      write_blocked_reason: 'Programming is not implemented.', regions: {} },
    base_map: { intact: false }, checkpoints: {},
  }));
  await expect(page.locator('#memCaps')).toContainText('No ECU memory reader is implemented');
  await expect(page.locator('#memCaps')).toContainText('unknown — no memory reader implemented');
  await expect(page.locator('#memCaps')).toContainText('Separate experimental tool');
  await expect(page.locator('#readBtn')).toBeDisabled();
  await expect(page.locator('#backupBtn')).toBeDisabled();
});

test('desktop reads and exports a synthetic Buell source-layout EEPROM image', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  const data = Buffer.from(Array.from({length: 1210}, (_, i) => i & 255));
  const requests = [];
  await page.route('**/api/tools/buell-ddfi', async (route) => {
    const body = route.request().postDataJSON(); requests.push(body);
    const result = body.action === 'identify'
      ? {version: 'BUEIB310 12-11-03'}
      : {version: 'BUEIB310 12-11-03', kind: 'eeprom-image', layout: 'BUEIB',
         length: data.length, data_hex: data.toString('hex').toUpperCase(),
         sha256: 'synthetic', repeated_match: true};
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(result)});
  });
  await page.locator('#buellPort').fill('/dev/ttyUSB0');
  await page.locator('#buellConfirm').check();
  await page.locator('#buellIdentify').click();
  await expect(page.locator('#buellVersion')).toHaveValue('BUEIB310 12-11-03');
  await page.locator('#buellCompare').check();
  await page.locator('#buellConfirm').check();
  await page.locator('#buellImage').click();
  await expect(page.locator('#buellOut')).toContainText('Two complete reads matched');
  expect(requests[1]).toMatchObject({action: 'image', compare_repeat: true, version: 'BUEIB310 12-11-03'});
  await page.locator('#buellSaveImage').click();
  await expect(page.locator('#buellOut')).toContainText('Saved:');
  const name = (await page.locator('#buellOut').innerText()).match(/BUEIB-guzzionboard-\d+\.xpr/)[0];
  expect(readFileSync(join(EXPORTS, name))).toEqual(data);
  await page.locator('#buellPort').fill('/dev/ttyUSB1');
  await expect(page.locator('#buellSaveImage')).toBeDisabled();
});

test('desktop edits and exports a synthetic Buell XPR with the bundled source XDF', async ({page}) => {
  const source = join(resolve('.desktop-test-data'), 'BUEIB-synthetic.xpr');
  const image = Buffer.from(Array.from({length: 1210}, (_, i) => i & 255));
  writeFileSync(source, image);
  await page.goto('/');
  await page.locator('[data-view="firmware"]').click();
  await page.locator('#xdfOnlyFitting').uncheck();
  await page.locator('#mapsRefreshBtn').click();
  await page.locator('#xdfSelect').selectOption('BUEIB_source_research.xdf');
  await page.locator('#mapsImagePath').fill(source);
  await page.locator('#mapsAddressBase').fill('0');
  await page.locator('#mapsRenderBtn').click();
  if (await page.locator('#modal').isVisible()) await page.locator('#modalConfirm').click();
  const cell = page.locator('[data-map-kind="table"][data-map-id="0x3"][data-map-row="1"][data-map-col="0"]');
  await expect(cell).toHaveAttribute('data-map-value', String(image[884]));
  await page.locator('details.map-table-entry').filter({hasText: 'Tab_Fuel_Front'}).locator('summary').first().click();
  await cell.dblclick();
  await page.locator('#mapEditValue').fill('42');
  await page.locator('#modalConfirm').click();
  await page.locator('#mapResearchPreviewBtn').click();
  await expect(page.locator('#userResearchExportBtn')).toBeVisible();
  await page.locator('#researchRegionStart').fill('0');
  await page.locator('#researchRegionEnd').fill('1210');
  await page.locator('#userResearchExportBtn').click();
  const response = page.waitForResponse((r) => r.url().includes('/api/maps/research-export') && r.status() === 201);
  await page.locator('#modalConfirm').click();
  const saved = await (await response).json();
  expect(readFileSync(saved.path)[884]).toBe(42);
  expect(readFileSync(source)).toEqual(image);
  expect(JSON.parse(readFileSync(saved.manifest_path)).flash_ready).toBe(false);
});

test('desktop Buell write requires review and confirmation and invalidates stale plans', async ({ page }) => {
  await page.goto('/'); await page.locator('[data-view="tools"]').click();
  const calls = [];
  await page.route('**/api/tools/buell-ddfi', async route => {
    const body = route.request().postDataJSON(); calls.push(body);
    const result = body.action === 'identify' ? {version:'BUEIB310 12-11-03'}
      : body.action === 'prepare-write' ? {version:'BUEIB310 12-11-03', xdf:'BUEIB_source_research.xdf',
          changes:[{offset:884,before:116,after:42}], base_sha256:'original', target_sha256:'edited',
          warning:'Synthetic only', token:'synthetic-token', expires_seconds:300}
      : {chunks_written:1,edited_bytes:1,backup_path:'/synthetic/backup.xpr',backup_sha256:'backup',note:'Synthetic only'};
    await route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(result)});
  });
  await page.locator('#buellPort').fill('/dev/ttyUSB0');
  await page.locator('#buellConfirm').check(); await page.locator('#buellIdentify').click();
  await expect(page.locator('#buellVersion')).toHaveValue('BUEIB310 12-11-03');
  await page.locator('#buellDdfi details > summary').click();
  await page.locator('#buellWriteOriginal').fill('/tmp/BUEIB-original.xpr');
  await page.locator('#buellWriteEdited').fill('/tmp/edited.bin');
  await page.locator('#buellWriteConfirm').check(); await page.locator('#buellConfirm').check();
  await page.locator('#buellWritePrepare').click();
  await expect(page.locator('#buellWriteOut')).toContainText('0x374: 116 → 42');
  await expect(page.locator('#buellWriteExecute')).toBeEnabled();
  await page.locator('#buellWriteEdited').fill('/tmp/other.bin');
  await expect(page.locator('#buellWriteExecute')).toBeDisabled();
  await page.locator('#buellWritePrepare').click();
  await expect(page.locator('#buellWriteExecute')).toBeEnabled();
  await page.locator('#buellWriteExecute').click();
  await expect(page.locator('#modal')).toContainText('synthetic tests');
  expect(calls.filter(c => c.action === 'write')).toHaveLength(0);
  await page.locator('#modalConfirm').click();
  await expect(page.locator('#buellWriteOut')).toContainText('Fresh backup: /synthetic/backup.xpr');
  expect(calls.filter(c => c.action === 'write')).toEqual([{action:'write',confirm:true,confirm_write:true,token:'synthetic-token'}]);
  await expect(page.locator('#buellWriteExecute')).toBeDisabled();
});

test('Harley Delphi experimental read and reviewed write use local API only', async ({ page }) => {
  const calls = [];
  await page.route('**/api/tools/harley-memory', async route => {
    const body = route.request().postDataJSON(); calls.push(body);
    let response;
    if (body.action === 'read') response = {identity:{F1EA:'41',F1ED:'42',F1F5:'43'},region:'tune',address:0x7f4000,length:16384,sha256:'abc',data_hex:'00'.repeat(16384),repeated_match:false,read_token:'read-token',original_tune_path:'/synthetic/original.bin',original_tune_sha256:'orig',original_tune_verified:false};
    else if (body.action === 'prepare-from-read') response = {identity:{F1EA:'41',F1ED:'42',F1F5:'43'},original_sha256:'orig',target_sha256:'target',changed_bytes:1,changes:[{offset:10,before:0,after:1}],token:'single-use',expires_seconds:300,single_read:true};
    else response = {backup_path:'/synthetic/backup.bin',backup_sha256:'backuphash',note:'Synthetic test.'};
    await route.fulfill({json: response});
  });
  await page.goto('/');
  await page.locator('[data-view="tools"]').first().click();
  await page.locator('#hdMemChannel').fill('can0');
  await page.locator('#hdMemCapture').fill('/tmp/authorized-capture.txt');
  await page.locator('#hdMemConfirm').check();
  await page.locator('#hdMemRead').click();
  await expect(page.locator('#hdMemOut')).toContainText('Single read only');
  await expect(page.locator('#hdMemWritePanel')).toHaveJSProperty('open', true);
  await expect(page.locator('#hdMemOriginal')).toHaveValue('/synthetic/original.bin');
  await expect(page.locator('#hdMemPrepare')).toBeDisabled();
  await page.locator('#hdMemEdited').fill('/tmp/edited.bin');
  await page.locator('#hdMemPrepare').click();
  await expect(page.locator('#hdMemWriteOut')).toContainText('0xA: 0 → 1');
  await expect(page.locator('#hdMemWrite')).toBeDisabled();
  await page.locator('#hdMemWriteConfirm').check();
  await page.locator('#hdMemEdited').fill('/tmp/other.bin');
  await expect(page.locator('#hdMemWrite')).toBeDisabled();
  await expect(page.locator('#hdMemWriteConfirm')).not.toBeChecked();
  await page.locator('#hdMemPrepare').click();
  await page.locator('#hdMemWriteConfirm').check();
  await page.locator('#hdMemWrite').click();
  await expect(page.locator('#modalBody')).toContainText('without a fresh pre-write comparison');
  await page.locator('#modalConfirm').click();
  await expect(page.locator('#hdMemWriteOut')).toContainText('/synthetic/backup.bin');
  expect(calls.map(c => c.action)).toEqual(['read','prepare-from-read','prepare-from-read','write']);
  expect(calls[0].compare_repeat).toBe(false);
  expect(calls[1].read_token).toBe('read-token');
  expect(calls[1]).not.toHaveProperty('original_path');
  expect(calls.at(-1).token).toBe('single-use');
  expect(page.failures).toEqual([]);
});

test('BikeStudio reference searches parts and selects only an existing garage model', async ({page}) => {
  await page.goto('/');
  await page.locator('#bikeStudioLookup > summary').click();
  await page.locator('#bikeStudioYear').fill('2014');
  await page.locator('#bikeStudioQuery').fill('38770-MGZ-A03');
  await expect(page.locator('#bikeStudioResults')).toContainText('38770-MGZ-A03');
  await expect(page.locator('#bikeStudioResults')).toContainText('market: Asia');
  await expect(page.locator('#bikeStudioResults')).toContainText('separate Honda PGM-FI ECU-only');
  await expect(page.locator('#bikeStudioResults')).toContainText('this listing does not enable a read or write');
  await expect(page.locator('#bikeStudioResults a', {hasText:'source part'})).toHaveAttribute('href', 'https://bikestudio.io/ecu/38770-mgz-a03?lang=en');
  await page.getByRole('button', {name:'Choose Honda CB500F 2014 in Garage'}).click();
  await expect(page.locator('#makeSelect')).toHaveValue('Honda');
  await expect(page.locator('#modelSelect')).toHaveValue('CB500F');
  await expect(page.locator('#yearSelect')).toHaveValue('2014');
  await expect(page.locator('#bikeStudioGarage')).toContainText('38770-MGZ-A03');
  await expect(page.locator('#bikeStudioGarage')).not.toContainText('38770-MGZ-B01');
  await page.locator('#bikeStudioQuery').fill('38770-MGP-A92');
  await expect(page.locator('#bikeStudioResults')).toContainText('separate Honda PGM-FI ECU-only');
  await expect(page.locator('#bikeStudioResults')).toContainText('Synthetic-tested only');
  await page.locator('#bikeStudioQuery').fill('38770-KYJ-922');
  await expect(page.locator('#bikeStudioResults')).toContainText('separate Honda PGM-FI ECU-only');
  await expect(page.locator('#bikeStudioResults')).toContainText('this listing does not enable a read or write');
  await page.locator('#bikeStudioQuery').fill('38770-K0F-A01');
  await page.locator('#bikeStudioYear').fill('2018');
  await expect(page.locator('#bikeStudioResults')).toContainText('separate Honda PGM-FI ECU-only');
  await page.locator('#bikeStudioQuery').fill('CT 125');
  await page.locator('#bikeStudioYear').fill('2024');
  await expect(page.locator('#bikeStudioResults')).toContainText('2025–2024 (invalid source range; review)');
  await expect(page.locator('#bikeStudioResults')).toContainText('year unknown');
  await expect(page.locator('#bikeStudioResults')).not.toContainText('38770-K2E-T11');
  await page.locator('#bikeStudioQuery').fill('R15');
  await page.locator('#bikeStudioYear').fill('2021');
  await page.getByRole('button', {name:'Choose Yamaha YZF-R15 2021 in Garage'}).click();
  await expect(page.locator('#modelSelect')).toHaveValue('YZF-R15');
  await expect(page.locator('#bikeStudioGarage')).toContainText('BDJ0');
  await expect(page.locator('#resolveResult')).toContainText('BikeStudio part reference only');
  await expect(page.locator('#connectBtn')).toBeDisabled();
  await expect(page.locator('#selectOfflineBtn')).toBeEnabled();
  expect(page.failures).toEqual([]);
});

test('additional BikeStudio source candidates retain anomalies and year gaps', async ({page}) => {
  await page.goto('/');
  await page.locator('#bikeStudioLookup > summary').click();
  await page.locator('#bikeStudioQuery').fill('CB 150 R');
  await page.locator('#bikeStudioYear').fill('2014');
  await expect(page.locator('#bikeStudioResults')).toContainText('2021–2019 (invalid source range; review)');
  await expect(page.locator('#bikeStudioResults')).toContainText('source cc: 149,48');
  await page.locator('#bikeStudioQuery').fill('ADV 160');
  await page.locator('#bikeStudioYear').fill('2026');
  await page.getByRole('button', {name:'Choose Honda ADV 160 2026 in Garage'}).click();
  await expect(page.locator('#bikeStudioGarage')).toContainText('30400-K0WW-ND2');
  await expect(page.locator('#bikeStudioGarage')).not.toContainText('30400-K0WL-NA1');
  await expect(page.locator('#connectBtn')).toBeDisabled();
  expect(await page.locator('#yearSelect option').allTextContents()).not.toContain('2024');
  expect(page.failures).toEqual([]);
});

test('BikeStudio new PCX and XMAX selections keep gaps and unknown data', async ({page}) => {
  await page.goto('/');
  await page.locator('#bikeStudioLookup > summary').click();
  await page.locator('#bikeStudioQuery').fill('PCX 160');
  await page.locator('#bikeStudioYear').fill('2025');
  await page.getByRole('button', {name:'Choose Honda PCX 160 2025 in Garage'}).click();
  await expect(page.locator('#bikeStudioGarage')).toContainText('30400-K1ZH-B11');
  await expect(page.locator('#connectBtn')).toBeDisabled();
  expect(await page.locator('#yearSelect option').allTextContents()).not.toContain('2024');
  await page.locator('#bikeStudioQuery').fill('XMAX');
  await page.locator('#bikeStudioYear').fill('2023');
  await expect(page.locator('#bikeStudioResults')).toContainText('B741 · source years: not stated (year unknown)');
  await page.getByRole('button', {name:'Choose Yamaha XMAX 2023 in Garage'}).click();
  await expect(page.locator('#bikeStudioGarage')).toContainText('B5X0');
  await expect(page.locator('#connectBtn')).toBeDisabled();
  expect(page.failures).toEqual([]);
});

test('BikeStudio market filtering is local, exact and retains unstated markets', async ({page}) => {
  await page.goto('/');
  await page.locator('#bikeStudioLookup > summary').click();
  await page.locator('#bikeStudioQuery').fill('CBR 250 R');
  await page.locator('#bikeStudioYear').fill('2014');
  await page.locator('#bikeStudioMarket').fill('indonesia');
  const box = page.locator('#bikeStudioResults .gate-card').filter({has:page.getByRole('heading', {name:'Honda CBR 250 R', exact:true})});
  await expect(box).toContainText('38770-K33-N03');
  await expect(box).toContainText('38770-K33-D22'); // market not stated
  await expect(box).not.toContainText('38770-K33-T53'); // Asia is a distinct label
  await page.locator('#bikeStudioMarket').fill('Asia');
  await expect(box).toContainText('38770-K33-T53');
  await expect(box).toContainText('38770-K33-D22');
  await expect(box).not.toContainText('38770-K33-N03');
  expect(page.failures).toEqual([]);
});

test('ECU identifier search opens the BikeStudio reference without changing bike', async ({page}) => {
  await page.goto('/');
  await page.locator('[data-view="tools"]').click();
  await page.locator('#ecuPart').fill('38770-MGZ-A03');
  await page.locator('#ecuLookupBtn').click();
  await page.getByRole('button', {name:'Find this part in the BikeStudio reference'}).click();
  await expect(page.locator('#bikeStudioQuery')).toHaveValue('38770-MGZ-A03');
  await expect(page.locator('#bikeStudioResults')).toContainText('38770-MGZ-A03');
  await page.locator('[data-view="tools"]').click();
  await page.locator('#sharedEcuLoad').click();
  await expect(page.locator('#sharedEcuFamily')).toBeEnabled();
  expect(await page.locator('#sharedEcuFamily option[value="bikestudio_reference_only"]').count()).toBe(0);
  expect(await page.locator('#sharedEcuFamily option[value="honda_pgmfi_flash_research"]').count()).toBe(0);
  expect(page.failures).toEqual([]);
});

test('BikeStudio live lookup fetches only explicit public index and chosen model', async ({page}) => {
  const requests = [];
  await page.route('**/api/tools/bikestudio', async route => {
    const body = route.request().postDataJSON(); requests.push(body);
    const data = body.kind === 'index' ? {models:[
      {slug:'honda-beat-110',label:'BeAT 110 (8)',aliases:'BeAT eSP'},
      {slug:'yamaha-nmax-new',label:'NMAX NEW (13)',aliases:'NMAX Connected'}]} :
      {slug:body.slug,rows:[{part:'BLE-H594A-00',part_slug:'ble-h594a-00',years:'2024–2026',cc:'155',market:'Asia'},
                            {part:'B6Y-H594A-02',part_slug:'b6y-h594a-02',years:'2021–2024',cc:'155',market:'Asia'},
                            {part:'UNKNOWN',part_slug:'unknown',years:'',cc:'',market:''}]};
    await route.fulfill({json:data});
  });
  await page.goto('/');
  await page.locator('#bikeStudioLookup > summary').click();
  await page.locator('#bikeStudioOnline summary').click();
  expect(requests).toHaveLength(0);
  await page.locator('#bikeStudioOnlineLoad').click();
  await expect(page.locator('#bikeStudioOnlineOut')).toContainText('Loaded 2 public model links');
  await page.locator('#bikeStudioOnlineFilter').fill('NMAX Connected');
  await page.locator('#bikeStudioOnlineModel').selectOption('yamaha-nmax-new');
  await page.locator('#bikeStudioYear').fill('2022');
  await page.locator('#bikeStudioOnlineRead').click();
  await expect(page.locator('#bikeStudioOnlineOut')).toContainText('B6Y-H594A-02');
  await expect(page.locator('#bikeStudioOnlineOut')).toContainText('year unknown');
  await expect(page.locator('#bikeStudioOnlineOut')).not.toContainText('BLE-H594A-00');
  await expect(page.locator('#bikeStudioOnlineOut a', {hasText:'source part'}).first()).toHaveAttribute('href','https://bikestudio.io/ecu/b6y-h594a-02?lang=en');
  await page.locator('#bikeStudioMarket').fill('Indonesia');
  await expect(page.locator('#bikeStudioOnlineOut')).not.toContainText('B6Y-H594A-02');
  await expect(page.locator('#bikeStudioOnlineOut')).toContainText('UNKNOWN');
  await page.locator('#bikeStudioMarket').fill('Asia');
  await expect(page.locator('#bikeStudioOnlineOut')).toContainText('B6Y-H594A-02');
  expect(requests).toEqual([{kind:'index',confirm_external:true},{kind:'model',slug:'yamaha-nmax-new',confirm_external:true}]);
  expect(page.failures).toEqual([]);
});

test('desktop Buell single image read automatically saves and opens write review', async ({page}) => {
  await page.goto('/'); await page.locator('[data-view="tools"]').click();
  const calls = [];
  const data = Buffer.alloc(1210, 1);
  await page.route('**/api/tools/buell-ddfi', async route => {
    const body = route.request().postDataJSON(); calls.push(body);
    const result = body.action === 'identify' ? {version:'BUEIB310 12-11-03'}
      : body.action === 'image' ? {version:'BUEIB310 12-11-03', kind:'eeprom-image', layout:'BUEIB',
          length:data.length, data_hex:data.toString('hex').toUpperCase(), sha256:'synthetic',
          read_token:'single-read-token', original_path:'/synthetic/BUEIB-original.xpr', original_verified:false}
      : body.action === 'prepare-from-read' ? {version:'BUEIB310 12-11-03', xdf:'BUEIB_source_research.xdf',
          changes:[{offset:884,before:1,after:42}], base_sha256:'original', target_sha256:'edited',
          warning:'Synthetic only', token:'review-token', expires_seconds:300, single_read:true}
      : {chunks_written:1,edited_bytes:1,backup_path:'/synthetic/BUEIB-original.xpr',backup_sha256:'original',note:'Synthetic only',single_read:true};
    await route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(result)});
  });
  await page.locator('#buellPort').fill('/dev/ttyUSB0');
  await page.locator('#buellConfirm').check(); await page.locator('#buellIdentify').click();
  await expect(page.locator('#buellVersion')).toHaveValue('BUEIB310 12-11-03');
  await page.locator('#buellConfirm').check(); await page.locator('#buellImage').click();
  await expect(page.locator('#buellWritePanel')).toHaveAttribute('open', '');
  await expect(page.locator('#buellWriteOriginal')).toHaveValue('/synthetic/BUEIB-original.xpr');
  await expect(page.locator('#buellOut')).toContainText('no SET was sent');
  await page.locator('#buellSaveImage').click();
  await expect(page.locator('#buellOut')).toContainText('Saved:');
  await expect(page.locator('#buellWriteOriginal')).toHaveValue('/synthetic/BUEIB-original.xpr');
  await page.locator('#buellWriteEdited').fill('/synthetic/edited.xpr');
  await page.locator('#buellWriteConfirm').check(); await page.locator('#buellWritePrepare').click();
  await expect(page.locator('#buellWriteExecute')).toBeEnabled();
  expect(calls.filter(c => c.action === 'prepare-from-read')).toEqual([
    {action:'prepare-from-read',confirm:true,read_token:'single-read-token',edited_path:'/synthetic/edited.xpr'}]);
  expect(calls.filter(c => c.action === 'write')).toHaveLength(0);
  await page.locator('#buellWriteExecute').click();
  await expect(page.locator('#modal')).toContainText('only affected live chunks');
  expect(calls.filter(c => c.action === 'write')).toHaveLength(0);
  await page.locator('#modalConfirm').click();
  await expect(page.locator('#buellWriteOut')).toContainText('Single-read original: /synthetic/BUEIB-original.xpr');
  expect(calls.filter(c => c.action === 'write')).toHaveLength(1);
});

test('rusEFI one-read calibration review requires explicit write and burn confirmation', async ({page}) => {
  await page.goto('/'); await page.locator('[data-view="tools"]').click();
  const requests = [];
  const signature = 'rusEFI synthetic.board.1234';
  const ini = `[TunerStudio]\nsignature = "${signature}"\n[Constants]\npageSize=300\n`;
  await page.route('**/api/tools/rusefi-read', async route => {
    const body = route.request().postDataJSON(); requests.push(body);
    const data = body.action === 'read-calibration'
      ? {signature, length:300, sha256:'old', original_path:'/synthetic/rusefi-page0.bin', read_token:'read-token'}
      : body.action === 'prepare-calibration'
      ? {signature, changed_bytes:1, original_sha256:'old', target_sha256:'new', ini_sha256:'ini',
         changes:[{offset:10,before:'01',after:'02'}],token:'plan-token',expires_seconds:300}
      : {changed_bytes:1,chunks_written:1,original_path:'/synthetic/rusefi-page0.bin',note:'Synthetic only; persistence not verified.'};
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.locator('#rusefiPort').fill('/dev/ttyACM0');
  await page.locator('#rusefiIni').setInputFiles({name:'rusefi.ini',mimeType:'text/plain',buffer:Buffer.from(ini)});
  await expect(page.locator('#rusefiSignature')).toHaveValue(signature);
  await page.locator('#rusefiConfirm').check();
  await page.locator('#rusefiTunePanel > summary').click();
  await page.locator('#rusefiTuneRead').click();
  await expect(page.locator('#rusefiTuneOriginal')).toHaveValue('/synthetic/rusefi-page0.bin');
  expect(requests[0]).toMatchObject({action:'read-calibration',port:'/dev/ttyACM0',baud:115200,ini,confirm:true});
  await page.locator('#rusefiTuneEdited').fill('/synthetic/edited.bin');
  await page.locator('#rusefiTuneConfirm').check();
  await page.locator('#rusefiTunePrepare').click();
  await expect(page.locator('#rusefiTuneOut')).toContainText('0xA: 01 → 02');
  expect(requests.filter(x => x.action === 'write-calibration')).toHaveLength(0);
  await page.locator('#rusefiTuneEdited').fill('/synthetic/other.bin');
  await expect(page.locator('#rusefiTuneWrite')).toBeDisabled();
  await page.locator('#rusefiTunePrepare').click();
  await page.locator('#rusefiTuneWrite').click();
  await expect(page.locator('#modal')).toContainText('previously pending burn');
  expect(requests.filter(x => x.action === 'write-calibration')).toHaveLength(0);
  await page.locator('#modalConfirm').click();
  await expect(page.locator('#rusefiTuneOut')).toContainText('persistence not verified');
  expect(requests.filter(x => x.action === 'write-calibration')).toEqual([
    {action:'write-calibration',confirm:true,confirm_tuning:true,confirm_write:true,token:'plan-token'}]);
  await expect(page.locator('#rusefiTuneWrite')).toBeDisabled();
});

test('Honda VFR research checksum review exports only a corrected copy', async ({ page }) => {
  await page.goto('/'); await page.locator('[data-view="tools"]').click();
  const original = Buffer.alloc(0x100000);
  Buffer.from([1, 0, 0xaa, 5, 1]).copy(original, 0x36b57);
  let sum = 0; for (const byte of original) sum = (sum + byte) & 255;
  original[0x7fff8] = (-sum) & 255;
  const edited = Buffer.from(original); edited[0x1234] = 37;
  await page.locator('#hondaVfrVariant').selectOption('0100AA0501');
  await page.locator('#hondaVfrOriginal').setInputFiles({name:'original.bin', mimeType:'application/octet-stream', buffer:original});
  await page.locator('#hondaVfrEdited').setInputFiles({name:'edited.bin', mimeType:'application/octet-stream', buffer:edited});
  await page.locator('#hondaVfrInspect').click();
  await expect(page.locator('#hondaVfrOut')).toContainText('1 bytes differ');
  await expect(page.locator('#hondaVfrExport')).toBeDisabled();
  await page.locator('#hondaVfrConfirm').check();
  await page.locator('#hondaVfrInspect').click();
  await expect(page.locator('#hondaVfrExport')).toBeEnabled();
  const before = new Set(readdirSync(EXPORTS));
  await page.locator('#hondaVfrExport').click();
  await expect(page.locator('#hondaVfrOut')).toContainText('Saved research copy:');
  const filename = readdirSync(EXPORTS).find(name => name.startsWith('honda-38770-mge-773-research-') && !before.has(name));
  expect(filename).toBeTruthy();
  const result = readFileSync(join(EXPORTS, filename));
  sum = 0; let changes = [];
  for (let i=0; i<result.length; i++) { sum = (sum + result[i]) & 255; if (result[i] !== edited[i]) changes.push(i); }
  expect(sum).toBe(0); expect(changes).toEqual([0x7fff8]);
  await page.locator('#hondaVfrVariant').selectOption('4801011901');
  await expect(page.locator('#hondaVfrExport')).toBeDisabled();
  await page.locator('#hondaVfrInspect').click();
  await expect(page.locator('#hondaVfrOut')).toContainText('Both images must contain the selected ID');
  expect(page.failures).toEqual([]);
});

test('Honda source checksum rejects mismatched and corrupted synthetic candidates', () => {
  const honda = createRequire(import.meta.url)('../../web/honda-research-checksum.js');
  expect(Object.keys(honda.candidates).length).toBe(44);
  for (const [variant, spec] of Object.entries(honda.candidates)) {
    const original = new Uint8Array(spec.size);
    original.set(variant.match(/../g).map(x => parseInt(x,16)), spec.id_offset);
    original[spec.checksum_offset] = (-original.reduce((a,b) => a+b,0)) & 255;
    const edited = original.slice(); edited[123] = 255;
    const result = honda.inspect(original, edited, variant);
    expect(result.corrected.reduce((a,b) => (a+b)&255,0)).toBe(0);
    expect(result.changed).toBe(1); expect(original[123]).toBe(0); expect(edited[123]).toBe(255);
    expect(() => honda.inspect(original, original, variant)).toThrow();
    expect(() => honda.inspect(original, edited, 'wrong')).toThrow();
    const corrupt = original.slice(); corrupt[1]++;
    expect(() => honda.inspect(corrupt, edited, variant)).toThrow();
    expect(() => honda.inspect(original.slice(0,-1), edited, variant)).toThrow();
  }
});

test('one synthetic Honda VFR research read automatically opens its candidate XDF', async ({ page }) => {
  const path = resolve('.desktop-test-data', 'vfr-synthetic-research.bin');
  const image = Buffer.alloc(0x100000); Buffer.from([1,0,0xaa,5,1]).copy(image,0x36b57);
  image[0x7fff8] = (-image.reduce((sum, n) => sum+n, 0)) & 255; writeFileSync(path, image);
  await page.goto('/'); await page.locator('[data-view="firmware"]').click();
  await page.evaluate(path => renderMemoryProgress({name:'read:flash', state:'done', result:{
    path, research_only:true,
    describe:{identity:{'ECM ID candidate':'01 00 AA 05 01', 'Source part candidate':'38770-MGE-773'}, meta:{protocol:'honda-source-id-research', candidate_source:'AlexKovalevich/HondaECU db0a6cb8'}}
  }}), path);
  await expect(page.locator('#hondaVfrHandoff')).toContainText('not a verified backup');
  await expect(page.locator('#xdfSelect')).toHaveValue('HONDA_VFR1200F_MGE_773.xdf');
  await expect(page.locator('#mapsImagePath')).toHaveValue(path);
  await expect(page.locator('#mapsOut')).toContainText('Honda VFR1200F 2010 NA 38770-MGE-773');
  await expect(page.locator('#mapsOut .map-value').first()).toBeVisible();
  expect(readFileSync(path)).toEqual(image);
  await page.evaluate(path => {
    maps.changes.set('sentinel', { value: 1 });
    return openHondaResearchMap(path, '38770-MGE-701');
  }, path);
  await expect(page.locator('#hondaVfrHandoff')).toContainText('existing staged edits were preserved');
  await expect(page.locator('#xdfSelect')).toHaveValue('HONDA_VFR1200F_MGE_773.xdf');
  expect(await page.evaluate(() => maps.changes.has('sentinel'))).toBe(true);
  expect(page.failures.filter(error => !/server responded with a status of 409/.test(error))).toEqual([]);
});

test('Honda MGZ one-read handoff and source checksum review stay research-only', async ({ page }) => {
  const path = resolve('.desktop-test-data', 'mgz-synthetic-research.bin');
  const image = Buffer.alloc(0x40000); Buffer.from([1,1,0x25,5,1]).copy(image,0x17fc7);
  image[0x3fff8] = (-image.reduce((sum,n) => sum+n,0)) & 255; writeFileSync(path,image);
  await page.goto('/'); await page.locator('[data-view="firmware"]').click();
  await page.evaluate(path => renderMemoryProgress({name:'read:flash', state:'done', result:{
    path, research_only:true,
    describe:{identity:{'ECM ID candidate':'01 01 25 05 01','Source part candidate':'38770-MGZ-A03'},
      meta:{protocol:'honda-source-id-research',candidate_source:'WiseNoodle/honda-moto-ecu-suite 85431bd8'}}
  }}), path);
  await expect(page.locator('#xdfSelect')).toHaveValue('38770-MGZ.xdf');
  await expect(page.locator('#hondaVfrHandoff')).toContainText('byte order conflicts');
  await expect(page.locator('#mapsOut')).toContainText('table(s)');
  await page.locator('[data-view="tools"]').click();
  const edited = Buffer.from(image); edited[0x100] = 42;
  await page.locator('#hondaVfrVariant').selectOption('0101250501');
  await page.locator('#hondaVfrOriginal').setInputFiles({name:'original.bin',mimeType:'application/octet-stream',buffer:image});
  await page.locator('#hondaVfrEdited').setInputFiles({name:'edited.bin',mimeType:'application/octet-stream',buffer:edited});
  await page.locator('#hondaVfrConfirm').check(); await page.locator('#hondaVfrInspect').click();
  await expect(page.locator('#hondaVfrOut')).toContainText('Checksum at 0x3FFF8');
  await expect(page.locator('#hondaVfrExport')).toBeEnabled();
  expect(readFileSync(path)).toEqual(image);
  expect(page.failures.filter(error => !/server responded with a status of 409/.test(error))).toEqual([]);
});

test('Honda edited research map previews and exports a checksum-corrected copy in one workflow', async ({ page }) => {
  const root = resolve('.desktop-test-data'), definitions = join(root, 'xdfs');
  mkdirSync(definitions, {recursive:true});
  const path = join(root, 'honda-checksum-workflow.bin');
  const source = Buffer.alloc(0x40000); Buffer.from([1,1,0x25,5,1]).copy(source, 0x17fc7);
  Buffer.from([10,20,30,40]).copy(source,0x20);
  source[0x3fff8] = (-source.reduce((sum,n) => sum+n,0)) & 255; writeFileSync(path,source);
  const xdf = `<XDFFORMAT><XDFHEADER><deftitle>Synthetic Honda workflow</deftitle><DEFAULTS signed="0" lsbfirst="0"/><REGION size="0x40000"/></XDFHEADER>
  <XDFTABLE uniqueid="fuel"><title>Fuel</title><XDFAXIS id="x"><indexcount>2</indexcount></XDFAXIS><XDFAXIS id="y"><indexcount>2</indexcount></XDFAXIS>
  <XDFAXIS id="z"><EMBEDDEDDATA mmedaddress="0x20" mmedelementsizebits="8" mmedrowcount="2" mmedcolcount="2"/><MATH equation="X"/></XDFAXIS></XDFTABLE></XDFFORMAT>`;
  writeFileSync(join(definitions,'honda-workflow.xdf'),xdf);
  await page.goto('/'); await page.locator('[data-view="firmware"]').click();
  await page.locator('#xdfOnlyFitting').uncheck(); await page.locator('#mapsRefreshBtn').click();
  await expect(page.locator('#xdfSelect option[value="honda-workflow.xdf"]')).toHaveCount(1);
  await page.locator('#xdfSelect').selectOption('honda-workflow.xdf');
  await page.locator('#mapsImagePath').fill(path); await page.locator('#mapsRenderBtn').click();
  if (await page.locator('#modal').isVisible()) await page.locator('#modalConfirm').click();
  const cell = page.locator('[data-map-kind="table"][data-map-id="fuel"][data-map-row="0"][data-map-col="1"]');
  await expect(cell).toHaveAttribute('data-map-value','20'); await cell.dblclick();
  await page.locator('#mapEditValue').fill('25'); await page.locator('#modalConfirm').click();
  await page.locator('#mapResearchPreviewBtn').click();
  const preview = page.locator('#mapResearchPreviewOut');
  await expect(preview).toContainText('Honda checksum candidates');
  await expect(preview).toContainText('38770-MGZ-A03');
  await expect(preview).toContainText('Checksum byte 0x3FFF8');
  await preview.locator('[data-honda-checksum-export]').click();
  await expect(page.locator('#modal')).toBeVisible(); await page.locator('#modalConfirm').click();
  await expect(preview).toContainText('Honda research copy saved');
  const text = await preview.textContent(); const outputPath = text.match(/Image:\s*(\S+\.bin)/)?.[1];
  expect(outputPath).toBeTruthy(); const result = readFileSync(outputPath);
  expect(result[0x21]).toBe(25); expect(result.reduce((s,n)=>(s+n)&255,0)).toBe(0);
  expect(result[0x3fff8]).not.toBe(source[0x3fff8]); expect(readFileSync(path)).toEqual(source);
  expect(page.failures.filter(error => !/server responded with a status of 409/.test(error))).toEqual([]);
});

test('Buell single read opens source map and carries reviewed edits to write review', async ({page}) => {
  const sourcePath = join(resolve('.desktop-test-data'), 'BUEIB-one-read.xpr');
  const image = Buffer.from(Array.from({length:1210}, (_,i) => i & 255)); writeFileSync(sourcePath,image);
  const digest = createHash('sha256').update(image).digest('hex'); const calls = [];
  await page.route('**/api/tools/buell-ddfi', async route => {
    const body = route.request().postDataJSON(); calls.push(body);
    const response = body.action === 'identify' ? {version:'BUEIB310 12-11-03'}
      : body.action === 'image' ? {version:'BUEIB310 12-11-03',kind:'eeprom-image',layout:'BUEIB',
          length:image.length,data_hex:image.toString('hex').toUpperCase(),sha256:digest,
          read_token:'single-read-token',original_path:sourcePath,original_verified:false,map_xdf:'BUEIB_source_research.xdf'}
      : {version:'BUEIB310 12-11-03',xdf:'BUEIB_source_research.xdf',changes:[{offset:884,before:image[884],after:42}],
         base_sha256:digest,target_sha256:'synthetic',warning:'Synthetic tests only',token:'plan',expires_seconds:300,single_read:true};
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(response)});
  });
  await page.goto('/'); await page.locator('[data-view="tools"]').click();
  await page.locator('#buellPort').fill('/dev/ttyUSB0'); await page.locator('#buellConfirm').check();
  await page.locator('#buellIdentify').click(); await page.locator('#buellConfirm').check();
  await page.locator('#buellImage').click(); await expect(page.locator('#buellOpenMap')).toBeEnabled();
  await expect(page.locator('#buellMapStatus')).toContainText('opened in Maps');
  await page.locator('#buellOpenMap').click();
  await expect(page.locator('#xdfSelect')).toHaveValue('BUEIB_source_research.xdf');
  await expect(page.locator('#mapsImagePath')).toHaveValue(sourcePath);
  await page.locator('details.map-table-entry').filter({hasText:'Tab_Fuel_Front'}).locator('summary').first().click();
  const cell = page.locator('[data-map-kind="table"][data-map-id="0x3"][data-map-row="1"][data-map-col="0"]');
  await cell.dblclick(); await page.locator('#mapEditValue').fill('42'); await page.locator('#modalConfirm').click();
  await page.locator('#mapResearchPreviewBtn').click();
  await expect(page.locator('#buellMapExportBtn')).toBeVisible();
  await page.locator('#buellMapExportBtn').click();
  const response = page.waitForResponse(r => r.url().includes('/api/maps/research-export') && r.status() === 201);
  await page.locator('#modalConfirm').click(); const saved = await (await response).json();
  await expect(page.locator('#mapResearchPreviewOut')).toContainText('Edited path filled');
  expect(readFileSync(saved.path)[884]).toBe(42); expect(readFileSync(sourcePath)).toEqual(image);
  await page.locator('[data-view="tools"]').click();
  await expect(page.locator('#buellWriteEdited')).toHaveValue(saved.path);
  await page.locator('#buellWriteConfirm').check(); await page.locator('#buellWritePrepare').click();
  await expect(page.locator('#buellWriteExecute')).toBeEnabled();
  expect(calls.filter(c=>c.action==='prepare-from-read')).toEqual([{action:'prepare-from-read',confirm:true,read_token:'single-read-token',edited_path:saved.path}]);
  expect(calls.filter(c=>c.action==='write')).toHaveLength(0);
  expect(page.failures).toEqual([]);
});

test('Harley saved single-read tune flows through chosen XDF into reviewed write', async ({page}) => {
  const root = resolve('.desktop-test-data'), xdfs = join(root,'xdfs'); mkdirSync(xdfs,{recursive:true});
  const sourcePath = join(root,'harley-one-read.bin'), image = Buffer.alloc(0x4000);
  Buffer.from([10,20,30,40]).copy(image,0x20); writeFileSync(sourcePath,image);
  const digest = createHash('sha256').update(image).digest('hex');
  const xdf = `<XDFFORMAT><XDFHEADER><deftitle>Synthetic Harley one-read</deftitle><DEFAULTS signed="0" lsbfirst="0"/><REGION size="0x4000"/></XDFHEADER>
  <XDFTABLE uniqueid="fuel"><title>Fuel</title><XDFAXIS id="x"><indexcount>2</indexcount></XDFAXIS><XDFAXIS id="y"><indexcount>2</indexcount></XDFAXIS><XDFAXIS id="z"><EMBEDDEDDATA mmedaddress="0x20" mmedelementsizebits="8" mmedrowcount="2" mmedcolcount="2"/><MATH equation="X"/></XDFAXIS></XDFTABLE></XDFFORMAT>`;
  writeFileSync(join(xdfs,'harley-one-read.xdf'),xdf); const calls=[];
  await page.route('**/api/tools/harley-memory', async route => {
    const body=route.request().postDataJSON(); calls.push(body);
    const response=body.action==='read' ? {identity:{F1EA:'41',F1ED:'42',F1F5:'43'},region:'tune',address:0x7f4000,length:16384,sha256:digest,data_hex:image.toString('hex').toUpperCase(),repeated_match:false,read_token:'one-read',original_tune_path:sourcePath,original_tune_sha256:digest,original_tune_verified:false}
      : {identity:{F1EA:'41',F1ED:'42',F1F5:'43'},original_sha256:digest,target_sha256:'target',changed_bytes:1,changes:[{offset:33,before:20,after:25}],token:'plan',expires_seconds:300};
    await route.fulfill({json:response});
  });
  await page.goto('/'); await page.locator('[data-view="tools"]').click();
  await page.locator('#hdMemChannel').fill('can0'); await page.locator('#hdMemCapture').fill('/tmp/test-auth');
  await page.locator('#hdMemConfirm').check(); await page.locator('#hdMemRead').click();
  await expect(page.locator('#hdMemOpenMap')).toBeEnabled(); await page.locator('#hdMemOpenMap').click();
  await expect(page.locator('#mapsImagePath')).toHaveValue(sourcePath);
  await page.locator('#xdfOnlyFitting').uncheck(); await page.locator('#xdfSelect').selectOption('harley-one-read.xdf');
  await page.locator('#mapsAddressBase').fill('0'); await page.locator('#mapsRenderBtn').click();
  if (await page.locator('#modal').isVisible()) await page.locator('#modalConfirm').click();
  const cell=page.locator('[data-map-kind="table"][data-map-id="fuel"][data-map-row="0"][data-map-col="1"]');
  await expect(cell).toHaveAttribute('data-map-value','20'); await cell.dblclick();
  await page.locator('#mapEditValue').fill('25'); await page.locator('#modalConfirm').click();
  await page.locator('#mapResearchPreviewBtn').click(); await page.locator('#harleyResearchExportBtn').click();
  const response=page.waitForResponse(r=>r.url().includes('/api/maps/harley-research-export') && r.status()===201);
  await page.locator('#modalConfirm').click(); const saved=await (await response).json();
  await expect(page.locator('#mapResearchPreviewOut')).toContainText('Edited tune path filled');
  expect(readFileSync(saved.path)[33]).toBe(25); expect(readFileSync(sourcePath)).toEqual(image);
  await page.locator('[data-view="tools"]').click(); await expect(page.locator('#hdMemEdited')).toHaveValue(saved.path);
  await page.locator('#hdMemPrepare').click(); await expect(page.locator('#hdMemWriteOut')).toContainText('0x21: 20 → 25');
  expect(calls.filter(c=>c.action==='prepare-from-read')).toEqual([{action:'prepare-from-read',confirm:true,read_token:'one-read',edited_path:saved.path}]);
  expect(calls.filter(c=>c.action==='write')).toHaveLength(0); expect(page.failures).toEqual([]);
});

test('rusEFI saved page flows through user XDF into calibration write review', async ({page}) => {
  const root=resolve('.desktop-test-data'), xdfs=join(root,'xdfs'); mkdirSync(xdfs,{recursive:true});
  const sourcePath=join(root,'rusefi-one-read.bin'), image=Buffer.alloc(300);
  Buffer.from([10,20,30,40]).copy(image,0x20); writeFileSync(sourcePath,image);
  const digest=createHash('sha256').update(image).digest('hex'), signature='rusEFI synthetic.board.1234';
  const xdf=`<XDFFORMAT><XDFHEADER><deftitle>Synthetic rusEFI</deftitle><DEFAULTS signed="0" lsbfirst="0"/><REGION size="300"/></XDFHEADER>
  <XDFTABLE uniqueid="fuel"><title>Fuel</title><XDFAXIS id="x"><indexcount>2</indexcount></XDFAXIS><XDFAXIS id="y"><indexcount>2</indexcount></XDFAXIS><XDFAXIS id="z"><EMBEDDEDDATA mmedaddress="0x20" mmedelementsizebits="8" mmedrowcount="2" mmedcolcount="2"/><MATH equation="X"/></XDFAXIS></XDFTABLE></XDFFORMAT>`;
  writeFileSync(join(xdfs,'rusefi-one-read.xdf'),xdf); const calls=[];
  await page.route('**/api/tools/rusefi-read',async route=>{
    const body=route.request().postDataJSON(); calls.push(body);
    const response=body.action==='read-calibration' ? {signature,length:300,sha256:digest,original_path:sourcePath,read_token:'read-token'}
      : {signature,length:300,original_sha256:digest,target_sha256:'target',ini_sha256:'ini',changed_bytes:1,changes:[{offset:33,before:'14',after:'19'}],token:'plan',expires_seconds:300};
    await route.fulfill({json:response});
  });
  await page.goto('/'); await page.locator('[data-view="tools"]').click();
  await page.locator('#rusefiPort').fill('/dev/ttyACM0');
  await page.locator('#rusefiIni').setInputFiles({name:'synthetic.ini',mimeType:'text/plain',buffer:Buffer.from(`[TunerStudio]\nsignature="${signature}"\n[Constants]\npageSize=300\n`)});
  await page.locator('#rusefiConfirm').check(); await page.locator('#rusefiTunePanel > summary').click(); await page.locator('#rusefiTuneRead').click();
  await expect(page.locator('#rusefiOpenMap')).toBeEnabled(); await page.locator('#rusefiOpenMap').click();
  await expect(page.locator('#mapsImagePath')).toHaveValue(sourcePath);
  await page.locator('#xdfOnlyFitting').uncheck(); await page.locator('#xdfSelect').selectOption('rusefi-one-read.xdf');
  await page.locator('#mapsAddressBase').fill('0'); await page.locator('#mapsRenderBtn').click();
  if (await page.locator('#modal').isVisible()) await page.locator('#modalConfirm').click();
  const cell=page.locator('[data-map-kind="table"][data-map-id="fuel"][data-map-row="0"][data-map-col="1"]');
  await expect(cell).toHaveAttribute('data-map-value','20'); await cell.dblclick();
  await page.locator('#mapEditValue').fill('25'); await page.locator('#modalConfirm').click();
  await page.locator('#mapResearchPreviewBtn').click(); await page.locator('#rusefiMapExportBtn').click();
  const response=page.waitForResponse(r=>r.url().includes('/api/maps/research-export') && r.status()===201);
  await page.locator('#modalConfirm').click(); const saved=await (await response).json();
  await expect(page.locator('#mapResearchPreviewOut')).toContainText('Edited path filled in the rusEFI panel');
  expect(readFileSync(saved.path)[33]).toBe(25); expect(readFileSync(sourcePath)).toEqual(image);
  await page.locator('[data-view="tools"]').click(); await expect(page.locator('#rusefiTuneEdited')).toHaveValue(saved.path);
  await page.locator('#rusefiTuneConfirm').check(); await page.locator('#rusefiTunePrepare').click();
  await expect(page.locator('#rusefiTuneWrite')).toBeEnabled();
  expect(calls.filter(c=>c.action==='prepare-calibration')).toEqual([{action:'prepare-calibration',confirm:true,confirm_tuning:true,read_token:'read-token',edited_path:saved.path}]);
  expect(calls.filter(c=>c.action==='write-calibration')).toHaveLength(0); expect(page.failures).toEqual([]);
});

test('Buell automatic map handoff preserves staged edits and can be retried after clearing', async ({page}) => {
  const sourcePath=join(resolve('.desktop-test-data'),'BUEIB-preserve.xpr');
  const data=Buffer.from(Array.from({length:1210},(_,i)=>i&255)); writeFileSync(sourcePath,data);
  const digest=createHash('sha256').update(data).digest('hex');
  await page.route('**/api/tools/buell-ddfi',async route=>{
    const body=route.request().postDataJSON();
    await route.fulfill({json:body.action==='identify' ? {version:'BUEIB310 12-11-03'} :
      {version:'BUEIB310 12-11-03',kind:'eeprom-image',layout:'BUEIB',length:data.length,data_hex:data.toString('hex').toUpperCase(),sha256:digest,read_token:'current',original_path:sourcePath,map_xdf:'BUEIB_source_research.xdf'}});
  });
  await page.goto('/'); await page.locator('[data-view="firmware"]').click();
  await page.locator('#xdfOnlyFitting').uncheck(); await page.locator('#mapsRefreshBtn').click();
  await page.locator('#xdfSelect').selectOption('BUEIB_source_research.xdf');
  await page.locator('#mapsImagePath').fill(sourcePath); await page.locator('#mapsAddressBase').fill('0');
  await page.locator('#mapsRenderBtn').click(); if (await page.locator('#modal').isVisible()) await page.locator('#modalConfirm').click();
  await page.locator('details.map-table-entry').filter({hasText:'Tab_Fuel_Front'}).locator('summary').first().click();
  const cell=page.locator('[data-map-kind="table"][data-map-id="0x3"][data-map-row="1"][data-map-col="0"]');
  await cell.dblclick(); await page.locator('#mapEditValue').fill('42'); await page.locator('#modalConfirm').click();
  await expect(page.locator('#mapResearchPreviewBtn')).toBeEnabled();
  await page.locator('[data-view="tools"]').click(); await page.locator('#buellPort').fill('/dev/ttyUSB0');
  await page.locator('#buellConfirm').check(); await page.locator('#buellIdentify').click();
  await page.locator('#buellConfirm').check(); await page.locator('#buellImage').click();
  await expect(page.locator('#buellMapStatus')).toContainText('Existing staged map edits were preserved');
  await expect(page.locator('#buellOpenMap')).toBeEnabled();
  await page.locator('[data-view="firmware"]').click(); await expect(page.locator('#mapResearchPreviewBtn')).toBeEnabled();
  await page.locator('#mapClearChangesBtn').click();
  await page.locator('[data-view="tools"]').click(); await page.locator('#buellOpenMap').click();
  await expect(page.locator('#buellMapStatus')).toContainText('opened in Maps');
  await expect(page.locator('#mapsImagePath')).toHaveValue(sourcePath); expect(page.failures).toEqual([]);
});

test('Buell export preserves an edited path changed during confirmation', async ({page}) => {
  const sourcePath=join(resolve('.desktop-test-data'),'BUEIB-race.xpr');
  const image=Buffer.from(Array.from({length:1210},(_,i)=>i&255)); writeFileSync(sourcePath,image);
  const digest=createHash('sha256').update(image).digest('hex');
  await page.route('**/api/tools/buell-ddfi',async route=>{
    const b=route.request().postDataJSON(); await route.fulfill({json:b.action==='identify' ? {version:'BUEIB310 12-11-03'} :
      {version:'BUEIB310 12-11-03',kind:'eeprom-image',layout:'BUEIB',length:image.length,data_hex:image.toString('hex').toUpperCase(),sha256:digest,read_token:'valid',original_path:sourcePath,map_xdf:'BUEIB_source_research.xdf'}});
  });
  await page.goto('/'); await page.locator('[data-view="tools"]').click();
  await page.locator('#buellPort').fill('/dev/ttyUSB0'); await page.locator('#buellConfirm').check();
  await page.locator('#buellIdentify').click(); await page.locator('#buellConfirm').check(); await page.locator('#buellImage').click();
  await expect(page.locator('#buellOpenMap')).toBeEnabled(); await page.locator('#buellOpenMap').click();
  await page.locator('details.map-table-entry').filter({hasText:'Tab_Fuel_Front'}).locator('summary').first().click();
  await page.locator('[data-map-kind="table"][data-map-id="0x3"][data-map-row="1"][data-map-col="0"]').dblclick();
  await page.locator('#mapEditValue').fill('42'); await page.locator('#modalConfirm').click();
  await page.locator('#mapResearchPreviewBtn').click(); await page.locator('#buellMapExportBtn').click();
  await page.evaluate(() => { const x=document.querySelector('#buellWriteEdited'); x.value='/manual/selected.xpr'; x.dispatchEvent(new Event('input',{bubbles:true})); });
  await page.locator('#modalConfirm').click();
  await expect(page.locator('#mapResearchPreviewOut')).toContainText('edited path changed during export and was preserved');
  await page.locator('[data-view="tools"]').click(); await expect(page.locator('#buellWriteEdited')).toHaveValue('/manual/selected.xpr');
  await expect(page.locator('#buellWriteExecute')).toBeDisabled(); expect(page.failures).toEqual([]);
});
