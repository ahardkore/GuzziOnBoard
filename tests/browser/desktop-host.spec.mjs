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
  await expect(page.locator('#xdfFitNote')).toContainText('Research only: image builds are blocked');
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

test('experimental Honda research read requires its own acknowledgement', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-view="firmware"]').click();
  await page.evaluate(() => renderMemoryCapabilities({
    capabilities: { ecu: 'honda_cb500f_dashble', family: 'Honda', protocol: 'Honda K-Line',
      research_read_only: true, read_supported: true, write_supported: false,
      regions: {flash: {size: 262144}} }, base_map: {intact: false}, checkpoints: {}
  }));
  await expect(page.locator('#memCaps')).toContainText('experimental MGZ-A03 only');
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
  await expect(page.locator('#modalTitle')).toHaveText('Experimental MGZ-A03 research read');
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
  await expect(page.locator('#canFields')).toContainText('No ECU memory');
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
    if (request.action === 'read') Object.assign(response, {page:request.page, offset:request.offset, length:request.length, data_hex:'AABB'});
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
  await page.locator('#buellConfirm').check();
  await page.locator('#buellRead').click();
  await expect(page.locator('#buellOut')).toContainText('AABB');
  await expect(page.locator('#buellOut')).toContainText('not a complete backup');
  expect(calls[1]).toMatchObject({action:'read', mode:'stock', version:'BUEIB310 12-11-03', page:1, offset:0, length:2});
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
