#!/usr/bin/env python3
"""Maintainer tool: turn field confirmations into a signed protocol update.

This is the review bench, not a build step. It runs where the private key
lives, on bundles that arrived through a GitHub issue, and it refuses to emit
anything until every claim can be recomputed from the capture that travels
with it, every promotion has reached quorum on *independent* sessions, and
nothing in the pack reaches outside the read-level allowlist. Read
``docs/PROTOCOL_UPDATES.md`` for the review checklist it enforces.

    # once per release key (keep the seed offline; commit only the public key)
    python3 scripts/build_protocol_update.py --generate-key release --out ~/keys

    # review a directory of submitted bundles (bundle + .session.jsonl pairs)
    python3 scripts/build_protocol_update.py --confirmations ./submitted \\
        --reviewer "your name" --key-id release --seed-file ~/keys/release.seed \\
        --sequence 3 --out dist/protocol-update.json

    # what the maintainer does with the result
    gh release upload protocol-updates dist/protocol-update.json

    # two publication routes, same promotions
    --apply-catalog   # commit the change; reaches every user in a release
    (the signed pack) # reaches installs that opted in, without a release

    # verify what you are about to publish
    python3 scripts/build_protocol_update.py --check dist/protocol-update.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guzzionboard import confirmations, protocol_updates, signing   # noqa: E402
from guzzionboard.catalog import ECU_DIR, source_fingerprint        # noqa: E402


def _load_confirmations(directory: Path) -> list[tuple[dict, bytes]]:
    """Every bundle in a directory, paired with its frozen capture."""
    if not directory.is_dir():
        raise SystemExit(f"{directory} is not a directory")
    pairs = []
    problems = []
    for path in sorted(directory.glob("conf-*.json")):
        try:
            bundle = confirmations.load_bundle(path)
            capture = confirmations.capture_for(bundle, directory)
        except confirmations.ConfirmationError as exc:
            problems.append(f"{path.name}: {exc}")
            continue
        pairs.append((bundle, capture))
    for problem in problems:
        print(f"  skipped  {problem}")
    if not pairs:
        raise SystemExit(f"no usable confirmations in {directory}")
    return pairs


def _generate_key(name: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    seed = os.urandom(32).hex()
    seed_file = out / f"{name}.seed"
    if seed_file.exists():
        raise SystemExit(f"{seed_file} already exists; refusing to overwrite a key")
    seed_file.write_text(seed + "\n", encoding="utf-8")
    seed_file.chmod(0o600)
    public = signing.public_key(seed)
    keyring_file = out / f"{name}.pub.json"
    signing.save_keyring(keyring_file, {name: public})
    print(f"private seed : {seed_file}  (mode 600, never commit this file)")
    print(f"public key   : {public}")
    print(f"keyring file : {keyring_file}  (public keys; safe to share)")
    print()
    print("Pin it by committing the public half, for example:")
    print()
    print(f'  {{"keys": {{"{name}": "{public}"}}}}')
    print(f"  -> {ROOT / 'guzzionboard' / 'catalog' / 'protocol_keys.json'}")
    print()
    print("Anyone can also pin the same key locally, without modifying the app:")
    print(f'  {{"keys": {{"{name}": "{public}"}}}}')
    print("  -> ~/.guzzionboard/protocol/keys.json")


def _print_review(pack: dict, envelope: dict) -> None:
    print()
    print(f"pack        : {pack['id']}  (sequence {pack['sequence']})")
    print(f"reviewer    : {pack.get('reviewer') or '(unnamed)'}")
    print(f"valid until : {pack['expires_at']}")
    print(f"payload sha : {envelope['payload_sha256']}")
    print(f"signature   : {envelope['signature'][:32]}… (key {envelope['key_id']})")
    print("base revisions reviewed against:")
    for ecu, fingerprint in pack["base"]["catalog_fingerprints"].items():
        print(f"  {ecu:10s} {fingerprint[:24]}…")
    print("promotions:")
    for promotion in pack["promotions"]:
        print(f"  {promotion['ecu']}/{promotion['claim']}: "
              f"{len(promotion['references'])} independent confirmation(s)")
        for effect in promotion["effects"]:
            print(f"      {effect['target']} = {json.dumps(effect.get('value'))}")
    if pack.get("refused"):
        print("refused (did not reach quorum or was withheld):")
        for entry in pack["refused"]:
            print(f"  {entry['ecu']}/{entry['claim']}: {entry['reason']}")
    if pack.get("rejected"):
        print("rejected before aggregation:")
        for entry in pack["rejected"]:
            print(f"  {entry['id']}: {entry['reason']}")
    print()
    print("Review checklist (docs/PROTOCOL_UPDATES.md): confirm each attached")
    print("capture reproduces its claim digests, that the sessions are hardware")
    print("sessions on distinct machines, and that nothing here reaches outside")
    print("read-level operations.")


def _apply_catalog(pack: dict) -> None:
    fragment = protocol_updates.catalog_fragment(pack)
    for ecu_id, changes in fragment.items():
        path = ECU_DIR / f"{ecu_id}.json"
        if not path.is_file():
            raise SystemExit(f"{path} does not exist; refusing to invent a family")
        raw = json.loads(path.read_text(encoding="utf-8"))
        merged = protocol_updates.merge_catalog_fragment(raw, changes)
        path.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"  updated  {path}")
    print()
    print("Commit the catalog change separately from the pack: the pack is a")
    print("release artifact, the catalog edit is the reviewed source of truth.")


def _check(path: Path, keyring_path: Path | None) -> None:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if keyring_path:
        keyring = signing.load_keyring(keyring_path)
    else:
        keyring = protocol_updates.keyring()
    verified = protocol_updates.verify_envelope(envelope, keyring)
    print(f"{path.name}: signature ok against {verified['key_id']!r}")
    print(f"payload sha256: {verified['sha256']}")
    pack = verified["pack"]
    print(f"promotions: {len(pack['promotions'])} claim(s) for "
          f"{', '.join(sorted(pack['base']['catalog_fingerprints']))}")
    local = protocol_updates.catalog_fingerprints(
        sorted(pack["base"]["catalog_fingerprints"])
    )
    for ecu, want in pack["base"]["catalog_fingerprints"].items():
        state = "matches" if local.get(ecu) == want else "DIFFERS"
        print(f"  catalog {ecu}: {state}")
    print("effects:")
    for promotion in pack["promotions"]:
        for effect in promotion["effects"]:
            print(f"  {promotion['ecu']}/{promotion['claim']}: "
                  f"{effect['target']} = {json.dumps(effect.get('value'))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_protocol_update",
        description=(
            "Aggregate reviewed field confirmations into a signed protocol update"
        ),
    )
    parser.add_argument("--generate-key", metavar="NAME",
                        help="create a release keypair and print the public half")
    parser.add_argument("--out", default="protocol-update.json",
                        help="where to write the signed envelope")
    parser.add_argument("--key-dir", default=".",
                        help="directory for --generate-key output")
    parser.add_argument("--confirmations", metavar="DIR",
                        help="directory of conf-*.json bundles with their captures")
    parser.add_argument("--reviewer", default="", help="who reviewed this pack")
    parser.add_argument("--key-id", default="release", help="name of the signing key")
    parser.add_argument("--seed-file", metavar="FILE",
                        help="file holding the private seed (hex, 32 bytes)")
    parser.add_argument("--sequence", type=int, default=1,
                        help="monotonic pack number; installs refuse replays")
    parser.add_argument("--quorum", type=int, default=2,
                        help="independent confirmations required per claim")
    parser.add_argument("--valid-days", type=int, default=400)
    parser.add_argument("--notes", default="", help="release notes for the pack")
    parser.add_argument("--withhold", action="append", default=[],
                        metavar="ECU/CLAIM", help="refuse a claim you are not ready to publish")
    parser.add_argument("--apply-catalog", action="store_true",
                        help="also write the promotions into the shipped catalog")
    parser.add_argument("--check", metavar="ENVELOPE",
                        help="verify a pack instead of building one")
    parser.add_argument("--keys", metavar="FILE",
                        help="keyring to verify --check against")
    parser.add_argument("--print-catalog-fragment", action="store_true",
                        help="print the catalog edits for the PR route")
    args = parser.parse_args(argv)

    if args.generate_key:
        _generate_key(args.generate_key, Path(args.key_dir).expanduser())
        return 0

    if args.check:
        try:
            _check(
                Path(args.check).expanduser(),
                Path(args.keys).expanduser() if args.keys else None,
            )
        except (protocol_updates.ProtocolUpdateError, signing.SignatureError,
                OSError, json.JSONDecodeError) as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        return 0

    if not args.confirmations:
        parser.error("--confirmations DIR is required (or --generate-key / --check)")
    if not args.seed_file:
        parser.error("--seed-file is required to sign a pack")
    seed = Path(args.seed_file).expanduser().read_text(encoding="utf-8").strip()
    confirmations_in = _load_confirmations(Path(args.confirmations).expanduser())
    print(f"read {len(confirmations_in)} confirmation(s) from {args.confirmations}")

    pack = protocol_updates.build_update_pack(
        confirmations_in,
        quorum=args.quorum,
        reviewer=args.reviewer,
        sequence=args.sequence,
        valid_days=args.valid_days,
        notes=args.notes,
        withhold=tuple(args.withhold),
    )
    unmatched = protocol_updates.unmatched_parameter_promotions(pack)
    if unmatched:
        print("refusing to sign: the pack promotes live parameters these catalog", file=sys.stderr)
        print("definitions do not declare, so the effect would silently do nothing:", file=sys.stderr)
        for entry in unmatched:
            print(
                f"  {entry['ecu']}/{entry['claim']}: {entry['parameter']!r}"
                f" ({entry['ecu']} declares {entry['declares']} live parameter(s))",
                file=sys.stderr,
            )
        print(
            "Either fix the catalog definition or drop the claim with "
            "--withhold <ecu>/<claim>, then rebuild.",
            file=sys.stderr,
        )
        return 2
    envelope = protocol_updates.envelope_for(pack, seed=seed, key_id=args.key_id)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    _print_review(pack, envelope)
    print(f"wrote       : {out}")

    if args.print_catalog_fragment:
        print()
        print(json.dumps(protocol_updates.catalog_fragment(pack), indent=2))
    if args.apply_catalog:
        print()
        print("applying the promotions to the shipped catalog:")
        _apply_catalog(pack)

    print()
    print("Next: publish the pack as a release asset, for example")
    print(f"  gh release upload <tag> {out.name} --clobber")
    print("Installs that pinned the key will pick it up on the next check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
