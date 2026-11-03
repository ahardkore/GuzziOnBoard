"""Keihin KMSK16 K-Line decoder: KTM, Husqvarna 449/511 and CCM 450 Adventure.

The KMSK16 is a Keihin ECU that speaks ordinary KWP2000 over a 10,400 baud
K-Line through an L9637D. Nothing about the transport is unusual; what makes it
worth a module is that the *data identifiers* are Keihin's own, not SAE PIDs,
and that a published job description for them exists.

Evidence, pinned in ``docs/KMSK16_KLINE.md``:

* ``gobftald/CCM450-diag`` at ``43104d2cfca9``. The repository has **no licence
  file**, so nothing here is copied from it: the frame layout, service set,
  identifiers, ranges and enumerations are facts, reimplemented from its
  published descriptions with attribution. Two of its accounts of the same
  identifier disagree; both are recorded on the entries below rather than
  resolved by preference.
* ``studies/cyd/src/ecu/ccm450.rs`` — format byte ``0x80`` (physical
  addressing), target ``0x12``, source ``0xF1``.
* ``studies/cyd/src/adapter/l9637.rs`` — ``KWP2000_BAUDRATE = 10_400``.
* ``studies/cyd/src/protocol/kwp2000.rs`` — ``fmt = 0x80 + len + 1`` where
  ``len`` counts the parameters after the service identifier. That is the same
  encoding this repository already implements in
  :mod:`guzzionboard.protocol.kwp2000`, so the codec is reused rather than
  rewritten: only the identifier table and the ECU addresses are new.

What this module does **not** do: connect, transmit, run a routine, clear a
fault or write anything. It decodes frames that were already captured. The
source's security-access key is not reproduced here (it was obtained by brute
force and is supplier-specific), and the programming services are listed as
names only, because a name in a job file is not a verified write sequence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from . import kwp2000

#: ECU address on the KMSK16 (``TARGET_ADDR`` in the source).
ECU_ADDRESS = 0x12
#: Tester address (``SOURCE_ADDR`` in the source).
TESTER_ADDRESS = 0xF1
#: Line speed (``KWP2000_BAUDRATE`` in the source).
BAUD_RATE = 10_400
#: Fast-init half period the source drives before the first frame.
FAST_INIT_HALF_PERIOD_US = 25_000


# --------------------------------------------------------------------------
# Identifier table
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DataId:
    """One ``$22 ReadDataByCommonIdentifier`` entry.

    ``scale``/``bias`` are only present where the value can be derived, and
    ``inferred`` says whether the source states it or it was worked out from the
    declared range and the examples the source recorded. The two are never
    mixed silently: ``basis`` is printed with any derived value.
    """

    identifier: int
    name: str
    symbol: str
    job: str
    kind: str = "real"          # "real", "int" or "bytes"
    unit: str | None = None
    low: float | None = None
    high: float | None = None
    enum: Mapping[int, str] | None = None
    formula: str | None = None
    scale: float | None = None
    bias: float = 0.0
    inferred: bool = True
    basis: str = ""
    conflict: str | None = None
    note: str | None = None


_VOLT = 5 / 1023          # 10-bit ADC counts, from the source's own 0x03FF examples
_RATIO = 2 / 65536        # 0..2 over the 16-bit span


def _did(**kwargs) -> DataId:
    return DataId(**kwargs)


DATA_IDS: dict[int, DataId] = {entry.identifier: entry for entry in (
    _did(identifier=0x0000, name="Throttle position sensor voltage", symbol="THAD",
         job="STATUS_THROTTLE_POSITION_SENSOR_VOLTAGE", unit="V", low=0, high=5,
         scale=_VOLT, basis="10-bit ADC: the source's own example is 0x03FF = 1023"),
    _did(identifier=0x0001, name="Throttle position (angle channel)", symbol="THM",
         job="STATUS_THROTTLE_ANGLE_VOLTAGE", unit="deg", low=0, high=80,
         formula="THM / 80 deg × 100 %", scale=1.0,
         basis="declared range 0–80 degrees, so one count is one degree"),
    _did(identifier=0x0002, name="Manifold pressure sensor voltage", symbol="voltage PM1",
         job="STATUS_INTAKE_MANIFOLD_PRESSURE_SENSOR_VOLTAGE", unit="V", low=0, high=5,
         scale=_VOLT, basis="10-bit ADC: the source's example is 0x03FA = 1018"),
    _did(identifier=0x0003, name="Manifold absolute pressure", symbol="PM1",
         job="STATUS_INTAKE_MANIFOLD_PRESSURE", unit="mbar", low=0, high=65535,
         scale=1.0, basis="declared range covers the 16-bit span exactly"),
    _did(identifier=0x0006, name="Battery voltage at the A/D converter", symbol="UBAT-AD",
         job="STATUS_BATTERY_VOLTAGE_AD_CONVERTER", unit="V", low=0, high=5,
         scale=0.1, basis="the source's own example: 0x0075 = 117 → 11.7 V",
         conflict="the declared range says 0–5 V, which cannot hold its own "
                  "example of 11.7 V — treat the range as wrong and the example as right"),
    _did(identifier=0x0007, name="Battery voltage (scaled channel)", symbol="UBAT",
         job="STATUS_BATTERY_VOLTAGE", unit="V", low=0, high=5,
         scale=0.1, basis="same 0.1 V/count as 0x0006; the source's example is 0x0070 = 112",
         conflict="declared 0–5 V range against a 16-bit channel; the scaling the "
                  "name refers to lives in the ECU, not in this table"),
    _did(identifier=0x0008, name="Coolant temperature sensor voltage", symbol="voltage TW",
         job="STATUS_ENGINE_TEMPERATURE_SENSOR_VOLTAGE", unit="V", low=0, high=5,
         scale=_VOLT, basis="10-bit ADC: the source's example is 0x03FF = 1023"),
    _did(identifier=0x0009, name="Engine coolant temperature", symbol="TW",
         job="STATUS_ENGINE_TEMPERATURE", unit="degC", low=-40, high=215,
         scale=1.0, bias=-40,
         basis="255-count span from −40 to 215 °C, one count per degree",
         note="a 255-wide range on a 2-byte response: the second byte is not "
              "explained by the source, so it is shown and not used"),
    _did(identifier=0x0010, name="Intake air temperature sensor voltage", symbol="voltage TA",
         job="STATUS_INTAKE_AIR_TEMPERATURE_SENSOR_VOLTAGE", unit="V", low=0, high=5,
         scale=_VOLT, basis="10-bit ADC: the source's example is 0x03FF = 1023"),
    _did(identifier=0x0011, name="Intake air temperature", symbol="TA",
         job="STATUS_INTAKE_AIR_TEMPERATURE", unit="degC", low=-40, high=215,
         scale=1.0, bias=-40, basis="same −40 °C offset as the coolant channel",
         note="a 255-wide range on a 2-byte response; the second byte is unexplained"),
    _did(identifier=0x0012, name="Lambda sensor voltage", symbol="VHG1",
         job="STATUS_LAMBDA_SENSOR_VOLTAGE", unit="V", low=0, high=5,
         scale=_VOLT, basis="10-bit ADC: the source's example is 0x03F6 = 1014"),
    _did(identifier=0x0018, name="Second throttle actuator voltage", symbol="",
         job="STATUS_THROTTLE_SENSOR_2_VOLTAGE", unit="V", low=0, high=5,
         scale=_VOLT, basis="declared 0–5 V range and a 10-bit ADC elsewhere"),
    _did(identifier=0x0040, name="Neutral switch", symbol="NEUTRAL",
         job="STATUS_NEUTRALSWITCH", kind="int",
         enum={0x0000: "Neutral", 0x00FF: "Gear engaged"}),
    _did(identifier=0x0053, name="Sport switch input", symbol="MAPCHG",
         job="STATUS_SPORTSWITCH_INPUT", kind="int",
         enum={0x0000: "Standard map", 0x00FF: "Sport map"}),
    _did(identifier=0x0060, name="Fuel pump relay", symbol="FLPR",
         job="FUEL_PUMP_RELAY_STATUS", kind="int",
         enum={0x0000: "OFF", 0x00FF: "ON"}),
    _did(identifier=0x0064, name="Lambda heater", symbol="HG1HT",
         job="STATUS_LAMBDA_SENSOR_HEATING", kind="int",
         enum={0x0000: "OFF", 0x00FF: "ON"}),
    _did(identifier=0x0100, name="Engine speed", symbol="NE",
         job="STATUS_ENGINE_SPEED", unit="rpm", low=0, high=16384,
         scale=0.25, basis="16384 rpm is exactly a quarter of the 16-bit span"),
    _did(identifier=0x0102, name="Short-term fuel trim", symbol="MHG1",
         job="STATUS_LAMBDA_CONTROL_FACTOR", unit="ratio", low=0, high=2,
         scale=_RATIO, basis="declared 0–2 range over the 16-bit span"),
    _did(identifier=0x0107, name="Calculated load", symbol="CLV",
         job="STATUS_CALCULATED_ENGINE_LOAD", unit="%", low=0, high=100,
         formula="CLV = (PM1M / 10103 mbar) × 100 %",
         note="not computed here: the source does not say which identifier "
              "supplies PM1M, and guessing one would invent a number"),
    _did(identifier=0x0110, name="Injector on-time (bank 1)", symbol="TIOUT1",
         job="STATUS_INJECTION_DURATION", unit="us", low=0, high=65535,
         scale=1.0, basis="declared range covers the 16-bit span exactly"),
    _did(identifier=0x0120, name="Ignition timing (bank 1)", symbol="IGAB1",
         job="STATUS_FIRING_ANGLE", unit="deg", low=-64, high=64,
         scale=0.5, bias=-64,
         basis="the source's own example is 0x0080 = 128 → 0°, so 0.5 °/count with a −64° offset"),
    _did(identifier=0x0130, name="Ignition coil dwell (bank 1)", symbol="IGDWELL",
         job="STATUS_IGNITION_CLOSING_TIME", unit="us", low=0, high=65535,
         scale=1.0, basis="declared range covers the 16-bit span exactly"),
    _did(identifier=0x0140, name="Throttle flap angle reference", symbol="THREF",
         job="STATUS_THROTTLE_FLAP_ANGLE_REFERENCE", unit="deg", low=-3276.8, high=3276.8,
         scale=0.1, basis="±3276.8 over a signed 16-bit span is 0.1 °/count"),
    _did(identifier=0x0142, name="Lambda adaption, part load", symbol="MREFHG1",
         job="STATUS_LAMBDA_ADAPTION_PART_LOAD", unit="ratio", low=0, high=2,
         scale=_RATIO, basis="declared 0–2 range over the 16-bit span"),
    _did(identifier=0x0143, name="Lambda adaption, idle", symbol="MREFHG1ID",
         job="STATUS_LAMBDA_ADAPTION_IDLE", unit="ratio", low=0, high=2,
         scale=_RATIO, basis="declared 0–2 range over the 16-bit span"),
    _did(identifier=0x0149, name="Lambda adaption, displayed value", symbol="MRFH1DEC",
         job="STATUS_LAMBDA_ADAPTION_SHOW", unit="ratio", low=0, high=2,
         scale=_RATIO, basis="declared 0–2 range over the 16-bit span"),
    _did(identifier=0x0170, name="Second throttle actual angle", symbol="STHAD",
         job="STATUS_THROTTLE_FLAP_ANGLE_2_ACTUAL_VALUE", unit="deg", low=0, high=80,
         formula="(STHAD − STHADL) / (STHADH / STHADL) × 100 %",
         note="as written the expression divides by a ratio of two A/D values, "
              "which is not a fraction of span; the dimensionally consistent "
              "reading (STHAD − STHADL) / (STHADH − STHADL) needs 0x0172 and "
              "0x0173 as well, and is shown separately and labelled as rewritten"),
    _did(identifier=0x0171, name="Second throttle target angle", symbol="STHTRG",
         job="STATUS_THROTTLE_FLAP_ANGLE_2_SETPOINT", unit="deg", low=0, high=80,
         scale=1.0, basis="declared range 0–80 degrees"),
    _did(identifier=0x0172, name="Second throttle reference, low", symbol="STHADLL",
         job="STATUS_THROTTLE_2_REF_VOLTAGE_MIN", unit="V", low=0, high=5,
         scale=_VOLT, basis="declared 0–5 V and the source's example 0x00E3 = 227"),
    _did(identifier=0x0173, name="Second throttle reference, high", symbol="STDHADHH",
         job="STATUS_THROAT_VALVE_2_REF_VOLTAGE_MAX", unit="V", low=0, high=5,
         scale=_VOLT, basis="declared 0–5 V and the source's example 0x03A1 = 929"),
    _did(identifier=0x0174, name="Second throttle actuator steps, maximum", symbol="STHSTEPH",
         job="STATUS_THROTTLE_VALVE_ACTUATOR_2_STEPS_MAX", unit="steps", low=0, high=32767,
         scale=1.0, basis="declared range is a count, one per step"),
    _did(identifier=0x0185, name="Purge valve duty cycle", symbol="",
         job="STATUS_PURGE_VALVE_DUTY", unit="%", low=0, high=100,
         note="the source lists a 0–100 % range and, next to it, an error text "
              "for an unsupported sub-function — so some ECUs answer this "
              "identifier with a negative response instead of a value"),
    _did(identifier=0x0500, name="Sport switch memory", symbol="RaceMAP SW",
         job="STATUS_SPORTSWITCH_MEMORY", kind="int",
         enum={0x0000: "Standard map", 0x00FF: "Sport map"}),
    _did(identifier=0x0501, name="Over-rev counter, total", symbol="",
         job="STATUS_OVERSPEED_COUNTER_SPECIAL", unit="min", low=0, high=196605,
         scale=3.0, basis="196605 minutes is exactly three times the 16-bit span"),
    # The source numbers these 0x0502–0x0509 and then 0x0510 for area 9: the
    # identifiers skip 0x050A–0x050F, so the list is written out rather than
    # computed from an offset.
    *[_did(identifier=identifier, name=f"Over-rev counter, area {area}", symbol="",
           job=f"STATUS_OVERSPEED_COUNTER_RANGE{area}", unit="s", low=0, high=6553.5,
           conflict="two ranges in the same source: 0–6553.5 s (0.1 s/count) in the "
                    "job entry, 0–196605 min (3 min/count) in the identifier summary. "
                    "Both are recorded; no value is derived from either.")
       for area, identifier in enumerate(
           [0x0502, 0x0503, 0x0504, 0x0505, 0x0506, 0x0507, 0x0508, 0x0509, 0x0510], start=1)],
    _did(identifier=0x1000, name="Test stamp", symbol="", job="READ_TEST_STAMP", kind="bytes",
         note="programming-session stamp, not a measurement"),
    _did(identifier=0x1001, name="DTC environmental condition: engine speed", symbol="",
         job="STATUS_ERROR_MEMORY_ENVIRONMENTAL_CONDITIONS", kind="bytes",
         note="a sub-identifier used inside a fault record, not a live channel"),
    _did(identifier=0x2500, name="ZIF backup read", symbol="PRBHW*B", job="ZIF_BACKUP_READ",
         kind="bytes", note="programming reference block"),
    _did(identifier=0x2501, name="Flash times", symbol="Times", job="FLASH_TIMES_READING",
         kind="bytes", note="programming geometry"),
    _did(identifier=0x2502, name="Hardware reference", symbol="HWREF",
         job="READ_HARDWARE_REFERENCE", kind="bytes", note="ASCII hardware reference"),
    _did(identifier=0x2503, name="Program reference", symbol="ProgrammReferenz",
         job="BAUDRATE_62500", kind="bytes",
         note="12 bytes of ASCII, laid out ZZZ PPP x V BB x h in the source"),
    _did(identifier=0x2504, name="Data reference", symbol="DREF", job="READ_DATA_REFERENCE",
         kind="bytes", note="ASCII data reference"),
    _did(identifier=0x2506, name="Maximum flash block length", symbol="MaximumBlockLength",
         job="FLASH_BLOCK_LENGTH_READING", kind="bytes",
         note="programming geometry, reported with the service identifier included"),
)}

#: ``$31`` routine identifiers the job description names. Read-only ones are
#: marked; the rest are names only, because a job name is not a write sequence.
ROUTINES: dict[int, str] = {
    0x0102: "CheckCodingChecksum — application code (read-only)",
    0x0104: "CheckCodingChecksum — calibration data (read-only)",
    0x0A00: "CheckProgrammingStatus (read-only)",
    0xA600: "Purge control valve ON/OFF test",
    0x9000: "FLASH_DELETE_K16 — erase (not implemented anywhere in this project)",
}

#: Service identifiers named in the job description, with what a positive
#: response would be.
SERVICES: dict[int, tuple[str, int | None]] = {
    0x10: ("StartDiagnosticSession", 0x50),
    0x11: ("EcuReset", 0x51),
    0x14: ("ClearDiagnosticInformation", 0x54),
    0x17: ("ReadStatusOfDiagnosticTroubleCodes", 0x57),
    0x18: ("ReadDiagnosticTroubleCodesByStatus", 0x58),
    0x1A: ("ReadEcuIdentification", 0x5A),
    0x20: ("StopDiagnosticSession", 0x60),
    0x22: ("ReadDataByCommonIdentifier", 0x62),
    0x23: ("ReadMemoryByAddress", 0x63),
    0x27: ("SecurityAccess", 0x67),
    0x31: ("StartRoutineByLocalIdentifier", 0x71),
    0x32: ("StopRoutineByLocalIdentifier", 0x72),
    0x34: ("RequestDownload", 0x74),
    0x35: ("RequestUpload", 0x75),
    0x36: ("TransferData", 0x76),
    0x37: ("RequestTransferExit", 0x77),
    0x3B: ("WriteDataByLocalIdentifier", 0x7B),
    0x3D: ("WriteMemoryByAddress", 0x7D),
    0x3E: ("TesterPresent", 0x7E),
    0x81: ("StartCommunication", 0xC1),
    0x82: ("StopCommunication", 0xC2),
}

_RESPONSE_TO_SERVICE = {positive: service for service, (_, positive) in SERVICES.items()}


# --------------------------------------------------------------------------
# Frames
# --------------------------------------------------------------------------


class DecodeError(Exception):
    """A capture line that cannot be decoded, with the reason it cannot."""


_HEX = set("0123456789abcdefABCDEF")


def parse_hex_line(line: str) -> bytes:
    """Turn one captured line into bytes.

    Accepts the shapes people actually paste: ``80 F1 12 02 62 01 00 5B``,
    ``0x80,0xF1,…``, ``80F112026201005B`` and a leading ``RX:``/``TX:`` or
    ``>``/``<``. A token that is not a hex byte is an error rather than
    something to skip: silently dropping ``ZZ`` or the ``can0`` of a candump
    line would turn a frame that was never transmitted into a frame that
    decodes.
    """
    text = line.strip()
    for marker in ("RX:", "TX:", "rx:", "tx:", ">", "<"):
        if text.startswith(marker):
            text = text[len(marker):].strip()
    tokens = [token for token in text.replace(",", " ").split() if token]
    if not tokens:
        raise DecodeError("no hex bytes in this line")
    compact: list[str] = []
    for token in tokens:
        body = token[2:] if token[:2].lower() == "0x" else token
        if not body or any(ch not in _HEX for ch in body):
            raise DecodeError(f"'{token}' is not a hex byte")
        if len(body) <= 2:
            compact.append(body.rjust(2, "0"))
        elif len(body) % 2 == 0:
            compact.extend(body[index:index + 2] for index in range(0, len(body), 2))
        else:
            raise DecodeError(f"'{token}' has an odd number of hex digits ({len(body)})")
    return bytes(int(token, 16) for token in compact)


@dataclass(frozen=True)
class Decoded:
    """The result of decoding one capture line."""

    headline: str = ""
    line: str = ""
    ok: bool = True
    lines: tuple[str, ...] = ()
    identifier: int | None = None
    raw_value: int | None = None
    value: float | None = None
    state: str | None = None
    reason: str | None = None


def _address_label(address: int | None) -> str:
    return "—" if address is None else f"0x{address:02X}"


def _format_did(data: bytes) -> Decoded:
    """Decode the payload that follows a ``0x62`` positive response."""
    if not data:
        raise DecodeError("positive response carries no data identifier")
    if len(data) < 2:
        raise DecodeError("a data identifier is two bytes; this response has one")
    identifier = (data[0] << 8) | data[1]
    body = data[2:]
    listed = DATA_IDS.get(identifier)
    name = listed.name if listed else "not in the KMSK16 table"
    headline = f"0x{identifier:04X} · {name}"
    lines: list[str] = []
    raw: int | None = None
    value: float | None = None
    state: str | None = None

    if listed is None:
        lines.append(f"Data identifier 0x{identifier:04X} is not one of the "
                     f"{len(DATA_IDS)} the job description names.")
        if body:
            lines.append("Payload bytes: " + " ".join(f"{b:02X}" for b in body))
        return Decoded(ok=True, headline=headline, lines=tuple(lines), identifier=identifier)

    if listed.job:
        lines.append(f"Job: {listed.job}" + (f" · symbol {listed.symbol}" if listed.symbol else ""))
    if not body:
        lines.append("The ECU answered with the identifier and no value bytes.")
        return Decoded(ok=True, headline=headline, lines=tuple(lines), identifier=identifier)

    payload_hex = " ".join(f"{b:02X}" for b in body)
    lines.append(f"Payload: {payload_hex}")

    if listed.kind == "bytes":
        ascii_text = "".join(chr(b) if 32 <= b < 127 else "·" for b in body)
        lines.append(f"ASCII: {ascii_text}")
        if listed.note:
            lines.append(listed.note)
        return Decoded(ok=True, headline=headline, lines=tuple(lines), identifier=identifier)

    if len(body) < 2:
        lines.append("Only one value byte arrived; the table describes a 16-bit value, "
                     "so nothing is derived from half of it.")
        return Decoded(ok=True, headline=headline, lines=tuple(lines), identifier=identifier)

    raw = (body[0] << 8) | body[1]
    lines.append(f"Raw: 0x{raw:04X} = {raw} (big-endian: both descriptions that "
                 "mention byte order say high byte first)")

    if listed.enum:
        state = listed.enum.get(raw)
        lines.append(f"State: {state}" if state
                     else f"State: not one of the declared values "
                          f"(0x0000 / 0x00FF) — {raw} is reported as-is")
    if listed.formula:
        lines.append(f"Formula in the source: {listed.formula}")
    if listed.scale is not None:
        value = raw * listed.scale + listed.bias
        basis = "stated" if not listed.inferred else "inferred"
        lines.append(f"Value ({basis}): {_format_value(value, listed.unit)}"
                     f" — {listed.basis}")
    if listed.low is not None and listed.high is not None:
        lines.append(f"Declared range: {_number(listed.low)}–{_number(listed.high)}"
                     + (f" {listed.unit}" if listed.unit else ""))
        if listed.conflict is None and not (listed.low <= raw <= listed.high):
            lines.append(f"Out of range: the raw value {raw} is outside the declared "
                         "range, so the identifier, the ECU variant or the scaling is "
                         "wrong somewhere. Nothing is corrected here.")
    if listed.conflict:
        lines.append(f"Source conflict: {listed.conflict}")
    if listed.note:
        lines.append(listed.note)
    return Decoded(ok=True, headline=headline, lines=tuple(lines),
                   identifier=identifier, raw_value=raw, value=value, state=state)


def _format_value(value: float, unit: str | None) -> str:
    text = _number(value)
    return f"{text} {unit}" if unit and unit != "ratio" else text


def _number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _format_routine(data: bytes) -> tuple[str, list[str]]:
    """Decode the payload after ``0x71``/``0x72`` (routine result)."""
    lines: list[str] = []
    if not data:
        return "routine accepted, no result bytes", lines
    two = (data[0] << 8) | data[1] if len(data) >= 2 else None
    name = ROUTINES.get(two) if two is not None else None
    identifier = two
    if name is None:
        name = ROUTINES.get(data[0])
        identifier = data[0] if name else None
    if name:
        lines.append(f"Routine 0x{identifier:04X}: {name}")
    else:
        lines.append("Routine identifier not in the KMSK16 list: "
                     + " ".join(f"{b:02X}" for b in data))
    result = data[2:] if identifier == two else data[1:]
    if result:
        lines.append("Result bytes: " + " ".join(f"{b:02X}" for b in result)
                     + " (the job description does not give their layout)")
    return (name or "routine"), lines


def decode_line(line: str) -> Decoded:
    """Decode one captured request or response."""
    try:
        raw = parse_hex_line(line)
    except DecodeError as exc:
        return Decoded(line=line, ok=False, headline="rejected", reason=str(exc))

    if len(raw) < 4:
        return Decoded(line=line, ok=False, headline="rejected",
                       reason=f"a KMSK16 frame is at least 5 bytes; this is {len(raw)}")

    try:
        frame = kwp2000.decode_frame(raw)
    except kwp2000.ProtocolError as exc:
        return Decoded(line=line, ok=False, headline="rejected",
                       reason=f"{exc}; checksum should be "
                              f"0x{kwp2000.checksum(raw[:-1]):02X}")

    payload = frame.payload
    service = payload[0] if payload else -1
    data = payload[1:]
    lines: list[str] = []

    if frame.target not in (ECU_ADDRESS, TESTER_ADDRESS) or frame.source not in (ECU_ADDRESS, TESTER_ADDRESS):
        lines.append(f"Addresses: target 0x{frame.target:02X}, source 0x{frame.source:02X} "
                     f"— the source uses 0x12 (ECU) and 0xF1 (tester)")

    if service == kwp2000.NEGATIVE_RESPONSE:
        if len(data) < 2:
            return Decoded(line=line, ok=False, headline="negative response",
                           reason="a negative response is 7F <service> <code>; this one is short")
        rejected, code = data[0], data[1]
        label = SERVICES.get(rejected, ("unknown service", None))[0]
        text = kwp2000.NRC_TEXT.get(code, f"unknown NRC 0x{code:02X}")
        lines.append(f"Service 0x{rejected:02X} ({label}) was rejected: "
                     f"{text} (0x{code:02X})")
        return Decoded(line=line, ok=True, headline="negative response",
                       lines=tuple(lines), identifier=None)

    if service == 0x62:
        decoded = _format_did(data)
        return Decoded(line=line, ok=decoded.ok, headline=decoded.headline,
                       lines=tuple(lines) + decoded.lines, identifier=decoded.identifier,
                       raw_value=decoded.raw_value, value=decoded.value,
                       state=decoded.state, reason=decoded.reason)

    if service in (0x71, 0x72):
        name, extra = _format_routine(data)
        lines.extend(extra)
        return Decoded(line=line, ok=True, headline=f"routine response · {name}",
                       lines=tuple(lines))

    request_service = _RESPONSE_TO_SERVICE.get(service)
    if request_service is not None:
        label = SERVICES[request_service][0]
        lines.append(f"Positive response to 0x{request_service:02X} {label}")
        if data:
            lines.append("Payload: " + " ".join(f"{b:02X}" for b in data))
        return Decoded(line=line, ok=True, headline=f"0x{service:02X} · {label}",
                       lines=tuple(lines))

    if service in SERVICES:
        label = SERVICES[service][0]
        lines.append(f"Request: 0x{service:02X} {label}")
        if service == 0x22:
            if len(data) >= 2:
                identifier = (data[0] << 8) | data[1]
                listed = DATA_IDS.get(identifier)
                lines.append(f"Asks for 0x{identifier:04X}"
                             + (f" · {listed.name}" if listed else " · not in the table"))
            else:
                lines.append("The request carries no two-byte data identifier.")
        elif service in (0x31, 0x32):
            if len(data) >= 2:
                identifier = (data[0] << 8) | data[1]
                name = ROUTINES.get(identifier) or ROUTINES.get(data[0])
                lines.append(f"Routine 0x{identifier:04X}: "
                             + (name or "not in the KMSK16 list"))
        elif service == 0x27:
            lines.append("Security access — the key is not in this project, and this "
                         "panel never sends anything.")
        elif service == 0x3E:
            lines.append("Tester present — keeps the session alive.")
        return Decoded(line=line, ok=True, headline=f"request · {label}", lines=tuple(lines))

    lines.append(f"Service 0x{service:02X} is not one the KMSK16 job description names.")
    if data:
        lines.append("Payload: " + " ".join(f"{b:02X}" for b in data))
    return Decoded(line=line, ok=True, headline=f"unknown service 0x{service:02X}",
                   lines=tuple(lines))


# --------------------------------------------------------------------------
# A whole paste
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CaptureResult:
    """Every line of a paste, plus anything that needs more than one frame."""

    frames: tuple[Decoded, ...]
    derived: tuple[str, ...] = ()
    accepted: int = 0
    rejected: int = 0

    def lines(self) -> list[str]:
        out: list[str] = []
        for index, frame in enumerate(self.frames, start=1):
            out.append(f"Frame {index}: {frame.line}")
            if frame.ok:
                out.append(frame.headline)
                out.extend(frame.lines)
            else:
                out.append(f"Rejected: {frame.reason}")
            out.append("")
        out.extend(self.derived)
        return out


def decode_capture(text: str) -> CaptureResult:
    """Decode a paste of captured frames, newest frame last."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 100:
        raise DecodeError("limit: 100 frames per decode")
    frames = tuple(decode_line(line) for line in lines)
    accepted = sum(1 for frame in frames if frame.ok)
    raw_by_id = {frame.identifier: frame.raw_value
                 for frame in frames if frame.identifier is not None and frame.raw_value is not None}
    derived: list[str] = []

    had = {identifier: raw_by_id[identifier] for identifier in (0x0170, 0x0172, 0x0173)
           if identifier in raw_by_id}
    if len(had) == 3:
        span = had[0x0173] - had[0x0172]
        if span > 0:
            percent = (had[0x0170] - had[0x0172]) / span * 100
            derived.append(
                "Derived across frames (rewritten, not quoted): second throttle at "
                f"{percent:.1f} % of its reference span, from 0x0170={had[0x0170]}, "
                f"0x0172={had[0x0172]}, 0x0173={had[0x0173]} using "
                "(STHAD − STHADL) / (STHADH − STHADL) × 100 %. The source writes the "
                "divisor as STHADH / STHADL, which would give a meaningless number.")
        else:
            derived.append(
                f"0x0173 ({had[0x0173]}) is not above 0x0172 ({had[0x0172]}), so the "
                "second-throttle reference span is empty and no percentage is derived.")
    elif had:
        missing = ", ".join(f"0x{identifier:04X}" for identifier in sorted({0x0170, 0x0172, 0x0173} - set(had)))
        derived.append(f"Second-throttle percentage needs 0x0170, 0x0172 and 0x0173; "
                       f"this paste is missing {missing}.")
    return CaptureResult(frames=frames, derived=tuple(derived), accepted=accepted,
                         rejected=len(frames) - accepted)
