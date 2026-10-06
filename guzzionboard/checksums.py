"""Explicit, process-isolated calibration-checksum plugin interface.

No ECU calibration checksum algorithm is bundled here. A provider is selected
by id (never guessed), must name every XDF checksum it supports, must update and
verify deterministically, and is fingerprinted into the tuning plan.

Local ``~/.guzzionboard/checksums/*.py`` plugins execute in a fresh interpreter
with an isolated environment, resource limits, a timeout, and an audit hook that
blocks network, subprocess, mutation, and file access outside the plugin and
standard library. This materially contains mistakes and ordinary malicious
behavior; it is not claimed to be a kernel-grade sandbox.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Callable

PLUGIN_DIR = Path.home() / ".guzzionboard" / "checksums"
WORKER = Path(__file__).with_name("checksum_worker.py")
WORKER_TIMEOUT_SECONDS = 4
MAX_WORKER_RESPONSE = 16 * 1024 * 1024


class ChecksumUnavailable(ValueError):
    """A requested checksum provider is absent, incompatible, or invalid."""


def _run_worker(path: Path, request: dict) -> dict:
    payload = {"plugin": str(path.resolve()), **request}
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 16 * 1024 * 1024:
        raise ChecksumUnavailable("checksum worker request exceeds 16 MiB")
    environment = {
        "HOME": "",
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "PATH": os.defpath,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="guzzionboard-checksum-") as work:
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-B", str(WORKER)],
                input=encoded,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=work,
                env=environment,
                timeout=WORKER_TIMEOUT_SECONDS,
                check=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise ChecksumUnavailable(
            f"checksum plugin exceeded {WORKER_TIMEOUT_SECONDS} second isolation timeout"
        ) from exc
    except OSError as exc:
        raise ChecksumUnavailable(f"cannot start isolated checksum worker: {exc}") from exc
    if len(result.stdout) > MAX_WORKER_RESPONSE:
        raise ChecksumUnavailable("checksum worker response exceeds 16 MiB")
    try:
        response = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        detail = result.stderr.decode("utf-8", "replace")[:300]
        raise ChecksumUnavailable(
            f"isolated checksum worker returned invalid output"
            + (f": {detail}" if detail else "")
        ) from exc
    if result.returncode != 0 or not response.get("ok"):
        raise ChecksumUnavailable(
            f"isolated checksum plugin failed: {response.get('error') or 'unknown worker error'}"
        )
    return response


@dataclass(frozen=True)
class ChecksumProvider:
    provider_id: str
    name: str
    version: str
    supported_checksums: tuple[str, ...]
    update_fn: Callable[[bytes, dict], bytes] | None = None
    verify_fn: Callable[[bytes, dict], bool] | None = None
    verified: bool = False
    note: str = ""
    source: str = ""
    plugin_sha256: str = ""
    plugin_path: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.provider_id,
            "name": self.name,
            "version": self.version,
            "supported_checksums": list(self.supported_checksums),
            "verified": self.verified,
            "note": self.note,
            "source": self.source,
            "plugin_sha256": self.plugin_sha256,
            "isolation": (
                "fresh-python-process+resource-limits+audit-guard"
                if self.plugin_path else "in-process-provider"
            ),
            "isolation_timeout_seconds": (
                WORKER_TIMEOUT_SECONDS if self.plugin_path else None
            ),
        }

    def supports(self, declared: list[str]) -> bool:
        return bool(declared) and all(name in self.supported_checksums for name in declared)

    def _isolated_apply(self, original: bytes, context: dict) -> tuple[bytes, bytes]:
        path = Path(self.plugin_path)
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ChecksumUnavailable(f"cannot re-read checksum plugin {path}: {exc}") from exc
        if digest != self.plugin_sha256:
            raise ChecksumUnavailable(
                "checksum plugin SHA-256 changed after selection; reload and review it"
            )
        request = {
            "operation": "apply",
            "image": base64.b64encode(original).decode("ascii"),
            "context": context,
        }
        first_response = _run_worker(path, request)
        second_response = _run_worker(path, request)
        if first_response.get("verified") is not True or second_response.get("verified") is not True:
            raise ChecksumUnavailable(
                f"checksum provider {self.provider_id!r} did not verify its output"
            )
        try:
            first = base64.b64decode(first_response["image"], validate=True)
            second = base64.b64decode(second_response["image"], validate=True)
        except (KeyError, ValueError) as exc:
            raise ChecksumUnavailable("isolated checksum worker returned invalid image bytes") from exc
        return first, second

    def _inline_apply(self, original: bytes, context: dict) -> tuple[bytes, bytes]:
        if not callable(self.update_fn) or not callable(self.verify_fn):
            raise ChecksumUnavailable("checksum provider has no callable update/verify implementation")
        try:
            first = self.update_fn(original, dict(context))
            second = self.update_fn(original, dict(context))
        except Exception as exc:
            raise ChecksumUnavailable(
                f"checksum provider {self.provider_id!r} failed: {exc}"
            ) from exc
        if not isinstance(first, bytes) or not isinstance(second, bytes):
            raise ChecksumUnavailable("checksum provider update() must return bytes")
        try:
            verified = self.verify_fn(first, dict(context))
        except Exception as exc:
            raise ChecksumUnavailable(
                f"checksum provider {self.provider_id!r} verification failed: {exc}"
            ) from exc
        if verified is not True:
            raise ChecksumUnavailable(
                f"checksum provider {self.provider_id!r} did not verify its output"
            )
        return first, second

    def apply(self, image: bytes, context: dict) -> tuple[bytes, dict]:
        original = bytes(image)
        first, second = (
            self._isolated_apply(original, dict(context))
            if self.plugin_path else self._inline_apply(original, dict(context))
        )
        if not isinstance(first, bytes) or not isinstance(second, bytes):
            raise ChecksumUnavailable("checksum provider update() must return bytes")
        if len(first) != len(original):
            raise ChecksumUnavailable(
                "checksum provider changed the image length; calibration checksum updates must be in-place"
            )
        if first != second:
            raise ChecksumUnavailable(
                "checksum provider is not deterministic across fresh isolated processes"
            )
        changed = [index for index, (before, after) in enumerate(zip(original, first))
                   if before != after]
        if len(changed) > 4096:
            raise ChecksumUnavailable(
                "checksum provider changed more than 4096 bytes; refusing an unbounded plugin write"
            )
        ranges = []
        if changed:
            start = previous = changed[0]
            for index in changed[1:] + [None]:
                if index is not None and index == previous + 1:
                    previous = index
                    continue
                end = previous + 1
                ranges.append({
                    "offset": f"0x{start:X}",
                    "length": end - start,
                    "before_hex": original[start:end].hex(),
                    "after_hex": first[start:end].hex(),
                })
                if index is not None:
                    start = previous = index
        return first, {
            **self.as_dict(),
            "input_sha256": hashlib.sha256(original).hexdigest(),
            "output_sha256": hashlib.sha256(first).hexdigest(),
            "changed_bytes": len(changed),
            "byte_changes": ranges,
            "provider_verified_claim": self.verified,
            "status": (
                "isolated-plugin-verified-output-not-core-endorsed"
                if self.plugin_path else "in-process-provider-verified-output-not-core-endorsed"
            ),
        }


def _provider_from_file(path: Path) -> ChecksumProvider:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    response = _run_worker(path, {"operation": "describe"})
    metadata = response.get("metadata")
    if not isinstance(metadata, dict):
        raise ChecksumUnavailable(f"{path}: isolated worker returned no metadata")
    provider_id = str(metadata.get("provider_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,79}", provider_id):
        raise ChecksumUnavailable(f"{path}: PROVIDER_ID is missing or invalid")
    if not metadata.get("has_update") or not metadata.get("has_verify"):
        raise ChecksumUnavailable(f"{path}: callable update() and verify() are required")
    supported = metadata.get("supported_checksums")
    if (not isinstance(supported, list) or not supported
            or any(not isinstance(value, str) or not value.strip() for value in supported)):
        raise ChecksumUnavailable(f"{path}: SUPPORTED_CHECKSUMS must list exact XDF titles")
    return ChecksumProvider(
        provider_id=provider_id,
        name=str(metadata.get("name") or provider_id).strip() or provider_id,
        version=str(metadata.get("version") or "").strip() or "unspecified",
        supported_checksums=tuple(value.strip() for value in supported),
        verified=bool(metadata.get("verified")),
        note=str(metadata.get("note") or "").strip(),
        source=str(path),
        plugin_sha256=digest,
        plugin_path=str(path.resolve()),
    )


def load_providers(directory: str | Path = PLUGIN_DIR) -> tuple[list[ChecksumProvider], list[dict]]:
    """Inspect every plugin in an isolated worker; never import one in-process."""
    root = Path(directory).expanduser()
    if not root.exists():
        return [], []
    providers, errors = [], []
    ids: set[str] = set()
    for path in sorted(root.glob("*.py")):
        try:
            provider = _provider_from_file(path)
            if provider.provider_id in ids:
                raise ChecksumUnavailable(
                    f"duplicate checksum provider id {provider.provider_id!r}"
                )
            ids.add(provider.provider_id)
            providers.append(provider)
        except (OSError, ChecksumUnavailable) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return providers, errors


def provider_by_id(provider_id: str, directory: str | Path = PLUGIN_DIR) -> ChecksumProvider:
    providers, errors = load_providers(directory)
    matches = [provider for provider in providers if provider.provider_id == provider_id]
    if len(matches) == 1:
        return matches[0]
    detail = f"; {len(errors)} plugin(s) failed to load" if errors else ""
    raise ChecksumUnavailable(
        f"no checksum provider with id {provider_id!r} in {Path(directory).expanduser()}{detail}"
    )
