import { test, expect } from '@playwright/test';

async function openEditor(page) {
  await page.goto('/web/index.html');
  await expect(page.locator('#connectBtn')).toBeEnabled({ timeout: 20_000 });
  await page.locator('#connectBtn').click();
  await expect(page.locator('#connTitle')).toHaveText('Connected', { timeout: 20_000 });

  // A protected base map is intentionally unavailable until a verified
  // two-pass backup exists. Exercise that browser-side job and file the result
  // rather than injecting editor state.
  await page.evaluate(async () => {
    const started = await fetch('/api/memory/backup', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ region: 'flash' }),
    }).then((response) => response.json());
    let job = started;
    const deadline = Date.now() + 30_000;
    while (job.state === 'running' && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 100));
      job = await fetch('/api/memory/progress').then((response) => response.json());
    }
    if (job.state !== 'done' || !job.result?.path) throw new Error('demo backup did not finish');
    const filed = await fetch('/api/memory/basemap', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ region: 'flash', path: job.result.path }),
    });
    if (!filed.ok) throw new Error(`base-map filing failed: ${filed.status}`);
  });
  await page.locator('[data-view="firmware"]').click();
  await expect(page.locator('#mapsBaseBtn')).toBeEnabled({ timeout: 30_000 });
  const smallerDefinition = page.locator('#xdfSelect option[value="5AM_GuzziDiag_One_Lambda_V1.41.xdf"]');
  if (await smallerDefinition.count()) {
    await page.locator('#xdfSelect').selectOption('5AM_GuzziDiag_One_Lambda_V1.41.xdf');
  }

  // The bundled community XDFs use static axis labels. For the axis-editor DOM
  // path, promote numeric labels in this test response to an image-backed test
  // fixture; production still trusts only the XDF's `editable` declaration.
  await page.evaluate(() => {
    const applicationFetch = window.fetch;
    window.fetch = async (...args) => {
      const response = await applicationFetch(...args);
      const target = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
      const method = String(args[1]?.method || 'GET').toUpperCase();
      if (!target.includes('/api/maps/render') || method !== 'POST' || !response.ok) return response;
      const payload = await response.json();
      (payload.tables || []).forEach((table) => {
        for (const axisName of ['x', 'y']) {
          const axis = table.axes?.[axisName];
          const values = (axis?.values || []).map(Number);
          if (!axis || values.some((value) => !Number.isFinite(value))) continue;
          Object.assign(axis, {
            editable: true, raw_values: [...values], equation: 'X',
            address: 'browser-test-fixture', size_bits: 32, signed: true,
          });
        }
      });
      return new Response(JSON.stringify(payload), {
        status: response.status, statusText: response.statusText,
        headers: { 'Content-Type': 'application/json' },
      });
    };
  });
  await page.locator('#mapsBaseBtn').click();
  await expect(page.locator('#mapsOut .map-grid').first()).toBeVisible({ timeout: 30_000 });
}

async function editableTable(page, minimumRows = 3, minimumCols = 3) {
  return page.evaluate(({ rows, cols }) => {
    const table = maps.render.tables.find((candidate) =>
      candidate.rows >= rows && candidate.cols >= cols
      && candidate.x.every((value) => Number.isFinite(Number(value)))
      && candidate.y.every((value) => Number.isFinite(Number(value))));
    return table ? { id: table.id, rows: table.rows, cols: table.cols } : null;
  }, { rows: minimumRows, cols: minimumCols });
}

function tableCell(page, table, row, col) {
  return page.locator(`[data-map-kind="table"][data-map-id="${table.id}"][data-map-row="${row}"][data-map-col="${col}"]`);
}

async function selectRectangle(page, table, row0, col0, row1, col1) {
  await tableCell(page, table, row0, col0).click();
  await tableCell(page, table, row1, col1).click({ modifiers: ['Shift'] });
}

async function confirmNumericOperation(page, button, input, value) {
  await page.locator(button).click();
  await expect(page.locator('#modal')).toBeVisible();
  await page.locator(input).fill(String(value));
  await page.locator('#modalConfirm').click();
  await expect(page.locator('#modal')).toBeHidden();
}

test('DOM editor supports rectangular transforms, keyboard editing, axes, heat maps, 2D/3D, undo and redo', async ({ page }) => {
  await openEditor(page);
  const table = await editableTable(page);
  expect(table).not.toBeNull();

  const tableDetails = page.locator('#mapsOut details').filter({
    has: page.locator(`[data-map-kind="table"][data-map-id="${table.id}"]`),
  }).first();
  await expect(tableDetails.locator('.map-viz')).toHaveCount(2);
  await expect(tableCell(page, table, 0, 0)).toHaveAttribute('style', /--map-heat:/);

  await selectRectangle(page, table, 0, 0, 1, 2);
  await expect(page.locator(`[data-map-id="${table.id}"].selected`)).toHaveCount(6);

  await confirmNumericOperation(page, '#mapPercentBtn', '#mapTransformValue', 10);
  await expect(page.locator(`[data-map-id="${table.id}"].modified`)).toHaveCount(6);
  const percentValue = await tableCell(page, table, 0, 0).getAttribute('data-map-value');

  await confirmNumericOperation(page, '#mapAddBtn', '#mapTransformValue', 1);
  const additiveValue = await tableCell(page, table, 0, 0).getAttribute('data-map-value');
  expect(Number(additiveValue)).toBeCloseTo(Number(percentValue) + 1, 8);

  await page.locator('#mapUndoBtn').click();
  await expect(tableCell(page, table, 0, 0)).toHaveAttribute('data-map-value', percentValue);
  await page.locator('#mapRedoBtn').click();
  await expect(tableCell(page, table, 0, 0)).toHaveAttribute('data-map-value', additiveValue);

  await tableCell(page, table, 0, 0).click();
  await page.keyboard.press('Shift+ArrowRight');
  await expect(page.locator(`[data-map-id="${table.id}"].selected`)).toHaveCount(2);
  await expect(tableCell(page, table, 0, 1)).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#mapEditValue')).toBeVisible();
  await page.locator('#modalCancel').click();

  const editableAxis = page.locator('[data-map-kind="axis"]').first();
  await expect(editableAxis).toBeVisible();
  const originalAxis = Number(await editableAxis.getAttribute('data-map-value'));
  await editableAxis.focus();
  await page.keyboard.press('Enter');
  await page.locator('#mapEditValue').fill(String(originalAxis + 0.001));
  await page.locator('#modalConfirm').click();
  await expect(editableAxis).toHaveClass(/modified/);
});

test('DOM editor pastes, copies, interpolates, smooths, blends and round-trips a saved project', async ({ page }) => {
  await openEditor(page);
  const table = await editableTable(page);
  expect(table).not.toBeNull();
  await selectRectangle(page, table, 0, 0, 2, 2);
  const pasted = [];
  for (let row = 0; row < 3; row += 1) {
    const values = [];
    for (let col = 0; col < 3; col += 1) {
      const original = Number(await tableCell(page, table, row, col).getAttribute('data-map-value'));
      values.push(original + 1000 + (col === 1 ? 100 + row * 17 : row * 10 + col));
    }
    pasted.push(values);
  }

  await page.locator('#mapPasteBtn').click();
  await expect(page.locator('#mapPasteValues')).toBeVisible();
  await page.locator('#mapPasteValues').fill(pasted.map((row) => row.join('\t')).join('\n'));
  await page.locator('#modalConfirm').click();
  await expect(page.locator(`[data-map-id="${table.id}"].modified`)).toHaveCount(9);

  await page.locator('#mapCopyBtn').click();
  await expect(page.locator('#toast')).toContainText(/copied|TSV/i);
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied.split('\n')).toHaveLength(3);

  await page.locator('#mapInterpolateRowsBtn').click();
  for (let row = 0; row < 3; row += 1) {
    const interpolated = Number(await tableCell(page, table, row, 1).getAttribute('data-map-value'));
    expect(interpolated).toBeCloseTo((pasted[row][0] + pasted[row][2]) / 2, 8);
  }

  await confirmNumericOperation(page, '#mapSmoothBtn', '#mapSmoothStrength', 50);
  await confirmNumericOperation(page, '#mapBlendBtn', '#mapBlendStrength', 100);
  await expect(page.locator(`[data-map-id="${table.id}"].modified`)).toHaveCount(9);

  const downloadPromise = page.waitForEvent('download');
  await page.locator('#mapExportProjectBtn').click();
  const download = await downloadPromise;
  const projectPath = await download.path();
  expect(projectPath).toBeTruthy();

  await page.locator('#mapClearChangesBtn').click();
  await expect(page.locator('.map-value.modified')).toHaveCount(0);
  await page.locator('#mapProjectFile').setInputFiles(projectPath);
  await expect(page.locator(`[data-map-id="${table.id}"].modified`)).toHaveCount(9);
  await expect(page.locator('#mapBuildChanges')).toContainText('staged change');
});

test('explicit live-channel mapping replaces guessing and time-aware log analysis runs through the UI', async ({ page }) => {
  await openEditor(page, { connect: true });
  const table = await editableTable(page);
  expect(table).not.toBeNull();

  await page.locator('[data-view="live"]').click();
  await page.locator('#pollBtn').click();
  await expect(page.locator('#liveGrid .metric').first()).toBeVisible({ timeout: 15_000 });
  await page.locator('#pollBtn').click();
  await page.locator('[data-view="firmware"]').click();
  await expect(page.locator('.map-value.live-trace')).toHaveCount(0);
  await expect(page.locator('#mapLiveTraceStatus')).toContainText('No explicit live-trace mappings');

  const axes = await page.evaluate((tableId) => {
    const table = maps.render.tables.find((candidate) => candidate.id === tableId);
    return {
      x: table.x.map(Number), y: table.y.map(Number),
    };
  }, table.id);
  const xCenter = (Math.min(...axes.x) + Math.max(...axes.x)) / 2;
  const yCenter = (Math.min(...axes.y) + Math.max(...axes.y)) / 2;
  const live = await page.evaluate(() => Object.fromEntries(
    state.lastSamples.map((sample) => [sample.key, Number(sample.value)]),
  ));
  const mapping = page.locator(`[data-trace-table="${table.id}"]`);
  await mapping.locator('summary').click();
  await mapping.locator('[data-trace-channel="x"]').selectOption('rpm');
  await mapping.locator('[data-trace-channel="y"]').selectOption('throttle');
  await mapping.locator('[data-trace-scale="x"]').fill('1');
  await mapping.locator('[data-trace-offset="x"]').fill(String(xCenter - live.rpm));
  await mapping.locator('[data-trace-scale="y"]').fill('1');
  await mapping.locator('[data-trace-offset="y"]').fill(String(yCenter - live.throttle));
  await mapping.locator('[data-trace-save]').click();
  await expect(page.locator(`[data-trace-table="${table.id}"] summary`)).toContainText('explicitly mapped');
  await expect(page.locator('.map-value.live-trace')).toHaveCount(1);
  await expect(page.locator('#mapLiveTraceStatus')).toContainText('explicit live trace');
  await expect(page.locator('#mapLiveTraceStatus')).toContainText('interpolation');
  const interpolationWeight = await page.locator('.map-value.live-trace-weight')
    .evaluateAll((cells) => cells.reduce((sum, cell) => sum + Number(cell.dataset.traceWeight), 0));
  expect(interpolationWeight).toBeCloseTo(1, 5);

  await page.locator('.map-log-tools > summary').click();
  const csvRows = ['Time,RPM,Load,Measured AFR,Target AFR'];
  for (let index = 0; index < 10; index += 1) {
    csvRows.push(`${(index * 0.25).toFixed(2)},${axes.x[0]},${axes.y[0]},15,14`);
  }
  await page.locator('#mapLogFile').setInputFiles({
    name: 'steady-time-aware.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(csvRows.join('\n')),
  });
  await page.locator('#mapLogTable').selectOption(table.id);
  await expect(page.locator('#mapLogTime')).toHaveValue('Time');
  await page.locator('#mapLogMinSamples').fill('3');
  await page.locator('#mapLogAnalyzeBtn').click();
  await expect(page.locator('#mapLogOut')).toContainText('linearly interpolated x/y/target', { timeout: 15_000 });
  await expect(page.locator('#mapLogOut')).toContainText('eligible bounded proposals');
  await expect(page.locator('#mapLogOut')).toContainText('transient');

  await page.locator(`[data-trace-table="${table.id}"] summary`).click();
  await page.locator(`[data-trace-table="${table.id}"] [data-trace-clear]`).click();
  await expect(page.locator('.map-value.live-trace')).toHaveCount(0);
  await expect(page.locator('#mapLiveTraceStatus')).toContainText('No explicit live-trace mappings');

  await page.locator('[data-view="live"]').click();
  if (await page.locator('#pollBtn').getAttribute('class').then((value) => value.includes('danger'))) {
    await page.locator('#pollBtn').click();
  }
});
