/* Experimental Delphi CAN memory: synthetic tests only. */
'use strict';
{
  const $h = id => document.getElementById(id);
  const iface = $h('hdMemInterface'), channel = $h('hdMemChannel'), capture = $h('hdMemCapture');
  const region = $h('hdMemRegion'), repeat = $h('hdMemRepeat'), confirm = $h('hdMemConfirm');
  const original = $h('hdMemOriginal'), edited = $h('hdMemEdited'), writeConfirm = $h('hdMemWriteConfirm');
  const read = $h('hdMemRead'), save = $h('hdMemSave'), prepare = $h('hdMemPrepare'), write = $h('hdMemWrite');
  const out = $h('hdMemOut'), writeOut = $h('hdMemWriteOut'), writePanel = $h('hdMemWritePanel');
  const openMap = $h('hdMemOpenMap'), mapStatus = $h('hdMemMapStatus');
  let result = null, plan = null, generation = 0, active = false, reviewing = false;
  const updateReady = () => {
    openMap.disabled = active || reviewing || !result?.read_token || !confirm.checked;
    prepare.disabled = active || reviewing || !result?.read_token || !edited.value.trim();
    write.disabled = active || reviewing || !plan || !confirm.checked || !writeConfirm.checked;
  };
  window.addEventListener('beforeunload', e => { if (active) { e.preventDefault(); e.returnValue = ''; } });
  const invalidate = () => { plan = null; write.disabled = true; writeOut.textContent = 'Selection changed; review a new plan.'; };
  for (const field of [iface, channel, capture, region, repeat, confirm, edited]) {
    const update = () => {
      generation++; invalidate();
      if ([iface, channel, capture, region, repeat, confirm].includes(field)) {
        result = null; save.disabled = true; original.value = ''; writeConfirm.checked = false;
      }
      if (field === edited) writeConfirm.checked = false;
      if ([iface, channel, capture].includes(field)) confirm.checked = false;
      updateReady();
    };
    field.addEventListener('change', update);
    if (field.tagName === 'INPUT' && field.type !== 'checkbox') field.addEventListener('input', update);
  }
  writeConfirm.addEventListener('change', updateReady);
  const selected = () => ({interface: iface.value, channel: channel.value.trim(), capture_path: capture.value.trim(), confirm: true});
  const busy = value => { active = value; read.disabled = value; if (value) save.disabled = true; updateReady(); };
  read.onclick = async () => {
    if (isHostedDemo()) { out.textContent = 'The hosted demo cannot access local CAN hardware.'; return; }
    if (!confirm.checked) { out.textContent = 'Confirm the opaque download and ECU conditions first.'; return; }
    invalidate(); result = null; original.value = ''; writeConfirm.checked = false; const gen = ++generation; busy(true);
    out.textContent = 'Authenticating and reading; keep power and adapter connected. This can take several minutes…';
    try {
      const data = await api('/api/tools/harley-memory', {method: 'POST', body: {...selected(), action: 'read', region: region.value, compare_repeat: repeat.checked}});
      if (gen !== generation) return;
      result = data;
      if (data.read_token) {
        original.value = data.original_tune_path;
        writePanel.open = true;
        writeOut.textContent = 'Single-read original saved automatically. Open it in Maps with a user-selected XDF or choose an edited 16 KiB tune to review; no pre-write reread will occur.';
        mapStatus.textContent = 'Saved 16 KiB tune is ready. Choose your matching XDF in Maps; fitment and checksum are not verified.';
      }
      out.textContent = `ECU DIDs: ${JSON.stringify(data.identity)}\n${data.region}: ${data.length} bytes at 0x${data.address.toString(16).toUpperCase()}\nSHA-256 ${data.sha256}\n${data.repeated_match ? 'Two reads matched.' : 'Single read only.'} Synthetic-tested only; trailing response bytes and calibration checksum are not verified.` +
        (data.read_token ? `\nSingle-read original (not verified): ${data.original_tune_path}\nOriginal tune SHA-256 ${data.original_tune_sha256}` : data.write_review_unavailable ? `\nWrite review unavailable: ${data.write_review_unavailable}` : '\nThis region cannot be used for tune-write review.');
    } catch (error) { if (gen === generation) out.textContent = `Read stopped: ${error.message} Authentication may have altered ECU state.`; }
    finally { busy(false); if (result && gen === generation) save.disabled = false; }
  };
  openMap.onclick = async () => {
    const selectedRead = result;
    if (!selectedRead?.read_token || !confirm.checked || active || reviewing) return;
    const isCurrent = () => result === selectedRead && confirm.checked && !active;
    const attach = (path, oldValue) => {
      if (!isCurrent() || edited.value !== oldValue) return false;
      generation++; edited.value = path; invalidate(); writeConfirm.checked = false; updateReady();
      writeOut.textContent = `Edited copy ready: ${path}\nReview every difference and the unknown checksum before any write.`;
      return true;
    };
    openMap.disabled = true;
    try { await openHarleyResearchMap(selectedRead, isCurrent, () => edited.value, attach); }
    catch (error) { if (isCurrent()) mapStatus.textContent = `Map not opened: ${error.message}`; }
    finally { updateReady(); }
  };
  save.onclick = async () => {
    if (!result) return;
    const data = result, gen = generation;
    try {
      const bytes = Uint8Array.from(data.data_hex.match(/../g), v => parseInt(v,16));
      if (bytes.length !== data.length) throw new Error('Invalid read data length.');
      const name = `harley-delphi-${data.region}-${Date.now()}.bin`;
      if (window.gobDesktop?.available) {
        let binary = ''; for (let i=0; i<bytes.length; i+=8192) binary += String.fromCharCode(...bytes.subarray(i,i+8192));
        const saved = await window.gobDesktop.saveBinary(name, btoa(binary));
        if (gen === generation) out.textContent += `\nSaved: ${saved.path}`;
      } else {
        const url = URL.createObjectURL(new Blob([bytes], {type: 'application/octet-stream'}));
        const link = document.createElement('a'); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
        if (gen === generation) out.textContent += `\nDownloaded: ${name}`;
      }
    } catch (e) { out.textContent += `\nSave failed: ${e.message}`; }
  };
  prepare.onclick = async () => {
    if (isHostedDemo() || !confirm.checked || !result?.read_token) { writeOut.textContent = 'A current tune or calibration read is required.'; return; }
    const gen = ++generation; invalidate(); reviewing = true; updateReady();
    try {
      const data = await api('/api/tools/harley-memory', {method:'POST', body:{action:'prepare-from-read', confirm:true, read_token:result.read_token, edited_path:edited.value.trim()}});
      if (gen !== generation) return;
      plan = data; writeConfirm.checked = false;
      writeOut.textContent = `Identity ${JSON.stringify(data.identity)}\nOriginal SHA-256 ${data.original_sha256}\nTarget SHA-256 ${data.target_sha256}\n${data.changed_bytes} changed bytes:\n` + data.changes.map(c => `0x${c.offset.toString(16).toUpperCase()}: ${c.before} → ${c.after}`).join('\n') + `\nOne-read original; no pre-write reread. Entire 16 KiB written. Unknown checksum and recovery. Plan expires in ${data.expires_seconds} seconds.`;
    } catch(e) { if (gen === generation) writeOut.textContent = `Review failed: ${e.message}`; }
    finally { reviewing = false; updateReady(); }
  };
  write.onclick = async () => {
    if (!plan || !confirm.checked || !writeConfirm.checked || isHostedDemo()) return;
    const picked = plan, gen = generation;
    const ok = await confirmDialog('Write Harley Delphi tune?', '<p>Experimental: the entire 16 KiB tune will be downloaded using the single saved read, without a fresh pre-write comparison. Raw DIDs may not identify an ECU uniquely: an ECU swap or tune change since the read may go undetected. Checksums, fitment and recovery are unknown; the engine-stop check is manual. Authentication can change ECU state. A failed write may permanently damage the ECU. Keep power connected.</p>', 'Write tune', {tone:'danger'});
    if (!ok || gen !== generation || picked !== plan || !confirm.checked || !writeConfirm.checked) return;
    plan = null; busy(true); writeOut.textContent = 'Checking the saved original, authenticating and checking identity before download; no fresh tune read. Keep power connected…';
    try {
      const data = await api('/api/tools/harley-memory', {method:'POST', body:{action:'write', confirm:true, confirm_write:true, token:picked.token}});
      writeOut.textContent = `Readback matched. Backup: ${data.backup_path}\nBackup SHA-256 ${data.backup_sha256}\n${data.note}`;
    } catch(e) { writeOut.textContent = `Write stopped: ${e.message}`; }
    finally { result = null; original.value = ''; writeConfirm.checked = false; save.disabled = true; busy(false); }
  };
}
