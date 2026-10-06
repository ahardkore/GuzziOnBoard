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
  addEventListener() {},
};

const demoData = JSON.parse(readFileSync(join(WEB, 'demo-data.json'), 'utf8'));

const sandboxFetch = async (url) => {
  if (String(url).includes('demo-data.json')) {
    return { ok: true, status: 200, json: async () => demoData };
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
  parseInt,
  parseFloat,
  Object,
  Number,
  String,
  Array,
  Error,
  Promise,
});
context.globalThis = context;

vm.runInContext(readFileSync(join(WEB, 'demo-api.js'), 'utf8'), context,
  { filename: 'demo-api.js' });

const api = async (path, options = {}) => {
  const response = await context.window.fetch(path, options);
  const payload = await response.json();
  return { status: response.status, payload };
};
const post = (path, body) =>
  api(path, { method: 'POST', body: JSON.stringify(body || {}) });

/* -------------------------------------------------------------- drive */

console.log('demo-api.js (hosted demo backend)');

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

const hardware = await post('/api/select', {
  make: 'Moto Guzzi', model: 'Griso 1200 8V', year: 2012, transport: 'kline',
});
check('hardware selection warns it is a demo',
  hardware.payload.notices.some((n) => n.level === 'danger'));
const refused = await post('/api/connect', { mode: 'read_only' });
check('hardware connect is refused, not faked',
  refused.status === 501 && refused.payload.code === 'demo_local_only');

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

for (const [path, method] of [
  ['/api/memory', 'GET'], ['/api/maps', 'GET'], ['/api/report', 'GET'],
  ['/api/procedures', 'GET'], ['/api/tools/gearing', 'GET'],
]) {
  const res = method === 'GET' ? await api(path) : await post(path, {});
  check(`${path} is refused with a local-only message`,
    res.status === 501 && /run_server\.py/.test(res.payload.error));
}

const disconnected = await post('/api/disconnect', {});
check('disconnect returns to the garage', disconnected.payload.connected === false);

console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
process.exit(failures ? 1 : 0);
