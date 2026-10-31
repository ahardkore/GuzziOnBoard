/* Synthetic-tested, read-only rusEFI aftermarket controller serial research. */
'use strict';
{
  const port = document.getElementById('rusefiPort');
  const baud = document.getElementById('rusefiBaud');
  const signature = document.getElementById('rusefiSignature');
  const ini = document.getElementById('rusefiIni');
  const iniStatus = document.getElementById('rusefiIniStatus');
  const lookup = document.getElementById('rusefiLookup');
  const lookupNote = document.getElementById('rusefiLookupNote');
  const page = document.getElementById('rusefiPage');
  const offset = document.getElementById('rusefiOffset');
  const length = document.getElementById('rusefiLength');
  const confirm = document.getElementById('rusefiConfirm');
  const output = document.getElementById('rusefiOut');
  const identify = document.getElementById('rusefiIdentify');
  const read = document.getElementById('rusefiRead');
  const outputs = document.getElementById('rusefiOutputs');
  let generation = 0;
  for (const input of [port, baud, signature, page, offset, length, confirm]) {
    const invalidate = () => {
      generation++;
      if (input !== confirm) confirm.checked = false;
      output.textContent = 'Selection changed; confirm before continuing.';
      if (input === port || input === baud) {
        lookup.hidden = true;
        lookup.removeAttribute('href');
        lookupNote.textContent = 'Identify a controller to generate a lookup link. Opening it sends the signature in the URL to rusEFI.';
      }
    };
    input.addEventListener('change', invalidate);
    if (input !== confirm) input.addEventListener('input', invalidate);
  }
  ini.addEventListener('change', async () => {
    const token = ++generation;
    confirm.checked = false;
    signature.value = '';
    output.textContent = 'INI selection changed; confirm before continuing.';
    iniStatus.textContent = 'Reading INI locally…';
    try {
      const file = ini.files?.[0];
      if (!file) { iniStatus.textContent = 'No INI selected.'; return; }
      if (file.size > RusefiIni.MAX_BYTES) throw new Error('INI must be no larger than 2 MiB.');
      const text = await file.text();
      if (generation !== token) return;
      signature.value = RusefiIni.signature(text);
      iniStatus.textContent = 'INI signature loaded locally. Check it against the identified controller; this does not verify the INI contents.';
    } catch (error) {
      if (generation === token) iniStatus.textContent = `INI not loaded: ${error.message}`;
    }
  });
  async function perform(action) {
    const token = ++generation;
    if (isHostedDemo()) { output.textContent = 'The hosted demo cannot access serial hardware.'; return; }
    if (!confirm.checked) { output.textContent = 'Confirm the controller and wiring first.'; return; }
    if (action !== 'identify' && (!signature.value || (action === 'read' && !page.value) || !offset.value || !length.value)) {
      output.textContent = 'Enter the exact INI signature and complete the range.'; return;
    }
    if (action === 'identify') {
      lookup.hidden = true;
      lookup.removeAttribute('href');
      lookupNote.textContent = 'Identifying controller; no lookup link available yet.';
    }
    identify.disabled = read.disabled = outputs.disabled = true;
    output.textContent = 'Communicating with the selected local serial device…';
    try {
      const body = { action, port: port.value, baud: Number(baud.value), confirm: true };
      if (action !== 'identify') Object.assign(body, { signature: signature.value, page: Number(page.value), offset: Number(offset.value), length: Number(length.value) });
      const result = await api('/api/tools/rusefi-read', { method: 'POST', body });
      if (token !== generation) return;
      if (action === 'identify') {
        const url = RusefiIni.lookup(result.signature);
        lookup.hidden = !url;
        if (url) {
          lookup.href = url;
          lookupNote.textContent = 'Opening this link sends the signature in the URL to rusEFI. Availability is not guaranteed.';
        } else {
          lookup.removeAttribute('href');
          lookupNote.textContent = 'Signature format is not supported by this link generator; use the rusEFI lookup guide.';
        }
      }
      output.textContent = `Controller signature: ${result.signature}\n` + (action === 'read'
        ? `Page ${result.page}, offset ${result.offset}, ${result.length} bytes:\n${result.data_hex}\n\nRaw working-page data, not a verified backup. Locked controllers may return zeros.`
        : action === 'outputs' ? `Live output offset ${result.offset}, ${result.length} bytes:\n${result.data_hex}\n\nRaw snapshot; use the matching INI to interpret it.`
        : 'Compare this signature with your matching INI before requesting page or output data.') +
        '\nSynthetic-tested only; not stock Harley ECU access. No write or burn command sent.';
    } catch (error) { if (token === generation) output.textContent = `Communication failed: ${error.message}`; }
    finally { identify.disabled = read.disabled = outputs.disabled = false; }
  }
  identify.onclick = () => perform('identify');
  read.onclick = () => perform('read');
  outputs.onclick = () => perform('outputs');
}
