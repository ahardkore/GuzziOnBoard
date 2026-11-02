/* CAN database (DBC) importer and frame decoder.
 *
 * Reads the parts of the Vector DBC format a capture review actually needs:
 * BO_ messages, SG_ signals (start bit, length, byte order, sign, scale,
 * offset, min/max, unit, receivers), VAL_ value tables, CM_ comments,
 * SIG_VALTYPE_ floats and BA_ "GenSigStartValue". Format semantics follow the
 * canmatrix documentation (ebroecker/canmatrix, BSD-2-Clause, revision
 * 8b54a41dd44b); no code was copied. Decoding is arithmetic on frames the
 * operator pastes — nothing here opens a bus.
 */
'use strict';

const DBC_SYSTEM = { 0: 'P', 1: 'C', 2: 'B', 3: 'U' };

function dbcNumber(text) {
  const value = Number(String(text).trim());
  if (!Number.isFinite(value)) throw new Error(`"${text}" is not a number.`);
  return value;
}

function parseDbc(text) {
  const warnings = [];
  const messages = new Map();
  let current = null;
  String(text || '').split(/\r?\n/).forEach((rawLine, index) => {
    const line = rawLine.trim();
    if (!line) return;
    let match = line.match(/^BO_\s+(\d+)\s+([^:]+):\s*(\d+)\s*(\S*)/);
    if (match) {
      const id = Number(match[1]);
      current = {
        id,
        name: match[2].trim(),
        dlc: Number(match[3]),
        transmitter: match[4] || '',
        signals: [],
        comment: '',
        cycleTime: null,
        line: index + 1,
      };
      if (messages.has(id)) warnings.push(`Line ${index + 1}: message ${id} (${current.name}) appears twice; the later one wins.`);
      messages.set(id, current);
      return;
    }
    match = line.match(/^SG_\s+(\w+)\s*(M|m\d+)?\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*\(([^,]+),([^)]+)\)\s*\[([^|]*)\|([^\]]*)\]\s*"([^"]*)"\s*(.*)$/);
    if (match) {
      if (!current) {
        warnings.push(`Line ${index + 1}: a signal outside any message was ignored.`);
        return;
      }
      const [, name, mux, start, length, order, sign, factor, offset, min, max, unit, receivers] = match;
      const signal = {
        name,
        multiplexer: mux || '',
        start: Number(start),
        length: Number(length),
        littleEndian: order === '1',
        signed: sign === '-',
        factor: dbcNumber(factor),
        offset: dbcNumber(offset),
        min: min === '' ? null : dbcNumber(min),
        max: max === '' ? null : dbcNumber(max),
        unit,
        receivers: receivers.trim(),
        values: new Map(),
        comment: '',
        startValue: null,
        float: false,
      };
      if (signal.start < 0 || signal.length < 1 || signal.length > 64) {
        warnings.push(`Line ${index + 1}: ${name} has an impossible start/length (${signal.start}/${signal.length}); kept but not decodable.`);
      }
      current.signals.push(signal);
      return;
    }
    match = line.match(/^VAL_\s+(\d+)\s+(\w+)\s+(.*);?\s*$/);
    if (match) {
      const message = messages.get(Number(match[1]));
      const signal = message?.signals.find((entry) => entry.name === match[2]);
      if (!signal) {
        warnings.push(`Line ${index + 1}: VAL_ for ${match[1]}/${match[2]} names no parsed signal.`);
        return;
      }
      const table = match[3].match(/(-?\d+)\s+"([^"]*)"/g) || [];
      table.forEach((entry) => {
        const pair = entry.match(/(-?\d+)\s+"([^"]*)"/);
        if (pair) signal.values.set(Number(pair[1]), pair[2]);
      });
      return;
    }
    match = line.match(/^CM_\s+(SG_|BO_)\s+(\d+)(?:\s+(\w+))?\s+"(.*)"\s*;?\s*$/);
    if (match) {
      const message = messages.get(Number(match[2]));
      if (!message) return;
      if (match[1] === 'BO_') message.comment = match[4];
      else {
        const signal = message.signals.find((entry) => entry.name === match[3]);
        if (signal) signal.comment = match[4];
      }
      return;
    }
    match = line.match(/^SIG_VALTYPE_\s+(\d+)\s+(\w+)\s*:?\s*(\d+)\s*;?/);
    if (match) {
      const message = messages.get(Number(match[1]));
      const signal = message?.signals.find((entry) => entry.name === match[2]);
      if (signal) {
        if (Number(match[3]) === 4 || Number(match[3]) === 2) signal.float = true;
        if (Number(match[3]) === 0) warnings.push(`Line ${index + 1}: ${match[2]} uses the deprecated integer valtype 0; treated as integer.`);
      }
      return;
    }
    match = line.match(/^BA_\s+"GenSigStartValue"\s+SG_\s+(\d+)\s+(\w+)\s+(-?[\d.eE+]+)\s*;?/);
    if (match) {
      const message = messages.get(Number(match[1]));
      const signal = message?.signals.find((entry) => entry.name === match[2]);
      if (signal) signal.startValue = dbcNumber(match[3]);
      return;
    }
    match = line.match(/^BA_\s+"GenMsgCycleTime"\s+BO_\s+(\d+)\s+(-?\d+)\s*;?/);
    if (match) {
      const message = messages.get(Number(match[1]));
      if (message) message.cycleTime = Number(match[2]);
    }
  });

  const list = Array.from(messages.values()).sort((a, b) => a.id - b.id);
  return {
    messages: list,
    warnings,
    signalCount: list.reduce((total, message) => total + message.signals.length, 0),
    valueTables: list.reduce((total, message) => (
      total + message.signals.filter((signal) => signal.values.size).length
    ), 0),
  };
}

function dbcBit(bytes, position) {
  const byte = bytes[position >> 3];
  if (byte === undefined) return null;
  return (byte >> (position & 7)) & 1;
}

/** Extract a raw signal value.
 *
 *  Little-endian (Intel): the start bit is the least significant bit and the
 *  value grows as the bit position increases. Big-endian (Motorola): the start
 *  bit is the most significant bit, and the walk steps down within a byte,
 *  jumping from bit 0 to bit 7 of the next byte. Both use DBC numbering, where
 *  bit 0 is the least significant bit of byte 0.
 */
function dbcRaw(bytes, signal) {
  const { start, length, littleEndian } = signal;
  if (length < 1 || length > 64 || start < 0) return null;
  let raw = 0n;
  if (littleEndian) {
    for (let i = 0; i < length; i += 1) {
      const bit = dbcBit(bytes, start + i);
      if (bit === null) return null;
      raw |= BigInt(bit) << BigInt(i);
    }
  } else {
    let position = start;
    for (let i = 0; i < length; i += 1) {
      const bit = dbcBit(bytes, position);
      if (bit === null) return null;
      raw = (raw << 1n) | BigInt(bit);
      position = (position & 7) === 0 ? position + 15 : position - 1;
    }
  }
  if (signal.signed) {
    const limit = 1n << BigInt(length - 1);
    if (raw >= limit) raw -= 1n << BigInt(length);
  }
  return raw;
}

function dbcPhysical(signal, raw, floatValue) {
  if (floatValue !== undefined) return floatValue;
  return Number(raw) * signal.factor + signal.offset;
}

function decodeDbcMessage(message, data) {
  if (!message) throw new Error('No message to decode.');
  const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
  const missing = Math.max(0, message.dlc - bytes.length);
  const signals = [];
  message.signals.forEach((signal) => {
    if (signal.multiplexer.startsWith('m')) return; // multiplexed: needs the selector, reported separately
    if (signal.float) {
      const offsetBytes = signal.start >> 3;
      if (offsetBytes + 4 > bytes.length) return;
      const view = new DataView(bytes.buffer, bytes.byteOffset + offsetBytes, 4);
      const value = view.getFloat32(0, signal.littleEndian);
      signals.push({ name: signal.name, raw: value, value, unit: signal.unit, mapped: null });
      return;
    }
    const raw = dbcRaw(bytes, signal);
    if (raw === null) return;
    const value = dbcPhysical(signal, raw);
    signals.push({
      name: signal.name,
      raw: Number(raw),
      value,
      unit: signal.unit,
      mapped: signal.values.size ? (signal.values.get(Number(raw)) ?? null) : null,
    });
  });
  const multiplexed = message.signals.filter((signal) => signal.multiplexer.startsWith('m')).map((signal) => signal.name);
  return { message, signals, missingBytes: missing, multiplexed };
}

function decodeDbcLog(dbc, text) {
  if (typeof window === 'undefined' || !window.gobFrameLab) throw new Error('The frame parser is not loaded.');
  const byId = new Map(dbc.messages.map((message) => [message.id, message]));
  const frames = [];
  const unknown = new Map();
  const errors = [];
  String(text || '').split(/\r?\n/).forEach((line, index) => {
    if (!line.trim()) return;
    const frame = window.gobFrameLab.parseCandumpLine(line);
    if (!frame) {
      errors.push({ line: index + 1, text: line.trim() });
      return;
    }
    const message = byId.get(frame.identifier);
    if (!message) {
      unknown.set(frame.identifier, (unknown.get(frame.identifier) || 0) + 1);
      return;
    }
    const decoded = decodeDbcMessage(message, frame.data);
    frames.push({ ...decoded, time: frame.time, identifier: frame.identifier, length: frame.length, bytes: frame.data });
  });
  return {
    frames,
    unknown: Array.from(unknown, ([id, count]) => ({ id, count })).sort((a, b) => b.count - a.count),
    errors,
    messagesSeen: new Set(frames.map((frame) => frame.message.id)).size,
  };
}

function dbcCsv(result, options = {}) {
  const limit = Number(options.limit) || 0;
  const frames = limit ? result.frames.slice(0, limit) : result.frames;
  const names = new Set();
  frames.forEach((frame) => frame.signals.forEach((signal) => names.add(signal.name)));
  const columns = Array.from(names);
  const rows = [['time', 'identifier', 'message', ...columns].join(',')];
  frames.forEach((frame) => {
    const values = new Map(frame.signals.map((signal) => [signal.name, signal]));
    rows.push([
      frame.time === null || frame.time === undefined ? '' : frame.time,
      `0x${frame.identifier.toString(16).toUpperCase()}`,
      frame.message.name,
      ...columns.map((name) => {
        const signal = values.get(name);
        if (!signal) return '';
        return Number.isFinite(signal.value) ? Number(signal.value.toFixed(6)) : '';
      }),
    ].join(','));
  });
  return rows.join('\n');
}

if (typeof window !== 'undefined') {
  window.gobDbc = { parseDbc, decodeDbcMessage, decodeDbcLog, dbcCsv, dbcRaw };
}

/* ---- panel wiring ------------------------------------------------------- */

if (typeof document !== 'undefined') {
  const el = (id) => document.getElementById(id);
  const setText = (id, text) => { const node = el(id); if (node) node.textContent = text; };
  const setHtml = (id, html) => { const node = el(id); if (node) node.innerHTML = html; };
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
  const state = { dbc: null, decoded: null };

  const loadBtn = el('dbcLoad');
  if (loadBtn) {
    loadBtn.onclick = async () => {
      setText('dbcMeta', '');
      try {
        const file = el('dbcFile').files?.[0];
        if (!file) throw new Error('Choose a .dbc file.');
        if (file.size > 8 * 1024 * 1024) throw new Error('Databases above 8 MiB are not read here.');
        el('dbcIn').value = await file.text();
        setText('dbcMeta', `${file.name} · ${(file.size / 1024).toFixed(0)} KiB loaded — parse it below.`);
        el('dbcParse').click();
      } catch (error) {
        setText('dbcMeta', `Not loaded: ${error.message}`);
      }
    };
  }

  const parseBtn = el('dbcParse');
  if (parseBtn) {
    parseBtn.onclick = () => {
      setHtml('dbcOut', '');
      setText('dbcMeta', '');
      setHtml('dbcDecodeOut', '');
      try {
        const text = el('dbcIn').value;
        if (!text.trim()) throw new Error('Paste a .dbc file first.');
        const dbc = parseDbc(text);
        if (!dbc.messages.length) throw new Error('No BO_ message was found in that text.');
        state.dbc = dbc;
        const rows = dbc.messages.map((message) => `<tr><td><b>${escapeHtml(message.name)}</b></td>`
          + `<td><code>0x${message.id.toString(16).toUpperCase()}</code></td><td>${message.dlc}</td>`
          + `<td>${escapeHtml(message.transmitter || '')}</td><td>${message.signals.length}</td>`
          + `<td>${message.cycleTime === null ? '' : `${message.cycleTime} ms`}</td>`
          + `<td>${escapeHtml(message.comment || '')}</td></tr>`).join('');
        const signalRows = dbc.messages.flatMap((message) => message.signals.map((signal) => `<tr>`
          + `<td>${escapeHtml(message.name)}</td><td><b>${escapeHtml(signal.name)}</b></td>`
          + `<td>${signal.start}|${signal.length}</td>`
          + `<td>${signal.littleEndian ? 'Intel (little)' : 'Motorola (big)'}</td>`
          + `<td>${signal.signed ? 'signed' : 'unsigned'}</td>`
          + `<td>${signal.factor}</td><td>${signal.offset}</td>`
          + `<td>${escapeHtml(signal.unit)}</td>`
          + `<td>${signal.values.size ? Array.from(signal.values, ([k, v]) => `${k}=${v}`).join(', ') : ''}</td>`
          + '</tr>')).join('');
        setHtml('dbcOut', `<div class="kv">`
          + `<div><span>Messages</span><b>${dbc.messages.length}</b></div>`
          + `<div><span>Signals</span><b>${dbc.signalCount}</b></div>`
          + `<div><span>Value tables</span><b>${dbc.valueTables}</b></div>`
          + `</div>`
          + (dbc.warnings.length ? `<ul class="small">${dbc.warnings.slice(0, 12).map((warning) => `<li>${escapeHtml(warning)}</li>`).join('')}</ul>` : '')
          + '<h3>Messages</h3><div class="table-wrap"><table class="data"><thead><tr><th>Message</th><th>Id</th>'
          + '<th>DLC</th><th>Sender</th><th>Signals</th><th>Cycle</th><th>Comment</th></tr></thead><tbody>'
          + rows + '</tbody></table></div>'
          + '<h3>Signals</h3><div class="table-wrap"><table class="data"><thead><tr><th>Message</th><th>Signal</th>'
          + '<th>Start|Len</th><th>Order</th><th>Sign</th><th>Factor</th><th>Offset</th><th>Unit</th>'
          + '<th>Value table</th></tr></thead><tbody>' + signalRows + '</tbody></table></div>');
        setText('dbcMeta', `${dbc.messages.length} message(s) · ${dbc.signalCount} signal(s)`
          + (dbc.warnings.length ? ` · ${dbc.warnings.length} warning(s)` : ''));
      } catch (error) {
        setText('dbcMeta', `Not parsed: ${error.message}`);
      }
    };
  }

  const decodeBtn = el('dbcDecode');
  if (decodeBtn) {
    decodeBtn.onclick = () => {
      setHtml('dbcDecodeOut', '');
      try {
        if (!state.dbc) throw new Error('Parse a .dbc file above first.');
        const result = decodeDbcLog(state.dbc, el('dbcLog').value);
        state.decoded = result;
        if (!result.frames.length) {
          setHtml('dbcDecodeOut', '<p class="tip warn"><b>No frame matched.</b> The pasted identifiers are not in '
            + 'this database, or the log is in a format the frame parser does not read.</p>');
          return;
        }
        const names = [];
        result.frames.forEach((frame) => frame.signals.forEach((signal) => {
          if (!names.includes(signal.name)) names.push(signal.name);
        }));
        const preview = result.frames.slice(0, 40).map((frame) => {
          const map = new Map(frame.signals.map((signal) => [signal.name, signal]));
          return `<tr><td>${frame.time === null ? '' : frame.time}</td>`
            + `<td><code>0x${frame.identifier.toString(16).toUpperCase()}</code></td>`
            + `<td>${escapeHtml(frame.message.name)}</td>`
            + names.slice(0, 8).map((name) => {
              const signal = map.get(name);
              if (!signal) return '<td></td>';
              return `<td>${Number(signal.value).toFixed(3)}${signal.mapped ? ` <em>${escapeHtml(signal.mapped)}</em>` : ''}</td>`;
            }).join('') + '</tr>';
        }).join('');
        setHtml('dbcDecodeOut', `<p class="small">${result.frames.length} frame(s) decoded across `
          + `${result.messagesSeen} message(s)`
          + (result.unknown.length ? ` · ${result.unknown.length} identifier(s) not in the database` : '')
          + (result.errors.length ? ` · ${result.errors.length} line(s) unreadable` : '') + '.</p>'
          + `<div class="table-wrap"><table class="data"><thead><tr><th>Time</th><th>Id</th><th>Message</th>`
          + names.slice(0, 8).map((name) => `<th>${escapeHtml(name)}</th>`).join('')
          + '</tr></thead><tbody>' + preview + '</tbody></table></div>'
          + (result.unknown.length ? `<p class="muted small">Not in the database: `
            + result.unknown.slice(0, 8).map((entry) => `0x${entry.id.toString(16).toUpperCase()} ×${entry.count}`).join(', ')
            + '.</p>' : '')
          + '<p class="muted small">Decoded values are raw \u00d7 factor + offset in the units the database '
          + 'declares. A DBC describes one source\u2019s understanding of a bus: identifiers can collide across '
          + 'model years, and multiplexed signals need their selector, so they are skipped rather than guessed.</p>');
        setText('dbcMeta', `${state.dbc.messages.length} message(s) · ${result.frames.length} frame(s) decoded`);
        el('dbcDownload').disabled = false;
      } catch (error) {
        setText('dbcMeta', `Not decoded: ${error.message}`);
      }
    };
  }

  const download = el('dbcDownload');
  if (download) {
    download.onclick = () => {
      if (!state.decoded) return;
      const url = URL.createObjectURL(new Blob([dbcCsv(state.decoded)], { type: 'text/csv' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'dbc-decoded.csv';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    };
  }
}
