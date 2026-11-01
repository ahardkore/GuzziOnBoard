/* Synthetic-tested rusEFI aftermarket serial research and reviewed calibration writer. */
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
  const tuneRead = document.getElementById('rusefiTuneRead');
  const tuneOriginal = document.getElementById('rusefiTuneOriginal');
  const tuneEdited = document.getElementById('rusefiTuneEdited');
  const tuneConfirm = document.getElementById('rusefiTuneConfirm');
  const tunePrepare = document.getElementById('rusefiTunePrepare');
  const tuneWrite = document.getElementById('rusefiTuneWrite');
  const tuneOut = document.getElementById('rusefiTuneOut');
  const openMap = document.getElementById('rusefiOpenMap');
  const mapStatus = document.getElementById('rusefiMapStatus');
  let iniText = null, evidence = null, plan = null, busy = false;
  function clearPlan() { plan = null; tuneWrite.disabled = true; }
  function clearEvidence() {
    evidence = null; clearPlan(); tuneOriginal.value = ''; tunePrepare.disabled = true;
    openMap.disabled = true;
    tuneOut.textContent = 'Selection changed; read the settings page again.';
  }
  window.addEventListener('beforeunload', event => {
    if (busy) { event.preventDefault(); event.returnValue = ''; }
  });
  let generation = 0;
  for (const input of [port, baud, signature, page, offset, length, confirm]) {
    const invalidate = () => {
      generation++;
      clearEvidence();
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
    clearEvidence(); iniText = null;
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
      iniText = text;
      iniStatus.textContent = 'INI signature loaded locally. Check it against the identified controller; this does not verify the INI contents.';
    } catch (error) {
      if (generation === token) iniStatus.textContent = `INI not loaded: ${error.message}`;
    }
  });
  async function perform(action) {
    clearEvidence();
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
  for (const input of [tuneEdited, tuneConfirm]) {
    const invalidate = () => { generation++; clearPlan(); tuneOut.textContent = 'Review a new calibration plan.'; };
    input.addEventListener('change', invalidate);
    if (input !== tuneConfirm) input.addEventListener('input', invalidate);
  }
  function disableOperations(disabled) {
    identify.disabled = read.disabled = outputs.disabled = tuneRead.disabled = disabled;
    openMap.disabled = disabled || !evidence;
  }
  tuneRead.onclick = async () => {
    if (isHostedDemo()) { tuneOut.textContent = 'The hosted demo cannot access serial hardware.'; return; }
    if (!confirm.checked || !iniText || signature.value !== RusefiIni.signature(iniText)) {
      tuneOut.textContent = 'Select the matching INI and confirm controller and wiring first.'; return;
    }
    clearEvidence(); const token = ++generation;
    busy = true; disableOperations(true);
    tuneOut.textContent = 'Reading the entire INI-described settings page once; keep power connected…';
    try {
      const result = await api('/api/tools/rusefi-read', {method:'POST', body:{
        action:'read-calibration', confirm:true, port:port.value, baud:Number(baud.value), ini:iniText,
      }});
      if (token !== generation) return;
      if (!result.read_token) { tuneOut.textContent = result.write_review_unavailable || 'No write evidence was created.'; return; }
      evidence = result; tuneOriginal.value = result.original_path; tunePrepare.disabled = false;
      document.getElementById('rusefiTunePanel').open = true;
      tuneOut.textContent = `Saved ${result.length} bytes: ${result.original_path}\nSHA-256 ${result.sha256}\nNot independently verified. Open in Maps with your matching XDF or edit a separate copy with a compatible editor.`;
      mapStatus.textContent = 'Saved page ready. Select a matching user XDF; the INI signature does not confirm fitment.';
    } catch (error) { if (token === generation) tuneOut.textContent = `Calibration read failed: ${error.message}`; }
    finally { busy = false; disableOperations(false); }
  };
  openMap.onclick = async () => {
    const selectedRead = evidence;
    if (!selectedRead || !confirm.checked || busy) return;
    const isCurrent = () => evidence === selectedRead && confirm.checked && !busy;
    const attach = (path, oldValue) => {
      if (!isCurrent() || tuneEdited.value !== oldValue) return false;
      generation++; tuneEdited.value = path; clearPlan(); tuneConfirm.checked = false;
      tuneOut.textContent = `Edited copy ready: ${path}\nConfirm risks and review the differences; no write or burn has been sent.`;
      return true;
    };
    openMap.disabled = true;
    try { await openRusefiResearchMap(selectedRead, isCurrent, () => tuneEdited.value, attach); }
    catch (error) { if (isCurrent()) mapStatus.textContent = `Map not opened: ${error.message}`; }
    finally { openMap.disabled = busy || !evidence; }
  };
  tunePrepare.onclick = async () => {
    if (!evidence || !confirm.checked || !tuneConfirm.checked || isHostedDemo()) {
      tuneOut.textContent = 'Read the settings page and confirm all tuning risks first.'; return;
    }
    const token = ++generation; clearPlan(); tunePrepare.disabled = true;
    try {
      const result = await api('/api/tools/rusefi-read', {method:'POST', body:{
        action:'prepare-calibration', confirm:true, confirm_tuning:true, read_token:evidence.read_token, edited_path:tuneEdited.value.trim(),
      }});
      if (token !== generation) return;
      plan = result; tuneWrite.disabled = false;
      tuneOut.textContent = `Signature ${result.signature}\n${result.changed_bytes} changed bytes; original SHA-256 ${result.original_sha256}\nEdited SHA-256 ${result.target_sha256}\nINI SHA-256 ${result.ini_sha256}\n` +
        result.changes.map(c => `0x${c.offset.toString(16).toUpperCase()}: ${c.before} → ${c.after}`).join('\n') +
        `\nSynthetic-tested only; verify every changed byte and its meaning. Plan expires in ${result.expires_seconds} seconds.`;
    } catch (error) { if (token === generation) tuneOut.textContent = `Review failed: ${error.message}`; }
    finally { tunePrepare.disabled = !evidence; }
  };
  tuneWrite.onclick = async () => {
    if (!plan || !evidence || !confirm.checked || !tuneConfirm.checked || isHostedDemo()) return;
    const selected = plan, token = generation;
    const accepted = await confirmDialog('Write and burn rusEFI calibration?',
      `<p>Live RAM writes can affect operation before burn. The integration is <b>synthetic-tested only</b>; a failure may leave an uncertain partial calibration. A CRC request can complete a previously pending burn. The signature is not unique; CRC and readback do not prove correct tune, identity or persistent flash. Engine must be stopped and power stable.</p>`,
      'Write and burn', {tone:'danger'});
    if (!accepted || token !== generation || plan !== selected) return;
    busy = true; evidence = null; clearPlan(); tunePrepare.disabled = true; disableOperations(true);
    tuneOut.textContent = 'Checking the page, writing RAM and burning; do not disconnect or start the engine…';
    try {
      const result = await api('/api/tools/rusefi-read', {method:'POST', body:{
        action:'write-calibration', confirm:true, confirm_tuning:true, confirm_write:true, token:selected.token,
      }});
      tuneOut.textContent = `Wrote ${result.changed_bytes} bytes in ${result.chunks_written} chunks.\nOriginal: ${result.original_path}\n${result.note}`;
    } catch (error) { tuneOut.textContent = `Write stopped: ${error.message}`; }
    finally { busy = false; disableOperations(false); }
  };
  identify.onclick = () => perform('identify');
  read.onclick = () => perform('read');
  outputs.onclick = () => perform('outputs');
}
