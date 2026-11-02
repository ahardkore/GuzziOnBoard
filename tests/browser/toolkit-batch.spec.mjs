import { test, expect } from '@playwright/test';

/* The five offline general tools added in the "batch 1" pass:
 * checksum workbench, ROM region map, XDF library finder, wideband lab and the
 * J1939 / ISO-TP frame lab. All of them work on data the operator supplies, so
 * every case here runs in the hosted demo with no adapter attached. */

const EXPECTED = {
  kwp: '82 10 F1 21 01 A5',
  j1939: { priority: 6, pgn: 65265, sa: 0, name: 'CCVS · Vehicle speed' },
};

function crc32(bytes) {
  let table = [];
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  let crc = 0xffffffff;
  for (const byte of bytes) crc = table[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function imageWithCrc32(size = 4096) {
  const bytes = new Uint8Array(size);
  for (let i = 0; i < size - 4; i += 1) bytes[i] = (i * 37 + 11) & 0xff;
  const crc = crc32(bytes.subarray(0, size - 4));
  const view = new DataView(bytes.buffer);
  view.setUint32(size - 4, crc, false);
  return Buffer.from(bytes);
}

test.beforeEach(async ({ page }) => {
  await page.goto('/web/index.html');
  await page.locator('[data-view="tools"]').click();
  await expect(page.locator('#tools')).toBeVisible();
});

test('the bench carries the five new general tools and counts them', async ({ page }) => {
  await expect(page.locator('#toolsCountBadge')).toHaveText('29 of 29 tools');
  await expect(page.locator('[data-brand-heading="general"] [data-brand-count]')).toContainText('16 tools');
  for (const id of ['checksumWorkbench', 'romMapPanel', 'xdfFinderPanel', 'widebandLab', 'frameLabPanel']) {
    await expect(page.locator(`#${id}`)).toBeAttached();
    await expect(page.locator(`#${id}`)).toHaveAttribute('data-tool-brand', 'general');
  }
  // The brand filter still hides them: no new tool claims a manufacturer.
  await page.locator('#toolsBrandSelect').selectOption('harley');
  await expect(page.locator('#checksumWorkbench')).toBeHidden();
  await page.locator('#toolsBrandSelect').selectOption('general');
  await expect(page.locator('#checksumWorkbench')).toBeVisible();
});

test('the frame lab decodes J1939 identifiers, segments ISO-TP and composes KWP', async ({ page }) => {
  const decoded = await page.evaluate(() => window.gobFrameLab.decodeJ1939(0x18fef100));
  expect(decoded.priority).toBe(EXPECTED.j1939.priority);
  expect(decoded.pgn).toBe(EXPECTED.j1939.pgn);
  expect(decoded.sa).toBe(EXPECTED.j1939.sa);
  expect(decoded.pgnName).toBe(EXPECTED.j1939.name);
  // PDU1 destinations live in PS; PDU2 folds PS into the PGN.
  const pdu1 = await page.evaluate(() => window.gobFrameLab.decodeJ1939(0x18ea10f1));
  expect(pdu1.pgn).toBe(0xea00);
  expect(pdu1.destination).toBe(0x10);

  await page.locator('#frameLabIn').fill('can0 18FEF100 [8] 01 02 03 04 05 06 07 08\ncan0 0CF00400 [8] 11 22 33 44 55 66 77 88');
  await page.locator('#frameLabDecode').click();
  await expect(page.locator('#frameLabOut')).toContainText('2 frame(s), 2 distinct identifier(s)');
  await expect(page.locator('#frameLabOut')).toContainText('PGN 65265');
  await expect(page.locator('#frameLabOut')).toContainText('EEC1 · Engine speed and torque');

  const frames = await page.evaluate(() => window.gobFrameLab.isotpSegments(new Uint8Array(20).fill(0x41)));
  expect(frames).toHaveLength(4);
  expect(frames[0].kind).toBe('FF');
  expect(Array.from(frames[0].data.slice(0, 2))).toEqual([0x10, 0x14]);
  expect(frames[1].data[0]).toBe(0x21);

  await page.locator('#isotpPayload').fill('62 F1 90 41 42 43 44 45 46 47 48 49 4A 4B 4C 4D 4E 4F 50 51');
  await page.locator('#isotpBuild').click();
  await expect(page.locator('#isotpOut')).toContainText('20 byte payload → 4 frame(s)');
  await expect(page.locator('#isotpOut')).toContainText('FF  10 14 62 F1 90 41 42 43');

  const kwp = await page.evaluate(() => window.gobFrameLab.kwpEncode('21 01', { target: 0x10, source: 0xf1 }));
  expect(kwp.hex).toBe(EXPECTED.kwp);
  await page.locator('#kwpPayload').fill('21 01');
  await page.locator('#kwpBuild').click();
  await expect(page.locator('#kwpOut')).toContainText(EXPECTED.kwp);
  await expect(page.locator('#kwpOut')).toContainText('checksum ok');
});

test('ISO-TP reassembly refuses a sequence gap and completes a real payload', async ({ page }) => {
  const result = await page.evaluate(() => window.gobFrameLab.isotpReassemble(
    '10 14 62 F1 90 41 42 43, 21 44 45 46 47 48 49, 22 4A 4B 4C 4D 4E 4F, 23 50 51 CC CC CC CC',
  ));
  expect(result.complete).toBe(true);
  expect(result.payload.startsWith('62 F1 90')).toBe(true);
  const broken = await page.evaluate(() => {
    try {
      window.gobFrameLab.isotpReassemble('10 14 62 F1 90 41 42 43, 22 44 45 46 47 48 49');
      return 'no error';
    } catch (error) {
      return error.message;
    }
  });
  expect(broken).toContain('sequence');
});

test('the wideband lab applies the published curves and fuel stoichiometry', async ({ page }) => {
  const innovate = await page.evaluate(() => window.gobWidebandLab.voltsToAfr('innovate_lc2', 2, { stoich: 14.7 }));
  expect(innovate.afr).toBeCloseTo(13.366, 3);
  expect(innovate.lambda).toBeCloseTo(13.366 / 14.7, 4);

  const aem = await page.evaluate(() => window.gobWidebandLab.voltsToAfr('aem_xseries', 0.4));
  expect(aem.status).toBe('not ready');
  expect(aem.afr).toBeNull();
  const aemHigh = await page.evaluate(() => window.gobWidebandLab.voltsToAfr('aem_xseries', 4.8));
  expect(aemHigh.status).toBe('sensor error');

  const zt2 = await page.evaluate(() => window.gobWidebandLab.voltsToAfr('zeitronix_zt2', 2.5));
  expect(zt2.afr).toBeCloseTo(14.6, 6);

  await page.locator('#wbIn').fill('volts\n0.0\n2.0\n5.0');
  await page.locator('#wbConvertBtn').click();
  await expect(page.locator('#wbMeta')).toContainText('3 sample(s)');
  await expect(page.locator('#wbMeta')).toContainText('AFR 7.35');
  await expect(page.locator('#wbOut')).toContainText('13.37');

  await page.locator('#wbCalMeasured').fill('15.0');
  await page.locator('#wbCalActual').fill('14.7');
  await page.locator('#wbCalBtn').click();
  await expect(page.locator('#wbCalOut')).toContainText('the log reads lean of the reference');
});

test('the ROM map finds padding and code, and compares two images', async ({ page }) => {
  const first = Buffer.alloc(8192, 0);
  for (let i = 4096; i < 8192; i += 1) first[i] = (i * 97 + 13) & 0xff;
  const second = Buffer.from(first);
  second[5000] = 0xff;

  await page.locator('#romFile').setInputFiles({ name: 'rom-a.bin', mimeType: 'application/octet-stream', buffer: first });
  await page.locator('#romFileB').setInputFiles({ name: 'rom-b.bin', mimeType: 'application/octet-stream', buffer: second });
  await page.locator('#romMapBtn').click();

  await expect(page.locator('#romMeta')).toContainText('8.0 KiB');
  await expect(page.locator('#romStrip svg.rom-strip')).toBeVisible();
  await expect(page.locator('#romOut')).toContainText('padding / blank');
  await expect(page.locator('#romOut')).toContainText('code or compressed');
  await expect(page.locator('#romDiff')).toContainText('1 run(s)');
  await expect(page.locator('#romDiff')).toContainText('0x1388');
});

test('the checksum workbench finds a stored CRC-32 and repairs a copy only', async ({ page }) => {
  const buffer = imageWithCrc32(4096);
  await page.locator('#cksFile').setInputFiles({ name: 'image.bin', mimeType: 'application/octet-stream', buffer });
  await page.locator('#cksScanBtn').click();

  await expect(page.locator('#cksMeta')).toContainText('4096 byte(s)');
  await expect(page.locator('#cksOut')).toContainText('CRC-32 (zlib / IEEE)');
  const row = page.locator('#cksOut table.data tbody tr').filter({ hasText: 'CRC-32' }).first();
  await expect(row).toContainText('big');
  await row.locator('button[data-cks-row]').click();
  await expect(page.locator('#cksDetail')).toContainText('Download repaired copy');
  await expect(page.locator('#cksDetail')).toContainText('A matching checksum is not flash approval');
  await expect(page.locator('#cksDetail .kv')).toContainText('Original SHA-256');
});

test('the checksum workbench reports an image whose word does not add up', async ({ page }) => {
  const buffer = imageWithCrc32(2048);
  buffer[100] ^= 0xff; // corrupt the data, leave the stored word alone
  await page.locator('#cksFile').setInputFiles({ name: 'broken.bin', mimeType: 'application/octet-stream', buffer });
  await page.locator('#cksScanBtn').click();
  await expect(page.locator('#cksMeta')).toContainText('match(es)');
  const body = await page.locator('#cksMeta').textContent();
  expect(body).not.toContain('1 match(es)');
});

test('the XDF library finder searches all bundled definitions by brand and field', async ({ page }) => {
  await page.locator('#xdfFindQuery').fill('injection');
  await page.locator('#xdfFindBtn').click();
  await expect(page.locator('#xdfFindMeta')).toContainText('of 121 definition(s)');
  await expect(page.locator('#xdfFindMeta')).toContainText('4,280 tables');
  await expect(page.locator('#xdfFindOut .xdf-find-group').first()).toBeVisible();
  const groups = await page.locator('#xdfFindOut .xdf-find-group').count();
  expect(groups).toBeGreaterThan(3);

  await page.locator('#xdfFindBrand').selectOption('ducati');
  await page.locator('#xdfFindBtn').click();
  await expect(page.locator('#xdfFindOut .xdf-find-group')).toHaveCount(1);
  await page.locator('#xdfFindBrand').selectOption('');

  // Address search accepts hex with or without the 0x prefix.
  await page.locator('#xdfFindQuery').fill('');
  await page.locator('#xdfFindField').selectOption('address');
  await page.locator('#xdfFindQuery').fill('0xB024');
  await page.locator('#xdfFindBtn').click();
  await expect(page.locator('#xdfFindOut')).toContainText('0xB024');
  await expect(page.locator('#xdfFindMeta')).not.toContainText('Nothing matched');

  await page.locator('#xdfFindField').selectOption('all');
  await page.locator('#xdfFindClear').click();
  await expect(page.locator('#xdfFindMeta')).toHaveText('');
});
