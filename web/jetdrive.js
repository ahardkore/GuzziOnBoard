/* Bounded JetDrive observer; protocol adapted from MIT-licensed DynoAI. */
'use strict';
{
  const group = document.getElementById('jetdriveGroup'), iface = document.getElementById('jetdriveInterface');
  const request = document.getElementById('jetdriveRequest'), confirm = document.getElementById('jetdriveConfirm');
  const capture = document.getElementById('jetdriveCapture'), exportButton = document.getElementById('jetdriveExport');
  const out = document.getElementById('jetdriveOut');
  let samples = [], generation = 0;
  function reset(message) { ++generation; samples = []; exportButton.disabled = true; out.textContent = message; }
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
      samples = result.samples; exportButton.disabled = samples.length === 0;
      const lines = samples.slice(-50).map((s) => `${s.source} · provider ${s.provider} · ${s.channel_name || `channel ${s.id}`} [unit ${s.unit_code ?? '?'}] · ${s.timestamp_ms} ms · ${s.value}`);
      out.textContent = `${result.packets} datagrams, ${result.invalid_packets} ignored, ${samples.length} sample(s)${result.limit_reached ? ' · limit reached' : ''}${result.metadata_requested ? ' · metadata request sent' : ' · receive only'}.\n${lines.length ? lines.join('\n') : 'No samples in this window.'}\nCurrent window only; telemetry is not authenticated or hardware-validated.`;
    } catch (error) { if (token === generation) out.textContent = `Capture failed: ${error.message}`; }
    finally { capture.disabled = false; }
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
