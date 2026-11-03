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
   sh scripts/deploy_worker.sh
   ```

   The manual equivalent of the production path is
   `npx wrangler deploy --config cloudflare/wrangler.build.toml`; use the script
   so builds of non-production branches do not attempt a production deploy.

   This exact config flag is essential: plain `npx wrangler deploy` at the repo
   root can auto-detect a static project and publish repository files instead of
   the relay. Leave the website Worker's build settings unchanged unless you
   independently review what files its existing static deployment publishes.

   Better: set the deploy command to the branch-aware entry point instead, so a
   build of a pull-request branch does not try to deploy over production:

   ```sh
   sh scripts/deploy_worker.sh
   ```

   It runs `wrangler deploy --config cloudflare/wrangler.build.toml` on the
   production branch and `wrangler versions upload --config …` on every other
   branch, printing the command it chose. See
   [why branch builds fail](#why-the-workers-builds-check-fails-on-a-branch).
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
   The config also pins `[observability] enabled = false` to match the Worker's
   dashboard setting: Cloudflare offers to "update your Wrangler configuration
   to keep deployments in sync", and recording the setting in the file stops a
   deploy from re-applying it behind the dashboard's back. Change both together
   if you ever enable Workers Logs for the relay.
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

## Why the Workers Builds check fails on a branch

A pull request shows red checks named `Workers Builds: guzzionboard` and
`Workers Builds: guzzionboard-validation`, while every build of `main` passes.
That is not a defect in this repository, and the reason is a setting most people
never look at.

Workers Builds runs up to three commands, and **which one runs depends on the
branch**:

| Command | When it runs | Default |
| --- | --- | --- |
| Build command | every build | empty |
| Deploy command | the **production** branch only | `npx wrangler deploy` |
| **Preview command** | every branch that is **not** the production branch | `npx wrangler preview` |

So a branch build never runs the deploy command at all — it runs the preview
command, which defaults to `npx wrangler preview`. That command creates a
[Worker Preview](https://developers.cloudflare.com/workers/previews/), and a
Preview needs its **own** bindings and variables, configured separately from
production. This Worker has none: a Preview of the relay would need a second D1
database, and `preview_urls = false` deliberately keeps the relay off any branch
URL. Without preview settings, `npx wrangler preview` fails, so every branch
build fails, on both Workers — and `main` stays green because the preview
command never runs there. The command announces itself as
*"an open beta command"* and reads a "Preview base config" from the dashboard,
which is the settings the relay does not have and must not acquire. See
[Configuration](https://developers.cloudflare.com/workers/ci-cd/builds/configuration/#preview-command)
and [Build branches](https://developers.cloudflare.com/workers/ci-cd/builds/build-branches/#configure-preview-builds).

What was ruled out, and how:

| Observation | Evidence |
| --- | --- |
| Fails on **every** commit of a branch, including ones that touch nothing deployable | PR #38's commits, all twelve commits of PR #39, and a fresh branch pushed 2026-11-03 fail identically |
| Passes on `main` with the **same tree** that failed on the branch | PR #39 merged as `00a6a70`; its tree is the branch tip `116632a`, whose checks failed, and `00a6a70`'s checks — both Workers included — pass |
| Both Workers fail together | `guzzionboard` (a static site with no configuration in this repository) fails exactly like the relay, so the cause is shared and account-level, not a relay bug |
| Not a bundle problem | `npx wrangler deploy --dry-run --config cloudflare/wrangler.build.toml` uploads 12.92 KiB / 4.58 KiB gzip, one D1 binding, exit 0 |
| Not a repository-size problem | 703 tracked files, 4.1 MB of `web/`, 4.7 MB of `vendor/`; the Worker imports only the 151-byte `cloudflare/catalog.json` |

**Do not read build duration from the check run.** Cloudflare stamps
`started_at` and `completed_at` inside the same second for successful builds
too — build `c0086ccb` on `main` "took" 0 s — so the timestamps carry no
information about how long a build ran. An earlier revision of this document
used an invented "instant failure" as a symptom, and blamed the deploy command;
both were wrong, and no conclusion here rests on them.

**Fix, in the Cloudflare dashboard — a repository change cannot do it:**

1. Workers & Pages → **guzzionboard-validation** → Settings → Build → **Branch
   control**. Either:
   - **uncheck Enable Preview Builds.** Preferred here: the relay has nothing
     worth previewing, branch builds stop running, and no red check appears on a
     pull request at all; or
   - keep preview builds and set the **Preview command** to
     `sh scripts/deploy_worker.sh` (equivalently
     `npx wrangler versions upload --config cloudflare/wrangler.build.toml`).
     Cloudflare documents that swapping `wrangler preview` for
     `wrangler versions upload` makes a branch build store a version instead of
     a Preview. The script is safe in that slot: it sees a non-production
     branch, uploads a version, and never deploys.
2. Repeat for the **guzzionboard** website Worker if its branch checks are also
   noise. That Worker has no configuration in this repository — not in
   `cloudflare/`, not at the root — so its settings exist only in its dashboard
   and its build log is the only place to read them.
3. Keep the **Deploy command** on the relay as `sh scripts/deploy_worker.sh`.
   It only ever runs for `main`, where the script deploys; the branch rule in it
   is a second line of defence, not the mechanism.

Do **not** enable Worker Previews for the relay to make the check pass. A
Preview does not inherit production bindings, so the only way to make one work
is a second D1 database and a second public entry point — and
`tests/test_cloudflare_worker.py` asserts `preview_urls` stays false precisely
so a branch URL can never reach the production database.

Verifying needs one branch push: the production half proves nothing on its own,
which is how the same-tree row above came about — `main` went green while every
branch build stayed red. What each choice looks like on a pull request:

| Setting | What a branch push produces | Production |
| --- | --- | --- |
| Preview builds **off** (option 1) | **no** `Workers Builds` check at all — not green, absent, because nothing runs for that branch | untouched |
| Preview builds on, command `wrangler versions upload` (option 2) | a **green** check; the build stores a version | untouched |
| Preview builds on, default `npx wrangler preview` | a **red** check, on every commit | untouched, but the signal is useless |

An absent check is success here, so read the check list rather than expecting
green ticks: the relay's job is to stay off branch URLs and out of production
until `main` deploys it.

Observed on 2026-11-03, after preview builds were switched off for the relay: a
branch push produced **no** `Workers Builds: guzzionboard-validation` check at
all, while `Workers Builds: guzzionboard` still failed on the same commit. That
is the table above read from real data — the relay is configured as intended,
and the website Worker's preview builds are still on. Reports of one check
should not be read as reports about the other; they are separate Workers with
separate settings.

The checks this repository owns — the Python suite, the desktop-shell UI run,
the platform builds and the `relay` job below — are what actually cover a
change. GitHub reports a pull request in this situation as `MERGEABLE` /
`UNSTABLE` (failing non-required checks) rather than `BLOCKED`.


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
