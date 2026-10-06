"""Isolated worker for user-supplied calibration-checksum plugins.

This file is launched with ``python -I -S -B`` by :mod:`guzzionboard.checksums`.
It intentionally uses only the standard library and communicates as one JSON
request/response. It is process/resource containment, not a claim of a perfect
OS security sandbox.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import sysconfig


def _limits() -> None:
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    except (ImportError, OSError, ValueError):
        pass


def _install_audit_guard(plugin: Path) -> None:
    roots = {plugin.resolve()}
    for key in ("stdlib", "platstdlib"):
        value = sysconfig.get_path(key)
        if value:
            roots.add(Path(value).resolve())

    def readable(path_value) -> bool:
        if isinstance(path_value, int):
            return True
        try:
            path = Path(os.fspath(path_value)).resolve()
        except (TypeError, ValueError, OSError):
            return False
        return any(path == root or root in path.parents for root in roots)

    denied_prefixes = (
        "socket.", "subprocess.", "ctypes.", "multiprocessing.",
    )
    denied_events = {
        "os.system", "os.posix_spawn", "os.posix_spawnp", "os.spawn",
        "os.fork", "os.forkpty", "os.kill", "os.putenv", "os.unsetenv",
        "os.chdir", "os.chroot", "os.remove", "os.rmdir", "os.rename",
        "os.replace", "os.mkdir", "os.link", "os.symlink", "os.truncate",
        "os.chmod", "os.chown", "shutil.copyfile", "shutil.copymode",
    }

    def guard(event, args):
        if event.startswith(denied_prefixes) or event in denied_events:
            raise PermissionError(f"checksum plugin isolation denied {event}")
        if event == "open":
            path = args[0] if args else None
            mode = args[1] if len(args) > 1 else "r"
            flags = args[2] if len(args) > 2 else 0
            writing = (isinstance(mode, str) and any(char in mode for char in "wax+"))
            if isinstance(flags, int):
                writing = writing or bool(flags & (
                    getattr(os, "O_WRONLY", 1) | getattr(os, "O_RDWR", 2)
                    | getattr(os, "O_CREAT", 64) | getattr(os, "O_TRUNC", 512)
                    | getattr(os, "O_APPEND", 1024)
                ))
            if writing or not readable(path):
                raise PermissionError("checksum plugin isolation denied file access")

    sys.addaudithook(guard)


def _load(plugin: Path):
    spec = importlib.util.spec_from_file_location(
        f"guzzionboard_checksum_worker_{plugin.stem}", plugin
    )
    if spec is None or spec.loader is None:
        raise ValueError("cannot construct plugin import")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _describe(module) -> dict:
    supported = getattr(module, "SUPPORTED_CHECKSUMS", ())
    supported = [str(value) for value in supported] if isinstance(supported, (tuple, list)) else None
    return {
        "provider_id": str(getattr(module, "PROVIDER_ID", "")),
        "name": str(getattr(module, "NAME", "")),
        "version": str(getattr(module, "VERSION", "")),
        "supported_checksums": supported,
        "verified": bool(getattr(module, "VERIFIED", False)),
        "note": str(getattr(module, "NOTE", "")),
        "has_update": callable(getattr(module, "update", None)),
        "has_verify": callable(getattr(module, "verify", None)),
    }


def main() -> int:
    result_fd = os.dup(1)
    null_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        request = json.loads(sys.stdin.read())
        plugin = Path(str(request["plugin"])).resolve(strict=True)
        _limits()
        _install_audit_guard(plugin)
        # Plugin prints never enter the protocol stream.
        os.dup2(null_fd, 1)
        os.dup2(null_fd, 2)
        module = _load(plugin)
        operation = request.get("operation")
        if operation == "describe":
            response = {"ok": True, "metadata": _describe(module)}
        elif operation == "apply":
            update = getattr(module, "update", None)
            verify = getattr(module, "verify", None)
            if not callable(update) or not callable(verify):
                raise ValueError("callable update() and verify() are required")
            image = base64.b64decode(request["image"], validate=True)
            context = request.get("context")
            if not isinstance(context, dict):
                raise ValueError("context must be an object")
            output = update(image, context)
            if not isinstance(output, bytes):
                raise TypeError("update() must return bytes")
            verified = verify(output, context)
            response = {
                "ok": True,
                "image": base64.b64encode(output).decode("ascii"),
                "verified": verified is True,
            }
        else:
            raise ValueError("unknown worker operation")
    except BaseException as exc:  # worker boundary; report without traceback leakage
        response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        os.dup2(result_fd, 1)
        os.close(result_fd)
        os.close(null_fd)
    encoded = json.dumps(response, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 16 * 1024 * 1024:
        encoded = b'{"ok":false,"error":"worker response exceeded 16 MiB"}'
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
