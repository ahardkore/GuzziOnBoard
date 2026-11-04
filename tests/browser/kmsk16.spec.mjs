import { test, expect } from '@playwright/test';

/* Batch 5: the Keihin KMSK16 decoder, filed under KTM and Husqvarna.
 *
 * Both panels are the same decoder, because the Husqvarna 449/511 are reported
 * to use the same ECU. Each case is driven the way an operator drives it —
 * paste a captured frame, press Decode, read the panel — and every value below
 * was computed by hand from the declared range, not copied from the output:
 *
 *   0x0100 engine speed  0x0BB8 = 3000 counts × 0.25 rpm = 750 rpm
 *   0x0040 neutral       0x00FF = "Gear engaged"
 *   0x0006 battery       0x0075 = 117 × 0.1 V = 11.7 V, against a 0–5 V range
 *   0x0502 over-rev      raw only: the source gives two contradictory ranges
 *
 * The frames are real KWP2000 frames with correct sums; the checksum byte in
 * the last case is deliberately wrong.
 */

test.beforeEach(async ({ page }) => {
  await page.goto('/web/index.html');
  await page.locator('[data-view="tools"]').click();
  await expect(page.locator('#tools')).toBeVisible();
});

const PANELS = [
  ['ktmKmsk16', 'ktm', 'ktm'],
  ['husqvarnaKmsk16', 'husqvarna', 'husqvarna'],
];

for (const [id, brand, prefix] of PANELS) {
  test(`${brand}: the panel decodes engine speed and says the scale is inferred`, async ({ page }) => {
    await expect(page.locator(`#${id}`)).toHaveAttribute('data-tool-brand', brand);
    await expect(page.locator(`[data-brand-heading="${brand}"]`)).toBeAttached();
    await page.locator(`#${prefix}Kmsk16Frames`).fill('85 F1 12 62 01 00 0B B8 AE');
    await page.locator(`#${prefix}Kmsk16Decode`).click();
    const out = page.locator(`#${prefix}Kmsk16Out`);
    await expect(out).toContainText('Engine speed');
    await expect(out).toContainText('750 rpm');
    await expect(out).toContainText('inferred');
    await expect(out).toContainText('Declared range: 0–16384 rpm');
    await expect(page.locator(`#${prefix}Kmsk16Meta`)).toHaveText('1 of 1 frame(s) decoded');
  });

  test(`${brand}: a bad checksum is refused by name`, async ({ page }) => {
    await page.locator(`#${prefix}Kmsk16Frames`).fill('85 F1 12 62 01 00 0B B8 AF');
    await page.locator(`#${prefix}Kmsk16Decode`).click();
    await expect(page.locator(`#${prefix}Kmsk16Out`)).toContainText('Rejected:');
    await expect(page.locator(`#${prefix}Kmsk16Out`)).toContainText('checksum');
    await expect(page.locator(`#${prefix}Kmsk16Meta`)).toHaveText('0 of 1 frame(s) decoded');
  });

  test(`${brand}: a non-hex token is not silently trimmed into a frame`, async ({ page }) => {
    await page.locator(`#${prefix}Kmsk16Frames`).fill('85 F1 12 62 01 00 0B B8 AE ZZ');
    await page.locator(`#${prefix}Kmsk16Decode`).click();
    await expect(page.locator(`#${prefix}Kmsk16Out`)).toContainText("'ZZ' is not a hex byte");
  });

  test(`${brand}: the reference table is rendered from the decoder's own data`, async ({ page }) => {
    await page.locator(`#${id} details.advanced summary`).click();
    const ref = page.locator(`#${prefix}Kmsk16Ref`);
    await expect(ref).toContainText('0x0100');
    await expect(ref).toContainText('Engine speed');
    await expect(ref).toContainText('0.25');
    await expect(ref).toContainText('(inferred)');
    await expect(ref).toContainText('0x0510');
    // The area numbering skips 0x050A–0x050F in the source; the table must not
    // invent them.
    await expect(ref).not.toContainText('0x050A');
  });
}

test('both KMSK16 panels decode the same frame identically', async ({ page }) => {
  const frame = '85 F1 12 62 00 40 00 FF 29';
  await page.locator('#ktmKmsk16Frames').fill(frame);
  await page.locator('#ktmKmsk16Decode').click();
  await page.locator('#husqvarnaKmsk16Frames').fill(frame);
  await page.locator('#husqvarnaKmsk16Decode').click();
  const ktm = (await page.locator('#ktmKmsk16Out').textContent()).replace(/^.*\n/, '');
  const hus = (await page.locator('#husqvarnaKmsk16Out').textContent()).replace(/^.*\n/, '');
  expect(ktm).toBe(hus);
  await expect(page.locator('#ktmKmsk16Out')).toContainText('Gear engaged');
});

test('a source conflict is reported instead of a number', async ({ page }) => {
  await page.locator('#ktmKmsk16Frames').fill('85 F1 12 62 00 06 00 75 65');
  await page.locator('#ktmKmsk16Decode').click();
  const out = page.locator('#ktmKmsk16Out');
  await expect(out).toContainText('11.7 V');
  await expect(out).toContainText('Source conflict');
  await expect(out).toContainText('0–5 V');

  await page.locator('#ktmKmsk16Frames').fill('85 F1 12 62 05 02 05 D1 C7');
  await page.locator('#ktmKmsk16Decode').click();
  await expect(out).toContainText('Source conflict');
  await expect(out).not.toContainText('Value (');
});

test('three frames give the second-throttle percentage, labelled as rewritten', async ({ page }) => {
  await page.locator('#ktmKmsk16Frames').fill([
    '85 F1 12 62 01 70 02 00 5D',
    '85 F1 12 62 01 72 00 E3 40',
    '85 F1 12 62 01 73 03 A1 02',
  ].join('\n'));
  await page.locator('#ktmKmsk16Decode').click();
  const out = page.locator('#ktmKmsk16Out');
  await expect(out).toContainText('Derived across frames (rewritten, not quoted)');
  await expect(out).toContainText('40.6 %');
  await expect(page.locator('#ktmKmsk16Meta')).toHaveText('3 of 3 frame(s) decoded');
});

test('a request and a negative response are both readable', async ({ page }) => {
  await page.locator('#ktmKmsk16Frames').fill(['83 12 F1 22 01 00 A9', '83 F1 12 7F 22 31 58'].join('\n'));
  await page.locator('#ktmKmsk16Decode').click();
  const out = page.locator('#ktmKmsk16Out');
  await expect(out).toContainText('Asks for 0x0100 · Engine speed');
  await expect(out).toContainText('Request out of range (0x31)');
});

test('the bench counts the two new panels and filters by their brands', async ({ page }) => {
  await expect(page.locator('#toolsCountBadge')).toHaveText('46 of 46 tools');
  await expect(page.locator('[data-brand-heading="ktm"] [data-brand-count]')).toContainText('1 tool');
  await expect(page.locator('[data-brand-heading="husqvarna"] [data-brand-count]')).toContainText('1 tool');
  await page.locator('#toolsBrandSelect').selectOption('ktm');
  await expect(page.locator('#toolsBrandBadge')).toContainText('KTM');
  const visible = page.locator('#tools > article.panel[data-tool-cat]:not(.hidden)');
  await expect(visible).toHaveCount(1);
  await expect(page.locator('#ktmKmsk16')).toBeVisible();
});

test('the help centre answers for the decoder, both brands and the protocol', async ({ page }) => {
  await page.goto('/web/index.html#help/ktm-kmsk16-decoder');
  await expect(page.locator('#helpArticlePane')).toContainText('over-rev');
  await page.goto('/web/index.html#help/husqvarna-kmsk16-decoder');
  await expect(page.locator('#helpArticlePane')).toContainText('449');
  await page.goto('/web/index.html#help/protocol/kmsk16');
  await expect(page.locator('#helpArticlePane')).toContainText('CheckCodingChecksum');
  await expect(page.locator('#helpArticlePane')).toContainText('10,400');
});
