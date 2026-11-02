"""ECU memory reading and programming.

This is the most dangerous code in the project, so it is also the most
defensive. The order of operations is not negotiable:

    identify -> backup -> verify backup by re-reading -> validate new image
    -> arm safety gate -> erase -> transfer -> program -> verify by re-reading

A write that cannot be verified is reported as a failure even if the ECU said
"ok". A checkpoint records interruption and uncertainty; it does not establish
that a hardware write can be resumed or recovered.

Two wire protocols are supported, selected per ECU family by the catalog:

``read_memory_by_address``
    The generic KWP2000 path: ``23 <addr> <size>`` to read, ``3D`` to write.

``iaw_transfer``
    What the IAW 5AM actually does. The read sequence comes from a published
    5am_util transcript:

        -> 10 85                StartDiagnosticSession, programming session
        -> 1A 80                ReadEcuIdentification (hardware check)
        -> 10 0C 0C 09          session + baud switch; tester address becomes 0x01
        -> 27 01                SecurityAccess requestSeed  -> 67 01 <4 byte seed>
        -> 27 02 <4 byte key>   sendKey                     -> 67 02
        -> 36 11 00 FE 02 01 00 TransferData, setup         -> 76 11 02
        -> 36 21 <bank> <addr16> <len>   read block         -> 76 21 <addr16> <len16> <data>

    The write sequence is transcribed from the same tool's source (see
    ``docs/PRIOR_ART.md`` 1.2):

        -> 10 85 03             programming session; the line moves to 38400
        -> 83 03 ...            AccessTimingParameter
        -> 27 01 / 27 02        SecurityAccess (sent from tester 0x01)
        -> 3B 98 20             writer record   - mandatory, or the download fails
        -> 3B 99 20 <date>      reflash-date record
        -> 31 02 00 40 00 04 FF FF   arm the erase for 0x4000..0x4FFFF
        -> 33 02                run the erase (the ECU streams status frames)
        -> 34 00 40 00 33 04 C0 00   RequestDownload
        -> 36 <254 bytes>       TransferData of the *encoded* blob (firmware.iaw5am_upload_blob)
        -> 37                   RequestTransferExit
        -> 31 01 00 40 00 04 FF FF <sum16>   arm programming with the checksum
        -> 33 01                program

    Physical 5AM reads use a block-selected 0x4000..0x7fff window. The
    region-shaped output omits block 0 and synthesizes blocks 2-5 as FF;
    it is a partial research result, not a verified complete backup. The
    simulator's contiguous model does not establish physical compatibility.
"""
from __future__ import annotations

from . import resources

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .basemap import DEFAULT_BASEMAP_DIR, BaseMapVault, ecu_key
from .catalog import EcuProfile
from .firmware import (
    FirmwareImage,
    IncompatibleImage,
    extract_hardware_strings,
    iaw5am_upload_blob,
    iaw5am_upload_checksum,
    summarise_findings,
)
from .protocol.kwp2000 import NegativeResponse, ProtocolError, Service
from .safety import Check, Decision, Mode, Risk, SafetyGate, SafetyViolation
from .security import SecurityUnavailable, best_provider

#: Where backups and checkpoints live.
DEFAULT_IMAGE_DIR = resources.data_root() / "images"


class ProgrammingError(Exception):
    pass


class VerificationFailed(ProgrammingError):
    """The ECU does not contain what we just wrote. Do not power it down."""


@dataclass
class Progress:
    phase: str
    done: int = 0
    total: int = 0
    message: str = ""
    started: float = field(default_factory=time.time)

    @property
    def fraction(self) -> float:
        return (self.done / self.total) if self.total else 0.0

    @property
    def eta_s(self) -> float:
        elapsed = time.time() - self.started
        if not self.done or not self.total:
            return 0.0
        return max(0.0, elapsed * (self.total - self.done) / self.done)

    def as_dict(self) -> dict:
        return {
            "phase": self.phase, "done": self.done, "total": self.total,
            "fraction": round(self.fraction, 4), "eta_s": round(self.eta_s),
            "message": self.message,
        }


ProgressFn = Callable[[Progress], None]


@dataclass
class Region:
    """A readable/writable area of ECU memory."""

    name: str
    start: int
    size: int
    block: int = 0x80
    writable: bool = False
    addr_bytes: int = 3
    expect_vector_table: bool = False
    note: str = ""

    @classmethod
    def from_catalog(cls, name: str, spec: dict) -> "Region":
        return cls(
            name=name,
            start=int(spec.get("start", 0)),
            size=int(spec.get("size", 0)),
            block=int(spec.get("block", 0x80)),
            writable=bool(spec.get("writable", False)),
            addr_bytes=int(spec.get("addr_bytes", 3)),
            expect_vector_table=bool(spec.get("expect_vector_table", False)),
            note=spec.get("note", ""),
        )

    def as_dict(self) -> dict:
        return {
            "name": self.name, "start": self.start, "size": self.size,
            "block": self.block, "writable": self.writable, "note": self.note,
        }


class ProgrammingService:
    """Memory operations on one connected ECU.

    Takes a live :class:`~guzzionboard.diagnostics.DiagnosticsService` so it
    reuses the same session, safety gate and session log.
    """

    def __init__(self, diagnostics, *, image_dir: Path | str = DEFAULT_IMAGE_DIR,
                 vault: BaseMapVault | None = None):
        self.diag = diagnostics
        self.profile: EcuProfile = diagnostics.profile
        self.gate: SafetyGate = diagnostics.gate
        self.log = diagnostics.log
        self.image_dir = Path(image_dir)
        #: The durable store of base maps. A write is refused unless this
        #: ECU has an intact one on file, session or no session.
        #: A redirected image directory (a portable setup, a test) keeps
        #: its base maps with it rather than in the user's home.
        self.vault = vault or BaseMapVault(
            DEFAULT_BASEMAP_DIR if self.image_dir == DEFAULT_IMAGE_DIR
            else self.image_dir / "basemaps"
        )
        self.unlocked = False
        #: Explicit provider override; otherwise the registry is consulted.
        self.key_provider = None
        self.progress: Progress | None = None
        self._progress_fn: ProgressFn | None = None
        #: False in tests: simulated ECUs do not need the erase/program
        #: pacing waits that real silicon does. Hardware keeps the defaults.
        self.hardware_pacing = True

    EXTERNAL_BACKUP_ACKNOWLEDGEMENT = (
        "I confirm this file is a verified full backup from this exact ECU"
    )

    # -- catalog plumbing -------------------------------------------------
    @property
    def spec(self) -> dict:
        return (self.profile.memory or {}).get("programming", {})

    def has_implemented_writer(self, region_name: str = "flash") -> bool:
        """True when a concrete protocol write sequence is implemented for ``region_name``."""
        memory = self.profile.memory or {}
        if self.profile.id == "honda_cb500f_dashble" or memory.get("research_read_only"):
            return False
        raw_regions = memory.get("regions") or {}
        spec = raw_regions.get(region_name)
        if not isinstance(spec, dict) or int(spec.get("size") or 0) <= 0:
            return False
        if memory.get("write_supported") and spec.get("writable"):
            return True
        write_spec = self.spec.get("write") or {}
        return bool(
            isinstance(write_spec, dict)
            and any(k in write_spec for k in ("session", "erase", "request_download", "program", "records"))
        )

    def _writer_unlocked(self, region_name: str = "flash") -> bool:
        return bool(
            self.gate.allow_unverified_hardware_writes
            and self.has_implemented_writer(region_name)
        )

    def regions(self) -> dict[str, Region]:
        raw = (self.profile.memory or {}).get("regions", {})
        out: dict[str, Region] = {}
        for name, s in raw.items():
            spec_copy = dict(s)
            if self._writer_unlocked(name):
                spec_copy["writable"] = True
            out[name] = Region.from_catalog(name, spec_copy)
        return out

    def region(self, name: str) -> Region:
        try:
            return self.regions()[name]
        except KeyError:
            raise ProgrammingError(
                f"{self.profile.family} has no '{name}' region in the catalog"
            ) from None

    def capabilities(self) -> dict:
        memory = self.profile.memory or {}
        regions = self.regions()
        implemented_regions = [
            name for name in regions if self.has_implemented_writer(name)
        ]
        unlocked_any = any(self._writer_unlocked(name) for name in regions)
        effective_write = bool(memory.get("write_supported")) or unlocked_any
        return {
            "ecu": self.profile.id,
            "family": self.profile.family,
            "protocol": self.spec.get("protocol", "none"),
            "regions": {n: r.as_dict() for n, r in regions.items()},
            "read_supported": bool(memory.get("read_supported")),
            "read_blocked_reason": (
                "No ECU memory reader is implemented for this profile. "
                + str(memory.get("read_blocked_reason") or memory.get("write_blocked_reason") or "")
                if not memory.get("read_supported") else ""
            ),
            "write_supported": effective_write,
            "write_blocked_reason": (
                "" if effective_write else memory.get("write_blocked_reason", "")
            ),
            "implemented_writer_available": bool(implemented_regions),
            "implemented_writer_regions": implemented_regions,
            "unverified_hardware_writes_enabled": bool(
                self.gate.allow_unverified_hardware_writes
            ),
            "unverified_hardware_writer_unlocked": unlocked_any,
            "unverified_writer_acknowledgement": self.gate.UNVERIFIED_WRITER_ACKNOWLEDGEMENT,
            "external_backup_acknowledgement": self.EXTERNAL_BACKUP_ACKNOWLEDGEMENT,
            # These two are set only on simulated sessions — see
            # Workstation._simulated_capable_profile.  They let the UI say
            # "proved here means proved against the simulation" instead of
            # letting a green Write row imply the same of real hardware.
            "simulated": bool(memory.get("simulated")),
            "simulation_note": memory.get("simulation_note", ""),
            # Without a reader, missing security metadata does not mean the
            # ECU has no security requirements.
            "security_required": (bool(self.spec.get("security", {}).get("required"))
                                  if memory.get("read_supported") else None),
            "security_available": (self._security_available()
                                   if memory.get("read_supported") else None),
            "hardware_note": memory.get("hardware_note", ""),
            "research_read_only": bool(memory.get("research_read_only")),
            "partial_read_note": (
                "Experimental 5AM source-derived read: blocks 2–5 are FF placeholders, not read. "
                "Not a verified backup, base map, or flash-ready image. Reconnect after reading."
                if self.profile.id == "5am" and self.diag.transport.is_physical else ""
            ),
            "estimated_read_minutes": memory.get("approx_read_minutes"),
        }

    def _security_available(self) -> bool:
        if not self.spec.get("security", {}).get("required"):
            return True
        if self.key_provider is not None:
            return True
        try:
            best_provider(self.profile.id)
            return True
        except SecurityUnavailable:
            return False

    # -- progress ---------------------------------------------------------
    def _emit(self, phase: str, done: int, total: int, message: str = "") -> None:
        if self.progress is None or self.progress.phase != phase:
            self.progress = Progress(phase=phase, total=total)
        self.progress.done = done
        self.progress.total = total
        self.progress.message = message
        if self._progress_fn:
            self._progress_fn(self.progress)

    # -- session ----------------------------------------------------------
    def enter_programming_session(self) -> dict:
        """Bring the ECU into the session that allows memory access."""
        session = self.diag._require()
        spec = self.spec
        steps: list[dict] = []

        want = spec.get("session")
        if want is not None:
            frame = session.try_request([Service.START_DIAGNOSTIC_SESSION, want])
            steps.append(
                {"step": f"StartDiagnosticSession 0x{want:02X}",
                 "ok": frame is not None,
                 "response": frame.hex() if frame else "rejected"}
            )
            if frame is None:
                raise ProgrammingError(
                    f"{self.profile.family} refused diagnostic session "
                    f"0x{want:02X}. On most IAW ECUs this means the ignition is "
                    "off, the engine is running, or the ECU is not in a state "
                    "that permits programming."
                )

        baud = spec.get("baud_switch")
        if baud:
            # 5am_util and onboard-logger send the switch itself from 0x01,
            # then wait for the last old-rate stop bit before re-rating UART.
            set_baud = getattr(session.connection, "set_baudrate", None)
            if self.diag.transport.is_physical and not callable(set_baud):
                raise ProgrammingError("this physical connection cannot switch the required baud rate")
            old_source = session.source
            session.source = baud.get("tester_address", old_source)
            payload = [Service.START_DIAGNOSTIC_SESSION, baud["session"], *baud.get("params", [])]
            frame = session.try_request(payload)
            steps.append(
                {"step": "baud switch", "ok": frame is not None,
                 "response": frame.hex() if frame else "rejected"}
            )
            if frame is None:
                session.source = old_source
                raise ProgrammingError("ECU did not confirm the baud switch; reconnect before retrying")
            if self.diag.transport.is_physical:
                self._wait(0.06)
                try:
                    set_baud(baud["baud"])
                except Exception as exc:
                    raise ProgrammingError("adapter baud switch failed; reconnect before retrying") from exc
            steps.append(
                {"step": f"tester address -> 0x{session.source:02X}",
                 "ok": True, "response": ""}
            )

        self.log.action("programming_session", {"steps": steps})
        return {"steps": steps}

    def _wait(self, seconds: float) -> None:
        """Pacing between phases, from the 5am_util reference timings."""
        if self.hardware_pacing and seconds > 0:
            time.sleep(seconds)

    def _enter_write_session(self) -> dict:
        """Bring the ECU into the session the *write* path needs.

        The 5AM write bring-up differs from the read path (5am_util
        ``write_firmware``): the session frame itself moves the line to
        38400, AccessTimingParameter follows, and the tester address stays
        0xF1 instead of becoming 0x01. Families without a write-session spec
        fall back to the read bring-up.
        """
        wsess = self.spec.get("write", {}).get("session")
        if not wsess:
            return self.enter_programming_session()

        session = self.diag._require()
        steps: list[dict] = []
        set_baud = getattr(session.connection, "set_baudrate", None)
        if self.diag.transport.is_physical and wsess.get("baud") and not callable(set_baud):
            raise ProgrammingError("this physical connection cannot switch the write baud rate")
        if "source" in wsess:
            session.source = wsess["source"]

        frame = session.try_request(list(wsess["start"]))
        steps.append(
            {"step": "write session start", "ok": frame is not None,
             "response": frame.hex() if frame else "rejected"}
        )
        if frame is None:
            raise ProgrammingError(
                f"{self.profile.family} refused the programming session."
            )
        if self.profile.id == "5am" and not frame.data.startswith(b"\x85"):
            raise ProgrammingError("5AM write-session response mismatch; reconnect before retrying")

        # 5am_util changes the UART *between* the session request and the
        # timing request. On a physical link, sending timing at the previous
        # diagnostic baud would fail before a write could even start.
        if self.diag.transport.is_physical and wsess.get("baud"):
            self._wait(0.06)
            try:
                set_baud(wsess["baud"])
            except Exception as exc:
                raise ProgrammingError("write baud switch failed; reconnect before retrying") from exc
            steps.append({"step": f"write baud -> {wsess['baud']}", "ok": True, "response": ""})

        timing = wsess.get("timing")
        if timing:
            frame = session.try_request(list(timing))
            steps.append(
                {"step": "access timing parameters", "ok": frame is not None,
                 "response": frame.hex() if frame else "rejected"}
            )
            if frame is None:
                raise ProgrammingError(
                    f"{self.profile.family} refused the timing parameters."
                )

        if "source" in wsess:
            session.source = wsess["source"]
            steps.append(
                {"step": f"tester address -> 0x{wsess['source']:02X}",
                 "ok": True, "response": ""}
            )

        self.log.action("write_session", {"steps": steps})
        return {"steps": steps}

    def _unverified_key_accepted(self, explicit: bool) -> bool:
        """In-process callers may pass a flag directly; users of the app
        accept the same risk through the safety gate (audited, session-scoped).
        """
        return explicit or self.gate.allow_unverified_keys

    def unlock(self, *, allow_unverified: bool = False) -> dict:
        """SecurityAccess seed/key exchange."""
        self.unlocked = False
        spec = self.spec.get("security", {})
        if not spec.get("required"):
            self.unlocked = True
            return {"unlocked": True, "method": "not required"}

        session = self.diag._require()
        level = spec.get("level", 0x01)
        provider = self.key_provider or best_provider(
            self.profile.id,
            allow_unverified=self._unverified_key_accepted(allow_unverified),
        )

        # On the write path 5am_util addresses the 27 exchange from tester
        # 0x01 even though every other frame keeps 0xF1. The catalog records
        # that source; honour it for the exchange only.
        saved_source = session.source
        if "source" in spec:
            session.source = spec["source"]
        try:
            seed_frame = session.request([Service.SECURITY_ACCESS, level])
            if len(seed_frame.data) < 2 or seed_frame.data[0] != level:
                raise ProgrammingError("SecurityAccess seed response is empty or has the wrong level")
            seed = bytes(seed_frame.data[1:])
            self.log.action(
                "security_seed",
                {"level": level, "seed": seed.hex(" "), "provider": provider.name},
            )
            if not any(seed):
                self.unlocked = True
                return {"unlocked": True, "method": "already unlocked"}

            key = provider(seed)
            try:
                reply = session.request([Service.SECURITY_ACCESS, level + 1, *key])
                if not reply.data or reply.data[0] != level + 1:
                    raise ProgrammingError("SecurityAccess key response has the wrong level")
            except NegativeResponse as exc:
                self.log.error("security_key", f"{provider.name}: {exc}")
                raise ProgrammingError(
                    f"SecurityAccess rejected the key from '{provider.name}' "
                    f"({exc}). This project ships no verified key algorithm for "
                    f"{self.profile.family}; supply one as a plugin. Do not retry "
                    "repeatedly - ECUs lock out after a few failures."
                ) from exc
        finally:
            session.source = saved_source

        self.unlocked = True
        self.log.action(
            "security_unlocked", {"provider": provider.name, "verified": provider.verified}
        )
        return {
            "unlocked": True, "method": provider.name, "verified": provider.verified,
            "seed": seed.hex(" "), "key": key.hex(" "),
        }

    # -- reading ----------------------------------------------------------
    def read_region(
        self,
        region_name: str = "flash",
        *,
        progress: ProgressFn | None = None,
        allow_unverified_key: bool = False,
        experimental_confirmation: bool = False,
        attempt_5am_skipped_blocks: bool = False,
    ) -> FirmwareImage:
        """Read a region without interleaving diagnostics or keepalives."""
        with self.diag._lock:
            return self._read_region_locked(
                region_name, progress=progress, allow_unverified_key=allow_unverified_key,
                experimental_confirmation=experimental_confirmation,
                attempt_5am_skipped_blocks=attempt_5am_skipped_blocks,
            )

    def _read_region_locked(
        self, region_name: str, *, progress: ProgressFn | None,
        allow_unverified_key: bool, experimental_confirmation: bool,
        attempt_5am_skipped_blocks: bool,
    ) -> FirmwareImage:
        self._progress_fn = progress
        memory = self.profile.memory or {}
        if not memory.get("read_supported"):
            raise ProgrammingError(
                f"{self.profile.family}: reading is not supported by this build "
                f"({memory.get('write_blocked_reason', 'no verified read path')})"
            )
        if attempt_5am_skipped_blocks:
            if (self.profile.id != "5am" or not self.diag.transport.is_physical
                    or region_name != "flash"):
                raise ProgrammingError("the extra-block attempt is only available for physical 5AM flash")
            if not experimental_confirmation:
                raise ProgrammingError("confirm the experimental 5AM extra-block read before attempting it")
        if self.profile.id in ("honda_cb500f_dashble", "honda_pgmfi_flash_research"):
            return self._read_honda_research(region_name, experimental_confirmation)
        if not self.diag.identity:
            raise ProgrammingError("identify the ECU before reading its memory")

        region = self.region(region_name)
        if region.size <= 0:
            raise ProgrammingError(
                f"the geometry of the '{region_name}' region on "
                f"{self.profile.family} has never been captured, so this build "
                "does not know how much to read or from where. "
                f"{region.note}".strip()
            )
        self.enter_programming_session()
        if self.spec.get("security", {}).get("required"):
            self.unlock(
                allow_unverified=self._unverified_key_accepted(allow_unverified_key)
            )

        protocol = self.spec.get("protocol", "read_memory_by_address")
        reader = {
            "read_memory_by_address": self._read_by_address,
            "iaw_transfer": self._read_by_transfer,
        }.get(protocol)
        if reader is None:
            raise ProgrammingError(f"unknown programming protocol {protocol!r}")

        started = time.time()
        # The documented source selects 16 KiB blocks and synthesizes four
        # unserved blocks. Keep that physically useful read separate from the
        # simulator's earlier, contiguous model and never attest it as a backup.
        partial_5am = self.profile.id == "5am" and self.diag.transport.is_physical
        if partial_5am:
            data = (self._read_5am_source_blocks(region, attempt_skipped=True)
                    if attempt_5am_skipped_blocks else self._read_5am_source_blocks(region))
        else:
            data = reader(region)
        image = FirmwareImage(
            data=data,
            ecu_id=self.profile.id,
            region=region_name,
            source="research-read" if partial_5am else "read",
            identity=dict(self.diag.identity.fields),
            meta={
                "protocol": protocol,
                "duration_s": round(time.time() - started, 1),
                "region": region.as_dict(),
                **({"verified_backup": False,
                    "synthetic_blocks": [] if attempt_5am_skipped_blocks else [2, 3, 4, 5],
                    "extra_blocks_attempted": attempt_5am_skipped_blocks,
                    "note": ("Experimental 5AM read attempted blocks 1-19, including four blocks skipped by the source. Their address association and contents are not verified. "
                             if attempt_5am_skipped_blocks else
                             "Source-derived partial 5AM read: blocks 2-5 are filled with FF, not read. ")
                            + "Response headers do not establish block association; not a verified backup or flash-ready image. Reconnect after reading."}
                   if partial_5am else {}),
            },
        )
        self.log.action(
            "research_memory_read_complete" if partial_5am else "memory_read_complete",
            {"region": region_name, "size": image.size,
             "sha256": image.sha256, "duration_s": image.meta["duration_s"]},
        )
        from .read_sharing import configured, queue_read
        if configured():
            import threading
            try:
                threading.Thread(target=queue_read, args=(self.diag, image, region_name),
                                 name="queue-read-report", daemon=True).start()
            except RuntimeError:
                pass  # optional evidence sharing must never invalidate a completed read
        return image

    def _read_honda_research(self, region_name: str, confirmed: bool) -> FirmwareImage:
        from .protocol.honda_cbr600rr import (HondaCB500FDashSession, HONDA_RESEARCH_LAYOUTS,
                                               HONDA_EXAMPLE_INFERRED_IDS, HONDA_RESEARCH_IMAGE_SIZES,
                                               HONDA_RESEARCH_STARTS, HONDA_RESEARCH_EXAMPLE_PARTS,
                                               HONDA_RESEARCH_COMMENTED_IDS, HONDA_VFR_RESEARCH_IDS,
                                               HONDA_TABLE_ONLY_IDS, HONDA_EXAMPLE_ONLY_IDS,
                                               HONDA_FAMILY_INFERRED_IDS, HONDA_SOURCE_CONFLICTS,
                                               read_honda_research_image)
        from .protocol.honda_pgmfi import HondaPgmfiFlashResearchSession
        if (confirmed is not True or region_name != "flash" or self.gate.mode != Mode.READ_ONLY
                or not self.diag.transport.is_physical or self.diag.transport.name != "kline"):
            raise ProgrammingError("Honda research read requires explicit confirmation, read-only physical K-Line and the flash region")
        started = time.time()
        with self.diag._lock:
            session = self.diag._require()
            expected = HondaCB500FDashSession if self.profile.id == "honda_cb500f_dashble" else HondaPgmfiFlashResearchSession
            if type(session) is not expected:
                raise ProgrammingError("Honda research read requires its exact Honda session")
            def progress(done, total):
                self.diag._touch()
                self._emit("research-read", done, total, "Experimental Honda read; not a verified backup")
            data, ecm_id = read_honda_research_image(session, progress)
        part, id_offset = HONDA_RESEARCH_LAYOUTS[ecm_id]
        image = FirmwareImage(data=bytearray(data), ecu_id=self.profile.id, region=region_name,
                              source="research-read", identity={"ECM ID candidate": ecm_id.hex(' ').upper(),
                                                               "Source part candidate": part,
                                                               **({"Conflicting source example label": HONDA_RESEARCH_EXAMPLE_PARTS[ecm_id]}
                                                                  if ecm_id in HONDA_RESEARCH_EXAMPLE_PARTS else {}),
                                                               **({"Source ID conflict": HONDA_SOURCE_CONFLICTS[ecm_id]}
                                                                  if ecm_id in HONDA_SOURCE_CONFLICTS else {})},
                              meta={"protocol": "honda-source-id-research", "source_id_offset": id_offset,
                                    "candidate_source": ("AlexKovalevich/HondaECU db0a6cb8"
                                                         if ecm_id in HONDA_VFR_RESEARCH_IDS else
                                                         "aeaphichart/HondaECU-1 b59ae98b"
                                                         if ecm_id in HONDA_TABLE_ONLY_IDS else
                                                         "WiseNoodle/honda-moto-ecu-suite 85431bd8"),
                                    "read_block_size": 128 if ecm_id in HONDA_VFR_RESEARCH_IDS else 8,
                                    "source_id_table_status": ("example-only ID/part candidate; table may conflict"
                                                               if ecm_id in HONDA_EXAMPLE_ONLY_IDS else
                                                               "active table ID; named example has a different ID"
                                                               if ecm_id in HONDA_FAMILY_INFERRED_IDS else
                                                               "commented out upstream; matching example"
                                                               if ecm_id in HONDA_RESEARCH_COMMENTED_IDS
                                                               else "active upstream entry"),
                                    "id_offset_basis": ("source ID table; no example independently checked"
                                                        if ecm_id in HONDA_TABLE_ONLY_IDS else
                                                        "inferred from another family example; named example ID conflicts"
                                                        if ecm_id in HONDA_FAMILY_INFERRED_IDS else
                                                        "inferred from source-named example image"
                                                        if ecm_id in HONDA_EXAMPLE_INFERRED_IDS
                                                        else "source ID table, confirmed in example image"),
                                    "sample_size": (None if ecm_id in HONDA_TABLE_ONLY_IDS | HONDA_FAMILY_INFERRED_IDS else HONDA_RESEARCH_IMAGE_SIZES[ecm_id]),
                                    "read_size": HONDA_RESEARCH_IMAGE_SIZES[ecm_id],
                                    "read_size_basis": ("source model/family ROM size; no example independently checked"
                                                        if ecm_id in HONDA_TABLE_ONLY_IDS else
                                                        "another family example; named example ID conflicts"
                                                        if ecm_id in HONDA_FAMILY_INFERRED_IDS else
                                                        "source-named example file length"),
                                    "read_start": HONDA_RESEARCH_STARTS[ecm_id],
                                    "address_basis": ("source table offset used as assumed read start; example file origin not established"
                                                      if HONDA_RESEARCH_STARTS[ecm_id]
                                                      else "zero start assumed; example file origin not established"),
                                    "verified_backup": False,
                                    "duration_s": round(time.time() - started, 1),
                                    "note": "Source-derived experimental read, not a verified backup or flash-ready image."})
        self.log.action("research_memory_read_complete", {"size": image.size, "sha256": image.sha256,
                                                            "verified_backup": False})
        return image

    def _read_by_address(self, region: Region) -> bytearray:
        session = self.diag._require()
        out = bytearray()
        address = region.start
        while len(out) < region.size:
            chunk = min(region.block, region.size - len(out))
            data = session.read_memory_by_address(
                address, chunk, addr_bytes=region.addr_bytes
            )
            if len(data) != chunk:
                raise ProtocolError(f"memory read at 0x{address:06X} returned {len(data)} bytes, expected {chunk}")
            out += data
            address += chunk
            self.diag._touch()
            self._emit("read", len(out), region.size, f"0x{address:06X}")
        return out

    def _read_by_transfer(self, region: Region) -> bytearray:
        """The IAW ``36 11`` setup / ``36 21`` block-read path."""
        session = self.diag._require()
        setup = self.spec.get("read", {}).get("setup")
        if setup:
            session.write_guard = self.gate.session_guard(
                {Service.TRANSFER_DATA}, purpose="read"
            )
            try:
                session.request([Service.TRANSFER_DATA, *setup])
            finally:
                session.write_guard = self.gate.session_guard()

        out = bytearray()
        address = region.start
        subfn = self.spec.get("read", {}).get("block_subfn", 0x21)

        session.write_guard = self.gate.session_guard(
            {Service.TRANSFER_DATA}, purpose="read"
        )
        try:
            while len(out) < region.size:
                chunk = min(region.block, region.size - len(out))
                bank = (address >> 16) & 0xFF
                frame = session.request(
                    [Service.TRANSFER_DATA, subfn, bank,
                     (address >> 8) & 0xFF, address & 0xFF, chunk]
                )
                # 76 <subfn> <addr16> <len16> <data...>
                body = frame.data[1:]
                if (len(body) < 4 or frame.data[0] != subfn
                        or int.from_bytes(body[:2], "big") != (address & 0xffff)
                        or int.from_bytes(body[2:4], "big") != chunk):
                    raise ProtocolError(f"memory block header mismatch at 0x{address:06X}")
                payload = body[4:]
                if len(payload) != chunk:
                    raise ProtocolError(f"memory block at 0x{address:06X} returned {len(payload)} bytes, expected {chunk}")
                out += payload
                address += len(payload)
                self.diag._touch()
                self._emit("read", len(out), region.size, f"0x{address:06X}")
        finally:
            session.write_guard = self.gate.session_guard()
        return out

    def _read_5am_source_blocks(self, region: Region, *, attempt_skipped: bool = False) -> bytearray:
        """Read source-selected 5AM windows; optionally attempt skipped blocks.

        5am_util skips blocks 2-5 without explaining why. Applying its selector
        to those blocks is an unverified experiment, not source evidence that
        they are readable. Any failed request aborts rather than filling gaps.
        Neither response metadata semantics nor block association is proven
        across the range; the research output must not be treated as a backup.
        """
        if (region.name, region.start, region.size, region.block) != ("flash", 0x4000, 0x4C000, 0x20):
            raise ProgrammingError("unexpected 5AM region geometry for source-derived read")
        session = self.diag._require()
        out = bytearray()
        session.write_guard = self.gate.session_guard({Service.TRANSFER_DATA}, purpose="read")
        try:
            for block in range(1, 20):
                if block in range(2, 6) and not attempt_skipped:
                    out.extend(b"\xff" * 0x4000)
                    self._emit("research-read", len(out), region.size, f"block {block}: FF placeholder, not read")
                    continue
                setup = session.request([Service.TRANSFER_DATA, 0x11, 0, 0xFE, 2, 1, block])
                if not setup.data or setup.data[0] != 0x11:
                    raise ProtocolError(f"5AM block {block} setup response mismatch")
                for offset in range(0x4000, 0x8000, 0x20):
                    frame = session.request([Service.TRANSFER_DATA, 0x21, 0, offset >> 8, offset & 0xff, 0x20])
                    # One upstream transcript shows 40 00 00 20 at the first
                    # window; it does not establish that these bytes echo all
                    # later requests. The newer onboard-logger fake even uses
                    # fixed metadata. Neither identifies the selected block.
                    if len(frame.data) != 5 + 0x20 or frame.data[0] != 0x21:
                        raise ProtocolError(f"invalid 5AM read response at block {block}, offset 0x{offset:04X}")
                    out.extend(frame.data[5:])
                    self.diag._touch()
                    self._emit("research-read", len(out), region.size, f"block {block}, 0x{offset:04X}; unverified research image")
        finally:
            session.write_guard = self.gate.session_guard()
        return out

    # -- backup -----------------------------------------------------------
    def backup(
        self, region_name: str = "flash", *, progress: ProgressFn | None = None,
        verify: bool = True, allow_unverified_key: bool = False,
        save_base_map: bool = True,
        attempt_5am_skipped_blocks: bool = False,
        experimental_confirmation: bool = False,
    ) -> dict:
        """Read a region twice and only trust it if both reads agree.

        A single read of a flash over a noisy K-Line is not a backup. Two
        identical reads is the cheapest honest verification available.
        """
        if (self.profile.memory or {}).get("research_read_only"):
            raise ProgrammingError("Experimental Honda reads cannot create a verified backup or base map")
        full_physical_5am = (
            self.profile.id == "5am"
            and self.diag.transport.is_physical
            and attempt_5am_skipped_blocks
            and experimental_confirmation
            and self.gate.allow_unverified_hardware_writes
        )
        if self.profile.id == "5am" and self.diag.transport.is_physical and not full_physical_5am:
            raise ProgrammingError("The physical 5AM source-derived read is partial and cannot create a verified backup or base map; use Read for an experimental image")
        if full_physical_5am and not verify:
            raise ProgrammingError("A full 19-block physical 5AM backup requires dual-read verification")

        first = self.read_region(
            region_name, progress=progress,
            allow_unverified_key=allow_unverified_key,
            experimental_confirmation=experimental_confirmation if full_physical_5am else False,
            attempt_5am_skipped_blocks=attempt_5am_skipped_blocks if full_physical_5am else False,
        )
        result = {"image": first, "verified": False, "attempts": 1}

        if verify:
            second = self.read_region(
                region_name, progress=progress,
                allow_unverified_key=allow_unverified_key,
                experimental_confirmation=experimental_confirmation if full_physical_5am else False,
                attempt_5am_skipped_blocks=attempt_5am_skipped_blocks if full_physical_5am else False,
            )
            result["attempts"] = 2
            if first.matches(second):
                result["verified"] = True
            else:
                diff = first.diff(second)
                self.log.error(
                    "backup_verify",
                    f"two reads disagree in {diff['changed_bytes']} bytes",
                )
                result["diff"] = diff
                raise VerificationFailed(
                    f"Two consecutive reads of {region_name} differ in "
                    f"{diff['changed_bytes']} bytes. The link is unreliable - "
                    "check the adapter, the ground and the battery before "
                    "trusting any backup."
                )

        if full_physical_5am:
            val_report = self.validate(first, region_name)
            if not val_report["ok"]:
                raise VerificationFailed(
                    "19-block 5AM backup failed structural validation: "
                    + "; ".join(f["detail"] for f in val_report["fatal"])
                )
            first.source = "backup"
            first.meta["verified_backup"] = True
            first.meta["note"] = (
                "Dual-read verified 19-block 5AM flash backup created under "
                "operator-unlocked hardware writer gate."
            )

        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"{self.profile.id}-{region_name}-{stamp}.bin"
        path = first.save(self.image_dir / name)

        self.gate.state.verified_backup = bool(result["verified"])
        self.gate.state.backup_path = str(path)

        # A verified backup is also the chance to secure the guaranteed way
        # back. The first one taken from this ECU becomes its base map, kept
        # outside the working image directory and re-hashed before every
        # write; later ones are filed as extra restore points. This happens
        # automatically because the moment it is easy to skip is the moment
        # it gets skipped.
        base_map = None
        if result["verified"] and save_base_map:
            try:
                base_map = self.vault.store(
                    ecu_id=self.profile.id,
                    hardware=self._ecu_hardware(),
                    region=region_name,
                    source_path=path,
                    verified=True,
                    identity=dict(self.diag.identity.fields)
                    if self.diag.identity else {},
                    note="saved automatically from a verified backup",
                )
                self.log.action(
                    "base_map_store",
                    {"key": base_map.get("key"), "path": base_map.get("path"),
                     "is_base_map": base_map.get("is_base_map", False)},
                )
            except Exception as exc:                    # never lose the backup
                self.log.error("base_map_store", str(exc))
                base_map = {"error": str(exc)}
        self._refresh_base_map_state(region_name)

        self.log.action(
            "backup",
            {"region": region_name, "path": str(path), "sha256": first.sha256,
             "verified": result["verified"]},
        )
        return {
            "path": str(path),
            "verified": result["verified"],
            "attempts": result["attempts"],
            "describe": first.describe(),
            "base_map": base_map or self.base_map_status(region_name),
        }

    # -- the base map (the guaranteed restore map) -------------------------
    def _ecu_hardware(self) -> str:
        if self.diag.identity:
            return str(self.diag.identity.fields.get("Hardware", "")).strip()
        return str(self.gate.state.ecu_hardware or "").strip()

    def base_map_status(self, region_name: str = "flash") -> dict:
        """What stands between this ECU and an unrecoverable write."""
        status = self.vault.status(
            self.profile.id, self._ecu_hardware(), region_name
        )
        status["ecu_family"] = self.profile.family
        return status

    def _refresh_base_map_state(self, region_name: str = "flash") -> dict:
        status = self.base_map_status(region_name)
        self.gate.state.base_map = bool(status.get("intact"))
        self.gate.state.base_map_path = status.get("path", "") or ""
        return status

    def save_base_map(self, path: str | Path, region_name: str = "flash",
                      *, verified: bool = True, replace: bool = False,
                      note: str = "") -> dict:
        """File an existing verified image as this ECU's base map.

        For the case where the backup was taken earlier (or by GuzziDiag)
        and the operator wants the vault to know about it. The file is
        copied, hashed and indexed exactly like an automatic save.
        """
        if (self.profile.memory or {}).get("research_read_only"):
            raise ProgrammingError("Experimental research reads cannot be filed as verified base maps")
        store = self.vault.replace_base_map if replace else self.vault.store
        result = store(
            ecu_id=self.profile.id,
            hardware=self._ecu_hardware(),
            region=region_name,
            source_path=path,
            verified=verified,
            identity=dict(self.diag.identity.fields) if self.diag.identity else {},
            note=note or "filed by the operator",
        )
        self.log.action(
            "base_map_save",
            {"path": str(path), "region": region_name, "replace": replace},
        )
        self._refresh_base_map_state(region_name)
        return result

    def restore_plan(self, region_name: str = "flash") -> dict:
        """Everything needed to put the base map back, in order.

        Restoring is an ordinary write of a known-good image, so it runs
        through the same gate as any other write - no hidden fast path.
        """
        status = self.base_map_status(region_name)
        if not status.get("intact"):
            return dict(status, steps=[], ready=False)
        return dict(
            status,
            ready=True,
            key=ecu_key(self.profile.id, self._ecu_hardware(), region_name),
            steps=[
                "Keep the ECU powered from a charger for the whole restore.",
                "Enable programming and acknowledge the risk.",
                f"Validate {status['path']} against this ECU.",
                f"Write {status['path']} back to the {region_name} region.",
                "Re-read and compare the SHA-256 with "
                f"{status.get('sha256', '')[:16]}… before powering down.",
            ],
        )

    def attest_external_backup(
        self,
        path: str | Path,
        region_name: str = "flash",
        *,
        acknowledgement: str,
        save_base_map: bool = True,
        note: str = "",
    ) -> dict:
        """Attest an externally captured verified stock dump for this identified ECU.

        Supports both exact region-sized dumps (e.g. 311,296-byte 5AM flash
        0x4000..0x50000) and full ECU memory dumps (e.g. 327,680-byte GuzziDiag /
        IAW5xReader 0x00000..0x50000 images, sliced to ``region.start..end``).
        """
        if (self.profile.memory or {}).get("research_read_only"):
            raise ProgrammingError(
                "Experimental research profiles cannot attest verified backups"
            )
        if not self.diag.identity:
            raise ProgrammingError(
                "identify the ECU before attesting an external backup"
            )
        if acknowledgement.strip() != self.EXTERNAL_BACKUP_ACKNOWLEDGEMENT:
            raise ProgrammingError(
                "to attest an external backup, repeat exactly: "
                f"{self.EXTERNAL_BACKUP_ACKNOWLEDGEMENT!r}"
            )
        region = self.region(region_name)
        if region.size <= 0:
            raise ProgrammingError(f"region {region_name!r} has no configured size")

        source_file = Path(path).expanduser()
        if not source_file.is_file():
            raise ProgrammingError(f"backup file does not exist: {source_file}")
        loaded = FirmwareImage.from_file(source_file)
        if loaded.meta.get("synthetic_blocks"):
            raise ProgrammingError(
                "cannot attest a partial research read with synthetic 0xFF placeholder blocks"
            )
        raw_bytes = bytes(loaded.data)
        full_size = int((self.profile.memory or {}).get("image_size") or 0)
        sliced = False
        if len(raw_bytes) == region.size:
            region_bytes = raw_bytes
        elif (
            full_size > 0
            and len(raw_bytes) == full_size
            and region.start + region.size <= full_size
        ):
            region_bytes = raw_bytes[region.start : region.start + region.size]
            sliced = True
        else:
            expected_desc = f"{region.size} bytes"
            if full_size and full_size != region.size:
                expected_desc += f" (or {full_size}-byte full dump)"
            raise IncompatibleImage(
                f"backup file is {len(raw_bytes)} bytes, expected {expected_desc}"
            )

        att_identity = dict(self.diag.identity.fields)
        candidate = FirmwareImage(
            data=region_bytes,
            ecu_id=self.profile.id,
            region=region_name,
            source="external-backup",
            identity=att_identity,
            meta={
                "attested_from": str(source_file),
                "original_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "original_bytes": len(raw_bytes),
                "sliced_from_full_dump": sliced,
                "verified_backup": True,
                "note": note or "attested external verified backup",
            },
        )
        validation = self.validate(candidate, region_name)
        if not validation["ok"]:
            raise IncompatibleImage(
                "external backup failed validation against this ECU: "
                + "; ".join(f["detail"] for f in validation["fatal"])
            )
        hw_check = self.gate._hardware_family_check(
            str(att_identity.get("Hardware", "")),
            extract_hardware_strings(candidate.data),
        )
        if not hw_check.passed:
            raise IncompatibleImage(hw_check.detail)

        self.image_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        saved = candidate.save(
            self.image_dir / f"{self.profile.id}-{region_name}-attested-{stamp}.bin"
        )
        self.gate.state.verified_backup = True
        self.gate.state.backup_path = str(saved)

        base_map = None
        if save_base_map:
            base_map = self.vault.store(
                ecu_id=self.profile.id,
                hardware=self._ecu_hardware(),
                region=region_name,
                source_path=saved,
                verified=True,
                identity=att_identity,
                note=note or "filed from attested external backup",
            )
            self.log.action(
                "base_map_store",
                {
                    "key": base_map.get("key"),
                    "path": base_map.get("path"),
                    "is_base_map": base_map.get("is_base_map", False),
                },
            )
        self._refresh_base_map_state(region_name)
        self.log.action(
            "external_backup_attested",
            {
                "region": region_name,
                "source_path": str(source_file),
                "saved_path": str(saved),
                "sha256": candidate.sha256,
                "sliced_from_full_dump": sliced,
            },
        )
        return {
            "path": str(saved),
            "verified": True,
            "bytes": candidate.size,
            "sha256": candidate.sha256,
            "sliced_from_full_dump": sliced,
            "describe": candidate.describe(),
            "validation": validation,
            "base_map": base_map or self.base_map_status(region_name),
        }

    # -- validation -------------------------------------------------------
    def validate(self, image: FirmwareImage, region_name: str = "flash") -> dict:
        identity = dict(self.diag.identity.fields) if self.diag.identity else None
        findings = image.validate_for(
            self.profile, region=region_name, target_identity=identity
        )
        summary = summarise_findings(findings)
        summary["image"] = image.describe()
        self.log.action("image_validate", {"region": region_name, "ok": summary["ok"]})
        return summary

    def check_write(self, region_name: str = "flash",
                    image: FirmwareImage | None = None) -> Decision:
        """The write gate.  Pass the candidate ``image`` to include the
        hardware-family check in the decision; without one the decision
        cannot speak to compatibility and :meth:`write_region` re-evaluates
        with the image before anything is transmitted.
        """
        from dataclasses import replace as dc_replace

        if self.diag.identity:
            # The live session is the authority on what is on the bench;
            # keep the gate's picture of it current.
            hardware = str(self.diag.identity.fields.get("Hardware", "")).strip()
            if hardware:
                self.gate.state.ecu_hardware = hardware
        # The vault is the authority on whether a way back exists; the
        # gate only mirrors it, and it is re-checked (by re-hashing the
        # file) every single time a write is considered.
        self._refresh_base_map_state(region_name)
        image_hardware = None
        image_embedded = None
        if image is not None:
            image_hardware = str((image.identity or {}).get("Hardware", "")).strip()
            image_embedded = extract_hardware_strings(image.data)
        memory = self.profile.memory or {}
        region = self.regions().get(region_name)
        unlocked = self._writer_unlocked(region_name)
        effective_write = bool(memory.get("write_supported")) or unlocked
        eval_profile = self.profile
        if unlocked and "memory_write" not in eval_profile.capabilities:
            eval_profile = dc_replace(
                eval_profile,
                capabilities=tuple(eval_profile.capabilities) + ("memory_write",),
            )
        decision = self.gate.evaluate(
            f"write:{region_name}", Risk.IRREVERSIBLE,
            profile=eval_profile, capability="memory_write",
            image_hardware=image_hardware,
            image_embedded_hardware=image_embedded,
            additional_checks=(
                Check("write-supported", effective_write,
                      "" if effective_write else str(memory.get("write_blocked_reason") or "no ECU writer enabled for this profile")),
                Check("writable-region", bool(region and region.writable),
                      f"{region_name!r} is not a declared writable region"),
            ),
        )
        self.log.decision(decision.as_dict())
        return decision

    # -- writing ----------------------------------------------------------
    def write_region(
        self,
        image: FirmwareImage,
        token: str,
        region_name: str = "flash",
        *,
        progress: ProgressFn | None = None,
        allow_unverified_key: bool = False,
    ) -> dict:
        """Hold the ECU session exclusively through programming and readback."""
        with self.diag._lock:
            return self._write_region_locked(image, token, region_name, progress=progress,
                                             allow_unverified_key=allow_unverified_key)

    def _write_region_locked(
        self, image: FirmwareImage, token: str, region_name: str, *,
        progress: ProgressFn | None, allow_unverified_key: bool,
    ) -> dict:
        """Erase, transfer, program and verify. Every step can refuse."""
        self._progress_fn = progress
        memory = self.profile.memory or {}
        if self.profile.id == "honda_cb500f_dashble":
            raise ProgrammingError("The experimental Honda profile never writes ECU memory")
        region = self.region(region_name)

        # 1. policy
        effective_write = bool(memory.get("write_supported")) or self._writer_unlocked(region_name)
        if not effective_write:
            raise SafetyViolation(self.check_write(region_name))
        if not region.writable:
            raise ProgrammingError(f"the {region_name} region is not writable")
        # The hardware-family gate runs here, on the concrete image: an
        # HW1xx image into an HW3xx ECU (or any other cross-family pair)
        # bricks the ECU, and this is the check that refuses it before a
        # single frame is transmitted.
        decision = self.check_write(region_name, image=image)
        if not decision.allowed:
            raise SafetyViolation(decision)
        self.gate.consume(token, f"write:{region_name}")

        # 2. structure and provenance.  A file with the right length is not
        # enough: never silently reinterpret a dump for another region/ECU.
        if image.region != region_name:
            raise IncompatibleImage(
                f"image is labelled for region {image.region!r}, not {region_name!r}"
            )
        if image.ecu_id and image.ecu_id != self.profile.id:
            raise IncompatibleImage(
                f"image belongs to ECU {image.ecu_id!r}, not {self.profile.id!r}"
            )
        validation = self.validate(image, region_name)
        if not validation["ok"]:
            raise IncompatibleImage(
                "image failed validation: "
                + "; ".join(f["detail"] for f in validation["fatal"])
            )
        # validate_for reports the byte-level hardware-string comparison
        # (a missing embedded string is only a warning there, because
        # inspection workflows must not be blocked by it).  The write is
        # different: the gate above already required a captured provenance
        # identity and a matching family, so a fatal hardware finding here
        # is the second, independent net - for example an image whose
        # embedded strings belong to another ECU than its sidecar claims.

        # 3. backup must exist and be verified
        if not self.gate.state.verified_backup:
            raise ProgrammingError(
                "no verified backup for this ECU. Take one and let it verify "
                "before writing anything."
            )

        # 3b. and a base map must be on file and still intact. The session
        # backup proves this read worked; the base map is what is still
        # there tomorrow, after the laptop has been closed and the temp
        # directory swept, if the bike needs to go back to stock.
        base_map = self._refresh_base_map_state(region_name)
        if not base_map.get("intact"):
            raise ProgrammingError(
                "no intact base map on file for this ECU "
                f"({base_map.get('reason') or 'none saved'}). Save one from a "
                "verified backup first - it is the only guaranteed way back."
            )

        # Build the exact transfer and checksum before entering a write
        # session or requesting an erase. Never discover encoding failures
        # only after the ECU might have lost its program.
        upload = self._upload_payload(image)
        program_spec = self.spec.get("write", {}).get("program", {})
        program_checksum = None
        if isinstance(program_spec, dict) and program_spec.get("checksum"):
            if self.spec.get("write", {}).get("upload_encoding") != "iaw5am-addror":
                raise ProgrammingError("no checksum form for this upload encoding")
            program_checksum = iaw5am_upload_checksum(image.data)

        checkpoint = self._checkpoint_path(region_name)
        self._write_checkpoint(
            checkpoint,
            {"phase": "starting", "region": region_name,
             "erase_may_have_started": False, "image_sha256": image.sha256,
             "backup": self.gate.state.backup_path,
             "base_map": self.gate.state.base_map_path,
             "identity": dict(self.diag.identity.fields) if self.diag.identity else {}},
        )

        erase_may_have_started = False
        try:
            self._enter_write_session()
            if self.spec.get("security", {}).get("required"):
                self.unlock(
                    allow_unverified=self._unverified_key_accepted(
                        allow_unverified_key
                    )
                )

            session = self.diag._require()
            armed = {
                Service.REQUEST_DOWNLOAD,
                Service.TRANSFER_DATA,
                Service.REQUEST_TRANSFER_EXIT,
                Service.WRITE_MEMORY_BY_ADDRESS,
                Service.WRITE_DATA_BY_LOCAL_ID,
                Service.START_ROUTINE_BY_LOCAL_ID,
                Service.REQUEST_ROUTINE_RESULTS,  # 5AM erase/program trigger
            }
            session.write_guard = self.gate.session_guard(armed)
            try:
                self._pre_write_records()
                # Treat the erase arm itself as the point of no return: a
                # lost reply does not prove the ECU did not act on it.
                self._write_checkpoint(checkpoint, {"phase": "erase_requested", "erase_may_have_started": True})
                erase_may_have_started = True
                self._erase(region)
                self._write_checkpoint(checkpoint, {"phase": "erased"})
                self._transfer(image, region, payload=upload)
                self._write_checkpoint(checkpoint, {"phase": "transferred"})
                self._finalise(image, region, checksum=program_checksum)
            finally:
                session.write_guard = self.gate.session_guard()

            # 4. verify by reading it back
            self._emit("verify", 0, region.size, "reading back")
            readback = self.read_region(
                region_name,
                progress=progress,
                allow_unverified_key=self._unverified_key_accepted(allow_unverified_key),
            )
            synthetic_blocks = list(readback.meta.get("synthetic_blocks") or [])
            if synthetic_blocks == [2, 3, 4, 5] and len(readback.data) == len(image.data) == 0x4C000:
                # Physical 5AM source-derived read skips blocks 2..5
                # (offsets 0x4000..0x14000 inside the 0x4C000 flash region).
                # Verify every served block byte-for-byte against ``image``.
                served_diffs = sum(
                    a != b
                    for idx, (a, b) in enumerate(zip(readback.data, image.data))
                    if not (0x4000 <= idx < 0x14000)
                )
                if served_diffs:
                    diff = {"changed_bytes": served_diffs, "unverified_blocks": synthetic_blocks}
                    self._write_checkpoint(
                        checkpoint, {"phase": "verify_failed", "diff": diff}
                    )
                    raise VerificationFailed(
                        f"Write verification FAILED: {served_diffs} readable bytes "
                        "differ from what was sent. DO NOT power the ECU down. "
                        f"Retry the write, or restore {self.gate.state.backup_path}."
                    )
            elif not readback.matches(image):
                diff = readback.diff(image)
                self._write_checkpoint(
                    checkpoint, {"phase": "verify_failed", "diff": diff}
                )
                raise VerificationFailed(
                    f"Write verification FAILED: {diff['changed_bytes']} bytes "
                    "differ from what was sent. DO NOT power the ECU down. "
                    f"Retry the write, or restore {self.gate.state.backup_path}."
                )

            self._write_checkpoint(checkpoint, {"phase": "complete"})
            self.log.action(
                "write_complete",
                {
                    "region": region_name,
                    "sha256": image.sha256,
                    "verified": True,
                    **({"partial_readback_unverified_blocks": synthetic_blocks} if synthetic_blocks else {}),
                },
            )
            return {
                "ok": True, "region": region_name, "verified": True,
                "sha256": image.sha256, "bytes": image.size,
                **({"partial_readback_unverified_blocks": synthetic_blocks} if synthetic_blocks else {}),
            }

        except VerificationFailed as exc:
            # The phase is already recorded and is more specific than "failed".
            self._write_checkpoint(checkpoint, {"error": str(exc)})
            self.log.error("write", str(exc))
            raise
        except Exception as exc:
            phase = "failed_after_erase_requested" if erase_may_have_started else "failed_before_erase"
            self._write_checkpoint(checkpoint, {"phase": phase, "error": str(exc),
                                               "erase_may_have_started": erase_may_have_started})
            self.log.error("write", str(exc))
            raise

    def _pre_write_records(self) -> None:
        """Writer and reflash-date records (service 0x3B).

        5am_util is explicit: leave these out and RequestDownload fails. The
        catalog carries them as data so the values stay auditable.
        """
        session = self.diag._require()
        for record in self.spec.get("write", {}).get("records", []):
            did = bytes(record["did"])
            value = bytes(record.get("value", []))
            reply = session.request([Service.WRITE_DATA_BY_LOCAL_ID, *did, *value])
            if self.profile.id == "5am" and (not did or not reply.data.startswith(did[:1])):
                raise ProtocolError("5AM writer/date record response mismatch")
            self.diag._touch()

    def _erase(self, region: Region) -> None:
        session = self.diag._require()
        self._emit("erase", 0, 1, "erasing")
        erase = self.spec.get("write", {}).get("erase")
        if isinstance(erase, dict) and "start" in erase:
            # The documented IAW sequence: a routine call arms the erase and
            # a routine-results request is what actually runs it.
            started = session.request(list(erase["start"]))
            if self.profile.id == "5am":
                if not started.data.startswith(b"\x02"):
                    raise ProtocolError("5AM erase routine response mismatch")
                # Source-derived bounded wait: consume the stream without
                # retransmitting 33 02. A positive response is required
                # before RequestDownload; a timeout leaves erase uncertain.
                done = session.request(list(erase["trigger"]), timeout=3.0, pending_timeout=90.0)
                if not done.data.startswith(b"\x02"):
                    raise ProtocolError("5AM erase completion response mismatch")
            else:
                session.request(list(erase["trigger"]))
                self._wait(erase.get("wait_s", 0))
        else:
            legacy = self.spec.get("erase")
            if legacy:
                session.request(list(legacy))
            else:
                session.request(
                    [Service.REQUEST_DOWNLOAD,
                     *region.start.to_bytes(region.addr_bytes, "big"),
                     0x00,
                     *region.size.to_bytes(region.addr_bytes, "big")]
                )
        self.diag._touch()
        self._emit("erase", 1, 1, "erased")

    def _upload_payload(self, image: FirmwareImage) -> bytes:
        """What actually goes on the wire: the encoded blob, not the dump."""
        encoding = self.spec.get("write", {}).get("upload_encoding")
        if not encoding:
            return image.data
        if encoding != "iaw5am-addror":
            raise ProgrammingError(f"unknown upload encoding {encoding!r}")
        return iaw5am_upload_blob(image.data)

    def _transfer(self, image: FirmwareImage, region: Region, *, payload: bytes | None = None) -> None:
        session = self.diag._require()
        write_spec = self.spec.get("write", {})
        download = write_spec.get("request_download")
        if download:
            session.request(list(download))
            self.diag._touch()

        if payload is None:
            payload = self._upload_payload(image)
        block = write_spec.get("chunk", write_spec.get("block", region.block))
        subfn = write_spec.get("block_subfn")
        sent = 0
        address = region.start
        while sent < len(payload):
            chunk = payload[sent : sent + block]
            if subfn is None:
                if self.profile.id == "5am":
                    session.request([Service.TRANSFER_DATA, *chunk], force_long=True)
                else:
                    session.request([Service.TRANSFER_DATA, *chunk])
            else:
                bank = (address >> 16) & 0xFF
                session.request(
                    [Service.TRANSFER_DATA, subfn, bank,
                     (address >> 8) & 0xFF, address & 0xFF, len(chunk), *chunk]
                )
            sent += len(chunk)
            address += len(chunk)
            self.diag._touch()
            self._emit("write", sent, len(payload), f"0x{address:06X}")

    def _finalise(self, image: FirmwareImage, region: Region, *, checksum: int | None = None) -> None:
        session = self.diag._require()
        self._emit("program", 0, 1, "programming")
        # Transfer exit is a required state transition, not a capability
        # probe.  Swallowing a negative response here could make us run the
        # erase/program routine against an incomplete download.
        if self.profile.id == "5am":
            session.request([Service.REQUEST_TRANSFER_EXIT], force_long=True)
        else:
            session.request([Service.REQUEST_TRANSFER_EXIT])
        self.diag._touch()

        program = self.spec.get("write", {}).get("program")
        if isinstance(program, dict) and "start" in program:
            payload = list(program["start"])
            if program.get("checksum"):
                encoding = self.spec.get("write", {}).get("upload_encoding")
                if encoding != "iaw5am-addror":
                    raise ProgrammingError(
                        f"no checksum form for upload encoding {encoding!r}"
                    )
                # The ECU validates the plain image, decoded from the blob.
                if checksum is None:
                    checksum = iaw5am_upload_checksum(image.data)
                payload += [checksum >> 8, checksum & 0xFF]
            if self.profile.id == "5am":
                armed = session.request(payload, force_long=True)
                if not armed.data.startswith(b"\x01"):
                    raise ProtocolError("5AM program routine response mismatch")
                # Upstream reports pending and says a final positive response
                # is not established on all ECUs. Absence is uncertainty, not
                # successful programming or permission to read back yet.
                done = session.request(list(program["trigger"]), timeout=3.0, pending_timeout=120.0)
                if done.data and not done.data.startswith(b"\x01"):
                    raise ProtocolError("5AM program completion response mismatch")
            else:
                session.request(payload)
                session.request(list(program["trigger"]))
                self._wait(program.get("wait_s", 0))
            self.diag._touch()

        self._emit("program", 1, 1, "programmed")

    # -- checkpoints ------------------------------------------------------
    def _checkpoint_path(self, region_name: str) -> Path:
        self.image_dir.mkdir(parents=True, exist_ok=True)
        return self.image_dir / f"{self.profile.id}-{region_name}-checkpoint.json"

    def _write_checkpoint(self, path: Path, data: dict) -> None:
        existing = {}
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
        existing.update(data)
        existing["updated_at"] = time.time()
        path.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")

    def pending_checkpoint(self, region_name: str = "flash") -> dict | None:
        """An interrupted write, if there is one."""
        path = self._checkpoint_path(region_name)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if data.get("phase") in ("complete", None):
            return None
        data["recovery"] = self.recovery_advice(data.get("phase", ""))
        return data

    @staticmethod
    def recovery_advice(phase: str) -> list[str]:
        common = [
            "Keep the ignition on and the ECU powered. Do not disconnect anything.",
            "Put the battery on a charger before retrying.",
        ]
        by_phase = {
            "starting": ["The erase was not yet requested; writer records may have changed."],
            "failed_before_erase": ["The erase was not requested; writer records may have changed. Diagnose the failure before retrying."],
            "erase_requested": ["The erase may have started even if no reply arrived. The ECU may not have a valid program."],
            "failed_after_erase_requested": ["The erase may have started; the ECU may not have a valid program. Do not ride. Seek model-specific recovery assistance."],
            "erased": [
                "The region was erased but not written. The ECU will not run.",
                "Retry the write with the same image, or restore the backup.",
            ],
            "transferred": [
                "Data was transferred but the programming step did not confirm.",
                "Do not assume a repeat transfer is accepted; seek model-specific recovery assistance.",
            ],
            "verify_failed": [
                "The ECU does not contain what was sent.",
                "Retry the write. If it fails again, restore the backup image.",
            ],
            "failed": [
                "The write aborted. Restore the backup image recorded in this "
                "checkpoint before riding the motorcycle.",
            ],
        }
        return common + by_phase.get(phase, ["Restore the backup image."])

    # -- EEPROM convenience ----------------------------------------------
    def read_eeprom(self, **kw) -> FirmwareImage:
        """EEPROM holds the learned values: TPS zero, CO trim, fault memory.

        Far smaller and far less dangerous than flash, and the thing most
        owners actually want to inspect or move between ECUs.
        """
        return self.read_region("eeprom", **kw)
