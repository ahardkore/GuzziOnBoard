"""ECU memory reading and programming.

This is the most dangerous code in the project, so it is also the most
defensive. The order of operations is not negotiable:

    identify -> backup -> verify backup by re-reading -> validate new image
    -> arm safety gate -> erase -> transfer -> program -> verify by re-reading

A write that cannot be verified is reported as a failure even if the ECU said
"ok", and a failed transfer leaves a resumable checkpoint on disk plus a
recovery procedure in the session log.

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

    The readable region observed on a 5AM runs from 0x4000 to 0x50000; the
    bootloader below 0x4000 is not reachable this way.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .catalog import EcuProfile
from .firmware import (
    FirmwareImage,
    IncompatibleImage,
    checksums,
    extract_hardware_strings,
    iaw5am_upload_blob,
    iaw5am_upload_checksum,
    summarise_findings,
)
from .protocol.kwp2000 import NegativeResponse, ProtocolError, Service
from .safety import Decision, Risk, SafetyGate, SafetyViolation
from .security import SecurityUnavailable, best_provider

#: Where backups and checkpoints live.
DEFAULT_IMAGE_DIR = Path.home() / ".guzzionboard" / "images"


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

    def __init__(self, diagnostics, *, image_dir: Path | str = DEFAULT_IMAGE_DIR):
        self.diag = diagnostics
        self.profile: EcuProfile = diagnostics.profile
        self.gate: SafetyGate = diagnostics.gate
        self.log = diagnostics.log
        self.image_dir = Path(image_dir)
        self.unlocked = False
        #: Explicit provider override; otherwise the registry is consulted.
        self.key_provider = None
        self.progress: Progress | None = None
        self._progress_fn: ProgressFn | None = None
        #: False in tests: simulated ECUs do not need the erase/program
        #: pacing waits that real silicon does. Hardware keeps the defaults.
        self.hardware_pacing = True

    # -- catalog plumbing -------------------------------------------------
    @property
    def spec(self) -> dict:
        return (self.profile.memory or {}).get("programming", {})

    def regions(self) -> dict[str, Region]:
        raw = (self.profile.memory or {}).get("regions", {})
        return {name: Region.from_catalog(name, s) for name, s in raw.items()}

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
        return {
            "ecu": self.profile.id,
            "family": self.profile.family,
            "protocol": self.spec.get("protocol", "none"),
            "regions": {n: r.as_dict() for n, r in regions.items()},
            "read_supported": bool(memory.get("read_supported")),
            "write_supported": bool(memory.get("write_supported")),
            "write_blocked_reason": memory.get("write_blocked_reason", ""),
            # These two are set only on simulated sessions — see
            # Workstation._simulated_capable_profile.  They let the UI say
            # "proved here means proved against the simulation" instead of
            # letting a green Write row imply the same of real hardware.
            "simulated": bool(memory.get("simulated")),
            "simulation_note": memory.get("simulation_note", ""),
            "security_required": bool(self.spec.get("security", {}).get("required")),
            "security_available": self._security_available(),
            "hardware_note": memory.get("hardware_note", ""),
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
            payload = [Service.START_DIAGNOSTIC_SESSION, baud["session"], *baud.get("params", [])]
            frame = session.try_request(payload)
            steps.append(
                {"step": "baud switch", "ok": frame is not None,
                 "response": frame.hex() if frame else "rejected"}
            )
            if frame is not None and "tester_address" in baud:
                # The 5AM transcript shows the tester address becoming 0x01
                # after the switch; everything afterwards uses the new pair.
                session.source = baud["tester_address"]
                steps.append(
                    {"step": f"tester address -> 0x{baud['tester_address']:02X}",
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

        frame = session.try_request(list(wsess["start"]))
        steps.append(
            {"step": "write session start", "ok": frame is not None,
             "response": frame.hex() if frame else "rejected"}
        )
        if frame is None:
            raise ProgrammingError(
                f"{self.profile.family} refused the programming session."
            )

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
                session.request([Service.SECURITY_ACCESS, level + 1, *key])
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
    ) -> FirmwareImage:
        """Read a whole region into a :class:`FirmwareImage`."""
        self._progress_fn = progress
        memory = self.profile.memory or {}
        if not memory.get("read_supported"):
            raise ProgrammingError(
                f"{self.profile.family}: reading is not supported by this build "
                f"({memory.get('write_blocked_reason', 'no verified read path')})"
            )
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
        data = reader(region)
        image = FirmwareImage(
            data=data,
            ecu_id=self.profile.id,
            region=region_name,
            source="read",
            identity=dict(self.diag.identity.fields),
            meta={
                "protocol": protocol,
                "duration_s": round(time.time() - started, 1),
                "region": region.as_dict(),
            },
        )
        self.log.action(
            "memory_read_complete",
            {"region": region_name, "size": image.size,
             "sha256": image.sha256, "duration_s": image.meta["duration_s"]},
        )
        return image

    def _read_by_address(self, region: Region) -> bytearray:
        session = self.diag._require()
        out = bytearray()
        address = region.start
        while len(out) < region.size:
            chunk = min(region.block, region.size - len(out))
            out += session.read_memory_by_address(
                address, chunk, addr_bytes=region.addr_bytes
            )
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
                if len(body) < 4:
                    raise ProtocolError(
                        f"short block response at 0x{address:06X}: {frame.hex()}"
                    )
                payload = body[4:]
                if not payload:
                    raise ProtocolError(f"empty block at 0x{address:06X}")
                out += payload
                address += len(payload)
                self.diag._touch()
                self._emit("read", len(out), region.size, f"0x{address:06X}")
        finally:
            session.write_guard = self.gate.session_guard()
        return out

    # -- backup -----------------------------------------------------------
    def backup(
        self, region_name: str = "flash", *, progress: ProgressFn | None = None,
        verify: bool = True, allow_unverified_key: bool = False,
    ) -> dict:
        """Read a region twice and only trust it if both reads agree.

        A single read of a flash over a noisy K-Line is not a backup. Two
        identical reads is the cheapest honest verification available.
        """
        first = self.read_region(
            region_name, progress=progress, allow_unverified_key=allow_unverified_key
        )
        result = {"image": first, "verified": False, "attempts": 1}

        if verify:
            second = self.read_region(
                region_name, progress=progress,
                allow_unverified_key=allow_unverified_key,
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

        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"{self.profile.id}-{region_name}-{stamp}.bin"
        path = first.save(self.image_dir / name)

        self.gate.state.verified_backup = bool(result["verified"])
        self.gate.state.backup_path = str(path)

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
        if self.diag.identity:
            # The live session is the authority on what is on the bench;
            # keep the gate's picture of it current.
            hardware = str(self.diag.identity.fields.get("Hardware", "")).strip()
            if hardware:
                self.gate.state.ecu_hardware = hardware
        image_hardware = None
        image_embedded = None
        if image is not None:
            image_hardware = str((image.identity or {}).get("Hardware", "")).strip()
            image_embedded = extract_hardware_strings(image.data)
        decision = self.gate.evaluate(
            f"write:{region_name}", Risk.IRREVERSIBLE,
            profile=self.profile, capability="memory_write",
            image_hardware=image_hardware,
            image_embedded_hardware=image_embedded,
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
        """Erase, transfer, program and verify. Every step can refuse.

        This will not run in the shipped configuration: the safety gate's
        ``programming-enabled`` check is false unless the build explicitly
        enables it, and no catalog entry declares ``memory_write``.
        """
        self._progress_fn = progress
        memory = self.profile.memory or {}
        region = self.region(region_name)

        # 1. policy
        if not memory.get("write_supported"):
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

        checkpoint = self._checkpoint_path(region_name)
        self._write_checkpoint(
            checkpoint,
            {"phase": "starting", "region": region_name,
             "image_sha256": image.sha256,
             "backup": self.gate.state.backup_path,
             "identity": dict(self.diag.identity.fields) if self.diag.identity else {}},
        )

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
            }
            session.write_guard = self.gate.session_guard(armed)
            try:
                self._pre_write_records()
                self._erase(region)
                self._write_checkpoint(checkpoint, {"phase": "erased"})
                self._transfer(image, region)
                self._write_checkpoint(checkpoint, {"phase": "transferred"})
                self._finalise(image, region)
            finally:
                session.write_guard = self.gate.session_guard()

            # 4. verify by reading it back
            self._emit("verify", 0, region.size, "reading back")
            readback = self.read_region(region_name, progress=progress)
            if not readback.matches(image):
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
                {"region": region_name, "sha256": image.sha256, "verified": True},
            )
            return {
                "ok": True, "region": region_name, "verified": True,
                "sha256": image.sha256, "bytes": image.size,
            }

        except VerificationFailed as exc:
            # The phase is already recorded and is more specific than "failed".
            self._write_checkpoint(checkpoint, {"error": str(exc)})
            self.log.error("write", str(exc))
            raise
        except Exception as exc:
            self._write_checkpoint(checkpoint, {"phase": "failed", "error": str(exc)})
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
            session.request([Service.WRITE_DATA_BY_LOCAL_ID, *did, *value])
            self.diag._touch()

    def _erase(self, region: Region) -> None:
        session = self.diag._require()
        self._emit("erase", 0, 1, "erasing")
        erase = self.spec.get("write", {}).get("erase")
        if isinstance(erase, dict) and "start" in erase:
            # The documented IAW sequence: a routine call arms the erase and
            # a routine-results request is what actually runs it.
            session.request(list(erase["start"]))
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

    def _transfer(self, image: FirmwareImage, region: Region) -> None:
        session = self.diag._require()
        write_spec = self.spec.get("write", {})
        download = write_spec.get("request_download")
        if download:
            session.request(list(download))
            self.diag._touch()

        payload = self._upload_payload(image)
        block = write_spec.get("chunk", write_spec.get("block", region.block))
        subfn = write_spec.get("block_subfn")
        sent = 0
        address = region.start
        while sent < len(payload):
            chunk = payload[sent : sent + block]
            if subfn is None:
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

    def _finalise(self, image: FirmwareImage, region: Region) -> None:
        session = self.diag._require()
        self._emit("program", 0, 1, "programming")
        # Transfer exit is a required state transition, not a capability
        # probe.  Swallowing a negative response here could make us run the
        # erase/program routine against an incomplete download.
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
                checksum = iaw5am_upload_checksum(image.data)
                payload += [checksum >> 8, checksum & 0xFF]
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
            "starting": ["Nothing was written. It is safe to retry."],
            "erased": [
                "The region was erased but not written. The ECU will not run.",
                "Retry the write with the same image, or restore the backup.",
            ],
            "transferred": [
                "Data was transferred but the programming step did not confirm.",
                "Retry the write; the ECU should accept a repeat transfer.",
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
