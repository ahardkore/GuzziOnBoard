/* Synthetic-tested, restricted Buell DDFI serial research. */
'use strict';
{
  const port = document.getElementById('buellPort');
  const mode = document.getElementById('buellMode');
  const version = document.getElementById('buellVersion');
  const page = document.getElementById('buellPage');
  const offset = document.getElementById('buellOffset');
  const length = document.getElementById('buellLength');
  const compare = document.getElementById('buellCompare');
  const confirm = document.getElementById('buellConfirm');
  const output = document.getElementById('buellOut');
  const identify = document.getElementById('buellIdentify');
  const runtime = document.getElementById('buellRuntime');
  const read = document.getElementById('buellRead');
  let generation = 0;
  for (const field of [port, mode, version, page, offset, length, compare, confirm]) {
    const invalidate = () => {
      generation++;
      if (field !== confirm) confirm.checked = false;
      if (field === port || field === mode) version.value = '';
      output.textContent = 'Selection changed; reconfirm before continuing.';
    };
    field.addEventListener('change', invalidate);
    if (field !== confirm) field.addEventListener('input', invalidate);
  }
  async function perform(action) {
    const token = ++generation;
    if (isHostedDemo()) { output.textContent = 'The hosted demo cannot access serial hardware.'; return; }
    if (!confirm.checked) { output.textContent = 'Confirm the ECM, adapter and wiring first.'; return; }
    if (action !== 'identify' && !version.value) { output.textContent = 'Identify the ECM first.'; return; }
    if (action === 'read' && (!page.value || !offset.value || !length.value)) { output.textContent = 'Enter a complete page range.'; return; }
    identify.disabled = runtime.disabled = read.disabled = true;
    output.textContent = 'Communicating with the selected local serial device…';
    try {
      const body = {port: port.value, mode: mode.value, action, confirm: true};
      if (action !== 'identify') body.version = version.value;
      if (action === 'read') Object.assign(body, {page: Number(page.value), offset: Number(offset.value), length: Number(length.value), compare_repeat: compare.checked});
      const result = await api('/api/tools/buell-ddfi', {method: 'POST', body});
      if (token !== generation) return;
      if (action === 'identify') {
        version.value = result.version;
        confirm.checked = false;
      }
      output.textContent = `ECM version: ${result.version}\n` + (action === 'identify'
        ? 'Check version and wiring, then reconfirm to read.'
        : action === 'runtime' ? `Runtime data (${result.length} bytes):\n${result.data_hex}\n` + (result.bueia_candidates ? `BUEIA ADX candidates: ${JSON.stringify(result.bueia_candidates)}\nSynthetic-tested only; do not use these values for riding or safety decisions.` : 'Raw payload; layout varies by ECM.')
        : `Page ${result.page}, offset ${result.offset}, ${result.length} bytes:\n${result.data_hex}\nPartial EEPROM research data, not a complete backup. ${result.repeated_match ? 'Two range reads matched; this does not prove reply-address association or ECU identity.' : 'Read once; no repeat comparison.'}`) +
        '\nSynthetic-tested only; no write, clear, actuator or reset command sent.';
    } catch (error) { if (token === generation) output.textContent = `Buell communication failed: ${error.message}`; }
    finally { identify.disabled = runtime.disabled = read.disabled = false; }
  }
  identify.onclick = () => perform('identify');
  runtime.onclick = () => perform('runtime');
  read.onclick = () => perform('read');
}
