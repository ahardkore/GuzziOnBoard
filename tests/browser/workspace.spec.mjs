import { test, expect } from '@playwright/test';

test('layout preference survives reload and navigation labels are complete', async ({ page }) => {
  await page.goto('/web/index.html');
  await page.locator('#layoutDensity').selectOption('compact');
  await expect(page.locator('body')).toHaveAttribute('data-density', 'compact');
  await page.reload();
  await expect(page.locator('#layoutDensity')).toHaveValue('compact');
  await page.locator('[data-view="tools"]').click();
  await expect(page.locator('#pageTitle')).toHaveText('Tools');
  await page.locator('[data-view="firmware"]').click();
  await expect(page.locator('#pageTitle')).toHaveText('ECU memory');
});

test('timeline uses only current-session data, shows gaps and keeps independent scales', async ({ page }) => {
  await page.goto('/web/index.html');
  await page.evaluate(() => {
    state.plotEpoch = 8;
    state.parameters = [{ key: 'rpm', name: 'Engine speed' }, { key: 'temp', name: 'Temperature' }];
    state.selectedChannels = new Set(['rpm', 'temp']);
    state.plotChannels = new Set(['rpm', 'temp']);
    const sample = (value, unit) => ({ value, unit });
    state.liveLog = [
      { plotEpoch: 7, t: 0, values: { rpm: sample(99999, 'rpm') } },
      { plotEpoch: 8, t: 1, values: { rpm: sample(1000, 'rpm'), temp: sample(20, '°C') } },
      { plotEpoch: 8, t: 2, values: { temp: sample(22, '°C') } },
      { plotEpoch: 8, t: 3, values: { rpm: sample(1200, 'rpm'), temp: { error: 'no answer' } } },
      { plotEpoch: 8, t: 4, values: { rpm: sample(1400, 'rpm'), temp: sample(24, '°C') } },
    ];
    renderPlotChannels();
    show('live');
  });
  const lanes = page.locator('#livePlot .plot-lane');
  await expect(lanes).toHaveCount(2);
  await expect(lanes.nth(0)).toContainText('MIN 1000 · MAX 1400 · LAST 1400 rpm · 3 samples');
  await expect(lanes.nth(0).locator('circle')).toHaveCount(1);
  await expect(lanes.nth(0).locator('.plot-line')).toHaveCount(1);
  await expect(lanes.nth(1)).toContainText('MIN 20 · MAX 24');
  await expect(page.locator('#livePlot')).not.toContainText('99999');
  await expect(page.locator('#livePlot')).toContainText('4 sweeps');
  await page.locator('#plotChannels input[value="rpm"]').uncheck();
  await expect(page.locator('#livePlot .plot-lane')).toHaveCount(1);
  const polled = await page.evaluate(() => [...state.selectedChannels]);
  expect(polled).toEqual(['rpm', 'temp']);
});

test('timeline refuses to join changed units and handles a backwards clock', async ({ page }) => {
  await page.goto('/web/index.html');
  await page.evaluate(() => {
    state.plotEpoch = 1;
    state.parameters = [{ key: 'x', name: 'Test' }];
    state.plotChannels = new Set(['x']);
    state.liveLog = [
      { plotEpoch: 1, t: 2, values: { x: { value: 4, unit: 'V' } } },
      { plotEpoch: 1, t: 1, values: { x: { value: 5, unit: 'V' } } },
    ];
    show('live');
  });
  await expect(page.locator('#livePlot')).toContainText('clock moved backwards');
  await expect(page.locator('#livePlot circle')).toHaveCount(2);
  await page.evaluate(() => { state.liveLog[1].values.x.unit = 'mV'; renderLivePlot(); });
  await expect(page.locator('#livePlot')).toContainText('Inconsistent units');
  await expect(page.locator('#livePlot .plot-svg')).toHaveCount(0);
});

test('timeline breaks across polling restarts and temperature display changes immediately', async ({ page }) => {
  await page.goto('/web/index.html');
  await page.evaluate(() => {
    state.plotEpoch = 2;
    state.parameters = [{ key: 'temp', name: 'Temperature' }];
    state.plotChannels = new Set(['temp']);
    state.liveLog = [
      { plotEpoch: 2, plotRun: 1, t: 1, values: { temp: { value: 20, unit: '°C' } } },
      { plotEpoch: 2, plotRun: 3, t: 20, values: { temp: { value: 25, unit: '°C' } } },
    ];
    show('live');
  });
  await expect(page.locator('#livePlot circle')).toHaveCount(2);
  await expect(page.locator('#livePlot .plot-line')).toHaveCount(0);
  await page.locator('#tempUnit').selectOption('F');
  await expect(page.locator('#livePlot')).toContainText('MIN 68 · MAX 77 · LAST 77 °F');
});

test('a late polling response from an old connection is ignored', async ({ page }) => {
  await page.goto('/web/index.html');
  const result = await page.evaluate(async () => {
    state.plotEpoch = 1; state.plotRun = 1; state.polling = true;
    state.selectedChannels = new Set(['rpm']);
    const previousFetch = window.fetch;
    let resolveFetch;
    window.fetch = () => new Promise((resolve) => { resolveFetch = resolve; });
    const pending = pollOnce();
    state.plotEpoch = 2; state.plotRun = 2;
    resolveFetch(new Response(JSON.stringify({ at: 1, samples: [{ key: 'rpm', value: 123 }], derived: [], findings: [] }), { status: 200 }));
    await pending;
    window.fetch = previousFetch;
    state.polling = false;
    return state.liveLog.length;
  });
  expect(result).toBe(0);
});

test('workspace fits a narrow screen without hiding navigation', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/web/index.html');
  await expect(page.locator('[data-view="live"]')).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test('optional Ducati decoder is opt-in, passive and rejects unrelated frames', async ({ page }) => {
  await page.goto('/web/index.html');
  const capture = [
    '(1.0) can0 080#0000000055123400',
    '(2.0) can0 018#0000000065B00000',
    '(3.0) can0 100#0000001E7B280000',
    '(4.0) can0 00000080#0000000055123400',
    '(5.0) can0 080#00000000',
    '6.0 T11 080 00 00 00 00 55 12 34 00',
  ].join('\n');
  const answer = await page.evaluate(async (text) => {
    const request = (body) => fetch('/api/tools/canlog', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then((r) => r.json());
    return { none: await request({ text }), decoded: await request({ text, decoder: 'ducati_panigale_mitsubishi' }) };
  }, capture);
  expect(answer.none.decoder).toBeUndefined();
  const result = answer.decoded.decoder;
  expect(result.recognized_frames).toBe(3);
  expect(result.invalid_length_frames).toBe(1);
  expect(result.ignored_tx_frames).toBe(1);
  expect(result.events.map((e) => e.values)).toEqual([
    { throttle_percent: 42, rpm: 4660 },
    { rear_wheel_speed_kmh: 91, gear_raw: 3 },
    { coolant_c: -10, air_c: 0, battery_v: 12.3 },
  ]);
  await page.locator('[data-view="discovery"]').click();
  await page.locator('#canlogText').locator('..').locator('summary').click();
  await page.locator('#canlogText').fill(capture);
  await page.locator('#canlogDecoder').selectOption('ducati_panigale_mitsubishi');
  await page.locator('#canlogPasteBtn').click();
  await expect(page.locator('#canlogOut')).toContainText('Not vehicle identification or a Guzzi profile');
  await expect(page.locator('#canlogOut')).toContainText('rpm: 4660');
});

test('manual shim worksheet requires a confirmed direction and reports arithmetic only', async ({ page }) => {
  await page.goto('/web/index.html');
  await page.locator('[data-view="tools"]').click();
  await page.locator('#shimMeasured').fill('0.300');
  await page.locator('#shimCurrent').fill('2.500');
  await page.locator('#shimMin').fill('0.100');
  await page.locator('#shimMax').fill('0.200');
  await page.locator('#shimCandidates').fill('2.60, 2.65, 2.70');
  await page.locator('#shimCalcBtn').click();
  await expect(page.locator('#shimOut')).toContainText('Confirm how a thicker shim affects clearance');
  await page.locator('#shimDirection').selectOption('decrease');
  await page.locator('#shimCalcBtn').click();
  await expect(page.locator('#shimOut')).toContainText('calculated exact shim: 2.6500 mm');
  await expect(page.locator('#shimOut')).toContainText('0.1500');
  await page.locator('#shimDirection').selectOption('increase');
  await page.locator('#shimCalcBtn').click();
  await expect(page.locator('#shimOut')).toContainText('calculated exact shim: 2.3500 mm');
  await page.locator('#shimMin').fill('0.300');
  await page.locator('#shimCalcBtn').click();
  await expect(page.locator('#shimOut')).toContainText('Target minimum cannot exceed the maximum');
  const rejection = await page.evaluate(() => {
    try { calculateShimWorksheet('0.1001', '2.5', '0.1', '0.2', 'decrease', ''); return false; } catch (_) { return true; }
  });
  expect(rejection).toBe(true);
});

test('passive CAN byte statistics require filtering and report observations only', async ({ page }) => {
  await page.goto('/web/index.html');
  const capture = ['1.0 R11 567 00 01', '2.0 R11 567 03 01', '3.0 R11 567 01',
    '4.0 R11 567 01 81', '5.0 T11 567 FF 10', '6.0 R29 567 FF 20'].join('\n');
  const result = await page.evaluate(async (text) => {
    const request = (body) => fetch('/api/tools/canlog', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(async (response) => ({ status: response.status, body: await response.json() }));
    return { missing: await request({ text, byte_stats: true }), ok: await request({ text, byte_stats: true, filter_ids: '567' }) };
  }, capture);
  expect(result.missing.status).toBe(400);
  expect(result.ok.body.byte_stats.groups).toHaveLength(3);
  expect(result.ok.body.byte_stats.groups[0].bytes).toEqual([
    { index: 1, samples: 4, minimum: 0, maximum: 3, changes: 2, varying_mask: 3 },
    { index: 2, samples: 3, minimum: 1, maximum: 129, changes: 1, varying_mask: 128 },
  ]);
  await page.locator('[data-view="discovery"]').click();
  await page.locator('#canlogText').locator('..').locator('summary').click();
  await page.locator('#canlogText').fill(capture);
  await page.locator('#canlogFilter').fill('567');
  await page.locator('#canlogByteStats').check();
  await page.locator('#canlogPasteBtn').click();
  await expect(page.locator('#canlogOut')).toContainText('Raw byte observations');
  await expect(page.locator('#canlogOut')).toContainText('not a signal definition or vehicle identification');
  await expect(page.locator('#canlogOut')).toContainText('0x80');
});
