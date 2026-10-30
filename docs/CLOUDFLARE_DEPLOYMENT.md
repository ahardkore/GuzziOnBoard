# Cloudflare deployment: existing `guzzionboard` D1 database

The Cloudflare Worker has been locally synthetic-tested and its public relay
endpoint responds at `https://guzzionboard-validation.aaron-hard11.workers.dev`.
The owner reports running the schema and provisioning runtime values. The D1
contents, authenticated production submission, production signing-key match,
and hardware use have not been independently verified from this workspace.
The owner-provided D1 ID is configured in `cloudflare/wrangler.build.toml`.
Cloudflare Workers cannot run the standalone Python HTTP relay unchanged. This
Worker implements the same submission and signed-update endpoints using D1.

## What this deploys

* `POST /v1/confirmations` accepts an authenticated, bounded minimal read report.
* `GET /protocol-update.json` serves its signed, cumulative update. One report
  suffices for its region; the Worker stores only minimal provenance metadata,
  not the capture, image, image hash, or client-supplied free text. It signs
  again before an update expires when an install fetches it.
* A compare-and-swap D1 row makes concurrent publications atomic and keeps the
  pack sequence monotonic. Back up the D1 database, especially this row; rolling
  it back causes clients to refuse older sequence numbers. `schema.sql` uses
  `CREATE TABLE IF NOT EXISTS` and `INSERT OR IGNORE`; it does not delete
  unrelated tables. Do not manually reset or delete its row after publication.
* Report origins are **self-reported**, not independently verified hardware.
  The published update adds region-specific provenance only, not family-wide
  `verified-bench` confidence, new read paths, or write authorization. The
  only currently eligible profile/region in the shipped catalog is 5AM flash;
  more become eligible only when the app itself has an established read path and
  exact region geometry. Synthetic tests are not hardware validation.

HTTPS protects traffic in transit; the submission token authorizes a client,
not the truth of its report. The current design uses one shared bearer token:
any holder can forge reports and leaking it permits abuse. Rate limits and
monitoring should be configured before general release. Do not bundle that
secret into a public desktop binary or distribute it indiscriminately. Review
[consent and privacy](HOSTED_READ_SHARING.md#consent-and-data) before enabling
uploads. The Worker discards connection frames after validation, but receives
those frames and they may contain identifying bytes; Cloudflare network and
logging systems can see request metadata. Configure log retention appropriately.

## Workers Builds from a phone

The account has a separate existing `guzzionboard` Worker serving a website.
**Do not change or replace that Worker** to deploy the relay. Create a separate
Worker named `guzzionboard-validation` and connect it to this repository using
Workers Builds. The tracked `cloudflare/wrangler.build.toml` identifies the
owner-provided D1 database and `worker.mjs`, has no static assets, and preserves
variables set in the Cloudflare dashboard. It contains no secret values. It is
not an instruction to create or alter any database automatically.

1. In Cloudflare, open **D1 → guzzionboard → Console** and run the contents of
   [`cloudflare/schema.sql`](../cloudflare/schema.sql). The statements use
   `IF NOT EXISTS` and `INSERT OR IGNORE`: they do not delete other tables or
   reset an existing sequence. Back up the database first and verify the selected
   database name and ID before running SQL. The schema is not initialized by a
   Worker deployment.
2. Under **Workers & Pages**, create a new Worker named
   `guzzionboard-validation` and connect this repository. In its build settings
   use the repository root (`/`), leave the build command empty, and set the
   **deploy command** to:

   ```sh
   npx wrangler deploy --config cloudflare/wrangler.build.toml
   ```

   This exact config flag is essential: plain `npx wrangler deploy` at the repo
   root can auto-detect a static project and publish repository files instead of
   the relay. Leave the website Worker's build settings unchanged unless you
   independently review what files its existing static deployment publishes.
   Check the deploy log: it must name `guzzionboard-validation`, include a D1
   `DB` binding, and not upload the repository as static assets. A build token
   must have whatever permissions Cloudflare requires to deploy the Worker and
   use this D1 binding. Never put a Cloudflare API token in chat or source code.
   Connecting an existing Worker to Git does not necessarily start a build. If
   the history is empty, a later push to the configured production branch can
   trigger the first build. Alternatively, use a Cloudflare Deploy Hook and a
   POST request. A Deploy Hook URL is itself a credential: do not share it or
   commit it. A retry option only helps when there is a previous build to retry.
3. On that **validation** Worker, in **Settings → Variables and Secrets**, add:

   | Name | Type | Value |
   | --- | --- | --- |
   | `GOB_KEY_ID` | variable | `release` |
   | `GOB_PUBLIC_KEY` | variable | public key, 64 hex characters |
   | `GOB_SIGNING_SEED` | **secret** | corresponding 64-hex private seed |
   | `GOB_VALIDATION_TOKEN` | **secret** | a strong random token, at least 32 characters |

   Create and back up the key pair and token securely. Provision the **matching**
   public key and seed; the Worker refuses to publish if they differ. Do not
   send either secret in chat or commit it. Apply/deploy the dashboard changes.
   Build settings variables are not the same as runtime variables; these must be
   on the Worker. `keep_vars = true` protects dashboard variables on later Git
   deployments, while Cloudflare preserves encrypted secrets separately.
4. Verify the validation Worker's own HTTPS address, distinct from the website.
   A `GET /protocol-update.json` returning JSON `no update yet` with HTTP 404 is
   expected before the first accepted report. Missing schema produces a 503;
   submissions also return 503 until all required variables and secrets exist.
   Deploying the Worker does not configure existing desktop apps: provision its
   URL and pin the public key on receiving installations, and separately obtain
   consent and provision the token on authorized submitting installations.

This Git-build configuration is account-specific. If the D1 ID changes, review
and update the config; preserve the existing database and monotonic sequence.
Do not reuse the same production D1 for untrusted previews. The configuration
explicitly disables preview URLs; a separate isolated environment is needed for
safe preview tests. Cloudflare access, production secrets, database contents,
and a public Worker URL were not available to verify from this workspace.

## Prepare on an authorized administrator's machine

Commands below run locally on a machine with Cloudflare access; no credentials
or private keys need to be pasted into chat or committed. Install Node.js 22+
and Python 3.11+, clone the current source, then run `npm ci`. Authenticate
Wrangler with your Cloudflare account using `npx wrangler login` in your own
terminal/browser. If you have multiple accounts, select the one containing the
`guzzionboard` D1 database. The script below queries your selected account by
database name; it does not create a new database.

1. Generate a **dedicated** signing key on your secure machine, outside the
   repository (do not overwrite an existing production key):

   ```sh
   python3 scripts/build_protocol_update.py --generate-key release \
     --key-dir "$HOME/.guzzionboard/keys"
   ```

   Keep `release.seed` private. The public `release.pub.json` can be distributed
   over an authenticated channel to app installations and included in a new
   release's trusted public keyring. The Worker uses Ed25519 and verifies that
   its configured public key matches the signing seed before publishing.
2. Generate the catalog manifest and resolve the existing D1 database ID:

   ```sh
   python3 scripts/build_cloudflare_catalog.py --check
   node cloudflare/configure.mjs "$HOME/.guzzionboard/keys/release.pub.json"
   ```

   This creates the ignored `cloudflare/wrangler.deploy.toml` containing only
   the D1 identifier and public key. It is not a secret, but it is account-
   specific. If the catalog check fails, run the script without `--check`,
   review the change, and release a Worker and clients with matching catalogs.
   `cloudflare/wrangler.toml` is **local test configuration only**; never use it
   for production deployment.
3. Initialize the existing database (verify your selected account first):

   ```sh
   npx wrangler d1 execute guzzionboard --remote \
     --config cloudflare/wrangler.deploy.toml --file cloudflare/schema.sql
   ```

4. Provision a random submission token and signing seed as Worker secrets. For
   example, create a private token file and pipe it to Wrangler; never type a
   secret into shell history or commit the file:

   ```sh
   umask 077
   python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "$HOME/.guzzionboard/keys/validation.token"
   npx wrangler secret put GOB_VALIDATION_TOKEN --config cloudflare/wrangler.deploy.toml < "$HOME/.guzzionboard/keys/validation.token"
   npx wrangler secret put GOB_SIGNING_SEED --config cloudflare/wrangler.deploy.toml < "$HOME/.guzzionboard/keys/release.seed"
   ```

   The key ID and public key come from the generated config, not secrets.
   Restrict Cloudflare account and Worker secret access. The signing seed is
   online, unlike the offline manual signing route. Protect the local token
   file or securely remove it after distributing the token to authorized shops.
5. Deploy the Worker:

   ```sh
   npx wrangler deploy --config cloudflare/wrangler.deploy.toml
   ```

   Configure a `workers.dev` hostname or custom domain in Cloudflare. Check
   Workers and D1 usage limits, CPU time, logging and rate limiting for your
   account; local tests do not establish production capacity or cost. Verify
   a synthetic end-to-end test with a clearly labeled test environment first.
6. Updated builds bundle the public key and URL for the hosted relay at
   `https://guzzionboard-validation.aaron-hard11.workers.dev`. For a different
   relay, receiving installs must pin its public key out of band and set
   `GOB_PROTOCOL_UPDATE_URL=https://<your-worker-host>/protocol-update.json`.
   For **submitting** installs, securely provision `GOB_VALIDATION_TOKEN` and
   set the explicit consent flag `GOB_SHARE_READ_VALIDATIONS=1`; set
   `GOB_VALIDATION_URL` only when using a different HTTPS Worker origin. Those installations also need session
   recording enabled. Never distribute the seed or give the token to someone
   who should not be able to submit. Existing app releases must be updated.

A new Worker returns 404 for the update until its first accepted report. The
app checks at startup and every four hours; a current live session is not
changed. A different catalog fingerprint is refused, so coordinate client and
Worker catalog updates. Old reports with stale fingerprints are omitted from
new packs until re-reported. On key rotation, provision the new public pin to
clients before switching the Worker key and retain the D1 sequence. Rotate the
submission token on both Worker and authorized submitters if exposed. Cloudflare
and app operators should define incident response, backup, retention, and
source-distribution procedures before production use.

## Local tests

```sh
npm ci
python3 scripts/build_cloudflare_catalog.py --check
npx wrangler d1 execute guzzionboard --config cloudflare/wrangler.toml --local --file cloudflare/schema.sql
python3 -m pytest tests/test_cloudflare_worker.py
```

The tests use synthetic data; `wrangler --local` creates only local state. The
Python test verifies signatures with the actual desktop code and exercises
single-read acceptance, authentication, tampering, size limits, duplicate and
concurrent submissions, expiration refresh, and source-only effects. For a
local Wrangler server use test-only key/token values via ignored `.dev.vars`;
never use production secrets in a local test.
