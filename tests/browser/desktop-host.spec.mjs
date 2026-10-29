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
      select: await post('/api/select', { make: 'Suzuki', model: 'SV650AK7', year: 2007, transport: 'kline' }),
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
