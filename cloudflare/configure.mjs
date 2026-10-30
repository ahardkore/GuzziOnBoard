// Resolve the existing D1 database by name, without putting credentials in Git.
import { spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = dirname(fileURLToPath(import.meta.url));
const [publicFile, keyId = 'release'] = process.argv.slice(2);
if (!publicFile || !/^[a-zA-Z0-9_-]{1,64}$/.test(keyId)) {
  console.error('Usage: node cloudflare/configure.mjs /path/to/release.pub.json [key-id]');
  process.exit(2);
}
const keys = JSON.parse(readFileSync(resolve(publicFile), 'utf8')).keys;
const publicKey = keys?.[keyId];
if (typeof publicKey !== 'string' || !/^[0-9a-fA-F]{64}$/.test(publicKey)) throw Error('Public key file has no matching key ID');
const wrangler = resolve(dir, '../node_modules/wrangler/bin/wrangler.js');
const result = spawnSync(process.execPath, [wrangler, 'd1', 'list', '--json'], { encoding: 'utf8' });
if (result.status !== 0) {
  console.error('Unable to list your D1 databases. Authenticate Wrangler on this machine and retry.');
  if (result.stderr) console.error(result.stderr);
  process.exit(1);
}
const databases = JSON.parse(result.stdout);
const matches = databases.filter(item => item.name === 'guzzionboard');
if (matches.length !== 1 || !/^[0-9a-f-]{36}$/i.test(matches[0].uuid || '')) throw Error('Expected exactly one D1 database named guzzionboard in the selected account');
const output = `name = "guzzionboard-validation"\nmain = "worker.mjs"\ncompatibility_date = "2025-08-01"\n\n[vars]\nGOB_KEY_ID = "${keyId}"\nGOB_PUBLIC_KEY = "${publicKey.toLowerCase()}"\n\n[[d1_databases]]\nbinding = "DB"\ndatabase_name = "guzzionboard"\ndatabase_id = "${matches[0].uuid}"\n`;
writeFileSync(resolve(dir, 'wrangler.deploy.toml'), output, { mode: 0o600 });
console.log('Created ignored cloudflare/wrangler.deploy.toml using the existing guzzionboard database.');
console.log('Next: initialize the schema, provision secrets and deploy as documented.');
