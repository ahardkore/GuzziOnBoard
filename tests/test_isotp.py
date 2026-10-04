"""ISO 15765-2 segmentation and reassembly."""
import pytest

from guzzionboard.protocol.isotp import (
    FlowStatus, IsoTpError, Reassembler, encode_single, flow_control, segment,
)


def test_short_payload_becomes_one_single_frame():
    frames = segment(b"\x21\x30")
    assert len(frames) == 1
    assert frames[0][:3] == b"\x02\x21\x30"
    assert len(frames[0]) == 8          # padded


def test_long_payload_is_split_into_first_and_consecutive():
    payload = bytes(range(20))
    frames = segment(payload)
    assert frames[0][0] >> 4 == 0x1     # first frame
    assert ((frames[0][0] & 0x0F) << 8) | frames[0][1] == 20
    # 6 bytes in the first frame, then 7 per consecutive frame.
    assert [f[0] for f in frames[1:]] == [0x21, 0x22]
    assert all(len(f) == 8 for f in frames)


def test_single_frame_overflow_is_refused():
    with pytest.raises(IsoTpError):
        encode_single(b"12345678")


def test_payload_beyond_the_classic_limit_is_refused():
    with pytest.raises(IsoTpError):
        segment(b"\x00" * 5000)


def test_round_trip_through_the_reassembler():
    payload = bytes(range(60))
    frames = segment(payload)
    rx = Reassembler()
    out, reply = rx.feed(frames[0])
    assert out is None and reply is not None     # must answer flow control
    assert reply[0] >> 4 == 0x3
    for frame in frames[1:-1]:
        out, _ = rx.feed(frame)
        assert out is None
    out, _ = rx.feed(frames[-1])
    assert out == payload


def test_single_frame_round_trip():
    out, reply = Reassembler().feed(segment(b"\x1A\x80")[0])
    assert out == b"\x1A\x80" and reply is None


def test_sequence_errors_are_caught_not_silently_accepted():
    frames = segment(bytes(range(30)))
    rx = Reassembler()
    rx.feed(frames[0])
    rx.feed(frames[1])
    with pytest.raises(IsoTpError, match="sequence"):
        rx.feed(frames[3])          # skipped frame 2


def test_consecutive_frame_without_a_first_frame_is_rejected():
    with pytest.raises(IsoTpError):
        Reassembler().feed(b"\x21\x00\x00\x00\x00\x00\x00\x00")


def test_flow_control_encoding():
    fc = flow_control(FlowStatus.CONTINUE, block_size=0, st_min=10)
    assert fc[0] == 0x30 and fc[1] == 0 and fc[2] == 10
    assert flow_control(FlowStatus.WAIT)[0] == 0x31


def test_reassembler_resets_cleanly():
    rx = Reassembler()
    rx.feed(segment(bytes(range(30)))[0])
    assert rx.active
    rx.reset()
    assert not rx.active
