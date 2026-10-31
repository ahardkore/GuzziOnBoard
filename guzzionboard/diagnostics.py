"""Diagnostics service: the layer the UI talks to.

It owns one ECU conversation and enforces the order of operations:

    connect -> identify -> (live data | DTCs | discovery) -> service actions

Nothing that can change the motorcycle happens without a
:class:`~guzzionboard.safety.Decision` and the single-use token it mints.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .catalog import Catalog, EcuProfile, Parameter, load_catalog
from .protocol.legacy_iaw import LegacyIAWSession
from .protocol.kawasaki_er6n import KawasakiER6nSession, decode_kawasaki_value
from .protocol.aster_kline import AsterKLineSession, Versys2012Session, KawasakiKdsResearchSession, Gsxr6002011Session, Gsxr10002004Session, SuzukiGsxrResearchSession, Sv6502003Session, Sv650Ak7Session, decode_versys, decode_gsxr, decode_sv650ak7
from .protocol.honda_cbr600rr import HondaCBR600RRSession, HondaCB500FDashSession, HondaCTX700Session, decode_honda, decode_honda_ctx
from .protocol.honda_pgmfi import HondaPgmfiSession
from .protocol.kawasaki_ninja7 import KawasakiNinja7Session
from .protocol.triumph_daytona import TriumphDaytonaSession
from .protocol.harley_j1850 import HarleyJ1850Session
from .protocol.obd_can import ObdCanSession
from .protocol.harley_delphi_can import HarleyDelphiCanSession
from .protocol.kwp2000 import (
    KWP2000Session,
    NegativeResponse,
    ProtocolError,
    Service,
    TimingParameters,
    apply_scaling,
    decode_raw_value,
)
from .safety import Check, Decision, Mode, Risk, SafetyGate, SafetyViolation
from .sessionlog import NullSessionLog, SessionLog
from .transports.base import (
    Connection,
    InitResult,
    Transport,
    TransportError,
    TransportUnavailable,
)


@dataclass
class Sample:
    """One decoded live value, with the bytes it came from."""

    key: str
    name: str
    local_id: int
    raw: bytes
    value: float | int | None
    unit: str
    text: str = ""
    at: float = field(default_factory=time.time)
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "local_id": self.local_id,
            "raw": self.raw.hex(" "), "value": self.value, "unit": self.unit,
            "text": self.text, "at": self.at, "error": self.error,
        }


@dataclass
class Identity:
    fields: dict = field(default_factory=dict)
    raw: bytes = b""
    ecu_id: str = ""
    family: str = ""

    def as_dict(self) -> dict:
        return {
            "fields": self.fields, "raw": self.raw.hex(" "),
            "ecu_id": self.ecu_id, "family": self.family,
        }


class NotConnected(RuntimeError):
    pass


class DiagnosticsService:
    """One ECU conversation."""

    def __init__(
        self,
        profile: EcuProfile,
        transport: Transport,
        gate: SafetyGate,
        *,
        log: SessionLog | None = None,
        catalog: Catalog | None = None,
    ):
        self.profile = profile
        self.transport = transport
        self.gate = gate
        self.log = log or NullSessionLog()
        self.catalog = catalog or load_catalog()

        self.connection: Connection | None = None
        self.session: KWP2000Session | LegacyIAWSession | None = None
        self.init_result: InitResult | None = None
        self.identity: Identity | None = None
        self.last_samples: dict[str, Sample] = {}
        self.discovered: dict[int, dict] = {}
        #: Actuators currently energised -> deadline (monotonic).
        self.active_outputs: dict[str, float] = {}

        self._lock = threading.RLock()
        self._last_tx = 0.0
        self._stop = threading.Event()
        self._keepalive: threading.Thread | None = None

    # -- lifecycle --------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self.session is not None and self.connection is not None and self.connection.is_open

    def connect(self, *, init_method: str | None = None) -> InitResult:
        with self._lock:
            if self.connected:
                return self.init_result  # type: ignore[return-value]

            if (
                self.transport.is_physical
                and self.profile.session.get("physical_supported") is False
            ):
                reason = self.profile.session.get(
                    "physical_blocked_reason",
                    "the physical diagnostic protocol is not validated",
                )
                raise TransportUnavailable(
                    f"{self.profile.family}: {reason} "
                    "The safety boundary stopped here: no port was opened and no "
                    "request was sent."
                )

            method = init_method or self.profile.kline.get("init", "fast")
            exact_method = self.profile.session.get("protocol")
            if exact_method == "kawasaki-ninja7-can" and init_method is None:
                method = "can"
            if exact_method == "harley-j1850-harleydroid" and (self.transport.name != "elm_j1850" or not self.transport.is_physical or self.gate.mode.value != "read_only"):
                raise TransportUnavailable("Harley J1850 requires the ELM serial transport and read-only mode")
            if exact_method in ("kawasaki-er6n", "triumph-daytona-2012", "harley-j1850-harleydroid", "aster-versys-2012", "kawasaki-kds-research", "aster-gsxr600-2011", "suzuki-gsxr1000-2004", "suzuki-sv650ak7-2007", "suzuki-sv650-2003", "suzuki-sds-gsxr-research", "honda-cbr600rr-2005", "honda-cb500f-dashble", "honda-ctx700-minidash", "honda-pgmfi-research") and method != exact_method:
                raise TransportUnavailable(f"{self.profile.family} requires its profile-default initialization")
            if exact_method in ("honda-cbr600rr-2005", "honda-cb500f-dashble", "honda-ctx700-minidash", "honda-pgmfi-research"):
                expected = {"honda-cbr600rr-2005": "honda_cbr600rr_2005", "honda-cb500f-dashble": "honda_cb500f_dashble", "honda-ctx700-minidash": "honda_ctx700_minidash", "honda-pgmfi-research": "honda_pgmfi_research"}[exact_method]
                if (self.profile.id != expected or self.transport.name != "kline"
                        or not self.transport.is_physical or self.gate.mode != Mode.READ_ONLY
                        or getattr(self.transport, "baud", 10400) != 10400):
                    raise TransportUnavailable("Honda source-scoped profile requires 10400 baud, physical K-Line and read-only mode")
            if exact_method in ("aster-versys-2012", "kawasaki-kds-research", "aster-gsxr600-2011", "suzuki-gsxr1000-2004", "suzuki-sv650ak7-2007", "suzuki-sv650-2003", "suzuki-sds-gsxr-research"):
                expected = {"aster-versys-2012": "kawasaki_versys650_2012", "kawasaki-kds-research": "kawasaki_kds_research",
                            "aster-gsxr600-2011": "suzuki_gsxr600_2011", "suzuki-gsxr1000-2004": "suzuki_gsxr1000_2004", "suzuki-sv650ak7-2007": "suzuki_sv650ak7_2007", "suzuki-sv650-2003": "suzuki_sv650_2003", "suzuki-sds-gsxr-research": "suzuki_sds_gsxr_research"}[exact_method]
                if (self.profile.id != expected or self.transport.name != "kline"
                        or not self.transport.is_physical or self.gate.mode != Mode.READ_ONLY
                        or getattr(self.transport, "baud", 10400) != 10400):
                    raise TransportUnavailable("Source-scoped K-Line requires its exact profile, 10400 baud, and read-only physical transport")
            if exact_method == "generic-obd-can-11bit":
                tx = getattr(self.transport, "tx_id", None)
                if (self.profile.id != "generic_obd_can_11bit" or self.transport.name != "can"
                        or not self.transport.is_physical or self.gate.mode != Mode.READ_ONLY
                        or init_method not in (None, "can") or getattr(self.transport, "bitrate", None) != 500000
                        or type(tx) is not int or not 0x7E0 <= tx <= 0x7E7
                        or getattr(self.transport, "rx_id", None) != tx + 8
                        or getattr(self.transport, "padding", None) != 0):
                    raise TransportUnavailable("Generic OBD requires 11-bit physical OBD CAN IDs, 500 kbit/s, zero padding and read-only mode")
            if exact_method == "harley-delphi-can-identity":
                if (self.profile.id != "harley_delphi_can_uds" or self.transport.name != "can"
                        or not self.transport.is_physical or self.gate.mode != Mode.READ_ONLY
                        or init_method not in (None, "can")
                        or (getattr(self.transport, "bitrate", None), getattr(self.transport, "tx_id", None),
                            getattr(self.transport, "rx_id", None), getattr(self.transport, "padding", None))
                           != (500000, 0x7e0, 0x7e8, 0)):
                    raise TransportUnavailable("Harley Delphi research requires fixed 500 kbit/s CAN IDs and read-only mode")
            if exact_method == "kawasaki-ninja7-can":
                if (self.profile.id != "kawasaki_ninja7_hybrid" or self.transport.name != "can"
                        or not self.transport.is_physical or self.gate.mode != Mode.READ_ONLY
                        or init_method not in (None, "can")
                        or (getattr(self.transport, "bitrate", None), getattr(self.transport, "tx_id", None),
                            getattr(self.transport, "rx_id", None), getattr(self.transport, "padding", None))
                           != (500000, 0x764, 0x746, 0)):
                    raise TransportUnavailable("Ninja 7 requires its exact source-scoped CAN settings and read-only mode")
            self.connection = self.transport.open()
            try:
                self.init_result = self.transport.initialize(
                    self.connection,
                    method=method,
                    address=self.profile.kline.get("address", 0x33),
                    fast_target=self.profile.kline.get(
                        "fast_target", self.profile.kline.get("address", 0x33)
                    ),
                    tester_address=self.profile.kline.get("tester_address", 0xF1),
                    fast_functional=self.profile.kline.get("fast_functional", True),
                    legacy_wakeup_timeout=self.profile.kline.get("wakeup_timeout", 8.0),
                    legacy_comm_baud=self.profile.kline.get("comm_baud", 7680),
                )
            except Exception:
                self.connection.close()
                self.connection = None
                raise
            # Fast K-Line initialisation occurs before KWP2000Session exists.
            # Preserve those raw bytes in the same provenance log as every
            # later request/response instead of losing the most important
            # handshake of the session.
            for frame in self.init_result.prelude:
                self.log.frame("tx", frame)
            if self.init_result.request:
                self.log.frame("tx", self.init_result.request)
            if self.init_result.response:
                self.log.frame("rx", self.init_result.response)
            self.log.action(
                "connect",
                {
                    "transport": self.transport.name,
                    "ecu": self.profile.id,
                    "init": self.init_result.method,
                    "protocol": self.init_result.protocol,
                    "ok": self.init_result.ok,
                    "detail": self.init_result.detail,
                    "attempts": self.init_result.attempts,
                },
            )
            if not self.init_result.ok:
                self.connection.close()
                self.connection = None
                raise TransportError(f"ECU wake-up failed: {self.init_result.detail}")

            # ISO-TP is only the CAN transport layer. The shipped CAN-family
            # catalogs still lack validated Piaggio CAN IDs and an exact UDS
            # or KWP-on-CAN application definition. Reusing K-Line frames
            # inside ISO-TP would look plausible in a simulator but is not a
            # real protocol, so physical CAN remains explicitly unavailable.
            if (self.init_result.protocol == "isotp" and self.transport.is_physical
                    and exact_method not in ("kawasaki-ninja7-can", "generic-obd-can-11bit", "harley-delphi-can-identity")):
                self.connection.close()
                self.connection = None
                raise TransportUnavailable(
                    f"{self.profile.family}: CAN transport is available, but its "
                    "diagnostic application protocol and CAN identifiers are not "
                    "validated; no request was sent"
                )

            if exact_method == "harley-delphi-can-identity":
                try:
                    if self.init_result.protocol != "isotp" or not self.init_result.handshake_complete:
                        raise ProtocolError("Harley Delphi identity research requires ISO-TP CAN transport")
                    self.session = HarleyDelphiCanSession(self.connection, on_frame=self.log.frame)
                    self.session.request(b"\x3e\x00")
                except Exception:
                    self.connection.close()
                    self.connection = None
                    self.session = None
                    raise
            elif exact_method == "generic-obd-can-11bit":
                try:
                    if self.init_result.protocol != "isotp" or not self.init_result.handshake_complete:
                        raise ProtocolError("Generic OBD requires ISO-TP CAN transport")
                    self.session = ObdCanSession(self.connection, on_frame=self.log.frame)
                    self.session.initialise()
                except Exception:
                    self.connection.close()
                    self.connection = None
                    self.session = None
                    raise
            elif exact_method == "kawasaki-ninja7-can":
                try:
                    if self.init_result.protocol != "isotp" or not self.init_result.handshake_complete:
                        raise ProtocolError("Ninja 7 requires ISO-TP CAN transport")
                    self.session = KawasakiNinja7Session(connection=self.connection,
                        on_frame=self.log.frame, write_guard=lambda _: False)
                    self.session.request(b"\x10\x80")
                except Exception:
                    self.connection.close()
                    self.connection = None
                    self.session = None
                    raise
            elif exact_method in ("honda-cbr600rr-2005", "honda-cb500f-dashble", "honda-ctx700-minidash", "honda-pgmfi-research"):
                if (self.init_result.protocol != "honda-cbr600rr" or not self.init_result.handshake_complete
                        or self.init_result.response != bytes.fromhex("02 04 00 fa")):
                    self.connection.close()
                    self.connection = None
                    raise ProtocolError("Honda profile requires the exact initialization response")
                cls = {"honda-cbr600rr-2005": HondaCBR600RRSession, "honda-cb500f-dashble": HondaCB500FDashSession, "honda-ctx700-minidash": HondaCTX700Session, "honda-pgmfi-research": HondaPgmfiSession}[exact_method]
                self.session = cls(connection=self.connection, on_frame=self.log.frame, write_guard=lambda _: False)
            elif exact_method in ("aster-versys-2012", "kawasaki-kds-research", "aster-gsxr600-2011", "suzuki-gsxr1000-2004", "suzuki-sv650ak7-2007", "suzuki-sv650-2003", "suzuki-sds-gsxr-research"):
                from .protocol.kwp2000 import decode_frame
                try:
                    target = 0x11 if exact_method in ("aster-versys-2012", "kawasaki-kds-research") else 0x12
                    wake = decode_frame(self.init_result.response)
                    wake_ok = (len(wake.payload) == 3 and wake.payload[0] == 0xc1
                               if exact_method in ("suzuki-gsxr1000-2004", "suzuki-sv650ak7-2007", "suzuki-sv650-2003", "suzuki-sds-gsxr-research")
                               else wake.payload == b"\xc1\xea\x8f")
                    if (not self.init_result.handshake_complete or wake.target != 0xF1
                            or wake.source != target or not wake_ok):
                        raise ProtocolError("Source-scoped K-Line requires addressed C1 and source-specific key bytes")
                    cls = {"aster-versys-2012": Versys2012Session, "kawasaki-kds-research": KawasakiKdsResearchSession, "aster-gsxr600-2011": Gsxr6002011Session, "suzuki-gsxr1000-2004": Gsxr10002004Session, "suzuki-sv650ak7-2007": Sv650Ak7Session, "suzuki-sv650-2003": Sv6502003Session, "suzuki-sds-gsxr-research": SuzukiGsxrResearchSession}[exact_method]
                    self.session = cls(connection=self.connection, target=target, source=0xF1,
                                       on_frame=self.log.frame, write_guard=lambda _: False)
                    if target == 0x11:
                        self.session.request(b"\x10\x80")
                except Exception:
                    self.connection.close()
                    self.connection = None
                    self.session = None
                    raise
            elif self.profile.session.get("protocol") == "kawasaki-er6n":
                from .protocol.kwp2000 import decode_frame
                try:
                    wake = decode_frame(self.init_result.response)
                    if (not self.init_result.handshake_complete or wake.target != 0xF1
                            or wake.source != 0x11 or wake.payload != b"\xc1\xea\x8f"):
                        raise ProtocolError("ER-6n wake-up response does not match C1 EA 8F and addresses")
                    self.session = KawasakiER6nSession(
                        connection=self.connection, target=0x11, source=0xF1,
                        on_frame=self.log.frame, write_guard=lambda _: False,
                    )
                    self.session.request([0x10, 0x80])
                except Exception:
                    self.connection.close()
                    self.connection = None
                    self.session = None
                    raise
            elif self.profile.session.get("protocol") == "harley-j1850-harleydroid":
                if self.init_result.protocol != "j1850-vpw" or not self.init_result.handshake_complete:
                    self.connection.close()
                    self.connection = None
                    raise ProtocolError("Harley J1850 requires the ELM VPW initialization")
                self.session = HarleyJ1850Session(self.connection, on_frame=self.log.frame)
            elif self.profile.session.get("protocol") == "triumph-daytona-2012":
                try:
                    if (self.init_result.protocol != "iso9141-2" or not self.init_result.handshake_complete
                            or self.init_result.key_bytes != (0x08, 0x08)):
                        raise ProtocolError("Daytona requires the ISO 9141 08 08 slow-init handshake")
                    self.session = TriumphDaytonaSession(connection=self.connection,
                        on_frame=self.log.frame, write_guard=lambda _: False)
                    self.session.initialise()
                except Exception:
                    self.connection.close()
                    self.connection = None
                    self.session = None
                    raise
            elif self.init_result.protocol == "legacy-iaw":
                self.session = LegacyIAWSession(
                    connection=self.connection,
                    timeout=float(self.profile.session.get("response_timeout", 0.5)),
                    inter_request_delay=float(
                        self.profile.session.get("inter_request_delay", 0.005)
                    ),
                    on_frame=self.log.frame,
                )
            else:
                timing = TimingParameters(
                    tester_present_interval=self.profile.session.get(
                        "tester_present_interval", 2.0
                    )
                )
                self.session = KWP2000Session(
                    connection=self.connection,
                    timing=timing,
                    target=self.profile.kline.get("ecu_address", 0x10),
                    source=self.profile.kline.get("tester_address", 0xF1),
                    addressed=self.profile.kline.get("addressed", True),
                    on_frame=self.log.frame,
                    write_guard=self.gate.session_guard(),
                )

                # A physical fast-init transport has already sent and validated
                # StartCommunication. Sending 0x81 again here was a real-hardware
                # double-handshake bug. The simulator deliberately leaves that
                # exchange to the protocol session so its framing is still tested.
                if (
                    self.init_result.protocol == "iso14230"
                    and not self.init_result.handshake_complete
                ):
                    self.session.start_communication()
                if self.profile.session.get("access_timing"):
                    self.session.access_timing_parameters()

            self._touch()
            if isinstance(self.session, KWP2000Session):
                self._start_keepalive()
            return self.init_result

    def disconnect(self) -> None:
        with self._lock:
            self._stop.set()
            if self._keepalive:
                self._keepalive.join(timeout=1.0)
                self._keepalive = None
            if self.session is not None:
                self.release_all_outputs()
                try:
                    if isinstance(self.session, (KawasakiER6nSession, KawasakiNinja7Session, TriumphDaytonaSession, AsterKLineSession, HondaCBR600RRSession)):
                        pass  # no unverified stop exchange
                    elif isinstance(self.session, KWP2000Session):
                        self.session.stop_diagnostic_session()
                        self.session.stop_communication()
                    else:
                        self.session.close()
                except Exception:
                    pass
            if self.connection is not None:
                self.connection.close()
            self.log.action("disconnect", {})
            self.session = None
            self.connection = None
            self.identity = None
            # Drop the hardware identity with the session that produced it,
            # so a stale string from ECU A can never vouch for ECU B.
            self.gate.state.ecu_hardware = ""

    def _require(self) -> KWP2000Session | LegacyIAWSession | HarleyJ1850Session:
        if not self.connected:
            raise NotConnected("not connected to an ECU")
        return self.session

    def _require_kwp(self) -> KWP2000Session:
        session = self._require()
        if not isinstance(session, KWP2000Session):
            raise ProtocolError("this operation requires a KWP2000 session")
        return session

    def _require_legacy(self) -> LegacyIAWSession:
        session = self._require()
        if not isinstance(session, LegacyIAWSession):
            raise ProtocolError("this operation requires a legacy IAW session")
        return session

    def _touch(self) -> None:
        self._last_tx = time.monotonic()

    def _start_keepalive(self) -> None:
        self._stop.clear()

        def run() -> None:
            interval = self.profile.session.get("tester_present_interval", 2.0)
            while not self._stop.wait(0.25):
                if time.monotonic() - self._last_tx < interval:
                    continue
                with self._lock:
                    if self.session is None:
                        return
                    try:
                        self.session.tester_present()
                        self._touch()
                    except Exception as exc:
                        self.log.error("keepalive", str(exc))
                        return
                self._release_expired()

        self._keepalive = threading.Thread(
            target=run, name="guzzionboard-keepalive", daemon=True
        )
        self._keepalive.start()

    # -- identification ---------------------------------------------------
    def identify(self) -> Identity:
        with self._lock:
            if "identify" not in self.profile.capabilities:
                raise ProtocolError(
                    f"{self.profile.family}: identification request is not validated"
                )
            session = self._require()
            spec = self.profile.identification
            fields = {}

            if isinstance(session, HarleyDelphiCanSession):
                self.identity = None
                self.gate.state.identified = False
                self.gate.state.ecu_hardware = ""
                fields, raw = session.read_identity_candidates()
                self._touch()
                self.identity = Identity(fields=fields, raw=raw, ecu_id="", family=self.profile.family)
                self.log.action("identify", self.identity.as_dict())
                return self.identity
            if isinstance(session, ObdCanSession):
                # VIN and calibration identifiers are not verified ECU hardware
                # or permission to write. Drop stale evidence before re-reading.
                self.identity = None
                self.gate.state.identified = False
                self.gate.state.ecu_hardware = ""
                fields, raw = session.read_vehicle_information()
                self._touch()
                self.identity = Identity(fields=fields,
                                         raw=raw, ecu_id="", family=self.profile.family)
                self.log.action("identify", self.identity.as_dict())
                return self.identity
            if isinstance(session, HondaCBR600RRSession):
                # This is a source-derived raw candidate, not a verified part number
                # or a basis for the safety gate / programming authorization.
                self.identity = None
                self.gate.state.identified = False
                self.gate.state.ecu_hardware = ""
                raw = session.read_identity_candidate()
                self._touch()
                self.identity = Identity(fields={"Honda ECM ID (raw candidate)": raw.hex(" ").upper()},
                                         raw=raw, ecu_id="", family=self.profile.family)
                self.log.action("identify", self.identity.as_dict())
                return self.identity
            if isinstance(session, KawasakiNinja7Session):
                self.identity = None
                self.gate.state.identified = False
                self.gate.state.ecu_hardware = ""
                raw = session.read_identity_raw()
                fields = {"ECU identification (raw ASCII candidate)": raw.decode("ascii", "replace").strip("\x00 ")}
            elif isinstance(session, HarleyJ1850Session):
                # A failed re-identification must not leave prior ECU evidence active.
                self.identity = None
                self.gate.state.identified = False
                self.gate.state.ecu_hardware = ""
                fields, raw = session.read_identity()
            elif isinstance(session, LegacyIAWSession):
                chunks = []
                wake = self.init_result.response if self.init_result else b""
                if wake and spec.get("include_wakeup", True):
                    fields[spec.get("wakeup_name", "ISO key-on code")] = wake.hex(
                        " "
                    ).upper()
                    chunks.append(wake)
                for block in spec.get("blocks", []):
                    chunk = session.query_many(block.get("requests", []))
                    chunks.append(chunk)
                    if block.get("encoding", "ascii") == "hex":
                        value = chunk.hex(" ").upper()
                    else:
                        value = (
                            chunk.decode("ascii", "replace")
                            .strip()
                            .strip("\x00")
                            .strip()
                        )
                    fields[block["name"]] = value
                raw = b"".join(chunks)
            else:
                raw = session.read_ecu_identification(spec.get("option", 0x80))
                for field_spec in spec.get("fields", []):
                    chunk = raw[
                        field_spec["offset"] : field_spec["offset"] + field_spec["length"]
                    ]
                    fields[field_spec["name"]] = (
                        chunk.decode("ascii", "replace")
                        .strip()
                        .strip("\x00")
                        .strip()
                    )
            self._touch()

            self.identity = Identity(
                fields=fields, raw=raw, ecu_id=self.profile.id, family=self.profile.family
            )
            self.gate.state.identified = True
            self.gate.state.ecu_confidence = self.profile.confidence
            # The hardware string the write path's family gate compares the
            # candidate image against.  It is recorded from the live ECU's
            # own answer, never from the selection or the filename.
            self.gate.state.ecu_hardware = fields.get("Hardware", "")
            self.log.action("identify", self.identity.as_dict())
            return self.identity

    # -- live data --------------------------------------------------------
    def read_parameter(self, param: Parameter) -> Sample:
        session = self._require()
        if isinstance(session, (HarleyJ1850Session, KawasakiKdsResearchSession, Gsxr6002011Session, Gsxr10002004Session, SuzukiGsxrResearchSession, Sv6502003Session, Sv650Ak7Session, HondaCBR600RRSession)):
            return self.read_parameters([param.key])[0]
        try:
            if isinstance(session, LegacyIAWSession):
                raw = session.query_many(param.request_ids or (param.local_id,))
            else:
                raw = session.read_data_by_local_id(param.local_id)
            self._touch()
        except (NegativeResponse, ProtocolError) as exc:
            sample = Sample(
                param.key, param.name, param.local_id, b"", None, param.unit,
                error=str(exc),
            )
            self.last_samples[param.key] = sample
            return sample

        try:
            value_raw = decode_raw_value(
                raw,
                offset=param.offset,
                length=param.length,
                endian=param.endian,
                signed=param.signed,
            )
        except ProtocolError as exc:
            sample = Sample(
                param.key, param.name, param.local_id, raw, None, param.unit,
                error=str(exc),
            )
            self.last_samples[param.key] = sample
            return sample

        if isinstance(session, KawasakiER6nSession):
            value = decode_kawasaki_value(param.local_id, raw)
        elif isinstance(session, Versys2012Session):
            value = decode_versys(param.local_id, raw)
        else:
            value = apply_scaling(
                value_raw, scale=param.scale, bias=param.bias, recip=param.recip
            )
        value = round(value, param.digits) if param.digits else int(round(value))
        text = param.states.get(str(int(value_raw)), "") if param.states else ""

        sample = Sample(
            param.key, param.name, param.local_id, raw, value, param.unit, text=text
        )
        self.last_samples[param.key] = sample
        self.log.sample(param.key, param.local_id, raw, value, param.unit)
        if not isinstance(session, AsterKLineSession):
            self._update_inferred_state(param.key, value, text)
        return sample

    def read_parameters(self, keys: list[str] | None = None) -> list[Sample]:
        with self._lock:
            if "live" not in self.profile.capabilities:
                raise ProtocolError(
                    f"{self.profile.family}: live-data requests are not validated"
                )
            if keys is None:
                params = self.profile.default_parameters or self.profile.live_parameters
            else:
                params = [self.profile.parameter(k) for k in keys]
            session = self._require()
            if isinstance(session, KawasakiKdsResearchSession):
                samples = []
                for param in params:
                    try:
                        raw = session.read_raw(param.local_id)
                        self._touch()
                        sample = Sample(param.key, param.name, param.local_id, raw, None, param.unit,
                                        text="Raw KDS data (interpretation unverified)")
                        self.log.sample(param.key, param.local_id, raw, None, param.unit)
                    except (NegativeResponse, ProtocolError) as exc:
                        sample = Sample(param.key, param.name, param.local_id, b"", None, param.unit, error=str(exc))
                    self.last_samples[param.key] = sample
                    samples.append(sample)
                return samples
            if isinstance(session, Gsxr10002004Session):
                if not params:
                    return []
                try:
                    raw = session.read_snapshot()
                    self._touch()
                    sample = Sample(params[0].key, params[0].name, params[0].local_id, raw, None, params[0].unit,
                                    text="Raw snapshot (interpretation unverified)")
                    self.log.sample(sample.key, sample.local_id, raw, None, sample.unit)
                except (NegativeResponse, ProtocolError) as exc:
                    sample = Sample(params[0].key, params[0].name, params[0].local_id, b"", None, params[0].unit, error=str(exc))
                self.last_samples[sample.key] = sample
                return [sample]
            if isinstance(session, HondaPgmfiSession):
                tables, errors = {}, {}
                for table in dict.fromkeys(p.local_id for p in params):
                    try:
                        tables[table] = session.read_table(table)
                        self._touch()
                    except (NegativeResponse, ProtocolError) as exc:
                        errors[table] = str(exc)
                samples = []
                for param in params:
                    data = tables.get(param.local_id, b"")
                    error = errors.get(param.local_id, "")
                    value, text, raw = None, "", data
                    if not error and param.key.endswith("_rpm"):
                        if len(data) < 2: error = "Honda table too short for candidate RPM"
                        else: raw, value = data[:2], int.from_bytes(data[:2], "big")
                    elif not error and param.key.endswith("_coolant"):
                        if len(data) < 6: error = "Honda table too short for candidate coolant"
                        else: raw, value = data[5:6], data[5] - 40
                    elif not error:
                        text = "Raw table (meaning varies)"
                    sample = Sample(param.key, param.name, param.local_id, raw, value, param.unit, text=text, error=error)
                    self.last_samples[param.key] = sample
                    if not error:
                        self.log.sample(param.key, param.local_id, raw, value, param.unit)
                    samples.append(sample)
                return samples
            if isinstance(session, HondaCBR600RRSession):
                snapshots, errors = {}, {}
                for table in dict.fromkeys(p.local_id for p in params):
                    try:
                        snapshots[table] = session.read_snapshot(table)
                        self._touch()
                    except (NegativeResponse, ProtocolError) as exc:
                        errors[table] = str(exc)
                samples = []
                for param in params:
                    if param.local_id in errors:
                        sample = Sample(param.key, param.name, param.local_id, b"", None, param.unit,
                                        error=errors[param.local_id])
                    else:
                        raw = snapshots[param.local_id][param.key]
                        value = (decode_honda_ctx(param.key, raw) if isinstance(session, HondaCTX700Session)
                                 else decode_honda(param.key, raw))
                        value = round(value, param.digits) if param.digits else int(round(value))
                        text = param.states.get(str(int(value)), "") if param.states else ""
                        sample = Sample(param.key, param.name, param.local_id, raw, value, param.unit, text=text)
                        self.log.sample(param.key, param.local_id, raw, value, param.unit)
                    self.last_samples[param.key] = sample
                    samples.append(sample)
                return samples
            if isinstance(session, Sv650Ak7Session):
                try:
                    snapshot = session.read_snapshot()
                    self._touch()
                except (NegativeResponse, ProtocolError) as exc:
                    samples = [Sample(p.key, p.name, p.local_id, b"", None, p.unit, error=str(exc)) for p in params]
                    self.last_samples.update({sample.key: sample for sample in samples})
                    return samples
                samples = []
                for param in params:
                    raw = snapshot[param.key]
                    value = decode_sv650ak7(param.key, raw)
                    value = round(value, param.digits) if param.digits else int(round(value))
                    sample = Sample(param.key, param.name, param.local_id, raw, value, param.unit)
                    self.last_samples[param.key] = sample
                    self.log.sample(param.key, param.local_id, raw, value, param.unit)
                    samples.append(sample)
                return samples
            if isinstance(session, Gsxr6002011Session):
                try:
                    snapshot = session.read_snapshot()
                    self._touch()
                except (NegativeResponse, ProtocolError) as exc:
                    samples = [Sample(p.key, p.name, p.local_id, b"", None, p.unit, error=str(exc)) for p in params]
                    self.last_samples.update({sample.key: sample for sample in samples})
                    return samples
                samples = []
                for param in params:
                    raw = snapshot[param.key]
                    value = decode_gsxr(param.key, raw)
                    value = round(value, param.digits) if param.digits else int(round(value))
                    sample = Sample(param.key, param.name, param.local_id, raw, value, param.unit)
                    self.last_samples[param.key] = sample
                    self.log.sample(param.key, param.local_id, raw, value, param.unit)
                    samples.append(sample)
                return samples
            if isinstance(session, HarleyJ1850Session):
                snapshot = session.read_snapshot()
                samples = []
                for param in params:
                    raw = snapshot.get(param.local_id)
                    if raw is None:
                        sample = Sample(param.key, param.name, param.local_id, b"", None, param.unit,
                                        error="No matching CRC-valid broadcast in this monitor window")
                    else:
                        raw_value = decode_raw_value(raw, offset=param.offset, length=param.length,
                                                     endian=param.endian, signed=param.signed)
                        value = apply_scaling(raw_value, scale=param.scale, bias=param.bias, recip=param.recip)
                        value = round(value, param.digits) if param.digits else int(round(value))
                        sample = Sample(param.key, param.name, param.local_id, raw, value, param.unit)
                        self.log.sample(param.key, param.local_id, raw, value, param.unit)
                        self._update_inferred_state(param.key, value, "")
                    self.last_samples[param.key] = sample
                    samples.append(sample)
                self._touch()
                return samples
            return [self.read_parameter(p) for p in params]

    def _update_inferred_state(self, key: str, value, text: str) -> None:
        """Feed the safety gate from observed values, never from assumptions."""
        state = self.gate.state
        if key == "battery" and isinstance(value, (int, float)):
            state.battery_v = float(value)
        elif key == "rpm" and isinstance(value, (int, float)):
            state.engine_running = value > 200
        elif key == "stop_state" and text:
            state.engine_running = text == "Running"

    # -- DTCs -------------------------------------------------------------
    def read_dtcs(self) -> dict:
        """Codes plus the context the workstation observed when it read them.

        An IAW ECU of this era does not hand over an ECU-stored freeze frame,
        and this project will not pretend it does. What the workstation *can*
        do honestly is read the default live channels at the same moment and
        keep them next to the codes: the engine state the fault was read in,
        labelled as exactly that.
        """
        with self._lock:
            if "dtc_read" not in self.profile.capabilities:
                raise ProtocolError(
                    f"{self.profile.family}: fault-memory request is not validated"
                )
            session = self._require()
            if isinstance(session, HarleyJ1850Session):
                result = session.read_dtcs()
                self._touch()
                self.log.action("read_dtcs", {"count": len(result["dtcs"]), "format": result["format"],
                                               "modules": result["modules"], "dtcs": result["dtcs"]})
                return result
            if isinstance(session, KawasakiNinja7Session):
                dtcs = session.read_stored_codes()
                self._touch()
                self.log.action("read_dtcs", {"count": len(dtcs), "dtcs": dtcs, "format": "kawasaki-ninja7"})
                return {"dtcs": dtcs, "format": "kawasaki-ninja7", "context": {},
                        "note": "Source confirmed a zero-DTC response; nonzero records and status interpretation remain candidates."}
            if isinstance(session, (TriumphDaytonaSession, ObdCanSession)):
                dtcs = session.read_stored_codes()
                self._touch()
                self.log.action("read_dtcs", {"count": len(dtcs), "dtcs": dtcs, "format": "obd-stored"})
                return {"dtcs": dtcs, "format": "obd-stored", "context": {},
                        "note": "Stored mode 03 emission-related codes from the selected ECU only; other modules, pending codes, warning-lamp state and individual status bytes were not read."}
            if isinstance(session, LegacyIAWSession):
                result = self._read_legacy_fault_registers(session)
                self._touch()
                context = self._read_context()
                result["context"] = context
                self.log.action(
                    "read_dtcs",
                    {
                        "count": len(result["dtcs"]),
                        "format": result["format"],
                        "dtcs": result["dtcs"],
                        "registers": result["registers"],
                        "context": context,
                    },
                )
                return result

            dtcs = session.read_dtcs(self.profile.dtc_descriptions)
            self._touch()
            payload = [d.as_dict() for d in dtcs]
            context = self._read_context()
            self.log.action(
                "read_dtcs",
                {"count": len(payload), "dtcs": payload, "context": context},
            )
            return {"dtcs": payload, "context": context}

    def _read_legacy_fault_registers(self, session: LegacyIAWSession) -> dict:
        """Return legacy fault flags without fabricating SAE/ISO DTCs.

        These ECUs expose bitfields rather than KWP DTC records. Until a
        family-specific bit map is supported by Moto Guzzi evidence, every set
        bit is labelled only by its request byte and bit number.
        """
        requests = self.profile.session.get("fault_registers", [])
        registers = []
        flags = []
        for request in requests:
            identifier = int(request)
            value = session.query(identifier)
            set_bits = [bit for bit in range(8) if value & (1 << bit)]
            registers.append(
                {
                    "request": identifier,
                    "hex_request": f"0x{identifier:02X}",
                    "value": value,
                    "hex_value": f"0x{value:02X}",
                    "set_bits": set_bits,
                }
            )
            for bit in set_bits:
                flags.append(
                    {
                        "code": f"REG-{identifier:02X}-BIT-{bit}",
                        "description": (
                            "Uninterpreted legacy fault flag; no validated "
                            "Moto Guzzi bit description is available"
                        ),
                        "status_byte": value,
                        "kind": "legacy-raw-bit",
                        "status": "raw flag",
                        "warning_indicator": False,
                    }
                )
        return {
            "format": "legacy-fault-bitfields",
            "dtcs": flags,
            "registers": registers,
            "note": (
                "Raw legacy fault registers. These are not SAE/ISO DTCs; "
                "register and bit positions are shown without guessed meanings."
            ),
        }

    def _read_context(self, limit: int = 8) -> dict[str, dict]:
        """A handful of default channels, best effort, honestly labelled."""
        if "live" not in self.profile.capabilities:
            return {}
        out: dict[str, dict] = {}
        for param in self.profile.default_parameters[:limit]:
            try:
                sample = self.read_parameter(param)
            except Exception:
                continue          # a channel that fails is skipped, not faked
            out[param.key] = {
                "name": param.name,
                "value": sample.value,
                "unit": param.unit,
            }
        return out

    def check_clear_dtcs(self) -> Decision:
        decision = self.gate.evaluate_clear_dtcs(self.profile)
        self.log.decision(decision.as_dict())
        return decision

    def clear_dtcs(self, token: str) -> dict:
        with self._lock:
            session = self._require_kwp()
            self.gate.consume(token, "clear-dtcs")
            session.write_guard = self.gate.session_guard(
                {Service.CLEAR_DIAGNOSTIC_INFORMATION}
            )
            try:
                session.clear_dtcs()
                self._touch()
            finally:
                session.write_guard = self.gate.session_guard()
            self.log.action("clear_dtcs", {"result": "ok"})
            remaining = [
                d.as_dict() for d in session.read_dtcs(self.profile.dtc_descriptions)
            ]
            return {"ok": True, "remaining": remaining}

    # -- actuators --------------------------------------------------------
    def check_actuator(self, key: str) -> Decision:
        actuator = self.profile.actuator(key)
        decision = self.gate.evaluate_actuator(self.profile, actuator)
        self.log.decision(decision.as_dict())
        return decision

    def pulse_actuator(self, key: str, token: str, seconds: float | None = None) -> dict:
        """Energise an output for a bounded time.

        IAW ECUs have no output timer: once commanded on, an output stays on
        until something turns it off. The deadline is therefore owned here, and
        release also happens on disconnect and on keep-alive ticks, so a closed
        browser tab cannot leave a fuel pump running.
        """
        with self._lock:
            session = self._require_kwp()
            actuator = self.profile.actuator(key)
            self.gate.consume(token, f"actuator:{key}")

            duration = min(
                float(seconds or actuator.max_pulse_s), actuator.max_pulse_s
            )
            duration = max(0.2, duration)

            session.write_guard = self.gate.session_guard(
                {Service.IO_CONTROL_BY_LOCAL_ID}
            )
            try:
                session.io_control(actuator.local_id, actuator.on_command)
                self._touch()
            finally:
                session.write_guard = self.gate.session_guard()

            self.active_outputs[key] = time.monotonic() + duration
            self.log.action(
                "actuator_on",
                {"key": key, "local_id": actuator.local_id, "duration_s": duration},
            )
            return {"ok": True, "key": key, "duration_s": duration}

    def release_actuator(self, key: str) -> dict:
        with self._lock:
            if self.session is None:
                self.active_outputs.pop(key, None)
                return {"ok": False, "reason": "not connected"}
            actuator = self.profile.actuator(key)
            self.session.write_guard = self.gate.session_guard(
                {Service.IO_CONTROL_BY_LOCAL_ID}
            )
            try:
                self.session.io_control(actuator.local_id, actuator.off_command)
                self._touch()
            except Exception as exc:
                self.log.error("actuator_off", f"{key}: {exc}")
                return {"ok": False, "reason": str(exc)}
            finally:
                self.session.write_guard = self.gate.session_guard()
            self.active_outputs.pop(key, None)
            self.log.action("actuator_off", {"key": key})
            return {"ok": True, "key": key}

    def _release_expired(self) -> None:
        now = time.monotonic()
        for key, deadline in list(self.active_outputs.items()):
            if now >= deadline:
                self.release_actuator(key)

    def release_all_outputs(self) -> None:
        for key in list(self.active_outputs):
            self.release_actuator(key)

    # -- routines ---------------------------------------------------------
    def check_routine(self, key: str) -> Decision:
        routine = self.profile.routine(key)
        decision = self.gate.evaluate_routine(self.profile, routine)
        self.log.decision(decision.as_dict())
        return decision

    def run_routine(self, key: str, token: str) -> dict:
        with self._lock:
            session = self._require_kwp()
            routine = self.profile.routine(key)
            self.gate.consume(token, f"routine:{key}")

            service = Service(routine.service)
            session.write_guard = self.gate.session_guard({service})
            try:
                if self.profile.session.get("lazy_session"):
                    session.start_diagnostic_session(
                        self.profile.session.get("diagnostic_session", 0x81)
                    )
                if service is Service.START_ROUTINE_BY_LOCAL_ID:
                    frame = session.start_routine(routine.local_id, *routine.params)
                else:
                    frame = session.io_control(
                        routine.local_id,
                        routine.params[0] if routine.params else 0x07,
                    )
                self._touch()
            finally:
                session.write_guard = self.gate.session_guard()

            result = {
                "ok": True,
                "key": key,
                "name": routine.name,
                "response": frame.hex(),
                "follow_up": routine.follow_up,
            }
            # Best effort: many IAW families do not implement 0x33 at all.
            results = session.routine_results(routine.local_id)
            if results is not None:
                result["routine_results"] = results.hex()
            self.log.action("routine", result)
            return result

    # -- discovery --------------------------------------------------------
    def discover_identifiers(
        self, start: int = 0x30, end: int = 0x7F, *, settle: float = 0.0
    ) -> dict:
        """Read-only sweep of ``21 <rli>`` across a range.

        This is available only where a family definition establishes that
        service 0x21 is a non-mutating read.  Unknown transports are not probed
        on a customer's motorcycle merely because the intended operation is a
        read.
        """
        with self._lock:
            if "discover" not in self.profile.capabilities:
                raise ProtocolError(
                    f"{self.profile.family}: identifier discovery is not validated"
                )
            session = self._require()
            found: dict[int, dict] = {}
            for local_id in range(start, end + 1):
                try:
                    raw = session.read_data_by_local_id(local_id)
                    found[local_id] = {
                        "local_id": local_id,
                        "hex_id": f"0x{local_id:02X}",
                        "length": len(raw),
                        "raw": raw.hex(" "),
                        "int_be": int.from_bytes(raw, "big") if raw else None,
                        "answered": True,
                    }
                except NegativeResponse as exc:
                    found[local_id] = {
                        "local_id": local_id, "hex_id": f"0x{local_id:02X}",
                        "answered": False, "nrc": exc.code,
                    }
                except ProtocolError as exc:
                    found[local_id] = {
                        "local_id": local_id, "hex_id": f"0x{local_id:02X}",
                        "answered": False, "error": str(exc),
                    }
                self._touch()
                if settle:
                    time.sleep(settle)

            self.discovered = found
            answered = [f for f in found.values() if f.get("answered")]
            summary = {
                "range": [start, end],
                "answered": len(answered),
                "scanned": len(found),
                "identifiers": list(found.values()),
            }
            self.log.action("discover", {"range": [start, end], "answered": len(answered)})
            return summary

    def discovery_delta(self, before: dict, after: dict) -> list[dict]:
        """Identifiers whose value changed between two sweeps.

        Sweep with the engine off, then with it running: whatever moved is a
        live channel and whatever did not is probably a shared zero slot.
        """
        changed = []
        for local_id, first in before.items():
            second = after.get(local_id)
            if not (first.get("answered") and second and second.get("answered")):
                continue
            if first.get("raw") != second.get("raw"):
                changed.append(
                    {
                        "local_id": local_id,
                        "hex_id": f"0x{local_id:02X}",
                        "before": first.get("raw"),
                        "after": second.get("raw"),
                    }
                )
        return changed

    # -- memory -----------------------------------------------------------
    def check_memory_read(self) -> Decision:
        """Report the direct KWP read path, independently of write readiness.

        Other research readers have their own explicit confirmation and session
        checks in ProgrammingService. A diagnostic connection alone does not
        imply that a memory reader has been implemented.
        """
        checks = (
            Check("connected", self.connected, "connect before reading memory"),
            Check("read-path", bool(self.profile.memory.get("read_supported"))
                  and not self.profile.memory.get("research_read_only"),
                  "no direct KWP read path for this profile; an experimental reader may have its own workflow"),
            Check("protocol", isinstance(self.session, KWP2000Session),
                  "direct memory reading requires a KWP2000 session"),
        )
        return Decision(all(c.passed for c in checks), "memory-read", Risk.READ, checks)

    def read_memory(
        self, start: int = 0, size: int | None = None, *, block: int = 0x80,
        progress=None,
    ) -> bytes:
        """Read through an implemented KWP path; this is not a verified backup."""
        with self._lock:
            decision = self.check_memory_read()
            if not decision.allowed:
                raise SafetyViolation(decision)
            session = self._require_kwp()
            total = self.profile.memory.get("image_size") if size is None else size
            if not isinstance(start, int) or isinstance(start, bool) or start < 0:
                raise ValueError("start must be a non-negative integer")
            if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
                raise ValueError(f"{self.profile.family}: image size is unknown or invalid")
            if not isinstance(block, int) or isinstance(block, bool) or not 1 <= block <= 0xff:
                raise ValueError("block must be 1..255 bytes")
            if start + total > 0x1000000:
                raise ValueError("memory read exceeds the 24-bit address space")

            out = bytearray()
            address = start
            while len(out) < total:
                chunk = min(block, total - len(out))
                data = session.read_memory_by_address(address, chunk)
                if len(data) != chunk:
                    raise ProtocolError(f"memory read at 0x{address:06X} returned {len(data)} bytes, expected {chunk}")
                out += data
                address += chunk
                self._touch()
                if progress:
                    progress(len(out), total)
            self.log.action("memory_read", {"start": start, "size": len(out)})
            return bytes(out)

    # -- status -----------------------------------------------------------
    def status(self) -> dict:
        return {
            "connected": self.connected,
            "transport": self.transport.describe(),
            "ecu": self.profile.as_dict(include_parameters=False),
            "init": (
                {
                    "ok": self.init_result.ok,
                    "method": self.init_result.method,
                    "protocol": self.init_result.protocol,
                    "detail": self.init_result.detail,
                    "key_bytes": list(self.init_result.key_bytes),
                    "attempts": list(self.init_result.attempts),
                    "handshake_complete": self.init_result.handshake_complete,
                    "request": self.init_result.request.hex(" "),
                    "response": self.init_result.response.hex(" "),
                }
                if self.init_result
                else None
            ),
            "identity": self.identity.as_dict() if self.identity else None,
            "mode": self.gate.mode.value,
            "vehicle_state": self.gate.state.as_dict(),
            "active_outputs": {
                k: round(max(0.0, v - time.monotonic()), 1)
                for k, v in self.active_outputs.items()
            },
            "samples": {k: s.as_dict() for k, s in self.last_samples.items()},
        }
