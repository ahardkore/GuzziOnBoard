/* Tune-file diff.
 *
 * Compares two calibration files the way a tuner actually reads them: constants
 * by name, tables cell by cell, and log columns by statistics. Reads:
 *   - TunerStudio / MegaSquirt / Speeduino .msq (XML: <constant>, <table> with
 *     <x>/<y>/<z> rows),
 *   - TunerStudio-style .ini (sections and key = value),
 *   - MotoLink tune files (XML: <Motolink>/<Properties>/<Tables><Table Name>),
 *   - logger CSV exports.
 * Nothing is written, uploaded or applied: a difference is a question to
 * answer, not an edit to make.
 */
'use strict';

const TUNE_NUMERIC_EPSILON = 1e-9;

function tuneNumbers(text) {
  if (text === null || text === undefined) return [];
  return String(text)
    .split(/[\s,;]+/)
    .map((token) => token.trim())
    .filter(Boolean)
    .map((token) => Number(token))
    .filter((value) => Number.isFinite(value));
}

function tuneNumberOrText(value) {
  if (value === null || value === undefined) return '';
  const text = String(value).trim();
  if (!text) return '';
  const numeric = Number(text);
  return Number.isFinite(numeric) && /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(text) ? numeric : text;
}

function parseMsq(text) {
  const constants = {};
  const tables = [];
  if (typeof DOMParser !== 'undefined') {
    const doc = new DOMParser().parseFromString(text, 'text/xml');
    if (doc.querySelector('parsererror')) throw new Error('The .msq is not well-formed XML.');
    doc.querySelectorAll('constant').forEach((node) => {
      const name = node.getAttribute('name');
      if (!name) return;
      const value = node.getAttribute('value') ?? node.querySelector('value')?.textContent ?? '';
      constants[name] = tuneNumberOrText(value);
    });
    doc.querySelectorAll('table').forEach((node) => {
      const name = node.getAttribute('name') || `table ${tables.length + 1}`;
      const read = (tag) => tuneNumbers(node.querySelector(tag)?.textContent || '');
      const z = read('z');
      const x = read('x');
      const y = read('y');
      if (!z.length && !x.length && !y.length) return;
      const cols = x.length || (z.length && y.length ? Math.round(z.length / y.length) : 0);
      tables.push({ name, x, y, z, rows: cols ? Math.ceil(z.length / cols) : 0, cols });
    });
    return { constants, tables };
  }
  // Regex fallback for environments without DOMParser.
  const constantRe = /<constant\b([^>]*?)(?:\/>|>([\s\S]*?)<\/constant>)/g;
  let match;
  while ((match = constantRe.exec(text))) {
    const attrs = match[1];
    const name = (attrs.match(/name\s*=\s*"([^"]*)"/) || [])[1];
    if (!name) continue;
    const valueAttr = (attrs.match(/value\s*=\s*"([^"]*)"/) || [])[1];
    const valueChild = (match[2] || '').match(/<value>\s*([^<]*)\s*<\/value>/);
    constants[name] = tuneNumberOrText(valueAttr ?? valueChild?.[1] ?? '');
  }
  const tableRe = /<table\b([^>]*)>([\s\S]*?)<\/table>/g;
  while ((match = tableRe.exec(text))) {
    const name = (match[1].match(/name\s*=\s*"([^"]*)"/) || [])[1] || `table ${tables.length + 1}`;
    const body = match[2];
    const read = (tag) => tuneNumbers((body.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`)) || [])[1] || '');
    const z = read('z');
    const x = read('x');
    const y = read('y');
    if (!z.length && !x.length && !y.length) continue;
    const cols = x.length || (z.length && y.length ? Math.round(z.length / y.length) : 0);
    tables.push({ name, x, y, z, rows: cols ? Math.ceil(z.length / cols) : 0, cols });
  }
  return { constants, tables };
}

/* MotoLink's tune file, read from upstream mtlfile.cpp (fpoussin/MotoLink, GPL-3.0):
 * the writer emits <Motolink><Info date version><Settings/><Properties> with one
 * <Property Name="…">value</Property> per setting, then shared <Rows>/<Columns>
 * axis labels, then <Tables><Table Name="AFR"><Row><Column>…</Column></Row>…
 * Readers require all four elements and refuse anything whose root is not
 * <Motolink>. The GUI writes the settings RpmMult, SpeedMult, AFRInput, TPS0,
 * TPS100, AFR0V and AFR5V, and the three permanent tables AFR, AFR Target and
 * Knock. */
const MTL_PROPERTIES = ['RpmMult', 'SpeedMult', 'AFRInput', 'TPS0', 'TPS100', 'AFR0V', 'AFR5V'];

function parseMtl(text) {
  const body = String(text || '');
  if (typeof DOMParser !== 'undefined') {
    const doc = new DOMParser().parseFromString(body, 'text/xml');
    if (doc.querySelector('parsererror')) throw new Error('The MotoLink file is not well-formed XML.');
    const root = doc.documentElement;
    if (!root || root.tagName !== 'Motolink') throw new Error('Not a MotoLink tune file: the root element is not <Motolink>.');
    const constants = {};
    const axis = { rows: [], columns: [] };
    doc.querySelectorAll('Properties > Property').forEach((node) => {
      const name = node.getAttribute('Name');
      if (name) constants[name] = tuneNumberOrText(node.textContent);
    });
    doc.querySelectorAll('Rows > Row').forEach((node) => axis.rows.push(node.textContent.trim()));
    doc.querySelectorAll('Columns > Column').forEach((node) => axis.columns.push(node.textContent.trim()));
    const tables = [];
    doc.querySelectorAll('Tables > Table').forEach((node, index) => {
      const name = node.getAttribute('Name') || `table ${index + 1}`;
      const z = [];
      let cols = 0;
      node.querySelectorAll(':scope > Row').forEach((row) => {
        const cells = Array.from(row.querySelectorAll(':scope > Column')).map((cell) => tuneNumberOrText(cell.textContent));
        cols = Math.max(cols, cells.length);
        cells.forEach((cell) => z.push(cell));
      });
      if (!z.length) return;
      tables.push({ name, x: [], y: [], z, rows: cols ? Math.ceil(z.length / cols) : 0, cols });
    });
    const info = doc.querySelector('Info');
    return {
      constants,
      tables,
      axis,
      format: 'MotoLink',
      info: {
        version: info?.getAttribute('version') || '',
        date: info?.getAttribute('date') || '',
        // Which of the settings the upstream GUI reads are actually present:
        // a file that carries none of them is a table dump, not a tune.
        settings: MTL_PROPERTIES.filter((name) => name in constants),
      },
    };
  }
  // Regex fallback for environments without DOMParser.
  if (!/<Motolink\b/i.test(body)) throw new Error('Not a MotoLink tune file: the root element is not <Motolink>.');
  const constants = {};
  const propRe = /<Property\s+Name="([^"]*)"\s*>([^<]*)<\/Property>/g;
  let match;
  while ((match = propRe.exec(body))) constants[match[1]] = tuneNumberOrText(match[2]);
  const axis = { rows: [], columns: [] };
  const rowsBlock = (body.match(/<Rows\b[^>]*>([\s\S]*?)<\/Rows>/) || [])[1] || '';
  const columnsBlock = (body.match(/<Columns\b[^>]*>([\s\S]*?)<\/Columns>/) || [])[1] || '';
  (rowsBlock.match(/<Row>([\s\S]*?)<\/Row>/g) || []).forEach((row) => {
    axis.rows.push((row.match(/<Row>([\s\S]*?)<\/Row>/) || [])[1].trim());
  });
  (columnsBlock.match(/<Column>([\s\S]*?)<\/Column>/g) || []).forEach((cell) => {
    axis.columns.push((cell.match(/<Column>([\s\S]*?)<\/Column>/) || [])[1].trim());
  });
  const tables = [];
  const tableRe = /<Table\s+Name="([^"]*)"\s*>([\s\S]*?)<\/Table>/g;
  while ((match = tableRe.exec(body))) {
    const z = [];
    let cols = 0;
    (match[2].match(/<Row>([\s\S]*?)<\/Row>/g) || []).forEach((row) => {
      const cells = (row.match(/<Column>([\s\S]*?)<\/Column>/g) || [])
        .map((cell) => tuneNumberOrText((cell.match(/<Column>([\s\S]*?)<\/Column>/) || [])[1]));
      cols = Math.max(cols, cells.length);
      cells.forEach((cell) => z.push(cell));
    });
    if (!z.length) continue;
    tables.push({ name: match[1], x: [], y: [], z, rows: cols ? Math.ceil(z.length / cols) : 0, cols });
  }
  const info = body.match(/<Info\b([^>]*)\/?>/);
  const attributes = info ? info[1] : '';
  return {
    constants,
    tables,
    axis,
    format: 'MotoLink',
    info: {
      version: (attributes.match(/version="([^"]*)"/) || [])[1] || '',
      date: (attributes.match(/date="([^"]*)"/) || [])[1] || '',
      settings: MTL_PROPERTIES.filter((name) => name in constants),
    },
  };
}

function parseIni(text) {
  const constants = {};
  let section = '';
  String(text || '').split(/\r?\n/).forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line || line.startsWith(';') || line.startsWith('#')) return;
    const header = line.match(/^\[([^\]]+)\]$/);
    if (header) {
      section = header[1].trim();
      return;
    }
    const pair = line.match(/^([A-Za-z0-9_.\- ]+?)\s*=\s*(.*)$/);
    if (!pair) return;
    const key = section ? `${section}.${pair[1].trim()}` : pair[1].trim();
    constants[key] = tuneNumberOrText(pair[2].replace(/\s*;.*$/, ''));
  });
  return { constants, tables: [] };
}

function parseCsv(text) {
  const lines = String(text || '').split(/\r?\n/).filter((line) => line.trim());
  if (!lines.length) throw new Error('The CSV is empty.');
  const delimiter = (lines[0].match(/;/g) || []).length > (lines[0].match(/,/g) || []).length ? ';' : ',';
  const header = lines[0].split(delimiter).map((cell) => cell.trim().replace(/^"|"$/g, ''));
  const rows = [];
  for (let i = 1; i < lines.length; i += 1) {
    const cells = lines[i].split(delimiter).map((cell) => cell.trim().replace(/^"|"$/g, ''));
    if (cells.length < 2) continue;
    rows.push(cells);
  }
  return { header, rows, delimiter };
}

function parseTuneText(name, text) {
  const body = String(text || '');
  // MotoLink first: its XML also contains <Table>, which the .msq branch would
  // claim, so the root element decides before any generic tag test runs.
  if (/<Motolink\b/i.test(body)) {
    const parsed = parseMtl(body);
    return { name, kind: 'mtl', ...parsed };
  }
  if (/<msq\b|<constant\b|<table\b/i.test(body)) {
    const parsed = parseMsq(body);
    return { name, kind: 'msq', ...parsed };
  }
  if (/^\s*[[A-Za-z0-9_.\- ]+\]/m.test(body) && /^\s*[A-Za-z0-9_.\- ]+\s*=/m.test(body)) {
    const parsed = parseIni(body);
    return { name, kind: 'ini', ...parsed };
  }
  const csv = parseCsv(body);
  return { name, kind: 'csv', ...csv };
}

function tuneValuesEqual(a, b) {
  if (typeof a === 'number' && typeof b === 'number') {
    return Math.abs(a - b) <= TUNE_NUMERIC_EPSILON * Math.max(1, Math.abs(a), Math.abs(b));
  }
  return String(a) === String(b);
}

function diffConstants(a, b) {
  const added = [];
  const removed = [];
  const changed = [];
  Object.keys(b.constants).forEach((key) => {
    if (!(key in a.constants)) added.push({ key, value: b.constants[key] });
  });
  Object.keys(a.constants).forEach((key) => {
    if (!(key in b.constants)) {
      removed.push({ key, value: a.constants[key] });
      return;
    }
    const before = a.constants[key];
    const after = b.constants[key];
    if (tuneValuesEqual(before, after)) return;
    const delta = typeof before === 'number' && typeof after === 'number' ? after - before : null;
    changed.push({
      key,
      before,
      after,
      delta,
      percent: delta !== null && before !== 0 ? (delta / before) * 100 : null,
    });
  });
  changed.sort((x, y) => Math.abs(y.delta ?? 0) - Math.abs(x.delta ?? 0));
  added.sort((x, y) => x.key.localeCompare(y.key));
  removed.sort((x, y) => x.key.localeCompare(y.key));
  return { added, removed, changed };
}

function diffTables(a, b) {
  const added = [];
  const removed = [];
  const changed = [];
  const namesA = new Map(a.tables.map((table) => [table.name, table]));
  const namesB = new Map(b.tables.map((table) => [table.name, table]));
  namesB.forEach((table, name) => {
    if (!namesA.has(name)) added.push({ name, cells: table.z.length });
  });
  namesA.forEach((table, name) => {
    if (!namesB.has(name)) {
      removed.push({ name, cells: table.z.length });
      return;
    }
    const other = namesB.get(name);
    const cells = [];
    const count = Math.max(table.z.length, other.z.length);
    let maxDelta = 0;
    let totalDelta = 0;
    for (let i = 0; i < count; i += 1) {
      const before = table.z[i];
      const after = other.z[i];
      if (tuneValuesEqual(before, after)) continue;
      const delta = typeof before === 'number' && typeof after === 'number' ? after - before : null;
      if (delta !== null) {
        maxDelta = Math.max(maxDelta, Math.abs(delta));
        totalDelta += delta;
      }
      if (cells.length < 12) {
        cells.push({
          index: i,
          row: table.cols ? Math.floor(i / table.cols) : null,
          col: table.cols ? i % table.cols : null,
          before,
          after,
          delta,
        });
      }
    }
    const axisXChanged = table.x.length !== other.x.length
      || table.x.some((value, i) => !tuneValuesEqual(value, other.x[i]));
    const axisYChanged = table.y.length !== other.y.length
      || table.y.some((value, i) => !tuneValuesEqual(value, other.y[i]));
    if (!cells.length && !axisXChanged && !axisYChanged) return;
    changed.push({
      name,
      changedCells: cells.length && count === table.z.length
        ? table.z.reduce((total, value, i) => total + (tuneValuesEqual(value, other.z[i]) ? 0 : 1), 0)
        : null,
      shape: { before: [table.rows, table.cols], after: [other.rows, other.cols] },
      axisXChanged,
      axisYChanged,
      maxDelta,
      meanDelta: cells.length ? totalDelta / cells.length : 0,
      cells,
      truncated: count > 12 && cells.length === 12,
    });
  });
  changed.sort((x, y) => y.maxDelta - x.maxDelta || x.name.localeCompare(y.name));
  added.sort((x, y) => x.name.localeCompare(y.name));
  removed.sort((x, y) => x.name.localeCompare(y.name));
  return { added, removed, changed };
}

function diffCsvTables(a, b) {
  const counts = new Map();
  b.header.forEach((name) => counts.set(name, { name, changed: 0, maxDelta: 0, totalDelta: 0, samples: [], numeric: true }));
  const rows = Math.min(a.rows.length, b.rows.length);
  const indexA = new Map(a.header.map((name, i) => [name, i]));
  const indexB = new Map(b.header.map((name, i) => [name, i]));
  b.header.forEach((name) => {
    const entry = counts.get(name);
    if (!indexA.has(name)) {
      entry.numeric = false;
      return;
    }
    const ia = indexA.get(name);
    const ib = indexB.get(name);
    for (let r = 0; r < rows; r += 1) {
      const beforeRaw = a.rows[r]?.[ia];
      const afterRaw = b.rows[r]?.[ib];
      const before = Number(beforeRaw);
      const after = Number(afterRaw);
      const numeric = beforeRaw !== '' && afterRaw !== '' && Number.isFinite(before) && Number.isFinite(after);
      if (numeric) {
        const delta = after - before;
        if (Math.abs(delta) <= TUNE_NUMERIC_EPSILON) continue;
        entry.changed += 1;
        entry.maxDelta = Math.max(entry.maxDelta, Math.abs(delta));
        entry.totalDelta += delta;
        if (entry.samples.length < 5) entry.samples.push({ row: r + 2, before, after, delta });
      } else if (String(beforeRaw) !== String(afterRaw)) {
        entry.numeric = false;
        entry.changed += 1;
      }
    }
  });
  const columns = Array.from(counts.values());
  columns.forEach((column) => {
    column.meanDelta = column.changed ? column.totalDelta / column.changed : 0;
  });
  return {
    columns,
    rowsCompared: rows,
    rowMismatch: a.rows.length - b.rows.length,
    addedColumns: b.header.filter((name) => !indexA.has(name)),
    removedColumns: a.header.filter((name) => !indexB.has(name)),
    changedColumns: columns.filter((column) => column.changed).length,
  };
}

function diffTunes(a, b) {
  if (!a || !b) throw new Error('Load two files to compare.');
  if (a.kind === 'csv' || b.kind === 'csv') {
    if (a.kind !== 'csv' || b.kind !== 'csv') throw new Error('A CSV log can only be compared with another CSV log.');
    return { kind: 'csv', ...diffCsvTables(a, b) };
  }
  const constants = diffConstants(a, b);
  const tables = diffTables(a, b);
  return {
    kind: a.kind === b.kind ? a.kind : 'mixed',
    constants,
    tables,
    changed: constants.changed.length + tables.changed.length,
    added: constants.added.length + tables.added.length,
    removed: constants.removed.length + tables.removed.length,
  };
}

if (typeof window !== 'undefined') {
  window.gobTuneDiff = { parseTuneText, diffTunes, diffConstants, diffTables, diffCsvTables };
}

/* ---- panel wiring ------------------------------------------------------- */

if (typeof document !== 'undefined') {
  const el = (id) => document.getElementById(id);
  const setText = (id, text) => { const node = el(id); if (node) node.textContent = text; };
  const setHtml = (id, html) => { const node = el(id); if (node) node.innerHTML = html; };
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
  const fmt = (value) => {
    if (value === null || value === undefined) return '';
    if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
    return escapeHtml(value);
  };

  const compareBtn = el('tuneDiffBtn');
  if (compareBtn) {
    compareBtn.onclick = async () => {
      setHtml('tuneDiffOut', '');
      setText('tuneDiffMeta', '');
      try {
        const first = el('tuneDiffA').files?.[0];
        const second = el('tuneDiffB').files?.[0];
        if (!first || !second) throw new Error('Choose two files.');
        if (first.size > 32 * 1024 * 1024 || second.size > 32 * 1024 * 1024) throw new Error('Files above 32 MiB are not compared here.');
        const a = parseTuneText(first.name, await first.text());
        const b = parseTuneText(second.name, await second.text());
        const result = diffTunes(a, b);
        if (result.kind === 'csv') {
          const rows = result.columns.map((column) => `<tr><td><b>${escapeHtml(column.name)}</b></td>`
            + `<td>${column.changed}</td><td>${column.numeric ? fmt(column.maxDelta) : '—'}</td>`
            + `<td>${column.numeric ? fmt(column.meanDelta) : '—'}</td>`
            + `<td>${column.samples.slice(0, 3).map((sample) => `row ${sample.row}: ${fmt(sample.before)} → ${fmt(sample.after)}`).join('<br>')}</td></tr>`).join('');
          setHtml('tuneDiffOut', `<p class="small">${result.rowsCompared} row(s) compared`
            + (result.rowMismatch ? ` · ${Math.abs(result.rowMismatch)} row(s) ${result.rowMismatch > 0 ? 'missing from' : 'extra in'} the second file` : '')
            + ` · ${result.changedColumns} column(s) moved.</p>`
            + (result.addedColumns.length ? `<p class="small">Columns only in the second file: ${escapeHtml(result.addedColumns.join(', '))}</p>` : '')
            + (result.removedColumns.length ? `<p class="small">Columns only in the first file: ${escapeHtml(result.removedColumns.join(', '))}</p>` : '')
            + '<div class="table-wrap"><table class="data"><thead><tr><th>Column</th><th>Cells changed</th>'
            + '<th>Largest Δ</th><th>Mean Δ</th><th>Samples</th></tr></thead><tbody>' + rows + '</tbody></table></div>');
          setText('tuneDiffMeta', `${first.name} vs ${second.name} · CSV · ${result.changedColumns} column(s) moved`);
          return;
        }
        const constantRows = result.constants.changed.map((entry) => `<tr><td><b>${escapeHtml(entry.key)}</b></td>`
          + `<td>${fmt(entry.before)}</td><td>${fmt(entry.after)}</td>`
          + `<td>${entry.delta === null ? '' : `${entry.delta > 0 ? '+' : ''}${fmt(entry.delta)}`}</td>`
          + `<td>${entry.percent === null ? '' : `${entry.percent > 0 ? '+' : ''}${entry.percent.toFixed(1)} %`}</td></tr>`).join('');
        const tableRows = result.tables.changed.map((table) => `<tr><td><b>${escapeHtml(table.name)}</b></td>`
          + `<td>${table.changedCells === null ? 'shape changed' : table.changedCells}</td>`
          + `<td>${fmt(table.maxDelta)}</td><td>${fmt(table.meanDelta)}</td>`
          + `<td>${table.axisXChanged ? 'X ' : ''}${table.axisYChanged ? 'Y' : ''}</td>`
          + `<td>${table.cells.slice(0, 3).map((cell) => `${cell.row === null ? '#' : `[${cell.row},${cell.col}]`} ${fmt(cell.before)} → ${fmt(cell.after)}`).join('<br>')}</td></tr>`).join('');
        setHtml('tuneDiffOut', `<div class="kv">`
          + `<div><span>Changed</span><b>${result.changed}</b></div>`
          + `<div><span>Only in second</span><b>${result.added}</b></div>`
          + `<div><span>Only in first</span><b>${result.removed}</b></div>`
          + `<div><span>Untouched constants</span><b>${Object.keys(a.constants).length - result.constants.changed.length - result.constants.removed.length}</b></div>`
          + `</div>`
          + (constantRows ? '<h3>Constants</h3><div class="table-wrap"><table class="data"><thead><tr>'
            + '<th>Constant</th><th>First</th><th>Second</th><th>Δ</th><th>Δ %</th></tr></thead><tbody>'
            + constantRows + '</tbody></table></div>' : '')
          + (result.constants.added.length ? `<p class="small">Only in the second file: ${result.constants.added.slice(0, 12).map((entry) => `${escapeHtml(entry.key)} = ${fmt(entry.value)}`).join(', ')}</p>` : '')
          + (result.constants.removed.length ? `<p class="small">Only in the first file: ${result.constants.removed.slice(0, 12).map((entry) => `${escapeHtml(entry.key)} = ${fmt(entry.value)}`).join(', ')}</p>` : '')
          + (tableRows ? '<h3>Tables</h3><div class="table-wrap"><table class="data"><thead><tr><th>Table</th>'
            + '<th>Cells changed</th><th>Largest Δ</th><th>Mean Δ</th><th>Axis</th><th>Samples</th></tr></thead><tbody>'
            + tableRows + '</tbody></table></div>' : '')
          + (result.tables.added.length || result.tables.removed.length
            ? `<p class="small">Tables only in the second file: ${escapeHtml(result.tables.added.map((t) => t.name).join(', ') || 'none')}. `
              + `Only in the first: ${escapeHtml(result.tables.removed.map((t) => t.name).join(', ') || 'none')}.</p>` : '')
          + '<p class="muted small">A difference is a question, not an instruction: the same change can be a fix, '
          + 'a mistake or a different firmware\u2019s addressing. Nothing here writes, applies or uploads a tune.</p>');
        setText('tuneDiffMeta', `${first.name} vs ${second.name} · ${a.kind.toUpperCase()} · `
          + `${result.changed} change(s), ${result.added} added, ${result.removed} removed`);
      } catch (error) {
        setText('tuneDiffMeta', `Not compared: ${error.message}`);
      }
    };
  }
}
