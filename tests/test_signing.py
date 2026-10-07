"""Ed25519 verification, pinned to the RFC's own test vectors.

A dependency-free signature implementation is only worth having if it is
*correct*, so this suite checks the published known-answer vectors (RFC 8032
section 7.1) rather than only round-tripping our own output, and then checks
the ways a signature can be made to look valid when it is not: a mutated
message, a mutated signature, a non-canonical S value, a truncated key and a
different key that happens to be trusted for another purpose.
"""
from __future__ import annotations

import pytest

from guzzionboard import signing

#: RFC 8032, section 7.1 - (seed, public key, message, signature).
VECTORS = [
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        b"",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e0652249015"
        "55fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        bytes.fromhex("72"),
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
        "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
]


@pytest.mark.parametrize("seed,public,message,signature", VECTORS)
def test_rfc8032_vectors(seed, public, message, signature):
    assert signing.public_key(seed) == public
    assert signing.sign(message, seed) == signature
    assert signing.verify(message, signature, public) is True


@pytest.mark.parametrize("seed,public,message,signature", VECTORS)
def test_a_changed_message_or_signature_never_verifies(seed, public, message, signature):
    assert signing.verify(message + b"!", signature, public) is False
    assert signing.verify(b"!" + message, signature, public) is False
    flipped = bytearray(bytes.fromhex(signature))
    flipped[0] ^= 0x01
    assert signing.verify(message, flipped.hex(), public) is False
    flipped = bytearray(bytes.fromhex(signature))
    flipped[-1] ^= 0x01
    assert signing.verify(message, flipped.hex(), public) is False


def test_a_signature_from_another_key_is_refused():
    message = b"protocol update"
    one = signing.sign(message, "01" * 32)
    other_public = signing.public_key("02" * 32)
    assert signing.verify(message, one, other_public) is False


def test_malformed_input_is_a_refusal_not_a_traceback():
    public = signing.public_key("03" * 32)
    good = signing.sign(b"m", "03" * 32)
    for bad_signature in ("", "zz", "00" * 63, "00" * 65, None, 12345):
        assert signing.verify(b"m", bad_signature, public) is False
    for bad_key in ("", "zz", "00" * 31, "00" * 33, None):
        assert signing.verify(b"m", good, bad_key) is False
    assert signing.is_public_key(public) is True
    assert signing.is_public_key("00" * 31) is False
    for bad_seed in ("", "zz", "00" * 31, "00" * 33):
        with pytest.raises(signing.SignatureError):
            signing.sign(b"m", bad_seed)


def test_a_non_canonical_s_value_is_refused():
    """S must be reduced; accepting S+L is the classic malleability bug."""
    public = signing.public_key("04" * 32)
    signature = bytes.fromhex(signing.sign(b"m", "04" * 32))
    r, s = signature[:32], int.from_bytes(signature[32:], "little")
    malleable = r + (s + signing.L).to_bytes(32, "little")
    assert signing.verify(b"m", malleable.hex(), public) is False


def test_decoding_rejects_encodings_that_are_not_points_on_the_curve():
    from guzzionboard import signing as s

    # A y coordinate with no matching x, and a y >= 2**255-19, must not decode.
    assert s._decode_point(bytes([0x02] + [0x00] * 31)) is None
    assert s._decode_point(bytes([0x00] * 32)) is not None      # y=0 is a point
    assert s._decode_point(b"\xff" * 32) is None
    assert s._decode_point(b"\x00" * 31) is None                # wrong length
    # An R that does not decode is a refusal, not an exception.
    assert signing.verify(b"m", "ff" * 64, signing.public_key("05" * 32)) is False
    # A public key that does not decode is a refusal too.
    assert signing.verify(b"m", signing.sign(b"m", "05" * 32), "ff" * 32) is False


def test_the_canonical_form_is_stable_and_order_independent():
    one = {"b": [1, 2, {"z": None}], "a": "x"}
    two = {"a": "x", "b": [1, 2, {"z": None}]}
    assert signing.canonical_json(one) == signing.canonical_json(two)
    assert b" " not in signing.canonical_json(one)
    # a different value is a different message, so it cannot share a signature
    assert signing.canonical_json({"a": 1}) != signing.canonical_json({"a": "1"})


def test_keyrings_hold_public_keys_only(tmp_path):
    path = tmp_path / "keys.json"
    assert signing.load_keyring(path) == {}      # missing file: an empty keyring
    public = signing.public_key("06" * 32)
    signing.save_keyring(path, {"release": public, "workshop": signing.public_key("07" * 32)})
    keys = signing.load_keyring(path)
    assert keys["release"] == public
    assert signing.public_key("06" * 32) != signing.public_key("07" * 32)

    path.write_text('{"keys": {"bad": "not-a-key"}}')
    with pytest.raises(signing.SignatureError, match="32-byte public key"):
        signing.load_keyring(path)
    path.write_text("{not json")
    with pytest.raises(signing.SignatureError, match="unreadable"):
        signing.load_keyring(path)
