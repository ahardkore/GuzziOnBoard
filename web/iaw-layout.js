/* IAW image layout and definition fit.
 *
 * Answers two questions about a dump of a Marelli IAW ECU, without an ECU and
 * without guessing:
 *   1. Where does this file sit inside the image, and how big is the image?
 *   2. Does the definition I want to use describe tables that are actually in
 *      this file? Every address and size comes from the definition itself.
 *
 * The only geometry this file states as fact is the IAW 5AM flash region
 * (0x4000-0x50000, 311,296 bytes inside a 320 KiB image), which is the same
 * constant the catalog, the help guides and guzzionboard/catalog/ecus/5am.json
 * carry. Everything else is offered as a suggestion the operator confirms.
 */
'use strict';

const IAW_GEOMETRY = {
  '5am-flash': {
    id: '5am-flash',
    label: 'IAW 5AM flash region · 0x4000–0x50000',
    base: 0x4000,
    size: 311296,
    imageSize: 327680,
    note: 'The region GuzziDiag and 5am_util read and write. A full image is 320 KiB; the readable flash starts at 0x4000.',
  },
  '5am-image': {
    id: '5am-image',
    label: 'IAW 5AM full 320 KiB image',
    base: 0,
    size: 327680,
    imageSize: 327680,
    note: 'The whole image, including the 0x0–0x3FFF header area.',
  },
  'full-image': {
    id: 'full-image',
    label: 'Full image from address 0',
    base: 0,
    size: null,
    imageSize: null,
    note: 'No base offset: the first byte of the file is address 0.',
  },
  custom: {
    id: 'custom',
    label: 'Custom base and size',
    base: 0,
    size: null,
    imageSize: null,
    note: 'Set the base offset yourself.',
  },
};

/** Bytes a table occupies, from the shape the definition declares. */
function iawTableBytes(table) {
  const cells = Math.max(1, Number(table.rows) || 1) * Math.max(1, Number(table.cols) || 1);
  const bits = Number(table.size_bits) || 8;
  return Math.ceil(cells * bits / 8);
}

/**
 * Compare one definition against a file that starts at `base` in the image.
 * Returns the tables that fit, the ones that run past the end, and the address
 * range the definition needs.
 */
function iawFit(definition, fileLength, base = 0) {
  const length = Number(fileLength) || 0;
  if (!definition || !Array.isArray(definition.tables)) throw new Error('Choose a definition first.');
  const inside = [];
  const outside = [];
  let lowest = Infinity;
  let highest = -Infinity;
  definition.tables.forEach((table) => {
    if (table.address === null || table.address === undefined) return;
    const size = iawTableBytes(table);
    const start = table.address - base;
    const end = start + size;
    lowest = Math.min(lowest, start);
    highest = Math.max(highest, end);
    const entry = {
      title: table.title,
      address: table.address,
      size,
      start,
      end,
      units: table.units || '',
      rows: table.rows,
      cols: table.cols,
    };
    if (start >= 0 && end <= length) inside.push(entry);
    else outside.push({ ...entry, reason: start < 0 ? 'starts before the first byte of this file' : 'runs past the last byte' });
  });
  const total = inside.length + outside.length;
  return {
    inside,
    outside,
    total,
    coverage: total ? inside.length / total : 0,
    range: Number.isFinite(lowest) ? { start: lowest, end: highest } : null,
    fileLength: length,
    base,
    needed: Number.isFinite(highest) ? highest : null,
    fitsAll: total > 0 && outside.length === 0,
  };
}

/** Which bundled definitions belong to a brand, from the library index. */
function iawDefinitions(library, brand) {
  return (library?.xdfs || [])
    .filter((entry) => !brand || entry.brand === brand)
    .filter((entry) => Array.isArray(entry.tables) && entry.tables.length)
    .map((entry) => ({
      id: entry.filename,
      label: `${entry.brand_label ? `${entry.brand_label} · ` : ''}${entry.label || entry.title}`,
      filename: entry.filename,
      family: entry.family || '',
      regionSize: entry.region_size || null,
      tableCount: entry.tables.length,
      tables: entry.tables,
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

if (typeof window !== 'undefined') {
  window.gobIawLayout = { geometry: IAW_GEOMETRY, iawFit, iawDefinitions, iawTableBytes };
}

/* ---- panel wiring ------------------------------------------------------- */

if (typeof document !== 'undefined') {
  const el = (id) => document.getElementById(id);
  const setText = (id, text) => { const node = el(id); if (node) node.textContent = text; };
  const setHtml = (id, html) => { const node = el(id); if (node) node.innerHTML = html; };
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
  const hex = (value) => (value === null || value === undefined ? '' : `0x${Number(value).toString(16).toUpperCase()}`);
  const size = (bytes) => (bytes >= 1024 ? `${(bytes / 1024).toFixed(bytes >= 10240 ? 0 : 1)} KiB` : `${bytes} B`);

  const state = { library: null, loading: null };

  /* The index is the same file in both builds: the desktop server answers
   * /api/maps/library from guzzionboard/maps.py, and the hosted demo either
   * answers through the demo router or serves web/xdf-library.json directly.
   * Falling back keeps this panel usable when the page is opened statically. */
  async function fetchLibrary() {
    if (typeof api === 'function') return api('/api/maps/library');
    const response = await fetch('/api/maps/library');
    if (response.ok) return response.json();
    throw new Error(`HTTP ${response.status}`);
  }

  async function loadLibrary() {
    if (state.library) return state.library;
    if (!state.loading) {
      state.loading = (async () => {
        try {
          state.library = await fetchLibrary();
        } catch (apiError) {
          try {
            const response = await fetch('xdf-library.json', { cache: 'force-cache' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            state.library = await response.json();
            state.library.source = 'web/xdf-library.json (static page)';
          } catch (fileError) {
            throw new Error(`${apiError.message}; ${fileError.message}`);
          }
        }
        return state.library;
      })().catch((error) => {
        state.loading = null;
        throw error;
      });
    }
    return state.loading;
  }

  function wire(prefix, brand) {
    const select = el(`${prefix}Definition`);
    const baseInput = el(`${prefix}Base`);
    const preset = el(`${prefix}Preset`);
    const fileInput = el(`${prefix}File`);
    const runBtn = el(`${prefix}Run`);
    if (!runBtn || !select) return;

    const fill = () => loadLibrary().then((library) => {
      const list = iawDefinitions(library, brand);
      select.innerHTML = list.length
        ? list.map((entry) => `<option value="${escapeHtml(entry.id)}">${escapeHtml(entry.label)}`
          + ` · ${entry.tableCount} tables${entry.regionSize ? ` · ${size(entry.regionSize)}` : ''}</option>`).join('')
        : '<option value="">no definitions for this brand in the library</option>';
      setText(`${prefix}Meta`, `${list.length} definition(s) for this brand`);
    }).catch((error) => {
      setText(`${prefix}Meta`, `Library unavailable: ${error.message}`);
    });

    if (preset) {
      preset.addEventListener('change', () => {
        const geometry = IAW_GEOMETRY[preset.value];
        if (geometry && baseInput) baseInput.value = `0x${geometry.base.toString(16).toUpperCase()}`;
      });
    }
    select.addEventListener('focus', () => { if (!state.library) fill(); }, { once: true });
    fill();

    runBtn.onclick = async () => {
      setHtml(`${prefix}Out`, '');
      try {
        const library = await loadLibrary();
        const list = iawDefinitions(library, brand);
        const definition = list.find((entry) => entry.id === select.value);
        if (!definition) throw new Error('Choose a definition.');
        const file = fileInput?.files?.[0];
        let fileLength = 0;
        if (file) {
          if (file.size > 4 * 1024 * 1024) throw new Error('Images above 4 MiB are not inspected here.');
          fileLength = file.size;
        } else {
          const manual = String(el(`${prefix}Size`)?.value || '').trim();
          if (!manual) throw new Error('Choose an image file, or type the size of the region you have.');
          fileLength = /^0x/i.test(manual) ? parseInt(manual, 16) : parseInt(manual, 10);
          if (!Number.isInteger(fileLength) || fileLength <= 0) throw new Error('Size must be a byte count.');
        }
        const baseText = String(baseInput?.value || '0').trim();
        const base = /^0x/i.test(baseText) ? parseInt(baseText, 16) : parseInt(baseText, 10);
        if (!Number.isInteger(base) || base < 0) throw new Error('Base offset must be a byte address.');

        const fit = iawFit(definition, fileLength, base);
        const geometry = IAW_GEOMETRY[preset?.value] || null;
        const rows = fit.inside.slice(0, 30).map((table) => `<tr><td><b>${escapeHtml(table.title)}</b></td>`
          + `<td><code>${hex(table.address)}</code></td><td>${table.rows}×${table.cols}</td>`
          + `<td>${size(table.size)}</td><td><code>${hex(table.start)}–${hex(table.end)}</code></td>`
          + `<td>${escapeHtml(table.units)}</td></tr>`).join('');
        const missing = fit.outside.slice(0, 15).map((table) => `<tr><td><b>${escapeHtml(table.title)}</b></td>`
          + `<td><code>${hex(table.address)}</code></td><td>${size(table.size)}</td>`
          + `<td>${escapeHtml(table.reason)}</td></tr>`).join('');

        setHtml(`${prefix}Out`, `<div class="kv">`
          + `<div><span>File</span><b>${file ? escapeHtml(file.name) : 'typed size'} · ${size(fileLength)}</b></div>`
          + `<div><span>File starts at</span><b>${hex(base)}</b></div>`
          + `<div><span>Covers image addresses</span><b>${hex(base)}–${hex(base + fileLength - 1)}</b></div>`
          + `<div><span>Definition</span><b>${escapeHtml(definition.filename)}</b></div>`
          + `<div><span>Tables inside this file</span><b>${fit.inside.length} of ${fit.total}</b></div>`
          + `<div><span>Highest address used</span><b>${fit.needed === null ? '—' : hex(base + fit.needed)}</b></div>`
          + (geometry ? `<div class="full"><span>Geometry preset</span><b>${escapeHtml(geometry.label)}</b> — ${escapeHtml(geometry.note)}</div>` : '')
          + `</div>`
          + `<p class="${fit.fitsAll ? 'tip' : 'tip warn'}"><b>${fit.fitsAll
            ? 'Every table in this definition falls inside the file.'
            : `${fit.outside.length} table(s) fall outside this file.`}</b> `
          + (fit.fitsAll
            ? 'That means the file is big enough for the definition, not that the definition belongs to this ECU: '
              + 'a definition from another family can describe plausible tables at the wrong addresses.'
            : 'Either the file is a partial read, or the base offset is wrong, or the definition describes a '
              + 'different image layout. Check the region size and the base before trusting any value.')
          + '</p>'
          + (rows ? `<h3>Tables inside (${fit.inside.length})</h3><div class="table-wrap"><table class="data">`
            + '<thead><tr><th>Table</th><th>Address</th><th>Shape</th><th>Bytes</th><th>File offsets</th>'
            + `<th>Units</th></tr></thead><tbody>${rows}</tbody></table></div>` : '')
          + (fit.inside.length > 30 ? `<p class="muted small">Showing the first 30 of ${fit.inside.length}.</p>` : '')
          + (missing ? `<h3>Outside this file (${fit.outside.length})</h3><div class="table-wrap"><table class="data">`
            + '<thead><tr><th>Table</th><th>Address</th><th>Bytes</th><th>Why</th></tr></thead>'
            + `<tbody>${missing}</tbody></table></div>` : ''));
        setText(`${prefix}Meta`, `${definition.tableCount} table(s) · ${fit.inside.length} inside`
          + ` · covers ${(fit.coverage * 100).toFixed(0)} % of the definition`);
      } catch (error) {
        setText(`${prefix}Meta`, `Not inspected: ${error.message}`);
      }
    };
  }

  wire('iawGuzzi', 'moto_guzzi');
  wire('iawAprilia', 'aprilia');
}
