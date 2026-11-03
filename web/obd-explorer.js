/* OBD-II / EOBD explorer.
 *
 * Decodes Mode 01 live PIDs, Mode 03/07 stored and pending trouble codes and
 * Mode 09 VIN from text the operator already has: an ELM327 transcript (with or
 * without `>` prompts and `0:` frame numbers) or a candump capture of the
 * 0x7E8 diagnostic response. The PID scalings are the SAE J1979 formulae, not a
 * manufacturer's private table.
 *
 * The Royal Enfield 650 profile records which PIDs that source polls and how it
 * turns RPM and road speed into a gear (moca-owner-dev/RoyalEnfieldObd,
 * backend/obd.py, revision 2317442d813f, Copyright (c) 2026 David Moca, MIT —
 * see LICENSES/RoyalEnfieldObd-MIT.txt). The profile selects a reading list; it
 * claims no fitment and sends nothing.
 */
'use strict';

const OBD_MODES = {
  1: 'Current data',
  2: 'Freeze-frame data',
  3: 'Stored trouble codes',
  4: 'Clear codes (not sent by this tool)',
  5: 'Oxygen sensor results',
  6: 'On-board test results',
  7: 'Pending trouble codes',
  9: 'Vehicle information',
  10: 'Permanent trouble codes',
};

const OBD_PIDS = {
  0x04: { name: 'Calculated engine load', unit: '%', bytes: 1, decode: (b) => b[0] * 100 / 255 },
  0x05: { name: 'Engine coolant temperature', unit: '°C', bytes: 1, decode: (b) => b[0] - 40 },
  0x0B: { name: 'Intake manifold pressure', unit: 'kPa', bytes: 1, decode: (b) => b[0] },
  0x0C: { name: 'Engine speed', unit: 'rpm', bytes: 2, decode: (b) => (b[0] * 256 + b[1]) / 4 },
  0x0D: { name: 'Vehicle speed', unit: 'km/h', bytes: 1, decode: (b) => b[0] },
  0x0E: { name: 'Timing advance', unit: '° before TDC', bytes: 1, decode: (b) => b[0] / 2 - 64 },
  0x0F: { name: 'Intake air temperature', unit: '°C', bytes: 1, decode: (b) => b[0] - 40 },
  0x10: { name: 'Mass air flow', unit: 'g/s', bytes: 2, decode: (b) => (b[0] * 256 + b[1]) / 100 },
  0x11: { name: 'Throttle position', unit: '%', bytes: 1, decode: (b) => b[0] * 100 / 255 },
  0x14: {
    name: 'Oxygen sensor 1', unit: 'V / %', bytes: 2,
    decode: (b) => ({ voltage: b[0] / 200, trim: b[1] * 100 / 128 - 100 }),
    format: (value) => `${value.voltage.toFixed(3)} V · ${value.trim.toFixed(1)} % trim`,
  },
  0x1F: { name: 'Run time since engine start', unit: 's', bytes: 2, decode: (b) => b[0] * 256 + b[1] },
  0x21: { name: 'Distance travelled with MIL on', unit: 'km', bytes: 2, decode: (b) => b[0] * 256 + b[1] },
  0x2F: { name: 'Fuel tank level', unit: '%', bytes: 1, decode: (b) => b[0] * 100 / 255 },
  0x31: { name: 'Distance since codes cleared', unit: 'km', bytes: 2, decode: (b) => b[0] * 256 + b[1] },
  0x33: { name: 'Absolute barometric pressure', unit: 'kPa', bytes: 1, decode: (b) => b[0] },
  0x42: { name: 'Control module voltage', unit: 'V', bytes: 2, decode: (b) => (b[0] * 256 + b[1]) / 1000 },
  0x46: { name: 'Ambient air temperature', unit: '°C', bytes: 1, decode: (b) => b[0] - 40 },
  0x5B: { name: 'Hybrid battery remaining', unit: '%', bytes: 1, decode: (b) => b[0] * 100 / 255 },
  0x5C: { name: 'Engine oil temperature', unit: '°C', bytes: 1, decode: (b) => b[0] - 40 },
  0x5E: { name: 'Engine fuel rate', unit: 'L/h', bytes: 2, decode: (b) => (b[0] * 256 + b[1]) / 20 },
};

const OBD_PROFILES = {
  generic: {
    id: 'generic',
    label: 'Generic OBD-II (SAE J1979)',
    note: 'Every mode and PID here is the standard set. Nothing about a particular motorcycle is assumed.',
    pids: [0x04, 0x05, 0x0B, 0x0C, 0x0D, 0x0F, 0x10, 0x11, 0x1F, 0x2F, 0x42, 0x46],
    gear: false,
  },
  'royal-enfield-650': {
    id: 'royal-enfield-650',
    label: 'Royal Enfield 650 · documented OBD-II reading list',
    note: 'Source records this polling set on an Interceptor 650: RPM, speed, throttle, MAP, intake air, engine oil '
      + 'temperature and load, with a gear estimated from RPM and road speed. One owner\u2019s bike, not a fitment claim.',
    pids: [0x0C, 0x0D, 0x11, 0x0B, 0x0F, 0x5C, 0x04],
    gear: true,
    tyreCircumference: 2.008,
  },
};

function obdHexTokens(line) {
  const cleaned = String(line).replace(/\b(?:SEARCHING|BUS\s*INIT|NO\s*DATA|OK|STOPPED|ELM327[^\n]*)\b/gi, ' ');
  const tokens = cleaned.match(/\b[0-9A-Fa-f]{2}\b/g);
  return tokens ? tokens.map((token) => parseInt(token, 16)) : [];
}

function obdDtc(code1, code2) {
  const system = ['P', 'C', 'B', 'U'][(code1 >> 6) & 0x03];
  const digits = ((code1 & 0x3f) << 8) | code2;
  return `${system}${digits.toString(16).toUpperCase().padStart(4, '0')}`;
}

/** Decode a 43/47 response body into trouble codes. */
function obdDecodeDtcs(payload) {
  const codeCount = payload[1];
  const dtcs = [];
  for (let i = 2; i + 1 < payload.length; i += 2) {
    if (payload[i] === 0 && payload[i + 1] === 0) continue;
    dtcs.push(obdDtc(payload[i], payload[i + 1]));
  }
  return { count: codeCount, dtcs };
}

function obdDecodeMode1(pid, data) {
  const definition = OBD_PIDS[pid];
  if (!definition) return { pid, name: `PID 0x${pid.toString(16).toUpperCase().padStart(2, '0')} (not in the dictionary)`, value: null, unit: '', raw: data };
  if (data.length < definition.bytes) {
    return { pid, name: definition.name, value: null, unit: definition.unit, raw: data, note: 'short response' };
  }
  try {
    const value = definition.decode(data);
    return { pid, name: definition.name, value, unit: definition.unit, raw: data.slice(0, definition.bytes), format: definition.format };
  } catch (error) {
    return { pid, name: definition.name, value: null, unit: definition.unit, raw: data, note: error.message };
  }
}

/**
 * Split pasted text into OBD payloads.
 *
 * Accepts `41 0C 1A F8`, ELM327 transcripts with `>` prompts, `0:` frame
 * numbers and 7E8 headers, plus candump lines whose ISO-TP framing is removed.
 */
function obdPayloads(text) {
  const payloads = [];
  const requests = [];
  const ignored = [];
  const byId = new Map();

  String(text || '').split(/\r?\n/).forEach((rawLine, index) => {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) return;
    const isRequest = line.startsWith('>');
    const body = line.replace(/^>\s*/, '').replace(/^\d+\s*:\s*/, '').replace(/^0x/i, '');
    if (/^[0-9A-Fa-f]{4}$/.test(body) && isRequest) {
      const pid = parseInt(body.slice(2, 4), 16);
      requests.push({ line: index + 1, raw: body, pid, name: OBD_PIDS[pid]?.name || `PID 0x${body.slice(2, 4).toUpperCase()}` });
      return;
    }
    const frame = window.gobFrameLab?.parseCandumpLine(line);
    if (frame) {
      if (!byId.has(frame.identifier)) byId.set(frame.identifier, []);
      byId.get(frame.identifier).push({ data: frame.data, line: index + 1 });
      return;
    }
    const tokens = obdHexTokens(body);
    if (!tokens.length) {
      if (isRequest) return;
      ignored.push({ line: index + 1, text: line, why: 'no hex payload' });
      return;
    }
    let bytes = tokens;
    // A CAN identifier may lead the line: 7E8 04 41 0C 1A F8.
    if (bytes.length > 3 && ((bytes[0] === 0x7e8) || (bytes[0] >= 0x7e0 && bytes[0] <= 0x7ef))) {
      bytes = bytes.slice(1);
    }
    payloads.push({ bytes, line: index + 1, source: 'text' });
  });

  // Reassemble ISO-TP streams from candump captures. One identifier can carry
  // many independent answers (each a single frame) and one multi-frame answer,
  // so walk the frames in order instead of reassembling the whole group.
  byId.forEach((frames, identifier) => {
    const source = `can 0x${identifier.toString(16).toUpperCase()}`;
    let pending = null;
    frames.forEach((frame) => {
      const data = frame.data;
      if (!data || !data.length) return;
      const kind = data[0] >> 4;
      if (kind === 0) {
        const length = data[0] & 0x0f;
        if (length && length <= data.length - 1) {
          payloads.push({ bytes: Array.from(data.slice(1, 1 + length)), line: frame.line, source });
        }
        pending = null;
        return;
      }
      if (kind === 1) {
        const total = ((data[0] & 0x0f) << 8) | data[1];
        pending = { total, bytes: Array.from(data.slice(2, 8)), line: frame.line };
        return;
      }
      if (kind === 2 && pending) {
        pending.bytes.push(...data.slice(1));
        if (pending.bytes.length >= pending.total) {
          payloads.push({ bytes: pending.bytes.slice(0, pending.total), line: pending.line, source });
          pending = null;
        }
      }
    });
    if (pending) {
      ignored.push({ line: pending.line, text: source, why: `incomplete multi-frame answer (${pending.bytes.length}/${pending.total} bytes)` });
    }
  });

  // Bare DTC text such as "P0133" is accepted too.
  String(text || '').split(/\r?\n/).forEach((rawLine, index) => {
    const match = rawLine.trim().match(/^([PCBU])([0-9A-F]{4})$/i);
    if (match) payloads.push({ literalDtc: `${match[1].toUpperCase()}${match[2].toUpperCase()}`, line: index + 1, source: 'text' });
  });

  return { payloads, requests, ignored };
}

function decodeObd(text) {
  const { payloads, requests, ignored } = obdPayloads(text);
  const readings = [];
  const dtcs = [];
  const literalDtcs = [];
  const vinParts = [];
  const notes = [];

  payloads.forEach((entry) => {
    if (entry.literalDtc) {
      literalDtcs.push(entry.literalDtc);
      return;
    }
    const bytes = entry.bytes;
    if (!bytes.length) return;
    const mode = bytes[0];
    const responseMode = mode & 0x40 ? mode - 0x40 : mode;
    if (mode === 0x7f) {
      notes.push(`The ECU refused a request: service 0x${(bytes[1] || 0).toString(16).toUpperCase()}, code 0x${(bytes[2] || 0).toString(16).toUpperCase()}.`);
      return;
    }
    if (responseMode === 1) {
      const pid = bytes[1];
      const decoded = obdDecodeMode1(pid, bytes.slice(2));
      readings.push({ ...decoded, source: entry.source });
      return;
    }
    if (responseMode === 3 || responseMode === 7) {
      const { count, dtcs: codes } = obdDecodeDtcs(bytes);
      codes.forEach((code) => dtcs.push({ code, kind: responseMode === 3 ? 'stored' : 'pending' }));
      if (codes.length !== count && count !== undefined) {
        notes.push(`Mode 0${responseMode}: the response announces ${count} code(s) but carries ${codes.length}.`);
      }
      return;
    }
    if (responseMode === 9) {
      const pid = bytes[1];
      if (pid === 0x02) {
        const frameIndex = bytes[2];
        const ascii = bytes.slice(3).filter((value) => value >= 0x20 && value <= 0x7e).map((value) => String.fromCharCode(value)).join('');
        vinParts.push({ frameIndex, ascii });
      } else if (pid === 0x04) {
        const ascii = bytes.slice(2).map((value) => String.fromCharCode(value)).join('');
        notes.push(`Calibration ID: ${ascii.replace(/[^\x20-\x7e]/g, '').trim()}`);
      } else if (pid === 0x0a) {
        const ascii = bytes.slice(2).map((value) => String.fromCharCode(value)).join('');
        notes.push(`ECU name: ${ascii.replace(/[^\x20-\x7e]/g, '').trim()}`);
      }
      return;
    }
    if (responseMode === 4) return; // a clear-codes acknowledgement says nothing about the bike
    if (responseMode === 6) {
      notes.push('Mode 06 (on-board test results) is present; it is not decoded here.');
      return;
    }
    notes.push(`Mode 0x${responseMode.toString(16).toUpperCase()} is not decoded by this tool.`);
  });

  const vin = vinParts.length
    ? vinParts.sort((a, b) => a.frameIndex - b.frameIndex).map((part) => part.ascii).join('').replace(/[^A-HJ-NPR-Z0-9]/gi, '').slice(0, 17)
    : '';

  const byPid = new Map();
  readings.forEach((reading) => {
    if (!byPid.has(reading.pid)) byPid.set(reading.pid, []);
    byPid.get(reading.pid).push(reading.value);
  });

  return {
    readings,
    dtcs,
    literalDtcs,
    vin,
    requests,
    ignored,
    notes,
    summary: {
      readings: readings.length,
      pids: byPid.size,
      dtcs: dtcs.length + literalDtcs.length,
      vin: Boolean(vin),
    },
  };
}

function obdFormatReading(reading) {
  if (reading.value === null || reading.value === undefined) return '—';
  if (typeof reading.value === 'object') return reading.format ? reading.format(reading.value) : JSON.stringify(reading.value);
  const digits = Math.abs(reading.value) >= 1000 ? 0 : (Math.abs(reading.value) >= 100 ? 1 : 2);
  return `${reading.value.toFixed(digits)}${reading.unit ? ` ${reading.unit}` : ''}`;
}

/**
 * Estimate the engaged gear from engine speed and road speed.
 *
 * wheel rpm = speed / tyre circumference; the ratio between engine and wheel
 * speed is primary x final x gear. With no ratios supplied the estimate is
 * declined rather than guessed.
 */
function estimateObdGear({ rpm, speedKph, tyreCircumference = 2.008, primary = 1, finalDrive = 1, ratios = [] }) {
  if (!Number.isFinite(rpm) || !Number.isFinite(speedKph) || rpm < 500 || speedKph < 3) return null;
  if (!ratios.length) return null;
  const wheelRpm = (speedKph / 3.6) / tyreCircumference * 60;
  if (!Number.isFinite(wheelRpm) || wheelRpm <= 0) return null;
  const overall = rpm / wheelRpm;
  let best = null;
  ratios.forEach((ratio, index) => {
    const expected = primary * finalDrive * ratio;
    const error = Math.abs(overall - expected) / expected;
    if (!best || error < best.error) best = { gear: index + 1, expected, error };
  });
  if (!best || best.error > 0.25) return { gear: null, overall, best, note: 'no gear matches within 25 %' };
  return { ...best, overall };
}

if (typeof window !== 'undefined') {
  window.gobObd = {
    pids: OBD_PIDS,
    profiles: OBD_PROFILES,
    modes: OBD_MODES,
    decodeObd,
    obdPayloads,
    estimateObdGear,
    formatReading: obdFormatReading,
    dtc: obdDtc,
  };
}

/* ---- panel wiring ------------------------------------------------------- */

if (typeof document !== 'undefined') {
  const el = (id) => document.getElementById(id);
  const setText = (id, text) => { const node = el(id); if (node) node.textContent = text; };
  const setHtml = (id, html) => { const node = el(id); if (node) node.innerHTML = html; };
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
  const state = { decoded: null };

  const profileSelect = el('obdProfile');
  if (profileSelect) {
    const sync = () => {
      const profile = OBD_PROFILES[profileSelect.value] || OBD_PROFILES.generic;
      setText('obdProfileNote', profile.note);
      const list = el('obdPidList');
      if (list) {
        list.innerHTML = profile.pids.map((pid) => {
          const definition = OBD_PIDS[pid];
          return `<li><code>01 ${pid.toString(16).toUpperCase().padStart(2, '0')}</code> `
            + `${escapeHtml(definition?.name || 'unknown')}${definition?.unit ? ` <span class="muted">(${escapeHtml(definition.unit)})</span>` : ''}</li>`;
        }).join('');
      }
    };
    profileSelect.addEventListener('change', sync);
    sync();
  }

  const decodeBtn = el('obdDecodeBtn');
  if (decodeBtn) {
    decodeBtn.onclick = () => {
      setHtml('obdOut', '');
      setText('obdMeta', '');
      try {
        const result = decodeObd(el('obdIn').value);
        state.decoded = result;
        if (!result.readings.length && !result.dtcs.length && !result.literalDtcs.length && !result.vin) {
          setText('obdMeta', 'Nothing decoded — paste an ELM327 transcript, candump lines or PIDs.');
          return;
        }
        const readingRows = result.readings.map((reading) => `<tr>`
          + `<td><code>01 ${reading.pid.toString(16).toUpperCase().padStart(2, '0')}</code></td>`
          + `<td>${escapeHtml(reading.name)}</td>`
          + `<td>${escapeHtml(obdFormatReading(reading))}</td>`
          + `<td>${reading.raw.map((byte) => byte.toString(16).toUpperCase().padStart(2, '0')).join(' ')}</td>`
          + `<td>${escapeHtml(reading.source || '')}</td></tr>`).join('');
        const dtcRows = result.dtcs.map((entry) => `<tr><td><b>${entry.code}</b></td><td>${entry.kind}</td></tr>`).join('');
        setHtml('obdOut', '<div class="kv">'
          + `<div><span>Readings</span><b>${result.summary.readings}</b></div>`
          + `<div><span>Distinct PIDs</span><b>${result.summary.pids}</b></div>`
          + `<div><span>Trouble codes</span><b>${result.summary.dtcs}</b></div>`
          + `<div><span>VIN</span><b>${escapeHtml(result.vin || 'not in the capture')}</b></div></div>`
          + (readingRows ? '<h3>Mode 01 readings</h3><div class="table-wrap"><table class="data"><thead><tr>'
            + '<th>PID</th><th>Channel</th><th>Value</th><th>Raw</th><th>Source</th></tr></thead><tbody>'
            + readingRows + '</tbody></table></div>' : '')
          + (dtcRows ? '<h3>Trouble codes</h3><div class="table-wrap"><table class="data"><thead><tr>'
            + '<th>Code</th><th>Kind</th></tr></thead><tbody>' + dtcRows + '</tbody></table></div>' : '')
          + (result.literalDtcs.length ? `<p class="small">Typed codes: ${escapeHtml(result.literalDtcs.join(', '))}</p>` : '')
          + (result.requests.length ? `<p class="small">Requests in the transcript: `
            + result.requests.map((request) => `<code>${escapeHtml(request.raw)}</code> ${escapeHtml(request.name)}`).join(' · ') + '</p>' : '')
          + (result.notes.length ? `<ul class="small">${result.notes.map((note) => `<li>${escapeHtml(note)}</li>`).join('')}</ul>` : '')
          + (result.ignored.length ? `<p class="muted small">${result.ignored.length} line(s) could not be read: `
            + result.ignored.slice(0, 3).map((entry) => `line ${entry.line} (${escapeHtml(entry.why)})`).join(', ') + '.</p>' : '')
          + '<p class="muted small">Values use the SAE J1979 scalings. A response proves the ECU answered that '
          + 'PID; it does not identify the model, and a code is a starting point, not a diagnosis.</p>');
        setText('obdMeta', `${result.summary.readings} reading(s) · ${result.summary.pids} PID(s)`
          + (result.summary.dtcs ? ` · ${result.summary.dtcs} code(s)` : '')
          + (result.vin ? ' · VIN decoded' : ''));
      } catch (error) {
        setText('obdMeta', `Not decoded: ${error.message}`);
      }
    };
  }

  const gearBtn = el('obdGearBtn');
  if (gearBtn) {
    gearBtn.onclick = () => {
      setText('obdGearOut', '');
      try {
        const ratios = String(el('obdRatios').value || '').split(/[\s,]+/).filter(Boolean).map(Number);
        if (!ratios.length || ratios.some((value) => !Number.isFinite(value) || value <= 0)) {
          throw new Error('Enter the gearbox ratios from the manual, highest first.');
        }
        const rpmEntry = state.decoded?.readings.find((reading) => reading.pid === 0x0c);
        const speedEntry = state.decoded?.readings.find((reading) => reading.pid === 0x0d);
        const rpm = Number(el('obdGearRpm').value) || (rpmEntry ? Number(rpmEntry.value) : NaN);
        const speedKph = Number(el('obdGearSpeed').value) || (speedEntry ? Number(speedEntry.value) : NaN);
        const result = estimateObdGear({
          rpm,
          speedKph,
          tyreCircumference: Number(el('obdGearTyre').value) || 2.008,
          primary: Number(el('obdGearPrimary').value) || 1,
          finalDrive: Number(el('obdGearFinal').value) || 1,
          ratios,
        });
        if (!result) throw new Error('A gear estimate needs engine speed above 500 rpm and road speed above 3 km/h.');
        setText('obdGearOut', result.gear
          ? `Gear ${result.gear} · overall ${result.overall.toFixed(2)}:1 (expected ${result.expected.toFixed(2)}:1, `
            + `${(result.error * 100).toFixed(1)} % away)`
          : `No gear matches: overall ratio ${result.overall.toFixed(2)}:1 is outside 25 % of every listed gear.`);
      } catch (error) {
        setText('obdGearOut', `Not estimated: ${error.message}`);
      }
    };
  }
}
