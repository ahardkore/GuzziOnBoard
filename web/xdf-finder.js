/* XDF library table finder.
 *
 * Searches the table-level index of every bundled definition (title, category,
 * units, address, definition label) without loading an image. The index comes
 * from /api/maps/library — the live parse in the desktop build, the generated
 * web/xdf-library.json in the hosted demo — so both builds search the same
 * 121 definitions and the same 4,280 tables.
 */
'use strict';

function xdfFinderMatchAddress(table, query) {
  if (table.address === null || table.address === undefined) return false;
  const text = String(query).trim();
  const parsed = /^0x/i.test(text) ? parseInt(text, 16) : (/^[0-9a-f]+$/i.test(text) && /[a-f]/i.test(text) ? parseInt(text, 16) : parseInt(text, 10));
  if (Number.isFinite(parsed) && parsed === table.address) return true;
  return `0x${table.address.toString(16)}`.includes(text.toLowerCase());
}

function xdfFinderSearch(library, options = {}) {
  const query = String(options.query || '').trim().toLowerCase();
  const brand = String(options.brand || '');
  const field = options.field || 'all';
  const limit = Number(options.limit) || 400;
  const definitions = [];
  let tableCount = 0;
  let totalTables = 0;

  (library?.xdfs || []).forEach((definition) => {
    totalTables += (definition.tables || []).length;
    if (brand && definition.brand !== brand) return;
    const defText = `${definition.title} ${definition.label} ${definition.filename} ${definition.family} ${definition.brand_label}`.toLowerCase();
    const matched = [];
    (definition.tables || []).forEach((table) => {
      let hit = !query;
      if (query) {
        if (field === 'address') hit = xdfFinderMatchAddress(table, query);
        else if (field === 'title') hit = table.title.toLowerCase().includes(query);
        else if (field === 'units') hit = String(table.units || '').toLowerCase().includes(query);
        else if (field === 'category') hit = String(table.category || '').toLowerCase().includes(query);
        else if (field === 'definition') hit = defText.includes(query);
        else {
          hit = table.title.toLowerCase().includes(query)
            || String(table.units || '').toLowerCase().includes(query)
            || String(table.category || '').toLowerCase().includes(query)
            || String(table.equation || '').toLowerCase().includes(query)
            || xdfFinderMatchAddress(table, query)
            || defText.includes(query);
        }
      }
      if (!hit) return;
      tableCount += 1;
      if (matched.length < limit) matched.push(table);
    });
    if (matched.length) definitions.push({ ...definition, matched });
  });

  return {
    definitions,
    tableCount,
    definitionCount: definitions.length,
    totalDefinitions: (library?.xdfs || []).length,
    totalTables,
    truncated: tableCount > limit,
    query,
    brand,
    field,
  };
}

function xdfFinderBrands(library) {
  const seen = new Map();
  (library?.xdfs || []).forEach((definition) => {
    const id = definition.brand || '';
    if (!id) return;
    if (!seen.has(id)) seen.set(id, { id, label: definition.brand_label || id, count: 0 });
    seen.get(id).count += 1;
  });
  return Array.from(seen.values()).sort((a, b) => a.label.localeCompare(b.label));
}

if (typeof window !== 'undefined') {
  window.gobXdfFinder = { search: xdfFinderSearch, brands: xdfFinderBrands };
}

/* ---- panel wiring ------------------------------------------------------- */

if (typeof document !== 'undefined') {
  const el = (id) => document.getElementById(id);
  const setText = (id, text) => { const node = el(id); if (node) node.textContent = text; };
  const setHtml = (id, html) => { const node = el(id); if (node) node.innerHTML = html; };
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
  const hex = (address) => (address === null || address === undefined ? '' : `0x${address.toString(16).toUpperCase()}`);

  const state = { library: null, loading: null, brandsDone: false };

  async function loadLibrary() {
    if (state.library) return state.library;
    if (!state.loading) {
      state.loading = (async () => {
        const payload = typeof api === 'function'
          ? await api('/api/maps/library')
          : await (await fetch('/api/maps/library')).json();
        state.library = payload;
        return payload;
      })().catch((error) => {
        state.loading = null;
        throw error;
      });
    }
    return state.loading;
  }

  function fillBrands(library) {
    if (state.brandsDone) return;
    const select = el('xdfFindBrand');
    if (!select) return;
    xdfFinderBrands(library).forEach((brand) => {
      const option = document.createElement('option');
      option.value = brand.id;
      option.textContent = `${brand.label} (${brand.count})`;
      select.appendChild(option);
    });
    state.brandsDone = true;
  }

  function render(result) {
    const groups = result.definitions.map((definition) => {
      const rows = definition.matched.map((table) => `<tr>`
        + `<td><b>${escapeHtml(table.title)}</b></td>`
        + `<td><code>${hex(table.address)}</code></td>`
        + `<td>${table.rows}×${table.cols}</td>`
        + `<td>${table.size_bits} bit${table.size_bits === 1 ? '' : 's'}${table.is_float ? ' float' : (table.signed ? ' signed' : '')}</td>`
        + `<td>${escapeHtml(table.units || '')}</td>`
        + `<td>${escapeHtml(table.category || '')}</td>`
        + `<td><button class="btn" data-xdf-ref="${escapeHtml(definition.filename)}|${escapeHtml(table.title)}|${hex(table.address)}">Copy</button></td>`
        + '</tr>').join('');
      return `<section class="xdf-find-group" data-xdf-definition="${escapeHtml(definition.filename)}">`
        + `<h3>${escapeHtml(definition.brand_label || definition.brand)} · ${escapeHtml(definition.label || definition.title)} `
        + `<span class="muted small">(${definition.matched.length} of ${(definition.tables || []).length} tables · ${escapeHtml(definition.filename)})</span></h3>`
        + '<div class="table-wrap"><table class="data"><thead><tr><th>Table</th><th>Address</th><th>Shape</th>'
        + '<th>Cell</th><th>Units</th><th>Category</th><th></th></tr></thead><tbody>'
        + rows + '</tbody></table></div></section>';
    }).join('');
    setHtml('xdfFindOut', groups || '<p class="tip"><b>Nothing matched.</b> Try a shorter term, a wider field, or '
      + 'switch the brand back to all. Address search accepts 0x1A2C, 1A2C or a decimal offset.</p>');
  }

  async function run() {
    setHtml('xdfFindOut', '');
    setText('xdfFindMeta', 'Reading the library index…');
    try {
      const library = await loadLibrary();
      fillBrands(library);
      const result = xdfFinderSearch(library, {
        query: el('xdfFindQuery').value,
        brand: el('xdfFindBrand').value,
        field: el('xdfFindField').value,
      });
      render(result);
      setText('xdfFindMeta', `${result.tableCount} table(s) in ${result.definitionCount} of ${result.totalDefinitions} definition(s)`
        + ` · library holds ${result.totalTables.toLocaleString()} tables`
        + (result.truncated ? ' · showing the first matches per definition' : ''));
      el('xdfFindClear').disabled = false;
    } catch (error) {
      setText('xdfFindMeta', `Library unavailable: ${error.message}`);
      setHtml('xdfFindOut', '<p class="tip warn">The index could not be read. In the installed app it is parsed from '
        + '<code>guzzionboard/xdfs</code>; in the hosted demo it is <code>web/xdf-library.json</code>.</p>');
    }
  }

  const searchBtn = el('xdfFindBtn');
  if (searchBtn) searchBtn.onclick = run;
  const queryInput = el('xdfFindQuery');
  if (queryInput) {
    queryInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') run();
    });
  }
  const brandSelect = el('xdfFindBrand');
  if (brandSelect) {
    brandSelect.addEventListener('change', run);
    // The list of brands comes from the index, so fill it the first time the
    // operator reaches for it rather than downloading the index on page load.
    brandSelect.addEventListener('focus', () => {
      loadLibrary().then(fillBrands).catch(() => {});
    }, { once: true });
  }

  const clear = el('xdfFindClear');
  if (clear) {
    clear.onclick = () => {
      if (queryInput) queryInput.value = '';
      if (brandSelect) brandSelect.value = '';
      const field = el('xdfFindField');
      if (field) field.value = 'all';
      setHtml('xdfFindOut', '');
      setText('xdfFindMeta', '');
      clear.disabled = true;
    };
  }

  document.addEventListener('click', async (event) => {
    const copy = event.target.closest?.('[data-xdf-ref]');
    if (!copy) return;
    const [filename, title, address] = copy.dataset.xdfRef.split('|');
    const reference = `${filename} · ${title}${address ? ` @ ${address}` : ''}`;
    try {
      await navigator.clipboard.writeText(reference);
      copy.textContent = 'Copied';
    } catch (_) {
      copy.textContent = reference;
    }
    setTimeout(() => { copy.textContent = 'Copy'; }, 1800);
    if (typeof window.guzziOpenWorkspaceTarget === 'function') {
      window.guzziOpenWorkspaceTarget({ view: 'firmware', selector: '#xdfSelect' });
    }
  });
}
