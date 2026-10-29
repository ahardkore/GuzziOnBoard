/* Honda ECU Manager, Copyright (C) 2025 andreibaw, GPL-3.0-or-later.
 * Offline-only adaptation of parseTable10 / parseTableD1 and checksum from
 * https://github.com/andreibaw/Honda_K-Line_KWP2000, commit f3bd42ff438e840e4da3802dd5038a195f3d67be.
 * Modified for GuzziOnBoard: no hardware, TX, initialization, polling or UI
 * code from the original; strict response framing, length and checksum checks.
 * Distributed with LICENSES/Honda-KLine-GPL-3.0.txt; NO WARRANTY.
 */
/* Table 11 candidate layout adapted from sophienyaa/Honda-Motorcycle-ECU-Tools,
 * MIT license: LICENSES/Honda-Motorcycle-ECU-Tools-MIT.txt.
 * Source: https://github.com/sophienyaa/Honda-Motorcycle-ECU-Tools/tree/84c203736dcea4ef1b436bfc4d36eca73d897110
 * The source uses integer arithmetic; this decoder displays the fractional
 * arithmetic implied by its formulas and marks this distinction explicitly.
 */
'use strict';

function decodeHondaResponse(line) {
  const trimmed = line.trim();
  if (!/^(?:[0-9a-fA-F]{2})(?:\s+[0-9a-fA-F]{2})*$/.test(trimmed)) {
    throw new Error('Use complete space-separated hex bytes only.');
  }
  const b = trimmed.split(/\s+/).map((hex) => parseInt(hex, 16));
  if (b.length < 5 || b[0] !== 0x02 || b[1] !== b.length || b[2] !== 0x71) {
    throw new Error('Not a complete Honda table response with a matching length.');
  }
  if ((b.reduce((sum, byte) => sum + byte, 0) & 0xff) !== 0) {
    throw new Error('Checksum mismatch; not decoded.');
  }
  if (b[3] === 0x10 && b.length === 22) {
    return [
      'Table 10 · candidate values',
      `RPM: ${(b[4] << 8) | b[5]} rpm`,
      `TPS: ${b[7] * 10 / 16} % · TPS voltage: ${b[6] * 5 / 256} V`,
      `Coolant: ${b[9] - 40} °C · coolant voltage: ${b[8] * 5 / 256} V`,
      `Intake air: ${b[11] - 40} °C · intake voltage: ${b[10] * 5 / 256} V`,
      `MAP: ${b[13]} kPa · MAP voltage: ${b[12] * 5 / 256} V`,
      `Battery: ${b[16] / 10} V · speed: ${b[17]} km/h`,
    ];
  }
  if (b[3] === 0x11 && b.length === 25) {
    return [
      'Table 11 · CRF250L source candidate values (fractional formulas; source code truncates)',
      `RPM: ${(b[4] << 8) | b[5]} rpm`,
      `TPS: ${b[7] / 16} % · TPS voltage: ${b[6] * 5 / 256} V`,
      `Coolant: ${b[9] - 40} °C · coolant voltage: ${b[8] * 5 / 256} V`,
      `Intake air: ${b[11] - 40} °C · intake voltage: ${b[10] * 5 / 256} V`,
      `MAP: ${b[13]} kPa · MAP voltage: ${b[12] * 5 / 256} V`,
      `Battery: ${b[16] / 10} V · speed: ${b[17]} km/h`,
    ];
  }
  if (b[3] === 0xd1 && b.length === 10) {
    const state = { 0: 'in gear', 1: 'neutral or clutch', 3: 'kickstand down' }[b[4]] || 'unknown';
    return [
      'Table D1 · candidate status',
      `Gear/status byte: 0x${b[4].toString(16).padStart(2, '0')} (${state}; not a confirmed gear)`,
      `Engine-status byte: 0x${b[8].toString(16).padStart(2, '0')} (${b[8] === 1 ? 'source interprets as running' : 'not interpreted'})`,
    ];
  }
  throw new Error('Only table 10 (22 bytes), CRF250L table 11 (25 bytes), and D1 (10 bytes) are supported.');
}

const hondaInput = document.getElementById('hondaFrames');
const hondaOut = document.getElementById('hondaOut');
hondaInput.addEventListener('input', () => { hondaOut.textContent = ''; });
document.getElementById('hondaClear').onclick = () => { hondaInput.value = ''; hondaOut.textContent = ''; };
document.getElementById('hondaDecode').onclick = () => {
  const lines = hondaInput.value.split(/\r?\n/).filter((line) => line.trim());
  if (!lines.length) { hondaOut.textContent = 'Paste at least one response frame.'; return; }
  if (lines.length > 100) { hondaOut.textContent = 'Limit: 100 frames per decode.'; return; }
  hondaOut.textContent = lines.map((line, index) => {
    try {
      const values = decodeHondaResponse(line);
      return `Frame ${index + 1}: ${line.trim()}\n${values.join('\n')}`;
    } catch (error) { return `Frame ${index + 1}: ${line.trim()}\nRejected: ${error.message}`; }
  }).join('\n\n');
};
