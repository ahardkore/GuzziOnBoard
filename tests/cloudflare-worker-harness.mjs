// Synthetic Node + SQLite D1 harness; production Worker runtime is tested separately.
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import worker from '../cloudflare/worker.mjs';
const input = JSON.parse(readFileSync(0, 'utf8'));
const raw = new DatabaseSync(':memory:');
raw.exec(readFileSync(new URL('../cloudflare/schema.sql', import.meta.url), 'utf8'));
class Query {
  constructor(query) { this.query = query; this.values = []; }
  bind(...values) { this.values = values; return this; }
  async first() { const row = raw.prepare(this.query).get(...this.values); await Promise.resolve(); return row || null; }
  async run() { const result = raw.prepare(this.query).run(...this.values); return {meta: {changes: result.changes}}; }
}
const env = { DB: {prepare: q => new Query(q)}, GOB_VALIDATION_TOKEN: 't'.repeat(40),
  GOB_SIGNING_SEED: '11'.repeat(32), GOB_PUBLIC_KEY: input.public_key, GOB_KEY_ID: 'release' };
const url = 'https://worker.example';
function request(report, token = env.GOB_VALIDATION_TOKEN) {
  return new Request(url + '/v1/confirmations', {method: 'POST', headers: {Authorization: 'Bearer ' + token}, body: JSON.stringify(report)});
}
async function call(req) { const response = await worker.fetch(req, env); return [response.status, await response.json()]; }
const expect = (ok, msg) => { if (!ok) throw Error(msg); };
let [status] = await call(new Request(url + '/protocol-update.json'));
expect(status === 404, 'initial GET');
[status] = await call(request(input.report, 'wrong'));
expect(status === 401, 'authorization');
const bad = structuredClone(input.report); bad.capture += '{"kind":"other"}\n';
[status] = await call(request(bad)); expect(status === 400, 'tampered capture');
const stale = structuredClone(input.report); stale.bundle.ecu.catalog_fingerprint = '0'.repeat(64);
[status] = await call(request(stale)); expect(status === 400, 'stale catalog');
const mismatched = { ...env, GOB_PUBLIC_KEY: '00'.repeat(32) };
const mismatchResponse = await worker.fetch(request(input.report), mismatched);
expect(mismatchResponse.status === 503 && raw.prepare('SELECT sequence FROM validation_state').get().sequence === 0, 'signing key mismatch');
const big = structuredClone(input.report); big.capture += 'x'.repeat(70000);
[status] = await call(request(big)); expect(status === 413, 'oversize');
[status] = await call(request(input.report)); expect(status === 201, 'first submission');
[status] = await call(request(input.report)); expect(status === 200, 'idempotency');
// Force interleaving of two writes: CAS must preserve sequence and reject races.
const two = structuredClone(input.report); two.bundle.id = 'conf-aaaaaaaaaaaa';
const three = structuredClone(input.report); three.bundle.id = 'conf-bbbbbbbbbbbb';
const results = await Promise.all([call(request(two)), call(request(three))]);
expect(results.every(result => result[0] === 201), 'concurrent submissions');
let row = raw.prepare('SELECT * FROM validation_state').get();
expect(row.sequence === 3, 'monotonic CAS sequence');
expect(!row.reports.includes('81 10') && !row.reports.includes(input.report.bundle.claims.memory_read.image_sha256), 'raw frames not stored');
let envelope = JSON.parse(row.envelope);
// A stale envelope is re-signed on fetch, preserving all stored reports.
envelope.payload.expires_at = '2000-01-01T00:00:00Z';
raw.prepare('UPDATE validation_state SET envelope = ? WHERE id = 1').run(JSON.stringify(envelope));
[status, envelope] = await call(new Request(url + '/protocol-update.json'));
expect(status === 200 && envelope.payload.sequence === 4, 'automatic refresh');
console.log(JSON.stringify({envelope, row: JSON.parse(row.reports), concurrent: results}));
