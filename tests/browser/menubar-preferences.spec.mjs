import { test, expect } from '@playwright/test';

test('top menu bar Quick Settings toggles Light/Dark mode, density, units, and opens Preferences', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await page.goto('/web/index.html');
  await expect(page.locator('#appMenubar')).toBeVisible();
  await expect(page.locator('#fileMenuBtn')).toBeVisible();
  await expect(page.locator('#quickSettingsBtn')).toBeVisible();

  // Open Quick Settings menu
  await page.locator('#quickSettingsBtn').click();
  await expect(page.locator('#quickSettingsMenu')).toBeVisible();

  // Switch to Light mode via Quick Settings
  await page.locator('#qsThemeLight').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await expect(page.locator('#menubarThemeLabel')).toHaveText('Light mode');

  // Switch density and temperature unit via Quick Settings
  await page.locator('#qsDensityCompact').click();
  await expect(page.locator('body')).toHaveAttribute('data-density', 'compact');
  await expect(page.locator('#layoutDensity')).toHaveValue('compact');

  await page.locator('#qsTempF').click();
  await expect(page.locator('#tempUnit')).toHaveValue('F');

  // Open Preferences modal from Quick Settings
  await page.locator('#openPreferencesBtn').click();
  await expect(page.locator('#quickSettingsMenu')).toBeHidden();
  await expect(page.locator('#prefsModal')).toBeVisible();
  await expect(page.locator('#prefThemeLight')).toBeChecked();

  // Persist and verify across reload
  await page.locator('#prefsSaveBtn').click();
  await expect(page.locator('#prefsModal')).toBeHidden();

  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await expect(page.locator('body')).toHaveAttribute('data-density', 'compact');
  await expect(page.locator('#tempUnit')).toHaveValue('F');

  // Check mobile viewport overflow in Light Mode
  await page.setViewportSize({ width: 375, height: 812 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});

test('Preferences modal manages Save and Load location presets and File menu applies them', async ({ page }) => {
  await page.goto('/web/index.html');

  // Open File -> Preferences
  await page.locator('#fileMenuBtn').click();
  await expect(page.locator('#fileMenu')).toBeVisible();
  await page.locator('#fileOpenPrefs').click();
  await expect(page.locator('#prefsModal')).toBeVisible();

  // Add a custom Save Location Preset
  await page.locator('[data-prefs-tab="save-presets"]').click();
  await page.locator('#prefSaveNameInput').fill('Dyno Room Reports');
  await page.locator('#prefSavePathInput').fill('/tmp/gob-dyno-saves');
  await page.locator('#prefSaveDescInput').fill('Bench dyno export folder');
  await page.locator('#prefAddSavePresetBtn').click();
  await expect(page.locator('#prefSavePresetsList')).toContainText('Dyno Room Reports');

  // Add a custom Load Location Preset
  await page.locator('[data-prefs-tab="load-presets"]').click();
  await page.locator('#prefLoadNameInput').fill('Race Calibrations');
  await page.locator('#prefLoadKindSelect').selectOption('images');
  await page.locator('#prefLoadPathInput').fill('/tmp/gob-race-maps');
  await page.locator('#prefAddLoadPresetBtn').click();
  await expect(page.locator('#prefLoadPresetsList')).toContainText('Race Calibrations');

  // Save Preferences
  await page.locator('#prefsSaveBtn').click();
  await expect(page.locator('#prefsModal')).toBeHidden();
  await expect(page.locator('#menubarPresetText')).toContainText('Save: Dyno Room Reports');
  await expect(page.locator('#menubarPresetText')).toContainText('Load: Race Calibrations');

  // File -> Insert Load Preset Path in Maps
  await page.locator('#fileMenuBtn').click();
  await page.locator('#fileApplyLoadPreset').click();
  await expect(page.locator('#firmware')).toBeVisible();
  await expect(page.locator('#mapsImagePath')).toHaveValue(/gob-race-maps\/$/);

  // File -> Browse Load Preset Folder
  await page.locator('#fileMenuBtn').click();
  await page.locator('#fileBrowseLoadPreset').click();
  await expect(page.locator('#presetBrowserModal')).toBeVisible();
  await expect(page.locator('#presetBrowserPathNote')).toContainText('gob-race-maps');
  await page.locator('#presetBrowserCloseBtn').click();
  await expect(page.locator('#presetBrowserModal')).toBeHidden();

  // Reset preferences back to clean defaults so shared servers stay tidy
  await page.locator('#menubarPresetSummary').click();
  await page.locator('[data-prefs-tab="workstation"]').click();
  await page.locator('#prefResetBtn').click();
  await page.locator('#prefsCloseX').click();
});

test('Tools and ECU Memory organizers filter panels cleanly and programmatic show("tools") loads gearing', async ({ page }) => {
  await page.goto('/web/index.html');

  // Navigate to Tools programmatically (regression test for show('tools') calling loadTools())
  await page.evaluate(() => show('tools'));
  await expect(page.locator('#tools')).toBeVisible();
  await expect.poll(async () => page.locator('#gearPreset option').count()).toBeGreaterThan(1);

  // Filter Tools by category and search query
  await expect(page.locator('#toolsCountBadge')).toHaveText('24 of 24 tools');
  await page.locator('[data-tool-filter="workshop"]').click();
  await expect(page.locator('#workshopManual')).toBeVisible();
  await expect(page.locator('#signalPanel')).toBeHidden();

  await page.locator('#toolsSearchInput').fill('gearing');
  await expect(page.locator('#toolsCountBadge')).toHaveText('1 of 24 tools');
  await page.locator('#toolsSearchClear').click();
  await expect(page.locator('#toolsCountBadge')).toHaveText('24 of 24 tools');

  // Filter ECU Memory workflow steps
  await page.locator('[data-view="firmware"]').click();
  await page.locator('[data-fw-filter="maps"]').click();
  await expect(page.locator('#mapsCard')).toBeVisible();
  await expect(page.locator('#backupPanel')).toBeHidden();
  await page.locator('[data-fw-filter="all"]').click();
  await expect(page.locator('#backupPanel')).toBeVisible();
});

test('File -> Exit Application confirms before exit and CSV/regex audit fixes hold', async ({ page }) => {
  await page.goto('/web/index.html');

  // Verify tuningTipsHtml ECU family regex fix (previously double-escaped \\b)
  const tipText = await page.evaluate(() => tuningTipsHtml({
    xdf: { title: 'IAW 5AM V11 Sport' },
    tables: [{ title: 'Checksum Zone', rows: 1, cols: 1 }],
  }));
  expect(tipText).toContain('5AM definition:');
  expect(tipText).not.toContain('this ECU definition:');

  // Verify RFC 4180 CSV escaping helper
  const escaped = await page.evaluate(() => [
    csvEscapeCell('plain'),
    csvEscapeCell('deg, C'),
    csvEscapeCell('say "hi"'),
  ]);
  expect(escaped).toEqual(['plain', '"deg, C"', '"say ""hi"""']);

  // Intercept desktop quit route if running against the shared desktop test server
  let quitRequested = false;
  await page.route('**/api/desktop/quit', async (route) => {
    quitRequested = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, note: 'Closing GuzziOnBoard.' }),
    });
  });

  // File -> Exit Application with Cancel, then Confirm
  await page.locator('#fileMenuBtn').click();
  await page.locator('#fileExitApp').click();
  await expect(page.locator('#modal')).toBeVisible();
  await page.locator('#modalCancel').click();
  await expect(page.locator('#appExitedOverlay')).toBeHidden();
  expect(quitRequested).toBe(false);

  await page.locator('#fileMenuBtn').click();
  await page.locator('#fileExitApp').click();
  await page.locator('#modalConfirm').click();
  await expect(page.locator('#appExitedOverlay')).toBeVisible();
  const isDesktop = await page.evaluate(() => Boolean(window.gobDesktop?.available));
  if (isDesktop) expect(quitRequested).toBe(true);
  await page.locator('#appResumeBtn').click();
  await expect(page.locator('#appExitedOverlay')).toBeHidden();
});
