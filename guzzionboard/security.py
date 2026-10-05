"""SecurityAccess key providers.

KWP2000 service 0x27 is a seed/key handshake: the ECU sends a challenge and
the tester must answer with a key derived by a manufacturer algorithm. Those
algorithms are proprietary and are not published.

**This project ships one working algorithm - for the IAW 5AM, transcribed
from the open-source 5am_util flashing tool - and no verified algorithm for
any Moto Guzzi ECU.** "Working" means it reproduces every published seed/key
pair and is what a tool that really flashed these ECUs used; "not verified"
means nobody has confirmed it unlocks a Guzzi-fitted 5AM, so it is never
selected automatically. On top of that:

* a stable :class:`KeyProvider` interface;
* a registry so a provider can be supplied without touching the core;
* a plugin loader that reads a provider from a local file, so anyone who has
  legitimately obtained the algorithm for their own ECU can drop it in;
* the 5AM provider, unverified on Guzzi hardware and disabled by default.

Why not guess? A wrong key costs nothing on the first attempt (the ECU answers
``invalidKey``), but most ECUs lock out after a few tries and some impose a
timed penalty, so a tool that sprays guesses at a security gate is a tool that
locks people out of their own motorcycle.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

#: Where a user-supplied provider is looked for.
PLUGIN_DIR = Path.home() / ".guzzionboard" / "keys"


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

    def __call__(self, seed: bytes) -> bytes:
        return self.fn(seed)

    def as_dict(self) -> dict:
        return {
            "ecu_id": self.ecu_id, "name": self.name, "verified": self.verified,
            "note": self.note, "source": self.source,
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
            "Enable unverified providers explicitly if you accept the lockout risk."
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
# Why it is registered unverified: it provably matches the two published
# pairs and is the algorithm a successful flashing tool actually shipped, but
# nobody has fed it a seed from a *Guzzi-fitted* 5AM and confirmed the unlock.
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
            "successfully, but it has not been confirmed against a "
            "Guzzi-fitted 5AM, so it is not chosen automatically. Repeated "
            "wrong keys can lock the security gate."
        ),
        source="5am_util main.c calc_key() via docs/PRIOR_ART.md 1.1",
    )
)


# --------------------------------------------------------------------------
# Plugin loading
# --------------------------------------------------------------------------


def load_plugins(directory: str | Path = PLUGIN_DIR) -> list[Provider]:
    """Import every ``*.py`` in ``directory`` as a key provider.

    A plugin module must define::

        ECU_ID = "5am"
        NAME = "my-5am-key"
        VERIFIED = True          # you have tested it on a real ECU
        def key(seed: bytes) -> bytes: ...
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []

    loaded: list[Provider] = []
    for path in sorted(directory.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"guzzikeys_{path.stem}", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            provider = Provider(
                ecu_id=getattr(module, "ECU_ID"),
                name=getattr(module, "NAME", path.stem),
                fn=getattr(module, "key"),
                verified=bool(getattr(module, "VERIFIED", False)),
                note=getattr(module, "NOTE", ""),
                source=str(path),
            )
        except Exception as exc:  # a broken plugin must not kill the app
            import logging

            logging.getLogger(__name__).warning("key plugin %s failed: %s", path, exc)
            continue
        loaded.append(register(provider))
    return loaded
