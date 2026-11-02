/* Brand decoders: one panel per manufacturer, one shared decoder.
 *
 * Kawasaki, Suzuki, Triumph and BMW reuse the profile decoders already written
 * for the multi-brand research tool (web/multibrand-offline.js) instead of
 * carrying a second copy of the same arithmetic. Ducati and Indian are new
 * here and mirror the Python implementations:
 *   - guzzionboard/ducati_panigale_can.py (MIT, DucatiPanigaleCanBus)
 *   - guzzionboard/indian_springfield_can.py (MIT, indian-thunderstroke-canbus)
 *
 * Every panel is the same shape: paste frames that were already captured, get
 * candidate values with the raw bytes kept beside them. Nothing here connects,
 * transmits, clears faults or writes; a decoded byte is a research lead, never
 * a fitment claim.
 */
'use strict';

const BRAND_FRAME_PROFILES = {
  kawasaki: {
    label: 'Kawasaki ER-6n 2006 · KDS over K-Line',
    source: 'iKawa, Copyright (c) 2026 Gabriele Randazzo, MIT (LICENSES/iKawa-MIT.txt).',
    profile: 'kawasaki_er6n',
    hint: 'A complete addressed K-Line response: 80 F1 11 <len> 61 <local id> <data> <checksum>.',
    placeholder: '80 F1 11 04 61 0C 03 1A 10',
    // Only the local identifiers the browser decoder actually interprets. The
    // Python module knows more request lengths (0x02, 0x05, 0x08, 0x44); listing
    // them here would advertise formulas this panel cannot produce.
    table: [
      ['0x04', 'Throttle', '((raw − 226) × 100 / 635) + 2 %, source calibration'],
      ['0x06', 'Coolant', '(a − 48) / 1.6 °C'],
      ['0x07', 'Intake air', '(a − 48) / 1.6 °C'],
      ['0x09', 'Engine speed', 'a × 100 + b rpm (decimal weighting)'],
      ['0x0A', 'Battery', 'a / 12.75 V'],
      ['0x0B', 'Gear byte', 'raw, interpretation unverified'],
      ['0x0C', 'Road speed', '(a × 100 + b) / 2 km/h'],
    ],
  },
  suzuki: {
    label: 'Suzuki SV650AK7 2007 · SDS over K-Line',
    source: 'SV650overlay, BananaJoh, GPL-3.0 (LICENSES/SV650overlay-GPL-3.0.txt).',
    profile: 'suzuki_sv650ak7',
    hint: 'The complete all-sensors answer (57 bytes) including the checksum: 80 F1 12 … 61 08 …',
    placeholder: '80 F1 12 34 61 08 … (57 bytes)',
    table: [
      ['byte 17', 'Engine speed', '(b17 × 6.9) truncated to 10 rpm — source uses the high byte only'],
      ['byte 19', 'Throttle', '(b19 − 58) × 0.6 %'],
      ['byte 20', 'Manifold pressure', 'b20 × 166.7 / 255 − 20 kPa'],
      ['byte 21', 'Coolant', 'b21 − 40 °C'],
      ['byte 22', 'Intake air', 'b22 − 40 °C'],
      ['byte 24', 'Battery', '(b24 + 109) × 0.05 V'],
      ['byte 26', 'Gear / status', 'raw byte'],
    ],
  },
  triumph: {
    label: 'Triumph Daytona 675 2012 · ISO 9141 / SAE mode 01',
    source: 'daytona-kline, Copyright (C) 2026 Andrew Wilke, GPL-3.0-or-later (LICENSES/Daytona-Kline-GPL-3.0.txt).',
    profile: 'triumph_daytona',
    hint: 'A complete ISO 9141 response burst: 48 6B D1 41 <pid> <data> <checksum>.',
    placeholder: '48 6B D1 41 0C 1A F8 E3',
    table: [
      ['PID 0x04', 'Engine load', 'A × 100 / 255 %'],
      ['PID 0x05', 'Coolant', 'A − 40 °C'],
      ['PID 0x06', 'Short-term fuel trim', '(A − 128) × 100 / 128 %'],
      ['PID 0x0B', 'Manifold pressure', 'A kPa'],
      ['PID 0x0C', 'Engine speed', '(A × 256 + B) / 4 rpm'],
      ['PID 0x0D', 'Road speed', 'A km/h'],
      ['PID 0x0E', 'Timing advance', 'A / 2 − 64 °'],
      ['PID 0x0F', 'Intake air', 'A − 40 °C'],
      ['PID 0x11', 'Throttle', 'A × 100 / 255 %'],
    ],
  },
  bmw: {
    label: 'BMW R1300GS · 11-bit CAN broadcast',
    source: 'EasierCan, Copyright (c) 2026 HagayBT, MIT (LICENSES/BMW-R1300GS-EasierCan-MIT.txt).',
    profile: 'bmw_r1300gs',
    hint: 'One 11-bit data frame per line: 10C#0011223344556677 — the source does not record direction.',
    placeholder: '10C#00001A2B00000000',
    table: [
      ['0x10C', 'Engine speed', '(b2 × 256 + b1) / 4 rpm'],
      ['0x2D0', 'High-beam flash', 'bit 0x10 of byte 6, active low'],
      ['0x2D2', 'Switch cluster', 'byte 0 bits: left 0x04, right 0x08, brake 0x20'],
    ],
  },
};

const DUCATI_FRAMES = {
  0x18: { min: 6, name: 'Wheel speed and gear' },
  0x80: { min: 7, name: 'Throttle and engine speed' },
  0x100: { min: 6, name: 'Temperatures and battery' },
};

/** Ducati Panigale Mitsubishi layout, mirroring ducati_panigale_can.py. */
function decodeDucatiFrame(line) {
  const frame = window.gobFrameLab?.parseCandumpLine(line);
  if (!frame) throw new Error('Use candump form: can0 080#0011223344556677 or can0 18 [8] …');
  if (frame.extended) throw new Error('The Panigale profile describes 11-bit identifiers only.');
  const meta = DUCATI_FRAMES[frame.identifier];
  if (!meta) throw new Error(`0x${frame.identifier.toString(16).toUpperCase()} is not in the Panigale profile (0x18, 0x80, 0x100).`);
  const data = frame.data;
  if (data.length < meta.min || data.length > 8) throw new Error(`0x${frame.identifier.toString(16)} needs ${meta.min}-8 data bytes, got ${data.length}.`);
  const hex = (value) => `0x${value.toString(16).toUpperCase()}`;
  if (frame.identifier === 0x80) {
    return [`0x80 · ${meta.name}`,
      `Throttle candidate: ${Math.trunc(data[4] / 2)} % (source truncates the byte)`,
      `Engine speed candidate: ${data[5] * 256 + data[6]} rpm`];
  }
  if (frame.identifier === 0x18) {
    return [`0x18 · ${meta.name}`,
      `Rear wheel speed candidate: ${((data[4] & 0x1f) << 4) + (data[5] >> 4)} km/h`,
      `Gear raw: ${Math.trunc(data[4] / 32)} (the source does not map it to a gear number)`];
  }
  return [`0x100 · ${meta.name}`,
    `Coolant candidate: ${data[3] - 40} °C (signed offset, so below zero does not wrap)`,
    `Battery candidate: ${(data[4] / 10).toFixed(1)} V`,
    `Air temperature candidate: ${data[5] - 40} °C`,
    `Raw: ${hex(data[0])} ${hex(data[1])} ${hex(data[2])} …`];
}

const INDIAN_PGN = {
  61444: { name: 'EEC1 · engine speed', decode: (d) => {
    const raw = d[3] | (d[4] << 8);
    return {
      'Engine speed candidate': raw === 0xffff ? null : `${raw / 8} rpm`,
      'Engine demand candidate': d[7] === 0xff ? null : `${d[7] - 125} %`,
    };
  } },
  65262: { name: 'ET1 · cylinder-head temperature', decode: (d) => ({
    'Cylinder-head temperature candidate': d[0] === 0xff ? null : `${d[0] - 40} °C`,
  }) },
  65265: { name: 'CCVS · rear wheel speed', decode: (d) => {
    const raw = d[1] | (d[2] << 8);
    return { 'Rear speed candidate': raw === 0xffff ? null : `${(raw / 256).toFixed(2)} km/h` };
  } },
  65276: { name: 'DD · dash display', decode: (d) => ({
    'Fuel level candidate': d[1] === 0xff ? null : `${(d[1] * 0.4).toFixed(1)} %`,
  }) },
  65215: { name: 'Wheel speed · front', decode: (d) => {
    const raw = d[0] | (d[1] << 8);
    return { 'Front speed candidate': raw === 0xffff ? null : `${(raw / 256).toFixed(2)} km/h` };
  } },
};

/* PGN and source address, without CAN priority — the same table as
 * guzzionboard/indian_springfield_can.py (PGN_SOURCE / MASK / FILTER_IDS). */
const INDIAN_PGN_SOURCE = new Map([[61444, 0], [65262, 0], [65265, 11], [65276, 0], [65215, 11]]);
const INDIAN_FILTER = new Set(Array.from(INDIAN_PGN_SOURCE, ([pgn, source]) => (pgn << 8) | source));
const INDIAN_MASK = 0x03ffffff;

/** Indian Springfield 2017 J1939 broadcast candidates, mirroring the Python decoder. */
function decodeIndianFrame(line) {
  const frame = window.gobFrameLab?.parseCandumpLine(line);
  if (!frame) throw new Error('Use candump form: can0 18FEF100 [8] 01 02 …');
  if (!frame.extended) throw new Error('J1939 uses 29-bit identifiers; this one is 11-bit.');
  if (frame.data.length !== 8) throw new Error(`A J1939 frame carries exactly 8 data bytes, got ${frame.data.length}.`);
  const key = frame.identifier & INDIAN_MASK;
  if (!INDIAN_FILTER.has(key)) {
    const seen = key >> 8;
    const address = key & 0xff;
    if (INDIAN_PGN_SOURCE.has(seen)) {
      const expected = INDIAN_PGN_SOURCE.get(seen);
      throw new Error(`PGN ${seen} is in the profile, but only from source address 0x`
        + `${expected.toString(16).toUpperCase().padStart(2, '0')}; this frame came from 0x`
        + `${address.toString(16).toUpperCase().padStart(2, '0')}. One bike, one address table — `
        + 'another controller may use a different source address.');
    }
    throw new Error(`PGN ${seen} is not one of the five the source describes `
      + '(61444, 65262, 65265, 65276, 65215).');
  }
  const pgn = key >> 8;
  const source = key & 0xff;
  const entry = INDIAN_PGN[pgn];
  const values = entry.decode(frame.data);
  const lines = [`PGN ${pgn} · ${entry.name} · source address 0x${source.toString(16).toUpperCase().padStart(2, '0')}`];
  Object.entries(values).forEach(([label, value]) => {
    lines.push(`${label}: ${value === null ? 'not available (0xFF / 0xFFFF)' : value}`);
  });
  return lines;
}

function decodeBrandLine(brand, line) {
  if (brand === 'ducati') return decodeDucatiFrame(line);
  if (brand === 'indian') return decodeIndianFrame(line);
  const entry = BRAND_FRAME_PROFILES[brand];
  if (!entry) throw new Error(`No decoder for "${brand}".`);
  if (typeof window.decodeMultiResearch !== 'function') {
    throw new Error('The research decoder is not loaded; reload the page.');
  }
  return window.decodeMultiResearch(entry.profile, line.trim());
}

const BRAND_REFERENCES = {
  ducati: [
    ['0x18', 'Wheel speed / gear', 'rear speed = ((b4 & 0x1F) << 4) + (b5 >> 4) km/h · gear raw = b4 / 32'],
    ['0x80', 'Throttle / engine speed', 'throttle = b4 / 2 % (truncated) · rpm = b5 × 256 + b6'],
    ['0x100', 'Temperatures / battery', 'coolant = b3 − 40 °C · battery = b4 / 10 V · air = b5 − 40 °C'],
  ],
  indian: [
    ['PGN 61444', 'EEC1 · engine speed', 'rpm = (b3 | b4 << 8) / 8 · demand = b7 − 125 %'],
    ['PGN 65262', 'ET1 · cylinder head', 'temperature = b0 − 40 °C (air-cooled source, not coolant)'],
    ['PGN 65265', 'CCVS · rear speed', 'speed = (b1 | b2 << 8) / 256 km/h'],
    ['PGN 65276', 'DD · dash', 'fuel = b1 × 0.4 %'],
    ['PGN 65215', 'Wheel speed · front', 'speed = (b0 | b1 << 8) / 256 km/h'],
  ],
};

if (typeof window !== 'undefined') {
  window.gobBrandTools = {
    profiles: BRAND_FRAME_PROFILES,
    decodeBrandLine,
    decodeDucatiFrame,
    decodeIndianFrame,
  };
}

/* ---- panel wiring ------------------------------------------------------- */

if (typeof document !== 'undefined') {
  const el = (id) => document.getElementById(id);

  const referenceFor = (brand) => {
    if (brand === 'ducati' || brand === 'indian') return BRAND_REFERENCES[brand];
    return BRAND_FRAME_PROFILES[brand]?.table || [];
  };
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));

  Object.keys(BRAND_FRAME_PROFILES).concat(['ducati', 'indian']).forEach((brand) => {
    const prefix = brand;
    // The reference table is rendered from the decoder's own data so the panel
    // can never advertise a formula the code does not implement.
    const refHost = el(`${prefix}Ref`);
    if (refHost) {
      const rows = referenceFor(brand);
      refHost.innerHTML = rows.length
        ? '<div class="table-wrap"><table class="data"><thead><tr><th>Identifier</th><th>Channel</th>'
          + '<th>Formula</th></tr></thead><tbody>'
          + rows.map((row) => `<tr><td><code>${escapeHtml(row[0])}</code></td><td>${escapeHtml(row[1])}</td>`
            + `<td>${escapeHtml(row[2])}</td></tr>`).join('')
          + '</tbody></table></div>'
        : '';
    }
    const button = el(`${prefix}Decode`);
    if (!button) return;
    const input = el(`${prefix}Frames`);
    const out = el(`${prefix}Out`);
    const meta = el(`${prefix}Meta`);
    const clear = el(`${prefix}Clear`);
    const reset = () => {
      if (out) out.textContent = '';
      if (meta) meta.textContent = '';
    };
    if (input) input.addEventListener('input', reset);
    if (clear) {
      clear.onclick = () => {
        if (input) input.value = '';
        reset();
      };
    }
    button.onclick = () => {
      if (!input || !out) return;
      const lines = input.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
      if (!lines.length) {
        if (meta) meta.textContent = 'Paste at least one captured frame.';
        return;
      }
      if (lines.length > 100) {
        if (meta) meta.textContent = 'Limit: 100 frames per decode.';
        return;
      }
      let accepted = 0;
      const blocks = lines.map((line, index) => {
        try {
          const result = decodeBrandLine(brand, line);
          accepted += 1;
          return `Frame ${index + 1}: ${line}\n${result.join('\n')}`;
        } catch (error) {
          return `Frame ${index + 1}: ${line}\nRejected: ${error.message}`;
        }
      });
      out.textContent = blocks.join('\n\n');
      if (meta) meta.textContent = `${accepted} of ${lines.length} frame(s) decoded`;
    };
  });
}
