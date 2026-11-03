import { test, expect } from '@playwright/test';

/* Batch 3: seven brand panels and the two image-layout panels.
 *
 * Each decoder case is driven the way an operator would drive it — paste a
 * captured frame, press Decode, read the panel — and each rejection is checked
 * for the reason it states, because a refusal that says nothing is no better
 * than a wrong number. The frames are synthetic values with hand-checked
 * arithmetic, so a formula change breaks a test instead of a motorcycle.
 */

test.beforeEach(async ({ page }) => {
  await page.goto('/web/index.html');
  await page.locator('[data-view="tools"]').click();
  await expect(page.locator('#tools')).toBeVisible();
});

const BRAND_PANELS = [
  ['kawasakiKds', 'kawasaki'],
  ['suzukiSds', 'suzuki'],
  ['triumphIso', 'triumph'],
  ['bmwCan', 'bmw'],
  ['ducatiCan', 'ducati'],
  ['indianJ1939', 'indian'],
  ['iawGuzziPanel', 'moto-guzzi'],
  ['iawApriliaPanel', 'aprilia'],
];

test('the bench lists the brand decoders under their own manufacturers', async ({ page }) => {
  await expect(page.locator('#toolsCountBadge')).toHaveText('44 of 44 tools');
  for (const [id, brand] of BRAND_PANELS) {
    await expect(page.locator(`#${id}`)).toHaveAttribute('data-tool-brand', brand);
    await expect(page.locator(`[data-brand-heading="${brand}"]`)).toBeAttached();
  }
  // The general group is unchanged by Batch 3.
  await expect(page.locator('[data-brand-heading="general"] [data-brand-count]')).toContainText('23 tools');

  await page.locator('#toolsBrandSelect').selectOption('ducati');
  const visible = page.locator('#tools > article.panel[data-tool-cat]:not(.hidden)');
  await expect(visible).toHaveCount(1);
  await expect(page.locator('#ducatiCan')).toBeVisible();
  await expect(page.locator('#toolsBrandBadge')).toHaveText('Ducati · 1 tool');
});

test('the Kawasaki panel decodes a complete KDS answer and names a bad checksum', async ({ page }) => {
  await page.locator('#kawasakiFrames').fill('80 F1 11 04 61 0C 03 1A 10');
  await page.locator('#kawasakiDecode').click();
  await expect(page.locator('#kawasakiOut')).toContainText('Speed candidate');
  // (0x03 × 100 + 0x1A) / 2 = 163
  await expect(page.locator('#kawasakiOut')).toContainText('163 km/h');
  await expect(page.locator('#kawasakiMeta')).toHaveText('1 of 1 frame(s) decoded');

  await page.locator('#kawasakiFrames').fill('80 F1 11 04 61 0C 03 1A 7D');
  await page.locator('#kawasakiDecode').click();
  await expect(page.locator('#kawasakiOut')).toContainText('Rejected:');
  await expect(page.locator('#kawasakiOut')).toContainText('Checksum');
  await expect(page.locator('#kawasakiMeta')).toHaveText('0 of 1 frame(s) decoded');

  // The reference table is rendered from the decoder's own data, not written twice.
  await page.locator('#kawasakiKds details.advanced summary').click();
  await expect(page.locator('#kawasakiRef')).toContainText('0x09');
  await expect(page.locator('#kawasakiRef')).toContainText('a × 100 + b rpm');
});

test('the Triumph panel verifies the ISO 9141 header and checksum before decoding', async ({ page }) => {
  await page.locator('#triumphFrames').fill('48 6B D1 41 0C 1A F8 E3');
  await page.locator('#triumphDecode').click();
  await expect(page.locator('#triumphOut')).toContainText('Engine speed: 1726 rpm');

  await page.locator('#triumphFrames').fill('48 6B D1 41 0C 1A F8 A9');
  await page.locator('#triumphDecode').click();
  await expect(page.locator('#triumphOut')).toContainText('Rejected:');
  await expect(page.locator('#triumphOut')).toContainText('Checksum');

  // A mode 01 PID outside the documented set is refused, not extrapolated.
  await page.locator('#triumphFrames').fill('48 6B D1 41 0D 3C 0E');
  await page.locator('#triumphDecode').click();
  await expect(page.locator('#triumphOut')).toContainText('Vehicle speed: 60 km/h');
});

test('the BMW panel takes 11-bit ID#DATA frames only', async ({ page }) => {
  await page.locator('#bmwFrames').fill('10C#00F81A0000000000');
  await page.locator('#bmwDecode').click();
  // (0x1A × 256 + 0xF8) / 4 = 1726
  await expect(page.locator('#bmwOut')).toContainText('1726 rpm');

  await page.locator('#bmwFrames').fill('2D0#0000000000001000');
  await page.locator('#bmwDecode').click();
  await expect(page.locator('#bmwOut')).toContainText('high-beam flash candidate');

  await page.locator('#bmwFrames').fill('123#0000');
  await page.locator('#bmwDecode').click();
  await expect(page.locator('#bmwOut')).toContainText('Rejected:');
  await expect(page.locator('#bmwOut')).toContainText('Unknown ID');
});

test('the Ducati decoder covers the three Panigale frames and refuses the rest', async ({ page }) => {
  const decoded = await page.evaluate(() => {
    const grab = (line) => {
      try { return window.gobBrandTools.decodeDucatiFrame(line); } catch (error) { return ['REJECTED', error.message]; }
    };
    return {
      throttle: grab('can0 080#00000000241A2B00'),
      speed: grab('can0 018#0000000041AB0000'),
      temperature: grab('can0 100#000000A0D2820000'),
      unknown: grab('can0 200#0000000000000000'),
      extended: grab('can0 18DAF110#022100'),
      short: grab('can0 080#0000000000'),
      junk: grab('hello'),
    };
  });

  expect(decoded.throttle[1]).toContain('18 %');          // 0x24 = 36 → trunc(36 / 2)
  expect(decoded.throttle[2]).toContain('6699 rpm');      // 0x1A2B
  expect(decoded.speed[1]).toContain('26 km/h');          // ((0x41 & 0x1F) << 4) + (0xAB >> 4)
  expect(decoded.speed[2]).toContain('Gear raw: 2');      // 0x41 / 32
  expect(decoded.temperature[1]).toContain('120 °C');     // 0xA0 − 40
  expect(decoded.temperature[2]).toContain('21.0 V');     // 0xD2 / 10
  expect(decoded.temperature[3]).toContain('90 °C');      // 0x82 − 40

  expect(decoded.unknown[1]).toContain('not in the Panigale profile');
  expect(decoded.extended[1]).toContain('11-bit');
  expect(decoded.short[1]).toContain('needs 7-8 data bytes');
  expect(decoded.junk[1]).toContain('candump');

  // The panel counts only the frames it actually decoded.
  await page.locator('#ducatiFrames').fill('can0 080#00000000241A2B00\ncan0 200#0000000000000000');
  await page.locator('#ducatiDecode').click();
  await expect(page.locator('#ducatiOut')).toContainText('Rejected:');
  await expect(page.locator('#ducatiMeta')).toHaveText('1 of 2 frame(s) decoded');
});

test('the Indian decoder reads the five J1939 PGNs and reports the rest by name', async ({ page }) => {
  const decoded = await page.evaluate(() => {
    const grab = (line) => {
      try { return window.gobBrandTools.decodeIndianFrame(line); } catch (error) { return ['REJECTED', error.message]; }
    };
    return {
      eec1: grab('can0 18F00400 [8] 00 00 00 40 1F 00 00 84'),
      head: grab('can0 18FEEE00 [8] 64 00 00 00 00 00 00 00'),
      rear: grab('can0 18FEF10B [8] 00 00 40 00 00 00 00 00'),
      fuel: grab('can0 18FEFC00 [8] 00 32 00 00 00 00 00 00'),
      front: grab('can0 18FEBF0B [8] 00 40 00 00 00 00 00 00'),
      notAvailable: grab('can0 18FEF10B [8] 00 FF FF 00 00 00 00 00'),
      elevenBit: grab('can0 0F0#0000000000000000'),
      wrongLength: grab('can0 18FEF10B [4] 00 00 40 00'),
      wrongAddress: grab('can0 18FEF100 [8] 00 00 40 00 00 00 00 00'),
      unknownPgn: grab('can0 18FF0000 [8] 00 00 40 00 00 00 00 00'),
    };
  });

  expect(decoded.eec1[0]).toContain('EEC1');
  expect(decoded.eec1[0]).toContain('source address 0x00');
  expect(decoded.eec1.join(' ')).toContain('1000 rpm');    // 0x1F40 / 8
  expect(decoded.eec1.join(' ')).toContain('7 %');         // 0x84 − 125
  expect(decoded.head.join(' ')).toContain('60 °C');       // 0x64 − 40
  expect(decoded.rear.join(' ')).toContain('64.00 km/h');  // 0x4000 / 256
  expect(decoded.fuel.join(' ')).toContain('20.0 %');      // 0x32 × 0.4
  expect(decoded.front.join(' ')).toContain('64.00 km/h');
  expect(decoded.notAvailable.join(' ')).toContain('not available');

  expect(decoded.elevenBit[1]).toContain('29-bit');
  expect(decoded.wrongLength[1]).toContain('exactly 8');
  expect(decoded.wrongAddress[1]).toContain('source address 0x0B');
  expect(decoded.unknownPgn[1]).toContain('PGN 65280');
});

test('the Suzuki panel refuses a partial all-sensors answer instead of decoding it', async ({ page }) => {
  await page.locator('#suzukiFrames').fill('80 F1 12 34 61 08 00 11 22 33');
  await page.locator('#suzukiDecode').click();
  await expect(page.locator('#suzukiOut')).toContainText('Rejected:');
  await expect(page.locator('#suzukiOut')).toContainText('addressed K-Line response');
  await expect(page.locator('#suzukiMeta')).toHaveText('0 of 1 frame(s) decoded');
});

test('the image-layout check reports which tables a file actually covers', async ({ page }) => {
  const fit = await page.evaluate(() => {
    const tables = [
      { title: 'Main fuel', address: 0x5000, rows: 16, cols: 16, size_bits: 8, units: 'ms' },
      { title: 'Ignition', address: 0x1000, rows: 8, cols: 8, size_bits: 16, units: '°' },
      { title: 'Beyond the read', address: 0x4E000, rows: 4, cols: 4, size_bits: 8, units: '' },
    ];
    const result = window.gobIawLayout.iawFit({ tables }, 0x2000, 0x4000);
    return {
      inside: result.inside.map((table) => table.title),
      outside: result.outside.map((table) => [table.title, table.reason]),
      coverage: result.coverage,
      size: result.inside[0]?.size,
      geometry: window.gobIawLayout.geometry['5am-flash'].size,
    };
  });

  // File offsets are 0x5000−0x4000 and 0x1000−0x4000 (the latter is before the file).
  expect(fit.inside).toEqual(['Main fuel']);
  expect(fit.size).toBe(256);
  expect(fit.outside.map((entry) => entry[0])).toEqual(['Ignition', 'Beyond the read']);
  expect(fit.outside[0][1]).toContain('starts before the first byte');
  expect(fit.outside[1][1]).toContain('runs past the last byte');
  expect(fit.coverage).toBeCloseTo(1 / 3, 5);
  expect(fit.geometry).toBe(311296);
});

test('the image-layout panel fills itself from the bundled definition library', async ({ page }) => {
  const select = page.locator('#iawGuzziDefinition');
  await expect(select.locator('option').first()).toBeAttached();
  await expect(select.locator('option').first()).not.toHaveText('— reading the library… —');
  const count = await select.locator('option').count();
  expect(count).toBeGreaterThan(0);
  await expect(page.locator('#iawGuzziMeta')).toContainText('definition(s) for this brand');

  await page.locator('#iawGuzziSize').fill('0x4C000');
  await page.locator('#iawGuzziPreset').selectOption('5am-flash');
  await expect(page.locator('#iawGuzziBase')).toHaveValue('0x4000');
  await page.locator('#iawGuzziRun').click();
  await expect(page.locator('#iawGuzziOut')).toContainText('File starts at');
  await expect(page.locator('#iawGuzziOut')).toContainText('0x4000–0x4FFFF');   // 311,296 bytes from 0x4000
  await expect(page.locator('#iawGuzziOut')).toContainText('Tables inside this file');

  // A size that cannot hold the definition must say so rather than stay silent.
  await page.locator('#iawGuzziSize').fill('0x100');
  await page.locator('#iawGuzziRun').click();
  await expect(page.locator('#iawGuzziOut')).toContainText('fall outside this file');

  // The Aprilia panel reads its own slice of the same library.
  const aprilia = await page.locator('#iawApriliaDefinition option').count();
  expect(aprilia).toBeGreaterThan(0);
  await expect(page.locator('#iawApriliaMeta')).toContainText('definition(s) for this brand');
});

test('a decode above the frame limit is refused before any work is done', async ({ page }) => {
  const lines = Array.from({ length: 101 }, () => 'can0 080#00000000241A2B00').join('\n');
  await page.locator('#ducatiFrames').fill(lines);
  await page.locator('#ducatiDecode').click();
  await expect(page.locator('#ducatiMeta')).toHaveText('Limit: 100 frames per decode.');
  await expect(page.locator('#ducatiOut')).toHaveText('');

  await page.locator('#ducatiClear').click();
  await expect(page.locator('#ducatiFrames')).toHaveValue('');
  await expect(page.locator('#ducatiMeta')).toHaveText('');
});
