/* MLVLG binary log importer.
 *
 * Field layout, block tags and the 34/10/3 byte string lengths follow the
 * MLVLG parser in karniv00l/mlg-converter, src/parser.ts, revision
 * 3c4253bec864 (Copyright (c) 2020 Piotr Rogowski, MIT — see
 * LICENSES/Mlg-Converter-MIT.txt). This is an independent implementation for
 * the browser: it reads the operator's own log, applies the log's own
 * scale/transform pairs, and writes CSV. It sends nothing anywhere and touches
 * no ECU.
 */
'use strict';

const MLG_MAGIC = 'MLVLG';
const MLG_FIELD_LENGTH = { 1: 55, 2: 89 };
const MLG_FIELD_NAME = 34;
const MLG_FIELD_UNITS = 10;
const MLG_FIELD_CATEGORY = 34;
const MLG_FIELD_UNUSED = 3;
const MLG_MARKER_MESSAGE = 50;

/** Raw numeric type for each logger field type byte. */
const MLG_TYPES = {
  0: { number: 'uint8', size: 1 },
  1: { number: 'int8', size: 1 },
  2: { number: 'uint16', size: 2 },
  3: { number: 'int16', size: 2 },
  4: { number: 'uint32', size: 4 },
  5: { number: 'int32', size: 4 },
  6: { number: 'int64', size: 8 },
  7: { number: 'float32', size: 4 },
  10: { number: 'uint8', size: 1, bits: true },
  11: { number: 'uint16', size: 2, bits: true },
  12: { number: 'uint32', size: 4, bits: true },
};

const MLG_DISPLAY = ['Float', 'Hex', 'bits', 'Date', 'On/Off', 'Yes/No', 'High/Low', 'Active/Inactive', 'True/False'];

class MlgFormatError extends Error {
  constructor(message) {
    super(message);
    this.name = 'MlgFormatError';
  }
}

function mlgText(bytes) {
  return String.fromCharCode(...bytes).replace(/\0/g, '').trim();
}

function parseMlg(input, options = {}) {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const maxRecords = Number(options.maxRecords) || 500000;
  const maxFields = Number(options.maxFields) || 512;
  let offset = 0;

  const need = (count) => {
    if (offset + count > bytes.length) throw new MlgFormatError('The file ends in the middle of a structure.');
  };
  const u8 = () => { need(1); const v = view.getUint8(offset); offset += 1; return v; };
  const i8 = () => { need(1); const v = view.getInt8(offset); offset += 1; return v; };
  const u16 = () => { need(2); const v = view.getUint16(offset); offset += 2; return v; };
  const i16 = () => { need(2); const v = view.getInt16(offset); offset += 2; return v; };
  const u32 = () => { need(4); const v = view.getUint32(offset); offset += 4; return v; };
  const i32 = () => { need(4); const v = view.getInt32(offset); offset += 4; return v; };
  const f32 = () => { need(4); const v = view.getFloat32(offset); offset += 4; return v; };
  const i64 = () => { need(8); const v = view.getBigInt64(offset); offset += 8; return Number(v); };
  const str = (length) => { need(length); const v = bytes.subarray(offset, offset + length); offset += length; return mlgText(v); };

  const format = str(6).replace(/"/g, '').trim();
  if (format !== MLG_MAGIC) throw new MlgFormatError(`Not an MLVLG log (magic reads "${format || 'nothing'}").`);
  const version = i16();
  const fieldLength = MLG_FIELD_LENGTH[version];
  if (!fieldLength) throw new MlgFormatError(`MLVLG version ${version} is not supported (1 and 2 are).`);
  const v2 = version === 2;

  const timestamp = i32();
  const infoDataStart = v2 ? i32() : i16();
  const dataBeginIndex = i32();
  const recordLength = i16();
  const fieldCount = i16();
  if (fieldCount < 0 || fieldCount > maxFields) throw new MlgFormatError(`Implausible channel count (${fieldCount}).`);
  if (dataBeginIndex <= 0 || dataBeginIndex > bytes.length) throw new MlgFormatError('The data start is outside the file.');

  const fields = [];
  for (let i = 0; i < fieldCount; i += 1) {
    const type = i8();
    const name = str(MLG_FIELD_NAME);
    const units = str(MLG_FIELD_UNITS);
    const displayStyle = MLG_DISPLAY[i8()] || `style ${type}`;
    const meta = { type, name: name || `field ${i + 1}`, units, displayStyle };
    if (type < 10) {
      meta.scale = f32();
      meta.transform = f32();
      meta.digits = i8();
      meta.category = v2 ? str(MLG_FIELD_CATEGORY) : '';
      meta.kind = MLG_TYPES[type]?.number || 'uint8';
      meta.size = MLG_TYPES[type]?.size || 1;
    } else {
      meta.bitFieldStyle = MLG_DISPLAY[i8()] || 'bits';
      meta.bitFieldNamesIndex = i32();
      meta.bits = i8();
      meta.unused = str(MLG_FIELD_UNUSED);
      meta.category = v2 ? str(MLG_FIELD_CATEGORY) : '';
      meta.kind = 'bits';
      meta.size = MLG_TYPES[type]?.size || 1;
    }
    fields.push(meta);
  }

  const namesBlockLength = infoDataStart - offset;
  const bitFieldNames = namesBlockLength > 0 ? str(namesBlockLength) : '';
  offset = infoDataStart;
  const infoLength = dataBeginIndex - 1 - infoDataStart;
  const info = infoLength > 0 ? str(infoLength).replace(/"/g, '').trim() : '';
  const bitNames = bitFieldNames.split(/[\x00-\x1f]+/).map((entry) => entry.trim()).filter(Boolean);

  const readNumber = (kind) => {
    switch (kind) {
      case 'uint8': return u8();
      case 'int8': return i8();
      case 'uint16': return u16();
      case 'int16': return i16();
      case 'uint32': return u32();
      case 'int32': return i32();
      case 'int64': return i64();
      case 'float32': return f32();
      default: throw new MlgFormatError(`Unknown channel type ${kind}.`);
    }
  };

  offset = dataBeginIndex;
  const records = [];
  const markers = [];
  while (offset < bytes.length) {
    if (records.length + markers.length >= maxRecords) {
      throw new MlgFormatError(`More than ${maxRecords} records: this looks like the wrong file, so parsing stopped.`);
    }
    const blockType = u8();
    const counter = u8();
    const stamp = u16();
    if (blockType === 0) {
      const row = { record: records.length, counter, stamp };
      fields.forEach((field) => {
        const raw = readNumber(field.kind);
        row[field.name] = field.kind === 'bits'
          ? raw
          : raw * field.scale + field.transform;
        if (field.kind === 'bits' && bitNames.length) {
          const base = field.bitFieldNamesIndex || 0;
          row[`${field.name} bits`] = Array.from({ length: field.bits || 0 }, (_, bit) => (
            (raw >> bit) & 1 ? (bitNames[base + bit] || `bit ${bit}`) : null
          )).filter(Boolean).join(', ');
        }
      });
      records.push(row);
      need(1); // the per-record checksum byte is not a verification of the log
      offset += 1;
    } else if (blockType === 1) {
      markers.push({ index: markers.length, counter, stamp, message: str(MLG_MARKER_MESSAGE) });
    } else {
      throw new MlgFormatError(`Unknown data block type ${blockType} at byte ${offset - 3}.`);
    }
  }

  fields.forEach((field) => {
    if (field.kind === 'bits') return;
    let min = Infinity;
    let max = -Infinity;
    records.forEach((row) => {
      const value = row[field.name];
      if (Number.isFinite(value)) {
        if (value < min) min = value;
        if (value > max) max = value;
      }
    });
    field.min = Number.isFinite(min) ? min : null;
    field.max = Number.isFinite(max) ? max : null;
  });

  return {
    format,
    version,
    timestamp,
    started: new Date(timestamp * 1000).toISOString(),
    info,
    recordLength,
    fieldLength,
    fields,
    bitFieldNames: bitNames,
    records,
    markers,
    bytes: bytes.length,
  };
}

function mlgCsv(log, options = {}) {
  const limit = Number(options.limit) || 0;
  const fields = log.fields.filter((field) => field.kind !== 'bits');
  const header = ['record', 'counter', 'stamp', ...fields.map((field) => (
    field.units ? `${field.name} [${field.units}]` : field.name
  ))];
  const rows = [header.join(',')];
  const records = limit ? log.records.slice(0, limit) : log.records;
  records.forEach((record) => {
    rows.push([
      record.record,
      record.counter,
      record.stamp,
      ...fields.map((field) => {
        const value = record[field.name];
        return Number.isFinite(value) ? Number(value.toFixed(field.digits ?? 3)) : '';
      }),
    ].join(','));
  });
  return rows.join('\n');
}

if (typeof window !== 'undefined') {
  window.gobMlg = { parseMlg, mlgCsv, types: MLG_TYPES, error: MlgFormatError };
}

/* ---- panel wiring ------------------------------------------------------- */

if (typeof document !== 'undefined') {
  const el = (id) => document.getElementById(id);
  const setText = (id, text) => { const node = el(id); if (node) node.textContent = text; };
  const setHtml = (id, html) => { const node = el(id); if (node) node.innerHTML = html; };
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ).replace(/\uFFFD/g, ''));
  const state = { log: null, name: '' };

  const parseBtn = el('mlgParse');
  if (parseBtn) {
    parseBtn.onclick = async () => {
      setHtml('mlgOut', '');
      setText('mlgMeta', '');
      try {
        const file = el('mlgFile').files?.[0];
        if (!file) throw new Error('Choose a .mlg log first.');
        if (file.size > 128 * 1024 * 1024) throw new Error('Logs above 128 MiB are not parsed in the browser.');
        const buffer = new Uint8Array(await file.arrayBuffer());
        const log = parseMlg(buffer, { maxRecords: Number(el('mlgMax').value) || 500000 });
        state.log = log;
        state.name = file.name;
        const channelRows = log.fields.map((field) => `<tr><td><b>${escapeHtml(field.name)}</b></td>`
          + `<td>${escapeHtml(field.units || '')}</td>`
          + `<td>${field.kind === 'bits' ? `bits × ${field.bits}` : field.kind}</td>`
          + `<td>${field.scale === undefined ? '' : field.scale}</td>`
          + `<td>${field.transform === undefined ? '' : field.transform}</td>`
          + `<td>${field.digits === undefined ? '' : field.digits}</td>`
          + `<td>${field.min === null || field.min === undefined ? '' : field.min.toFixed(3)}</td>`
          + `<td>${field.max === null || field.max === undefined ? '' : field.max.toFixed(3)}</td>`
          + `<td>${field.displayStyle}</td>`
          + `<td>${escapeHtml(field.category || '')}</td></tr>`).join('');
        const preview = log.records.slice(0, 8).map((record) => '<tr>'
          + `<td>${record.record}</td><td>${record.stamp}</td>`
          + log.fields.filter((field) => field.kind !== 'bits').slice(0, 8)
            .map((field) => `<td>${Number.isFinite(record[field.name]) ? Number(record[field.name]).toFixed(field.digits ?? 2) : ''}</td>`)
            .join('')
          + '</tr>').join('');
        setHtml('mlgOut', `<div class="kv">`
          + `<div><span>Format</span><b>${escapeHtml(log.format)} v${log.version}</b></div>`
          + `<div><span>Logged</span><b>${escapeHtml(log.started)}</b></div>`
          + `<div><span>Records</span><b>${log.records.length.toLocaleString()}</b></div>`
          + `<div><span>Channels</span><b>${log.fields.length}</b></div>`
          + `<div class="full"><span>Log info</span><code>${escapeHtml(log.info || '(none)')}</code></div>`
          + `</div>`
          + (log.markers.length ? `<p class="small">${log.markers.length} marker(s), first at record `
            + `${log.markers[0].index}: ${escapeHtml(log.markers[0].message)}</p>` : '')
          + '<h3>Channels</h3><div class="table-wrap"><table class="data"><thead><tr><th>Channel</th><th>Units</th>'
          + '<th>Type</th><th>Scale</th><th>Transform</th><th>Digits</th><th>Min</th><th>Max</th><th>Display</th>'
          + '<th>Category</th></tr></thead><tbody>' + channelRows + '</tbody></table></div>'
          + '<h3>First records</h3><div class="table-wrap"><table class="data"><thead><tr><th>#</th><th>Stamp</th>'
          + log.fields.filter((field) => field.kind !== 'bits').slice(0, 8)
            .map((field) => `<th>${escapeHtml(field.name)}</th>`).join('')
          + '</tr></thead><tbody>' + preview + '</tbody></table></div>'
          + '<p class="muted small">Values are the log\u2019s own: raw \u00d7 scale + transform, in the units the '
          + 'logging definition declared. The per-record stamp is a 16-bit counter that wraps, and MLVLG does not '
          + 'record its unit, so no seconds are invented here.</p>');
        setText('mlgMeta', `${file.name} · ${(file.size / 1024).toFixed(0)} KiB · ${log.records.length} record(s)`
          + ` · ${log.fields.length} channel(s)`);
        el('mlgClear').disabled = false;
        el('mlgDownload').disabled = false;
      } catch (error) {
        setText('mlgMeta', `Not parsed: ${error.message}`);
      }
    };
  }

  const download = el('mlgDownload');
  if (download) {
    download.onclick = () => {
      if (!state.log) return;
      const csv = mlgCsv(state.log);
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = state.name.replace(/\.[^.]+$/, '') + '.csv';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    };
  }

  const clear = el('mlgClear');
  if (clear) {
    clear.onclick = () => {
      state.log = null;
      state.name = '';
      el('mlgFile').value = '';
      setHtml('mlgOut', '');
      setText('mlgMeta', '');
      clear.disabled = true;
      el('mlgDownload').disabled = true;
    };
  }
}
