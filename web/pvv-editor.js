/* PVV XML research editing; source layout described by MIT-licensed DynoAI. */
'use strict';
{
  const file = document.getElementById('pvvFile'), select = document.getElementById('pvvSelect');
  const details = document.getElementById('pvvDetails'), grid = document.getElementById('pvvGrid');
  const changes = document.getElementById('pvvChanges'), confirm = document.getElementById('pvvConfirm');
  const revert = document.getElementById('pvvRevert'), exportButton = document.getElementById('pvvExport');
  let doc = null, tables = [], originals = new Map(), dirty = new Map(), invalid = false, generation = 0, current = '';
  const direct = (node, tag) => Array.from(node.children).filter((child) => child.tagName === tag);
  const numeric = (v) => /^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$/.test(v) && Number.isFinite(Number(v));
  function reset(message) {
    ++generation; doc = null; tables = []; originals = new Map(); dirty = new Map(); invalid = false; current = '';
    select.replaceChildren(new Option('Open a PVV file first', '')); select.disabled = true;
    grid.replaceChildren(); details.textContent = message; confirm.checked = false; update();
  }
  function update() {
    revert.disabled = !dirty.size && !invalid;
    exportButton.disabled = !doc || !dirty.size || invalid || !confirm.checked;
    changes.textContent = invalid ? 'Invalid numeric cell; fix it before changing tables or exporting.' :
      dirty.size ? `${dirty.size} staged cell change(s). Review before exporting.\n` + Array.from(dirty.values()).map((x) => `${x.table} [row ${x.row}, column ${x.col}]: ${x.before} → ${x.after}`).join('\n') : 'No staged changes.';
  }
  function cell(tag, text) { const node = document.createElement(tag); node.textContent = text; return node; }
  function draw(index) {
    grid.replaceChildren(); const item = tables[index];
    if (!item) { details.textContent = 'Choose an editable table.'; return; }
    const {node, cols, rows} = item;
    details.textContent = `${node.getAttribute('name') || '(unnamed)'} · values ${node.getAttribute('units') || '(unspecified units)'} · columns ${item.colUnits || '(units unspecified)'} · rows ${item.rowUnits || '(units unspecified)'} · ${rows.length} × ${cols.length}`;
    const table = document.createElement('table'), head = document.createElement('thead'), hrow = document.createElement('tr');
    hrow.append(cell('th', item.rowUnits || 'Row'));
    for (const col of cols) hrow.append(cell('th', col.getAttribute('label') || ''));
    head.append(hrow); table.append(head); const body = document.createElement('tbody');
    rows.forEach((row, r) => {
      const tr = document.createElement('tr'); tr.append(cell('th', row.node.getAttribute('label') || ''));
      row.cells.forEach((node, c) => {
        const td = document.createElement('td'), input = document.createElement('input');
        input.type = 'text'; input.maxLength = 64; input.inputMode = 'decimal'; input.value = node.getAttribute('value'); input.size = 8;
        input.setAttribute('aria-label', `Row ${r + 1} column ${c + 1}`);
        input.addEventListener('input', () => {
          confirm.checked = false; const value = input.value.trim();
          input.setCustomValidity(!numeric(value) ? 'Enter a finite number.' : !dirty.has(node) && value !== originals.get(node) && dirty.size >= 1000 ? 'At most 1,000 staged changes.' : '');
          invalid = Array.from(grid.querySelectorAll('input')).some((x) => !x.checkValidity());
          if (input.checkValidity()) {
            node.setAttribute('value', value); const before = originals.get(node);
            if (value === before) dirty.delete(node);
            else dirty.set(node, {table: node.closest('Item').getAttribute('name') || '(unnamed)', row: r + 1, col: c + 1, before, after:value});
          }
          update();
        });
        td.append(input); tr.append(td);
      });
      body.append(tr);
    });
    table.append(body); grid.append(table);
  }
  file.addEventListener('change', async () => {
    reset('Loading local PVV…'); const token = generation, selected = file.files[0];
    if (!selected) { details.textContent = 'No file loaded.'; return; }
    try {
      if (selected.size > 8 * 1024 * 1024) throw new Error('PVV exceeds 8 MiB.');
      const text = await selected.text(); if (token !== generation) return;
      if (/<!\s*(DOCTYPE|ENTITY)\b/i.test(text)) throw new Error('DTD and entity declarations are not supported.');
      const candidate = new DOMParser().parseFromString(text, 'application/xml');
      if (candidate.querySelector('parsererror') || candidate.documentElement.tagName !== 'PVV') throw new Error('Expected a valid PVV XML document.');
      const items = direct(candidate.documentElement, 'Item');
      if (!items.length || items.length > 4096) throw new Error('Expected 1–4096 PVV items.');
      const next = [], firstValues = new Map(); let skipped = 0, cellTotal = 0;
      for (const node of items) {
        const colParent = direct(node, 'Columns'), rowParent = direct(node, 'Rows');
        if (colParent.length !== 1 || rowParent.length !== 1) { skipped++; continue; }
        const cols = direct(colParent[0], 'Col'), rowNodes = direct(rowParent[0], 'Row');
        if (!cols.length || !rowNodes.length || cols.length > 128 || rowNodes.length > 128 || cols.length * rowNodes.length > 4096) { skipped++; continue; }
        const rows = rowNodes.map((row) => ({node:row, cells:direct(row, 'Cell')}));
        if (rows.some((r) => r.cells.length !== cols.length || r.cells.some((c) => !numeric(c.getAttribute('value') || '')))) { skipped++; continue; }
        cellTotal += cols.length * rowNodes.length;
        if (cellTotal > 100000) throw new Error('PVV has more than 100,000 editable cells.');
        for (const row of rows) for (const c of row.cells) firstValues.set(c, c.getAttribute('value'));
        next.push({node, cols, rows, rowUnits:rowParent[0].getAttribute('units'), colUnits:colParent[0].getAttribute('units')});
      }
      if (!next.length) throw new Error('No supported numeric tables found.');
      doc = candidate; tables = next; originals = firstValues;
      select.replaceChildren(...tables.map((item, i) => new Option(`${item.node.getAttribute('name') || '(unnamed)'} (${item.rows.length} × ${item.cols.length})`, String(i))));
      select.disabled = false; current = '0'; select.value = current; draw(0);
      changes.textContent = `No staged changes. ${next.length} editable item(s); ${skipped} unsupported item(s) preserved without editing.`;
    } catch (error) { if (token === generation) reset(`PVV not loaded: ${error.message}`); }
  });
  select.addEventListener('change', () => {
    if (invalid) { select.value = current; update(); return; }
    current = select.value; draw(Number(current));
  });
  revert.onclick = () => { for (const [node, value] of originals) node.setAttribute('value', value); dirty.clear(); invalid = false; confirm.checked = false; draw(Number(current)); update(); };
  confirm.addEventListener('change', update);
  exportButton.onclick = () => { if (!doc || invalid || !dirty.size || !confirm.checked) return; download(`guzzionboard-pvv-research-${Date.now()}.pvv`, new XMLSerializer().serializeToString(doc), 'application/xml'); };
  document.getElementById('pvvClear').onclick = () => { file.value = ''; reset('No file loaded.'); };
}
