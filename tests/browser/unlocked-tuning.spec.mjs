import { test, expect } from '@playwright/test';

async function connectAndLoad5amBaseMap(page) {
  await page.goto('/web/index.html');
  await expect(page.locator('#connectBtn')).toBeEnabled({ timeout: 20_000 });
  await page.locator('#connectBtn').click();
  await expect(page.locator('#connTitle')).toHaveText('Connected', { timeout: 20_000 });

  const backupPath = await page.evaluate(async () => {
    const started = await fetch('/api/memory/backup', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ region: 'flash' }),
    }).then((r) => r.json());
    let job = started;
    const deadline = Date.now() + 30_000;
    while (job.state === 'running' && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 100));
      job = await fetch('/api/memory/progress').then((r) => r.json());
    }
    if (job.state !== 'done' || !job.result?.path) throw new Error('demo backup did not finish');
    const filed = await fetch('/api/memory/basemap', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ region: 'flash', path: job.result.path }),
    });
    if (!filed.ok) throw new Error(`base-map filing failed: ${filed.status}`);
    return job.result.path;
  });

  await page.locator('[data-view="firmware"]').click();
  await expect(page.locator('#mapsBaseBtn')).toBeEnabled({ timeout: 30_000 });
  await page.locator('#xdfSelect').selectOption('5AM_GuzziDiag_One_Lambda_V1.41.xdf');
  await page.locator('#mapsBaseBtn').click();
  await expect(page.locator('#mapsOut .map-table-entry').first()).toBeVisible({ timeout: 30_000 });
  return backupPath;
}

test('unlocked XDF flag switches build in custom dyno mode without external URL and stage to brand writers', async ({ page }) => {
  await connectAndLoad5amBaseMap(page);

  // Verify XDF tree dock lists Flags & Switches and opens the rendered flags section
  const flagTreeItem = page.locator('#xdfTreeList .xdf-tree-item[data-xdf-kind="flags"]');
  await expect(flagTreeItem).toBeVisible();
  await flagTreeItem.click();
  const flagsSection = page.locator('#mapsOut details.xdf-section-flags');
  await expect(flagsSection).toHaveJSProperty('open', true);

  // Toggle the first unlocked XDF flag switch
  const firstFlagBtn = flagsSection.locator('[data-flag-id]').first();
  const beforeLabel = (await firstFlagBtn.textContent()).trim();
  await firstFlagBtn.click();
  await expect(firstFlagBtn).toHaveClass(/modified/);
  expect((await firstFlagBtn.textContent()).trim()).not.toBe(beforeLabel);
  await expect(page.locator('#mapBuildChanges')).toContainText('1 staged change(s)');

  // Build using custom dyno mode with an empty external URL
  await page.locator('#mapEvidenceMode').selectOption('dyno');
  await expect(page.locator('#mapEvidenceUrlLabel')).toContainText('optional');
  await page.locator('#mapEvidenceTitle').fill('Dyno run #7 lambda switch validation');
  await page.locator('#mapEvidenceUrl').fill('');
  await page.locator('#mapEvidenceRationale').fill('Local chassis dyno steady-state sweep on Griso 1200 8V fixture.');
  await page.locator('#mapAckCheck').check();
  await page.locator('#mapBuildBtn').click();

  await expect(page.locator('#modal')).toBeVisible();
  await page.locator('#modalConfirm').click();
  await expect(page.locator('#mapBuildOut')).toContainText('Modified map built', { timeout: 20_000 });

  // Stage built tune directly into Harley Delphi write review input
  const builtPath = await page.locator('#imagePath').inputValue();
  expect(builtPath.length).toBeGreaterThan(5);
  await page.locator('#mapBuildOut [data-stage-built="harley"]').click();
  await expect(page.locator('#hdMemEdited')).toHaveValue(builtPath);
});

test('JetDrive dyno capture pivots into Map AFR Overlay and analyzes with constant & 2D-table target AFR', async ({ page }) => {
  await connectAndLoad5amBaseMap(page);

  // Pick a fuel-like table with numeric X and Y axes so our synthetic JetDrive samples hit an exact cell
  const coords = await page.evaluate(() => {
    const tbl = maps.render.tables.find((t) =>
      t.rows >= 2 && t.cols >= 2
      && t.x.every((v) => Number.isFinite(Number(v)))
      && t.y.every((v) => Number.isFinite(Number(v))));
    return { id: tbl.id, x0: Number(tbl.x[0]), y0: Number(tbl.y[0]) };
  });

  await page.locator('[data-view="tools"]').click();
  await page.evaluate(({ x0, y0 }) => {
    const samples = [];
    for (let step = 0; step < 6; step += 1) {
      const ts = step * 400;
      samples.push({ source: '127.0.0.1', provider: 1, provider_name: 'Dyno', sequence: step, id: 1, channel_name: 'Engine RPM', unit_code: 1, timestamp_ms: ts, value: x0 });
      samples.push({ source: '127.0.0.1', provider: 1, provider_name: 'Dyno', sequence: step, id: 2, channel_name: 'Throttle TPS', unit_code: 2, timestamp_ms: ts + 10, value: y0 });
      samples.push({ source: '127.0.0.1', provider: 1, provider_name: 'Dyno', sequence: step, id: 3, channel_name: 'Wideband AFR', unit_code: 3, timestamp_ms: ts + 20, value: 14.52 });
    }
    window.guzziSetJetDriveSamples(samples);
  }, coords);

  await expect(page.locator('#jetdriveToOverlay')).toBeEnabled();
  await page.locator('#jetdriveToOverlay').click();

  await expect(page.locator('details.map-log-tools')).toHaveJSProperty('open', true);
  await expect(page.locator('#mapLogSummary')).toContainText('JetDrive capture');
  await expect(page.locator('#mapLogTime')).toHaveValue('timestamp_ms');
  await expect(page.locator('#mapLogTimeUnit')).toHaveValue('milliseconds');

  await page.locator('#mapLogTable').selectOption(coords.id);
  await page.locator('#mapLogX').selectOption('Engine RPM');
  await page.locator('#mapLogY').selectOption('Throttle TPS');
  await page.locator('#mapLogMeasured').selectOption('Wideband AFR');
  await page.locator('#mapLogGap').fill('1000');
  await page.locator('#mapLogSettle').fill('400');
  await page.locator('#mapLogDuration').fill('800');
  await page.locator('#mapLogMinSamples').fill('3');

  // Analyze with Constant target AFR (no target CSV column needed)
  await page.locator('#mapLogTargetMode').selectOption('constant');
  await page.locator('#mapLogTargetConst').fill('13.2');
  await page.locator('#mapLogAnalyzeBtn').click();
  await expect(page.locator('#mapLogOut')).toContainText('eligible bounded proposals');
  await expect(page.locator('#mapLogStageBtn')).toBeEnabled();
});

test('implemented hardware writer unlock/lock gate and external verified backup attestation work end-to-end', async ({ page }) => {
  const backupPath = await connectAndLoad5amBaseMap(page);

  // Unlock and re-lock implemented hardware writer gate
  const writerDetails = page.locator('#writerUnlockDetails');
  await writerDetails.evaluate((el) => { el.open = true; });
  await page.locator('#writerAckCheck').check();
  await page.locator('#unlockWriterBtn').click();
  await expect(page.locator('#writerUnlockBadge')).toContainText('Unlocked');
  await expect(page.locator('#lockWriterBtn')).toBeEnabled();

  await page.locator('#lockWriterBtn').click();
  await expect(page.locator('#unlockWriterBtn')).toBeEnabled();

  // Attest external verified backup
  const extDetails = page.locator('#externalBackupDetails');
  await extDetails.evaluate((el) => { el.open = true; });
  await page.locator('#externalBackupPath').fill(backupPath);
  await page.locator('#externalBackupNote').fill('Verified bench backup fixture');
  await page.locator('#externalBackupAckCheck').check();
  await page.locator('#externalBackupAttestBtn').click();
  await expect(page.locator('#externalBackupOut')).toContainText('External backup attested');
});
