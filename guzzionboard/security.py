"""SecurityAccess key providers.

KWP2000 service 0x27 is a seed/key handshake: the ECU sends a challenge and
the tester must answer with a key derived by a manufacturer algorithm. Those
algorithms are often proprietary; some have been published or reverse engineered.

**This project ships one working algorithm - for the IAW 5AM, transcribed
from the open-source 5am_util flashing tool - and no verified algorithm for
any Moto Guzzi ECU.** "Working" means it reproduces every published seed/key
pair and is what a tool that really flashed these ECUs used; "not verified"
means the GuzziOnBoard integration has not confirmed it on hardware, so it
is never selected automatically. Onboard-logger reports a successful Guzzi
5AM write using the reference utility; this is upstream evidence, not a test
of this integration. On top of that:

* a stable :class:`KeyProvider` interface;
* a registry so a provider can be supplied without touching the core;
* a plugin loader that reads a provider from a local file, so anyone who has
  legitimately obtained the algorithm for their own ECU can drop it in;
* the 5AM provider, unverified in this integration and disabled by default.

Why not guess? A wrong key costs nothing on the first attempt (the ECU answers
``invalidKey``), but most ECUs lock out after a few tries and some impose a
timed penalty, so a tool that sprays guesses at a security gate is a tool that
locks people out of their own motorcycle.
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from . import resources

#: Where a user-supplied provider is looked for.
PLUGIN_DIR = Path.home() / ".guzzionboard" / "keys"
#: The interpreter-side worker that runs a plugin outside this process.
WORKER = Path(__file__).with_name("key_worker.py")
WORKER_TIMEOUT_SECONDS = 4
MAX_WORKER_RESPONSE = 64 * 1024
MAX_SEED_BYTES = 8


class SecurityUnavailable(Exception):
    """No usable key provider for this ECU."""


class KeyProvider(Protocol):
    """Turns an ECU seed into the expected key."""

    ecu_id: str
    name: str
    verified: bool

    def __call__(self, seed: bytes) -> bytes: ...


@dataclass
class Provider:
    ecu_id: str
    name: str
    fn: Callable[[bytes], bytes]
    verified: bool = False
    note: str = ""
    source: str = ""
    #: Set for a plugin loaded from disk: it is imported and called in a
    #: separate, contained interpreter (see :mod:`guzzionboard.key_worker`).
    plugin_path: str = ""
    plugin_sha256: str = ""

    def __call__(self, seed: bytes) -> bytes:
        if self.plugin_path:
            return _run_key_worker(Path(self.plugin_path), seed,
                                   expected_sha256=self.plugin_sha256)
        return self.fn(seed)

    def as_dict(self) -> dict:
        return {
            "ecu_id": self.ecu_id, "name": self.name, "verified": self.verified,
            "note": self.note, "source": self.source,
            "plugin_sha256": self.plugin_sha256,
            "isolation": (
                "fresh-python-process+resource-limits+audit-guard"
                if self.plugin_path else "in-process-provider"
            ),
        }


_REGISTRY: dict[str, list[Provider]] = {}


def register(provider: Provider) -> Provider:
    _REGISTRY.setdefault(provider.ecu_id, []).append(provider)
    return provider


def providers_for(ecu_id: str) -> list[Provider]:
    return list(_REGISTRY.get(ecu_id, []))


def best_provider(ecu_id: str, *, allow_unverified: bool = False) -> Provider:
    """Pick a provider, preferring a verified one."""
    candidates = providers_for(ecu_id)
    verified = [p for p in candidates if p.verified]
    if verified:
        return verified[0]
    if candidates and allow_unverified:
        return candidates[0]
    if candidates:
        raise SecurityUnavailable(
            f"{ecu_id}: only unverified key providers are available "
            f"({', '.join(p.name for p in candidates)}). "
            "Enable unverified providers explicitly if you accept the lockout "
            "risk (gate.accept_unverified_key_risk(), allow_unverified_key=True "
            "in-process, or POST /api/security/unverified over HTTP)."
        )
    raise SecurityUnavailable(
        f"{ecu_id}: no SecurityAccess key provider is available.\n"
        f"Drop one into {PLUGIN_DIR}/ as a Python file defining\n"
        "    def key(seed: bytes) -> bytes\n"
        "plus ECU_ID, NAME and VERIFIED module attributes."
    )


def describe_all() -> dict:
    return {
        ecu: [p.as_dict() for p in provs] for ecu, provs in sorted(_REGISTRY.items())
    }


# --------------------------------------------------------------------------
# IAW 5AM: the 5am_util algorithm
# --------------------------------------------------------------------------
#
# Transcribed from calc_key() in 5am_util's main.c (github.com/denandz/5am_util,
# mirrored at codeberg.org/DoI/5am_util) and verified against both seed/key
# pairs that tool's README transcript publishes:
#
#     seed 27 88 27 89 -> key DA 78 69 27
#     seed 3C A9 3C AA -> key 0E 81 69 27
#
# The seed is a 16-bit X followed by X+1. The C code reads the big-endian
# challenge as two little-endian uint16 halves, which is where the byte swaps
# below come from; in seed terms the key is
#
#     (bswap16(X+1) div 161) << 24 | (bswap16(X) mod 200) << 16 | 0x6927
#
# Why it is registered unverified: the algorithm matches the two published
# pairs and onboard-logger reports a successful write to a Guzzi-fitted 5AM
# using the original utility, but this integration has not been hardware-tested.
# The 59M is expected to share it (IAW5xReader/Writer treat 5AM and 59M as one
# family); no such claim is made for the 15x, 7SM or MIU families.


def _iaw5am_key(seed: bytes) -> bytes:
    if len(seed) != 4:
        raise SecurityUnavailable(
            f"IAW 5AM seed should be 4 bytes, got {len(seed)}"
        )
    b0, b1, b2, b3 = seed
    q0 = b3 | (b2 << 8)      # q[0] as a little-endian host sees it
    q1 = b1 | (b0 << 8)      # q[1]
    w = ((q0 >> 8) | (q0 << 8)) & 0xFFFF
    return bytes(((w // 0xA1) & 0xFF, (q1 % 0xC8) & 0xFF, 0x69, 0x27))


register(
    Provider(
        ecu_id="5am",
        name="iaw5am-kwp-divmod",
        fn=_iaw5am_key,
        verified=False,
        note=(
            "Transcribed from calc_key() in 5am_util's main.c and reproducing "
            "both seed/key pairs published in that tool's transcript. It is "
            "the algorithm of a tool that has flashed IAW 5AM ECUs "
            "successfully, including a source-reported Guzzi 5AM write. "
            "GuzziOnBoard has not tested this integration on hardware, so it "
            "is not chosen automatically. Repeated "
            "wrong keys can lock the security gate."
        ),
        source="5am_util main.c calc_key() via docs/PRIOR_ART.md 1.1",
    )
)


# --------------------------------------------------------------------------
# Plugin loading
# --------------------------------------------------------------------------


def worker_command() -> list[str] | None:
    """How to start the isolated key-plugin worker on this installation."""
    if not resources.frozen():
        return [sys.executable, "-I", "-S", "-B", str(WORKER)]
    helper = resources.worker_executable()
    return [str(helper)] if helper is not None else None


def _run_worker(path: Path, request: dict) -> dict:
    from .checksums import ChecksumUnavailable
    from .checksums import _run_worker as run_checksum_worker

    # The command line, environment scrubbing, timeout and response cap are
    # the same problem the checksum worker already solves; reuse them rather
    # than keeping a second, drifting copy of that logic.
    payload = {"plugin": str(path.resolve()), **request}
    try:
        return run_checksum_worker(path, payload, command=worker_command(),
                                   label="key")
    except ChecksumUnavailable as exc:
        raise SecurityUnavailable(str(exc)) from exc


def _run_key_worker(path: Path, seed: bytes, *,
                    expected_sha256: str = "") -> bytes:
    """Call a plugin's ``key()`` in the isolated worker and return its answer."""
    if len(seed) > MAX_SEED_BYTES:
        raise SecurityUnavailable(
            f"SecurityAccess seed is {len(seed)} bytes; {MAX_SEED_BYTES} is the maximum"
        )
    try:
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise SecurityUnavailable(f"cannot read key plugin {path}: {exc}") from exc
    if expected_sha256 and expected != expected_sha256:
        raise SecurityUnavailable(
            "key plugin changed since it was loaded; review it and reload"
        )
    response = _run_worker(path, {"operation": "key", "seed": seed.hex()})
    # The plugin file must not have changed between review/loading and use.
    try:
        current = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise SecurityUnavailable(f"cannot re-read key plugin {path}: {exc}") from exc
    if current != expected:
        raise SecurityUnavailable(
            "key plugin changed while it was loaded; review it and reload"
        )
    key = response.get("key")
    if not isinstance(key, str):
        raise SecurityUnavailable("isolated key plugin returned no key")
    try:
        return bytes.fromhex(key)
    except ValueError as exc:
        raise SecurityUnavailable("isolated key plugin returned a non-hex key") from exc


def load_plugins(directory: str | Path = PLUGIN_DIR) -> list[Provider]:
    """Load every ``*.py`` in ``directory`` as a key provider.

    A plugin module must define::

        ECU_ID = "5am"
        NAME = "my-5am-key"
        VERIFIED = True          # you have tested it on a real ECU
        def key(seed: bytes) -> bytes: ...

    Plugins are *not* imported into this process. Each file is fingerprinted
    and described by a fresh interpreter with resource limits and an audit
    guard (:mod:`guzzionboard.key_worker`); ``key()`` is called there too, so
    a plugin cannot read the session log, open a socket, or reach the
    motorcycle except through the seed/key answer it is asked for. A plugin
    that declares ``VERIFIED = True`` is still only as trustworthy as the file
    the user dropped in; the self-declaration is reported, not adjudicated.

    Returns the providers that loaded; failures are logged, not raised, so one
    broken plugin cannot take the app down.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []

    loaded: list[Provider] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith(".") or path.is_symlink():
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            response = _run_worker(path, {"operation": "describe-key"})
            meta = response["metadata"]
            if not meta.get("has_key"):
                raise SecurityUnavailable("plugin defines no callable key()")
            provider = Provider(
                ecu_id=str(meta["ecu_id"]),
                name=str(meta.get("name") or path.stem),
                fn=lambda seed, _path=path, _digest=digest: _run_key_worker(
                    _path, seed, expected_sha256=_digest),
                verified=bool(meta.get("verified")),
                note=str(meta.get("note") or ""),
                source=str(path),
                plugin_path=str(path),
                plugin_sha256=digest,
            )
        except (SecurityUnavailable, OSError, KeyError, TypeError) as exc:
            import logging

            logging.getLogger(__name__).warning("key plugin %s failed: %s", path, exc)
            continue
        loaded.append(register(provider))
    return loaded
