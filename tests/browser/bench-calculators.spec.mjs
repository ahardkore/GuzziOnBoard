import { test, expect } from '@playwright/test';

/* Batch 4: the bench arithmetic — injector sizing, dyno correction and fuel
 * blend/lambda. Every expected number is hand-computed in the comment beside
 * it, so a formula change shows up here rather than on somebody's engine.
 *
 * These panels are pure arithmetic on typed input: no adapter, no file, no
 * motorcycle. The rejection cases matter as much as the results — a calculator
 * that silently returns zero for nonsense is worse than one that refuses.
 */

test.beforeEach(async ({ page }) => {
  await page.goto('/web/index.html');
  await page.locator('[data-view="tools"]').click();
  await expect(page.locator('#tools')).toBeVisible();
});

test('the three bench calculators are filed under General', async ({ page }) => {
  await expect(page.locator('#toolsCountBadge')).toHaveText('44 of 44 tools');
  await expect(page.locator('[data-brand-heading="general"] [data-brand-count]')).toContainText('23 tools');
  for (const id of ['injectorPanel', 'dynoCorrectionPanel', 'fuelBlendPanel']) {
    await expect(page.locator(`#${id}`)).toHaveAttribute('data-tool-brand', 'general');
  }
});

test('injector sizing: 100 hp at 0.50 BSFC is 50 lb/h and 507 cc/min', async ({ page }) => {
  await page.locator('#injPower').fill('100');
  await page.locator('#injBsfc').fill('0.50');
  await page.locator('#injCylinders').fill('4');
  await page.locator('#injDuty').fill('80');
  await page.locator('#injRun').click();

  const out = page.locator('#injOut');
  // 100 hp × 0.50 lb/(hp·h) = 50 lb/h = 22.68 kg/h = 30.44 L/h = 507.4 cc/min
  await expect(out).toContainText('50.0 lb/h');
  await expect(out).toContainText('507 cc/min');
  await expect(out).toContainText('30.4 L/h');
  // 507.4 / 0.80 / 4 = 158.6 cc/min per injector at 3 bar
  await expect(out).toContainText('159 cc/min at 3.00 bar');
  // 4-stroke at 9000 rpm: 120000 / 9000 = 13.33 ms per cycle, 80 % = 10.67 ms
  await expect(out).toContainText('13.33 ms at 9000 rpm');
  await expect(out).toContainText('10.67 ms at 80 % duty');
  await expect(page.locator('#injMeta')).toContainText('Sized at 80 % duty limit');
});

test('injector flow follows the square root of pressure', async ({ page }) => {
  await page.locator('#injPower').fill('100');
  await page.locator('#injCylinders').fill('4');
  await page.locator('#injDuty').fill('80');
  await page.locator('#injPressure').fill('4.0');   // running 4 bar through a 3 bar injector
  await page.locator('#injRated').fill('3.0');
  await page.locator('#injFlow').fill('240');
  await page.locator('#injRun').click();

  const out = page.locator('#injOut');
  // 240 × sqrt(4/3) = 277.1 cc/min each → 1108 cc/min total
  await expect(out).toContainText('277 cc/min each');
  // 507.4 / 1108 = 45.8 %
  await expect(out).toContainText('45.8 %');
  // The injector needed at its rating is 158.6 / sqrt(4/3) = 137.0 cc/min
  await expect(out).toContainText('137 cc/min at 3.00 bar');
});

test('under-sized injectors are called out instead of being rounded away', async ({ page }) => {
  await page.locator('#injPower').fill('100');
  await page.locator('#injCylinders').fill('4');
  await page.locator('#injFlow').fill('100');
  await page.locator('#injRun').click();
  // 507.4 / (100 × 4) = 126.8 % duty
  await expect(page.locator('#injOut')).toContainText('126.8 %');
  await expect(page.locator('#injOut')).toContainText('cannot deliver the target');
});

test('dyno correction matches the published SAE J1349 form at reference air', async ({ page }) => {
  const factors = await page.evaluate(() => {
    const standard = (id, tempC, pressureHpa) => window.gobBenchCalc
      .dynoCorrection({ standard: id, tempC, pressureHpa, humidity: 0, measured: 100 }).factor;
    return {
      j1349Ref: standard('sae_j1349', 25, 990),      // reference conditions → 1.000
      j1349Sea: standard('sae_j1349', 25, 1013),
      din: standard('din_70020', 25, 1013.25),
      j607: standard('sae_j607', 30, 990),
      iso: standard('iso_1585', 25, 1000),
      uncorrected: standard('uncorrected', 40, 800),
    };
  });
  expect(factors.j1349Ref).toBeCloseTo(1.0, 4);
  // 1.176 × (990/1013) − 0.176 = 0.9733
  expect(factors.j1349Sea).toBeCloseTo(0.9733, 4);
  // (1013.25/1013.25) × (298.15/293.15) = 1.0171
  expect(factors.din).toBeCloseTo(1.0171, 4);
  // (1013.25/990) × (303.15/288.15) = 1.0768
  expect(factors.j607).toBeCloseTo(1.0768, 4);
  expect(factors.iso).toBeCloseTo(1.0171, 4);   // (1000/1000) × (298.15/293.15)
  expect(factors.uncorrected).toBe(1);
});

test('the dyno panel shows every standard for the same run and flags a boosted J1349', async ({ page }) => {
  await page.locator('#dynoMeasured').fill('100');
  await page.locator('#dynoTemp').fill('25');
  await page.locator('#dynoPressure').fill('1013');
  await page.locator('#dynoRun').click();

  const out = page.locator('#dynoOut');
  await expect(out).toContainText('SAE J1349');
  await expect(out).toContainText('DIN 70020');
  await expect(out).toContainText('SAE J607');
  await expect(out).toContainText('Uncorrected (as measured)');
  await expect(out).toContainText('97.3 hp');           // 100 × 0.9733
  await expect(out).toContainText('101.7 hp');          // DIN 70020
  await expect(page.locator('#dynoMeta')).toContainText('SAE J1349 · factor 0.973');

  await page.locator('#dynoBoosted').check();
  await page.locator('#dynoRun').click();
  await expect(out).toContainText('defined for naturally aspirated engines');
});

test('an altitude stands in for a missing barometric pressure', async ({ page }) => {
  await page.locator('#dynoMeasured').fill('80');
  await page.locator('#dynoPressure').fill('');
  await page.locator('#dynoAltitude').fill('1500');
  await page.locator('#dynoRun').click();
  // 1013.25 × (1 − 2.25577e-5 × 1500)^5.25588 = 845.6 hPa
  await expect(page.locator('#dynoOut')).toContainText('845.6 hPa');
  await expect(page.locator('#dynoOut')).toContainText('estimated from 1500 m');

  await page.locator('#dynoAltitude').fill('');
  await page.locator('#dynoRun').click();
  await expect(page.locator('#dynoMeta')).toContainText('Give a barometric pressure');
});

test('fuel blend: E85 costs 1.42× the volume of petrol for the same lambda', async ({ page }) => {
  const blend = await page.evaluate(() => {
    const B = window.gobBenchCalc;
    const e85 = B.ethanolBlend(85);
    return {
      stoich: e85.stoich,
      density: e85.density,
      energy: e85.energyPerLitre,
      ratio: B.fuelVolumeRatio(85),
      afr: B.lambdaToAfr(0.85, e85.stoich),
      lambda: B.afrToLambda(12.5, e85.stoich),
      e0: B.ethanolBlend(0),
      e100: B.ethanolBlend(100),
    };
  });
  expect(blend.stoich).toBeCloseTo(9.855, 3);        // 14.7 × 0.15 + 9.0 × 0.85
  expect(blend.density).toBeCloseTo(0.7824, 4);      // 0.745 × 0.15 + 0.789 × 0.85
  expect(blend.energy).toBeCloseTo(22.84, 1);
  expect(blend.ratio).toBeCloseTo(1.42, 2);          // (14.7/9.855) × (0.745/0.7824)
  expect(blend.afr).toBeCloseTo(8.38, 2);            // 0.85 × 9.855
  expect(blend.lambda).toBeCloseTo(1.268, 3);        // 12.5 / 9.855
  expect(blend.e0.stoich).toBeCloseTo(14.7, 4);
  expect(blend.e100.stoich).toBeCloseTo(9.0, 4);
});

test('the blend panel converts lambda, and warns when E85 pushes duty past the knee', async ({ page }) => {
  await page.locator('#blendEthanol').fill('85');
  await page.locator('#blendMode').selectOption('lambda');
  await page.locator('#blendValue').fill('0.85');
  await page.locator('#blendPetrolDuty').fill('60');
  await page.locator('#blendRun').click();

  const out = page.locator('#fuelBlendPanel #blendOut');
  await expect(out).toContainText('9.86:1');
  await expect(out).toContainText('8.38');             // AFR at λ 0.85 on E85
  await expect(out).toContainText('12.49');            // the same λ on petrol
  await expect(out).toContainText('1.420 ×');
  // 60 % petrol duty × 1.420 = 85.2 %
  await expect(out).toContainText('85.2 %');
  await expect(out).toContainText('past the point where most injectors stay linear');

  // A blend that would need more than 100 % warns differently: it cannot deliver.
  await page.locator('#blendPetrolDuty').fill('80');
  await page.locator('#blendRun').click();
  await expect(out).toContainText('They cannot deliver that');

  await page.locator('#blendMode').selectOption('afr');
  await page.locator('#blendValue').fill('12.5');
  await page.locator('#blendRun').click();
  await expect(out).toContainText('1.268');
});

test('every calculator refuses nonsense with a reason', async ({ page }) => {
  const errors = await page.evaluate(() => {
    const B = window.gobBenchCalc;
    const grab = (fn) => { try { fn(); return 'accepted'; } catch (error) { return error.message; } };
    return {
      power: grab(() => B.injectorSizing({ powerHp: 0, cylinders: 4, maxDuty: 0.8 })),
      bsfc: grab(() => B.fuelFlowCcMin(100, 0)),
      cylinders: grab(() => B.injectorSizing({ powerHp: 100, cylinders: 0, maxDuty: 0.8 })),
      duty: grab(() => B.injectorSizing({ powerHp: 100, cylinders: 4, maxDuty: 1.2 })),
      pressure: grab(() => B.injectorSizing({ powerHp: 100, cylinders: 4, maxDuty: 0.8, fuelPressure: 0 })),
      rpm: grab(() => B.injectionWindowMs(0)),
      standard: grab(() => B.dynoCorrection({ standard: 'nope', tempC: 20, measured: 100 })),
      noAir: grab(() => B.dynoCorrection({ standard: 'sae_j1349', tempC: 20, measured: 100 })),
      ethanol: grab(() => B.ethanolBlend(150)),
      lambda: grab(() => B.lambdaToAfr(0, 14.7)),
      afr: grab(() => B.afrToLambda(-1, 14.7)),
      blendDuty: grab(() => B.blendInjectorImpact({ petrolDuty: 1.4, blendPercent: 85 })),
      altitude: grab(() => B.pressureAtAltitude(1013.25, 20000)),
    };
  });
  expect(errors.power).toContain('greater than zero');
  expect(errors.bsfc).toContain('BSFC');
  expect(errors.cylinders).toContain('whole number');
  expect(errors.duty).toContain('between 0 and 100 %');
  expect(errors.pressure).toContain('above zero bar');
  expect(errors.rpm).toContain('Engine speed');
  expect(errors.standard).toContain('Unknown correction standard');
  expect(errors.noAir).toContain('Give a barometric pressure');
  expect(errors.ethanol).toContain('between 0 and 100 %');
  expect(errors.lambda).toContain('Lambda');
  expect(errors.afr).toContain('AFR');
  expect(errors.blendDuty).toContain('between 0 and 100 %');
  expect(errors.altitude).toContain('Altitude');
});

test('the fuel choice carries its own BSFC default, but never overwrites a typed one', async ({ page }) => {
  // Fresh panel: petrol default 0.50 follows the fuel.
  await page.locator('#injFuel').selectOption('e85');
  await expect(page.locator('#injBsfc')).toHaveValue('0.66');

  // A number the operator typed is left alone.
  await page.locator('#injBsfc').fill('0.55');
  await page.locator('#injFuel').selectOption('methanol');
  await expect(page.locator('#injBsfc')).toHaveValue('0.55');
});

test('a changed input recalculates an answer already on screen', async ({ page }) => {
  await page.locator('#injPower').fill('100');
  await page.locator('#injRun').click();
  await expect(page.locator('#injOut')).toContainText('100.0 hp');

  await page.locator('#injPower').fill('200');
  // No second click: 200 hp doubles the demand to 1014 cc/min.
  await expect(page.locator('#injOut')).toContainText('200.0 hp');
  await expect(page.locator('#injOut')).toContainText('1015 cc/min');
});
