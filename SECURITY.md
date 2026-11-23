# Security policy

GuzziOnBoard talks to a machine that can hurt people and destroys expensive
parts when it is wrong. Security reports are welcome and taken seriously.

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private reporting:

<https://github.com/ahardkore/GuzziOnBoard/security/advisories/new>

Please include:

* what an attacker gains (drive an ECU? read a local file? forge a signed
  protocol update?),
* the version or commit, and the platform,
* a reproduction that does not need a real motorcycle if at all possible,
* whether it needs a physical adapter, local access, or only a browser.

You will get an acknowledgement, an assessment, and a fix or a reasoned
"working as intended". Please give a reasonable window before public disclosure.

## What is in scope

| Area | Why it matters |
| --- | --- |
| The HTTP API (`guzzionboard/server.py`) | It can drive a connected ECU. The origin check, the desktop token and the loopback default are all load-bearing. |
| The safety gate (`guzzionboard/safety.py`) | Any way to reach a programming service without the acknowledgement and the mode change. |
| Signature verification (`guzzionboard/signing.py`, `protocol_updates.py`) | A forged update pack changes what the app believes about a protocol. |
| Plugin isolation (`checksum_worker.py`, `key_worker.py`) | User-supplied plugins are executed; the containment must hold. |
| The read-sharing relay and Worker (`validation_service.py`, `cloudflare/worker.mjs`) | Accepting or signing a report it should have refused. |
| Link-following and file writes (`desktop.py`, `read_sharing.py`) | Anything that follows a caller's URL or writes outside the data root. |

## What is *not* a vulnerability

These are documented, deliberate design decisions:

* **The hosted demo can drive nothing.** It is a static page; a "finding" that
  it does not reach hardware is not a finding.
* **A loopback bind with no token.** The console server trusts the local
  machine. Binding it to a LAN address is an explicit `--host` choice, and it
  is warned about on startup; anyone on that network can then call the API.
* **Self-declared plugin trust.** A key or checksum plugin that says
  `VERIFIED = True` is reported as such. The app cannot verify a claim about
  someone's own hardware; it isolates the code and reports what it declares.
* **Self-reported read confirmations.** The relay signs provenance, not truth.
  A signed pack says "this install claims it read this region", not "this was
  independently verified".
* **A tracked research binary** (an OEM calibration archive or flash dump).
  These are not secrets and are not served by the website; they are recorded in
  [DynoAI and uploads](docs/DYNOAI_AND_UPLOADS.md). Removing them is a licensing
  question, not a vulnerability.

## Supported versions

This project is pre-1.0 and moves quickly: security fixes land on `main` and in
the next release. The desktop builds attached to the latest GitHub release are
the supported binaries.
