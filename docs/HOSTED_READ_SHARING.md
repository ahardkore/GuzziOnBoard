# Hosted read-report sharing

The Cloudflare relay responds at
`https://guzzionboard-validation.aaron-hard11.workers.dev`. Updated app builds
bundle that address and the supplied `release` public key. The operator reports
that the D1 schema and Worker secrets are configured, but authenticated production
submission, a production signature matching that key, and hardware have not yet
been independently verified. Existing releases need an app update. Merely running
the app does not upload reports: a sender also needs consent and a separately,
securely provisioned submission token. No token or signing seed ships in the app.

## What one read can and cannot establish

A completed full-region read on a physical transport, with session logging
and sharing enabled, creates one report. The relay checks its capture structure,
claim digest, catalog fingerprint and exact declared region size. One accepted
report is enough for a signed, cumulative update; recipients with the correct
pinned key and update URL check at startup and every four hours. The installed
catalog is reloaded after application; an active ECU session is unchanged.

The relay publishes **self-reported, region-specific provenance** in the profile.
It does not raise `verified-bench` confidence, authorize a new memory path, or
turn on writing/programming. The source names the reported region. A fingerprint
is a profile revision, not proof of every hardware/firmware/model variant. A
full-length read and hash do not prove a correct or restorable image. A shared
client token authenticates a token holder, not an ECU: a malicious or compromised
client can fabricate a plausible report. A server signature authenticates the
publisher, not the truth or physical origin of that report. Never treat it as
independent physical validation. Synthetic tests of this feature are not
hardware validation.

A report is only generated where an actual read path is already implemented and
permitted and the catalog declares exact region geometry. Research-only reads,
simulators, disabled logging, incomplete reads, oversized logs, and connections
without captured transmit/receive handshake frames cannot generate a report.
Thus this service does not manufacture an undocumented read protocol or overcome
a block where no safe, implemented read path exists. It does not by itself
unlock all bikes or all regions.

## Consent and data

The shop operator must explicitly configure consent and a securely provisioned
token before opening the desktop application or local console server. The URLs
below are optional overrides of the bundled defaults:

```sh
export GOB_SHARE_READ_VALIDATIONS=1
export GOB_VALIDATION_URL=https://YOUR-VALIDATION-HOST  # optional
export GOB_VALIDATION_TOKEN='YOUR-PROVISIONED-TOKEN'
export GOB_PROTOCOL_UPDATE_URL=https://YOUR-VALIDATION-HOST/protocol-update.json  # optional
```

Use a secret manager or protected environment file for the token, not shell
history, Git, or chat. Receiving-only installations need neither the submission
token nor sharing flag; they may override the default update URL if desired. To stop future uploads,
unset the flag or token. Pending files remain under the app data directory in
`protocol/outbox/`; delete those files if withdrawal must also discard retries.
The UI reports whether sharing is configured and how many reports are queued.
A network error leaves the report queued for later retry. There is no automatic
server-side deletion request; operators must contact their relay administrator.

A report contains an anonymous but **persistent, linkable installation marker**,
ECU profile and catalog fingerprint, transport and mode, connection handshake
frames, read region and byte count, and the image's SHA-256. It does not
intentionally include the ECU image, VIN/identity block, vehicle details or
live data. Connection frames are protocol-dependent and **may themselves
contain identifying bytes**; hashes can also enable correlation or guesses
about known images. The HTTPS proxy and host necessarily see network metadata
such as IP addresses. Consent must cover these risks. Uploads may start immediately after a read, so inspect handshake capture formats
before enabling sharing; do not enable uploads where the handshake is sensitive. The relay rejects extra session events and normalizes
bundles before storage, but cannot prevent a malicious client from encoding
sensitive data in otherwise allowed frame fields.

## Cloudflare

A Workers + D1 version is available for the existing database named
`guzzionboard`; see [Cloudflare deployment](CLOUDFLARE_DEPLOYMENT.md).
The operator reports running the D1 schema and configuring the Worker, but
authenticated production submission and signing remain unverified.

## Deploying the standalone relay

1. Run the same application/catalog revision as your clients on a maintained
   host. Generate a signing key on a secure machine with the existing tool:
   `python3 scripts/build_protocol_update.py --generate-key release --key-dir <private-directory>`.
   Protect the seed (it permits publishing updates) and distribute **only** the
   public key through an authenticated channel. Pin that key under the same ID
   in clients, using the desktop Trusted keys panel or the bundled keyring of a
   new app release. Do not fetch and trust a key from the update being verified.
2. Create a high-entropy token (at least 32 characters; use e.g.
   `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` locally).
   Provision it to authorized submitting installations over a secure channel.
   The current implementation uses **one shared token**: all token holders can
   submit and forge reports. There is no per-shop attribution, per-client
   revocation or independent verification. Limit distribution and rotate it
   immediately if exposed. Use a dedicated release key with this trust scope.
3. Provision `GOB_VALIDATION_TOKEN`, `GOB_SIGNING_SEED` (64 hex characters,
   from the seed file) and `GOB_KEY_ID` in a protected service environment.
   Install the package and run as an unprivileged service account:

   ```sh
   python3 -m guzzionboard.validation_service --db /var/lib/guzzionboard/relay.sqlite
   ```

   It listens on `127.0.0.1:8765` by default. The seed must be online for
   automatic signing; that has greater exposure than the offline manual signing
   workflow. Restrict process, secret-file and database access, and protect
   backups. Do not expose this plain HTTP listener to the internet.
4. Put a maintained HTTPS reverse proxy in front. Forward only
   `POST /v1/confirmations` and `GET /protocol-update.json` to the loopback
   listener. Limit request bodies to 64 KiB, add rate/concurrency limits and
   request timeouts, reject unexpected methods, and configure normal TLS
   certificate renewal. Avoid logging authorization headers or request bodies;
   review proxy access-log retention and IP privacy. The built-in relay suppresses
   request logging but does not itself provide TLS, rate limiting, timeouts,
   monitoring, or DDoS protection. Check those at the proxy/firewall.
5. Configure the HTTPS URLs and pinned key on updated clients. The first update
   returns 404 until a report is accepted. Verify a test report and receiving
   install before general rollout. Maintain backups of the SQLite database and
   its monotonically increasing sequence; restoring an old database can cause
   clients to reject replayed or older sequence numbers. The service stores one
   most recent report per ECU profile and region; stale catalog revisions are
   omitted from new packs until reported again. A cumulative pack containing
   incompatible catalog fingerprints will be refused by a recipient, so update
   clients and relay in a coordinated rollout.

Revoking a token requires changing it on the relay and all submitters. Rotate a
signing key by securely provisioning a new key ID/public key to clients first,
then switching the relay seed and ID; retire old pins after the transition. Key
loss or compromise calls for revoking the pin and distributing a replacement
through an authenticated app update or administrator. Preserve/increase the
sequence across rotations. A key or token must never be committed or pasted into
chat. The app is AGPL-3.0: comply with applicable source-distribution and network
interaction obligations when deploying modified versions.
