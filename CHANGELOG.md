# Changelog

Notable changes, newest first. This project does not tag every change; a minor
version bump is a behaviour change worth reading before you connect a bike.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [semantic versioning](https://semver.org/). Pre-1.0, a
minor bump may include a breaking change; it is always called out here.

## [Unreleased]

### Security

- **The console server binds loopback by default.** `serve()` used `0.0.0.0`,
  so `python -m guzzionboard.server` published an unauthenticated API that can
  drive a connected motorcycle to every machine on the network. Pass `--host`
  to widen it; the startup banner now says plainly what that exposes.
- **A malformed `Origin` header is refused instead of crashing the request.**
  `Origin: http://127.0.0.1:abc/` raised `ValueError` out of the guard (a 500 and
  a traceback per request) rather than returning 403.
- **Small-order Ed25519 public keys are rejected.** The identity point and the
  other cofactor-8 encodings decoded as valid keys, and under the identity key
  a signature verifies for *any* message. `is_public_key` now decodes the point
  rather than checking its length.
- **SecurityAccess key plugins no longer run in the app process.** They were
  `exec_module`-ed into the server, with full access to the session log, the
  filesystem and the network. They now run in a fresh interpreter with resource
  limits and an audit hook (`guzzionboard/key_worker.py`), fingerprinted at load
  and re-checked before every use.
- **Session routes resolve symlinks.** A link inside the session directory
  could read any file the process could read; the parent check is now on
  resolved paths.
- **An unexpected failure no longer echoes internal detail** in the 500 body.
- **XDF equations are no longer evaluated with `eval`.** They are parsed and
  walked against a fixed arithmetic table, so a hole in the allowlist regex is
  no longer code execution.

### Changed

- Session recording is thread-safe, and sessions are pruned (200 files / 90
  days) so a long-lived install cannot fill the disk.
- `JobRunner` publishes job state under its lock, so a progress write from the
  job thread and a read from the HTTP handler can no longer tear the dict.
- The Host/Origin/token policy moved to `guzzionboard/http_policy.py`, so the
  question "what may reach this API?" is one 149-line file rather than a
  section of the 2,900-line server. `server` re-exports every public name.
- Key plugins and checksum plugins share one isolated worker. A frozen build
  can only ship one console helper, so the previous split would have made key
  plugins unavailable in every installed build.
- `applied.json`, the applied pack and the revocation list are published
  atomically, so a crash mid-write cannot leave an unreadable overlay.
- A read confirmation the relay can never accept is quarantined
  (`*.rejected`) instead of blocking every later report at the head of the
  outbox.
- The hosted demo answers the desktop, J2534, bus-sniffing and research-export
  routes with a specific refusal instead of "no route"; a route-parity test now
  fails when a server route is added without a demo answer.
- The demo snapshot is cached normally instead of refetched on every visit.
- `desktop.log` rotates at 2 MiB.

### Added

- `docs/API.md`, generated from the live route table and kept in sync by a test.
- `CONTRIBUTING.md`, `SECURITY.md`, this changelog, and a documentation index.
- `tests/test_trust_boundary.py`: the manifest validator, relay authentication
  and refusal paths tested directly rather than incidentally.
- Accessibility: focus is never removed without a visible replacement,
  map cells and editors carry spoken labels, and motion respects
  `prefers-reduced-motion`.
- CI: Python 3.11/3.12/3.13, `ruff`, coverage, the desktop Playwright gate and a
  demo-parity job.

## [0.4.2]

The previously released state. See the git history and the release notes.
