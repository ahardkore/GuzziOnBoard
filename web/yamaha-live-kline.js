/* Source-scoped, receive-only Yamaha MT-03 dashboard-stream observation. */
'use strict';
const yamahaLiveOut = document.getElementById('yamahaLiveOut');
const yamahaLiveButton = document.getElementById('yamahaLiveObserve');
let yamahaLiveGeneration = 0;
document.getElementById('yamahaLivePort').addEventListener('change', () => {
  ++yamahaLiveGeneration;
  document.getElementById('yamahaLiveConfirm').checked = false;
  yamahaLiveOut.textContent = 'Port changed; reconfirm before observing.';
});
yamahaLiveButton.onclick = async () => {
  const token = ++yamahaLiveGeneration;
  if (isHostedDemo()) { yamahaLiveOut.textContent = 'The hosted demo cannot access serial hardware.'; return; }
  if (!document.getElementById('yamahaLiveConfirm').checked) { yamahaLiveOut.textContent = 'Confirm the bike, wiring and limitations first.'; return; }
  yamahaLiveButton.disabled = true;
  yamahaLiveOut.textContent = 'Observing a two-second window…';
  try {
    const result = await api('/api/tools/yamaha-mt03-listen', {method: 'POST', body: {port: document.getElementById('yamahaLivePort').value, confirm: true}});
    if (token !== yamahaLiveGeneration) return;
    const current = result.latest;
    yamahaLiveOut.textContent = `Current window: ${result.bytes_received} bytes · ${result.candidate_frames} candidate frames${result.byte_limit_reached ? ' · byte limit reached' : ''}.\n` +
      (current ? `Raw ${current.raw}\nRPM candidate: ${current.rpm_candidate}\nSpeed byte: ${current.speed_byte_raw} · status byte: ${current.status_byte_raw} · temperature byte: ${current.temperature_byte_raw}${current.temperature_ff_unavailable_candidate ? ' (0xFF: source says unavailable)' : ''}` : 'No candidate frame in this window.') +
      '\nChecksum matches can be accidental; not verified ECU data.';
  } catch (error) {
    if (token === yamahaLiveGeneration) yamahaLiveOut.textContent = `Observation failed: ${error.message}`;
  } finally { yamahaLiveButton.disabled = false; }
};
