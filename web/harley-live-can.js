/* Receive-only Harley HDLAN observation. Shared GPL source attribution and
 * model-dependent mapping details are in guzzionboard/harley_hdlan_can.py. */
'use strict';
let harleyObservationGeneration = 0;
let harleyObservationActive = false;
const harleyLiveOut = document.getElementById('harleyLiveOut');
const harleyStart = document.getElementById('harleyLiveStart');
const harleyStop = document.getElementById('harleyLiveStop');
function stopHarleyObservation(message = 'Observation stopped.') {
  ++harleyObservationGeneration;
  harleyObservationActive = false;
  harleyStart.disabled = false;
  harleyStop.disabled = true;
  harleyLiveOut.textContent = message;
}
harleyStop.onclick = () => stopHarleyObservation();
harleyStart.onclick = async () => {
  if (isHostedDemo()) return stopHarleyObservation('The hosted demo cannot access CAN hardware.');
  if (!document.getElementById('harleyLiveConfirm').checked) return stopHarleyObservation('Confirm the bus and limitations before starting.');
  const channel = document.getElementById('harleyLiveChannel').value;
  const profile = document.getElementById('harleyLiveProfile').value;
  const token = ++harleyObservationGeneration;
  harleyObservationActive = true;
  harleyStart.disabled = true; harleyStop.disabled = false;
  harleyLiveOut.textContent = 'Observing a two-second window…';
  while (harleyObservationActive && token === harleyObservationGeneration) {
    try {
      const result = await api('/api/tools/harley-hdlan-listen', {method: 'POST', body: {channel, profile, confirm: true}});
      if (!harleyObservationActive || token !== harleyObservationGeneration) return;
      const lines = result.events.map((event) => `${event.id} · raw ${event.raw} · ${Object.entries(event.values).map(([k, v]) => `${k}: ${v ?? 'unavailable'}`).join(' · ')}`);
      harleyLiveOut.textContent = `Current window: ${result.frames_received} received frame(s), ${result.invalid_length_frames} invalid length(s)${result.frame_limit_reached ? ' · frame limit reached' : ''}.\n${lines.length ? lines.join('\n') : 'No recognized values in this window.'}\nCandidate values only; no ECU identification or diagnostic requests.`;
      await new Promise((resolve) => setTimeout(resolve, 250));
    } catch (error) {
      if (token === harleyObservationGeneration) stopHarleyObservation(`Observation stopped: ${error.message}`);
      return;
    }
  }
};
document.getElementById('harleyLiveConfirm').addEventListener('change', (event) => {
  if (!event.target.checked && harleyObservationActive) stopHarleyObservation('Confirmation removed; observation stopped.');
});
for (const id of ['harleyLiveChannel', 'harleyLiveProfile']) {
  document.getElementById(id).addEventListener('change', () => {
    document.getElementById('harleyLiveConfirm').checked = false;
    if (harleyObservationActive) stopHarleyObservation('Selection changed; reconfirm before observing.');
  });
}
document.addEventListener('visibilitychange', () => {
  if (document.hidden && harleyObservationActive) stopHarleyObservation('Observation stopped when the page was hidden.');
});
