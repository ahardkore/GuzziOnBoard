/* GuzziOnBoard workstation UI.
 *
 * Deliberately dependency-free and readable: this is a tool people will run on
 * a laptop in a garage, and every number it shows has to be traceable back to
 * the bytes the ECU sent.
 */
'use strict';

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));

const state = {
  catalog: null,
  status: null,
  selection: null,
  connected: false,
  parameters: [],
  selectedChannels: new Set(),
  history: new Map(),       // key -> [values]
  polling: false,
  pollTimer: null,
  lastPollAt: 0,
  scan: null,
  baseline: null,
  report: null,
};

const HISTORY_LEN = 90;

/* ------------------------------------------------------------------ utils */

function toast(message, level = 'info') {
  const el = $('#toast');
  el.textContent = message;
  el.className = `toast show ${level}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('show'), 4200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  let payload = {};
  try { payload = await response.json(); } catch (_) { /* empty body */ }
  if (!response.ok) {
    const error = new Error(payload.error || `HTTP ${response.status}`);
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return payload;
}

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));

const confidenceClass = (c) => ({
  'verified-bench': 'ok', 'verified-capture': 'ok',
  documented: 'mid', inferred: 'low', unknown: 'low',
}[c] || 'low');

/* ----------------------------------------------------------- navigation */

const VIEW_META = {
  garage: ['Garage', 'Choose the motorcycle and the way you are talking to it.'],
  overview: ['Overview', 'Who this ECU says it is, and what it can do.'],
  live: ['Live data', 'Decoded channels, with the raw bytes behind them.'],
  faults: ['Fault codes', 'Stored and current diagnostic trouble codes.'],
  service: ['Service actions', 'Everything here changes something on the bike.'],
  discovery: ['Discovery', 'Read-only sweep for unmapped local identifiers.'],
  sessions: ['Sessions', 'Recorded frames, samples and safety decisions.'],
  report: ['Report', 'A shareable snapshot of this session.'],
};

function show(view) {
  $$('.view').forEach((v) => v.classList.toggle('hidden', v.id !== view));
  $$('.nav').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  const [title, sub] = VIEW_META[view] || ['', ''];
  $('#pageTitle').textContent = title;
  $('#pageSub').textContent = sub;
  if (view === 'sessions') loadSessions();
  if (view === 'service') loadServiceActions();
  if (view === 'overview') renderOverview();
}

$$('.nav').forEach((b) => (b.onclick = () => show(b.dataset.view)));

/* --------------------------------------------------------------- modal */

function confirmDialog(title, bodyHtml, confirmLabel = 'Confirm') {
  return new Promise((resolve) => {
    $('#modalTitle').textContent = title;
    $('#modalBody').innerHTML = bodyHtml;
    $('#modalConfirm').textContent = confirmLabel;
    $('#modal').classList.remove('hidden');
    const done = (value) => {
      $('#modal').classList.add('hidden');
      $('#modalConfirm').onclick = null;
      $('#modalCancel').onclick = null;
      resolve(value);
    };
    $('#modalConfirm').onclick = () => done(true);
    $('#modalCancel').onclick = () => done(false);
  });
}

/* -------------------------------------------------------------- catalog */

async function loadCatalog() {
  state.catalog = await api('/api/catalog');
  const { summary } = state.catalog;

  $('#modelList').innerHTML = state.catalog.models
    .map((m) => `<option value="${esc(m.model)}">`).join('');

  $('#ecuOverride').innerHTML = '<option value="">— use the model lookup —</option>'
    + state.catalog.ecus.map((e) =>
      `<option value="${esc(e.id)}">${esc(e.display_name)} · ${esc(e.years)}</option>`).join('');

  $('#coverageLine').innerHTML =
    `<b>${summary.ecu_count}</b> ECU families · <b>${summary.vehicle_count}</b> model variants · `
    + `<b>${summary.model_count}</b> distinct models · model years `
    + `<b>${summary.year_range[0]}–${summary.year_range[1]}</b>`;

  $('#ecuTable tbody').innerHTML = state.catalog.ecus.map((e) => `
    <tr>
      <td><b>${esc(e.display_name)}</b><div class="muted small">${esc(e.notes.slice(0, 120))}…</div></td>
      <td>${esc(e.years)}</td>
      <td><span class="tag">${esc(e.transport)}</span></td>
      <td><span class="conf ${confidenceClass(e.confidence)}">${esc(e.confidence)}</span></td>
      <td>${e.capabilities.map((c) => {
        const live = e.effective_capabilities.includes(c);
        return `<span class="tag ${live ? '' : 'muted-tag'}" title="${live ? 'available' : 'declared but gated by confidence'}">${esc(c)}</span>`;
      }).join(' ')}</td>
    </tr>`).join('');
}

async function resolveVehicle() {
  const model = $('#modelInput').value.trim();
  const year = parseInt($('#yearInput').value, 10);
  const box = $('#resolveResult');
  if (!model || !year) { box.innerHTML = ''; updateConnectEnabled(); return; }

  const data = await api(`/api/catalog/resolve?model=${encodeURIComponent(model)}&year=${year}`);
  if (!data.matches.length) {
    box.innerHTML = `<div class="resolve-card bad">No catalog entry for <b>${esc(model)} ${year}</b>.
      Check the spelling, or use the ECU override below if you know the family.</div>`;
    state.resolved = null; updateConnectEnabled(); return;
  }

  box.innerHTML = data.matches.map((m) => {
    const e = m.ecu_detail;
    return `<div class="resolve-card">
      <div class="resolve-head">
        <div><strong>${esc(e.display_name)}</strong>
          <span class="conf ${confidenceClass(e.confidence)}">${esc(e.confidence)}</span></div>
        <span class="tag">${esc(e.transport)}</span>
      </div>
      <div class="muted small">${esc(m.label)} · ${esc(m.displacement || '?')} cc · TPS ${esc(m.tps || 'n/a')}</div>
      ${m.notes ? `<p class="note">${esc(m.notes)}</p>` : ''}
      <div>${e.effective_capabilities.map((c) => `<span class="tag">${esc(c)}</span>`).join(' ')}</div>
    </div>`;
  }).join('')
    + (data.ambiguous ? `<div class="resolve-card warn">This model/year maps to more than one
      ECU family — a running change. Read the label on your ECU and use the override if needed.</div>` : '');

  state.resolved = data.matches[0];
  updateConnectEnabled();
}

/* ------------------------------------------------------------ transports */

function renderTransports(transports) {
  $('#transportList').innerHTML = transports.map((t) => `
    <label class="transport ${t.available ? '' : 'disabled'}">
      <input type="radio" name="transport" value="${esc(t.id)}" ${t.id === 'simulator' ? 'checked' : ''} ${t.available ? '' : 'disabled'}>
      <div>
        <strong>${esc(t.name)}</strong>
        <small>${esc(t.detail)}</small>
        ${(t.ports || []).length ? `<small class="ports">${t.ports.map((p) => esc(p.device)).join(', ')}</small>` : ''}
      </div>
    </label>`).join('');

  $$('input[name=transport]').forEach((r) => (r.onchange = onTransportChange));
  onTransportChange();
}

function currentTransport() {
  const checked = $('input[name=transport]:checked');
  return checked ? checked.value : 'simulator';
}

function onTransportChange() {
  const kind = currentTransport();
  const physical = kind !== 'simulator';
  $('#deviceField').hidden = !physical;
  $('#checklistBox').hidden = !physical;
  $('#deviceInput').placeholder = kind === 'can' ? 'can0' : '/dev/ttyUSB0';
  if (physical && $('#modeSelect').value === 'simulator') $('#modeSelect').value = 'read_only';
  if (!physical) $('#modeSelect').value = 'simulator';
  updateConnectEnabled();
}

function updateConnectEnabled() {
  const haveVehicle = Boolean(state.resolved) || Boolean($('#ecuOverride').value);
  const physical = currentTransport() !== 'simulator';
  const ok = haveVehicle && (!physical || $('#checklistAccept').checked);
  $('#connectBtn').disabled = !ok || state.connected;
}

/* ------------------------------------------------------------- connect */

async function connect() {
  const ecuOverride = $('#ecuOverride').value;
  const body = ecuOverride
    ? { ecu: ecuOverride, transport: currentTransport(), device: $('#deviceInput').value }
    : {
        model: $('#modelInput').value.trim(),
        year: parseInt($('#yearInput').value, 10),
        transport: currentTransport(),
        device: $('#deviceInput').value,
      };

  $('#connectBtn').disabled = true;
  try {
    const selection = await api('/api/select', { method: 'POST', body });
    renderNotices(selection.notices);
    if (currentTransport() !== 'simulator') {
      await api('/api/checklist', { method: 'POST', body: { accepted: $('#checklistAccept').checked } });
    }
    await api('/api/connect', { method: 'POST', body: { mode: $('#modeSelect').value } });
    toast('Connected. Read the ECU identification next.', 'ok');
    await refreshStatus();
    await loadParameters();
    await api('/api/identify').then(renderIdentity).catch(() => {});
    await refreshStatus();
    show('overview');
  } catch (err) {
    toast(err.message, 'bad');
  } finally {
    updateConnectEnabled();
  }
}

async function disconnect() {
  stopPolling();
  try { await api('/api/disconnect', { method: 'POST' }); } catch (_) {}
  state.history.clear();
  toast('Disconnected.');
  await refreshStatus();
}

/* --------------------------------------------------------------- status */

function renderNotices(notices = []) {
  $('#notices').innerHTML = notices.map((n) =>
    `<div class="notice ${esc(n.level)}">${esc(n.text)}</div>`).join('');
}

async function refreshStatus() {
  state.status = await api('/api/status');
  state.connected = state.status.connected;
  state.selection = state.status.selection;

  $('#appVersion').textContent = `v${state.status.version} · diagnostic workstation`;
  $('#modePill').textContent = state.status.mode;
  $('#modePill').className = `pill ${state.status.mode === 'simulator' ? '' : 'live'}`;

  const ecu = state.selection?.ecu;
  $('#ecuPill').textContent = ecu ? ecu.display_name : 'no ECU';

  $('#connDot').className = `conn-dot ${state.connected ? 'on' : ''}`;
  $('#connTitle').textContent = state.connected ? 'Connected' : 'Not connected';
  $('#connSub').textContent = state.connected
    ? `${ecu?.family || ''} via ${state.selection.transport}`
    : 'Pick a motorcycle in the Garage';
  $('#disconnectBtn').disabled = !state.connected;

  ['identifyBtn', 'pollBtn', 'readDtcBtn', 'scanBtn'].forEach((id) => {
    $(`#${id}`).disabled = !state.connected;
  });

  if (state.status.transports && !$('#transportList').children.length) {
    renderTransports(state.status.transports);
  }
  if (state.status.checklist && !$('#checklistItems').children.length) {
    $('#checklistItems').innerHTML = state.status.checklist
      .map((c) => `<li>${esc(c)}</li>`).join('');
  }
  if (state.selection?.notices) renderNotices(state.selection.notices);

  renderOverview();
}

/* ------------------------------------------------------------- overview */

function renderIdentity(identity) {
  if (!identity || !identity.fields) return;
  $('#identityBody').className = 'kv';
  $('#identityBody').innerHTML = Object.entries(identity.fields)
    .map(([k, v]) => `<div><span>${esc(k)}</span><b>${esc(v || '—')}</b></div>`).join('')
    + `<div class="full"><span>Raw block</span><code>${esc(identity.raw)}</code></div>`;
}

function renderOverview() {
  const d = state.status?.diagnostics;
  if (!d) return;

  if (d.identity) renderIdentity(d.identity);

  const init = d.init || {};
  $('#linkBody').className = 'kv';
  $('#linkBody').innerHTML = `
    <div><span>Transport</span><b>${esc(d.transport?.name)}</b></div>
    <div><span>Physical</span><b>${d.transport?.physical ? 'yes — real bike' : 'no — simulated'}</b></div>
    <div><span>Init method</span><b>${esc(init.method || '—')}</b></div>
    <div><span>Key bytes</span><b>${(init.key_bytes || []).map((b) => b.toString(16).toUpperCase().padStart(2, '0')).join(' ') || '—'}</b></div>
    <div><span>Mode</span><b>${esc(d.mode)}</b></div>
    <div><span>Battery observed</span><b>${d.vehicle_state?.battery_v ?? '—'} V</b></div>
    <div><span>Engine</span><b>${d.vehicle_state?.engine_running === null ? 'unknown' : (d.vehicle_state?.engine_running ? 'running' : 'stopped')}</b></div>
    <div class="full"><span>Init detail</span><code>${esc(init.detail || '—')}</code></div>`;

  const ecu = d.ecu || {};
  $('#capabilityGrid').innerHTML = (ecu.capabilities || []).map((c) => {
    const live = (ecu.effective_capabilities || []).includes(c);
    return `<div class="cap ${live ? '' : 'off'}">
      <b>${live ? '✓' : '✕'}</b>
      <div><strong>${esc(c)}</strong>
      <small>${live ? 'available on this ECU' : `gated: definition confidence is ${esc(ecu.confidence)}`}</small></div>
    </div>`;
  }).join('') || '<p class="muted">Connect to see the capability set.</p>';
}

/* ----------------------------------------------------------- live data */

async function loadParameters() {
  const data = await api('/api/parameters');
  state.parameters = data.parameters;
  state.selectedChannels = new Set(
    data.parameters.filter((p) => p.default).map((p) => p.key)
  );
  if (!state.selectedChannels.size) {
    state.parameters.slice(0, 8).forEach((p) => state.selectedChannels.add(p.key));
  }
  $('#channelList').innerHTML = state.parameters.map((p) => `
    <label class="check">
      <input type="checkbox" value="${esc(p.key)}" ${state.selectedChannels.has(p.key) ? 'checked' : ''}>
      ${esc(p.name)} <code>0x${p.local_id.toString(16).toUpperCase().padStart(2, '0')}</code>
      <span class="conf ${confidenceClass(p.confidence)}">${esc(p.confidence)}</span>
    </label>`).join('') || '<p class="muted small">No live channels are mapped for this ECU family yet. Use Discovery to characterise it.</p>';

  $$('#channelList input').forEach((cb) => (cb.onchange = () => {
    if (cb.checked) state.selectedChannels.add(cb.value);
    else state.selectedChannels.delete(cb.value);
  }));
}

function sparkline(values, min, max) {
  if (values.length < 2) return '';
  const lo = min ?? Math.min(...values);
  const hi = max ?? Math.max(...values);
  const span = (hi - lo) || 1;
  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * 100;
    const y = 30 - ((Math.min(hi, Math.max(lo, v)) - lo) / span) * 28;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return `<svg class="spark" viewBox="0 0 100 30" preserveAspectRatio="none">
    <polyline points="${points}"/></svg>`;
}

function renderLive(samples) {
  const byKey = new Map(state.parameters.map((p) => [p.key, p]));

  $('#liveGrid').innerHTML = samples.map((s) => {
    const meta = byKey.get(s.key) || {};
    if (s.error) {
      return `<article class="metric bad">
        <small>${esc(s.name)}</small><strong class="err">no answer</strong>
        <label>${esc(s.error.slice(0, 80))}</label></article>`;
    }
    const history = state.history.get(s.key) || [];
    const display = s.text || `${s.value}`;
    return `<article class="metric">
      <small>${esc(s.name)}</small>
      <strong>${esc(display)} <em>${esc(s.unit)}</em></strong>
      ${s.text ? '' : sparkline(history, meta.min, meta.max)}
      <label>0x${s.local_id.toString(16).toUpperCase().padStart(2, '0')} · ${esc(s.raw)}</label>
    </article>`;
  }).join('');

  $('#rawTable tbody').innerHTML = samples.map((s) => {
    const meta = byKey.get(s.key) || {};
    return `<tr>
      <td>${esc(s.name)}</td>
      <td><code>0x${s.local_id.toString(16).toUpperCase().padStart(2, '0')}</code></td>
      <td><code>${esc(s.raw || '—')}</code></td>
      <td>${s.error ? `<span class="err">${esc(s.error.slice(0, 60))}</span>` : `${esc(s.text || s.value)} ${esc(s.unit)}`}</td>
      <td><span class="conf ${confidenceClass(meta.confidence)}">${esc(meta.confidence || '?')}</span></td>
    </tr>`;
  }).join('');
}

async function pollOnce() {
  const keys = Array.from(state.selectedChannels);
  if (!keys.length) return;
  const started = performance.now();
  try {
    const data = await api(`/api/live?keys=${keys.join(',')}`);
    data.samples.forEach((s) => {
      if (s.value === null || s.text) return;
      const arr = state.history.get(s.key) || [];
      arr.push(s.value);
      if (arr.length > HISTORY_LEN) arr.shift();
      state.history.set(s.key, arr);
    });
    renderLive(data.samples);
    const elapsed = performance.now() - started;
    $('#pollRate').textContent =
      `${keys.length} channels · ${elapsed.toFixed(0)} ms/sweep · ${(1000 / Math.max(elapsed, 1)).toFixed(1)} Hz max`;
  } catch (err) {
    stopPolling();
    toast(`Polling stopped: ${err.message}`, 'bad');
  }
}

function startPolling() {
  if (state.polling) return;
  state.polling = true;
  $('#pollBtn').textContent = 'Stop polling';
  $('#pollBtn').classList.add('danger');
  const loop = async () => {
    if (!state.polling) return;
    await pollOnce();
    state.pollTimer = setTimeout(loop, 250);
  };
  loop();
}

function stopPolling() {
  state.polling = false;
  clearTimeout(state.pollTimer);
  $('#pollBtn').textContent = 'Start polling';
  $('#pollBtn').classList.remove('danger');
  $('#pollRate').textContent = 'idle';
}

/* -------------------------------------------------------------- faults */

function renderGate(decision, container) {
  if (!decision) { container.innerHTML = ''; return; }
  if (decision.allowed) {
    container.innerHTML = `<div class="gate ok">All preconditions satisfied.</div>`;
    return;
  }
  container.innerHTML = `<div class="gate blocked">
    <b>Blocked.</b>
    <ul>${decision.checks.filter((c) => !c.passed)
      .map((c) => `<li><code>${esc(c.name)}</code> ${esc(c.detail)}</li>`).join('')}</ul>
  </div>`;
}

async function readDtcs() {
  const data = await api('/api/dtcs');
  const list = data.dtcs;
  $('#faultBadge').textContent = list.length;
  $('#faultBadge').classList.toggle('hidden', !list.length);
  $('#dtcSummary').textContent = list.length
    ? `${list.length} code${list.length > 1 ? 's' : ''} in memory`
    : 'Fault memory is clean.';

  $('#faultList').innerHTML = list.length ? list.map((d) => `
    <article class="fault ${d.warning_indicator ? 'warn' : ''}">
      <div class="fault-code">${esc(d.code)}</div>
      <div class="fault-info">
        <strong>${esc(d.description || 'No description in the catalog for this code')}</strong>
        <small>status byte 0x${d.status_byte.toString(16).toUpperCase().padStart(2, '0')}
          · kind ${d.kind}${d.warning_indicator ? ' · warning lamp' : ''}</small>
      </div>
      <div class="fault-status ${d.status}">${esc(d.status)}</div>
    </article>`).join('')
    : `<article class="panel empty"><div class="empty-icon">✓</div>
       <h3>No diagnostic trouble codes</h3><p>The ECU reports a clean fault memory.</p></article>`;

  state.clearDecision = data.clear;
  renderGate(data.clear, $('#clearGate'));
  $('#clearDtcBtn').disabled = !data.clear.allowed;
}

async function clearDtcs() {
  const ok = await confirmDialog('Clear fault memory',
    `<p>This erases stored codes from the ECU. If the underlying fault is still
     present it will come back, but the <b>history is gone</b> — including freeze-frame
     context you may want for diagnosis.</p>
     <p class="muted">Read and export a report first if you have not.</p>`,
    'Clear fault memory');
  if (!ok) return;
  try {
    await api('/api/dtcs/clear', { method: 'POST', body: { token: state.clearDecision.token } });
    toast('Fault memory cleared.', 'ok');
    await readDtcs();
  } catch (err) { toast(err.message, 'bad'); }
}

/* ------------------------------------------------------------- service */

async function loadServiceActions() {
  if (!state.connected) {
    $('#routineList').innerHTML = '<p class="muted">Connect to an ECU first.</p>';
    $('#actuatorList').innerHTML = '';
    return;
  }
  const [routines, actuators] = await Promise.all([
    api('/api/routines'), api('/api/actuators'),
  ]);

  $('#routineList').innerHTML = routines.routines.length
    ? routines.routines.map((r) => actionCard(r, 'routine')).join('')
    : '<p class="muted">No adaptation routines are mapped for this ECU family.</p>';

  $('#actuatorList').innerHTML = actuators.actuators.length
    ? actuators.actuators.map((a) => actionCard(a, 'actuator')).join('')
    : '<p class="muted">No actuators are mapped for this ECU family.</p>';

  $$('[data-action]').forEach((btn) => (btn.onclick = () => runAction(
    btn.dataset.action, btn.dataset.key, btn.dataset.token
  )));
}

function actionCard(item, kind) {
  const d = item.decision;
  const blocked = !d.allowed;
  return `<article class="action ${blocked ? 'blocked' : ''}">
    <div class="action-head">
      <div>
        <strong>${esc(item.name)}</strong>
        <span class="conf ${confidenceClass(item.confidence)}">${esc(item.confidence)}</span>
        <code>0x${item.local_id.toString(16).toUpperCase().padStart(2, '0')}</code>
      </div>
      <button class="btn ${blocked ? '' : 'danger'}" ${blocked ? 'disabled' : ''}
        data-action="${kind}" data-key="${esc(item.key)}" data-token="${esc(d.token || '')}">
        ${kind === 'actuator' ? `Pulse ${item.max_pulse_s}s` : 'Run'}
      </button>
    </div>
    ${item.description ? `<p>${esc(item.description)}</p>` : ''}
    ${item.warning ? `<p class="action-warn">⚠ ${esc(item.warning)}</p>` : ''}
    ${item.follow_up ? `<p class="muted small"><b>Afterwards:</b> ${esc(item.follow_up)}</p>` : ''}
    ${blocked ? `<ul class="fail-list">${d.checks.filter((c) => !c.passed)
      .map((c) => `<li><code>${esc(c.name)}</code> ${esc(c.detail)}</li>`).join('')}</ul>` : ''}
  </article>`;
}

async function runAction(kind, key, token) {
  const label = kind === 'actuator' ? 'Energise output' : 'Run routine';
  const ok = await confirmDialog(`${label}: ${key}`,
    kind === 'actuator'
      ? `<p>This energises a real output on the motorcycle. Make sure nothing is
         in the way of moving parts, and that you understand what this output does.</p>
         <p class="muted">The workstation releases it automatically when the pulse expires.</p>`
      : `<p>This changes values the ECU has learned. It cannot be undone, and the
         bike may idle or run differently until it relearns.</p>`,
    label);
  if (!ok) return;

  try {
    const path = kind === 'actuator' ? '/api/actuators/pulse' : '/api/routines/run';
    const result = await api(path, { method: 'POST', body: { key, token } });
    toast(result.follow_up || `${key}: done.`, 'ok');
    setTimeout(loadServiceActions, kind === 'actuator' ? 1200 : 400);
  } catch (err) {
    toast(err.message, 'bad');
    loadServiceActions();
  }
}

/* ------------------------------------------------------------ discovery */

const parseId = (v) => {
  const n = String(v).trim().toLowerCase().startsWith('0x')
    ? parseInt(v, 16) : parseInt(v, 10);
  return Number.isFinite(n) ? Math.max(0, Math.min(255, n)) : 0;
};

async function runScan() {
  $('#scanBtn').disabled = true;
  $('#scanSummary').textContent = 'sweeping…';
  try {
    state.scan = await api('/api/discover', {
      method: 'POST',
      body: { start: parseId($('#scanStart').value), end: parseId($('#scanEnd').value) },
    });
    renderScan();
    toast(`${state.scan.answered} of ${state.scan.scanned} identifiers answered.`, 'ok');
  } catch (err) { toast(err.message, 'bad'); }
  finally { $('#scanBtn').disabled = !state.connected; }
}

function renderScan() {
  const scan = state.scan;
  if (!scan) return;
  $('#scanSummary').textContent =
    `${scan.answered} answered of ${scan.scanned} scanned (0x${scan.range[0].toString(16)}–0x${scan.range[1].toString(16)})`;
  $('#snapshotBtn').disabled = false;
  $('#exportScanBtn').disabled = false;

  const known = new Map(state.parameters.map((p) => [p.local_id, p]));
  const base = state.baseline
    ? new Map(state.baseline.identifiers.map((i) => [i.local_id, i])) : null;

  $('#scanTable tbody').innerHTML = scan.identifiers.map((i) => {
    const prior = base?.get(i.local_id);
    const changed = prior && prior.answered && i.answered && prior.raw !== i.raw;
    const param = known.get(i.local_id);
    return `<tr class="${changed ? 'changed' : ''} ${i.answered ? '' : 'dim'}">
      <td><code>${esc(i.hex_id)}</code></td>
      <td>${i.answered ? '<span class="yes">yes</span>' : `<span class="no">NRC ${i.nrc ?? '—'}</span>`}</td>
      <td>${i.length ?? '—'}</td>
      <td><code>${esc(i.raw || '')}</code></td>
      <td>${i.int_be ?? ''}</td>
      <td>${changed ? `<code>${esc(prior.raw)}</code> → <code>${esc(i.raw)}</code>` : ''}</td>
      <td>${param ? `${esc(param.name)} <span class="conf ${confidenceClass(param.confidence)}">${esc(param.confidence)}</span>` : '<span class="muted">unmapped</span>'}</td>
    </tr>`;
  }).join('');
}

function download(filename, text, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

/* ------------------------------------------------------------- sessions */

async function loadSessions() {
  const data = await api('/api/sessions');
  $('#sessionDir').textContent = `${data.sessions.length} recorded session(s)`;
  $('#sessionList').innerHTML = data.sessions.length ? data.sessions.map((s) => `
    <button class="session-row" data-name="${esc(s.name)}">
      <div><strong>${esc(s.meta.model || s.meta.ecu_family || 'session')}</strong>
        <small>${esc(s.meta.ecu_family || '')} · ${esc(s.meta.transport || '')} · ${esc(s.meta.mode || '')}</small></div>
      <div class="muted small">${(s.size / 1024).toFixed(1)} kB · ${new Date(s.modified * 1000).toLocaleString()}</div>
    </button>`).join('')
    : '<p class="muted">No sessions recorded yet. Connect to create one.</p>';

  $$('.session-row').forEach((b) => (b.onclick = () => loadSessionEvents(b.dataset.name)));
}

async function loadSessionEvents(name) {
  const data = await api(`/api/sessions/events?name=${encodeURIComponent(name)}&limit=400`);
  $('#sessionEvents').innerHTML =
    `<div class="muted small">${data.total} events, showing the last ${data.events.length}</div>`
    + data.events.map((e) => {
      const time = new Date(e.t * 1000).toLocaleTimeString();
      let body = '';
      if (e.kind === 'frame') body = `<span class="dir ${e.dir}">${e.dir}</span> <code>${esc(e.hex)}</code>`;
      else if (e.kind === 'sample') body = `${esc(e.key)} = ${esc(e.value)} ${esc(e.unit)} <code>${esc(e.raw)}</code>`;
      else if (e.kind === 'safety') body = `${e.allowed ? '<span class="yes">allowed</span>' : '<span class="no">refused</span>'} ${esc(e.operation)} — ${esc(e.reason)}`;
      else if (e.kind === 'action') body = `<b>${esc(e.name)}</b> ${esc(JSON.stringify(e.detail).slice(0, 160))}`;
      else if (e.kind === 'error') body = `<span class="no">${esc(e.where)}</span> ${esc(e.message)}`;
      else body = esc(JSON.stringify(e).slice(0, 200));
      return `<div class="log-line"><span class="log-t">${time}</span><span class="log-k">${esc(e.kind)}</span>${body}</div>`;
    }).join('');
}

/* --------------------------------------------------------------- report */

async function buildReport() {
  try {
    state.report = await api('/api/report');
    $('#reportText').textContent = state.report.text;
    $('#downloadReportBtn').disabled = false;
    $('#downloadJsonBtn').disabled = false;
    toast('Report built.', 'ok');
  } catch (err) { toast(err.message, 'bad'); }
}

/* ----------------------------------------------------------------- wire */

$('#modelInput').oninput = () => { clearTimeout($('#modelInput')._t); $('#modelInput')._t = setTimeout(resolveVehicle, 180); };
$('#yearInput').oninput = () => { clearTimeout($('#yearInput')._t); $('#yearInput')._t = setTimeout(resolveVehicle, 180); };
$('#ecuOverride').onchange = updateConnectEnabled;
$('#checklistAccept').onchange = updateConnectEnabled;
$('#connectBtn').onclick = connect;
$('#disconnectBtn').onclick = disconnect;
$('#identifyBtn').onclick = () => api('/api/identify').then((i) => { renderIdentity(i); toast('ECU identified.', 'ok'); refreshStatus(); }).catch((e) => toast(e.message, 'bad'));
$('#pollBtn').onclick = () => (state.polling ? stopPolling() : startPolling());
$('#readDtcBtn').onclick = () => readDtcs().catch((e) => toast(e.message, 'bad'));
$('#clearDtcBtn').onclick = clearDtcs;
$('#scanBtn').onclick = runScan;
$('#snapshotBtn').onclick = () => { state.baseline = state.scan; toast('Baseline kept. Change the engine state and sweep again.', 'ok'); renderScan(); };
$('#exportScanBtn').onclick = () => download(`guzzionboard-scan-${Date.now()}.json`, JSON.stringify(state.scan, null, 2), 'application/json');
$('#refreshSessionsBtn').onclick = loadSessions;
$('#buildReportBtn').onclick = buildReport;
$('#downloadReportBtn').onclick = () => download(`guzzionboard-report-${Date.now()}.txt`, state.report.text);
$('#downloadJsonBtn').onclick = () => download(`guzzionboard-report-${Date.now()}.json`, JSON.stringify(state.report.report, null, 2), 'application/json');

window.addEventListener('beforeunload', () => {
  if (state.connected) navigator.sendBeacon?.('/api/disconnect', '{}');
});

(async function boot() {
  try {
    await loadCatalog();
    await refreshStatus();
    setInterval(() => { if (!state.polling) refreshStatus().catch(() => {}); }, 5000);
  } catch (err) {
    toast(`Could not reach the local server: ${err.message}`, 'bad');
  }
})();

/* --------------------------------------------------------------- firmware */
/* ECU memory: adapter pre-flight, backup, validation and the write opt-in.
 * Reads take twenty minutes or more, so they run as a server-side job and
 * this view polls for progress rather than holding a request open. */

const fw = { caps: null, job: null, timer: null, lastImage: null };

function renderMemoryCapabilities(data) {
  fw.caps = data;
  const c = data.capabilities;
  const yesno = (v) => (v ? '<b class="ok">yes</b>' : '<b class="bad">no</b>');
  const rows = [
    ['ECU', `${esc(c.family)} <span class="muted">(${esc(c.ecu)})</span>`],
    ['Protocol', `<code>${esc(c.protocol)}</code>`],
    ['Read supported', yesno(c.read_supported)],
    ['Write supported', yesno(c.write_supported)],
    ['SecurityAccess', c.security_required
      ? (c.security_available
        ? '<b class="ok">required, provider available</b>'
        : '<b class="bad">required, no key provider</b>')
      : 'not required'],
  ];
  if (c.estimated_read_minutes) {
    rows.push(['Estimated read', `about ${c.estimated_read_minutes} minutes`]);
  }
  if (c.write_blocked_reason) rows.push(['Why not writable', esc(c.write_blocked_reason)]);
  if (c.hardware_note) rows.push(['Hardware notes', esc(c.hardware_note)]);

  $('#memCaps').innerHTML = rows
    .map(([k, v], i) => `<div${i >= 5 ? ' class="full"' : ''}>`
      + `<span>${k}</span><b>${v}</b></div>`)
    .join('');

  const select = $('#memRegion');
  select.innerHTML = Object.entries(c.regions).map(([name, r]) => {
    const size = r.size ? `${(r.size / 1024).toFixed(0)} KiB` : 'geometry unknown';
    return `<option value="${esc(name)}">${esc(name)} — ${size}</option>`;
  }).join('');

  const canRead = c.read_supported;
  $('#backupBtn').disabled = !canRead;
  $('#readBtn').disabled = !canRead;
  $('#validateBtn').disabled = false;

  // An interrupted write is the single most important thing to surface.
  const pending = Object.entries(data.checkpoints || {})
    .filter(([, v]) => v).map(([region, v]) => `
      <div class="gate-card bad">
        <h4>Unfinished write on ${esc(region)} — phase “${esc(v.phase)}”</h4>
        <ul>${(v.recovery || []).map((l) => `<li>${esc(l)}</li>`).join('')}</ul>
        ${v.backup ? `<p class="small">Backup: <code>${esc(v.backup)}</code></p>` : ''}
      </div>`);
  $('#checkpointOut').innerHTML = pending.join('');

  $('#ackInput').placeholder = data.acknowledgement || '';
  renderWriteGate();
}

function renderMemoryProgress(job) {
  fw.job = job;
  const box = $('#memProgress');
  const running = job && job.running;
  box.classList.toggle('hidden', !running && job?.state !== 'running');

  if (job?.progress) {
    const p = job.progress;
    $('#memBar').style.width = `${(p.fraction * 100).toFixed(1)}%`;
    const eta = p.eta_s > 60
      ? `${Math.round(p.eta_s / 60)} min left`
      : `${Math.round(p.eta_s)} s left`;
    $('#memProgressText').textContent =
      `${p.phase}: ${p.done.toLocaleString()} / ${p.total.toLocaleString()} bytes `
      + `(${(p.fraction * 100).toFixed(1)}%) — ${eta} — ${p.message}`;
  }

  if (job?.state === 'failed') {
    $('#memResult').innerHTML =
      `<div class="gate-card bad"><h4>${esc(job.name)} failed</h4><p>${esc(job.error)}</p></div>`;
    stopMemoryPoll();
  } else if (job?.state === 'done') {
    const r = job.result || {};
    const d = r.describe || {};
    $('#memResult').innerHTML = `
      <div class="gate-card ok">
        <h4>${esc(job.name)} complete</h4>
        ${r.verified !== undefined
          ? `<p>Two reads compared: <b>${r.verified ? 'identical' : 'DIFFERENT'}</b>
             (${r.attempts} attempts)</p>` : ''}
        ${r.path ? `<p>Saved to <code>${esc(r.path)}</code></p>` : ''}
        ${d.checksums ? `<p class="small">${d.checksums.length.toLocaleString()} bytes ·
          sum16 0x${d.checksums.sum16.toString(16).toUpperCase()} ·
          sha256 ${esc(d.checksums.sha256.slice(0, 32))}…</p>` : ''}
        ${d.hardware_strings?.length
          ? `<p class="small">Hardware strings: ${d.hardware_strings.map(esc).join(', ')}</p>` : ''}
      </div>`;
    if (r.path) $('#imagePath').value = r.path;
    stopMemoryPoll();
    loadMemory();
  }
}

function startMemoryPoll() {
  stopMemoryPoll();
  fw.timer = setInterval(async () => {
    try { renderMemoryProgress(await api('/api/memory/progress')); } catch (_) {}
  }, 1000);
}
function stopMemoryPoll() { clearInterval(fw.timer); fw.timer = null; }

async function loadMemory() {
  try {
    renderMemoryCapabilities(await api('/api/memory'));
  } catch (err) {
    $('#memCaps').innerHTML = `<p class="muted">${esc(err.message)}</p>`;
  }
  try {
    const sec = await api('/api/security');
    const entries = Object.entries(sec.providers);
    $('#securityOut').innerHTML = entries.length
      ? entries.map(([ecu, list]) => list.map((p) => `
          <div class="gate-card ${p.verified ? 'ok' : 'warn'}">
            <h4>${esc(ecu)} — ${esc(p.name)} ${p.verified ? '' : '(unverified)'}</h4>
            <p class="small">${esc(p.note || '')}</p>
          </div>`).join('')).join('')
      : '<p class="muted">No key providers registered.</p>';
    $('#securityOut').innerHTML +=
      `<p class="muted small">Plugin directory: <code>${esc(sec.plugin_dir)}</code></p>`;
  } catch (_) { /* not fatal */ }
}

async function renderWriteGate() {
  try {
    const decision = await api('/api/memory/check-write', {
      method: 'POST', body: { region: $('#memRegion').value || 'flash' },
    });
    renderGate(decision, $('#writeGate'));
    $('#writeBtn').disabled = !decision.allowed;
    $('#writeBtn').dataset.token = decision.token || '';
  } catch (err) {
    $('#writeGate').innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    $('#writeBtn').disabled = true;
  }
}

$('#adapterBtn').onclick = async () => {
  const port = encodeURIComponent($('#adapterPort').value.trim());
  const data = await api(`/api/adapter?port=${port}`);
  $('#adapterOut').textContent = data.text;
  const likely = (data.ports || []).find((p) => p.likely_adapter);
  if (likely && !$('#adapterPort').value) $('#adapterPort').value = likely.device;
};

$('#latencyBtn').onclick = async () => {
  const port = $('#adapterPort').value.trim();
  if (!port) return toast('Enter the adapter port first.', 'bad');
  const data = await api('/api/adapter/latency', { method: 'POST', body: { port, value: 1 } });
  if (data.ok) toast(`Latency timer is now ${data.latency_ms} ms.`, 'ok');
  else { toast('Could not set it from here.', 'bad'); $('#adapterOut').textContent = data.instructions; }
};

$('#backupBtn').onclick = async () => {
  const region = $('#memRegion').value;
  const minutes = fw.caps?.capabilities?.estimated_read_minutes;
  const warning = minutes
    ? `This reads ${region} twice to verify it, so expect roughly ${minutes * 2} minutes. `
      + 'Put the battery on a charger and do not let the machine sleep.'
    : 'This can take a long time. Put the battery on a charger.';
  if (!window.confirm(warning)) return;
  $('#memResult').innerHTML = '';
  await api('/api/memory/backup', { method: 'POST', body: { region } });
  startMemoryPoll();
};

$('#readBtn').onclick = async () => {
  $('#memResult').innerHTML = '';
  await api('/api/memory/read', { method: 'POST', body: { region: $('#memRegion').value } });
  startMemoryPoll();
};

$('#validateBtn').onclick = async () => {
  const path = $('#imagePath').value.trim();
  if (!path) return toast('Give the path of an image file.', 'bad');
  const result = await api('/api/memory/validate', {
    method: 'POST', body: { path, region: $('#memRegion').value },
  });
  const level = { ok: 'ok', warn: 'warn', fatal: 'bad' };
  $('#validateOut').innerHTML = `
    <div class="gate-card ${result.ok ? 'ok' : 'bad'}">
      <h4>${result.ok ? 'Image passes validation' : 'Image REJECTED'}</h4>
    </div>`
    + result.findings.map((f) => `
      <div class="gate-card ${level[f.level]}">
        <h4>${esc(f.check)}</h4><p class="small">${esc(f.detail)}</p>
      </div>`).join('');
};

$('#enableProgBtn').onclick = async () => {
  try {
    await api('/api/programming/enable', {
      method: 'POST', body: { acknowledgement: $('#ackInput').value },
    });
    toast('Programming enabled for this session.', 'warn');
  } catch (err) { toast(err.message, 'bad'); }
  loadMemory();
};

$('#disableProgBtn').onclick = async () => {
  await api('/api/programming/disable', { method: 'POST', body: {} });
  toast('Programming disabled.', 'ok');
  loadMemory();
};

$('#writeBtn').onclick = async () => {
  const path = $('#imagePath').value.trim();
  const token = $('#writeBtn').dataset.token;
  if (!path) return toast('Validate an image first.', 'bad');
  if (!window.confirm(
    'This will erase and rewrite the ECU.\n\n'
    + 'Confirm the battery is on a charger, nothing will interrupt the machine, '
    + 'and you have a verified backup you can restore.\n\nContinue?')) return;
  $('#memResult').innerHTML = '';
  await api('/api/memory/write', {
    method: 'POST', body: { path, token, region: $('#memRegion').value },
  });
  startMemoryPoll();
};

$('#memRegion').onchange = renderWriteGate;
$$('.nav').forEach((b) => {
  if (b.dataset.view === 'firmware') {
    const previous = b.onclick;
    b.onclick = () => { previous?.(); loadMemory(); };
  }
});
