/* BRT Juken 5 core block research, adapted from cfbird/juken5 maps.py,
 * Copyright (c) 2026 Charles Bird, MIT, revision 8585b94715e5db01eb37bdd81c7b0a0a91c1d739.
 * See LICENSES/Juken5-MIT.txt. No ECU communication, firmware writing or tune generation. */
'use strict';

const JUKEN_CELLS = 21 * 61;
const JUKEN_TABLES = Object.freeze([
  { name: 'FuelBase', width: 2, signed: true },
  { name: 'InjTmg', width: 2, signed: false },
  { name: 'IgnTmg', width: 2, signed: false },
  { name: 'FuelCor1', width: 1, signed: false },
  { name: 'FuelCorTB1', width: 1, signed: false },
]);
const JUKEN_SIZE = JUKEN_CELLS * 8;

function parseJukenResearch(bytes) {
  if (!(bytes instanceof Uint8Array) || bytes.length !== JUKEN_SIZE) {
    throw new Error('Expected exactly 10,248 raw bytes; bulk encoding and file headers are not supported.');
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 0;
  return JUKEN_TABLES.map((spec) => {
    const values = [];
    for (let i = 0; i < JUKEN_CELLS; i++) {
      const pos = offset + i * spec.width;
      values.push(spec.width === 1 ? view.getUint8(pos)
        : spec.signed ? view.getInt16(pos, true) : view.getUint16(pos, true));
    }
    const item = { ...spec, offset, values };
    offset += JUKEN_CELLS * spec.width;
    return item;
  });
}

const jukenFile = document.getElementById('jukenImage');
const jukenOut = document.getElementById('jukenOut');
const jukenSelect = document.getElementById('jukenTable');
const jukenSave = document.getElementById('jukenCsv');
let jukenTables = null;
let jukenGeneration = 0;
function clearJuken() {
  ++jukenGeneration;
  jukenTables = null;
  jukenOut.textContent = '';
  jukenSelect.disabled = true;
  jukenSave.disabled = true;
}
jukenFile.addEventListener('change', clearJuken);
document.getElementById('jukenClear').onclick = () => { clearJuken(); jukenFile.value = ''; };
document.getElementById('jukenInspect').onclick = async () => {
  clearJuken();
  const generation = jukenGeneration;
  try {
    const file = jukenFile.files?.[0];
    if (!file) throw new Error('Choose a user-supplied raw core block.');
    if (file.size !== JUKEN_SIZE) throw new Error('Expected exactly 10,248 raw bytes; bulk encoding and file headers are not supported.');
    const bytes = new Uint8Array(await file.arrayBuffer());
    const tables = parseJukenResearch(bytes);
    let hash = 'unavailable';
    if (globalThis.crypto?.subtle) {
      const digest = await crypto.subtle.digest('SHA-256', bytes);
      hash = [...new Uint8Array(digest)].map((v) => v.toString(16).padStart(2, '0')).join('');
    }
    if (generation !== jukenGeneration) return;
    jukenTables = tables;
    jukenSelect.disabled = false;
    jukenSave.disabled = false;
    jukenOut.textContent = `${file.name} · ${bytes.length} bytes\nSHA-256: ${hash}\n` + tables.map((table) =>
      `${table.name} · offset 0x${table.offset.toString(16).toUpperCase()} · ${table.values.length} values · min ${Math.min(...table.values)} · max ${Math.max(...table.values)} · first ${table.values.slice(0, 5).join(', ')}`
    ).join('\n') + '\nUnverified raw layout only. Byte order, table semantics, bulk encoding, axis orientation and scaling are not hardware-confirmed. Not a full ECU dump or a flashable tune.';
  } catch (error) {
    if (generation === jukenGeneration) jukenOut.textContent = `Not inspected: ${error.message}`;
  }
};
jukenSave.onclick = () => {
  if (!jukenTables) return;
  const table = jukenTables.find((item) => item.name === jukenSelect.value);
  if (!table) return;
  // Linear order only: the source's TPS/RPM orientation is unconfirmed.
  const csv = 'linear_index,raw_value\n' + table.values.map((value, index) => `${index},${value}`).join('\n') + '\n';
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  const link = document.createElement('a');
  link.href = url; link.download = `juken5-${table.name}-raw-research.csv`;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
