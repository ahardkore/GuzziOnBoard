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
  lastSamples: [],
  lastAnalysis: null,
  derivedCatalog: null,
  sim: null,
  procedures: [],
  run: null,
  liveLog: [],
  replay: null,
  replayTimer: null,
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

const Prefs = {
  get(key, fallback = null) {
    try {
      const v = localStorage.getItem(`guzzionboard.${key}`);
      return v === null || v === '' ? fallback : v;
    } catch (_) { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(`guzzionboard.${key}`, value ?? ''); } catch (_) { /* private mode */ }
  },
};

/* ------------------------------------------------------- temperature units
 *
 * The ECUs always answer in Celsius — that is what the wire says and that is
 * what the raw bytes column keeps showing. Everything a human reads can be
 * flipped to Fahrenheit, because plenty of these bikes are ridden where the
 * thermometer in the garage is marked in °F.
 */

const CELSIUS_RE = /^\s*(°|deg\.?\s*)?C(elsius)?\s*$/i;
const isCelsiusUnit = (unit) => CELSIUS_RE.test(String(unit ?? ''));

const Temp = {
  unit() { return Prefs.get('tempUnit', 'C') === 'F' ? 'F' : 'C'; },
  setUnit(u) { Prefs.set('tempUnit', u === 'F' ? 'F' : 'C'); },

  /* The label to print next to a converted value. */
  label(unit) {
    return isCelsiusUnit(unit) && Temp.unit() === 'F' ? '°F' : unit;
  },

  /* Convert a Celsius value if (and only if) the channel is a temperature
   * and the user asked for Fahrenheit. Non-numeric values pass through. */
  value(v, unit) {
    if (!isCelsiusUnit(unit) || Temp.unit() === 'C') return v;
    const n = Number(v);
    if (!Number.isFinite(n)) return v;
    const f = n * 9 / 5 + 32;
    return Number.isInteger(n) ? Math.round(f) : +f.toFixed(1);
  },

  /* A difference in Celsius is 1.8x as large in Fahrenheit, with no offset. */
  delta(v, unit) {
    if (!isCelsiusUnit(unit) || Temp.unit() === 'C') return v;
    const n = Number(v);
    if (!Number.isFinite(n)) return v;
    return +(n * 9 / 5).toFixed(2);
  },

  /* Units built on Celsius, such as "°C/min". */
  labelFor(unit) {
    const u = String(unit ?? '');
    return Temp.unit() === 'F' && u.includes('\u00b0C') ? u.replace('\u00b0C', '\u00b0F') : u;
  },

  /* A derived value. `delta` marks a difference or a rate: Fahrenheit
   * scales it by 9/5 but must not shift it by 32. */
  valueFor(v, unit, delta) {
    const u = String(unit ?? '');
    if (Temp.unit() === 'C' || !u.includes('\u00b0C')) return v;
    const n = Number(v);
    if (!Number.isFinite(n)) return v;
    const rate = delta || u !== '\u00b0C';
    return +(rate ? n * 9 / 5 : n * 9 / 5 + 32).toFixed(1);
  },

  /* "92.4 °F" — value and unit together, both escaped. */
  text(v, unit) {
    const u = Temp.label(unit);
    return `${esc(Temp.value(v, unit))}${u ? ` ${esc(u)}` : ''}`;
  },
};

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
  procedures: ['Guided tests', 'Known state, one bounded action, the right channels, a verdict.'],
  discovery: ['Discovery', 'Read-only sweep for unmapped local identifiers.'],
  simulator: ['Simulated bike', 'Drive the simulated engine and seed faults to practise on.'],
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
  if (view === 'simulator') loadSim();
  if (view === 'procedures') loadProcedures();
}

$$('.nav').forEach((b) => (b.onclick = () => show(b.dataset.view)));

/* ------------------------------------------------------- guided tests */

async function loadProcedures() {
  let data;
  try { data = await api('/api/procedures'); }
  catch (err) { return toast(err.message, 'bad'); }
  state.procedures = data.procedures;

  $('#procedureList').innerHTML = data.procedures.map((p) => `
    <div class="action ${p.available ? '' : 'blocked'}">
      <div class="action-main">
        <strong>${esc(p.name)}</strong>
        <span class="tagline">${esc({ off: 'engine stopped', running: 'engine running', any: 'both states' }[p.engine])}</span>
        <p class="small muted">${esc(p.purpose)}</p>
        ${p.caveat ? `<p class="small warn-text">⚠ ${esc(p.caveat)}</p>` : ''}
        ${p.available ? `<p class="small muted">${p.steps.length} steps</p>`
          : `<p class="small muted">Not offered on this ECU: ${esc(p.missing.join(', '))}</p>`}
      </div>
      <button class="btn small" data-procedure="${esc(p.key)}" ${p.available ? '' : 'disabled'}>Start</button>
    </div>`).join('');

  $$('#procedureList button[data-procedure]').forEach((b) => (b.onclick = async () => {
    try {
      const out = await api('/api/procedures/start', { method: 'POST', body: { key: b.dataset.procedure } });
      renderProcedureRun(out.run);
    } catch (err) { toast(err.message, 'bad'); }
  }));

  if (data.run) renderProcedureRun(data.run);
}

function renderProcedureRun(run) {
  state.run = run;
  const box = $('#procedureRun');
  if (!run) { box.innerHTML = '<p class="muted">Pick a test to begin.</p>'; return; }

  const done = run.status !== 'running';
  const step = run.step;
  const log = run.results.map((r) => `
    <div class="log-line"><span class="log-k">${esc(r.kind)}</span>
      <b>${esc(r.title || r.step)}</b> — ${esc(r.detail)}</div>`).join('');

  let controls = '';
  if (step && !done) {
    const label = { instruct: 'Done — continue', observe: 'Start sampling',
      actuate: 'Command it', input: 'Record', verdict: 'Show the result' }[step.kind];
    const input = step.kind === 'input'
      ? (step.input_kind === 'yesno'
        ? `<div class="toolbar"><button class="btn primary" data-answer="1">Yes</button>
             <button class="btn" data-answer="0">No</button></div>`
        : `<label class="field"><span>${esc(step.input_label)} (${esc(step.input_unit)})</span>
             <input type="number" step="0.1" id="procInput"></label>
           <button class="btn primary" id="procNext">${esc(label)}</button>`)
      : `<button class="btn primary" id="procNext">${esc(label)}</button>`;
    controls = `
      <div class="gate-card">
        <h4>Step ${run.step_index + 1} of ${run.step_count} · ${esc(step.title)}</h4>
        ${step.text ? `<p class="small">${esc(step.text)}</p>` : ''}
        ${step.channels.length ? `<p class="small muted">Will sample ${esc(step.channels.join(', '))} for ${step.seconds} s.</p>` : ''}
        ${step.actuator ? `<p class="small warn-text">⚠ Commands <code>${esc(step.actuator)}</code> for ${step.pulse_s} s.</p>` : ''}
        ${input}
      </div>`;
  }

  const verdict = run.verdict ? `
    <div class="finding ${esc(run.verdict.level)}">
      <div class="finding-head"><b>${esc(run.verdict.title)}</b>
        <span class="finding-level ${esc(run.verdict.level)}">${esc(run.verdict.level)}</span></div>
      <p class="small">${esc(run.verdict.detail)}</p>
      ${run.verdict.suspects.length ? `<p class="small muted">Usual suspects: ${esc(run.verdict.suspects.join(' · '))}</p>` : ''}
    </div>` : '';

  box.innerHTML = `
    <h4>${esc(run.name)} <span class="pill ghost">${esc(run.status)}</span></h4>
    ${run.caveat ? `<p class="small warn-text">⚠ ${esc(run.caveat)}</p>` : ''}
    ${controls}${verdict}
    <div class="log-view">${log || '<span class="muted">No steps run yet.</span>'}</div>
    <div class="toolbar">
      ${done ? '<button class="btn" id="procRestart">Back to the list</button>'
             : '<button class="btn danger" id="procAbort">Abort and release outputs</button>'}
    </div>
    <p class="muted small">${esc(run.note)}</p>`;

  const advance = async (value) => {
    const button = $('#procNext') || document.activeElement;
    if (button && button.tagName === 'BUTTON') { button.disabled = true; button.textContent = 'Working…'; }
    try {
      const out = await api('/api/procedures/advance', { method: 'POST', body: { value } });
      renderProcedureRun(out.run);
      if (out.run.status === 'blocked') toast('The safety gate refused this step.', 'bad');
    } catch (err) { toast(err.message, 'bad'); renderProcedureRun(run); }
  };

  if ($('#procNext')) {
    $('#procNext').onclick = () => advance(
      step.kind === 'input' ? Number($('#procInput').value) : undefined);
  }
  $$('#procedureRun button[data-answer]').forEach((b) => (b.onclick = () => advance(b.dataset.answer === '1')));
  if ($('#procAbort')) {
    $('#procAbort').onclick = async () => {
      const out = await api('/api/procedures/abort', { method: 'POST', body: {} });
      renderProcedureRun(out.run);
    };
  }
  if ($('#procRestart')) $('#procRestart').onclick = () => renderProcedureRun(null);
}

/* ----------------------------------------------------- simulated bike
 *
 * Controls for the built-in simulator. None of this can reach a real
 * motorcycle: the endpoints behind it refuse unless the transport in use is
 * the simulator or the virtual CAN bus.
 */

async function loadSim() {
  let data;
  try { data = await api('/api/sim'); }
  catch (err) { return toast(err.message, 'bad'); }
  state.sim = data;

  $('#simPanels').classList.toggle('hidden', !data.available);
  $('#simUnavailable').classList.toggle('hidden', !!data.available);
  if (!data.available) {
    $('#simUnavailableText').textContent = data.reason;
    renderSimFaults(data.faults, false);
    return;
  }
  renderSimEngine(data);
  renderSimFaults(data.faults, true);
  renderSimComms(data.comms);
}

function renderSimEngine(data) {
  const e = data.engine;
  const btn = $('#simRunBtn');
  btn.textContent = e.running ? 'Stop engine' : 'Start engine';
  btn.classList.toggle('primary', !e.running);
  $('#simStatePill').textContent = e.running
    ? `running · ${e.rpm} rpm` : 'engine stopped';
  $('#simThrottle').value = e.throttle_pct;
  $('#simThrottleLabel').textContent = `${Math.round(e.throttle_pct)}%`;
  $('#simAmbient').value = Math.round(e.ambient_c);
  $('#simAmbientLabel').textContent = `${Temp.value(Math.round(e.ambient_c), '\u00b0C')} ${Temp.label('\u00b0C')}`;
  $('#simBattery').value = Math.round(e.battery_health * 100);
  $('#simBatteryLabel').textContent = e.battery_health >= 0.95 ? 'healthy'
    : e.battery_health >= 0.8 ? 'tired' : 'flat';
  $('#simInGear').checked = e.in_gear;
  $('#simAutoBlip').checked = e.auto_blip;
  $('#simReadout').innerHTML = `
    <div><span>Head temperature</span><b>${esc(Temp.value(e.coolant_c, '\u00b0C'))} ${esc(Temp.label('\u00b0C'))}</b></div>
    <div><span>Battery</span><b>${e.battery_v} V</b></div>
    <div><span>Road speed</span><b>${e.road_speed} km/h</b></div>
    <div><span>Lambda loop</span><b>${e.closed_loop ? 'closed' : 'open'}</b></div>
    <div><span>Running for</span><b>${Math.round(e.seconds_since_start)} s</b></div>`;
}

function renderSimFaults(faults, live) {
  $('#simFaultList').innerHTML = faults.map((f) => `
    <div class="action ${f.active ? 'armed' : ''}">
      <div class="action-main">
        <strong>${esc(f.name)}</strong>
        <p class="small muted">${esc(f.description)}</p>
        <p class="small muted">${f.dtc ? `Stores <code>${esc(f.dtc)}</code> once it matures. ` : ''}${esc(f.teaches || '')}</p>
      </div>
      <button class="btn small ${f.active ? 'danger' : ''}" data-fault="${esc(f.key)}"
        ${live ? '' : 'disabled'}>${f.active ? 'Clear fault' : 'Seed fault'}</button>
    </div>`).join('');

  $$('#simFaultList button[data-fault]').forEach((b) => (b.onclick = async () => {
    const key = b.dataset.fault;
    const active = !(state.sim.faults.find((f) => f.key === key) || {}).active;
    try {
      state.sim = await api('/api/sim/faults', { method: 'POST', body: { key, active } });
      renderSimFaults(state.sim.faults, true);
      toast(active ? 'Fault seeded — watch the live data before the code arrives.'
                   : 'Fault cleared on the bike. Any stored code stays until you erase it.',
        active ? 'warn' : 'ok');
    } catch (err) { toast(err.message, 'bad'); }
  }));
}

function renderSimComms(c) {
  $('#simDrop').value = Math.round(c.drop_rate * 100);
  $('#simDropLabel').textContent = `${Math.round(c.drop_rate * 100)}%`;
  $('#simCorrupt').value = Math.round(c.corrupt_rate * 100);
  $('#simCorruptLabel').textContent = `${Math.round(c.corrupt_rate * 100)}%`;
  $('#simPending').value = Math.round(c.pending_rate * 100);
  $('#simPendingLabel').textContent = `${Math.round(c.pending_rate * 100)}%`;
  $('#simLatency').value = Math.round(c.extra_latency * 1000);
  $('#simLatencyLabel').textContent = `${Math.round(c.extra_latency * 1000)} ms`;
}

async function simEngine(body) {
  try {
    state.sim = await api('/api/sim/engine', { method: 'POST', body });
    renderSimEngine(state.sim);
  } catch (err) { toast(err.message, 'bad'); }
}

async function simComms(body) {
  try {
    state.sim = await api('/api/sim/comms', { method: 'POST', body });
    renderSimComms(state.sim.comms);
  } catch (err) { toast(err.message, 'bad'); }
}

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

  const make = $('#makeSelect');
  make.innerHTML = state.catalog.makes
    .map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
  const savedMake = Prefs.get('make');
  make.value = (savedMake && state.catalog.makes.includes(savedMake))
    ? savedMake
    : (state.catalog.makes.includes('Moto Guzzi') ? 'Moto Guzzi' : state.catalog.makes[0]);
  make.onchange = () => { Prefs.set('make', make.value); fillModels(); updateConnectEnabled(); };
  fillModels();

  // last time's bike, if it still exists in the catalog
  const savedModel = Prefs.get('model');
  const savedYear = Prefs.get('year');
  if (savedModel && [...$('#modelSelect').options].some((o) => o.value === savedModel)) {
    $('#modelSelect').value = savedModel;
    fillYears();
    if (savedYear && [...$('#yearSelect').options].some((o) => o.value === savedYear)) {
      $('#yearSelect').value = savedYear;
      resolveVehicle();
    }
  }

  // everything else the operator should not have to retype
  [['device', '#deviceInput'], ['mode', '#modeSelect'], ['initMethod', '#initMethod'],
   ['image', '#imagePath'], ['mapsImage', '#mapsImagePath'],
   ['mapsDiff', '#mapsDiffPath'], ['canTx', '#canTxId'],
   ['canRx', '#canRxId']].forEach(([k, sel]) => {
    const saved = Prefs.get(k);
    if (saved && $(sel)) $(sel).value = saved;
  });

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

function vehiclesOf(make) {
  return (state.catalog.vehicles || []).filter((v) => v.make === make);
}

function fillModels() {
  const make = $('#makeSelect').value || (state.catalog.makes || ['Moto Guzzi'])[0];
  const models = [...new Set(vehiclesOf(make).map((v) => v.model))].sort();
  $('#modelSelect').innerHTML = '<option value="">— pick a model —</option>'
    + models.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
  $('#modelSelect').onchange = () => {
    Prefs.set('model', $('#modelSelect').value);
    fillYears(); resolveVehicle();
  };
  fillYears();
}

function fillYears() {
  const make = $('#makeSelect').value;
  const model = $('#modelSelect').value;
  const entries = vehiclesOf(make).filter((v) => v.model === model);
  const years = new Set();
  entries.forEach((v) => {
    const end = Math.min(v.year_to || new Date().getFullYear(), new Date().getFullYear() + 1);
    for (let y = v.year_from; y <= end; y++) years.add(y);
  });
  const sorted = [...years].sort((a, b) => b - a);
  $('#yearSelect').innerHTML = '<option value="">— pick a year —</option>'
    + sorted.map((y) => `<option value="${y}">${y}</option>`).join('');
}

async function resolveVehicle() {
  const make = $('#makeSelect').value;
  const model = $('#modelSelect').value;
  const year = parseInt($('#yearSelect').value, 10);
  const box = $('#resolveResult');
  if (!model || !year) { box.innerHTML = ''; state.resolved = null; updateConnectEnabled(); return; }

  const data = await api(`/api/catalog/resolve?make=${encodeURIComponent(make)}&model=${encodeURIComponent(model)}&year=${year}`);
  if (!data.matches.length) {
    box.innerHTML = `<div class="resolve-card bad">No catalog entry for <b>${esc(make)} ${esc(model)} ${year}</b>.
      Pick another year, or use the ECU override below if you know the family.</div>`;
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
  const saved = Prefs.get('transport');
  if (saved) {
    const radio = document.querySelector(`input[name=transport][value="${CSS.escape(saved)}"]`);
    if (radio) radio.checked = true;
  }
  onTransportChange();
}

function currentTransport() {
  const checked = $('input[name=transport]:checked');
  return checked ? checked.value : 'simulator';
}

function onTransportChange() {
  const kind = currentTransport();
  const physical = !['simulator', 'cansim'].includes(kind);
  Prefs.set('transport', kind);
  $('#deviceField').hidden = !physical;
  $('#checklistBox').hidden = !physical;
  $('#klineFields').hidden = kind !== 'kline';
  $('#canFields').hidden = !['can', 'cansim'].includes(kind);
  $('#deviceInput').placeholder = kind === 'can' ? 'can0' : '/dev/ttyUSB0';
  if (['can', 'cansim'].includes(kind) && !$('#canTxId').value) {
    const spec = (state.resolved && state.resolved.ecu_detail && state.resolved.ecu_detail.can) || {};
    $('#canTxId').value = spec.tx_id !== undefined ? `0x${spec.tx_id.toString(16).toUpperCase()}` : '0x7E0';
    $('#canRxId').value = spec.rx_id !== undefined ? `0x${spec.rx_id.toString(16).toUpperCase()}` : '0x7E8';
  }
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
        make: $('#makeSelect').value,
        model: $('#modelSelect').value,
        year: parseInt($('#yearSelect').value, 10),
        transport: currentTransport(),
        device: $('#deviceInput').value,
      };
  if (['can', 'cansim'].includes(currentTransport())) {
    body.can_tx_id = $('#canTxId').value.trim();
    body.can_rx_id = $('#canRxId').value.trim();
  }

  $('#connectBtn').disabled = true;
  try {
    const selection = await api('/api/select', { method: 'POST', body });
    renderNotices(selection.notices);
    if (currentTransport() !== 'simulator') {
      await api('/api/checklist', { method: 'POST', body: { accepted: $('#checklistAccept').checked } });
    }
    const initMethod = currentTransport() === 'kline' ? $('#initMethod').value : '';
    Prefs.set('initMethod', initMethod);
    await api('/api/connect', {
      method: 'POST',
      body: { mode: $('#modeSelect').value, init_method: initMethod || undefined },
    });
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
  const simulated = ['simulator', 'cansim'].includes(state.selection?.transport);
  $('#connSub').textContent = state.connected
    ? (simulated
      ? `🧪 simulated ${ecu?.family || 'ECU'} — everything works, nothing is real`
      : `${ecu?.family || ''} via ${state.selection.transport}`)
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
    <div><span>Protocol</span><b>${esc(init.protocol || '—')}</b></div>
    <div><span>Key bytes</span><b>${(init.key_bytes || []).map((b) => b.toString(16).toUpperCase().padStart(2, '0')).join(' ') || '—'}</b></div>
    ${(init.attempts || []).length ? `<div class="full"><span>Handshake attempts</span><code>${esc(init.attempts.join(' · '))}</code></div>` : ''}
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
  await loadDerivedCatalog();
  renderChannelPicker();
}

async function loadDerivedCatalog() {
  if (state.derivedCatalog) return;
  try {
    state.derivedCatalog = (await api('/api/derived')).channels;
  } catch (_) { state.derivedCatalog = []; }
}

function renderChannelPicker() {
  $('#channelList').innerHTML = state.parameters.map((p) => `
    <label class="check">
      <input type="checkbox" value="${esc(p.key)}" ${state.selectedChannels.has(p.key) ? 'checked' : ''}>
      ${esc(p.name)} <code>0x${p.local_id.toString(16).toUpperCase().padStart(2, '0')}</code>
      <span class="conf ${confidenceClass(p.confidence)}">${esc(p.confidence)}</span>
    </label>`).join('') || '<p class="muted small">No live channels are mapped for this ECU family yet. Use Discovery to characterise it.</p>';

  $$('#channelList input').forEach((cb) => (cb.onchange = () => {
    if (cb.checked) state.selectedChannels.add(cb.value);
    else state.selectedChannels.delete(cb.value);
    renderDerivedGaps();
  }));
  renderDerivedGaps();
}

/* ------------------------------------------------- derived and findings
 *
 * The server computes both; this only draws them. Everything here is
 * visually separated from the metric grid above, because a value the
 * workstation worked out is not a value the ECU reported.
 */

function renderAnalysis(derived, findings) {
  state.lastAnalysis = { derived, findings };
  $('#derivedGrid').innerHTML = (derived || []).map((c) => {
    const unit = Temp.labelFor(c.unit);
    const value = Temp.valueFor(c.value, c.unit, c.delta);
    return `<article class="metric derived" title="${esc(c.note)}">
      <small>${esc(c.name)}</small>
      <strong>${esc(value)} <em>${esc(unit)}</em></strong>
      <label><span class="conf ${confidenceClass(c.confidence)}">${esc(c.confidence)}</span>
        ${esc(c.sources.join(' + '))}</label>
    </article>`;
  }).join('') || '<p class="muted">Nothing to derive from the channels being polled.</p>';

  const box = $('#findingList');
  if (!findings || !findings.length) {
    box.innerHTML = '<p class="muted">Every check that could run on the current '
      + 'channels is happy. That is not a clean bill of health — it is the '
      + 'absence of the specific problems these rules know about.</p>';
    return;
  }
  box.innerHTML = findings.map((f) => `
    <div class="finding ${esc(f.level)}">
      <div class="finding-head"><b>${esc(f.title)}</b>
        <span class="finding-level ${esc(f.level)}">${esc(f.level)}</span></div>
      <p class="small">${esc(f.detail)}</p>
      ${f.suspects.length ? `<p class="small muted">Usual suspects: ${esc(f.suspects.join(' · '))}</p>` : ''}
      <p class="small muted">Reacting to ${Object.entries(f.evidence)
        .map(([k, v]) => `<code>${esc(k)}</code> ${esc(v)}`).join(', ')}</p>
    </div>`).join('');
}

/* Which derived channels cannot be computed because their inputs are not
 * being polled — with one click to start polling them. */
function renderDerivedGaps() {
  const known = new Set(state.parameters.map((p) => p.key));
  const gaps = (state.derivedCatalog || []).map((c) => ({
    ...c,
    missing: c.sources.filter((k) => known.has(k) && !state.selectedChannels.has(k)),
    unmapped: c.sources.filter((k) => !known.has(k)),
  })).filter((c) => !c.unmapped.length && c.missing.length);

  const el = $('#derivedMissing');
  if (!el) return;
  if (!gaps.length) { el.innerHTML = ''; return; }
  const needed = Array.from(new Set(gaps.flatMap((c) => c.missing)));
  el.innerHTML = `<p class="muted small">Not computed yet: ${gaps
    .map((c) => `<b>${esc(c.name)}</b> (needs ${esc(c.missing.join(', '))})`).join('; ')}
    <button class="btn small" id="addDerivedChannels">Poll the ${needed.length} missing channel${needed.length > 1 ? 's' : ''}</button></p>`;
  $('#addDerivedChannels').onclick = () => {
    needed.forEach((k) => state.selectedChannels.add(k));
    renderChannelPicker();
    toast('Added the channels those derived values need.', 'ok');
  };
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
  state.lastSamples = samples;
  const byKey = new Map(state.parameters.map((p) => [p.key, p]));

  $('#liveGrid').innerHTML = samples.map((s) => {
    const meta = byKey.get(s.key) || {};
    if (s.error) {
      return `<article class="metric bad">
        <small>${esc(s.name)}</small><strong class="err">no answer</strong>
        <label>${esc(s.error.slice(0, 80))}</label></article>`;
    }
    const history = state.history.get(s.key) || [];
    const display = s.text || `${Temp.value(s.value, s.unit)}`;
    const span = isCelsiusUnit(s.unit)
      ? [Temp.value(meta.min, s.unit), Temp.value(meta.max, s.unit)]
      : [meta.min, meta.max];
    const trace = isCelsiusUnit(s.unit)
      ? history.map((v) => Temp.value(v, s.unit))
      : history;
    return `<article class="metric">
      <small>${esc(s.name)}</small>
      <strong>${esc(display)} <em>${esc(Temp.label(s.unit))}</em></strong>
      ${s.text ? '' : sparkline(trace, span[0], span[1])}
      <label>0x${s.local_id.toString(16).toUpperCase().padStart(2, '0')} · ${esc(s.raw)}</label>
    </article>`;
  }).join('');

  $('#rawTable tbody').innerHTML = samples.map((s) => {
    const meta = byKey.get(s.key) || {};
    return `<tr>
      <td>${esc(s.name)}</td>
      <td><code>0x${s.local_id.toString(16).toUpperCase().padStart(2, '0')}</code></td>
      <td><code>${esc(s.raw || '—')}</code></td>
      <td>${s.error ? `<span class="err">${esc(s.error.slice(0, 60))}</span>` : `${s.text ? esc(s.text) : Temp.text(s.value, s.unit)}`}</td>
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
    state.liveLog.push({
      t: data.at || Date.now() / 1000,
      values: Object.fromEntries(data.samples.map((s) => [s.key, s])),
    });
    if (state.liveLog.length > 5000) state.liveLog.shift();
    $('#exportLiveBtn').disabled = false;
    renderLive(data.samples);
    renderAnalysis(data.derived, data.findings);
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

  const context = Object.entries(data.context || {});
  const contextHtml = context.length
    ? `<div class="fault-context"><span class="muted small">Context observed at read time
        ${data.context_note ? `<span title="${esc(data.context_note)}">(?)</span>` : ''}:</span>
       ${context.map(([k, c]) =>
         `<span class="tag">${esc(c.name)} <b>${esc(Temp.value(c.value, c.unit))}${c.unit ? ' ' + esc(Temp.label(c.unit)) : ''}</b></span>`
       ).join(' ')}</div>`
    : '';

  $('#faultList').innerHTML = contextHtml + (list.length ? list.map((d) => `
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
       <h3>No diagnostic trouble codes</h3><p>The ECU reports a clean fault memory.</p></article>`);

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
  state.sessions = data.sessions;
  fillCompareSelects();
  $('#sessionDir').textContent = `${data.sessions.length} recorded session(s)`;
  $('#sessionList').innerHTML = data.sessions.length ? data.sessions.map((s) => `
    <div class="session-item">
      <button class="session-row" data-name="${esc(s.name)}">
        <div><strong>${esc(s.meta.model || s.meta.ecu_family || 'session')}</strong>
          <small>${esc(s.meta.ecu_family || '')} · ${esc(s.meta.transport || '')} · ${esc(s.meta.mode || '')}</small></div>
        <div class="muted small">${(s.size / 1024).toFixed(1)} kB · ${new Date(s.modified * 1000).toLocaleString()}</div>
      </button>
      <div class="toolbar">
        <button class="btn small" data-csv="${esc(s.name)}">Export CSV</button>
        <button class="btn small" data-replay="${esc(s.name)}">Replay</button>
      </div>
    </div>`).join('')
    : '<p class="muted">No sessions recorded yet. Connect to create one.</p>';

  $$('.session-row').forEach((b) => (b.onclick = () => loadSessionEvents(b.dataset.name)));
  $$('#sessionList button[data-csv]').forEach((b) => (b.onclick = () => exportSessionCsv(b.dataset.csv)));
  $$('#sessionList button[data-replay]').forEach((b) => (b.onclick = () => loadReplay(b.dataset.replay)));
}

async function loadSessionEvents(name) {
  const data = await api(`/api/sessions/events?name=${encodeURIComponent(name)}&limit=400`);
  $('#sessionEvents').innerHTML =
    `<div class="muted small">${data.total} events, showing the last ${data.events.length}</div>`
    + data.events.map((e) => {
      const time = new Date(e.t * 1000).toLocaleTimeString();
      let body = '';
      if (e.kind === 'frame') body = `<span class="dir ${e.dir}">${e.dir}</span> <code>${esc(e.hex)}</code>`;
      else if (e.kind === 'sample') body = `${esc(e.key)} = ${Temp.text(e.value, e.unit)} <code>${esc(e.raw)}</code>`;
      else if (e.kind === 'safety') body = `${e.allowed ? '<span class="yes">allowed</span>' : '<span class="no">refused</span>'} ${esc(e.operation)} — ${esc(e.reason)}`;
      else if (e.kind === 'action') body = `<b>${esc(e.name)}</b> ${esc(JSON.stringify(e.detail).slice(0, 160))}`;
      else if (e.kind === 'error') body = `<span class="no">${esc(e.where)}</span> ${esc(e.message)}`;
      else body = esc(JSON.stringify(e).slice(0, 200));
      return `<div class="log-line"><span class="log-t">${time}</span><span class="log-k">${esc(e.kind)}</span>${body}</div>`;
    }).join('');
}

/* ------------------------------------------------------- export, replay */

async function exportSessionCsv(name) {
  try {
    const data = await api(`/api/sessions/export?name=${encodeURIComponent(name)}&format=csv`);
    if (!data.rows) return toast('That session has no samples in it to export.', 'warn');
    download(data.filename, data.content, 'text/csv');
    toast(`${data.rows} sweeps exported.`, 'ok');
  } catch (err) { toast(err.message, 'bad'); }
}

/* Everything polled since the page was opened, as CSV. Same shape as the
 * server-side export, so the two files can sit in the same spreadsheet. */
function exportLiveCsv() {
  const log = state.liveLog;
  if (!log.length) return toast('Nothing polled yet.', 'warn');
  const keys = [];
  log.forEach((row) => Object.keys(row.values).forEach((k) => {
    if (!keys.includes(k)) keys.push(k);
  }));
  const units = {};
  log.forEach((row) => Object.entries(row.values).forEach(([k, v]) => {
    if (units[k] === undefined) units[k] = v.unit || '';
  }));
  const t0 = log[0].t;
  const lines = [
    ['time_unix', 'elapsed_s', ...keys, ...keys.map((k) => `${k}_raw`)].join(','),
    ['', 's', ...keys.map((k) => units[k]), ...keys.map(() => 'bytes')].join(','),
    ...log.map((row) => [
      row.t.toFixed(4), (row.t - t0).toFixed(3),
      ...keys.map((k) => (row.values[k]?.value ?? '')),
      ...keys.map((k) => (row.values[k]?.raw ?? '')),
    ].join(',')),
  ];
  download(`guzzionboard-live-${Date.now()}.csv`, lines.join('\n'), 'text/csv');
  toast(`${log.length} sweeps exported.`, 'ok');
}

async function loadReplay(name) {
  try {
    state.replay = await api(`/api/sessions/replay?name=${encodeURIComponent(name)}`);
  } catch (err) { return toast(err.message, 'bad'); }
  const frames = state.replay.frames;
  if (!frames.length) {
    $('#replayClock').textContent = 'this session recorded no samples';
    return toast('That session has no samples to replay.', 'warn');
  }
  $('#replayScrub').max = String(frames.length - 1);
  $('#replayScrub').value = '0';
  $('#replayScrub').disabled = false;
  $('#replayPlayBtn').disabled = false;
  showReplayFrame(0);
  toast(`${frames.length} sweeps over ${state.replay.duration_s} s.`, 'ok');
}

function showReplayFrame(index) {
  const frame = state.replay?.frames?.[index];
  if (!frame) return;
  $('#replayClock').textContent =
    `${frame.elapsed.toFixed(1)} s of ${state.replay.duration_s} s · sweep ${index + 1}/${state.replay.frames.length}`;

  const measured = Object.values(frame.values).map((v) => `
    <article class="metric">
      <small>${esc(v.key)}</small>
      <strong>${Temp.text(v.value, v.unit)}</strong>
      <label>${esc(v.raw || '—')}</label>
    </article>`).join('');
  const derived = frame.derived.map((c) => `
    <article class="metric derived">
      <small>${esc(c.name)}</small>
      <strong>${esc(Temp.valueFor(c.value, c.unit, c.delta))} <em>${esc(Temp.labelFor(c.unit))}</em></strong>
      <label>${esc(c.sources.join(' + '))}</label>
    </article>`).join('');
  $('#replayGrid').innerHTML = measured + derived;

  $('#replayFindings').innerHTML = frame.findings.map((f) => `
    <div class="finding ${esc(f.level)}">
      <div class="finding-head"><b>${esc(f.title)}</b>
        <span class="finding-level ${esc(f.level)}">${esc(f.level)}</span></div>
      <p class="small">${esc(f.detail)}</p>
    </div>`).join('');
}

function toggleReplayPlay() {
  if (state.replayTimer) {
    clearInterval(state.replayTimer);
    state.replayTimer = null;
    $('#replayPlayBtn').textContent = 'Play';
    return;
  }
  $('#replayPlayBtn').textContent = 'Pause';
  state.replayTimer = setInterval(() => {
    const scrub = $('#replayScrub');
    const next = Number(scrub.value) + 1;
    if (next > Number(scrub.max)) return toggleReplayPlay();
    scrub.value = String(next);
    showReplayFrame(next);
  }, 300);
}

/* --------------------------------------------------------------- report */

async function buildReport() {
  try {
    state.report = await api(`/api/report?temp_unit=${Temp.unit()}`);
    $('#reportText').textContent = state.report.text;
    $('#downloadReportBtn').disabled = false;
    $('#downloadJsonBtn').disabled = false;
    toast('Report built.', 'ok');
  } catch (err) { toast(err.message, 'bad'); }
}

/* ----------------------------------------------------------------- wire */

$('#yearSelect').onchange = resolveVehicle;
$('#printBtn').onclick = () => window.print();
$('#tempUnit').onchange = (e) => {
  Temp.setUnit(e.target.value);
  if (state.lastSamples.length) renderLive(state.lastSamples);
  if (state.lastAnalysis) renderAnalysis(state.lastAnalysis.derived, state.lastAnalysis.findings);
  toast(`Temperatures shown in ${Temp.unit() === 'F' ? 'Fahrenheit' : 'Celsius'}.`, 'ok');
};
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
$('#simRunBtn').onclick = () => simEngine({ running: !(state.sim?.engine?.running) });
$('#simWarmBtn').onclick = () => simEngine({ advance_s: 300 });
$('#simThrottle').oninput = (e) => {
  $('#simThrottleLabel').textContent = `${e.target.value}%`;
  simEngine({ throttle_pct: Number(e.target.value) });
};
$('#simAmbient').oninput = (e) => simEngine({ ambient_c: Number(e.target.value) });
$('#simBattery').oninput = (e) => simEngine({ battery_health: Number(e.target.value) / 100 });
$('#simInGear').onchange = (e) => simEngine({ in_gear: e.target.checked });
$('#simAutoBlip').onchange = (e) => simEngine({ auto_blip: e.target.checked });
$('#simDrop').oninput = (e) => simComms({ drop_rate: Number(e.target.value) / 100 });
$('#simCorrupt').oninput = (e) => simComms({ corrupt_rate: Number(e.target.value) / 100 });
$('#simPending').oninput = (e) => simComms({ pending_rate: Number(e.target.value) / 100 });
$('#simLatency').oninput = (e) => simComms({ extra_latency: Number(e.target.value) / 1000 });
$('#exportLiveBtn').onclick = exportLiveCsv;
$('#replayScrub').oninput = (e) => showReplayFrame(Number(e.target.value));
$('#replayPlayBtn').onclick = toggleReplayPlay;
$('#refreshSessionsBtn').onclick = loadSessions;
$('#buildReportBtn').onclick = buildReport;
$('#downloadReportBtn').onclick = () => download(`guzzionboard-report-${Date.now()}.txt`, state.report.text);
$('#downloadJsonBtn').onclick = () => download(`guzzionboard-report-${Date.now()}.json`, JSON.stringify(state.report.report, null, 2), 'application/json');

window.addEventListener('beforeunload', () => {
  if (state.connected) navigator.sendBeacon?.('/api/disconnect', '{}');
});

(async function boot() {
  try {
    $('#tempUnit').value = Temp.unit();
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
    ['Write supported', c.simulated
      ? (c.write_supported ? '<b class="ok">yes <span class="muted">(sim&nbsp;)</span></b>' : yesno(false))
      : yesno(c.write_supported)],
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

  $('#memCapsNote').innerHTML = c.simulation_note
    ? `<p class="tip"><b>Simulated ECU.</b> ${esc(c.simulation_note
        .replace(/^Simulated ECU:\s*/, ''))}</p>`
    : '';

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
    const chk = $('#unverifiedKeysChk');
    if (chk) chk.checked = !!sec.unverified_keys_accepted;
  } catch (_) { /* not fatal */ }
}

const unverifiedKeysChk = $('#unverifiedKeysChk');
if (unverifiedKeysChk) {
  unverifiedKeysChk.onchange = async (ev) => {
    try {
      const res = await api('/api/security/unverified', {
        method: 'POST', body: { accept: ev.target.checked },
      });
      toast(
        res.allow_unverified_keys
          ? 'Unverified key providers accepted for this session (audited).'
          : 'Unverified key providers refused; verified providers only.',
        res.allow_unverified_keys ? 'warn' : 'ok');
    } catch (err) {
      ev.target.checked = !ev.target.checked;
      toast(err.message, 'bad');
    }
    loadMemory();
  };
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
  let out = data.text;
  const driver = data.report && data.report.driver;
  if (driver && driver.hint) {
    out += `\n\n[driver · ${driver.os || 'host'}] ${driver.hint}`;
    out += driver.bundle_available
      ? `\n        mirrored bundle: ${driver.bundle_path}` : '';
  }
  $('#adapterOut').textContent = out;
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
    const keyChk = $('#unverifiedKeysChk');
    await api('/api/programming/enable', {
      method: 'POST',
      body: {
        acknowledgement: $('#ackInput').value,
        allow_unverified_keys: !!(keyChk && keyChk.checked),
      },
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

/* ------------------------------------------------------------------ maps */
/* TunerPro XDF definitions turn a raw dump into named tables. The XDFs are
 * third-party files (the GuzziDiag ones live at von-der-salierburg.de) and
 * live in ~/.guzzionboard/xdfs — nothing ships with the app. This view is
 * strictly read-only: it renders and diffs, it never writes. */

const maps = { xdfs: [], lastDoc: null };

const fmtValue = (v) => (Number.isInteger(v) ? String(v) : String(+v.toPrecision(4)));

async function loadXdfs() {
  try {
    const data = await api('/api/maps');
    maps.xdfs = data.xdfs || [];
    $('#mapsXdfDir').textContent = maps.xdfs.length
      ? `${maps.xdfs.length} definition file(s) in ${data.directory}`
      : `none in ${data.directory} yet`;
    $('#xdfSelect').innerHTML = maps.xdfs.length
      ? maps.xdfs.map((x) => `<option value="${esc(x.title)}">`
          + `${esc(x.title)} — ${x.tables} tables, ${x.constants} constants</option>`).join('')
      : '<option value="">— none found —</option>';
    $('#xdfSelect').onchange = () => Prefs.set('xdf', $('#xdfSelect').value);
    suggestXdf();
  } catch (err) {
    toast(`Could not list XDFs: ${err.message}`, 'bad');
  }
}

function suggestXdf() {
  const select = $('#xdfSelect');
  if (!select.options.length) return;
  const last = Prefs.get('xdf');
  if (last && [...select.options].some((o) => o.value === last)) {
    select.value = last;
    return;
  }
  // the selected ECU family usually names itself in the XDF title:
  // "IAW 5AM / 5AM2" -> any definition whose title mentions 5AM
  const family = (state.status?.vehicle?.ecu?.family || '').toUpperCase();
  const tokens = family.match(/(5AM2|5AM|16M|15M|59M|7SM|5SM|5DM|11MP|MIU|P7|P8)/g) || [];
  for (const token of tokens) {
    const hit = [...select.options].find((o) => o.value.toUpperCase().includes(token));
    if (hit) { select.value = hit.value; Prefs.set('xdf', hit.value); return; }
  }
}

function mapsTableHtml(t) {
  const head = `<tr><th>${esc(t.units || '')}</th>`
    + t.x.map((x) => `<th>${esc(x)}</th>`).join('') + '</tr>';
  const body = t.values.map((row, r) => `<tr><th>${esc(t.y[r] ?? '')}</th>`
    + row.map((v) => `<td>${esc(fmtValue(v))}</td>`).join('') + '</tr>').join('');
  return `<div class="table-wrap"><table class="data"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
}

function mapsNotices(render) {
  const out = [];
  const base = render.address_base ? (
    `Rendered with address base 0x${render.address_base.toString(16)} — `
    + 'the image is a region read, the XDF addresses the full device.') : null;
  if (base) out.push(`<p class="muted small">${esc(base)}</p>`);
  if (render.unsupported?.length) {
    out.push(`<div class="gate-card warn"><h4>${render.unsupported.length} item(s) not interpreted</h4>`
      + render.unsupported.map((u) => `<p class="small">${esc(u.title || 'untitled')}: ${esc(u.reason)}</p>`).join('')
      + '</div>');
  }
  if (render.errors?.length) {
    out.push(`<div class="gate-card bad"><h4>${render.errors.length} item(s) outside this image</h4>`
      + render.errors.map((e) => `<p class="small">${esc(e.title)}: ${esc(e.reason)}</p>`).join('')
      + '</div>');
  }
  return out.join('');
}

const MAPS_DOC_CSS = `body{font-family:Georgia,serif;margin:24px;color:#111}
h1{font-size:20px}h2{font-size:15px;margin:20px 0 4px}
table{border-collapse:collapse;margin:6px 0 18px}
th,td{border:1px solid #999;padding:3px 8px;font-size:12px;text-align:center}
thead th,tbody th{background:#eee}
.meta{color:#555;font-size:12px}
.cell-note{color:#333;font-size:13px;margin:2px 0 14px;padding-left:8px;border-left:3px solid #999}`;

function mapsTablesHtml(tables) {
  return tables.map((t) => `
    <h2>${esc(t.title)} <small>(${esc(t.category || '')} · ${esc(t.units || '')})</small></h2>
    <table><thead><tr><th>${esc(t.units || '')} \ ${esc(t.x_units || '')}</th>`
    + t.x.map((x) => `<th>${esc(x)}</th>`).join('') + '</tr></thead>'
    + '<tbody>' + t.values.map((row, r) => `<tr><th>${esc(t.y[r] ?? '')}</th>`
      + row.map((v) => `<td>${esc(fmtValue(v))}</td>`).join('') + '</tr>').join('') + '</tbody></table>').join('');
}

function mapsDoc(title, bodyHtml) {
  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)}</title>
<style>${MAPS_DOC_CSS}</style></head><body><h1>${esc(title)}</h1>${bodyHtml}</body></html>`;
}

function mapsResultToolbar() {
  return `<div class="toolbar no-export">
    <button class="btn small" data-act="save-html">Save as HTML</button>
    <button class="btn small" data-act="print">Print / PDF</button>
    <span class="muted small">Saved documents are standalone: tables, units and values, nothing else.</span>
  </div>`;
}

function wireMapsToolbar() {
  document.querySelectorAll('[data-act="save-html"]').forEach((btn) => {
    btn.onclick = () => {
      if (!maps.lastDoc) return;
      download(`guzzionboard-maps-${Date.now()}.html`,
        maps.lastDoc.html, 'text/html');
    };
  });
  document.querySelectorAll('[data-act="print"]').forEach((btn) => {
    btn.onclick = () => window.print();
  });
}

function renderMapsResult(render) {
  const meta = render.xdf || {};
  maps.lastDoc = {
    title: `${meta.title || 'Maps'} — rendered tables`,
    html: mapsDoc(`${meta.title || 'Maps'} — rendered tables`,
      `<p class="meta">${esc(render.image ? '' : '')}${render.tables.length} table(s), `
      + `${render.constants.length} constant(s) · image ${(render.image_size / 1024).toFixed(0)} KiB`
      + (render.address_base ? ` · address base 0x${render.address_base.toString(16)} (region read)` : '')
      + `</p>`
      + mapsTablesHtml(render.tables)
      + (render.constants.length ? `<h2>Constants</h2><table><thead><tr><th>Constant</th><th>Value</th><th>Units</th></tr></thead><tbody>`
        + render.constants.map((c) => `<tr><td>${esc(c.title)}</td><td>${esc(fmtValue(c.value))}</td><td>${esc(c.units)}</td></tr>`).join('')
        + '</tbody></table>' : '')),
  };
  const constants = render.constants?.length ? `
    <details><summary>Constants (${render.constants.length})</summary>
      <div class="table-wrap"><table class="data">
        <thead><tr><th>Constant</th><th>Category</th><th>Value</th><th>Address</th></tr></thead>
        <tbody>${render.constants.map((c) => `
          <tr><td>${esc(c.title)}</td><td>${esc(c.category)}</td>
              <td><b>${esc(fmtValue(c.value))}</b> ${esc(c.units)}</td>
              <td><code>${esc(c.address)}</code></td></tr>`).join('')}
        </tbody></table></div></details>` : '';
  $('#mapsOut').innerHTML = mapsResultToolbar() + `
    <div class="gate-card ok">
      <h4>${esc(meta.title || 'Definitions')}</h4>
      <p class="small">${esc(meta.description || '')}</p>
      <p class="muted small">${render.tables.length} table(s) · ${render.constants.length} constant(s)
        · image ${(render.image_size / 1024).toFixed(0)} KiB</p>
    </div>`
    + mapsNotices(render)
    + render.tables.map((t, i) => `
      <details ${i === 0 ? 'open' : ''}>
        <summary>${esc(t.title)}
          <span class="muted small"> — ${esc(t.category)} · ${esc(t.units)} · ${t.rows}×${t.cols} · <code>${esc(t.address)}</code></span>
        </summary>${mapsTableHtml(t)}</details>`).join('')
    + constants;
  wireMapsToolbar();
}

$('#mapsRefreshBtn').onclick = loadXdfs;

$('#mapsRenderBtn').onclick = async () => {
  const path = $('#mapsImagePath').value.trim() || $('#imagePath').value.trim();
  const xdf = $('#xdfSelect').value;
  if (!xdf) return toast('No XDF definitions found — drop .xdf files into ~/.guzzionboard/xdfs/.', 'bad');
  if (!path) return toast('Give the path of an image to render.', 'bad');
  if (!path.startsWith('/') && !path.startsWith('~')) {
    return toast('Give an absolute path, e.g. /home/you/.guzzionboard/images/5am-flash-read.bin', 'bad');
  }
  $('#mapsOut').innerHTML = '<p class="muted">Rendering…</p>';
  try {
    renderMapsResult(await api('/api/maps/render', { method: 'POST', body: { path, xdf } }));
  } catch (err) {
    $('#mapsOut').innerHTML = `<div class="gate-card bad"><h4>Could not render</h4><p class="small">${esc(err.message)}</p></div>`;
  }
};

$('#mapsDiffBtn').onclick = async () => {
  const a = $('#mapsImagePath').value.trim() || $('#imagePath').value.trim();
  const b = $('#mapsDiffPath').value.trim();
  const xdf = $('#xdfSelect').value;
  if (!xdf) return toast('No XDF definitions found — drop .xdf files into ~/.guzzionboard/xdfs/.', 'bad');
  if (!a || !b) return toast('Both images are needed to diff.', 'bad');
  $('#mapsOut').innerHTML = '<p class="muted">Comparing…</p>';
  try {
    const d = await api('/api/maps/diff', {
      method: 'POST', body: { path_a: a, path_b: b, xdf },
    });
    if (d.identical) {
      $('#mapsOut').innerHTML = '<div class="gate-card ok"><h4>No differences</h4>'
        + '<p class="small">Every table and constant in these definitions is identical between the two images.</p></div>';
      return;
    }
    maps.lastDoc = {
      title: `${(d.xdf || {}).title || 'Maps'} — diff`,
      html: mapsDoc(`${(d.xdf || {}).title || 'Maps'} — differences`,
        d.tables.map((t) => `<h2>${esc(t.title)} — ${t.changed_cells} cell(s) changed</h2>`
        + `<table><thead><tr><th>Row</th><th>Column</th><th>Before</th><th>After</th></tr></thead><tbody>`
        + (t.cells || []).map((c) => `<tr><td>${esc(c.y)}</td><td>${esc(c.x)}</td>`
          + `<td>${esc(fmtValue(c.before))}</td><td>${esc(fmtValue(c.after))}</td></tr>`).join('')
        + '</tbody></table>').join('')
        + (d.constants.length ? `<h2>Constants</h2><table><thead><tr><th>Constant</th><th>Before</th><th>After</th></tr></thead><tbody>`
          + d.constants.map((c) => `<tr><td>${esc(c.title)}</td><td>${esc(fmtValue(c.before))}</td><td>${esc(fmtValue(c.after))}</td></tr>`).join('')
          + '</tbody></table>' : '')),
    };
    $('#mapsOut').innerHTML = mapsResultToolbar() + `
      <div class="gate-card warn"><h4>Images differ</h4>
        <p class="small">${d.tables.length} table(s) and ${d.constants.length} constant(s) changed.</p></div>`
      + d.tables.map((t) => `
        <details open><summary>${esc(t.title)}
          <span class="muted small"> — ${t.changed_cells} cell(s) changed</span></summary>
        <div class="table-wrap"><table class="data">
          <thead><tr><th>Row</th><th>Column</th><th>Before</th><th>After</th></tr></thead>
          <tbody>${(t.cells || []).map((c) => `
            <tr><td>${esc(c.y)}</td><td>${esc(c.x)}</td>
                <td><b class="bad">${esc(fmtValue(c.before))}</b></td>
                <td><b class="ok">${esc(fmtValue(c.after))}</b></td></tr>`).join('')}
          </tbody></table></div>
        ${t.cells_truncated ? '<p class="muted small">Only the first 512 changed cells are listed.</p>' : ''}
        ${t.error ? `<p class="muted small">${esc(t.error)}</p>` : ''}
        </details>`).join('')
      + (d.constants.length ? `
        <details open><summary>Constants</summary>
        <div class="table-wrap"><table class="data">
          <thead><tr><th>Constant</th><th>Before</th><th>After</th></tr></thead>
          <tbody>${d.constants.map((c) => `
            <tr><td>${esc(c.title)}</td>
                <td><b class="bad">${esc(fmtValue(c.before))}</b> ${esc(c.units)}</td>
                <td><b class="ok">${esc(fmtValue(c.after))}</b></td></tr>`).join('')}
          </tbody></table></div></details>` : '');
    wireMapsToolbar();
  } catch (err) {
    $('#mapsOut').innerHTML = `<div class="gate-card bad"><h4>Could not diff</h4><p class="small">${esc(err.message)}</p></div>`;
  }
};

$$('.nav').forEach((b) => {
  if (b.dataset.view === 'firmware') {
    const previous = b.onclick;
    b.onclick = () => { previous?.(); loadXdfs(); };
  }
});

/* ------------------------------------------------- CAN capture analysis */
/* The CAN id pair is the one unknown on the CAN-era bikes (PRIOR_ART §7
 * item 2). This reads a passive capture — candump, SavvyCAN CSV or CRTD —
 * and reports the pair that behaves like ISO-TP diagnostics, with the
 * evidence, so nobody has to trust a guess. */

function renderCanlog(result) {
  const out = $('#canlogOut');
  const head = `
    <div class="gate-card ${result.diagnostic_traffic_found ? 'ok' : 'warn'}">
      <h4>${result.diagnostic_traffic_found
        ? `${result.pairs.length} candidate pair(s) found`
        : 'No diagnostic traffic recognised'}</h4>
      <p class="small">${result.frames} frames · format <b>${esc(result.format)}</b>
        ${result.span_seconds ? ` · ${(result.span_seconds / 60).toFixed(1)} min` : ''}
        · ${result.bus_ids.length} bus id(s)</p>
    </div>`;

  if (!result.diagnostic_traffic_found) {
    out.innerHTML = head
      + result.notes.map((n) => `<p class="muted small">${esc(n)}</p>`).join('');
    return;
  }

  const matchesNote = (p) => p.matches
    ? `<p class="small"><b class="ok">This is ${esc(p.matches)}.</b></p>`
    : `<p class="small"><b class="warn">This is neither standard pair.</b>
       Enter <code>${esc(p.request_id)}</code> / <code>${esc(p.response_id)}</code>
       in the Garage CAN fields when you connect${p.extended ? ' (29-bit)' : ''}.</p>`;

  out.innerHTML = head
    + result.pairs.map((p, i) => `
      <div class="gate-card ${i === 0 ? 'ok' : ''}">
        <h4>${i === 0 ? 'Best candidate: ' : ''}request <code>${esc(p.request_id)}</code>
          &rarr; response <code>${esc(p.response_id)}</code>
          <span class="conf ${p.confidence === 'strong' ? 'ok' : 'mid'}">${esc(p.confidence)}</span>
        </h4>
        ${matchesNote(p)}
        <p class="muted small">
          ${p.evidence.request_frames} request frame(s) · ${p.evidence.response_frames} response frame(s)
          · ${p.evidence.multi_frame_to_ecu} multi-frame exchange(s) to the ECU
          · ${p.evidence.multi_frame_from_ecu} from it
          ${p.tester_present_interval_s ? ` · tester present every ${p.tester_present_interval_s}s` : ''}
          ${p.padding_byte ? ` · padded with ${esc(p.padding_byte)}` : ''}
        </p>
        ${p.request_sids.length ? `<p class="muted small">Requests: ${esc(p.request_sids.join(', '))}</p>` : ''}
        ${p.response_sids.length ? `<p class="muted small">Responses: ${esc(p.response_sids.join(', '))}</p>` : ''}
      </div>`).join('')
    + result.notes.map((n) => `<p class="muted small">${esc(n)}</p>`).join('');
}

async function analyseCanlog(body) {
  $('#canlogOut').innerHTML = '<p class="muted">Analysing…</p>';
  try {
    renderCanlog(await api('/api/tools/canlog', { method: 'POST', body }));
  } catch (err) {
    $('#canlogOut').innerHTML =
      `<div class="gate-card bad"><h4>Could not analyse</h4><p class="small">${esc(err.message)}</p></div>`;
  }
}

$('#canlogBtn').onclick = () => {
  const path = $('#canlogPath').value.trim();
  if (!path) return toast('Give the path of a capture file.', 'bad');
  analyseCanlog({ path });
};
$('#canlogPasteBtn').onclick = () => {
  const text = $('#canlogText').value.trim();
  if (!text) return toast('Paste some capture lines first.', 'bad');
  analyseCanlog({ text });
};

/* ---------------------------------------------- K-Line capture analysis */
/* The 5AM identifier table in the catalog came from a wire tap, because no
 * published document carries one for any of these families. This makes that
 * method repeatable: characterise what answered, and solve the scalings
 * against the other tool's own CSV so a number earns 'verified-capture'
 * instead of being asserted. */

function renderKlinelog(result) {
  const out = $('#klinelogOut');
  const s = result.summary;
  const solved = result.matches.length;
  const head = `
    <div class="gate-card ${s.answered ? 'ok' : 'warn'}">
      <h4>${s.answered} identifier(s) answered · ${solved} scaling(s) solved</h4>
      <p class="small">${result.frames} frames · ${s.moved} moved · ${s.always_zero} always zero
        · ${s.refused} refused${result.identification.length
          ? ` · ECU says <code>${esc(result.identification[0].ascii)}</code>` : ''}</p>
    </div>`;

  if (!s.answered) {
    out.innerHTML = head + `<p class="muted small">${esc(result.note)}</p>`;
    return;
  }

  const solvedRows = result.matches.map((m) => `
    <tr><td><code>${esc(m.hex)}</code></td><td>${esc(m.channel)}</td>
      <td>${m.length} byte${m.length === 1 ? '' : 's'}${m.signed ? ', signed' : ''}</td>
      <td>× ${m.scale}${m.bias ? ` ${m.bias > 0 ? '+' : '−'} ${Math.abs(m.bias)}` : ''}</td>
      <td class="muted">r² ${m.fit} · ${m.points} pts</td></tr>`).join('');

  const unsolved = result.identifiers.filter(
    (e) => e.answers && !result.matches.some((m) => m.local_id === e.local_id));
  const unsolvedRows = unsolved.map((e) => `
    <tr><td><code>${esc(e.hex)}</code></td>
      <td class="muted">${e.always_zero ? 'always zero — dead slot'
        : e.moved ? 'moved, meaning unknown' : 'answered, never moved'}</td>
      <td>${e.length} byte${e.length === 1 ? '' : 's'}</td>
      <td class="muted">${e.min} … ${e.max}</td>
      <td class="muted">${e.samples} sample(s)</td></tr>`).join('');

  out.innerHTML = head
    + (solved ? `<h4>Solved against the reference log
         <span class="conf ok">verified-capture</span></h4>
       <table class="data"><thead><tr><th>Id</th><th>Channel</th><th>Width</th>
         <th>Scaling</th><th>Fit</th></tr></thead><tbody>${solvedRows}</tbody></table>`
      : `<p class="muted small">No scalings solved. Add the reference CSV the other
         tool wrote during the same capture — without it an identifier can only be
         shown to exist, not to mean anything.</p>`)
    + (unsolved.length ? `<h4>Answered but unsolved
         <span class="conf low">unknown</span></h4>
       <table class="data"><thead><tr><th>Id</th><th>What was seen</th><th>Width</th>
         <th>Range</th><th>Samples</th></tr></thead><tbody>${unsolvedRows}</tbody></table>` : '')
    + (result.services_seen.length ? `<p class="muted small">Services used by that tool:
        ${result.services_seen.map((x) => `${esc(x.name)} (${esc(x.service)})`).join(', ')}</p>` : '')
    + `<details class="advanced"><summary>Draft catalog fragment</summary>
        <p class="muted small">${esc(result.draft.note)}</p>
        <textarea rows="12" spellcheck="false" readonly>${esc(JSON.stringify(result.draft, null, 2))}</textarea>
       </details>`;
}

async function analyseKlinelog(body) {
  $('#klinelogOut').innerHTML = '<p class="muted">Analysing…</p>';
  try {
    renderKlinelog(await api('/api/tools/klinelog', { method: 'POST', body }));
  } catch (err) {
    $('#klinelogOut').innerHTML =
      `<div class="gate-card bad"><h4>Could not analyse</h4><p class="small">${esc(err.message)}</p></div>`;
  }
}

$('#klinelogBtn').onclick = () => {
  const path = $('#klinelogPath').value.trim();
  if (!path) return toast('Give the path of a capture file.', 'bad');
  analyseKlinelog({
    path,
    reference_path: $('#klinelogRefPath').value.trim() || undefined,
    family: $('#klinelogFamily').value.trim() || undefined,
  });
};
$('#klinelogPasteBtn').onclick = () => {
  const text = $('#klinelogText').value.trim();
  if (!text) return toast('Paste a capture first.', 'bad');
  analyseKlinelog({
    text,
    reference_path: $('#klinelogRefPath').value.trim() || undefined,
    family: $('#klinelogFamily').value.trim() || undefined,
  });
};

/* ---------------------------------------------------------- compare view */
/* Two recorded sessions, side by side, channel by channel. Sessions are
 * not aligned in time, so the server compares means, not point-by-point. */

function fillCompareSelects() {
  const sessions = state.sessions || [];
  const options = sessions.length
    ? sessions.map((s) => `<option value="${esc(s.name)}">${esc(s.name)}</option>`).join('')
    : '<option value="">no sessions yet</option>';
  $('#compareA').innerHTML = options;
  $('#compareB').innerHTML = options;
  if (sessions.length >= 2) {
    $('#compareA').value = sessions[1].name;   // newer first: A = older
    $('#compareB').value = sessions[0].name;
  }
}

function fmtStat(s, unit) {
  if (!s) return '<span class="muted">—</span>';
  const v = (x) => esc(Temp.value(x, unit));
  return `${v(s.mean)} <span class="muted small">(${v(s.min)}…${v(s.max)}, n=${s.count})</span>`;
}

$('#compareBtn').onclick = async () => {
  const a = $('#compareA').value, b = $('#compareB').value;
  if (!a || !b) return toast('Two recorded sessions are needed.', 'bad');
  $('#compareOut').innerHTML = '<p class="muted">Comparing…</p>';
  try {
    const d = await api('/api/sessions/compare', { method: 'POST', body: { a, b } });
    const meta = (s) => {
      const m = s.meta || {};
      return `${esc(m.model || m.ecu_family || '?')} · ${esc(m.ecu_family || '?')} · ${esc(s.name)}`;
    };
    const dtcLine = (title, codes) => codes.length
      ? `<p class="small"><b>${title}:</b> ${codes.map((c) => `<code>${esc(c)}</code>`).join(' ')}</p>`
      : '';
    $('#compareOut').innerHTML = `
      <div class="gate-card"><h4>${meta(d.a)} &nbsp;&harr;&nbsp; ${meta(d.b)}</h4></div>`
      + (d.channels_only_in_a.length ? `<p class="muted small">Only in A: ${esc(d.channels_only_in_a.join(', '))}</p>` : '')
      + (d.channels_only_in_b.length ? `<p class="muted small">Only in B: ${esc(d.channels_only_in_b.join(', '))}</p>` : '')
      + (d.dtcs.only_a.length || d.dtcs.only_b.length || d.dtcs.both.length
        ? dtcLine('Codes in both', d.dtcs.both) + dtcLine('Only in A', d.dtcs.only_a) + dtcLine('Only in B', d.dtcs.only_b)
        : '')
      + `<div class="table-wrap"><table class="data">
        <thead><tr><th>Channel</th><th>A (mean, range)</th><th>B (mean, range)</th><th>Δ mean</th></tr></thead>
        <tbody>${d.channels.map((c) => `
          <tr><td><b>${esc(c.key)}</b> ${esc(Temp.label(c.unit))}</td>
              <td>${fmtStat(c.a, c.unit)}</td><td>${fmtStat(c.b, c.unit)}</td>
              <td>${c.delta_mean === null ? '<span class="muted">—</span>'
                : `<b class="${Math.abs(c.delta_mean) < 1e-9 ? '' : 'warn'}">${c.delta_mean > 0 ? '+' : ''}${esc(Temp.delta(c.delta_mean, c.unit))}</b>`}</td>
          </tr>`).join('')}
        </tbody></table></div>`;
  } catch (err) {
    $('#compareOut').innerHTML =
      `<div class="gate-card bad"><h4>Could not compare</h4><p class="small">${esc(err.message)}</p></div>`;
  }
};

/* ------------------------------------------------------------------ tools */
/* Workshop utilities, no ECU connection needed: the gearing/road-speed
 * table with the per-model ratios read out of the mirrored GearSpeed app,
 * the Zeitronix ZT-2 to LogWorks DIF log converter (with the reference
 * tool's documented factor-4 timeline error corrected), and the bench RPM
 * trigger-signal generator (wheel geometry from RPMSensorEmu's configs). */

let toolsInit = false;

$$('.nav').forEach((b) => {
  if (b.dataset.view === 'tools') {
    const previous = b.onclick;
    b.onclick = () => { previous?.(); loadTools(); };
  }
});

async function loadTools() {
  if (toolsInit) return;
  toolsInit = true;
  try {
    const data = await api('/api/tools/gearing');
    const presets = data.presets || {};
    state.gearPresets = presets;
    $('#gearPreset').innerHTML =
      '<option value="">— custom ratios —</option>'
      + Object.keys(presets)
        .map((name) => `<option value="${esc(name)}">${esc(name)}</option>`)
        .join('');
    if (!$('#gearRatios').value.trim()) {
      $('#gearRatios').value = (data.gear_ratios_used || []).join(', ');
    }
  } catch (err) {
    $('#gearMeta').textContent = `Could not load presets: ${err.message}`;
  }
}

$('#gearPreset').onchange = (ev) => {
  const preset = (state.gearPresets || {})[ev.target.value];
  if (preset) $('#gearRatios').value = preset.gears.join(', ');
};

$('#gearCalcBtn').onclick = async () => {
  try {
    const params = new URLSearchParams({
      final_drive: $('#gearFinal').value.trim() || '4.125',
      tyre: $('#gearTyre').value.trim() || '180/55-17',
      preset: $('#gearPreset').value,
      gears: $('#gearRatios').value.trim(),
    });
    const data = await api(`/api/tools/gearing?${params}`);
    const gears = Object.entries(data.gears || {});
    if (!gears.length || !(data.rpm || []).length) {
      $('#gearOut').innerHTML = '<p class="muted">Nothing to show — check the gear ratios.</p>';
      return;
    }
    const head = '<th>engine rpm</th>'
      + gears.map(([g]) => `<th>${esc(g.replace('gear', ''))}. gear</th>`).join('');
    const maxRpm = data.max_rpm || Infinity;
    const rows = data.rpm.map((rpm, i) => {
      const cls = rpm > maxRpm ? ' class="dim"' : '';
      return `<tr${cls}><td>${rpm}</td>`
        + gears.map(([, speeds]) => `<td>${speeds[i]}</td>`).join('') + '</tr>';
    }).join('');
    $('#gearOut').innerHTML = `<div class="table-wrap"><table class="data">
      <thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
    $('#gearMeta').textContent =
      `${data.preset ? `Preset: ${data.preset} · ` : ''}`
      + `tyre ${data.tyre} (${data.circumference_m} m rolling) · final drive `
      + `${data.final_drive} · speeds in km/h`
      + (Number.isFinite(maxRpm) ? ` · dimmed rows are above the preset's ${maxRpm} rpm` : '');
  } catch (err) {
    toast(err.message, 'bad');
    $('#gearOut').innerHTML = '';
  }
};

/* -- wideband log converter -------------------------------------------- */

$('#z2ConvertBtn').onclick = async () => {
  const text = $('#z2In').value;
  if (!text.trim()) return toast('Paste a ZDL CSV export first.', 'bad');
  try {
    const data = await api('/api/tools/z2dif', {
      method: 'POST',
      body: {
        text,
        timeline_factor: parseFloat($('#z2Factor').value) || 4,
        sample_rate: parseFloat($('#z2Rate').value) || 65,
      },
    });
    state.z2dif = data.dif;
    $('#z2Out').value = data.dif;
    $('#z2Meta').textContent =
      `${data.rows} rows · ${data.channels.join(' · ')} · ${data.duration_s}s `
      + `at ${data.sample_rate}/s (factor ${data.timeline_factor})`;
    $('#z2DownloadBtn').disabled = false;
    $('#z2CopyBtn').disabled = false;
    toast(`Converted ${data.rows} rows.`, 'ok');
  } catch (err) {
    $('#z2Meta').textContent = err.message;
    toast(err.message, 'bad');
  }
};

$('#z2DownloadBtn').onclick = () => {
  const blob = new Blob([state.z2dif || $('#z2Out').value], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'zt2-converted.dif';
  a.click();
  URL.revokeObjectURL(a.href);
};

$('#z2CopyBtn').onclick = async () => {
  try {
    await navigator.clipboard.writeText($('#z2Out').value);
    toast('DIF table copied to the clipboard.', 'ok');
  } catch (_) {
    toast('Clipboard is blocked; select the text and copy by hand.', 'warn');
  }
};

/* -- bench RPM trigger signal ------------------------------------------ */

$('#sigPreset').onchange = (ev) => {
  $('#sigCustom').classList.toggle('hidden', ev.target.value !== 'custom');
};

function signalWheelBody() {
  const preset = $('#sigPreset').value;
  if (preset !== 'custom') return { pattern: preset };
  return {
    teeth: parseInt($('#sigTeeth').value, 10),
    missing: parseInt($('#sigMissing').value, 10),
    wheel: $('#sigWheel').value,
  };
}

async function generateSignal(body) {
  const data = await api('/api/tools/rpmsignal', { method: 'POST', body });
  $('#sigOut').innerHTML =
    `<div class="tip"><b>Saved:</b> <code>${esc(data.path)}</code><br>`
    + `${esc(data.pattern)} · ${data.duration_s}s of signal`
    + (data.note ? ` · ${esc(data.note)}` : '') + '</div>';
  toast('Signal WAV written — play it through an AC-coupled buffer.', 'ok');
}

$('#sigSimpleBtn').onclick = async () => {
  try {
    const body = signalWheelBody();
    body.rpm = parseFloat($('#sigRpm').value) || 0;
    body.seconds = parseFloat($('#sigSecs').value) || 0;
    await generateSignal(body);
  } catch (err) { toast(err.message, 'bad'); }
};

$('#sigBatchBtn').onclick = async () => {
  try {
    const events = $('#sigBatch').value.split('\n')
      .map((ln) => ln.trim())
      .filter((ln) => ln && !ln.startsWith(';'))
      .map((ln) => ln.split('|').map((v) => parseFloat(v.trim())));
    if (!events.length) return toast('Write at least one batch step first.', 'bad');
    const body = signalWheelBody();
    body.events = events;
    await generateSignal(body);
  } catch (err) { toast(err.message, 'bad'); }
};
