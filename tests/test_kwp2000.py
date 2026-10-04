"""Protocol layer tests: framing, decoding, services, error paths."""
import pytest

from guzzionboard.protocol.kwp2000 import (
    DTCStatus,
    KWP2000Session,
    NegativeResponse,
    ProtocolError,
    ChecksumError,
    Service,
    TimingParameters,
    apply_scaling,
    checksum,
    decode_dtc_number,
    decode_dtc_response,
    decode_frame,
    decode_raw_value,
    encode_request,
    frame_length,
)


class FakeConnection:
    """Scripted connection: queue raw response frames, inspect what was sent."""

    def __init__(self, responses=()):
        self.sent = []
        self.responses = list(responses)

    def write(self, data):
        self.sent.append(bytes(data))

    def read_frame(self, timeout):
        return self.responses.pop(0) if self.responses else b""

    def close(self):
        pass


# ------------------------------------------------------------- framing

def test_addressed_frame_matches_the_documented_layout():
    # 21 30 (ReadDataByLocalId, rli 0x30) to the ECU from the tester.
    raw = encode_request([0x21, 0x30])
    assert raw[:3] == bytes([0x82, 0x10, 0xF1])
    assert raw[3:5] == bytes([0x21, 0x30])
    assert raw[-1] == checksum(raw[:-1])


def test_short_frame_omits_addresses():
    raw = encode_request([0x3E], addressed=False)
    assert raw == bytes([0x01, 0x3E, 0x3F])


def test_long_payload_uses_the_extra_length_byte():
    payload = list(range(70))
    raw = encode_request(payload)
    assert raw[0] == 0x80          # length bits cleared
    assert raw[3] == 70            # explicit length
    assert decode_frame(raw).payload == bytes(payload)


def test_round_trip_through_decode():
    raw = encode_request([0x1A, 0x80])
    frame = decode_frame(raw)
    assert frame.service == 0x1A
    assert frame.data == b"\x80"
    assert frame.target == 0x10 and frame.source == 0xF1


def test_bad_checksum_is_rejected():
    raw = bytearray(encode_request([0x21, 0x30]))
    raw[-1] ^= 0xFF
    with pytest.raises(ChecksumError):
        decode_frame(bytes(raw))


def test_frame_length_asks_for_more_bytes_when_undecidable():
    assert frame_length(b"") is None
    assert frame_length(b"\x80") is None       # needs the length byte
    assert frame_length(b"\x82") == 6          # 3 header + 2 data + checksum
    assert frame_length(b"\x80\x10\xF1\x05") == 10


def test_truncated_frame_raises():
    with pytest.raises(ProtocolError):
        decode_frame(b"\x82\x10")


def test_empty_payload_is_refused():
    with pytest.raises(ProtocolError):
        encode_request([])


# ------------------------------------------------------------- decoding

def test_decode_raw_value_handles_signed_big_endian():
    assert decode_raw_value(b"\xFF\x9C", signed=True) == -100
    assert decode_raw_value(b"\x01\x2C") == 300
    assert decode_raw_value(b"\x2C\x01", endian="little") == 300


def test_decode_raw_value_rejects_an_out_of_range_slice():
    with pytest.raises(ProtocolError):
        decode_raw_value(b"\x01", offset=0, length=4)


def test_scaling_matches_the_captured_5am_formulas():
    assert apply_scaling(118, bias=-40) == 78          # coolant: raw - 40
    assert apply_scaling(47, scale=0.1) == pytest.approx(4.7)   # throttle: raw/10
    assert apply_scaling(1400, scale=0.001) == pytest.approx(1.4)  # injection: raw/1000
    assert apply_scaling(0, recip=1000) == 0.0         # period style, no divide by zero
    assert apply_scaling(4, recip=1000) == 250.0


# ----------------------------------------------------------------- DTCs

@pytest.mark.parametrize(
    "hi,lo,expected",
    [(0x01, 0x30, "P0130"), (0x05, 0x05, "P0505"), (0x41, 0x23, "C0123"),
     (0x83, 0x01, "B0301"), (0xC0, 0x01, "U0001")],
)
def test_dtc_number_decoding(hi, lo, expected):
    assert decode_dtc_number(hi, lo) == expected


def test_dtc_status_bits():
    stored = DTCStatus(0x2A)
    assert stored.stored and not stored.current
    current = DTCStatus(0x0A)
    assert current.current and not current.stored
    assert DTCStatus(0x60).warning_indicator


def test_decode_dtc_response_reads_every_record():
    payload = bytes([0x58, 0x02, 0x01, 0x30, 0x2A, 0x05, 0x05, 0x24])
    dtcs = decode_dtc_response(payload, {"P0130": "Lambda"})
    assert [d.code for d in dtcs] == ["P0130", "P0505"]
    assert dtcs[0].description == "Lambda"
    assert dtcs[0].status.stored


def test_decode_dtc_response_tolerates_a_truncated_tail():
    # Count claims 2 but only one full record arrived; report what is real.
    payload = bytes([0x58, 0x02, 0x01, 0x30, 0x2A, 0x05])
    assert len(decode_dtc_response(payload)) == 1


def test_decode_dtc_response_rejects_the_wrong_service():
    with pytest.raises(ProtocolError):
        decode_dtc_response(bytes([0x61, 0x30]))


# -------------------------------------------------------------- session

def _response(payload):
    """Build an ECU->tester frame."""
    return encode_request(payload, target=0xF1, source=0x10)


def test_session_returns_the_positive_response():
    conn = FakeConnection([_response([0x61, 0x30, 0x04, 0xDE])])
    session = KWP2000Session(connection=conn)
    assert session.read_data_by_local_id(0x30) == b"\x04\xDE"
    assert conn.sent[0] == encode_request([0x21, 0x30])


def test_negative_response_raises_with_the_decoded_reason():
    conn = FakeConnection([_response([0x7F, 0x10, 0x22])])
    session = KWP2000Session(connection=conn)
    with pytest.raises(NegativeResponse) as exc:
        session.request([Service.START_DIAGNOSTIC_SESSION, 0x85])
    assert exc.value.code == 0x22
    assert "conditions not correct" in str(exc.value).lower()


def test_response_pending_is_retried_transparently():
    conn = FakeConnection([
        _response([0x7F, 0x21, 0x78]),          # please wait
        _response([0x7F, 0x21, 0x78]),          # still waiting
        _response([0x61, 0x33, 0x76]),          # finally
    ])
    session = KWP2000Session(connection=conn)
    assert session.read_data_by_local_id(0x33) == b"\x76"


def test_response_pending_eventually_gives_up():
    conn = FakeConnection([_response([0x7F, 0x21, 0x78])] * 10)
    session = KWP2000Session(connection=conn, max_pending_retries=2)
    with pytest.raises(ProtocolError, match="responsePending"):
        session.read_data_by_local_id(0x30)


def test_silence_is_an_error_not_an_empty_value():
    session = KWP2000Session(connection=FakeConnection([]))
    with pytest.raises(ProtocolError, match="no response"):
        session.read_data_by_local_id(0x30)


def test_mismatched_response_service_is_rejected():
    conn = FakeConnection([_response([0x58, 0x00])])
    session = KWP2000Session(connection=conn)
    with pytest.raises(ProtocolError, match="does not answer"):
        session.read_data_by_local_id(0x30)


def test_local_id_echo_is_verified():
    conn = FakeConnection([_response([0x61, 0x31, 0x00])])
    session = KWP2000Session(connection=conn)
    with pytest.raises(ProtocolError, match="echoed"):
        session.read_data_by_local_id(0x30)


def test_try_request_converts_a_rejection_into_none():
    conn = FakeConnection([_response([0x7F, 0x33, 0x11])])
    session = KWP2000Session(connection=conn)
    assert session.routine_results(0x21) is None


def test_write_guard_blocks_a_mutating_service_before_it_is_sent():
    conn = FakeConnection([_response([0x71, 0x21])])
    session = KWP2000Session(connection=conn, write_guard=lambda sid: False)
    with pytest.raises(PermissionError):
        session.start_routine(0x21)
    assert conn.sent == []          # the frame never reached the transport


def test_write_guard_does_not_touch_reads():
    conn = FakeConnection([_response([0x61, 0x30, 0x01])])
    session = KWP2000Session(connection=conn, write_guard=lambda sid: False)
    assert session.read_data_by_local_id(0x30) == b"\x01"


def test_frames_are_handed_to_the_logger_in_both_directions():
    seen = []
    conn = FakeConnection([_response([0x61, 0x30, 0x01])])
    session = KWP2000Session(
        connection=conn, on_frame=lambda d, raw: seen.append((d, raw.hex()))
    )
    session.read_data_by_local_id(0x30)
    assert [d for d, _ in seen] == ["tx", "rx"]


def test_security_access_short_circuits_on_a_zero_seed():
    conn = FakeConnection([_response([0x67, 0x01, 0x00, 0x00])])
    session = KWP2000Session(connection=conn)
    assert session.security_access(0x01, lambda seed: b"\x00\x00") is True
    assert len(conn.sent) == 1      # no key was sent


def test_timing_defaults_are_iso_14230_shaped():
    t = TimingParameters()
    assert t.p2_max >= t.p2_min
    assert t.p3_min > 0
