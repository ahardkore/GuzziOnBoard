import { test, expect } from '@playwright/test';
import { createHash } from 'node:crypto';

async function openTools(page) {
  await page.goto('/web/index.html');
  await page.locator('[data-view="tools"]').click();
}

test('service worksheet requires a real anchor and handles distance and calendar thresholds', async ({ page }) => {
  await openTools(page);
  await page.locator('#serviceCurrentKm').fill('13500');
  await page.locator('#serviceIntervalKm').fill('10000');
  await page.locator('#serviceDueBtn').click();
  await expect(page.locator('#serviceDueOut')).toContainText('Distance needs the last service');
  await page.locator('#serviceLastKm').fill('5000');
  await page.locator('#serviceLastDate').fill('2024-01-31');
  await page.locator('#serviceAsOfDate').fill('2024-02-29');
  await page.locator('#serviceIntervalMonths').fill('1');
  await page.locator('#serviceDueBtn').click();
  await expect(page.locator('#serviceDueOut')).toContainText('15000 km');
  await expect(page.locator('#serviceDueOut')).toContainText('1500 km remaining');
  await expect(page.locator('#serviceDueOut')).toContainText('2024-02-29');
  await expect(page.locator('#serviceDueOut')).toContainText('due or overdue by 0 day(s)');
  await page.locator('#serviceCurrentKm').fill('4000');
  await expect(page.locator('#serviceDueOut')).toBeEmpty();
  await page.locator('#serviceDueBtn').click();
  await expect(page.locator('#serviceDueOut')).toContainText('below the last service');
  const details = await page.evaluate(() => {
    const inputs = { lastKm: '', currentKm: '', intervalKm: '', lastDate: '2023-01-31', asOfDate: '2023-03-01', intervalMonths: '1' };
    const nonLeap = calculateServiceDue(inputs);
    const impossible = (() => { try { serviceDate('2024-02-30', 'Date'); return false; } catch (_) { return true; } })();
    return { nonLeap, impossible };
  });
  expect(details.nonLeap.date).toEqual({ next: '2023-02-28', remainingDays: -1, due: true });
  expect(details.impossible).toBe(true);
});

test('service template requires explicit model and task; preserves uncertainty and does not execute HTML', async ({ page }) => {
  await openTools(page);
  await page.locator('#workshopService summary').click();
  const template = { motorcycles: [
    { name: 'Example <img src=x onerror=alert(1)>', description: 'Synthetic, no fitment claim', tasks: [
      { name: 'Oil', description: 'Synthetic oil task', km: 500, months: 6, intervalKm: 6000, intervalMonths: 12, notes: '<script>unsafe</script>' },
      { name: 'One-off', description: 'No repeat interval', km: 1000 },
      { name: 'Questionable interval', description: 'Review source', intervalKm: 1000, intervalMonths: 6000 },
    ] },
  ] };
  await page.locator('#serviceTemplateFile').setInputFiles({ name: 'example.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(template)) });
  await expect(page.locator('#serviceTemplateOut')).toContainText('1 model(s) loaded');
  await expect(page.locator('#serviceUseIntervals')).toBeDisabled();
  await page.locator('#serviceTemplateModel').selectOption('0');
  await page.locator('#serviceTemplateTask').selectOption('0');
  await expect(page.locator('#serviceTemplateOut')).toContainText('Initial: 500 km, 6 months');
  await expect(page.locator('#serviceTemplateOut')).toContainText('<script>unsafe</script>');
  await expect(page.locator('#serviceTemplateOut script')).toHaveCount(0);
  await expect(page.locator('#serviceIntervalKm')).toHaveValue('');
  await page.locator('#serviceUseIntervals').click();
  await expect(page.locator('#serviceIntervalKm')).toHaveValue('6000');
  await expect(page.locator('#serviceIntervalMonths')).toHaveValue('12');
  await expect(page.locator('#serviceLastKm')).toHaveValue('');
  await page.locator('#serviceLastKm').fill('1000');
  await page.locator('#serviceCurrentKm').fill('2000');
  await page.locator('#serviceLastDate').fill('2025-01-01');
  await page.locator('#serviceAsOfDate').fill('2025-03-01');
  await page.locator('#serviceDueBtn').click();
  await expect(page.locator('#serviceDueOut')).toContainText('example.json');
  await expect(page.locator('#serviceDueOut')).toContainText('fitment not verified');
  await page.locator('#serviceIntervalKm').fill('7000');
  await page.locator('#serviceDueBtn').click();
  await expect(page.locator('#serviceDueOut')).toContainText('Intervals entered manually');
  await page.locator('#serviceTemplateTask').selectOption('1');
  await expect(page.locator('#serviceUseIntervals')).toBeDisabled();
  await page.locator('#serviceTemplateTask').selectOption('2');
  await expect(page.locator('#serviceTemplateOut')).toContainText('exceeds the worksheet limit');
  await expect(page.locator('#serviceUseIntervals')).toBeDisabled();
  await page.locator('#serviceTemplateFile').setInputFiles({ name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from('{"motorcycles":[{}]}') });
  await expect(page.locator('#serviceTemplateOut')).toContainText('invalid name');
  await expect(page.locator('#serviceUseIntervals')).toBeDisabled();
});

test('local manual search is literal, source-hashed, escaped, and cleared on request', async ({ page }) => {
  await openTools(page);
  const text = 'Page one: M10x1.25 torque.\fPage two: M10x1.25 <img src=x onerror=alert(1)>.';
  const hash = createHash('sha256').update(text).digest('hex');
  const posts = [];
  page.on('request', (request) => { if (request.method() === 'POST') posts.push(request.url()); });
  await page.locator('#manualTextFile').setInputFiles({ name: 'my-manual.txt', mimeType: 'text/plain', buffer: Buffer.from(text) });
  await expect(page.locator('#manualTextStatus')).toContainText(hash);
  await page.locator('#manualTextQuery').fill('M10x1.25');
  await page.locator('#manualTextSearch').click();
  await expect(page.locator('#manualTextOut')).toContainText('2 literal match(es)');
  await expect(page.locator('#manualTextOut')).toContainText('Text segment 2');
  await expect(page.locator('#manualTextOut')).toContainText('not verified PDF page numbers');
  await expect(page.locator('#manualTextOut img')).toHaveCount(0);
  expect(posts).toEqual([]);
  const literal = await page.evaluate(() => ({
    metacharacters: searchManualText({ text: 'C++ [x] and a.b' }, 'C++ [x]').matches.length,
    noWildcard: searchManualText({ text: 'axb' }, 'a.b').matches.length,
    unicodeOffset: searchManualText({ text: 'İ'.repeat(120) + ' target' }, 'target').matches[0].excerpt,
    bounded: searchManualText({ text: 'x '.repeat(101) }, 'x'),
  }));
  expect(literal.metacharacters).toBe(1);
  expect(literal.noWildcard).toBe(0);
  expect(literal.unicodeOffset).toContain('target');
  expect(literal.bounded.matches).toHaveLength(100);
  expect(literal.bounded.truncated).toBe(true);
  await page.locator('#manualTextQuery').fill('not found');
  await expect(page.locator('#manualTextOut')).toBeEmpty();
  await page.locator('#manualTextSearch').click();
  await expect(page.locator('#manualTextOut')).toContainText('0 literal match(es)');
  await page.locator('#manualTextClear').click();
  await expect(page.locator('#manualTextSearch')).toBeDisabled();
  await expect(page.locator('#manualTextStatus')).toHaveText('No manual loaded.');
  await page.locator('#manualTextFile').setInputFiles({ name: 'manual.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4') });
  await expect(page.locator('#manualTextStatus')).toContainText('not a PDF');
  await expect(page.locator('#manualTextSearch')).toBeDisabled();
});

test('workshop reference tools fit a narrow screen', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await openTools(page);
  await expect(page.locator('#workshopService')).toBeVisible();
  await expect(page.locator('#workshopManual')).toBeVisible();
  await page.locator('#manualTextFile').setInputFiles({ name: 'example.txt', mimeType: 'text/plain', buffer: Buffer.from('search sample') });
  await expect(page.locator('#manualTextSearch')).toBeEnabled();
  await page.locator('#manualTextQuery').fill('sample');
  await page.locator('#manualTextSearch').click();
  await expect(page.locator('#manualTextOut')).toContainText('1 literal match(es)');
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
});

test('Honda decoder is offline, rejects bad checksums and preserves raw bytes', async ({ page }) => {
  await openTools(page);
  await page.setViewportSize({ width: 375, height: 812 });
  const requests = [];
  page.on('request', (req) => { if (req.method() === 'POST') requests.push(req.url()); });
  // Synthetic frames, not the upstream README's inconsistent examples.
  const frame = (bytes) => [...bytes, (-bytes.reduce((a, b) => a + b, 0)) & 255]
    .map((b) => b.toString(16).padStart(2, '0')).join(' ');
  const sensor = frame([2, 22, 0x71, 0x10, 0x2a, 0x30, 0xd4, 0x87, 0x2c, 0x87, 0x9f, 0x3c, 0xe0, 0x5d, 0xff, 0xff, 0x8e, 0x7a, 0x12, 0x0a, 0x80]);
  const status = frame([2, 10, 0x71, 0xd1, 1, 0, 0, 0, 1]);
  const badExample = '02 0A 71 D1 00 00 00 00 01 22';
  const badSensors = '02 16 71 10 2A 30 D4 87 2C 87 9F 3C E0 5D FF FF 8E 7A 12 0A 80 52';
  await page.locator('#hondaFrames').fill([sensor, status, badExample, badSensors, '<img src=x>'].join('\n'));
  await page.locator('#hondaDecode').click();
  const out = page.locator('#hondaOut');
  await expect(out).toContainText('RPM: 10800 rpm');
  await expect(out).toContainText('TPS: 84.375 %');
  await expect(out).toContainText('neutral or clutch');
  await expect(out).toContainText(sensor);
  await expect(out).toContainText('Checksum mismatch; not decoded.');
  await expect(out).toContainText('Use complete space-separated hex bytes only.');
  await expect(out.locator('img')).toHaveCount(0);
  expect(requests).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.locator('#hondaFrames').fill('02 16 71 10');
  await expect(out).toBeEmpty();
  await page.locator('#hondaDecode').click();
  await expect(out).toContainText('Not a complete Honda table response');
  await page.locator('#hondaClear').click();
  await expect(out).toBeEmpty();
});

test('hosted demo never turns the Honda research entry into a Honda simulator', async ({ page }) => {
  await page.goto('/web/index.html');
  await expect(page.locator('#connTitle')).toBeVisible();
  // The hosted garage remains the Moto Guzzi virtual tour; exercise the demo API
  // directly to ensure a crafted selection cannot simulate the research bike.
  const result = await page.evaluate(async () => {
    const post = async (url, body) => {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      return { status: r.status, body: await r.json() };
    };
    const vehicle = { make: 'Honda', model: 'CBR600RR', year: 2005 };
    return {
      mismatch: await post('/api/select', { ...vehicle, ecu: '5am' }),
      select: await post('/api/select', vehicle),
      connect: await post('/api/connect', {}),
      existing: await post('/api/select', { make: 'Moto Guzzi', model: 'Griso 1200 8V', year: 2012 }),
      existingConnect: await post('/api/connect', {}),
      relabel: await post('/api/select', vehicle),
      status: await (await fetch('/api/status')).json(),
    };
  });
  expect(result.mismatch.status).toBe(400);
  expect(result.select.status).toBe(200);
  expect(result.select.body.ecu.capabilities).toEqual([]);
  expect(result.select.body.notices.map((n) => n.text).join(' ')).toContain('No diagnostic operations are exposed');
  expect(result.connect.status).toBe(400);
  expect(result.connect.body.error).toContain('No matching simulator');
  expect(result.existing.status).toBe(200);
  expect(result.existingConnect.status).toBe(200);
  expect(result.relabel.status).toBe(400);
  expect(result.relabel.body.error).toContain('disconnect the current session');
  expect(result.status.selection.make).toBe('Moto Guzzi');
});

test('multi-brand research decoders validate framing and remain local', async ({ page }) => {
  await openTools(page);
  const posts = [];
  page.on('request', (req) => { if (req.method() === 'POST') posts.push(req.url()); });
  const toHex = (bytes) => bytes.map((b) => b.toString(16).padStart(2, '0')).join(' ');
  const checksummed = (b) => toHex([...b, b.reduce((a, x) => a + x, 0) & 255]);
  const profile = page.locator('#multiResearchProfile');
  const input = page.locator('#multiResearchFrames');
  const out = page.locator('#multiResearchOut');

  await profile.selectOption('kawasaki_er6n');
  const kawa = checksummed([0x80, 0xf1, 0x11, 4, 0x61, 9, 40, 0]);
  await input.fill(kawa + '\n' + kawa.replace(/..$/, '00') + '\n' + checksummed([0x80, 0xf1, 0x11, 3, 0x7f, 0x21, 0x10]));
  await page.locator('#multiResearchDecode').click();
  await expect(out).toContainText('Engine speed candidate: 4000 rpm');
  await expect(out).toContainText('Checksum mismatch');
  await expect(out).toContainText('Only positive 0x61 responses');
  await expect(out).toContainText(kawa);

  await profile.selectOption('suzuki_sv650ak7');
  await expect(out).toBeEmpty();
  const suzuki = [0x80, 0xf1, 0x12, 0x34, 0x61, 0x08, ...Array(50).fill(0)];
  suzuki[17] = 40; suzuki[19] = 100; suzuki[21] = 90; suzuki[22] = 60; suzuki[24] = 150; suzuki[26] = 3;
  await input.fill(checksummed(suzuki));
  await page.locator('#multiResearchDecode').click();
  await expect(out).toContainText('RPM candidate: 2760 rpm');
  await expect(out).toContainText('gear/status byte: 3');
  await expect(out).toContainText('other sources differ');

  await profile.selectOption('triumph_daytona');
  await input.fill(checksummed([0x48, 0x6b, 0xd1, 0x41, 0x0c, 0x3e, 0x80]));
  await page.locator('#multiResearchDecode').click();
  await expect(out).toContainText('Engine speed: 4000 rpm');

  await profile.selectOption('harley_vpw');
  await input.fill('01 02 03 C1\n01 02 03 1B\n31 32 33 34 35 36 37 38 39 4B');
  await page.locator('#multiResearchDecode').click();
  await expect(out).toContainText('J1850 CRC matches');
  await expect(out).toContainText('J1850 CRC mismatch');

  await profile.selectOption('bmw_r1300gs');
  await input.fill('10C#00003E\n2D2#2C\n2D0#00000000000000\n800#0102\n10C#00\n<script>alert(1)</script>');
  await page.locator('#multiResearchDecode').click();
  await expect(out).toContainText('engine speed candidate: 3968 rpm');
  await expect(out).toContainText('left: true · right: true · brake: true');
  await expect(out).toContainText('high-beam flash candidate: true');
  await expect(out).toContainText('Only 11-bit classic CAN data frames');
  await expect(out).toContainText('insufficient payload');
  await expect(out.locator('script')).toHaveCount(0);
  expect(posts).toEqual([]);
  await page.locator('#multiResearchClear').click();
  await expect(out).toBeEmpty();
});

test('Yamaha checksum research reads a synthetic file locally without writing', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await openTools(page);
  const posts = [];
  page.on('request', (req) => { if (req.method() === 'POST') posts.push(req.url()); });
  const bytes = Buffer.alloc(0x100000);
  bytes.write('ABCDY123', bytes.length - 16, 'ascii');
  bytes[bytes.length - 6] = 0x64; bytes[bytes.length - 5] = 0x02;
  let sum = 0;
  for (let i = 0; i < bytes.length; i += 2) sum = (sum + bytes.readUInt16BE(i)) & 0xffff;
  bytes.writeUInt16BE((0x5aa5 - sum) & 0xffff, bytes.length - 8);
  const hash = createHash('sha256').update(bytes).digest('hex');
  await page.locator('#yamahaVariant').selectOption('mt_1m');
  await page.locator('#yamahaImage').setInputFiles({ name: 'synthetic.bin', mimeType: 'application/octet-stream', buffer: bytes });
  await page.locator('#yamahaInspect').click();
  await expect(page.locator('#yamahaOut')).toContainText('Sum matches source target');
  await expect(page.locator('#yamahaOut')).toContainText('not flash or safety approval');
  await expect(page.locator('#yamahaOut')).toContainText(hash);
  await expect(page.locator('#yamahaOut')).toContainText('ABCDY123 (not proof of fitment)');
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.locator('#yamahaVariant').selectOption('mt07_2020');
  await expect(page.locator('#yamahaOut')).toBeEmpty();
  await page.locator('#yamahaInspect').click();
  await expect(page.locator('#yamahaOut')).toContainText('requires exactly 917504 bytes');
  await page.locator('#yamahaImage').setInputFiles({ name: 'invalid.bin', mimeType: 'application/octet-stream', buffer: Buffer.alloc(0xe0000) });
  await page.locator('#yamahaInspect').click();
  await expect(page.locator('#yamahaOut')).toContainText('trailer does not match');
  expect(posts).toEqual([]);
  await page.locator('#yamahaClear').click();
  await expect(page.locator('#yamahaOut')).toBeEmpty();
});

test('bundled service references load locally with attribution and explicit review', async ({ page }) => {
  await openTools(page);
  await page.locator('#workshopService summary').click();
  const selector = page.locator('#bundledServiceTemplate');
  const posts = [];
  page.on('request', (req) => { if (req.method() === 'POST') posts.push(req.url()); });
  for (const file of ['honda_africa_twin.json', 'ktm_790_adventure.json', 'royal_enfield_himalayan.json', 'suzuki_dr650.json', 'suzuki_drz400.json']) {
    await selector.selectOption(file);
    await expect(page.locator('#serviceTemplateOut')).toContainText('CC BY-SA 4.0');
    await expect(page.locator('#serviceTemplateOut')).toContainText('1 model(s) loaded');
    await page.locator('#serviceTemplateModel').selectOption('0');
    await expect(page.locator('#serviceTemplateTask option').nth(1)).toHaveCount(1);
    await expect(page.locator('#serviceUseIntervals')).toBeDisabled();
  }
  await selector.selectOption('honda_africa_twin.json');
  await expect(page.locator('#serviceTemplateOut')).toContainText('1 model(s) loaded');
  await page.locator('#serviceTemplateModel').selectOption('0');
  await page.locator('#serviceTemplateTask').selectOption('0');
  await expect(page.locator('#serviceTemplateOut')).toContainText('Honda Africa Twin');
  await expect(page.locator('#serviceIntervalKm')).toHaveValue('');
  await page.locator('#serviceUseIntervals').click();
  await expect(page.locator('#serviceIntervalKm')).toHaveValue('12800');
  await page.locator('#serviceLastKm').fill('1000');
  await page.locator('#serviceCurrentKm').fill('2000');
  await page.locator('#serviceDueBtn').click();
  await expect(page.locator('#serviceDueOut')).toContainText('Motorcycle Service DB');
  await expect(page.locator('#serviceDueOut')).toContainText('fitment not verified');
  expect(posts).toEqual([]);
});

test('CFMoto MSE6 inspection reports synthetic records without writing images', async ({ page }) => {
  await openTools(page);
  const posts = [];
  page.on('request', (r) => { if (r.method() === 'POST') posts.push(r.url()); });
  const bytes = Buffer.alloc(0x140500);
  bytes.fill(1, 0x1000, 0x3000);
  bytes.writeUInt32BE(0x1000, 0x140000); bytes.writeUInt32BE(0x3000, 0x140004);
  const sum = 0x101 * 0x1000;
  bytes.writeUInt32BE(sum, 0x140008); bytes.writeUInt32BE((~sum) >>> 0, 0x14000c);
  const file = page.locator('#mseImage');
  await file.setInputFiles({ name: 'synthetic-cfmoto.bin', mimeType: 'application/octet-stream', buffer: bytes });
  await page.locator('#mseInspect').click();
  await expect(page.locator('#mseOut')).toContainText('1 candidate record(s)');
  await expect(page.locator('#mseOut')).toContainText('computed 0x00101000 · match');
  await expect(page.locator('#mseOut')).toContainText('not ECU identification or flash approval');
  bytes[0x1000] = 2;
  await file.setInputFiles({ name: 'synthetic-bad.bin', mimeType: 'application/octet-stream', buffer: bytes });
  await expect(page.locator('#mseOut')).toBeEmpty();
  await page.locator('#mseInspect').click();
  await expect(page.locator('#mseOut')).toContainText('mismatch');
  await file.setInputFiles({ name: 'short.bin', mimeType: 'application/octet-stream', buffer: Buffer.alloc(10) });
  await page.locator('#mseInspect').click();
  await expect(page.locator('#mseOut')).toContainText('Image must be between');
  await page.locator('#mseClear').click();
  await expect(page.locator('#mseOut')).toBeEmpty();
  expect(posts).toEqual([]);
});

test('hosted garage offers the Honda XDF for offline research, not a Honda simulator', async ({ page }) => {
  await page.goto('/web/index.html');
  await page.selectOption('#makeSelect', 'Honda');
  await page.selectOption('#modelSelect', 'CBR1000RR (US)');
  await page.selectOption('#yearSelect', '2012');
  await expect(page.locator('#selectOfflineBtn')).toBeEnabled();
  await page.locator('#selectOfflineBtn').click();
  await expect(page.locator('#firmware')).toBeVisible();
  await expect(page.locator('#connTitle')).toHaveText('Not connected');
  await expect(page.locator('#xdfSelect')).toHaveValue('CBR1000RR_2012_US.xdf');
  await expect(page.locator('#xdfFitNote')).toContainText('ECU identity not established');
  await expect(page.locator('#mapChecksumProvider option[value="honda-cbr1000rr-2012-us-a01-v1"]')).toHaveCount(0);
  await page.locator('[data-view="garage"]').click();
  await expect(page.locator('#connectBtn')).toBeDisabled();
});
