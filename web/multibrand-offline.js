/* Offline-only research interpretations, NOT live diagnostic support.
 * Kawasaki ER-6n: adapted from iKawa, Copyright (c) 2026 Gabriele Randazzo,
 * MIT, commit 79eb9049d13037be6fd91b8a1d1acd164ca70104.
 * Suzuki SV650AK7: adapted from BananaJoh/sv650overlay, GPL-3.0,
 * commit cc80f0d35abd60255bbcd74cdddef515ed4945ce.
 * Triumph Daytona 675: SAE PID formulas and framing adapted from daytona-kline,
 * Copyright (C) 2026 Andrew Wilke, GPL-3.0-or-later,
 * commit d37e96718f5cd82ebde3297c1181c687a922ea32.
 * BMW R1300GS: adapted from EasierCan, Copyright (c) 2026 HagayBT, MIT,
 * commit a4c37ceabeea57bc7e97b51da345dd7b84e21596.
 * Harley J1850 candidates adapted from HarleyDroid EVO J1850.kt and README,
 * Copyright (C) 2010–2012 Stelian Pop and (C) 2026 Quickosss,
 * GPL-3.0-or-later, commit 668b63efc05977eb65cb8e84e597ae2205355d4c.
 * J1850 VPW CRC adapted from vpw-sniffer, Copyright (c) 2026 bbutka,
 * MIT, commit 37aa6f974615154419bc28eb9cf9f9cfb804ade0. No bike validation.
 * No hardware or commands are included. See docs/EXTERNAL_MOTORCYCLE_RESEARCH.md
 * and LICENSES for attribution, terms, limitations and sources. NO WARRANTY.
 */
'use strict';

function researchHex(text) {
  if (!/^[0-9a-f]{2}(?:\s+[0-9a-f]{2})*$/i.test(text)) throw new Error('Use space-separated hex bytes only.');
  const bytes = text.split(/\s+/).map((item) => parseInt(item, 16));
  if (bytes.length > 70) throw new Error('Frame exceeds 70 bytes.');
  return bytes;
}

function researchChecksum(bytes) {
  if (bytes.length < 5 || (bytes.slice(0, -1).reduce((a, b) => a + b, 0) & 255) !== bytes[bytes.length - 1]) {
    throw new Error('Checksum mismatch; not decoded.');
  }
}

function researchKwp(bytes, source) {
  // Only the explicitly addressed, extended-length response seen in these sources.
  if (bytes.length < 7 || bytes[0] !== 0x80 || bytes[1] !== 0xf1 || bytes[2] !== source || bytes[3] + 5 !== bytes.length) {
    throw new Error('Expected a complete addressed K-Line response with the source and length for this profile.');
  }
  researchChecksum(bytes);
  return bytes.slice(4, -1);
}

function researchKawasaki(bytes) {
  const p = researchKwp(bytes, 0x11);
  if (p[0] !== 0x61) throw new Error('Only positive 0x61 responses are interpreted.');
  const id = p[1], v = p.slice(2);
  const sizes = { 4: 2, 6: 1, 7: 1, 9: 2, 10: 1, 11: 1, 12: 2 };
  if (!Object.hasOwn(sizes, id) || v.length !== sizes[id]) throw new Error('Unknown or incorrectly sized Kawasaki local identifier.');
  const pair = () => v[0] * 100 + v[1];
  const values = {
    4: () => `Throttle candidate: ${Math.trunc(((((v[0] << 8) + v[1]) - 226) * 100) / 635) + 2} % (source-specific calibration)`,
    6: () => `Coolant candidate: ${(v[0] - 48) / 1.6} °C`,
    7: () => `Intake-air candidate: ${(v[0] - 48) / 1.6} °C`,
    9: () => `Engine speed candidate: ${pair()} rpm`,
    10: () => `Battery candidate: ${v[0] / 12.75} V`,
    11: () => `Gear byte: ${v[0]} (interpretation unverified)`,
    12: () => `Speed candidate: ${Math.trunc(pair() / 2)} km/h`,
  };
  return [`Kawasaki local ID 0x${id.toString(16).padStart(2, '0')}`, values[id]()];
}

function researchSuzuki(bytes) {
  const p = researchKwp(bytes, 0x12);
  // The source's all-sensors layout is a 0x34-byte payload. Reject partials,
  // other local IDs and frames whose checksum byte might be mistaken for data.
  if (bytes.length !== 57 || p.length !== 52 || p[0] !== 0x61 || p[1] !== 0x08) {
    throw new Error('Expected a complete 0x61 0x08 all-sensors response (57 bytes).');
  }
  const b = bytes;
  const rpm = Math.trunc(b[17] * 69 / 10) * 10; // source uses high byte only
  const tps = Math.trunc((b[19] - 58) * 6 / 10);
  const batt = b[24] ? (b[24] + 109) * 5 / 100 : 0;
  return [
    'Suzuki all-sensors response · SV650overlay candidates',
    `RPM candidate: ${rpm} rpm (source uses only byte 17; other sources differ)`,
    `Throttle candidate: ${tps} %`,
    `Coolant candidate: ${b[21] - 40} °C · intake-air candidate: ${b[22] - 40} °C`,
    `Battery candidate: ${batt} V · gear/status byte: ${b[26]}`,
    'These conversions are not independently confirmed and differ across published implementations.',
  ];
}

function researchTriumph(bytes) {
  if (bytes.length < 7 || bytes[0] !== 0x48 || bytes[1] !== 0x6b || bytes[2] !== 0xd1) {
    throw new Error('Expected the documented ISO 9141 response header.');
  }
  researchChecksum(bytes);
  const p = bytes.slice(3, -1);
  if (p[0] !== 0x41) throw new Error('Only positive mode 01 responses are interpreted.');
  const id = p[1], v = p.slice(2);
  const sizes = { 4: 1, 5: 1, 6: 1, 11: 1, 12: 2, 13: 1, 14: 1, 15: 1, 17: 1 };
  if (!Object.hasOwn(sizes, id) || v.length !== sizes[id]) throw new Error('Unknown or incorrectly sized mode 01 PID.');
  const values = {
    4: () => `Engine load: ${v[0] * 100 / 255} %`,
    5: () => `Coolant: ${v[0] - 40} °C`,
    6: () => `Short-term fuel trim: ${(v[0] - 128) * 100 / 128} %`,
    11: () => `Manifold pressure: ${v[0]} kPa`,
    12: () => `Engine speed: ${(v[0] * 256 + v[1]) / 4} rpm`,
    13: () => `Vehicle speed: ${v[0]} km/h`,
    14: () => `Timing advance: ${v[0] / 2 - 64} °`,
    15: () => `Intake air: ${v[0] - 40} °C`,
    17: () => `Throttle: ${v[0] * 100 / 255} %`,
  };
  return [`Triumph mode 01 PID 0x${id.toString(16).padStart(2, '0')} · candidate`, values[id]()];
}

function researchBmw(line) {
  const match = /^([0-9a-f]{1,3})#([0-9a-f]{2}(?:[0-9a-f]{2})*)$/i.exec(line);
  if (!match) throw new Error('Use 11-bit CAN format ID#DATA with contiguous hex data.');
  const id = parseInt(match[1], 16), hex = match[2];
  if (id > 0x7ff || hex.length > 16) throw new Error('Only 11-bit classic CAN data frames are accepted.');
  const b = hex.match(/../g).map((pair) => parseInt(pair, 16));
  if (id === 0x10c && b.length >= 3) return [`BMW 0x10C · engine speed candidate: ${(b[2] * 256 + b[1]) / 4} rpm`];
  if (id === 0x2d0 && b.length >= 7) return [`BMW 0x2D0 · high-beam flash candidate: ${(b[6] & 0x10) === 0}`];
  if (id === 0x2d2 && b.length >= 1) return [`BMW 0x2D2 · left: ${!!(b[0] & 4)} · right: ${!!(b[0] & 8)} · brake: ${!!(b[0] & 32)} (candidates)`];
  throw new Error('Unknown ID or insufficient payload for the selected BMW profile.');
}

function researchVpw(bytes) {
  if (bytes.length < 4 || bytes.length > 12) throw new Error('J1850 frame must contain 3 header bytes, up to 8 data bytes and a CRC.');
  let crc = 0xff;
  for (const byte of bytes.slice(0, -1)) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = ((crc << 1) ^ ((crc & 0x80) ? 0x1d : 0)) & 0xff;
  }
  crc ^= 0xff;
  if (crc !== bytes[bytes.length - 1]) throw new Error('J1850 CRC mismatch; not interpreted.');
  return ['J1850 CRC matches. Payload is not decoded; source is not validated on a motorcycle.'];
}

// The source describes trial-and-error J1850 frames, notably Sportster.
// Decode a single complete CRC-valid frame only; never combine identity
// fragments across captures, infer fault status, or send ECU commands.
function researchHarleyJ1850(bytes) {
  researchVpw(bytes);
  const b = bytes.slice(0, -1), prefix = b.slice(0, 4).map((v) => v.toString(16).padStart(2, '0')).join('');
  const word = () => b[4] * 256 + b[5];
  if (prefix === '281b1002' && b.length === 6) return [`Engine speed: ${word() / 4} rpm`];
  if (prefix === '48291002' && b.length === 6) return [`Road speed: ${word() / 128} km/h`];
  if (prefix === 'a8491010' && b.length === 5) return [`Engine temperature candidate: ${b[4] - 40} °C (raw ${b[4]}; source descriptions differ)`];
  if (prefix === 'a83b1003' && b.length === 5) return [`Gear raw byte: ${b[4]} (source documentation and code differ; do not infer gear)`];
  if (b.length === 4 && b[0] === 0x48 && b[1] === 0x3b && b[2] === 0x40 && (b[3] & 0x5d) === 0) {
    const neutral = b[3] === 0x20 ? 'false' : b[3] === 0xa0 ? 'true' : 'unknown';
    return [`Neutral candidate: ${neutral} · clutch bit candidate: ${Boolean(b[3] & 0x80)} · raw status 0x${b[3].toString(16).padStart(2, '0')}`];
  }
  if (prefix === '48da4039' && b.length === 5 && b[4] <= 3) return [`Turn signal candidate: ${['off', 'right', 'left', 'both'][b[4]]}`];
  if ((prefix === '68881003' || prefix === '68881083') && b.length === 4) return [`Check-engine lamp candidate: ${Boolean(b[3] & 0x80)}`];
  if ((prefix === 'a8691006' || prefix === 'a8691086') && b.length === 6) return [`Odometer pulse counter: ${word()} · raw counter, not absolute odometer · wrap flag: ${Boolean(b[3] & 0x80)}`];
  if ((prefix === 'a883100a' || prefix === 'a883108a') && b.length === 6) return [`Fuel-use pulse counter: ${word()} · raw counter, not total fuel · wrap flag: ${Boolean(b[3] & 0x80)}`];
  if ((prefix === 'a8836112' || prefix === 'a8836192') && b.length === 5) return [`Fuel-gauge candidate: ${b[4] & 15} / 15 · low-fuel bit: ${Boolean(b[3] & 0x80)}`];
  if (b.length === 6 && b[0] === 0x6c && b[1] === 0xf1 && [0x10, 0x40, 0x60].includes(b[2]) && b[3] === 0x59) {
    const module = { 16: 'ECM', 64: 'ABS', 96: 'TSM' }[b[2]];
    if (!b[4] && !b[5]) return [`${module} DTC payload 0000 (does not establish absence of faults).`];
    const code = 'PCBU'[b[4] >> 6] + ((b[4] >> 4) & 3).toString(16) + (b[4] & 15).toString(16) + b[5].toString(16).padStart(2, '0');
    return [`${module} DTC candidate: ${code.toUpperCase()} · current/historic status not determined (source interpretations differ)`];
  }
  if (prefix === '0cf1107c' && b.length >= 6) {
    const id = b[4], length = { 1: 6, 2: 6, 3: 6, 4: 6, 11: 1, 15: 6, 16: 6, 17: 5 }[id];
    if (length && b.length === 5 + length) {
      if (id === 11) return [`ECM software level candidate: ${b[5]}`];
      const fragment = b.slice(5).map((v) => v >= 32 && v <= 126 ? String.fromCharCode(v) : '�').join('');
      const what = id <= 2 ? 'ECM part number' : id <= 4 ? 'ECM calibration ID' : 'VIN';
      return [`${what} fragment (block 0x${id.toString(16)}): ${fragment} · not reassembled`];
    }
  }
  return ['CRC matches; this frame is not decoded by the selected profile.'];
}

function decodeMultiResearch(profile, line) {
  if (profile === 'bmw_r1300gs') return researchBmw(line);
  const bytes = researchHex(line);
  if (profile === 'kawasaki_er6n') return researchKawasaki(bytes);
  if (profile === 'suzuki_sv650ak7') return researchSuzuki(bytes);
  if (profile === 'triumph_daytona') return researchTriumph(bytes);
  if (profile === 'harley_vpw') return researchVpw(bytes);
  if (profile === 'harley_j1850_harleydroid') return researchHarleyJ1850(bytes);
  throw new Error('Choose an exact research profile.');
}

const multiFrames = document.getElementById('multiResearchFrames');
const multiProfile = document.getElementById('multiResearchProfile');
const multiOut = document.getElementById('multiResearchOut');
for (const input of [multiFrames, multiProfile]) input.addEventListener('input', () => { multiOut.textContent = ''; });
document.getElementById('multiResearchClear').onclick = () => { multiFrames.value = ''; multiOut.textContent = ''; };
document.getElementById('multiResearchDecode').onclick = () => {
  const lines = multiFrames.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (!multiProfile.value) { multiOut.textContent = 'Choose an exact research profile.'; return; }
  if (!lines.length) { multiOut.textContent = 'Paste at least one complete frame.'; return; }
  if (lines.length > 100) { multiOut.textContent = 'Limit: 100 frames per decode.'; return; }
  multiOut.textContent = lines.map((line, i) => {
    try { return `Frame ${i + 1}: ${line}\n${decodeMultiResearch(multiProfile.value, line).join('\n')}`; }
    catch (error) { return `Frame ${i + 1}: ${line}\nRejected: ${error.message}`; }
  }).join('\n\n');
};
