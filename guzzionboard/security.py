"""SecurityAccess key providers.

KWP2000 service 0x27 is a seed/key handshake: the ECU sends a challenge and
the tester must answer with a key derived by a manufacturer algorithm. Those
algorithms are proprietary and are not published.

**This project does not ship a working key algorithm for any Moto Guzzi ECU,
and does not pretend to.** What it ships is the plumbing:

* a stable :class:`KeyProvider` interface;
* a registry so a provider can be supplied without touching the core;
* a plugin loader that reads a provider from a local file, so anyone who has
  legitimately obtained the algorithm for their own ECU can drop it in;
* one explicitly-unverified *hypothesis* provider for the IAW 5AM, derived
  from two published seed/key pairs and disabled by default.

Why not just guess? Two published samples define infinitely many functions
that fit them. A wrong key costs nothing on the first attempt (the ECU answers
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
# Hypothesis provider: IAW 5AM
# --------------------------------------------------------------------------
#
# Two seed/key pairs are published in the 5am_util verbose output:
#
#     seed 0x27882789 -> key 0xDA786927
#     seed 0x3CA93CAA -> key 0x0E816927
#
# Observations:
#   * the seed is a 16-bit value X followed by X+1;
#   * the low 16 bits of the key are 0x6927 in both samples.
#
# Fitting key_hi = (a * X + b) mod 2^16 to two points yields exactly one (a, b)
# pair, which is *not* evidence - any two points define a line. It is recorded
# here so it can be tested by someone with a bench ECU, and it is marked
# unverified so that nothing uses it by accident.

_A, _B = None, None


def _fit_affine() -> tuple[int, int] | tuple[None, None]:
    x1, k1 = 0x2788, 0xDA78
    x2, k2 = 0x3CA9, 0x0E81
    for a in range(1, 1 << 16):
        if (x1 * a - k1) % 0x10000 == (x2 * a - k2) % 0x10000:
            b = (k1 - x1 * a) % 0x10000
            return a, b
    return None, None


def _iaw5am_hypothesis(seed: bytes) -> bytes:
    global _A, _B
    if _A is None:
        _A, _B = _fit_affine()
    if _A is None:
        raise SecurityUnavailable("5AM hypothesis: no affine fit")
    if len(seed) != 4:
        raise SecurityUnavailable(f"5AM seed should be 4 bytes, got {len(seed)}")
    x = int.from_bytes(seed[:2], "big")
    key_hi = (_A * x + _B) & 0xFFFF
    return key_hi.to_bytes(2, "big") + b"\x69\x27"


register(
    Provider(
        ecu_id="5am",
        name="iaw5am-affine-hypothesis",
        fn=_iaw5am_hypothesis,
        verified=False,
        note=(
            "Fitted to the two seed/key pairs published in the 5am_util verbose "
            "output. Two samples cannot determine the algorithm; this is a "
            "hypothesis to be tested on a bench ECU, not a working key routine. "
            "Expect invalidKey, and be aware that repeated failures can lock the "
            "security gate."
        ),
        source="5am_util verbose transcript",
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
