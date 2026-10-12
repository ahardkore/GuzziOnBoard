# Packaging

Everything needed to turn the checkout into something a person can install and
double-click. The full story is in [`docs/DESKTOP.md`](../docs/DESKTOP.md);
this is the map.

```text
packaging/
  guzzionboard.spec           PyInstaller recipe (one folder, two executables)
  entry_app.py                frozen entry point for the application
  build.py                    build → wrap → self-test → checksum
  make_icons.py               regenerate icons/ from icons/source.png
  icons/                      .ico (Windows), .icns (macOS), .png (Linux)
  installer/guzzionboard.iss  Inno Setup 6 script for the Windows installer
  resources/                  optional build inputs (WebView2 bootstrapper)
```

Quick start:

```bash
pip install -e '.[desktop,build]'
python packaging/build.py --portable-zip
./dist/GuzziOnBoard/GuzziOnBoard --selftest      # .exe on Windows
```

Two executables are produced on purpose: `GuzziOnBoard` (windowed, the
application) and `GuzziOnBoard-worker` (console, the isolated checksum-plugin
worker, built from `guzzionboard/checksum_worker.py`, which is stdlib-only).
The application looks for the worker next to itself; if it is missing, checksum
plugins are reported unavailable with that reason rather than run somewhere
weaker. See `guzzionboard/checksum_worker.py` and `guzzionboard/checksums.py`.

Nothing here is required to *run* the workstation: `python -m guzzionboard`
and `pip install -e '.[desktop]'` + `guzzionboard-desktop` both work from a
checkout. Packaging is how it becomes an installed program.
