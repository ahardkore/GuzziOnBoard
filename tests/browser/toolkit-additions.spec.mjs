import { test, expect } from '@playwright/test';

/* Batch 5: two additions to tools that already shipped.
 *
 *  1. The speedometer / driveline correction inside the gearing panel. The
 *     point of these cases is that three different questions stay apart:
 *     performance (speed at the same rpm), indication (what the dash reads at
 *     the same true speed) and correction (what a healer should be set to).
 *     Confusing indication with performance is the usual reason someone buys
 *     the wrong correction factor, so the sensor-location cases are explicit.
 *
 *  2. The MotoLink tune-file dialect for the tune diff, parsed from the format
 *     upstream mtlfile.cpp actually writes.
 */

test.beforeEach(async ({ page }) => {
  await page.goto('/web/index.html');
  await page.locator('[data-view="tools"]').click();
  await expect(page.locator('#tools')).toBeVisible();
});

/* ---- speedometer section ------------------------------------------------- */

test('the speedometer section lives in the gearing panel', async ({ page }) => {
  const panel = page.locator('#gearingPanel');
  await expect(panel).toContainText('Speedometer & driveline correction');
  for (const id of ['spdFrontFrom', 'spdFrontTo', 'spdRearFrom', 'spdRearTo', 'spdTyreFrom',
    'spdTyreTo', 'spdSensor', 'spdIndicated', 'spdActual', 'spdRun', 'spdOut']) {
    await expect(page.locator(`#${id}`)).toBeAttached();
  }
});

test('sprocket and tyre changes give the driveline and tyre factors', async ({ page }) => {
  const factors = await page.evaluate(() => {
    const S = window.gobSpeedo;
    const drive = S.drivelineFactor({ frontFrom: 15, frontTo: 16, rearFrom: 45, rearTo: 45 });
    const rear = S.drivelineFactor({ rearFrom: 45, rearTo: 47 });
    const tyre = S.tyreFactor('180/55-17', '190/55-17');
    return {
      ratioFrom: drive.ratioFrom,
      ratioTo: drive.ratioTo,
      drive: drive.percent,
      shorter: rear.percent,
      tyre: tyre.percent,
      growth: tyre.growthMm,
      taller: drive.taller,
    };
  });
  expect(factors.ratioFrom).toBeCloseTo(3.0, 6);        // 45 / 15
  expect(factors.ratioTo).toBeCloseTo(2.8125, 6);       // 45 / 16
  expect(factors.drive).toBeCloseTo(6.667, 3);          // 3 / 2.8125 = 1.0667
  expect(factors.shorter).toBeCloseTo(-4.255, 3);       // 47 rear: 45/47
  // 180/55-17 → 1.9786 m, 190/55-17 → 2.0131 m: +34.6 mm of circumference.
  expect(factors.tyre).toBeCloseTo(1.747, 3);
  expect(factors.growth).toBeCloseTo(34.56, 1);
  expect(factors.taller).toBe(true);
});

test('indication depends on where the speed signal is taken from', async ({ page }) => {
  const result = await page.evaluate(() => {
    const S = window.gobSpeedo;
    const drive = S.drivelineFactor({ frontFrom: 15, frontTo: 16 });
    const tyre = S.tyreFactor('180/55-17', '190/55-17');
    return {
      wheelNoDrive: S.indicationFactor({ drive, sensor: 'wheel' }).percent,
      wheel: S.indicationFactor({ drive, tyre, sensor: 'wheel' }).percent,
      gearbox: S.indicationFactor({ drive, tyre, sensor: 'gearbox' }).percent,
      speed: S.speedoReport({ frontFrom: 15, frontTo: 16, tyreFrom: '180/55-17', tyreTo: '190/55-17' }).speed.percent,
    };
  });
  // A wheel sensor ignores gearing entirely: only the tyre moves the reading.
  expect(result.wheelNoDrive).toBe(0);
  expect(result.wheel).toBeCloseTo(-1.7166, 3);         // 1 / 1.017466 - 1
  // A gearbox sensor also sees the ratio: (1/1.0667) × (1/1.01747).
  expect(result.gearbox).toBeCloseTo(-7.8593, 3);
  // Performance is the same wherever the sensor is: the factors multiply.
  expect(result.speed).toBeCloseTo(8.5297, 3);
});

test('measured error becomes a corrector factor, and the panel prints it', async ({ page }) => {
  await page.locator('#spdFrontFrom').fill('15');
  await page.locator('#spdFrontTo').fill('15');
  await page.locator('#spdRearFrom').fill('45');
  await page.locator('#spdRearTo').fill('45');
  await page.locator('#spdTyreFrom').fill('180/55-17');
  await page.locator('#spdTyreTo').fill('');
  await page.locator('#spdSensor').selectOption('wheel');
  await page.locator('#spdIndicated').fill('100');
  await page.locator('#spdActual').fill('92');
  await page.locator('#spdRun').click();

  const out = page.locator('#spdOut');
  await expect(out).toContainText('over-reads');
  await expect(out).toContainText('0.9200 ×');
  await expect(out).toContainText('-8.0 %');
  await expect(out).toContainText('92.0 km/h for 92 true');
  await expect(page.locator('#spdMeta')).toContainText('no change entered');

  // Hardware changes and a measurement combine into one suggested setting.
  await page.locator('#spdFrontTo').fill('16');
  await page.locator('#spdSensor').selectOption('gearbox');
  await page.locator('#spdRun').click();
  // 15 → 16 front sprocket is a 0.9375 indication factor at the gearbox, and
  // the measured 0.92 correction multiplies with it: 0.8625.
  await expect(out).toContainText('0.8625 × combined');
});

test('the speedometer maths refuses nonsense instead of guessing', async ({ page }) => {
  const errors = await page.evaluate(() => {
    const S = window.gobSpeedo;
    const grab = (fn) => { try { fn(); return 'accepted'; } catch (error) { return error.message; } };
    return {
      tyre: grab(() => S.speedoCircumference('180')),
      zeroTyre: grab(() => S.speedoCircumference('0/55-17')),
      teeth: grab(() => S.speedoDriveRatio(0, 45)),
      sensor: grab(() => S.indicationFactor({ sensor: 'gps' })),
      indicated: grab(() => S.speedoError({ indicated: 0, actual: 92 })),
      actual: grab(() => S.speedoError({ indicated: 100, actual: 0 })),
    };
  });
  expect(errors.tyre).toContain('Cannot parse tyre marking');
  expect(errors.zeroTyre).toContain('zero or negative');
  expect(errors.teeth).toContain('above zero');
  expect(errors.sensor).toContain('Unknown speed sensor location');
  expect(errors.indicated).toContain('Indicated speed');
  expect(errors.actual).toContain('Actual speed');
});

/* ---- MotoLink tune files ------------------------------------------------- */

/** The structure upstream mtlfile.cpp writes: Info, Settings, Properties, Rows, Columns, Tables. */
function buildMtl({ version = '1.2.3', props = [], tables = [] } = {}) {
  const rows = tables[0]?.rows ?? 2;
  const cols = tables[0]?.cols ?? 2;
  return `<?xml version="1.0" encoding="UTF-8"?>
<Motolink>
  <Info date="2026-11-02T10:00:00Z" version="${version}"/>
  <Settings/>
  <Properties>
${props.map(([name, value]) => `    <Property Name="${name}">${value}</Property>`).join('\n')}
  </Properties>
  <Rows count="${rows}">
${Array.from({ length: rows }, (_, i) => `    <Row>${1000 + i * 1000}</Row>`).join('\n')}
  </Rows>
  <Columns count="${cols}">
${Array.from({ length: cols }, (_, i) => `    <Column>${i * 10}</Column>`).join('\n')}
  </Columns>
  <Tables>
${tables.map((table) => `    <Table Name="${table.name}">
${table.z.map((row) => `      <Row>${row.map((cell) => `<Column>${cell}</Column>`).join('')}</Row>`).join('\n')}
    </Table>`).join('\n')}
  </Tables>
</Motolink>`;
}

test('a MotoLink tune file is recognised by its root element, not its extension', async ({ page }) => {
  const parsed = await page.evaluate((text) => {
    const file = window.gobTuneDiff.parseTuneText('tune.xml', text);
    return {
      kind: file.kind,
      format: file.format,
      version: file.info.version,
      settings: file.info.settings,
      rows: file.axis.rows,
      columns: file.axis.columns,
      tables: file.tables.map((table) => ({ name: table.name, cols: table.cols, z: table.z })),
    };
  }, buildMtl({
    props: [['RpmMult', '1.0000'], ['SpeedMult', '1.0000'], ['AFR0V', '7.35'], ['AFR5V', '22.39'], ['TPS0', '0.50']],
    tables: [{ name: 'AFR', cols: 2, rows: 2, z: [[13.5, 13.6], [13.7, 13.8]] }],
  }));

  expect(parsed.kind).toBe('mtl');
  expect(parsed.format).toBe('MotoLink');
  expect(parsed.version).toBe('1.2.3');
  // The five settings upstream's GUI reads are the ones this profile knows.
  // Reported in the order the upstream GUI reads them, whatever order they
  // appear in inside the file.
  expect(parsed.settings).toEqual(['RpmMult', 'SpeedMult', 'TPS0', 'AFR0V', 'AFR5V']);
  expect(parsed.rows).toEqual(['1000', '2000']);
  expect(parsed.columns).toEqual(['0', '10']);
  expect(parsed.tables).toEqual([{ name: 'AFR', cols: 2, z: [13.5, 13.6, 13.7, 13.8] }]);
});

test('two MotoLink tunes diff by constant and by cell', async ({ page }) => {
  const result = await page.evaluate(({ before, after }) => {
    const a = window.gobTuneDiff.parseTuneText('a.xml', before);
    const b = window.gobTuneDiff.parseTuneText('b.xml', after);
    return window.gobTuneDiff.diffTunes(a, b);
  }, {
    before: buildMtl({
      props: [['SpeedMult', '1.0000'], ['AFR0V', '7.35']],
      tables: [{ name: 'AFR', cols: 2, rows: 2, z: [[13.5, 13.6], [13.7, 13.8]] }],
    }),
    after: buildMtl({
      props: [['SpeedMult', '1.0500'], ['AFR0V', '7.35']],
      tables: [{ name: 'AFR', cols: 2, rows: 2, z: [[13.5, 13.6], [13.7, 14.2]] }],
    }),
  });

  expect(result.kind).toBe('mtl');
  expect(result.constants.changed).toHaveLength(1);
  expect(result.constants.changed[0].key).toBe('SpeedMult');
  expect(result.constants.changed[0].percent).toBeCloseTo(5, 6);
  expect(result.tables.changed).toHaveLength(1);
  expect(result.tables.changed[0].changedCells).toBe(1);
  // index 3 is row 1, column 1: the second row's second cell.
  expect(result.tables.changed[0].cells[0]).toMatchObject({ index: 3, row: 1, col: 1, before: 13.8, after: 14.2 });
});

test('an XML file that is not a MotoLink tune is not claimed as one', async ({ page }) => {
  const result = await page.evaluate(() => {
    const file = window.gobTuneDiff.parseTuneText('other.xml', '<Something><a>1</a></Something>');
    // A .msq must still be detected as .msq even though both are XML.
    const msq = window.gobTuneDiff.parseTuneText('tune.msq', '<msq><constant name="reqFuel" value="12.0"/></msq>');
    return { other: file.kind, msq: msq.kind, msqConstants: msq.constants };
  });
  expect(result.other).not.toBe('mtl');
  expect(result.msq).toBe('msq');
  expect(result.msqConstants.reqFuel).toBe(12);
});
