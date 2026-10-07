# Protocol updates — from one operator's confirmation to every install

## Status

The mechanism described here is implemented, tested and reachable from the
workstation UI and HTTP API. The evidence it distributes is not: the shipped
catalog still lists one family at `verified-bench` (the IAW 5AM, on the
strength of a published capture), and `guzzionboard/catalog/protocol_keys.json`
ships **empty on purpose**. Nothing in this repository is trusted until a
maintainer adds a key to that file, or an operator pins one locally.

That distinction is the whole point of this document. A pipeline is not
evidence, and a signature is not truth — it is a checkable claim about *who
said so*. What the pipeline does is make the claim checkable by everybody who
installs the application, and make the app's own honesty machinery
(confidence levels, the safety gate, the write path) impossible to reach
around.

## The short version

The catalog is data, so "a new verified protocol" is a data change. One
operator's session becomes every user's install like this:

```text
real session           bundle + frozen capture      signed pack            every install
   (this bike)  ──►   (quorum ≥ 2, independent) ──►  (release asset)  ──►  overlay on load
        │                       │                          │                    │
   capture.py            confirmations.py             signing.py          load_catalog()
        │                       │                          │                    │
        └── nothing is uploaded └── a reviewer recomputes  └── no server;  └── revert is one
            by the app              every claim digest        a file + key     file delete
```

Two publication routes carry *identical* promotions, and the code that makes
them identical is `protocol_updates.catalog_fragment()`:

* **the signed pack** — fast, opt-in, applied by installs that fetch it, and
  only after they have pinned a key in advance;
* **the committed catalog change** — slow, but it reaches every install in the
  next release and needs no trust infrastructure at all.

There is no hosted service, no account, and no telemetry. The pack is a file
with a signature; an install that never fetches anything still gets the
promotion through the ordinary catalog.

## 1. Capture — a session that can be checked

`guzzionboard/confirmations.py`. The session log that the workstation already
writes (raw frames, decoded samples, safety decisions, actions) is frozen into
a **confirmation bundle**:

| field | what it is |
| --- | --- |
| `session.capture_sha256` | SHA-256 of the exact JSONL bytes the bundle was built from |
| `claims.<claim>` | one per operation the session actually exercised — `{events, frames, digest, per_key?}` |
| `ecu.catalog_fingerprint` | SHA-256 of the family definition the session ran against |
| `install.marker` | truncated hash of a random per-install id, used only to tell two sessions apart |
| `observed` | operations that happened but are **not** claimable (see below) |
| `verdict` / `disputes` | what the operator reported about the session |

A live session is still appending, so the capture is cut back to the last
complete line: a bundle never freezes a half-written event.

Two rules are enforced at build time, not downstream:

1. **A simulated session confirms nothing about hardware.** `simulator` and
   `cansim` transports are refused when building a bundle, and a bundle whose
   capture says `transport: simulator` is refused when validated. The
   simulator proves the software; it cannot prove a motorcycle.
2. **Writing is not a claimable operation.** `write`, `programming_session`,
   `image_validate`, `erase` and friends are recorded under `observed`, never
   under `claims`. Enabling writes for strangers on the strength of a field
   confirmation is exactly the promotion this project refuses; that path runs
   through [`PHYSICAL_VALIDATION.md`](PHYSICAL_VALIDATION.md).

Nothing is uploaded. The bundle and its capture are two files on the
operator's disk until the operator attaches them to the issue that the
"freeze this session" button pre-fills.

HTTP: `POST /api/confirmations/build`, `POST /api/confirmations/verify`
(recomputes a bundle's claims from the capture it names), and
`POST /api/confirmations/validate` (structural check only).

## 2. Aggregate — quorum, independence, and refusal

`protocol_updates.build_update_pack()` is pure: no files, no network. Every
bundle is validated **and re-derived from its capture**, so a hand-edited claim
cannot be aggregated even if its digests look plausible.

A claim is promoted only when:

* **quorum** — at least two confirmations carry it (`quorum` must be ≥ 2 by
  definition: "one machine, one session and one mistake must not be able to
  change the catalog for everybody");
* **independence** — the confirmations have distinct install markers *and*
  distinct captures, so one operator submitting twice is not a quorum;
* **no dispute** — an operator reporting "this does not reproduce" blocks that
  claim outright; contradictions are refused, never averaged;
* **agreement on the revision** — every confirmation for a family must carry
  the same catalog fingerprint, or the pack is refused and the operator is told
  to rebuild against one release;
* **the reviewer's consent** — `--withhold ECU/CLAIM` refuses a claim that is
  not ready to publish.

Anything that fails is listed in the pack itself under `refused` or
`rejected`, with the reason, together with the promotions that did pass. If
nothing passed, the build fails: there is no "empty update".

## 3. Review — the checklist the tool prints

`scripts/build_protocol_update.py` prints the promotions, the refused and
rejected claims, and this checklist before it will sign anything:

* every attached capture reproduces its claim digests (the reviewer runs
  `verify` on the bundles, or reads the pack's own `references`);
* the sessions are hardware sessions from **distinct machines** — not the same
  operator, not the same file, not a replay;
* nothing in the promotion reaches outside read-level operations.

The reviewer is named in the pack (`--reviewer`), the pack carries the
tool and version that generated it, and `--notes` is free text that ships with
the signature.

## 4. Sign

```bash
# once, on a machine that is not the build machine; the seed stays offline
python3 scripts/build_protocol_update.py --generate-key release --key-dir ~/.guzzionboard/keys
#   → release.seed (mode 600, never commit) + release.pub.json (commit / pin)

python3 scripts/build_protocol_update.py \
    --confirmations ~/.guzzionboard/confirmations \
    --reviewer "whoever reviewed it" --key-id release --seed-file ~/.guzzionboard/keys/release.seed \
    --sequence 3 --notes "7SM live data confirmed on two bikes" \
    --out protocol-update.json
```

The signature is Ed25519 over `canonical_json(payload)`, implemented in
`guzzionboard/signing.py` (pure Python, standard library only — no build-time
crypto dependency is required to *verify* a pack). The envelope carries the
public key it was signed with, so an operator can compare it against a key they
obtained out of band before pinning it.

`--check protocol-update.json --keys <keyring>` verifies a pack the same way an
install does, exits non-zero when anything is wrong, and prints whether the
pack's recorded catalog fingerprints still match the shipped catalog
(`catalog <ecu>: matches` / `DIFFERS`). A pack reviewed against a different
catalog revision is refused at check time — a promotion is never applied to a
definition it did not review.

The tool also refuses to *sign* a pack whose parameter promotions the shipped
definitions do not declare, so a maintainer cannot publish a promise the app
cannot keep; the fix is either the missing definition or `--withhold
<ecu>/<claim>`.

## 5. Distribute — two routes that cannot disagree

| | signed pack | committed catalog change |
| --- | --- | --- |
| reaches | installs that opt in to fetching | every install, next release |
| needs | a pinned key, TLS | nothing |
| latency | minutes | a release |
| produced by | `--out protocol-update.json` | `--print-catalog-fragment` / `--apply-catalog` |

The pack is published as a GitHub release asset, because the artifact is then
public, versioned and independently mirrorable. `DEFAULT_PACK_URL` points at
`releases/latest/download/protocol-update.json`; fetches are bounded
(`MAX_PACK_BYTES` 512 KiB, `MAX_FETCH_SECONDS` 20 s) and only HTTPS or a local
file is accepted — no plain HTTP, no arbitrary schemes.

Route two is the same promotions expressed as catalog-file edits, produced by
`catalog_fragment()` and merged by `merge_catalog_fragment()`. Committing that
change is what makes the promotion part of the source of truth: the pack is a
fast lane, the catalog is the record. Publishing one without the other for long
is a mistake, and the tool prints the fragment every time it builds a pack so
the two can be compared by eye.

## 6. Check and apply — two explicit steps

In the workstation UI this is the **Protocol evidence** panel in the Garage: a
status card (what this install is running, which keys are pinned, where the
pack comes from), the confirmations stored on this machine with *recompute* and
*submit* links, a URL field for the check, an explicit **Apply exactly this
pack (digest…)** button that appears only after a verified preview, and a
**Trusted keys** section for pinning and forgetting keys by hand. Nothing is
fetched until the check button is pressed, and the apply button always sends
back the exact envelope that was previewed.



```text
GET  /api/protocol-updates         →  status, selection, sessions, bundles, claimable/not claimable
POST /api/protocol-updates/check   →  fetch (only here), verify, and describe what would change:
                                      {ok, url, preview{sha256, changes, ...}, envelope}
POST /api/protocol-updates/apply   →  requires expected_sha256 from the preview you were shown
POST /api/protocol-updates/revert  →  forget the pack; the shipped catalog is in force again
POST /api/protocol-updates/pin-key / unpin-key
```

Checking never changes anything, and applying refuses a digest that was not
previewed: a stale or swapped pack cannot be installed with an old consent. The
apply step also does not re-fetch anything behind the operator's back — it
applies the exact envelope the preview showed, or nothing.
Applying writes an overlay under `~/.guzzionboard/protocol/applied/` plus an
`applied.json` record naming the pack, its key, its SHA-256 and the exact
changes; the loader re-validates the overlay on every start, so a hand-edited
overlay is refused rather than trusted.

A running install does not need a restart: `Workstation.reload_catalog()`
makes the promotion live immediately. A session that is already open keeps the
definition it connected with — the ECU on the other end of the cable did not
change when your catalog did.

Applying also enforces that the pack's `sequence` is newer than what is
already applied, so a replayed or downgraded pack is refused, and packs carry
an `expires_at` (default 400 days) so a very old pack cannot be introduced
later as if it were current.

## 7. Keys — pinned in advance, never on first use

* The shipped keyring is `guzzionboard/catalog/protocol_keys.json`; it is
  **empty by design**, and an empty keyring refuses every pack. There is no
  trust-on-first-use anywhere in this path.
* An operator or workshop can pin additional keys in
  `~/.guzzionboard/protocol/keys.json` — a location application updates never
  overwrite, so a fleet can trust its own reviewer without changing the
  shipped file.
* Pinning a key is a local, inspectable file operation ("add this public key").
  The UI's **Trusted keys** panel lists what is pinned (name plus the start of
  the key) with a *forget* button per entry, and takes a new key only as 64 hex
  characters pasted from somewhere you trust — never from the pack you are
  about to install. Replacing an existing name is refused as a single step: you
  forget the old pin first, so the change is two visible actions rather than
  one silent overwrite.
* A key that must be retired is replaced by a new key and a new pack signed
  with it; installs that pinned the old key simply stop accepting new packs
  until they pin the new one, which is the intended failure direction.
* Losing the seed does not brick anything: the catalog route still ships the
  promotion in the next release.

## What a pack may do — and what it may never do

A promotion is a list of **effects**, and the allowlist is short and checked in
three places (build, validate, and load):

| effect target | needs | meaning |
| --- | --- | --- |
| `session.physical_supported` | a `handshake` claim plus one answered operation | allow a physical session at all |
| `memory.read_supported` | `memory_read` / `memory_backup` | allow reading ECU memory |
| `capability` | the claim that exercised it | grant a read-level capability (`identify`, `live`, `dtc_read`, `memory_read`) |
| `capability_confidence` | the claim that exercised it | raise that capability to `verified-bench` / `verified-capture` |
| `parameter_confidence` | a `live` claim | mark parameters that everyone saw as `verified-bench` — only parameters the family already declares |
| `source` | — | attach provenance text |

Everything else is refused, including a vocabulary check that rejects the
words for writing, erasing, programming, flashing, bootloader work, recovery,
actuators, routines, discovery and clearing anywhere in an effect. In
particular:

* **No pack can raise a family's overall confidence.** Control actions gate on
  that level (`guzzionboard/safety.py`), so a pack cannot widen what a
  stranger's motorcycle will answer to. Raising a family to `verified-bench`
  stays a human catalog change with a review trail.
* **No pack can enable writing, erasing or programming.** The effects do not
  exist, the words are rejected, and the write path additionally requires the
  physical-validation protocol.
* **No pack can rewrite scalings, identifiers, actuators or routines.** A
  promotion that could edit those would be a way to smuggle a guessed byte
  past review.
* **No pack may promise a change the definitions cannot carry out.** A
  `parameter_confidence` entry for a channel the family does not declare would
  appear in the preview as a change and do exactly nothing, so the maintainer
  tool refuses to sign such a pack and an install refuses to apply one. The
  message names the family, the claim and the parameter.

## Confidence vocabulary, precisely

| level | means | may a pack set it? |
| --- | --- | --- |
| `verified-bench` | exercised against this ECU on a bench or a bike | yes, for a capability a quorum of confirmations exercised |
| `verified-capture` | derived from a real recorded bus capture | yes |
| `documented` | a primary manual or a mature open implementation says so | no |
| `inferred` | reasonable, unverified | no (and it is not a promotion) |

A pack may only ever *raise* a capability's level to `verified-bench` or
`verified-capture`; `documented` and `inferred` are not outcomes a field
session can produce, and the family-level `confidence` field is never touched.

## What this does not defend against

Being explicit, because a distributed trust mechanism is where hand-waving is
most expensive:

* **A maintainer can sign a bad pack.** The signature proves who published it,
  not that it is right. The effect allowlist, the review checklist and the
  written record (`applied.json`, the pack's own `references`) are what make a
  mistake visible and reversible.
* **Quorum raises the bar; it does not prove truth.** Two independent sessions
  can both be wrong, or an ECU can answer identically for reasons nobody
  understood. That is why the outcome stays read-level.
* **A compromised operator machine can produce a convincing bundle.** It
  cannot produce a signature, and it cannot grant anything the allowlist does
  not contain.
* **Nothing here is a proof for a third party.** A record of a bench session is
  evidence for a reviewer; it is not a certificate, and it is exactly why
  writes stay behind `docs/PHYSICAL_VALIDATION.md`.
* **A local operator can lie to their own install.** They own the machine and
  the overlay; the loader validates what it reads, and the record says which
  pack it came from. The guarantees are about what *this project* will accept
  and publish, not about a hostile owner of the disk.

## Reference

Files and directories:

| path | what it holds |
| --- | --- |
| `guzzionboard/confirmations.py` | bundles: build, verify, store, submission link |
| `guzzionboard/protocol_updates.py` | aggregation, signing, keys, check/apply/revert, catalog fragment |
| `guzzionboard/signing.py` | Ed25519 and canonical JSON (stdlib only) |
| `guzzionboard/catalog/protocol_keys.json` | shipped keyring — empty until a maintainer adds a key |
| `~/.guzzionboard/confirmations/` | bundles (`conf-*.json`) and their frozen captures (`conf-*.session.jsonl`) |
| `~/.guzzionboard/protocol/` | `keys.json`, `applied.json`, `applied/<sha256>.json` |
| `scripts/build_protocol_update.py` | maintainer tool: generate key, build, review, sign, check, print/apply catalog fragment |

Schemas: `guzzionboard.protocol-confirmation/v1`,
`guzzionboard.protocol-update/v1`,
`guzzionboard.protocol-update-envelope/v1`,
`guzzionboard.protocol-overlay/v1`, `guzzionboard.keyring/v1`.

Error vocabulary you will see verbatim, and what each means:

| message | meaning |
| --- | --- |
| `no trusted key is pinned…` | nothing can be applied until a key is pinned; there is no trust-on-first-use |
| `the pack is signed by 'x', which is not in the trusted keyring` | a real key, but not one this install chose |
| `the signature does not verify against 'x'` | the pack was edited, or signed with another key |
| `this pack was reviewed against a different catalog revision…` | the definitions moved since review; update the app or wait for a pack built against this release |
| `pack sequence N is not newer than the applied sequence M` | a replay or a downgrade |
| `… expired on <date>` | stale pack; ask for a current update |
| `<ecu>/<claim>: 1 confirmation(s), quorum is 2` | not enough independent evidence — the refusal is recorded in the pack |
| `the confirmations are not independent: 1 install(s), 1 capture(s)` | the same operator or the same capture twice |
| `a simulated session confirms nothing about hardware` | the capture came from the simulator |
| `this pack promotes live parameters that this catalog revision does not define…` | the promotion would be a no-op; nothing was applied |
| `refusing to sign: … declares 0 live parameter(s)` | the maintainer tool will not sign a promotion the catalog cannot carry out |
