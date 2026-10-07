"""Ed25519 signatures, in pure Python, for signed protocol updates.

A protocol update changes what the workstation is allowed to do to somebody
else's motorcycle, so it cannot arrive as an unauthenticated JSON file from
the internet. It arrives signed, and this module is the smallest thing that
can check that signature without adding a dependency to a project that has
none: the reference Ed25519 formulation (RFC 8032), verified against the
RFC's own test vectors in ``tests/test_signing.py``.

Only two operations exist here:

* :func:`verify` - what the application does, with a public key;
* :func:`sign` - what ``scripts/build_protocol_update.py`` does, offline, with
  a seed the maintainer keeps out of the repository.

The comparison in :func:`verify` is constant-time-ish (``hmac.compare_digest``)
and every malformed input is a refusal, never a traceback the caller has to
interpret. This is verification, not a general-purpose crypto library: no key
agreement, no encryption, no streaming.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
_B = 256
_D = (-121665 * pow(121666, P - 2, P)) % P
_I = pow(2, (P - 1) // 4, P)


class SignatureError(ValueError):
    """A signature, key or signed payload that cannot be trusted."""


# ---------------------------------------------------------------- arithmetic


def _h(m: bytes) -> bytes:
    return hashlib.sha512(m).digest()


def _bit(h: bytes, i: int) -> int:
    return (h[i // 8] >> (i % 8)) & 1


def _decode_int(data: bytes) -> int:
    return int.from_bytes(data, "little")


def _recover_x(y: int) -> int | None:
    xx = (y * y - 1) * pow(_D * y * y + 1, P - 2, P)
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P != 0:
        x = (x * _I) % P
    if (x * x - xx) % P != 0:
        return None
    if x % 2 != 0:
        x = P - x
    return x


def _y_of_base() -> int:
    return (4 * pow(5, P - 2, P)) % P


def _x_of_base() -> int:
    x = _recover_x(_y_of_base())
    assert x is not None
    return x


_BASE = (_x_of_base(), _y_of_base())


def _edwards(p1: tuple[int, int], p2: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = p1
    x2, y2 = p2
    k = _D * x1 * x2 * y1 * y2
    x3 = (x1 * y2 + x2 * y1) * pow(1 + k, P - 2, P)
    y3 = (y1 * y2 + x1 * x2) * pow(1 - k, P - 2, P)
    return (x3 % P, y3 % P)


def _scalar_mult(point: tuple[int, int], e: int) -> tuple[int, int]:
    if e == 0:
        return (0, 1)
    half = _scalar_mult(point, e // 2)
    result = _edwards(half, half)
    if e & 1:
        result = _edwards(result, point)
    return result


def _encode_point(point: tuple[int, int]) -> bytes:
    x, y = point
    data = bytearray((y % P).to_bytes(32, "little"))
    data[31] |= (x & 1) << 7
    return bytes(data)


def _decode_point(data: bytes) -> tuple[int, int] | None:
    if len(data) != 32:
        return None
    sign = data[31] >> 7
    y = _decode_int(bytes(data[:31]) + bytes([data[31] & 0x7F]))
    if y >= P:
        return None
    x = _recover_x(y)
    if x is None:
        return None
    if x & 1 != sign:
        x = P - x
    # Reject a point that is not on the curve, and the small-order encodings
    # that would otherwise let a signature verify against a degenerate key.
    if (-x * x + y * y - 1 - _D * x * x * y * y) % P != 0:
        return None
    return (x, y)


def _clamp(seed: bytes) -> int:
    digest = _h(seed)
    return (
        2 ** (_B - 2)
        + sum(2**i * _bit(digest, i) for i in range(3, _B - 2))
    )


# ------------------------------------------------------------------ the API


def is_public_key(value: str) -> bool:
    """True if ``value`` is a hex-encoded 32-byte Ed25519 public key."""
    try:
        return len(bytes.fromhex(value)) == 32
    except (ValueError, TypeError):
        return False


def public_key(seed_hex: str) -> str:
    """The public key for a 32-byte seed, hex-encoded."""
    try:
        seed = bytes.fromhex(seed_hex)
    except ValueError as exc:
        raise SignatureError("the private seed must be 64 hex characters") from exc
    if len(seed) != 32:
        raise SignatureError("the private seed must be 64 hex characters")
    return _encode_point(_scalar_mult(_BASE, _clamp(seed))).hex()


def sign(message: bytes, seed_hex: str) -> str:
    """Sign ``message``; returns the 64-byte signature, hex-encoded."""
    try:
        seed = bytes.fromhex(seed_hex)
    except ValueError as exc:
        raise SignatureError("the private seed must be 64 hex characters") from exc
    if len(seed) != 32:
        raise SignatureError("the private seed must be 64 hex characters")
    digest = _h(seed)
    a = _clamp(seed)
    r = _decode_int(_h(digest[32:64] + message))
    big_r = _scalar_mult(_BASE, r)
    encoded_r = _encode_point(big_r)
    k = _decode_int(_h(encoded_r + _encode_point(_scalar_mult(_BASE, a)) + message))
    s = (r + k * a) % L
    return (encoded_r + s.to_bytes(32, "little")).hex()


def verify(message: bytes, signature_hex: str, public_key_hex: str) -> bool:
    """True only if ``signature_hex`` is a valid Ed25519 signature of
    ``message`` under ``public_key_hex``. Never raises for bad input: a
    malformed signature is simply not a valid one."""
    try:
        raw = bytes.fromhex(signature_hex)
    except (ValueError, TypeError):
        return False
    if len(raw) != 64:
        return False
    point_r = _decode_point(raw[:32])
    if point_r is None:
        return False
    s = _decode_int(raw[32:])
    if s >= L:                      # non-canonical S: refuse, do not reduce
        return False
    try:
        point_a = _decode_point(bytes.fromhex(public_key_hex))
    except (ValueError, TypeError):
        return False
    if point_a is None:
        return False
    k = _decode_int(_h(raw[:32] + bytes.fromhex(public_key_hex) + message))
    left = _scalar_mult(_BASE, s)
    right = _edwards(point_r, _scalar_mult(point_a, k))
    return hmac.compare_digest(_encode_point(left), _encode_point(right))


# ------------------------------------------------------------------ keyrings

KEYRING_SCHEMA = "guzzionboard.keyring/v1"


def load_keyring(path: str | Path) -> dict[str, str]:
    """Read ``{"keys": {"name": "<hex public key>"}}``.

    A missing file is an empty keyring, and an empty keyring refuses every
    pack: there is no such thing as a "trust on first use" protocol update.
    """
    path = Path(path).expanduser()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SignatureError(f"{path}: unreadable keyring ({exc})") from exc
    keys = raw.get("keys", {})
    if not isinstance(keys, dict):
        raise SignatureError(f"{path}: 'keys' must be an object")
    out: dict[str, str] = {}
    for name, value in keys.items():
        if not is_public_key(str(value)):
            raise SignatureError(f"{path}: key {name!r} is not a 32-byte public key")
        out[str(name)] = str(value).lower()
    return out


def save_keyring(path: str | Path, keys: dict[str, str]) -> Path:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    for name, value in keys.items():
        if not is_public_key(str(value)):
            raise SignatureError(f"key {name!r} is not a 32-byte public key")
    path.write_text(
        json.dumps(
            {
                "schema": KEYRING_SCHEMA,
                "note": (
                    "Public keys only. A private seed must never be stored "
                    "here or committed to the repository."
                ),
                "keys": {name: str(value).lower() for name, value in keys.items()},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def canonical_json(payload: object) -> bytes:
    """The exact bytes a signature covers.

    Both sides of the pipe serialise the payload the same way, so a signature
    cannot be defeated by re-indenting or re-ordering the JSON on the wire.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
