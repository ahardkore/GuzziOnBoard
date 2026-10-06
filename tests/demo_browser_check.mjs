/* Exercise web/demo-api.js outside a browser.
 *
 * The hosted demo answers the workstation's own /api calls in the page, so it
 * has to be tested the way the page uses it: install the shim, then drive a
 * whole session through window.fetch. This harness provides the smallest DOM
 * the shim touches and asserts on the payload shapes app.js consumes.
 *
 * Run directly (node tests/demo_browser_check.mjs) or through
 * tests/test_demo_mode.py, which skips when node is unavailable.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const WEB = join(ROOT, 'web');

let failures = 0;
function check(name, condition, detail = '') {
  if (condition) {
    console.log(`  ok   ${name}`);
  } else {
    failures += 1;
    console.log(`  FAIL ${name}${detail ? ' — ' + detail : ''}`);
  }
}

/* ----------------------------------------------------------- tiny DOM */

function element(id = '') {
  const el = {
    id,
    className: '',
    dataset: {},
    children: [],
    innerHTML: '',
    firstChild: null,
    setAttribute() {},
    appendChild(child) { this.children.push(child); return child; },
    insertBefore(child) { this.children.unshift(child); return child; },
  };
  return el;
}

const body = element('body');
const document = {
  body,
  readyState: 'complete',
  title: '',
  createElement: () => element(),
  getElementById: () => null,
  querySelector: (sel) => (sel === 'main' ? null : null),
  querySelectorAll: () => [],
  addEventListener() {},
};

const demoData = JSON.parse(readFileSync(join(WEB, 'demo-data.json'), 'utf8'));

const sandboxFetch = async (url) => {
  const target = String(url);
  if (target.includes('demo-data.json')) {
    return { ok: true, status: 200, json: async () => demoData };
  }
  /* demo-lab.js fetches the bundled XDF definitions from the site; here
   * they come off disk, which is where the deployed copies come from too. */
  const marker = target.indexOf('xdfs/');
  if (marker >= 0) {
    const file = join(ROOT, 'guzzionboard', 'xdfs', target.slice(marker + 5));
    return {
      ok: true, status: 200,
      text: async () => readFileSync(file, 'latin1'),
    };
  }
  throw new Error(`unexpected network call: ${url}`);
};

const windowObj = {
  fetch: sandboxFetch,
  location: { href: 'https://example.github.io/GuzziOnBoard/web/index.html' },
};

const context = vm.createContext({
  window: windowObj,
  document,
  fetch: sandboxFetch,
  Response,
  URL,
  URLSearchParams,
  performance,
  Date,
  Math,
  JSON,
  console,
  setTimeout,
  isFinite,
  setInterval,
  clearInterval,
  parseInt,
  parseFloat,
  Object,
  Number,
  String,
  Array,
  Error,
  Promise,
  Uint8Array,
  Int16Array,
  Int32Array,
  Uint32Array,
  DataView,
  ArrayBuffer,
  RegExp,
  Boolean,
  Function,
});
context.globalThis = context;

vm.runInContext(readFileSync(join(WEB, 'demo-api.js'), 'utf8'), context,
  { filename: 'demo-api.js' });
vm.runInContext(readFileSync(join(WEB, 'demo-lab.js'), 'utf8'), context,
  { filename: 'demo-lab.js' });

const api = async (path, options = {}) => {
  const response = await context.window.fetch(path, options);
  const payload = await response.json();
  return { status: response.status, payload };
};
const post = (path, body) =>
  api(path, { method: 'POST', body: JSON.stringify(body || {}) });

/* -------------------------------------------------------------- drive */

console.log('demo-api.js (hosted demo backend)');

check('every hosted-demo API route has a browser implementation',
  Object.keys(context.window.GUZZI_DEMO.localOnly).length === 0,
  Object.keys(context.window.GUZZI_DEMO.localOnly).join(', '));

const catalog = await api('/api/catalog');
check('catalog loads', catalog.status === 200 && catalog.payload.ecus.length > 0);
check('catalog carries every family',
  catalog.payload.summary.ecu_count === catalog.payload.ecus.length);
check('catalog has vehicles', catalog.payload.vehicles.length > 100);

const resolved = await api(
  '/api/catalog/resolve?make=Moto%20Guzzi&model=Griso%201200%208V&year=2012');
check('resolve finds the Griso', resolved.payload.matches.length === 1
  && resolved.payload.matches[0].ecu === '5am');
check('resolve carries the ECU detail',
  resolved.payload.matches[0].ecu_detail.family === 'IAW 5AM');

const cross = await api('/api/catalog/resolve?make=Ducati&model=Monster%20900&year=2000');
if (cross.payload.matches.length) {
  const detail = cross.payload.matches[0];
  check('cross-brand entries stay low-confidence',
    ['inferred', 'unknown'].includes(detail.confidence), detail.confidence);
}

const selected = await post('/api/select', {
  make: 'Moto Guzzi', model: 'Griso 1200 8V', year: 2012, transport: 'simulator',
});
check('select resolves to the 5AM', selected.payload.ecu.id === '5am');
check('select reports the model notice',
  selected.payload.notices.some((n) => n.level === 'info'));

const demoStatus = await api('/api/status');
check('the hosted demo offers no real-bike transports',
  demoStatus.payload.transports.length === 1
  && demoStatus.payload.transports[0].id === 'simulator');
const staleHardwareChoice = await post('/api/select', {
  make: 'Moto Guzzi', model: 'Griso 1200 8V', year: 2012, transport: 'kline',
});
check('stale hardware preferences are coerced to the virtual demo',
  staleHardwareChoice.payload.transport === 'simulator'
  && !staleHardwareChoice.payload.notices.some((n) => n.level === 'danger'));
const virtualFromStale = await post('/api/connect', { mode: 'read_only' });
check('a crafted real-bike request still starts only the simulator',
  virtualFromStale.status === 200
  && virtualFromStale.payload.connected === true
  && virtualFromStale.payload.mode === 'simulator');
await post('/api/disconnect', {});

await post('/api/select', {
  make: 'Moto Guzzi', model: 'Griso 1200 8V', year: 2012, transport: 'simulator',
});
const connected = await post('/api/connect', { mode: 'simulator' });
check('simulator connects', connected.payload.connected === true);
check('connected status carries diagnostics',
  !!connected.payload.diagnostics && connected.payload.diagnostics.init.ok);
check('status is labelled as the demo', connected.payload.demo === true);

const before = await api('/api/actuators');
check('actuators are blocked before identification',
  before.payload.actuators.every((a) => !a.decision.allowed));
check('the blocking check is named',
  before.payload.actuators[0].decision.checks.some(
    (c) => c.name === 'identified' && !c.passed));

const identity = await api('/api/identify');
check('identify returns the captured fields',
  identity.payload.fields.Hardware === 'IAW5AMHW610');
check('identify returns a raw block', /^[0-9a-f ]+$/.test(identity.payload.raw));

const params = await api('/api/parameters');
check('parameters come from the catalog', params.payload.parameters.length > 20);
check('parameters carry their confidence',
  params.payload.parameters.every((p) => !!p.confidence));

const live = await api('/api/live?keys=rpm,coolant_temp,throttle,battery');
check('live returns one sample per key', live.payload.samples.length === 4);
const rpm = live.payload.samples.find((s) => s.key === 'rpm');
check('rpm is a plausible idle', rpm.value > 900 && rpm.value < 3000, String(rpm.value));
check('samples carry raw bytes', /^[0-9a-f]{2}( [0-9a-f]{2})*$/.test(rpm.raw));
check('derived channels are labelled derived',
  live.payload.derived.every((d) => d.derived === true));

const dtcs = await api('/api/dtcs');
check('fault memory has the seeded codes', dtcs.payload.dtcs.length === 2);
check('fault codes are decoded', dtcs.payload.dtcs[0].code === 'P0130'
  && dtcs.payload.dtcs[0].description.length > 0);
check('fault read carries observed context',
  Object.keys(dtcs.payload.context).length > 0 && !!dtcs.payload.context_note);
check('clearing is gated by a decision', dtcs.payload.clear.allowed === true
  && !!dtcs.payload.clear.token);

const badToken = await post('/api/dtcs/clear', { token: 'nope' });
check('a forged token is refused', badToken.status === 403);

const cleared = await post('/api/dtcs/clear', { token: dtcs.payload.clear.token });
check('clearing empties fault memory', cleared.payload.remaining.length === 0);

const reused = await post('/api/dtcs/clear', { token: dtcs.payload.clear.token });
check('a token is consumed on use', reused.status === 403);

/* The engine is running, so an engine-off actuator must stay blocked. */
const running = await api('/api/actuators');
const pump = running.payload.actuators.find((a) => a.key === 'fuel_pump')
  || running.payload.actuators[0];
check('engine-off actuators are blocked while it runs', !pump.decision.allowed
  && pump.decision.checks.some((c) => c.name === 'engine-off' && !c.passed));

await post('/api/sim/engine', { running: false });
await api('/api/live?keys=rpm,battery');          // observe the stopped engine
const stopped = await api('/api/actuators');
const pump2 = stopped.payload.actuators.find((a) => a.key === pump.key);
check('stopping the engine unblocks the pulse', pump2.decision.allowed === true,
  pump2.decision.reason);

const pulse = await post('/api/actuators/pulse',
  { key: pump2.key, token: pump2.decision.token });
check('a pulse is bounded', pulse.payload.ok === true
  && pulse.payload.duration_s <= pump2.max_pulse_s);

const sim = await api('/api/sim');
check('the simulated bike is drivable', sim.payload.available === true
  && sim.payload.engine.running === false);
check('every seeded fault is offered', sim.payload.faults.length >= 9);

const seeded = await post('/api/sim/faults', { key: 'air_leak', active: true });
check('a fault can be seeded',
  seeded.payload.faults.find((f) => f.key === 'air_leak').active === true);

await post('/api/sim/engine', { running: true });
const leaking = await api('/api/live?keys=rpm,stepper_position,stepper_base');
const leakRpm = leaking.payload.samples.find((s) => s.key === 'rpm').value;
check('the air leak raises idle before any code appears', leakRpm > 1500,
  String(leakRpm));

const scan = await post('/api/discover', { start: 0x30, end: 0x40 });
check('the discovery sweep is read-only and answers',
  scan.payload.scanned === 17 && scan.payload.answered > 0);

/* ------------------------------------------- demo-lab.js: the workbench */

console.log('\ndemo-lab.js (the simulated workbench)');

/* Memory: read, backup, validate, write, verify — all against a flash image
 * synthesised in the page, with the job compressed to a few seconds. */
const memory = await api('/api/memory');
check('memory describes the ECU', memory.status === 200
  && memory.payload.capabilities.read_supported === true);
check('memory says the image is simulated', memory.payload.simulated === true
  && /simulat/i.test(JSON.stringify(memory.payload.demo_note || '')));
check('memory offers regions to read',
  Object.keys(memory.payload.capabilities.regions).length > 0);

const demoSecurity = await api('/api/security');
check('the virtual connector starts with its demo-only key fixture ready',
  demoSecurity.payload.unverified_keys_accepted === true);
check('the virtual hardware checklist is already complete',
  connected.payload.vehicle_state.checklist_accepted === true);

const started = await post('/api/memory/backup', { region: 'flash' });
check('a backup starts a job', started.status === 202
  && started.payload.state === 'running',
  JSON.stringify(started).slice(0, 300));
check('the job says how far it is compressed',
  started.payload.compression.real_seconds > 1000
  && started.payload.compression.demo_seconds < 10
  && /Time-compressed/.test(started.payload.compression.note));
check('progress carries a real-world ETA as well as the demo one',
  started.payload.progress.real_eta_s > started.payload.progress.eta_s);

let job = started.payload;
const deadline = Date.now() + 30000;
while (job.state === 'running' && Date.now() < deadline) {
  await new Promise((r) => setTimeout(r, 120));
  job = (await api('/api/memory/progress')).payload;
}
check('the backup finishes', job.state === 'done', job.state);
check('the backup is labelled simulated', job.simulated === true
  && /simulat/i.test(job.note));
const imagePath = job.result && job.result.path;
check('the backup produced an image path', !!imagePath, String(imagePath));
check('the backup verified itself by reading twice',
  job.result.verified === true && job.result.attempts === 2);
const describe = job.result.describe;
check('the image carries both hashes',
  /^[0-9a-f]{64}$/.test(describe.checksums.sha256)
  && typeof describe.checksums.sum16 === 'number');
check('the image looks like firmware, not noise',
  describe.vector_table === true && describe.blank === false);

const validated = await post('/api/memory/validate', { path: imagePath });
check('the backup validates', validated.status === 200
  && validated.payload.ok === true);
check('validation names its checks',
  validated.payload.findings.some((f) => f.check === 'size')
  && validated.payload.fatal === 0);

const preGate = await post('/api/memory/check-write', { region: 'flash' });
check('a write is refused before programming is armed',
  preGate.payload.allowed === false);
const sloppyAck = await post('/api/programming/enable', { acknowledgement: 'yes' });
check('the acknowledgement must be exact', sloppyAck.status === 403);
const progEnable = await post('/api/programming/enable', {
  acknowledgement: memory.payload.acknowledgement,
});
check('programming can be armed with the exact acknowledgement',
  progEnable.payload.programming_enabled === true);
const gate = await post('/api/memory/check-write', { region: 'flash' });
check('arming programming unblocks the write', gate.payload.allowed === true,
  gate.payload.reason);

const written = await post('/api/memory/write',
  { path: imagePath, token: gate.payload.token });
check('a write starts a job', written.status === 202
  && written.payload.state === 'running');
let wjob = written.payload;
const wdeadline = Date.now() + 30000;
while (wjob.state === 'running' && Date.now() < wdeadline) {
  await new Promise((r) => setTimeout(r, 120));
  wjob = (await api('/api/memory/progress')).payload;
}
check('the write finishes and verifies', wjob.state === 'done'
  && wjob.result.verified === true, wjob.state);
check('the write admits it is a simulation of the riskiest operation',
  wjob.result.simulated === true && /refuses/.test(wjob.result.note));

const replayedWrite = await post('/api/memory/write',
  { path: imagePath, token: gate.payload.token });
check('a write token is single-use (code token)',
  replayedWrite.status === 403 && replayedWrite.payload.code === 'token',
  `${replayedWrite.status} ${replayedWrite.payload.code}`);

/* The hardware-family safety gate. The demo's virtual bench carries an
 * image from a different hardware family (an HW1xx file for this HW6xx
 * ECU - the same class of mistake as flashing an HW1xx image into an HW3xx
 * ECU, which bricks it). It has to be refused at validation, at the write
 * gate, and on a direct write attempt that smuggles a token minted without
 * the image. */
const memView = await api('/api/memory');
const hazard = (memView.payload.demo_images || [])[0];
check('the demo bench lists its wrong-hardware-family fixture',
  !!hazard && /IAW5AMHW100/.test(String(hazard.hardware || '')),
  JSON.stringify(hazard || {}).slice(0, 140));
if (hazard) {
  const hv = await post('/api/memory/validate', { path: hazard.path });
  const hwFinding = (hv.payload.findings || [])
    .filter((f) => f.check === 'hardware')[0];
  check('validation flags the cross-family image as fatal',
    hv.status === 200 && hv.payload.ok === false
      && !!hwFinding && hwFinding.level === 'fatal',
    JSON.stringify(hwFinding || {}).slice(0, 160));

  const hg = await post('/api/memory/check-write',
    { region: 'flash', path: hazard.path });
  const hgFails = (hg.payload.checks || [])
    .filter((c) => !c.passed).map((c) => c.name);
  check('the write gate refuses the cross-family image by name',
    hg.status === 200 && hg.payload.allowed === false
      && hgFails.length === 1 && hgFails[0] === 'hardware-family',
    hg.payload.reason);

  const cleanGate = await post('/api/memory/check-write', { region: 'flash' });
  const forced = await post('/api/memory/write',
    { path: hazard.path, token: cleanGate.payload.token });
  check('a token cannot smuggle a cross-family image into the ECU',
    forced.status === 403 && /hardware-family/.test(String(forced.payload.error || '')),
    String(forced.payload.error || '').slice(0, 150));
}

/* Maps: the bundled XDFs, parsed in the page, against that image. */
const mapList = await api('/api/maps');
check('the bundled definitions are listed', mapList.payload.xdfs.length > 50);
check('the definitions say what is real and what is not',
  mapList.payload.simulated === true && /synthesi/i.test(mapList.payload.demo_note));
const xdfTitle = mapList.payload.xdfs.find((x) => x.tables > 20).title;
const rendered = await post('/api/maps/render', { path: imagePath, xdf: xdfTitle });
check('a definition renders against the image', rendered.status === 200
  && rendered.payload.tables.length > 20,
  JSON.stringify(rendered.payload).slice(0, 140));
const table = rendered.payload.tables[0];
check('rendered tables carry a grid of values',
  Array.isArray(table.values) && table.values.length === table.rows
  && !!table.title);
check('the render is labelled simulated', rendered.payload.simulated === true);

/* The read also leaves a lightly re-tuned copy alongside, so the diff has
 * two images to compare without inventing a second ECU. */
const tunedPath = imagePath.replace(/-[0-9]{8}-[0-9]{6}\.bin$/, '-tuned-demo.bin');
const diffed = await post('/api/maps/diff', {
  path_a: imagePath, path_b: tunedPath, xdf: xdfTitle,
});
check('two images can be diffed through a definition',
  diffed.status === 200 && Array.isArray(diffed.payload.tables),
  JSON.stringify(diffed.payload).slice(0, 140));
check('the diff says whether the two images agree',
  typeof diffed.payload.identical === 'boolean');

/* Sessions: two canned ones plus whatever this session recorded. */
const sessions = await api('/api/sessions');
check('the canned sessions are there', sessions.payload.sessions.length >= 2);
check('sessions say they live in the tab, not on disk',
  sessions.payload.simulated === true
  && /browser tab/i.test(sessions.payload.note));
const canned = sessions.payload.sessions.find((s) => /idle-hunting/.test(s.name));
check('the pre-recorded sessions are labelled as such',
  !!canned && canned.simulated === true && /browser tab/.test(canned.path));

const name = encodeURIComponent(canned.name);
const events = await api(`/api/sessions/events?name=${name}`);
check('session events can be listed', events.payload.events.length > 10);
check('the session recorded its fault codes',
  events.payload.events.some((e) => e.kind === 'action'
    && (((e.detail || {}).dtcs) || []).length === 2));
const csv = await api(`/api/sessions/export?name=${name}&format=csv`);
check('a session exports as CSV', csv.payload.rows > 100
  && /^time/i.test(csv.payload.content.split('\n')[0]),
  csv.payload.content.split('\n')[0].slice(0, 60));
const replay = await api(`/api/sessions/replay?name=${name}`);
check('a session replays into frames', replay.payload.frames.length > 100,
  String(replay.payload.frames && replay.payload.frames.length));
check('replay frames carry recomputed findings',
  replay.payload.frames.some((f) => (f.findings || []).length > 0));
check('replay recomputes derived channels from the recorded bytes',
  replay.payload.frames.some((f) => (f.derived || []).length > 0)
  && /recomputed/.test(replay.payload.note));
const compared = await post('/api/sessions/compare', {
  a: sessions.payload.sessions.find((s) => /warmup/.test(s.name)).name,
  b: canned.name,
});
check('two sessions compare', compared.status === 200
  && compared.payload.channels.length > 3);
check('the comparison notices the hunting idle',
  compared.payload.channels.some(
    (c) => c.key === 'rpm' && Math.abs(c.delta_mean) > 100),
  JSON.stringify(compared.payload.channels.find((c) => c.key === 'rpm')));
check('the comparison notices the new fault codes',
  compared.payload.dtcs.only_b.length === 2);

/* The report. */
const report = await api('/api/report?temp_unit=F');
check('a report is built from the session', report.status === 200
  && report.payload.report.vehicle.model === 'Griso 1200 8V');
check('the report says it is simulated',
  /SIMULATED/.test(report.payload.text) && report.payload.report.demo === true);
check('the report honours the temperature unit',
  report.payload.temp_unit === 'F' && /°F/.test(report.payload.text));
check('the report carries the safety audit',
  report.payload.report.safety_audit.length > 0);

/* Guided tests. */
const procedures = await api('/api/procedures');
check('the real procedures are offered', procedures.payload.procedures.length === 5);
check('procedures carry their caveats and availability',
  procedures.payload.procedures.every((p) => typeof p.available === 'boolean'));
check('the procedure note admits the compression',
  /compress/i.test(procedures.payload.note), procedures.payload.note);
const run = await post('/api/procedures/start', { key: 'idle_health' });
check('a procedure starts', run.payload.run.status === 'running');
let state = run.payload.run;
for (let i = 0; i < 6 && state.status === 'running'; i += 1) {
  state = (await post('/api/procedures/advance', {})).payload.run;
}
check('the procedure runs to a verdict', state.status === 'done' && !!state.verdict,
  state.status);
check('the observation step sampled the engine',
  state.results.some((r) => r.kind === 'observe' && r.stats.rpm.count > 3));
check('the verdict is labelled an interpretation',
  ['ok', 'warn', 'bad', 'info'].includes(state.verdict.level));

/* Tools. */
const gearing = await api('/api/tools/gearing?preset='
  + encodeURIComponent('Moto Guzzi — California III early'));
check('gearing answers with a speed table',
  gearing.payload.gears.gear1.length === gearing.payload.rpm.length);
check('gearing matches the Python arithmetic',
  gearing.payload.circumference_m === 1.979
  && gearing.payload.gears.gear1[0] === 14.4,
  JSON.stringify(gearing.payload.gears.gear1.slice(0, 2)));

const z2 = await post('/api/tools/z2dif', {
  text: 'Time,AFR,RPM,TPS\n0,14.7,1500,2\n1,13.2,3000,20\n',
});
check('a ZT-2 CSV converts to DIF', z2.payload.rows === 2
  && z2.payload.dif.split('\r\n')[0] === 'Time (s)\tTime\tAFR\tRPM\tTPS (%)');
check('the DIF time axis is rebuilt at factor 4/65',
  z2.payload.dif.split('\r\n')[2].startsWith('0.062'));
const z2bad = await post('/api/tools/z2dif', { text: 'A,B\n1,2\n' });
check('a non-ZT-2 CSV is rejected', z2bad.status === 400
  && /AFR\/Lambda/.test(z2bad.payload.error));

const wav = await post('/api/tools/rpmsignal',
  { pattern: 'motoguzzi', rpm: 1500, seconds: 1 });
check('the bench signal renders a real WAV', wav.payload.duration_s === 1
  && wav.payload.bytes === 44 + 44100 * 2);
check('the bench signal keeps its safety warning', /never/i.test(wav.payload.safety));
check('the wheel geometry comes from the presets',
  wav.payload.teeth === 46 && wav.payload.missing === 2
  && wav.payload.wheel === 'camshaft');

const canlog = await post('/api/tools/canlog', {
  text: [
    '(1.000) can0 7E0#0210C0AAAAAAAA',
    '(1.010) can0 7E8#0650C0AAAAAAAA',
    '(1.100) can0 7E0#021A80AAAAAAAA',
    '(1.110) can0 7E8#10145A80313233',
    '(1.120) can0 7E0#3000000000000000',
    '(2.000) can0 7E0#023E00AAAAAAAA',
    '(3.000) can0 7E0#023E00AAAAAAAA',
    '(4.000) can0 7E0#023E00AAAAAAAA',
  ].join('\n'),
});
check('a candump capture is analysed', canlog.payload.frames === 8
  && canlog.payload.format === 'candump');
check('the diagnostic pair is found with evidence',
  canlog.payload.diagnostic_traffic_found === true
  && canlog.payload.pairs[0].request_id === '0x7E0'
  && canlog.payload.pairs[0].response_id === '0x7E8');
check('the standard pair is recognised as standard',
  /15765-4/.test(canlog.payload.pairs[0].matches || ''));
check('tester present cadence is measured',
  canlog.payload.pairs[0].tester_present_interval_s === 1);

const kline = await post('/api/tools/klinelog', {
  text: ['0.000 tx 80 10 F1 02 21 30 1D',
    '0.020 rx 80 F1 10 04 61 30 0B B8',
    '0.100 tx 80 10 F1 02 21 30 1D',
    '0.120 rx 80 F1 10 04 61 30 0C 1A'].join('\n'),
});
check('a K-Line capture is characterised', kline.payload.summary.answered === 1
  && kline.payload.summary.moved === 1);
check('no scaling is claimed without the reference log',
  kline.payload.matches.length === 0
  && kline.payload.draft.parameters.every((p) => p.confidence === 'unknown'));

/* Comms quality now spoils the simulated wire instead of being disabled. */
const commsOn = await post('/api/sim/comms', { drop_rate: 1.0 });
check('the comms sliders now spoil the simulated wire',
  commsOn.status === 200 && /simulated one/.test(commsOn.payload.comms.note));
const spoiled = await api('/api/live?keys=rpm,coolant_temp,battery');
check('dropping every frame produces timeouts, not values',
  spoiled.payload.samples.every((s) => !!s.error), 
  JSON.stringify(spoiled.payload.samples.map((s) => s.error)));
check('the degraded read is labelled', !!spoiled.payload.comms_note);
await post('/api/sim/comms', { drop_rate: 0 });
const healthy = await api('/api/live?keys=rpm');
check('clearing the sliders restores the reads',
  healthy.payload.samples.every((s) => !s.error));

/* Connector-dependent setup is represented by an explicit virtual fixture. */
const adapter = await api('/api/adapter');
check('the demo supplies a labelled virtual connector and adapter',
  adapter.payload.simulated === true
  && adapter.payload.ports.length === 1
  && adapter.payload.ports[0].device === 'demo://virtual-kline'
  && /SIMULATED CONNECTOR/.test(adapter.payload.text));
const tunedAdapter = await post('/api/adapter/latency', {
  port: 'demo://virtual-kline', value: 1,
});
check('the virtual adapter pre-flight can be completed',
  tunedAdapter.payload.ok === true && tunedAdapter.payload.latency_ms === 1);

const disconnected = await post('/api/disconnect', {});
check('disconnect returns to the garage', disconnected.payload.connected === false);

/* Research metadata must not become a simulator capability through the API. */
await post('/api/select', { ecu: 'miug3', transport: 'simulator' });
await post('/api/connect', { mode: 'simulator' });
const unsupportedIdentity = await api('/api/identify');
const unsupportedLive = await api('/api/live?keys=manifold_pressure_raw');
const unsupportedDtcs = await api('/api/dtcs');
const unsupportedDiscovery = await post('/api/discover', { start: 0x30, end: 0x31 });
check('research-only identification is refused even in the simulator',
  unsupportedIdentity.status === 400 && unsupportedIdentity.payload.code === 'protocol_error');
check('research-only live identifiers are refused even in the simulator',
  unsupportedLive.status === 400 && unsupportedLive.payload.code === 'protocol_error');
check('research-only fault requests are refused even in the simulator',
  unsupportedDtcs.status === 400 && unsupportedDtcs.payload.code === 'protocol_error');
check('research-only discovery is refused even in the simulator',
  unsupportedDiscovery.status === 400 && unsupportedDiscovery.payload.code === 'protocol_error');
await post('/api/disconnect', {});

console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
process.exit(failures ? 1 : 0);
