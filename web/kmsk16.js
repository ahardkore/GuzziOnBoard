/* Keihin KMSK16 K-Line capture decoder — KTM, Husqvarna 449/511, CCM 450.
 *
 * The Python twin of this file is guzzionboard/protocol/kmsk16.py; the two
 * carry the same identifier table and the same rules, and
 * tests/test_kmsk16.py compares them entry by entry so neither can drift.
 *
 * Evidence: gobftald/CCM450-diag @ 43104d2. That repository has no licence
 * file, so nothing here is copied from it — the frame layout, service set,
 * identifiers, ranges and enumerations are facts, reimplemented from its
 * published descriptions with attribution (docs/KMSK16_KLINE.md).
 *
 * What it does: paste frames that were already captured, get the channel each
 * data identifier carries. Nothing is transmitted, no routine is run, no fault
 * is cleared and nothing is written: a decoded byte is a research lead, not a
 * fitment claim.
 */
'use strict';

/* Keihin's own data identifiers, not SAE PIDs. `scale` exists only where a
 * value can be derived; `inferred: true` means it was worked out from the
 * declared range or an example capture in the source rather than stated, and
 * the panel prints `basis` beside every derived number. `conflict` records an
 * identifier whose source disagrees with itself — both readings, no resolution.
 */
const KMSK16_DATA_IDS = [
  { id: 0x0000, name: 'Throttle position sensor voltage', job: 'STATUS_THROTTLE_POSITION_SENSOR_VOLTAGE', symbol: 'THAD', unit: 'V', low: 0.0, high: 5.0, scale: 0.004887585532746823, inferred: true, basis: '10-bit ADC: the source\'s own example is 0x03FF = 1023' },
  { id: 0x0001, name: 'Throttle position (angle channel)', job: 'STATUS_THROTTLE_ANGLE_VOLTAGE', symbol: 'THM', unit: 'deg', low: 0.0, high: 80.0, formula: 'THM / 80 deg × 100 %', scale: 1, inferred: true, basis: 'declared range 0–80 degrees, so one count is one degree' },
  { id: 0x0002, name: 'Manifold pressure sensor voltage', job: 'STATUS_INTAKE_MANIFOLD_PRESSURE_SENSOR_VOLTAGE', symbol: 'voltage PM1', unit: 'V', low: 0.0, high: 5.0, scale: 0.004887585532746823, inferred: true, basis: '10-bit ADC: the source\'s example is 0x03FA = 1018' },
  { id: 0x0003, name: 'Manifold absolute pressure', job: 'STATUS_INTAKE_MANIFOLD_PRESSURE', symbol: 'PM1', unit: 'mbar', low: 0.0, high: 65535.0, scale: 1, inferred: true, basis: 'declared range covers the 16-bit span exactly' },
  { id: 0x0006, name: 'Battery voltage at the A/D converter', job: 'STATUS_BATTERY_VOLTAGE_AD_CONVERTER', symbol: 'UBAT-AD', unit: 'V', low: 0.0, high: 5.0, scale: 0.1, inferred: true, basis: 'the source\'s own example: 0x0075 = 117 → 11.7 V', conflict: 'the declared range says 0–5 V, which cannot hold its own example of 11.7 V — treat the range as wrong and the example as right' },
  { id: 0x0007, name: 'Battery voltage (scaled channel)', job: 'STATUS_BATTERY_VOLTAGE', symbol: 'UBAT', unit: 'V', low: 0.0, high: 5.0, scale: 0.1, inferred: true, basis: 'same 0.1 V/count as 0x0006; the source\'s example is 0x0070 = 112', conflict: 'declared 0–5 V range against a 16-bit channel; the scaling the name refers to lives in the ECU, not in this table' },
  { id: 0x0008, name: 'Coolant temperature sensor voltage', job: 'STATUS_ENGINE_TEMPERATURE_SENSOR_VOLTAGE', symbol: 'voltage TW', unit: 'V', low: 0.0, high: 5.0, scale: 0.004887585532746823, inferred: true, basis: '10-bit ADC: the source\'s example is 0x03FF = 1023' },
  { id: 0x0009, name: 'Engine coolant temperature', job: 'STATUS_ENGINE_TEMPERATURE', symbol: 'TW', unit: 'degC', low: -40.0, high: 215.0, scale: 1, bias: -40.0, inferred: true, basis: '255-count span from −40 to 215 °C, one count per degree', note: 'a 255-wide range on a 2-byte response: the second byte is not explained by the source, so it is shown and not used' },
  { id: 0x0010, name: 'Intake air temperature sensor voltage', job: 'STATUS_INTAKE_AIR_TEMPERATURE_SENSOR_VOLTAGE', symbol: 'voltage TA', unit: 'V', low: 0.0, high: 5.0, scale: 0.004887585532746823, inferred: true, basis: '10-bit ADC: the source\'s example is 0x03FF = 1023' },
  { id: 0x0011, name: 'Intake air temperature', job: 'STATUS_INTAKE_AIR_TEMPERATURE', symbol: 'TA', unit: 'degC', low: -40.0, high: 215.0, scale: 1, bias: -40.0, inferred: true, basis: 'same −40 °C offset as the coolant channel', note: 'a 255-wide range on a 2-byte response; the second byte is unexplained' },
  { id: 0x0012, name: 'Lambda sensor voltage', job: 'STATUS_LAMBDA_SENSOR_VOLTAGE', symbol: 'VHG1', unit: 'V', low: 0.0, high: 5.0, scale: 0.004887585532746823, inferred: true, basis: '10-bit ADC: the source\'s example is 0x03F6 = 1014' },
  { id: 0x0018, name: 'Second throttle actuator voltage', job: 'STATUS_THROTTLE_SENSOR_2_VOLTAGE', unit: 'V', low: 0.0, high: 5.0, scale: 0.004887585532746823, inferred: true, basis: 'declared 0–5 V range and a 10-bit ADC elsewhere' },
  { id: 0x0040, name: 'Neutral switch', job: 'STATUS_NEUTRALSWITCH', symbol: 'NEUTRAL', kind: 'int', enum: {0x0000: 'Neutral', 0x00FF: 'Gear engaged'} },
  { id: 0x0053, name: 'Sport switch input', job: 'STATUS_SPORTSWITCH_INPUT', symbol: 'MAPCHG', kind: 'int', enum: {0x0000: 'Standard map', 0x00FF: 'Sport map'} },
  { id: 0x0060, name: 'Fuel pump relay', job: 'FUEL_PUMP_RELAY_STATUS', symbol: 'FLPR', kind: 'int', enum: {0x0000: 'OFF', 0x00FF: 'ON'} },
  { id: 0x0064, name: 'Lambda heater', job: 'STATUS_LAMBDA_SENSOR_HEATING', symbol: 'HG1HT', kind: 'int', enum: {0x0000: 'OFF', 0x00FF: 'ON'} },
  { id: 0x0100, name: 'Engine speed', job: 'STATUS_ENGINE_SPEED', symbol: 'NE', unit: 'rpm', low: 0.0, high: 16384.0, scale: 0.25, inferred: true, basis: '16384 rpm is exactly a quarter of the 16-bit span' },
  { id: 0x0102, name: 'Short-term fuel trim', job: 'STATUS_LAMBDA_CONTROL_FACTOR', symbol: 'MHG1', unit: 'ratio', low: 0.0, high: 2.0, scale: 3.0517578125e-05, inferred: true, basis: 'declared 0–2 range over the 16-bit span' },
  { id: 0x0107, name: 'Calculated load', job: 'STATUS_CALCULATED_ENGINE_LOAD', symbol: 'CLV', unit: '%', low: 0.0, high: 100.0, formula: 'CLV = (PM1M / 10103 mbar) × 100 %', note: 'not computed here: the source does not say which identifier supplies PM1M, and guessing one would invent a number' },
  { id: 0x0110, name: 'Injector on-time (bank 1)', job: 'STATUS_INJECTION_DURATION', symbol: 'TIOUT1', unit: 'us', low: 0.0, high: 65535.0, scale: 1, inferred: true, basis: 'declared range covers the 16-bit span exactly' },
  { id: 0x0120, name: 'Ignition timing (bank 1)', job: 'STATUS_FIRING_ANGLE', symbol: 'IGAB1', unit: 'deg', low: -64.0, high: 64.0, scale: 0.5, bias: -64.0, inferred: true, basis: 'the source\'s own example is 0x0080 = 128 → 0°, so 0.5 °/count with a −64° offset' },
  { id: 0x0130, name: 'Ignition coil dwell (bank 1)', job: 'STATUS_IGNITION_CLOSING_TIME', symbol: 'IGDWELL', unit: 'us', low: 0.0, high: 65535.0, scale: 1, inferred: true, basis: 'declared range covers the 16-bit span exactly' },
  { id: 0x0140, name: 'Throttle flap angle reference', job: 'STATUS_THROTTLE_FLAP_ANGLE_REFERENCE', symbol: 'THREF', unit: 'deg', low: -3276.8, high: 3276.8, scale: 0.1, inferred: true, basis: '±3276.8 over a signed 16-bit span is 0.1 °/count' },
  { id: 0x0142, name: 'Lambda adaption, part load', job: 'STATUS_LAMBDA_ADAPTION_PART_LOAD', symbol: 'MREFHG1', unit: 'ratio', low: 0.0, high: 2.0, scale: 3.0517578125e-05, inferred: true, basis: 'declared 0–2 range over the 16-bit span' },
  { id: 0x0143, name: 'Lambda adaption, idle', job: 'STATUS_LAMBDA_ADAPTION_IDLE', symbol: 'MREFHG1ID', unit: 'ratio', low: 0.0, high: 2.0, scale: 3.0517578125e-05, inferred: true, basis: 'declared 0–2 range over the 16-bit span' },
  { id: 0x0149, name: 'Lambda adaption, displayed value', job: 'STATUS_LAMBDA_ADAPTION_SHOW', symbol: 'MRFH1DEC', unit: 'ratio', low: 0.0, high: 2.0, scale: 3.0517578125e-05, inferred: true, basis: 'declared 0–2 range over the 16-bit span' },
  { id: 0x0170, name: 'Second throttle actual angle', job: 'STATUS_THROTTLE_FLAP_ANGLE_2_ACTUAL_VALUE', symbol: 'STHAD', unit: 'deg', low: 0.0, high: 80.0, formula: '(STHAD − STHADL) / (STHADH / STHADL) × 100 %', note: 'as written the expression divides by a ratio of two A/D values, which is not a fraction of span; the dimensionally consistent reading (STHAD − STHADL) / (STHADH − STHADL) needs 0x0172 and 0x0173 as well, and is shown separately and labelled as rewritten' },
  { id: 0x0171, name: 'Second throttle target angle', job: 'STATUS_THROTTLE_FLAP_ANGLE_2_SETPOINT', symbol: 'STHTRG', unit: 'deg', low: 0.0, high: 80.0, scale: 1, inferred: true, basis: 'declared range 0–80 degrees' },
  { id: 0x0172, name: 'Second throttle reference, low', job: 'STATUS_THROTTLE_2_REF_VOLTAGE_MIN', symbol: 'STHADLL', unit: 'V', low: 0.0, high: 5.0, scale: 0.004887585532746823, inferred: true, basis: 'declared 0–5 V and the source\'s example 0x00E3 = 227' },
  { id: 0x0173, name: 'Second throttle reference, high', job: 'STATUS_THROAT_VALVE_2_REF_VOLTAGE_MAX', symbol: 'STDHADHH', unit: 'V', low: 0.0, high: 5.0, scale: 0.004887585532746823, inferred: true, basis: 'declared 0–5 V and the source\'s example 0x03A1 = 929' },
  { id: 0x0174, name: 'Second throttle actuator steps, maximum', job: 'STATUS_THROTTLE_VALVE_ACTUATOR_2_STEPS_MAX', symbol: 'STHSTEPH', unit: 'steps', low: 0.0, high: 32767.0, scale: 1, inferred: true, basis: 'declared range is a count, one per step' },
  { id: 0x0185, name: 'Purge valve duty cycle', job: 'STATUS_PURGE_VALVE_DUTY', unit: '%', low: 0.0, high: 100.0, note: 'the source lists a 0–100 % range and, next to it, an error text for an unsupported sub-function — so some ECUs answer this identifier with a negative response instead of a value' },
  { id: 0x0500, name: 'Sport switch memory', job: 'STATUS_SPORTSWITCH_MEMORY', symbol: 'RaceMAP SW', kind: 'int', enum: {0x0000: 'Standard map', 0x00FF: 'Sport map'} },
  { id: 0x0501, name: 'Over-rev counter, total', job: 'STATUS_OVERSPEED_COUNTER_SPECIAL', unit: 'min', low: 0.0, high: 196605.0, scale: 3, inferred: true, basis: '196605 minutes is exactly three times the 16-bit span' },
  { id: 0x0502, name: 'Over-rev counter, area 1', job: 'STATUS_OVERSPEED_COUNTER_RANGE1', unit: 's', low: 0.0, high: 6553.5, conflict: 'two ranges in the same source: 0–6553.5 s (0.1 s/count) in the job entry, 0–196605 min (3 min/count) in the identifier summary. Both are recorded; no value is derived from either.' },
  { id: 0x0503, name: 'Over-rev counter, area 2', job: 'STATUS_OVERSPEED_COUNTER_RANGE2', unit: 's', low: 0.0, high: 6553.5, conflict: 'two ranges in the same source: 0–6553.5 s (0.1 s/count) in the job entry, 0–196605 min (3 min/count) in the identifier summary. Both are recorded; no value is derived from either.' },
  { id: 0x0504, name: 'Over-rev counter, area 3', job: 'STATUS_OVERSPEED_COUNTER_RANGE3', unit: 's', low: 0.0, high: 6553.5, conflict: 'two ranges in the same source: 0–6553.5 s (0.1 s/count) in the job entry, 0–196605 min (3 min/count) in the identifier summary. Both are recorded; no value is derived from either.' },
  { id: 0x0505, name: 'Over-rev counter, area 4', job: 'STATUS_OVERSPEED_COUNTER_RANGE4', unit: 's', low: 0.0, high: 6553.5, conflict: 'two ranges in the same source: 0–6553.5 s (0.1 s/count) in the job entry, 0–196605 min (3 min/count) in the identifier summary. Both are recorded; no value is derived from either.' },
  { id: 0x0506, name: 'Over-rev counter, area 5', job: 'STATUS_OVERSPEED_COUNTER_RANGE5', unit: 's', low: 0.0, high: 6553.5, conflict: 'two ranges in the same source: 0–6553.5 s (0.1 s/count) in the job entry, 0–196605 min (3 min/count) in the identifier summary. Both are recorded; no value is derived from either.' },
  { id: 0x0507, name: 'Over-rev counter, area 6', job: 'STATUS_OVERSPEED_COUNTER_RANGE6', unit: 's', low: 0.0, high: 6553.5, conflict: 'two ranges in the same source: 0–6553.5 s (0.1 s/count) in the job entry, 0–196605 min (3 min/count) in the identifier summary. Both are recorded; no value is derived from either.' },
  { id: 0x0508, name: 'Over-rev counter, area 7', job: 'STATUS_OVERSPEED_COUNTER_RANGE7', unit: 's', low: 0.0, high: 6553.5, conflict: 'two ranges in the same source: 0–6553.5 s (0.1 s/count) in the job entry, 0–196605 min (3 min/count) in the identifier summary. Both are recorded; no value is derived from either.' },
  { id: 0x0509, name: 'Over-rev counter, area 8', job: 'STATUS_OVERSPEED_COUNTER_RANGE8', unit: 's', low: 0.0, high: 6553.5, conflict: 'two ranges in the same source: 0–6553.5 s (0.1 s/count) in the job entry, 0–196605 min (3 min/count) in the identifier summary. Both are recorded; no value is derived from either.' },
  { id: 0x0510, name: 'Over-rev counter, area 9', job: 'STATUS_OVERSPEED_COUNTER_RANGE9', unit: 's', low: 0.0, high: 6553.5, conflict: 'two ranges in the same source: 0–6553.5 s (0.1 s/count) in the job entry, 0–196605 min (3 min/count) in the identifier summary. Both are recorded; no value is derived from either.' },
  { id: 0x1000, name: 'Test stamp', job: 'READ_TEST_STAMP', kind: 'bytes', note: 'programming-session stamp, not a measurement' },
  { id: 0x1001, name: 'DTC environmental condition: engine speed', job: 'STATUS_ERROR_MEMORY_ENVIRONMENTAL_CONDITIONS', kind: 'bytes', note: 'a sub-identifier used inside a fault record, not a live channel' },
  { id: 0x2500, name: 'ZIF backup read', job: 'ZIF_BACKUP_READ', symbol: 'PRBHW*B', kind: 'bytes', note: 'programming reference block' },
  { id: 0x2501, name: 'Flash times', job: 'FLASH_TIMES_READING', symbol: 'Times', kind: 'bytes', note: 'programming geometry' },
  { id: 0x2502, name: 'Hardware reference', job: 'READ_HARDWARE_REFERENCE', symbol: 'HWREF', kind: 'bytes', note: 'ASCII hardware reference' },
  { id: 0x2503, name: 'Program reference', job: 'BAUDRATE_62500', symbol: 'ProgrammReferenz', kind: 'bytes', note: '12 bytes of ASCII, laid out ZZZ PPP x V BB x h in the source' },
  { id: 0x2504, name: 'Data reference', job: 'READ_DATA_REFERENCE', symbol: 'DREF', kind: 'bytes', note: 'ASCII data reference' },
  { id: 0x2506, name: 'Maximum flash block length', job: 'FLASH_BLOCK_LENGTH_READING', symbol: 'MaximumBlockLength', kind: 'bytes', note: 'programming geometry, reported with the service identifier included' },
];

const KMSK16_BY_ID = new Map(KMSK16_DATA_IDS.map((entry) => [entry.id, entry]));

/* $31 routine identifiers the job description names. The two read-only ones
 * ask the ECU about its own coding checksums; the rest are names only, because
 * a job name is not a verified sequence. */
const KMSK16_ROUTINES = {
  0x0102: 'CheckCodingChecksum — application code (read-only)',
  0x0104: 'CheckCodingChecksum — calibration data (read-only)',
  0x0A00: 'CheckProgrammingStatus (read-only)',
  0xA600: 'Purge control valve ON/OFF test',
  0x9000: 'FLASH_DELETE_K16 — erase (not implemented anywhere in this project)',
};

const KMSK16_SERVICES = {
  0x10: ['StartDiagnosticSession', 0x50],
  0x11: ['EcuReset', 0x51],
  0x14: ['ClearDiagnosticInformation', 0x54],
  0x17: ['ReadStatusOfDiagnosticTroubleCodes', 0x57],
  0x18: ['ReadDiagnosticTroubleCodesByStatus', 0x58],
  0x1A: ['ReadEcuIdentification', 0x5A],
  0x20: ['StopDiagnosticSession', 0x60],
  0x22: ['ReadDataByCommonIdentifier', 0x62],
  0x23: ['ReadMemoryByAddress', 0x63],
  0x27: ['SecurityAccess', 0x67],
  0x31: ['StartRoutineByLocalIdentifier', 0x71],
  0x32: ['StopRoutineByLocalIdentifier', 0x72],
  0x34: ['RequestDownload', 0x74],
  0x35: ['RequestUpload', 0x75],
  0x36: ['TransferData', 0x76],
  0x37: ['RequestTransferExit', 0x77],
  0x3B: ['WriteDataByLocalIdentifier', 0x7B],
  0x3D: ['WriteMemoryByAddress', 0x7D],
  0x3E: ['TesterPresent', 0x7E],
  0x81: ['StartCommunication', 0xC1],
  0x82: ['StopCommunication', 0xC2],
};

/* Positive response to service; ISO 14230-3. Same table as the NRC texts in
 * guzzionboard/protocol/kwp2000.py, so the two sides cannot disagree about a
 * refusal. */
const KMSK16_RESPONSE_TO_SERVICE = {};
Object.entries(KMSK16_SERVICES).forEach(([service, [, positive]]) => {
  KMSK16_RESPONSE_TO_SERVICE[positive] = Number(service);
});

const KMSK16_NRC = {
  0x10: 'General reject',
  0x11: 'Service not supported by this ECU',
  0x12: 'Sub-function not supported',
  0x21: 'ECU busy - repeat request',
  0x22: 'Conditions not correct (check ignition, engine state)',
  0x31: 'Request out of range',
  0x33: 'Security access denied',
  0x35: 'Invalid security key',
  0x36: 'Exceeded number of security attempts',
  0x37: 'Security time delay not expired',
  0x40: 'Download not accepted',
  0x50: 'Upload not accepted',
  0x71: 'Transfer suspended',
  0x78: 'Response pending',
  0x7F: 'Service not supported in active session',
};

/* ---- framing (mirrors guzzionboard/protocol/kwp2000.py) ------------------ */

function kmsk16Hex(value, width = 2) {
  return value.toString(16).toUpperCase().padStart(width, '0');
}

function kmsk16Checksum(bytes) {
  return bytes.reduce((sum, byte) => (sum + byte) & 0xFF, 0);
}

/** One captured line to bytes.
 *
 * A token that is not a hex byte is an error, not something to skip: silently
 * dropping `ZZ` or the `can0` of a candump line would turn a frame that was
 * never transmitted into a frame that decodes. Same rule as the Python twin.
 */
function parseKmsk16Line(line) {
  let text = String(line ?? '').trim();
  text = text.replace(/^(RX|TX|rx|tx)\s*:/, '').replace(/^([<>])\s*/, '');
  const tokens = text.replace(/,/g, ' ').split(/\s+/).filter(Boolean);
  if (!tokens.length) throw new Error('no hex bytes in this line');
  const compact = [];
  tokens.forEach((token) => {
    const body = token.slice(0, 2).toLowerCase() === '0x' ? token.slice(2) : token;
    if (!body.length || !/^[0-9a-fA-F]+$/.test(body)) {
      throw new Error(`'${token}' is not a hex byte`);
    }
    if (body.length <= 2) {
      compact.push(body.padStart(2, '0'));
    } else if (body.length % 2 === 0) {
      for (let index = 0; index < body.length; index += 2) compact.push(body.slice(index, index + 2));
    } else {
      throw new Error(`'${token}' has an odd number of hex digits (${body.length})`);
    }
  });
  return compact.map((token) => parseInt(token, 16));
}

/** Decode one complete KWP2000 frame, checking its checksum. */
function kmsk16Frame(bytes) {
  const format = bytes[0];
  const addressed = (format & 0x80) !== 0;
  let header = addressed ? 3 : 1;
  let length = format & 0x3F;
  if (length === 0) {
    length = bytes[header];
    header += 1;
  }
  const total = header + length + 1;
  if (bytes.length !== total) {
    throw new Error(`frame length mismatch: expected ${total}, got ${bytes.length}`);
  }
  const computed = kmsk16Checksum(bytes.slice(0, -1));
  if (computed !== bytes[bytes.length - 1]) {
    throw new Error(`checksum 0x${kmsk16Hex(bytes[bytes.length - 1])}, computed 0x${kmsk16Hex(computed)}`
      + '; checksum should be 0x' + kmsk16Hex(computed));
  }
  return {
    format,
    target: addressed ? bytes[1] : null,
    source: addressed ? bytes[2] : null,
    payload: bytes.slice(header, header + length),
  };
}

function kmsk16Number(value) {
  if (Number.isInteger(value)) return String(value);
  return String(Number(value.toFixed(4)));
}

function kmsk16Value(value, unit) {
  const text = kmsk16Number(value);
  return unit && unit !== 'ratio' ? `${text} ${unit}` : text;
}

/* ---- data identifiers --------------------------------------------------- */

function kmsk16DecodeDataId(payload) {
  const lines = [];
  if (!payload.length) throw new Error('positive response carries no data identifier');
  if (payload.length < 2) throw new Error('a data identifier is two bytes; this response has one');
  const id = (payload[0] << 8) | payload[1];
  const body = payload.slice(2);
  const entry = KMSK16_BY_ID.get(id);
  const name = entry ? entry.name : 'not in the KMSK16 table';
  const result = { headline: `0x${kmsk16Hex(id, 4)} · ${name}`, lines, identifier: id };
  if (!entry) {
    lines.push(`Data identifier 0x${kmsk16Hex(id, 4)} is not one of the ${KMSK16_DATA_IDS.length} the job description names.`);
    if (body.length) lines.push('Payload bytes: ' + body.map((b) => kmsk16Hex(b)).join(' '));
    return result;
  }
  if (entry.job) {
    lines.push(`Job: ${entry.job}` + (entry.symbol ? ` · symbol ${entry.symbol}` : ''));
  }
  if (!body.length) {
    lines.push('The ECU answered with the identifier and no value bytes.');
    return result;
  }
  lines.push('Payload: ' + body.map((b) => kmsk16Hex(b)).join(' '));

  if (entry.kind === 'bytes') {
    const ascii = body.map((b) => (b >= 32 && b < 127 ? String.fromCharCode(b) : '·')).join('');
    lines.push(`ASCII: ${ascii}`);
    if (entry.note) lines.push(entry.note);
    return result;
  }
  if (body.length < 2) {
    lines.push('Only one value byte arrived; the table describes a 16-bit value, so nothing is derived from half of it.');
    return result;
  }
  const raw = (body[0] << 8) | body[1];
  result.raw = raw;
  lines.push(`Raw: 0x${kmsk16Hex(raw, 4)} = ${raw} (big-endian: both descriptions that mention byte order say high byte first)`);

  if (entry.enum) {
    const state = entry.enum[raw];
    result.state = state || null;
    lines.push(state
      ? `State: ${state}`
      : `State: not one of the declared values (0x0000 / 0x00FF) — ${raw} is reported as-is`);
  }
  if (entry.formula) lines.push(`Formula in the source: ${entry.formula}`);
  if (entry.scale !== undefined) {
    const value = raw * entry.scale + (entry.bias || 0);
    result.value = value;
    lines.push(`Value (${entry.inferred ? 'inferred' : 'stated'}): ${kmsk16Value(value, entry.unit)} — ${entry.basis}`);
  }
  if (entry.low !== undefined && entry.high !== undefined) {
    lines.push(`Declared range: ${kmsk16Number(entry.low)}–${kmsk16Number(entry.high)}`
      + (entry.unit && entry.unit !== 'ratio' ? ` ${entry.unit}` : ''));
    if (!entry.conflict && (raw < entry.low || raw > entry.high)) {
      lines.push(`Out of range: the raw value ${raw} is outside the declared range, so the identifier,`
        + ' the ECU variant or the scaling is wrong somewhere. Nothing is corrected here.');
    }
  }
  if (entry.conflict) lines.push(`Source conflict: ${entry.conflict}`);
  if (entry.note) lines.push(entry.note);
  return result;
}

function kmsk16DecodeRoutine(data) {
  const lines = [];
  if (!data.length) return { headline: 'routine accepted, no result bytes', lines };
  const two = data.length >= 2 ? (data[0] << 8) | data[1] : null;
  let identifier = KMSK16_ROUTINES[two] ? two : null;
  let name = identifier !== null ? KMSK16_ROUTINES[identifier] : null;
  if (name === null && KMSK16_ROUTINES[data[0]]) {
    identifier = data[0];
    name = KMSK16_ROUTINES[identifier];
  }
  if (name) lines.push(`Routine 0x${kmsk16Hex(identifier, 4)}: ${name}`);
  else lines.push('Routine identifier not in the KMSK16 list: ' + data.map((b) => kmsk16Hex(b)).join(' '));
  const result = identifier === two ? data.slice(2) : data.slice(1);
  if (result.length) {
    lines.push('Result bytes: ' + result.map((b) => kmsk16Hex(b)).join(' ')
      + ' (the job description does not give their layout)');
  }
  return { headline: `routine response · ${name || 'unknown routine'}`, lines };
}

/** Decode one captured request or response. */
function decodeKmsk16Line(line) {
  let bytes;
  try {
    bytes = parseKmsk16Line(line);
  } catch (error) {
    return { ok: false, line, headline: 'rejected', reason: error.message, lines: [] };
  }
  if (bytes.length < 4) {
    return { ok: false, line, headline: 'rejected', lines: [],
      reason: `a KMSK16 frame is at least 5 bytes; this is ${bytes.length}` };
  }
  let frame;
  try {
    frame = kmsk16Frame(bytes);
  } catch (error) {
    return { ok: false, line, headline: 'rejected', lines: [], reason: error.message };
  }
  const payload = frame.payload;
  const service = payload.length ? payload[0] : -1;
  const data = payload.slice(1);
  const lines = [];
  if (frame.target !== null && ![0x12, 0xF1].includes(frame.target)) {
    lines.push(`Addresses: target 0x${kmsk16Hex(frame.target)}, source 0x${kmsk16Hex(frame.source)}`
      + ' — the source uses 0x12 (ECU) and 0xF1 (tester)');
  }

  if (service === 0x7F) {
    if (data.length < 2) {
      return { ok: false, line, headline: 'negative response', lines,
        reason: 'a negative response is 7F <service> <code>; this one is short' };
    }
    const rejected = data[0];
    const code = data[1];
    const label = KMSK16_SERVICES[rejected] ? KMSK16_SERVICES[rejected][0] : 'unknown service';
    const text = KMSK16_NRC[code] || `unknown NRC 0x${kmsk16Hex(code)}`;
    lines.push(`Service 0x${kmsk16Hex(rejected)} (${label}) was rejected: ${text} (0x${kmsk16Hex(code)})`);
    return { ok: true, line, headline: 'negative response', lines, identifier: null };
  }

  if (service === 0x62) {
    let decoded;
    try {
      decoded = kmsk16DecodeDataId(data);
    } catch (error) {
      return { ok: false, line, headline: 'rejected', lines, reason: error.message };
    }
    return { ok: true, line, headline: decoded.headline, lines: lines.concat(decoded.lines),
      identifier: decoded.identifier, raw: decoded.raw, value: decoded.value, state: decoded.state };
  }

  if (service === 0x71 || service === 0x72) {
    const routed = kmsk16DecodeRoutine(data);
    return { ok: true, line, headline: routed.headline, lines: lines.concat(routed.lines) };
  }

  if (KMSK16_RESPONSE_TO_SERVICE[service] !== undefined) {
    const request = KMSK16_RESPONSE_TO_SERVICE[service];
    const label = KMSK16_SERVICES[request][0];
    lines.push(`Positive response to 0x${kmsk16Hex(request)} ${label}`);
    if (data.length) lines.push('Payload: ' + data.map((b) => kmsk16Hex(b)).join(' '));
    return { ok: true, line, headline: `0x${kmsk16Hex(service)} · ${label}`, lines };
  }

  if (KMSK16_SERVICES[service]) {
    const label = KMSK16_SERVICES[service][0];
    lines.push(`Request: 0x${kmsk16Hex(service)} ${label}`);
    if (service === 0x22) {
      if (data.length >= 2) {
        const id = (data[0] << 8) | data[1];
        const entry = KMSK16_BY_ID.get(id);
        lines.push(`Asks for 0x${kmsk16Hex(id, 4)}` + (entry ? ` · ${entry.name}` : ' · not in the table'));
      } else {
        lines.push('The request carries no two-byte data identifier.');
      }
    } else if (service === 0x31 || service === 0x32) {
      if (data.length >= 2) {
        const id = (data[0] << 8) | data[1];
        lines.push(`Routine 0x${kmsk16Hex(id, 4)}: `
          + (KMSK16_ROUTINES[id] || KMSK16_ROUTINES[data[0]] || 'not in the KMSK16 list'));
      }
    } else if (service === 0x27) {
      lines.push('Security access — the key is not in this project, and this panel never sends anything.');
    } else if (service === 0x3E) {
      lines.push('Tester present — keeps the session alive.');
    }
    return { ok: true, line, headline: `request · ${label}`, lines };
  }

  lines.push(`Service 0x${kmsk16Hex(service)} is not one the KMSK16 job description names.`);
  if (data.length) lines.push('Payload: ' + data.map((b) => kmsk16Hex(b)).join(' '));
  return { ok: true, line, headline: `unknown service 0x${kmsk16Hex(service)}`, lines };
}

/** Decode a whole paste; the second-throttle percentage needs three frames. */
function decodeKmsk16Capture(text) {
  const lines = String(text ?? '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (lines.length > 100) throw new Error('limit: 100 frames per decode');
  const frames = lines.map((line) => decodeKmsk16Line(line));
  const accepted = frames.filter((frame) => frame.ok).length;
  const rawById = {};
  frames.forEach((frame) => {
    if (frame.identifier !== undefined && frame.identifier !== null && frame.raw !== undefined) {
      rawById[frame.identifier] = frame.raw;
    }
  });
  const derived = [];
  const had = {};
  [0x0170, 0x0172, 0x0173].forEach((id) => { if (rawById[id] !== undefined) had[id] = rawById[id]; });
  const have = Object.keys(had).length;
  if (have === 3) {
    const span = had[0x0173] - had[0x0172];
    if (span > 0) {
      const percent = ((had[0x0170] - had[0x0172]) / span) * 100;
      derived.push('Derived across frames (rewritten, not quoted): second throttle at '
        + `${percent.toFixed(1)} % of its reference span, from 0x0170=${had[0x0170]}, `
        + `0x0172=${had[0x0172]}, 0x0173=${had[0x0173]} using `
        + '(STHAD − STHADL) / (STHADH − STHADL) × 100 %. The source writes the '
        + 'divisor as STHADH / STHADL, which would give a meaningless number.');
    } else {
      derived.push(`0x0173 (${had[0x0173]}) is not above 0x0172 (${had[0x0172]}), so the `
        + 'second-throttle reference span is empty and no percentage is derived.');
    }
  } else if (have) {
    const missing = [0x0170, 0x0172, 0x0173].filter((id) => had[id] === undefined)
      .map((id) => `0x${kmsk16Hex(id, 4)}`).join(', ');
    derived.push('Second-throttle percentage needs 0x0170, 0x0172 and 0x0173; this paste is missing '
      + `${missing}.`);
  }
  return { frames, derived, accepted, rejected: frames.length - accepted };
}

/* Reference rows for the panel: rendered from this table, so the panel cannot
 * advertise a formula the decoder does not implement. */
function kmsk16ReferenceRows() {
  return KMSK16_DATA_IDS.map((entry) => [
    `0x${kmsk16Hex(entry.id, 4)}`,
    entry.name + (entry.symbol ? ` · ${entry.symbol}` : ''),
    entry.enum
      ? Object.entries(entry.enum).map(([value, text]) => `${Number(value) === 0 ? '0x0000' : '0x00FF'} ${text}`).join(' · ')
      : entry.formula
        || (entry.scale !== undefined
          ? `${kmsk16Number(entry.scale)}${entry.bias ? ` · offset ${kmsk16Number(entry.bias)}` : ''}`
            + `${entry.unit && entry.unit !== 'ratio' ? ` ${entry.unit}/count` : ' per count'}`
            + (entry.inferred ? ' (inferred)' : '')
          : 'raw bytes'),
    entry.low !== undefined ? `${kmsk16Number(entry.low)}–${kmsk16Number(entry.high)}` : '',
  ]);
}

if (typeof window !== 'undefined') {
  window.gobKmsk16 = {
    dataIds: KMSK16_DATA_IDS,
    routines: KMSK16_ROUTINES,
    services: KMSK16_SERVICES,
    nrc: KMSK16_NRC,
    parseLine: parseKmsk16Line,
    decodeLine: decodeKmsk16Line,
    decodeCapture: decodeKmsk16Capture,
    referenceRows: kmsk16ReferenceRows,
  };
}

/* ---- panel wiring ------------------------------------------------------- */

if (typeof document !== 'undefined') {
  const PANELS = [
    { prefix: 'ktm', title: 'KTM' },
    { prefix: 'husqvarna', title: 'Husqvarna' },
  ];
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));

  PANELS.forEach(({ prefix }) => {
    const refHost = document.getElementById(`${prefix}Kmsk16Ref`);
    if (refHost) {
      const rows = kmsk16ReferenceRows();
      refHost.innerHTML = '<div class="table-wrap"><table class="data"><thead><tr>'
        + '<th>Identifier</th><th>Channel</th><th>Value rule</th><th>Declared range</th>'
        + '</tr></thead><tbody>'
        + rows.map((row) => `<tr><td><code>${escapeHtml(row[0])}</code></td>`
          + `<td>${escapeHtml(row[1])}</td><td>${escapeHtml(row[2])}</td>`
          + `<td>${escapeHtml(row[3])}</td></tr>`).join('')
        + '</tbody></table></div>';
    }
    const button = document.getElementById(`${prefix}Kmsk16Decode`);
    if (!button) return;
    const input = document.getElementById(`${prefix}Kmsk16Frames`);
    const out = document.getElementById(`${prefix}Kmsk16Out`);
    const meta = document.getElementById(`${prefix}Kmsk16Meta`);
    const clear = document.getElementById(`${prefix}Kmsk16Clear`);
    const reset = () => {
      if (out) out.textContent = '';
      if (meta) meta.textContent = '';
    };
    if (input) input.addEventListener('input', reset);
    if (clear) clear.onclick = () => { if (input) input.value = ''; reset(); };
    button.onclick = () => {
      if (!input || !out) return;
      if (!input.value.trim()) {
        if (meta) meta.textContent = 'Paste at least one captured frame.';
        return;
      }
      let result;
      try {
        result = decodeKmsk16Capture(input.value);
      } catch (error) {
        if (meta) meta.textContent = error.message;
        return;
      }
      const blocks = result.frames.map((frame, index) => {
        const body = frame.ok
          ? [frame.headline].concat(frame.lines).join('\n')
          : `Rejected: ${frame.reason}`;
        return `Frame ${index + 1}: ${frame.line}\n${body}`;
      });
      if (result.derived.length) blocks.push(result.derived.join('\n'));
      out.textContent = blocks.join('\n\n');
      if (meta) {
        meta.textContent = `${result.accepted} of ${result.frames.length} frame(s) decoded`;
      }
    };
  });
}
