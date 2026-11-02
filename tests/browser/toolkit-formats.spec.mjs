import { test, expect } from '@playwright/test';

/* Batch 2: the external-format tools — MLVLG logs, DBC databases, OBD-II
 * transcripts and tune-file diffs. Every case runs in the hosted demo with data
 * the test supplies, so none of it depends on an adapter. */

/** Build a minimal MLVLG v1 log: one u16 channel scaled 0.1, three records. */
function buildMlg() {
  const fieldName = (text) => {
    const bytes = Buffer.alloc(34);
    Buffer.from(text, 'utf8').copy(bytes);
    return bytes;
  };
  const field = Buffer.alloc(55);
  field.writeUInt8(2, 0);                       // U16
  fieldName('RPM').copy(field, 1);
  Buffer.from('rpm\0\0\0\0\0\0\0').copy(field, 35);
  field.writeUInt8(0, 45);                      // display: Float
  field.writeFloatBE(0.1, 46);                  // scale
  field.writeFloatBE(0, 50);                    // transform
  field.writeUInt8(2, 54);                      // digits

  const info = Buffer.from('synthetic log', 'utf8');
  const headerLength = 6 + 2 + 4 + 2 + 4 + 2 + 2 + 55;
  const infoStart = headerLength;               // no bit-field names
  const dataStart = infoStart + info.length + 1;

  const header = Buffer.alloc(headerLength);
  header.write('MLVLG\0', 0, 'binary');
  header.writeInt16BE(1, 6);
  header.writeInt32BE(1700000000, 8);
  header.writeInt16BE(infoStart, 12);
  header.writeInt32BE(dataStart, 14);
  header.writeInt16BE(7, 18);                   // record length
  header.writeInt16BE(1, 20);                   // one channel
  field.copy(header, 22);

  const records = Buffer.alloc(3 * 7);
  [1000, 2000, 3000].forEach((rpm, index) => {
    const at = index * 7;
    records.writeUInt8(0, at);                  // data block
    records.writeUInt8(index, at + 1);          // counter
    records.writeUInt16BE(index * 100, at + 2); // stamp
    records.writeUInt16BE(rpm, at + 4);
    records[at + 6] = 0;                        // checksum byte, skipped
  });
  return Buffer.concat([header, info, Buffer.from([0]), records]);
}

const DBC = [
  'VERSION ""',
  '',
  'NS_ :',
  '',
  'BS_:',
  '',
  'BU_: ECU Logger',
  '',
  'BO_ 595 SoC_Percentage: 8 ECU',
  ' SG_ SoC : 0|8@1+ (1,0) [0|100] "%" Logger',
  ' SG_ RemainingChargeTime : 24|8@1+ (1,0) [0|255] "min" Logger',
  '',
  'BO_ 599 EngineData: 8 ECU',
  ' SG_ EngineSpeed : 0|16@1+ (0.25,0) [0|16383] "rpm" Logger',
  ' SG_ Coolant : 16|8@1+ (1,-40) [-40|215] "C" Logger',
  ' SG_ Gear : 24|4@1+ (1,0) [0|15] "" Logger',
  ' SG_ Torque : 32|12@0- (0.5,-100) [-100|150] "Nm" Logger',
  '',
  'VAL_ 599 Gear 0 "Neutral" 1 "First" 2 "Second" ;',
  'CM_ BO_ 599 "Synthetic engine broadcast for the test.";',
  'CM_ SG_ 599 Gear "Four-bit gear selector.";',
  '',
  'BO_ 512 Scaled: 8 ECU',
  ' SG_ Wide : 7|16@0+ (1,0) [0|65535] "" Logger',
  ' SG_ Float : 16|32@1+ (1,0) [0|0] "" Logger',
  'SIG_VALTYPE_ 512 Float : 4;',
  '',
].join('\r\n');

test.beforeEach(async ({ page }) => {
  await page.goto('/web/index.html');
  await page.locator('[data-view="tools"]').click();
  await expect(page.locator('#tools')).toBeVisible();
});

test('the bench lists all four batch-2 tools in the general group', async ({ page }) => {
  await expect(page.locator('#toolsCountBadge')).toHaveText('33 of 33 tools');
  await expect(page.locator('[data-brand-heading="general"] [data-brand-count]')).toContainText('20 tools');
  for (const id of ['mlgLogPanel', 'dbcPanel', 'obdExplorerPanel', 'tuneDiffPanel']) {
    await expect(page.locator(`#${id}`)).toBeAttached();
    await expect(page.locator(`#${id}`)).toHaveAttribute('data-tool-brand', 'general');
  }
});

test('the MLVLG importer reads channels, scaling and records', async ({ page }) => {
  const log = await page.evaluate((bytes) => {
    const parsed = window.gobMlg.parseMlg(new Uint8Array(bytes));
    return {
      format: parsed.format,
      version: parsed.version,
      info: parsed.info,
      channels: parsed.fields.map((field) => ({ name: field.name, units: field.units, kind: field.kind, scale: field.scale })),
      records: parsed.records,
      csv: window.gobMlg.mlgCsv(parsed, { limit: 2 }),
    };
  }, [...buildMlg()]);

  expect(log.format).toBe('MLVLG');
  expect(log.version).toBe(1);
  expect(log.info).toBe('synthetic log');
  expect(log.channels).toEqual([{ name: 'RPM', units: 'rpm', kind: 'uint16', scale: 0.10000000149011612 }]);
  expect(log.records).toHaveLength(3);
  expect(log.records[1].RPM).toBeCloseTo(200, 4);   // 2000 raw × 0.1
  expect(log.csv.split('\n')[0]).toContain('RPM [rpm]');
  expect(log.csv.split('\n')).toHaveLength(3);      // header + the two requested rows

  // A file with the wrong magic is refused by name, not guessed at.
  const error = await page.evaluate(() => {
    try {
      window.gobMlg.parseMlg(new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]));
      return 'no error';
    } catch (raised) {
      return raised.message;
    }
  });
  expect(error).toContain('Not an MLVLG log');

  await page.locator('#mlgFile').setInputFiles({
    name: 'synthetic.mlg', mimeType: 'application/octet-stream', buffer: buildMlg(),
  });
  await page.locator('#mlgParse').click();
  await expect(page.locator('#mlgMeta')).toContainText('3 record(s)');
  await expect(page.locator('#mlgOut')).toContainText('RPM');
  await expect(page.locator('#mlgOut')).toContainText('synthetic log');
});

test('the DBC importer parses messages, signals, value tables and comments', async ({ page }) => {
  const dbc = await page.evaluate((text) => {
    const parsed = window.gobDbc.parseDbc(text);
    return {
      messages: parsed.messages.map((message) => ({
        id: message.id,
        name: message.name,
        dlc: message.dlc,
        comment: message.comment,
        signals: message.signals.map((signal) => ({
          name: signal.name,
          start: signal.start,
          length: signal.length,
          littleEndian: signal.littleEndian,
          signed: signal.signed,
          factor: signal.factor,
          offset: signal.offset,
          values: [...signal.values],
          comment: signal.comment,
          float: signal.float,
        })),
      })),
      warnings: parsed.warnings,
      signalCount: parsed.signalCount,
    };
  }, DBC);

  expect(dbc.messages.map((message) => message.name)).toEqual(['Scaled', 'SoC_Percentage', 'EngineData']);
  expect(dbc.signalCount).toBe(8);
  const engine = dbc.messages.find((message) => message.name === 'EngineData');
  expect(engine.comment).toContain('Synthetic engine broadcast');
  const gear = engine.signals.find((signal) => signal.name === 'Gear');
  expect(gear.values).toEqual([[0, 'Neutral'], [1, 'First'], [2, 'Second']]);
  expect(gear.comment).toContain('Four-bit gear selector');
  const torque = engine.signals.find((signal) => signal.name === 'Torque');
  expect(torque.littleEndian).toBe(false);
  expect(torque.signed).toBe(true);
  const floatSignal = dbc.messages.find((message) => message.name === 'Scaled').signals.find((s) => s.name === 'Float');
  expect(floatSignal.float).toBe(true);
});

test('the DBC decoder handles Intel, Motorola, signed and float signals', async ({ page }) => {
  const decoded = await page.evaluate((text) => {
    const dbc = window.gobDbc.parseDbc(text);
    // 0x0257: rpm = 4000 (raw 16000 = 0x3E80), coolant 90 C (130 = 0x82), gear 2
    const engine = new Uint8Array([0x80, 0x3e, 0x82, 0x02, 0, 0, 0, 0]);
    // Torque is a big-endian 12-bit signed signal at start bit 32. Encode raw
    // 100 the way a DBC author writes it: MSB first, walking down the byte and
    // jumping from bit 0 to bit 7 of the next one.
    const torqueFrame = new Uint8Array(8);
    const encodeMotorola = (start, length, raw) => {
      const bits = [];
      for (let i = length - 1; i >= 0; i -= 1) bits.push(Number((BigInt(raw) >> BigInt(i)) & 1n));
      let position = start;
      bits.forEach((bit) => {
        torqueFrame[position >> 3] |= bit << (position & 7);
        position = (position & 7) === 0 ? position + 15 : position - 1;
      });
    };
    encodeMotorola(32, 12, 100);
    // Float message: 0x00ff then float 12.5
    const floatFrame = new Uint8Array(8);
    floatFrame[0] = 0x00;
    floatFrame[1] = 0xff;
    new DataView(floatFrame.buffer).setFloat32(2, 12.5, true);
    const byName = (messageName) => dbc.messages.find((message) => message.name === messageName);
    const engineDecoded = window.gobDbc.decodeDbcMessage(byName('EngineData'), engine);
    return {
      engine: Object.fromEntries(engineDecoded.signals.map((signal) => [signal.name, { value: signal.value, mapped: signal.mapped }])),
      torque: Object.fromEntries(window.gobDbc.decodeDbcMessage(byName('EngineData'), torqueFrame).signals.map((s) => [s.name, s.value])),
      float: Object.fromEntries(window.gobDbc.decodeDbcMessage(byName('Scaled'), floatFrame).signals.map((s) => [s.name, s.value])),
      soc: Object.fromEntries(window.gobDbc.decodeDbcMessage(byName('SoC_Percentage'), new Uint8Array([80, 0, 0, 30, 0, 0, 0, 0])).signals.map((s) => [s.name, s.value])),
    };
  }, DBC);

  expect(decoded.engine.EngineSpeed.value).toBeCloseTo(4000, 6);
  expect(decoded.engine.Coolant.value).toBeCloseTo(90, 6);
  expect(decoded.engine.Gear.value).toBe(2);
  expect(decoded.engine.Gear.mapped).toBe('Second');
  expect(decoded.torque.Torque).toBeCloseTo(-50, 6);   // signed Motorola, scale 0.5, offset -100
  expect(decoded.float.Float).toBeCloseTo(12.5, 5);
  expect(decoded.float.Wide).toBe(255);                 // Motorola 16-bit starting at bit 7
  expect(decoded.soc.SoC).toBe(80);
  expect(decoded.soc.RemainingChargeTime).toBe(30);
});

test('the DBC decoder reports unknown identifiers instead of inventing values', async ({ page }) => {
  const result = await page.evaluate((text) => {
    const dbc = window.gobDbc.parseDbc(text);
    const log = 'can0 257#803E820200000000\ncan0 1A0#DEADBEEF\nnot a frame';
    const decoded = window.gobDbc.decodeDbcLog(dbc, log);
    return {
      frames: decoded.frames.length,
      unknown: decoded.unknown,
      errors: decoded.errors.length,
      csvFirst: window.gobDbc.dbcCsv(decoded).split('\n')[0],
    };
  }, DBC);
  expect(result.frames).toBe(1);
  expect(result.unknown).toEqual([{ id: 0x1a0, count: 1 }]);
  expect(result.errors).toBe(1);
  expect(result.csvFirst).toContain('EngineSpeed');
});

test('the OBD explorer decodes Mode 01, Mode 03 and Mode 09 from a transcript', async ({ page }) => {
  const result = await page.evaluate(() => {
    const text = [
      'ELM327 v1.5',
      '>010C',
      '41 0C 1A F8',
      '>010D',
      '41 0D 3C',
      '>0105',
      '41 05 82',
      '>03',
      '43 01 01 33 00 00 00 00',
      '>0902',
      '49 02 01 4D 45 33 31 41 42',
      '49 02 02 43 44 31 32 33 34',
      '49 02 03 35 36 37 38 39 30',
      '0: 49 02 04 31 32 33 34 35',
      'NO DATA',
    ].join('\n');
    const decoded = window.gobObd.decodeObd(text);
    return {
      readings: decoded.readings.map((reading) => ({ pid: reading.pid, value: reading.value, name: reading.name })),
      dtcs: decoded.dtcs,
      vin: decoded.vin,
      requests: decoded.requests.length,
      summary: decoded.summary,
    };
  });

  const byPid = (pid) => result.readings.find((reading) => reading.pid === pid);
  expect(byPid(0x0c).value).toBeCloseTo(1726, 3);   // (0x1A<<8 | 0xF8)/4
  expect(byPid(0x0d).value).toBe(60);
  expect(byPid(0x05).value).toBe(90);
  expect(result.dtcs).toEqual([{ code: 'P0133', kind: 'stored' }]);
  expect(result.vin.startsWith('ME31AB')).toBe(true);
  expect(result.requests).toBe(4);
  expect(result.summary.dtcs).toBe(1);
});

test('the OBD explorer strips ISO-TP framing from a candump capture', async ({ page }) => {
  const result = await page.evaluate(() => {
    const text = [
      'can0 7E8#04410C1AF8CCCCCC',      // single frame: 41 0C 1A F8
      'can0 7E8#03410D3CCCCCCCCC',
      'can0 7E8 [8] 04 41 05 82 CC CC CC CC',
    ].join('\n');
    const decoded = window.gobObd.decodeObd(text);
    return decoded.readings.map((reading) => [reading.pid, reading.value]);
  });
  expect(result).toEqual([[0x0c, 1726], [0x0d, 60], [0x05, 90]]);
});

test('the Royal Enfield profile lists the documented channels and estimates a gear', async ({ page }) => {
  const profile = await page.evaluate(() => {
    const entry = window.gobObd.profiles['royal-enfield-650'];
    return { pids: entry.pids, gear: entry.gear, note: entry.note };
  });
  expect(profile.pids).toEqual([0x0c, 0x0d, 0x11, 0x0b, 0x0f, 0x5c, 0x04]);
  expect(profile.gear).toBe(true);

  await page.locator('#obdProfile').selectOption('royal-enfield-650');
  await expect(page.locator('#obdPidList')).toContainText('Engine speed');
  await expect(page.locator('#obdProfileNote')).toContainText('Interceptor 650');

  const gear = await page.evaluate(() => window.gobObd.estimateObdGear({
    rpm: 3000, speedKph: 60, tyreCircumference: 2.008, primary: 1, finalDrive: 1,
    ratios: [9, 7.5, 6, 5, 4.2],
  }));
  // 60 km/h on a 2.008 m tyre is about 498 wheel rpm, so 3000 rpm is 6.02:1 —
  // the third ratio, 6.0, is the only one within 25 %.
  expect(gear.gear).toBe(3);
  expect(gear.error).toBeLessThan(0.01);

  const noRatios = await page.evaluate(() => window.gobObd.estimateObdGear({ rpm: 3000, speedKph: 60 }));
  expect(noRatios).toBeNull();
});

test('the tune diff compares MSQ constants and tables', async ({ page }) => {
  const result = await page.evaluate(() => {
    const a = [
      '<msq><constant name="reqFuel" value="12.5"/><constant name="injOpen" value="1.0"/>',
      '<constant name="idleRpm" value="1200"/>',
      '<table name="veTable1Tbl"><x>10,20,30</x><y>1,2</y><z>50,51,52,53,54,55</z></table>',
      '<table name="advTable1"><x>10,20</x><y>1</y><z>5,6</z></table></msq>',
    ].join('');
    const b = [
      '<msq><constant name="reqFuel" value="13.5"/><constant name="injOpen" value="1.0"/>',
      '<table name="veTable1Tbl"><x>10,20,30</x><y>1,2</y><z>50,55,60,53,54,55</z></table>',
      '<table name="newTable"><x>1</x><y>1</y><z>9</z></table></msq>',
    ].join('');
    const parsedA = window.gobTuneDiff.parseTuneText('a.msq', a);
    const parsedB = window.gobTuneDiff.parseTuneText('b.msq', b);
    const diff = window.gobTuneDiff.diffTunes(parsedA, parsedB);
    return { kind: diff.kind, constants: diff.constants, tables: diff.tables, counts: [diff.changed, diff.added, diff.removed] };
  });

  expect(result.kind).toBe('msq');
  expect(result.constants.changed.map((entry) => entry.key)).toEqual(['reqFuel']);
  expect(result.constants.changed[0].delta).toBeCloseTo(1, 9);
  expect(result.constants.removed.map((entry) => entry.key)).toEqual(['idleRpm']);
  expect(result.tables.changed.map((table) => table.name)).toEqual(['veTable1Tbl']);
  expect(result.tables.changed[0].cells.map((cell) => [cell.row, cell.col])).toEqual([[0, 1], [0, 2]]);
  expect(result.tables.changed[0].maxDelta).toBeCloseTo(8, 9);
  expect(result.tables.added.map((table) => table.name)).toEqual(['newTable']);
  expect(result.counts).toEqual([2, 1, 2]);
});

test('the tune diff compares CSV log columns by row', async ({ page }) => {
  const result = await page.evaluate(() => {
    const a = 'time,rpm,afr\n0,1000,14.7\n1,1100,14.6\n2,1200,14.5\n';
    const b = 'time,rpm,afr\n0,1000,14.7\n1,1150,13.9\n2,1200,14.5\n';
    const diff = window.gobTuneDiff.diffTunes(
      window.gobTuneDiff.parseTuneText('a.csv', a),
      window.gobTuneDiff.parseTuneText('b.csv', b),
    );
    return {
      kind: diff.kind,
      rows: diff.rowsCompared,
      columns: diff.columns.map((column) => ({ name: column.name, changed: column.changed, maxDelta: column.maxDelta })),
      changedColumns: diff.changedColumns,
    };
  });
  expect(result.kind).toBe('csv');
  expect(result.rows).toBe(3);
  expect(result.changedColumns).toBe(2);
  expect(result.columns.find((column) => column.name === 'rpm').maxDelta).toBe(50);
  expect(result.columns.find((column) => column.name === 'afr').maxDelta).toBeCloseTo(0.7, 6);
  expect(result.columns.find((column) => column.name === 'time').changed).toBe(0);
});

test('the tune diff panel refuses mismatched formats and explains itself', async ({ page }) => {
  await page.locator('#tuneDiffA').setInputFiles({
    name: 'a.msq', mimeType: 'text/plain', buffer: Buffer.from('<msq><constant name="reqFuel" value="12"/></msq>'),
  });
  await page.locator('#tuneDiffB').setInputFiles({
    name: 'b.csv', mimeType: 'text/plain', buffer: Buffer.from('time,rpm\n0,1000\n'),
  });
  await page.locator('#tuneDiffBtn').click();
  await expect(page.locator('#tuneDiffMeta')).toContainText('A CSV log can only be compared with another CSV log');
});
