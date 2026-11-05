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
  const image = document.getElementById('buellImage');
  const saveImage = document.getElementById('buellSaveImage');
  const original = document.getElementById('buellWriteOriginal');
  const edited = document.getElementById('buellWriteEdited');
  const writeConfirm = document.getElementById('buellWriteConfirm');
  const prepareWrite = document.getElementById('buellWritePrepare');
  const executeWrite = document.getElementById('buellWriteExecute');
  const writeOutput = document.getElementById('buellWriteOut');
  const openMap = document.getElementById('buellOpenMap');
  const mapStatus = document.getElementById('buellMapStatus');
  let writePlan = null;
  let writing = false;
  window.addEventListener('beforeunload', (event) => {
    if (writing) { event.preventDefault(); event.returnValue = ''; }
  });
  function invalidateWrite() {
    writePlan = null; executeWrite.disabled = true;
    writeOutput.textContent = 'Selection changed; review a new write plan.';
  }
  let lastImage = null;
  let mapReadyImage = null;
  let generation = 0;
  async function prepareMap(result, showAfter = false) {
    const isCurrent = () => lastImage === result && confirm.checked && version.value === result.version && !writing;
    const attach = (path, oldValue) => {
      if (!isCurrent() || edited.value !== oldValue) return false;
      generation++; edited.value = path; invalidateWrite();
      writeOutput.textContent = `Edited copy ready: ${path}\nConfirm the risks and review the differences; no SET has been sent.`;
      return true;
    };
    openMap.disabled = true;
    mapStatus.textContent = 'Opening the saved image with its source-derived XDF; fitment is not verified…';
    try {
      await openBuellResearchMap(result, isCurrent, () => edited.value, attach);
      if (!isCurrent()) return;
      mapReadyImage = result; openMap.disabled = false;
      mapStatus.textContent = `Saved image opened in Maps with ${result.map_xdf}. Inspect fitment and values, stage edits, preview, and save for Buell review. Synthetic-tested only.`;
      if (showAfter) show('firmware');
    } catch (error) {
      if (!isCurrent()) return;
      openMap.disabled = false;
      mapStatus.textContent = `Map was not opened: ${error.message} The saved original remains available; retry after resolving this issue.`;
    }
  }
  for (const field of [port, mode, version, page, offset, length, compare, confirm]) {
    const invalidate = () => {
      generation++;
      invalidateWrite();
      lastImage = null; saveImage.disabled = true; original.readOnly = false;
      openMap.disabled = true; mapStatus.textContent = 'Selection changed; read an image again.';
      if (field !== confirm) confirm.checked = false;
      if (field === port || field === mode) version.value = '';
      output.textContent = 'Selection changed; reconfirm before continuing.';
    };
    field.addEventListener('change', invalidate);
    if (field !== confirm) field.addEventListener('input', invalidate);
  }
  for (const field of [original, edited, writeConfirm]) {
    field.addEventListener('change', () => { generation++; invalidateWrite(); });
    if (field !== writeConfirm) field.addEventListener('input', () => { generation++; invalidateWrite(); });
  }
  async function perform(action) {
    invalidateWrite();
    const token = ++generation;
    if (isHostedDemo()) { output.textContent = 'The hosted demo cannot access serial hardware.'; return; }
    if (!confirm.checked) { output.textContent = 'Confirm the ECM, adapter and wiring first.'; return; }
    if (action !== 'identify' && !version.value) { output.textContent = 'Identify the ECM first.'; return; }
    if (action === 'read' && (!page.value || !offset.value || !length.value)) { output.textContent = 'Enter a complete page range.'; return; }
    identify.disabled = runtime.disabled = read.disabled = image.disabled = true;
    lastImage = null; saveImage.disabled = true; original.readOnly = false;
    openMap.disabled = true; mapStatus.textContent = 'Read an image to prepare a candidate source definition.';
    output.textContent = 'Communicating with the selected local serial device…';
    try {
      const body = {port: port.value, mode: mode.value, action, confirm: true};
      if (action !== 'identify') body.version = version.value;
      if (action === 'read') Object.assign(body, {page: Number(page.value), offset: Number(offset.value), length: Number(length.value), compare_repeat: compare.checked});
      if (action === 'image') body.compare_repeat = compare.checked;
      const result = await api('/api/tools/buell-ddfi', {method: 'POST', body});
      if (token !== generation) return;
      if (action === 'identify') {
        version.value = result.version;
        confirm.checked = false;
      }
      output.textContent = `ECM version: ${result.version}\n` + (action === 'identify'
        ? 'Check version and wiring, then reconfirm to read.'
        : action === 'runtime' ? `Runtime data (${result.length} bytes):\n${result.data_hex}\n` + (result.bueia_candidates ? `BUEIA ADX candidates: ${JSON.stringify(result.bueia_candidates)}\nSynthetic-tested only; do not use these values for riding or safety decisions.` : 'Raw payload; layout varies by ECM.')
        : action === 'image' ? `Source-described ${result.layout} EEPROM image: ${result.length} bytes; SHA-256 ${result.sha256}.\n${result.repeated_match ? 'Two complete reads matched.' : 'Read once; no repeat comparison.'} Responses do not echo addresses; not independently verified or authorization to write.`
        : `Page ${result.page}, offset ${result.offset}, ${result.length} bytes:\n${result.data_hex}\nPartial EEPROM research data, not a complete backup. ${result.repeated_match ? 'Two range reads matched; this does not prove reply-address association or ECU identity.' : 'Read once; no repeat comparison.'}`) +
        '\nSynthetic-tested only; no write, clear, actuator or reset command sent.';
      if (action === 'image') {
        if (!/^(?:[0-9A-F]{2})+$/.test(result.data_hex) || result.data_hex.length !== result.length * 2) throw new Error('Invalid EEPROM image response.');
        lastImage = result; saveImage.disabled = false;
        if (result.read_token && result.original_path) {
          original.value = result.original_path; original.readOnly = true;
          document.getElementById('buellWritePanel').open = true;
          writeOutput.textContent = `Original saved: ${result.original_path}\nUse this path with the matching XDF in Maps, then enter the exported edited image path and review. The original is not independently verified.`;
          output.textContent += `\nOriginal saved: ${result.original_path}\nWrite review opened; no SET was sent.`;
          if (result.map_xdf) void prepareMap(result);
        } else if (result.write_review_unavailable) {
          output.textContent += `\nAutomatic write review unavailable: ${result.write_review_unavailable}`;
        }
      }
    } catch (error) { if (token === generation) output.textContent = `Buell communication failed: ${error.message}`; }
    finally { identify.disabled = runtime.disabled = read.disabled = image.disabled = false; }
  }
  openMap.onclick = () => {
    if (!lastImage || openMap.disabled) return;
    if (mapReadyImage === lastImage && maps.buellHandoff?.isCurrent() && maps.render?.source?.path === lastImage.original_path && $('#xdfSelect').value === lastImage.map_xdf) show('firmware');
    else void prepareMap(lastImage, true);
  };
  identify.onclick = () => perform('identify');
  runtime.onclick = () => perform('runtime');
  read.onclick = () => perform('read');
  image.onclick = () => perform('image');
  prepareWrite.onclick = async () => {
    if (isHostedDemo()) { writeOutput.textContent = 'Hosted demo cannot access serial hardware or local paths.'; return; }
    if (!confirm.checked || !writeConfirm.checked || !version.value) {
      writeOutput.textContent = 'Identify and confirm the ECM, wiring, engine state and write warning first.'; return;
    }
    const token = ++generation;
    invalidateWrite(); prepareWrite.disabled = true;
    writeOutput.textContent = 'Reviewing local EEPROM files; no ECM write is sent…';
    try {
      const body = lastImage?.read_token
        ? {action: 'prepare-from-read', confirm: true, read_token: lastImage.read_token, edited_path: edited.value.trim()}
        : {action: 'prepare-write', confirm: true, port: port.value, mode: mode.value,
           version: version.value, original_path: original.value.trim(), edited_path: edited.value.trim()};
      const result = await api('/api/tools/buell-ddfi', {method: 'POST', body});
      if (token !== generation) return;
      writePlan = result; executeWrite.disabled = false;
      writeOutput.textContent = `ECM ${result.version}; ${result.changes.length} changed bytes; XDF ${result.xdf}.\nOriginal SHA-256 ${result.base_sha256}\nEdited SHA-256 ${result.target_sha256}\n` +
        result.changes.map(c => `0x${c.offset.toString(16).toUpperCase()}: ${c.before} → ${c.after}`).join('\n') +
        `\n${result.warning}\nPlan expires after ${result.expires_seconds} seconds.`;
    } catch (error) { if (token === generation) writeOutput.textContent = `Review failed: ${error.message}`; }
    finally { prepareWrite.disabled = false; }
  };
  executeWrite.onclick = async () => {
    if (!writePlan || !confirm.checked || !writeConfirm.checked || isHostedDemo()) return;
    const selected = writePlan, token = generation;
    const accepted = await confirmDialog('Write Buell EEPROM?',
      `<p>This sends live EEPROM SET commands for <b>${esc(selected.version)}</b>. ` +
      `The integration has only synthetic tests; the ECM can be damaged. ` +
      (selected.single_read
        ? `The saved single-read original is rechecked; only affected live chunks are compared before SET, not the full image. Version is not a unique identity; an ECM swap or unrelated changes may go undetected. `
        : `A fresh full image backup is saved before any write. `) +
      `Changed chunks are written and read back. A later mismatch or failure can leave an uncertain partial tune.</p>`, 'Write EEPROM', {tone: 'danger'});
    if (!accepted || token !== generation || selected !== writePlan) return;
    writing = true;
    lastImage = null; saveImage.disabled = true; original.readOnly = false;
    openMap.disabled = true; mapStatus.textContent = 'A write was attempted; read a fresh image before another review.';
    writePlan = null; executeWrite.disabled = prepareWrite.disabled = true;
    identify.disabled = runtime.disabled = read.disabled = image.disabled = true;
    writeOutput.textContent = 'Checking ECM and original, then writing; keep power and the adapter connected…';
    try {
      const result = await api('/api/tools/buell-ddfi', {method: 'POST', body: {
        action: 'write', confirm: true, confirm_write: true, token: selected.token,
      }});
      writeOutput.textContent = `Readback matched ${result.chunks_written} written chunks (${result.edited_bytes} edited bytes).\n${result.single_read ? 'Single-read original' : 'Fresh backup'}: ${result.backup_path}\nBackup SHA-256: ${result.backup_sha256}\n${result.note}`;
    } catch (error) { writeOutput.textContent = `Write stopped: ${error.message}`; }
    finally { writing = false; prepareWrite.disabled = false; identify.disabled = runtime.disabled = read.disabled = image.disabled = false; }
  };
  saveImage.onclick = async () => {
    if (!lastImage) return;
    const savedImage = lastImage, token = generation;
    saveImage.disabled = true;
    try {
      const bytes = Uint8Array.from(savedImage.data_hex.match(/../g), (value) => parseInt(value, 16));
      const name = `${savedImage.layout}-guzzionboard-${Date.now()}.xpr`;
      if (window.gobDesktop?.available) {
        if (typeof window.gobDesktop.saveBinary !== 'function') throw new Error('Desktop binary export unavailable.');
        let binary = '';
        for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
        const saved = await window.gobDesktop.saveBinary(name, btoa(binary));
        if (token === generation) { if (!savedImage.read_token) original.value = saved.path; invalidateWrite(); output.textContent += `\nSaved: ${saved.path}\nTo inspect/edit, enter this path in Maps and select a matching XDF; any exported changes are research-only.`; }
      } else {
        const url = URL.createObjectURL(new Blob([bytes], {type: 'application/octet-stream'}));
        const link = document.createElement('a'); link.href = url; link.download = name; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        if (token === generation) output.textContent += `\nDownloaded: ${name}`;
      }
    } catch (error) { if (token === generation) output.textContent += `\nSave failed: ${error.message}`; }
    finally { if (token === generation && lastImage === savedImage) saveImage.disabled = false; }
  };

  // Offline import of a read the operator already has. No port, no confirm.
  const importPath = document.getElementById('buellImportPath');
  const importEcm = document.getElementById('buellImportEcm');
  const importRun = document.getElementById('buellImportRun');
  const importOut = document.getElementById('buellImportOut');
  if (importRun) {
    importRun.onclick = async () => {
      if (isHostedDemo()) { importOut.textContent = 'The hosted demo cannot read local files.'; return; }
      const path = importPath.value.trim();
      if (!path) { importOut.textContent = 'Enter the absolute path of an .epr or hex-dump file.'; return; }
      const ecm = importEcm.value.trim().toUpperCase();
      importRun.disabled = true;
      importOut.textContent = 'Checking the file against the source page layouts…';
      try {
        const result = await api('/api/tools/buell-ddfi', {method: 'POST', body: {
          action: 'import', path, ...(ecm ? {ecm_id: ecm} : {}),
        }});
        importOut.textContent =
          `Imported ${result.kind} as ${result.ecm_id}; ${result.size} bytes; SHA-256 ${result.sha256}.\n` +
          (result.header ? `Header: ${result.header}\n` : '') +
          `Pages present: ${result.pages.map((entry) => `${entry.page} (${entry.size} B)`).join(', ')}\n` +
          (result.missing_page_zero ? `Page zero (${result.page_zero_size} bytes) is absent; the write review needs it.\n` : '') +
          `Research copy: ${result.saved_path}\nOpen that path in Maps with ${result.map_xdf} and address base ${result.address_base}. It is not flash-ready.\n` +
          result.warnings.map((warning) => `- ${warning}`).join('\n');
      } catch (error) { importOut.textContent = `Import failed: ${error.message}`; }
      finally { importRun.disabled = false; }
    };
  }
}
