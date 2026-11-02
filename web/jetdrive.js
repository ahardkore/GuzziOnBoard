/* Bounded JetDrive observer; protocol adapted from MIT-licensed DynoAI. */
'use strict';
{
  const group = document.getElementById('jetdriveGroup'), iface = document.getElementById('jetdriveInterface');
  const request = document.getElementById('jetdriveRequest'), confirm = document.getElementById('jetdriveConfirm');
  const capture = document.getElementById('jetdriveCapture'), exportButton = document.getElementById('jetdriveExport');
  const overlayButton = document.getElementById('jetdriveToOverlay');
  const out = document.getElementById('jetdriveOut');
  let samples = [], generation = 0;
  function syncButtons() {
    const empty = samples.length === 0;
    exportButton.disabled = empty;
    if (overlayButton) overlayButton.disabled = empty;
  }
  function reset(message) { ++generation; samples = []; syncButtons(); out.textContent = message; }
  for (const field of [group, iface, request, confirm]) {
    field.addEventListener('change', () => {
      if (field !== confirm) confirm.checked = false;
      reset('Selection changed; reconfirm before capturing.');
    });
    if (field === iface) field.addEventListener('input', () => { confirm.checked = false; reset('Interface changed; reconfirm before capturing.'); });
  }
  capture.onclick = async () => {
    reset(''); const token = generation;
    if (isHostedDemo()) { out.textContent = 'The hosted demo cannot access the local dyno network.'; return; }
    if (!confirm.checked) { out.textContent = 'Confirm the dyno network first.'; return; }
    capture.disabled = true; out.textContent = 'Observing a three-second JetDrive window…';
    try {
      const result = await api('/api/tools/jetdrive', {method:'POST', body:{group:group.value, interface:iface.value, request_info:request.checked, confirm:true}});
      if (token !== generation) return;
      samples = result.samples; syncButtons();
      const lines = samples.slice(-50).map((s) => `${s.source} · provider ${s.provider} · ${s.channel_name || `channel ${s.id}`} [unit ${s.unit_code ?? '?'}] · ${s.timestamp_ms} ms · ${s.value}`);
      out.textContent = `${result.packets} datagrams, ${result.invalid_packets} ignored, ${samples.length} sample(s)${result.limit_reached ? ' · limit reached' : ''}${result.metadata_requested ? ' · metadata request sent' : ' · receive only'}.\n${lines.length ? lines.join('\n') : 'No samples in this window.'}\nCurrent window only; telemetry is not authenticated or hardware-validated.`;
    } catch (error) { if (token === generation) out.textContent = `Capture failed: ${error.message}`; }
    finally { capture.disabled = false; }
  };
  function pivotJetDriveSamples(list) {
    const channelNames = [];
    const seen = new Set();
    const sorted = [...list]
      .filter((s) => Number.isFinite(Number(s?.timestamp_ms)) && Number.isFinite(Number(s?.value)))
      .sort((a, b) => Number(a.timestamp_ms) - Number(b.timestamp_ms));
    for (const s of sorted) {
      const col = (s.channel_name && String(s.channel_name).trim()) || `channel_${s.id}`;
      if (!seen.has(col)) { seen.add(col); channelNames.push(col); }
    }
    const headers = ['timestamp_ms', ...channelNames];
    const latest = new Map();
    const byTs = new Map();
    for (const s of sorted) {
      const ts = Number(s.timestamp_ms);
      const col = (s.channel_name && String(s.channel_name).trim()) || `channel_${s.id}`;
      if (!byTs.has(ts)) byTs.set(ts, []);
      byTs.get(ts).push([col, Number(s.value)]);
    }
    const MAX_HOLD_MS = 100;
    const rows = [];
    for (const [ts, updates] of byTs.entries()) {
      for (const [col, val] of updates) latest.set(col, { ts, val });
      const row = { timestamp_ms: String(ts) };
      let complete = channelNames.length > 0;
      for (const col of channelNames) {
        const entry = latest.get(col);
        if (!entry || (ts - entry.ts) > MAX_HOLD_MS) { complete = false; row[col] = ''; }
        else row[col] = String(entry.val);
      }
      if (complete) rows.push(row);
    }
    return { headers, rows };
  }
  if (overlayButton) {
    overlayButton.onclick = () => {
      if (!samples.length) return;
      const pivoted = pivotJetDriveSamples(samples);
      if (typeof window.guzziLoadJetDriveOverlay === 'function') {
        window.guzziLoadJetDriveOverlay({ ...pivoted, sampleCount: samples.length });
      }
    };
  }
  window.guzziSetJetDriveSamples = (nextSamples) => {
    samples = Array.isArray(nextSamples) ? nextSamples : [];
    syncButtons();
    return pivotJetDriveSamples(samples);
  };
  function csvCell(value, isText = false) {
    let text = value == null ? '' : String(value);
    if (isText && /^[\s]*[=+\-@\t\r]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  }
  exportButton.onclick = () => {
    if (!samples.length) return;
    const rows = ['source,provider,provider_name,sequence,channel_id,channel_name,unit_code,timestamp_ms,value'];
    for (const s of samples) rows.push([csvCell(s.source, true),csvCell(s.provider),csvCell(s.provider_name, true),csvCell(s.sequence),csvCell(s.id),csvCell(s.channel_name, true),csvCell(s.unit_code),csvCell(s.timestamp_ms),csvCell(s.value)].join(','));
    download(`guzzionboard-jetdrive-${Date.now()}.csv`, rows.join('\n') + '\n', 'text/csv');
  };
}
