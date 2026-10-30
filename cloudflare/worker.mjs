/** Cloudflare read-report relay. All reports are self-reported; no write effects. */
import catalog from './catalog.json' with { type: 'json' };

const MAX_REQUEST = 65536, MAX_CAPTURE = 32768, MAX_PACK = 512 * 1024;
const encoder = new TextEncoder();
const hex = bytes => Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
const unhex = value => Uint8Array.from(value.match(/../g), b => parseInt(b, 16));
const sha256 = async bytes => hex(await crypto.subtle.digest('SHA-256', bytes));
const canonical = value => {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
  return JSON.stringify(value);
};
const hasKeys = (x, keys) => x && typeof x === 'object' && !Array.isArray(x)
  && Object.keys(x).sort().join('\0') === [...keys].sort().join('\0');
const safeName = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,64}$/.test(value);
class Invalid extends Error {}
const demand = (condition, why = 'invalid report') => { if (!condition) throw new Invalid(why); };

async function boundedBody(request) {
  const length = request.headers.get('Content-Length');
  if (length && (!/^\d+$/.test(length) || Number(length) > MAX_REQUEST)) throw new Invalid('request too large');
  demand(request.body, 'empty request');
  const reader = request.body.getReader(), parts = [];
  let count = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    count += value.byteLength;
    if (count > MAX_REQUEST) { await reader.cancel(); throw new Invalid('request too large'); }
    parts.push(value);
  }
  demand(count > 0, 'empty request');
  const bytes = new Uint8Array(count); let offset = 0;
  for (const part of parts) { bytes.set(part, offset); offset += part.length; }
  return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
}

/** Validate the client's minimal event stream and retain only bounded provenance. */
export async function validateReport(report) {
  demand(hasKeys(report, ['bundle', 'capture']));
  const b = report.bundle, capture = report.capture;
  demand(b && b.schema === 'guzzionboard.protocol-confirmation/v1' && b.verdict === 'ok');
  demand(typeof b.id === 'string' && /^conf-[0-9a-f]{6,32}$/.test(b.id));
  demand(b.install && typeof b.install.marker === 'string' && /^[0-9a-f]{16}$/.test(b.install.marker));
  demand(hasKeys(b.claims, ['memory_read']) && b.session && b.ecu);
  for (const field of ['vin', 'serial', 'plate', 'owner', 'email', 'address']) demand(!b[field]);
  demand(typeof capture === 'string' && encoder.encode(capture).length <= MAX_CAPTURE);
  demand(await sha256(encoder.encode(capture)) === b.session.capture_sha256);
  const events = capture.split('\n').filter(line => line.trim()).map(line => JSON.parse(line));
  demand(events.length >= 5 && events.length <= 15);
  const metaEvent = events[0], connect = events.at(-2), read = events.at(-1);
  demand(hasKeys(metaEvent, ['kind', 'meta']) && metaEvent.kind === 'session_start');
  const meta = metaEvent.meta;
  demand(hasKeys(meta, ['ecu', 'transport', 'mode']) && safeName(meta.ecu));
  demand(['kline', 'can', 'elm_j1850'].includes(meta.transport));
  demand(typeof meta.mode === 'string' && meta.mode.length <= 64);
  demand(meta.ecu === b.ecu.id && meta.transport === b.session.transport);
  demand(hasKeys(connect, ['kind', 'name', 'detail']) && connect.kind === 'action' && connect.name === 'connect');
  demand(hasKeys(connect.detail, ['ok', 'protocol', 'init']) && connect.detail.ok === true);
  demand(typeof connect.detail.protocol === 'string' && connect.detail.protocol.length <= 64);
  demand(typeof connect.detail.init === 'string' && connect.detail.init.length <= 64);
  demand(hasKeys(read, ['kind', 'name', 'detail']) && read.kind === 'action' && read.name === 'memory_read_complete');
  demand(hasKeys(read.detail, ['region', 'size', 'sha256']));
  const frames = events.slice(1, -2);
  demand(frames.length >= 2 && frames.length <= 12);
  demand(frames.some(f => f.dir === 'tx') && frames.some(f => f.dir === 'rx'));
  for (const f of frames) {
    demand(hasKeys(f, ['kind', 'dir', 'hex']) && f.kind === 'frame' && ['tx', 'rx'].includes(f.dir));
    demand(typeof f.hex === 'string' && f.hex.length <= 128 && /^[0-9a-fA-F]{2}(?: ?[0-9a-fA-F]{2})*$/.test(f.hex));
  }
  const region = read.detail.region, size = read.detail.size, imageHash = read.detail.sha256;
  demand(safeName(region) && Number.isSafeInteger(size) && size > 0);
  demand(typeof imageHash === 'string' && /^[0-9a-fA-F]{64}$/.test(imageHash));
  demand(Object.hasOwn(catalog, meta.ecu));
  const profile = catalog[meta.ecu];
  demand(b.ecu.catalog_fingerprint === profile.fingerprint);
  demand(Object.hasOwn(profile.regions, region) && profile.regions[region] === size);
  const claim = b.claims.memory_read;
  demand(claim && claim.events === 1 && claim.frames === 0 && claim.region === region
      && claim.size === size && claim.image_sha256 === imageHash);
  demand(claim.digest === await sha256(encoder.encode(canonical([read]))));
  // Do not store the raw handshake, image hash, free text or supplied bundle.
  return { ecu: meta.ecu, region, id: b.id, install_marker: b.install.marker,
           capture_sha256: b.session.capture_sha256, claim_digest: claim.digest,
           fingerprint: profile.fingerprint };
}

function sameSecret(actual, expected) {
  const a = encoder.encode(actual), b = encoder.encode(expected);
  let difference = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) difference |= (a[i] || 0) ^ (b[i] || 0);
  return difference === 0;
}
function config(env) {
  if (typeof env.GOB_VALIDATION_TOKEN !== 'string' || env.GOB_VALIDATION_TOKEN.length < 32
      || !/^[0-9a-fA-F]{64}$/.test(env.GOB_SIGNING_SEED || '')
      || !/^[0-9a-fA-F]{64}$/.test(env.GOB_PUBLIC_KEY || '')
      || !safeName(env.GOB_KEY_ID)) throw new Error('service not configured');
}
function stillCompatible(record) {
  return Object.hasOwn(catalog, record.ecu) && catalog[record.ecu].fingerprint === record.fingerprint
    && Object.hasOwn(catalog[record.ecu].regions, record.region);
}
const iso = date => date.toISOString().replace(/\.\d{3}Z$/, 'Z');

async function signedEnvelope(records, sequence, env, now = new Date()) {
  const groups = new Map();
  for (const r of records) {
    if (!groups.has(r.ecu)) groups.set(r.ecu, []);
    groups.get(r.ecu).push(r);
  }
  const promotions = [], base = {};
  for (const [ecu, group] of [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    base[ecu] = catalog[ecu].fingerprint;
    const regions = [...new Set(group.map(r => r.region))].sort();
    promotions.push({ ecu, claim: 'memory_read',
      effects: regions.map(region => ({ target: 'source', value:
        `Authenticated self-reported completed read of region '${region}'; hardware origin and image completeness were not independently verified.` })),
      references: group.sort((a, b) => a.id.localeCompare(b.id)).map(r => ({
        id: r.id, install_marker: r.install_marker, capture_sha256: r.capture_sha256, claim_digest: r.claim_digest })),
      evidence_note: 'Self-reported completed reads; no independent hardware verification; no family-wide confidence or write authorization change.' });
  }
  const promotionDigest = await sha256(encoder.encode(canonical({ p: promotions })));
  const pack = { schema: 'guzzionboard.protocol-update/v1',
    id: `pu-${iso(now).slice(0, 10)}-${promotionDigest.slice(0, 8)}`,
    sequence, issued_at: iso(now), expires_at: iso(new Date(now.getTime() + 400 * 86400000)),
    reviewer: 'automatic authenticated read reports', quorum: 1,
    generator: { tool: 'cloudflare-validation', version: '1' },
    base: { catalog_fingerprints: base }, promotions, refused: [], rejected: [],
    notes: 'Self-reported successful reads; no ECU image or independent physical verification was provided.',
    rules: 'Read-level provenance only. Family confidence, control actions and every write path are unchanged.' };
  const payload = encoder.encode(canonical(pack));
  const privateDer = unhex('302e020100300506032b657004220420' + env.GOB_SIGNING_SEED);
  const privateKey = await crypto.subtle.importKey('pkcs8', privateDer, 'Ed25519', false, ['sign']);
  const signature = await crypto.subtle.sign('Ed25519', privateKey, payload);
  const publicKey = await crypto.subtle.importKey('raw', unhex(env.GOB_PUBLIC_KEY), 'Ed25519', false, ['verify']);
  if (!await crypto.subtle.verify('Ed25519', publicKey, signature, payload)) throw new Error('signing key mismatch');
  const envelope = { schema: 'guzzionboard.protocol-update-envelope/v1', key_id: env.GOB_KEY_ID,
    public_key: env.GOB_PUBLIC_KEY.toLowerCase(), payload: pack,
    signature: hex(signature), payload_sha256: await sha256(payload) };
  const text = JSON.stringify(envelope);
  if (encoder.encode(text).length > MAX_PACK) throw new Error('pack too large');
  return text;
}

async function update(db, env, incoming = null) {
  // Compare-and-swap the *entire* signed snapshot so concurrent Workers can
  // neither lose an accepted report nor reuse/rollback a sequence number.
  for (let attempt = 0; attempt < 8; attempt++) {
    const state = await db.prepare('SELECT sequence, reports, envelope FROM validation_state WHERE id = 1').first();
    if (!state) throw new Error('database schema not initialized');
    const records = JSON.parse(state.reports).filter(stillCompatible);
    if (!incoming && state.envelope) {
      const current = JSON.parse(state.envelope);
      if (Date.parse(current.payload.expires_at) > Date.now() + 30 * 86400000) return current;
    }
    if (incoming) {
      const prior = records.find(r => r.ecu === incoming.ecu && r.region === incoming.region);
      if (prior && prior.id === incoming.id) return { accepted: true, duplicate: true };
      const index = records.indexOf(prior);
      if (index >= 0) records.splice(index, 1);
      records.push(incoming);
    }
    if (!records.length) return null;
    const sequence = state.sequence + 1;
    const envelope = await signedEnvelope(records, sequence, env);
    const result = await db.prepare('UPDATE validation_state SET sequence = ?, reports = ?, envelope = ? WHERE id = 1 AND sequence = ?')
      .bind(sequence, JSON.stringify(records), envelope, state.sequence).run();
    if (result.meta.changes === 1) return incoming ? { accepted: true, duplicate: false, sequence } : JSON.parse(envelope);
  }
  throw new Error('concurrent updates, retry later');
}
function reply(status, value) {
  return new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' } });
}
export default {
  async fetch(request, env) {
    try {
      const { pathname, search } = new URL(request.url);
      if (search) return reply(404, { error: 'not found' });
      if (request.method === 'GET' && pathname === '/protocol-update.json') {
        const row = await env.DB.prepare('SELECT envelope FROM validation_state WHERE id = 1').first();
        if (!row || !row.envelope) return reply(404, { error: 'no update yet' });
        let envelope = JSON.parse(row.envelope);
        if (Date.parse(envelope.payload.expires_at) <= Date.now() + 30 * 86400000) {
          config(env);
          envelope = await update(env.DB, env);
          if (!envelope) return reply(404, { error: 'no compatible update' });
        }
        return reply(200, envelope);
      }
      if (request.method === 'POST' && pathname === '/v1/confirmations') {
        config(env);
        if (!sameSecret(request.headers.get('Authorization') || '', `Bearer ${env.GOB_VALIDATION_TOKEN}`)) return reply(401, { error: 'unauthorized' });
        const report = JSON.parse(await boundedBody(request));
        const result = await update(env.DB, env, await validateReport(report));
        return reply(result.duplicate ? 200 : 201, result);
      }
      return reply(404, { error: 'not found' });
    } catch (error) {
      if (error instanceof Invalid) return reply(error.message === 'request too large' ? 413 : 400, { error: 'invalid read confirmation' });
      if (error instanceof SyntaxError || error instanceof TypeError) return reply(400, { error: 'invalid read confirmation' });
      return reply(503, { error: 'relay unavailable' });
    }
  }
};
