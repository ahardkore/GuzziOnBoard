/* User-supplied, in-memory Harley DTC reference. No third-party list bundled. */
'use strict';
{
  const file = document.getElementById('harleyCodeFile');
  const query = document.getElementById('harleyCodeQuery');
  const out = document.getElementById('harleyCodeOut');
  const clear = document.getElementById('harleyCodeClear');
  let codes = new Map(), generation = 0, total = 0;
  const normalize = (value) => String(value || '').trim().toUpperCase();
  const lookup = (code) => codes.get(normalize(code)) || [];
  window.harleyCodeReference = {lookup};
  function show() {
    if (!total) { out.textContent = 'No reference loaded.'; return; }
    const code = normalize(query.value), found = lookup(code);
    out.textContent = `${total} reference entries loaded locally.\n` +
      (!code ? 'Enter a code to look it up.' : found.length
        ? `${code}:\n${found.map((x) => '• ' + x).join('\n')}\nReference descriptions only; confirm fitment and diagnosis.`
        : `${code}: no matching reference entry.`);
  }
  file.addEventListener('change', async () => {
    const token = ++generation; codes = new Map(); total = 0;
    document.querySelectorAll('.local-harley-reference').forEach((node) => node.remove());
    const selected = file.files[0];
    if (!selected) { show(); return; }
    try {
      if (selected.size > 1024 * 1024) throw new Error('JSON file exceeds 1 MiB.');
      const parsed = JSON.parse(await selected.text());
      if (token !== generation) return;
      if (!parsed || !Array.isArray(parsed.codes) || parsed.codes.length > 5000) throw new Error('Expected a codes array with at most 5,000 entries.');
      const next = new Map();
      for (const item of parsed.codes) {
        const code = normalize(item?.code);
        if (!/^[PBCU][0-9A-F]{3,5}$/.test(code) || typeof item?.description !== 'string' || !item.description.trim() || item.description.length > 512) throw new Error('Invalid reference entry; no entries loaded.');
        const values = next.get(code) || [];
        if (!values.includes(item.description.trim())) values.push(item.description.trim());
        next.set(code, values);
      }
      codes = next; total = parsed.codes.length; show();
    } catch (error) { if (token === generation) out.textContent = `Reference not loaded: ${error.message}`; }
  });
  query.addEventListener('input', show);
  clear.onclick = () => { ++generation; codes = new Map(); total = 0; document.querySelectorAll('.local-harley-reference').forEach((node) => node.remove()); file.value = ''; query.value = ''; show(); };
}
