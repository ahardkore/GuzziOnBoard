"""Tests for workstation preferences, save/load location presets, and audit fixes."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

from guzzionboard import preferences, resources
from guzzionboard.desktop import DesktopApp, ExportDesk
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "gob-home"
    monkeypatch.setenv(resources.HOME_ENV, str(home))
    return home


def test_default_preferences_and_roundtrip(isolated_home, tmp_path):
    export_dir = tmp_path / "exports"
    prefs = preferences.load(default_export_dir=export_dir)
    assert prefs["schema"] == preferences.SCHEMA_VERSION
    assert prefs["theme"] == "dark"
    assert prefs["layout_density"] == "comfortable"
    assert prefs["temp_unit"] == "C"
    assert prefs["poll_interval_ms"] == 250
    assert prefs["confirm_before_exit"] is True
    assert prefs["active_save_preset"] == "exports"
    assert prefs["active_load_preset"] == "images"
    assert Path(prefs["active_save_dir"]) == export_dir.absolute()

    custom_save = tmp_path / "custom-saves"
    custom_load = tmp_path / "custom-loads"
    updated = preferences.update(
        {
            "theme": "light",
            "layout_density": "compact",
            "temp_unit": "F",
            "poll_interval_ms": 500,
            "confirm_before_exit": False,
            "default_session_mode": "hardware",
            "save_presets": [
                *prefs["save_presets"],
                {"id": "bench-out", "name": "Bench Output", "path": str(custom_save), "builtin": False},
            ],
            "active_save_preset": "bench-out",
            "load_presets": [
                *prefs["load_presets"],
                {"id": "bench-in", "name": "Bench Maps", "path": str(custom_load), "kind": "images", "builtin": False},
            ],
            "active_load_preset": "bench-in",
        },
        default_export_dir=export_dir,
    )
    assert updated["theme"] == "light"
    assert updated["layout_density"] == "compact"
    assert updated["temp_unit"] == "F"
    assert updated["poll_interval_ms"] == 500
    assert updated["confirm_before_exit"] is False
    assert updated["default_session_mode"] == "hardware"
    assert updated["active_save_preset"] == "bench-out"
    assert Path(updated["active_save_dir"]) == custom_save.absolute()
    assert updated["active_load_preset"] == "bench-in"
    assert Path(updated["active_load_dir"]) == custom_load.absolute()

    reloaded = preferences.load(default_export_dir=export_dir)
    assert reloaded["theme"] == "light"
    assert reloaded["active_save_preset"] == "bench-out"
    assert reloaded["active_load_preset"] == "bench-in"

    reset = preferences.reset(default_export_dir=export_dir)
    assert reset["theme"] == "dark"
    assert reset["active_save_preset"] == "exports"


@pytest.mark.parametrize(
    "bad_patch",
    [
        {"theme": "neon"},
        {"layout_density": "huge"},
        {"temp_unit": "K"},
        {"poll_interval_ms": 10},
        {"poll_interval_ms": 99999},
        {"poll_interval_ms": True},
        {"confirm_before_exit": "yes"},
        {"default_session_mode": "cloud"},
        {"save_presets": []},
        {"load_presets": []},
        {"save_presets": [{"id": "ok", "name": "Bad", "path": "bad\x00path"}]},
        {"active_save_preset": "does-not-exist"},
        {"active_load_preset": "does-not-exist"},
    ],
)
def test_preferences_validation_rejects_invalid_inputs(isolated_home, bad_patch):
    with pytest.raises(preferences.PreferencesError):
        preferences.update(bad_patch)


def test_browse_and_save_to_preset_with_collision_protection(isolated_home, tmp_path):
    save_dir = tmp_path / "preset-saves"
    load_dir = tmp_path / "preset-loads"
    load_dir.mkdir(parents=True)
    (load_dir / "v7_stock.bin").write_bytes(b"\x00" * 256)
    (load_dir / "custom.xdf").write_text("<XDFFORMAT/>", encoding="utf-8")
    (load_dir / "readme.md").write_text("ignored by images filter", encoding="utf-8")

    preferences.update(
        {
            "save_presets": [{"id": "out", "name": "Out", "path": str(save_dir)}],
            "active_save_preset": "out",
            "load_presets": [
                {"id": "imgs", "name": "Images", "path": str(load_dir), "kind": "images"},
                {"id": "allf", "name": "All Files", "path": str(load_dir), "kind": "any"},
            ],
            "active_load_preset": "imgs",
        }
    )

    browsed_imgs = preferences.browse_preset("load", "imgs")
    assert browsed_imgs["exists"] is True
    assert [f["name"] for f in browsed_imgs["files"]] == ["v7_stock.bin"]

    browsed_all = preferences.browse_preset("load", "allf")
    assert {f["name"] for f in browsed_all["files"]} == {"v7_stock.bin", "custom.xdf", "readme.md"}

    first = preferences.save_to_preset("../../service-report.txt", "line 1\n")
    second = preferences.save_to_preset("service-report.txt", "line 2\n")
    assert first["name"] == "service-report.txt"
    assert second["name"] == "service-report-1.txt"
    assert Path(first["path"]).read_text(encoding="utf-8") == "line 1\n"
    assert Path(second["path"]).read_text(encoding="utf-8") == "line 2\n"


def test_api_preferences_syncs_desktop_export_desk(isolated_home, tmp_path):
    initial_exports = tmp_path / "initial-exports"
    next_exports = tmp_path / "next-exports"
    ws = Workstation()
    desk = ExportDesk(initial_exports)

    class BridgeStub:
        def __init__(self):
            self.desk = desk
            self.updated_to: list[str] = []

        def set_export_dir(self, directory: str | Path) -> Path:
            self.updated_to.append(str(directory))
            return self.desk.set_directory(directory)

    bridge = BridgeStub()
    api = Api(ws, desktop=bridge)

    status, got = api.get_preferences({})
    assert status == 200
    assert Path(got["active_save_dir"]) == initial_exports.resolve()

    status, updated = api.post_preferences(
        {
            "save_presets": [
                {"id": "exports", "name": "Exports", "path": str(initial_exports)},
                {"id": "custom", "name": "Custom", "path": str(next_exports)},
            ],
            "active_save_preset": "custom",
        }
    )
    assert status == 200
    assert Path(updated["active_save_dir"]) == next_exports.absolute()
    assert desk.directory == next_exports.resolve()
    assert len(bridge.updated_to) == 1


def test_desktop_app_restores_stdio_and_closes_log_handle(isolated_home, tmp_path, monkeypatch):
    import sys as _sys

    orig_out, orig_err = _sys.stdout, _sys.stderr
    monkeypatch.setattr(_sys, "stdout", None)
    monkeypatch.setattr(_sys, "stderr", None)
    app = DesktopApp(export_dir=tmp_path / "exports", no_window=True)
    try:
        app._setup_logging()
        handle = app._log_handle
        assert handle is not None and not handle.closed
        assert _sys.stdout is app._tee_stdout
        assert _sys.stderr is app._tee_stderr
        app.shutdown()
        assert handle.closed
        assert _sys.stdout is None
        assert _sys.stderr is None
    finally:
        monkeypatch.setattr(_sys, "stdout", orig_out)
        monkeypatch.setattr(_sys, "stderr", orig_err)


def test_archive_app_invokes_zip_from_parent_directory(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("gob_pkg_build", ROOT / "packaging" / "build.py")
    assert spec and spec.loader
    pkg_build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pkg_build)

    app_bundle = tmp_path / "dist" / "GuzziOnBoard.app"
    app_bundle.mkdir(parents=True)
    calls: list[tuple[list[str], Path | None]] = []

    def fake_run(cmd, *, cwd=None):
        calls.append((list(cmd), cwd))
        return 0

    monkeypatch.setattr(pkg_build.shutil, "which", lambda _name: None)
    with patch.object(pkg_build, "run", side_effect=fake_run):
        out = pkg_build.archive_app(app_bundle, "0.4.1")

    assert len(calls) == 1
    cmd, cwd = calls[0]
    assert cwd == app_bundle.parent
    assert cmd[:4] == ["zip", "-q", "-r", "-y"]
    assert Path(cmd[4]) == out.resolve()
    assert cmd[5] == "GuzziOnBoard.app"
