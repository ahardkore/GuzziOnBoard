# The desktop application

GuzziOnBoard is a program you install and launch, not a page you remember to
start a server for:

* **Windows** — `GuzziOnBoard-<version>-setup.exe` installs it per-user (no
  administrator prompt), creates Start-menu and optional desktop shortcuts,
  registers an uninstaller, and writes nothing outside its own folders. A
  portable `.zip` is published alongside it for a USB stick or a locked-down
  machine: unzip, run `GuzziOnBoard.exe`.
* **macOS** — `GuzziOnBoard.app` in a zip. Drag it to Applications.
* **Linux** — a folder build with `install.sh` (installs a menu entry and a
  `~/.local/bin/guzzionboard` symlink, no root), plus a portable archive.

Once running it is the whole workstation in one window: the Garage, live data,
fault codes, guided tests, service actions, ECU memory, maps, sessions,
reports and the workshop tools. Nothing about the diagnostics changed to make
this work — the window is the same UI, talking to the same loopback API, with
the same safety gate behind it.

> **Status: the packaging is tested, the window is not yet.** Everything below
> is exercised by the test suite (`tests/test_desktop.py`,
> `tests/test_packaging.py`) and by the self-test that CI runs against each
> built artifact — against the *simulator*, and against a Python-level stand-in
> for a frozen build. CI also launches the installed application on a runner
> and expects a window (or an explained fallback). Nobody has yet installed
> this on a Windows machine next to a motorcycle. When you do,
> `GuzziOnBoard.exe --selftest` is the first thing to run.

---

## Using it

Double-click the icon. That is the whole procedure: the app picks a free
loopback port, starts the workstation on it, opens the window on that address,
and stops the server when the window closes.

| In the app | What happens |
|---|---|
| **Exports** (left sidebar: *Open exports*) | Opens the folder holding everything you saved: reports, CSV logs, built images, printable views |
| *Quit* (sidebar or the window close button) | Stops the server, disconnects the ECU and releases actuator outputs on the way out |
| A second launch | Raises the window that is already open instead of starting a second workstation |
| Closing mid-job | Refuses once and says which operation is running; closing again really exits |

Files land in your **Downloads** folder by default; `--export-dir` puts them
somewhere else. An existing file is never overwritten — a second export of the
same name becomes `report-1.txt`, because these files are evidence.

Everything else is [the workstation you already
know](../README.md): simulator mode by default, no serial port opened until you
ask, the safety gate unchanged.

### Command line

```text
guzzionboard-desktop                     the window (this is what the shortcuts run)
guzzionboard-desktop --browser           the system browser instead of a window
guzzionboard-desktop --no-window         server only: scripts, CI, a headless box
guzzionboard-desktop --selftest          verify this installation and exit
guzzionboard-desktop --export-dir D      where saved files go
guzzionboard-desktop --data-dir D        a self-contained data root (USB stick)
guzzionboard-desktop --open-data         open the exports/sessions folder and exit
guzzionboard-desktop --port 8000         a fixed port instead of a free one
guzzionboard-desktop --gui gtk           force a pywebview renderer
guzzionboard-desktop --debug             webview developer tools
```

`guzzionboard --desktop` and `guzzionboard --selftest` exist too, so the
browser entry point can hand over to the shell when you want it.

### What the window does that the browser did not

Three things, and they are all about being the *host* of the page rather than
a tab in someone else's browser:

1. **Saving a file.** Webviews are unreliable about `a.download` on a blob
   URL, so exports go through the host: `/api/desktop/save` writes the file
   into your export folder, refuses to overwrite, and the UI says where it
   went. The file name is sanitised on the way in (no directory part, no
   Windows-reserved names, length capped) — a name from a page is untrusted
   input even when the page is ours.
2. **Printing.** `window.print()` is not implemented usefully by WebView2,
   WKWebView or WebKitGTK. *Print view* instead writes a standalone snapshot
   of the current view — stylesheet inlined, every `<canvas>` frozen to a PNG
   — into your export folder and opens it in your real browser, where Ctrl+P
   works properly. The snapshot survives as a file either way.
3. **Being well-behaved.** One instance, one port, an orderly shutdown that
   disconnects the ECU and releases actuator outputs, and a refusal to vanish
   in the middle of a flash read.

## How it is put together

```text
DesktopApp (guzzionboard/desktop.py)
  ├── ThreadingHTTPServer on 127.0.0.1:<free port>
  │     └── make_handler(workstation, guard=RequestGuard(token), desktop=bridge)
  │           └── Workstation            the same object the browser version uses
  ├── pywebview window ──> http://127.0.0.1:<port>/
  │     └── web/index.html + app.js + desktop-bridge.js (injected by the server)
  ├── ExportDesk                         where saved files land
  └── InstanceDirectory                  the single-instance record
```

* **The window is optional at every level.** No pywebview, a platform with no
  webview engine, `--browser`, or a window that fails to start: the server
  still runs and the page opens in the system browser, and the reason is
  printed (and written to the log). The app is still the app.
* **The bridge is injected, not written into the page.** `web/app.js` and
  `web/index.html` are the same files the hosted demo serves. When this
  process serves the page it adds one script tag and a `data-desktop="1"`
  attribute; `web/desktop-bridge.js` then installs the session token on every
  API call and re-routes downloads and printing. In a browser tab none of that
  exists and the UI uses ordinary browser behaviour.
* **Nothing ECU-facing lives in the shell.** `desktop.py` cannot open a serial
  port. Every control action still goes through the safety gate, the capability
  catalog and the frame guard, in the same process, over the same routes.

### Why loopback, and what stops another page

The API can energise an ignition coil and erase flash memory, so who can reach
it matters. Three checks run on every request, in `RequestGuard`:

| Check | Refuses |
|---|---|
| `Host` names loopback (`127.0.0.1`, `localhost`, `::1`) | DNS rebinding: a name an attacker controls resolving to your machine |
| `Origin`, when the browser sends one, is this same workstation | Any page on any other site — this is the one that matters, because a browser attaches `Origin` to every cross-origin request it makes |
| The per-launch token, on every `/api/` call | A process on the same machine that guessed the port, and the *hosted* demo page when it is open locally |

The token is generated per launch with `secrets.token_urlsafe(32)`, handed to
the window inside the generated `desktop-bridge.js` (never in a URL, so it
never reaches the address bar, the history or a referrer header), and written
to `~/.guzzionboard/desktop-instance.json` with mode `0600` so the next launch
can recognise this one. `guzzionboard --selftest` asserts all of this against a
running server: no token → 403, wrong token → 403, foreign origin → 403,
non-loopback `Host` → 403.

`python -m guzzionboard` (the browser server) gets the same origin and host
checks. It does not need a token: you asked for it, you opened the tab, and it
answers only the origin it serves.

### One instance, honestly

A record file is not proof that a process exists, so it is not treated as
proof. `InstanceDirectory` believes a record only after the recorded port
answers `/api/desktop/ping` with the recorded token and identifies itself as
this app; otherwise the record is deleted and the launch continues. A crashed
app can therefore never lock you out of the next launch, and `--new-instance`
skips the question entirely.

### Where things live

| Path | What |
|---|---|
| `<install folder>` | The program: two executables (`GuzziOnBoard.exe`, `GuzziOnBoard-worker.exe`) and `_internal/`, which holds `web/`, `guzzionboard/catalog`, `guzzionboard/xdfs`, `vendor/` |
| `~/.guzzionboard/sessions/` | Recorded sessions (raw frames + decoded samples) |
| `~/.guzzionboard/images/`, `basemaps/` | ECU reads and the protected base maps |
| `~/.guzzionboard/xdfs/`, `checksums/`, `keys/` | Your additions: XDFs, checksum plugins, key providers |
| `~/.guzzionboard/logs/desktop.log` | Window/shell log — a windowed build has no console, so this is where a startup failure is explained |
| `~/.guzzionboard/desktop-instance.json` | The running instance (pid, port, token) |
| Your Downloads folder | Everything you save from the UI |

`--data-dir D` (or `GUZZIONBOARD_HOME=D`) moves the whole per-user half of that
table under `D`, which makes a portable install on a USB stick genuinely
self-contained.

## Building it

```bash
pip install -e '.[desktop,build]'
python packaging/build.py                 # application folder in dist/
python packaging/build.py --installer     # ... and the Windows installer
python packaging/build.py --portable-zip  # ... and a portable archive
python packaging/build.py --skip-selftest # trust me (don't)
```

The build refuses to finish unless the artifact passes its own `--selftest`,
which is the check that catches a data file that never made it into the bundle
— `PyInstaller` will happily produce an executable that starts and then has no
XDF library. On macOS it runs that check twice: once on the folder and once on
`GuzziOnBoard.app/Contents/MacOS/GuzziOnBoard`, because a `.app` is a different
arrangement of the same files and only running it proves the arrangement works.

| Piece | Purpose |
|---|---|
| `packaging/guzzionboard.spec` | PyInstaller recipe: one folder, two executables |
| `packaging/entry_app.py` | The frozen entry point |
| `packaging/build.py` | Build, wrap per platform, verify, checksum |
| `packaging/installer/guzzionboard.iss` | The Windows installer (Inno Setup 6) |
| `packaging/installer/windows-install-check.ps1` | Installs the setup on a machine, runs the installed app, uninstalls it, checks the user's data survived — the Windows job runs it |
| `packaging/installer/linux-install-check.sh` | Runs `install.sh` on a machine, then checks the launcher, the menu entry, the icon and the installed app's self-test — the Linux job runs it |
| `packaging/make_icons.py` | Regenerates the icon set from `icons/source.png` |
| `.github/workflows/desktop-build.yml` | Builds (and on a `v*` tag, releases) all three platforms |
| `playwright.desktop.config.mjs` + `tests/browser/desktop-host.spec.mjs` | The UI in a real Chromium, talking to a real `guzzionboard-desktop --no-window`: the injected bridge, the token on every call, saves landing in the export folder, printing as a snapshot. `npm run test:browser:desktop` |


**Two executables, one folder.** `GuzziOnBoard.exe` is windowed (no console
window) and carries the application. `GuzziOnBoard-worker.exe` is a small
*console* binary built straight from `guzzionboard/checksum_worker.py`, which
is stdlib-only: it exists because a windowed process has no console to run the
isolated checksum-plugin worker in, and because that worker must stay cheap to
start (it has a 4-second timeout). From a source checkout the worker is just
`sys.executable`, so the two paths are tested as one (`tests/test_desktop.py`).

**`_internal/` is deliberate, not sloppiness.** PyInstaller 6 hides the data
next to the executable by default, and this build keeps that default: on macOS
— a case-insensitive filesystem — a flat folder would put the executable
`GuzziOnBoard` and the data directory `guzzionboard` in the same directory,
which is one name, and the build fails with `NotADirectoryError`. The app
resolves its files from `sys._MEIPASS` (`guzzionboard/resources.py`), which
points at `_internal/`, so the layout is invisible from the inside. The macOS
`.app` is unaffected either way: `BUNDLE` rearranges it into `Contents/`.

One folder rather than one file: a one-file build unpacks the whole ~30 MB
bundle into a temporary directory on every launch, and the app starts a
subprocess. A folder install is one directory, and the uninstaller removes it.

### What the workflow proves, on the platform it is proving it

The three platform jobs are not "does it compile" jobs. Each one runs
`packaging/build.py`, which builds the frozen application, checks the files it
must contain, and then **runs the artifact's own `--selftest`** on the machine
that built it. A build whose app cannot find its XDF library fails the job
rather than the user.

| Job | Artifact | Checked by |
|---|---|---|
| Windows | `GuzziOnBoard-<version>-setup.exe` (Inno Setup) and a portable `.zip` | The frozen folder app runs `--selftest`; the installer is compiled from that same folder |
| Linux | `GuzziOnBoard-<version>-linux-<arch>-portable.zip` (+ `install.sh`, `.desktop`) | The frozen folder app runs `--selftest` |
| macOS | `GuzziOnBoard-<version>-macos-<arch>.zip` (the `.app`) and a portable `.zip` | Both the folder app *and* `GuzziOnBoard.app/Contents/MacOS/GuzziOnBoard` run `--selftest` — a `.app` is a different arrangement of the same files |
| All three | `SHA256SUMS-<platform>.txt` and the transcript | `if-no-files-found: error`: an artifact-less build goes red |
| Windows, again | `windows-install-report` (install log + transcript + `windowed-desktop.log`) | A separate job **installs the setup silently**, checks the payload and the Start-menu shortcut, runs the installed application's `--selftest`, **starts the installed application** and talks to it (the UI answers, and its own token-checked `/api/desktop/ping` does), then **launches it windowed, the way a double-click does, and demands a window** — or an explained fallback, never a silent death (`packaging/installer/windows-install-check.ps1`), then **uninstalls it** and checks `%USERPROFILE%\.guzzionboard` came through untouched |
| Linux, again | `dist/linux-install-selftest.log` | The same script the README tells you to run is run for real, then its launcher is executed through the symlink the script installed — `--selftest`, and then for real, answering HTTP and its own ping (`packaging/installer/linux-install-check.sh`) |

### Publishing, and republishing

A `v*` tag publishes: the three release jobs attach the installer and the
archives, each platform's `SHA256SUMS-*.txt`, and the transcript of the
self-test that artifact passed, to that tag's release. They do it under their
own `permissions: contents: write`, while the rest of the workflow stays
`contents: read` — a tag that builds and self-tests three platforms is still
not a release until something is allowed to write one.

A tag build that fails at that last step is republished **without moving the
tag**: dispatch the workflow from any branch that carries the fix, and name the
tag it should publish.

```bash
gh workflow run desktop-build.yml --ref <branch-with-the-fix> -f release=true -f tag=v0.4.0
```

The run checks `v0.4.0` out, builds that tree on all three platforms, runs every
artifact's own self-test again, and attaches the results to the release of the
tag that already exists. Nothing is re-tagged, and nothing is published from a
branch that is not the tag.

### Windows

Inno Setup 6 compiles `packaging/installer/guzzionboard.iss`. The installer is
per-user by default (`PrivilegesRequired=lowest`), needs Windows 10 1809 or
newer, refuses to run on 32-bit Windows, and will use Microsoft's WebView2
bootstrapper if the runtime is missing *and* the build shipped one — see
[`packaging/resources/README.md`](../packaging/resources/README.md). If it
didn't, the app still runs: it opens in your browser and says why.

### Linux

`dist/GuzziOnBoard/` contains the app plus `install.sh` and
`guzzionboard.desktop.in`; `install.sh` copies a `.desktop` entry and an icon
into `~/.local/share` and links `~/.local/bin/guzzionboard` — the check in
`packaging/installer/linux-install-check.sh` runs that script and then starts
what it installed, through the symlink.

**The Linux artifact carries no window engine, so it opens your browser.** The
window needs pywebview *and* PyGObject with the WebKitGTK typelibs, and
freezing those into a folder build is its own piece of work — PyInstaller
collects Gtk but has no WebKit2 typelib hook, so a half-done bundle would fail
at the moment the window is created. What the artifact does instead is honest
and tested: it serves the same workstation and opens it in your usual browser,
which is the same code path the app takes anywhere else the window cannot
start. From a *source* install (`pip install -e '.[desktop]'` on a machine
with `python3-gi` and `gir1.2-webkit2-4.1`), the window is used.

### macOS

PyInstaller's `BUNDLE` produces `GuzziOnBoard.app`; `ditto` archives it so the
framework links inside survive. The bundle is unsigned and unnotarised, so
Gatekeeper will want a right-click → *Open* the first time. Signing needs an
Apple Developer certificate, which this project does not have.

## Troubleshooting

**"The installer worked, but nothing opened."** That was 0.4.0's bug, and it
is worth understanding. The window is created by pywebview on its own GUI
thread; a failure there kills the process with no error, no dialog and no
log line — the log simply ends at `mode: window`. (0.4.0's specific cause:
the window was handed the `.png` icon on Windows, whose backend loads it
with `System.Drawing.Icon` — an `.ico`-only API — so the GUI thread died
before a window existed, with exit code `0xE0434352`. The launch now checks
everything checkable first, and a .NET-side hook prints any exception that
still manages to die on that thread.) The launch now defends against the
whole class in two places:

* *Before* the window starts, everything checkable is checked on the main
  thread: the WebView2 runtime's presence and version (Windows), and the
  window engine itself. A failure there is an ordinary, explained error and
  the workstation opens in your browser instead, with the reason in
  `~/.guzzionboard/logs/desktop.log`.
* If the window is created but never appears within 25 seconds, a watchdog
  opens the workstation in your browser and says so in the log.

If you see *neither*, the process died before Python could say anything, and
the crash record is in Windows' Event Viewer (Windows Logs → Application,
Event ID 1000, "Application Error" — the *faulting module* line names the
culprit). That is the one file a bug report wants.

**"The window did not appear."** The shell prints why and opens the workstation
in your browser instead. The reason is also in `~/.guzzionboard/logs/desktop.log`.
On Windows this usually means the WebView2 runtime is missing; on Linux, that
GTK/WebKitGTK is not installed.

**"Windows protected your PC."** SmartScreen, because the build is unsigned.
*More info* → *Run anyway*. A code-signing certificate is the only real fix,
and it costs money.

**"It is already running" but no window is visible.** The earlier copy is
running in browser mode or its window is behind something; the message prints
the URL. If you believe it is wrong, delete
`~/.guzzionboard/desktop-instance.json` — the next launch cannot be locked out
by a stale record anyway.

**"Saved x.txt" but where?** The sidebar shows the export folder and *Open
exports* opens it. In the browser version, files go wherever your browser puts
downloads; that difference is the point.

**The port.** Normally the OS picks a free one. `--port 8000` fixes it, which
is useful when you want the page on another device on the same network
(`--host 0.0.0.0`); the origin check still refuses requests from other web
origins, and only loopback names are accepted unless you bind a LAN address
explicitly.

**Starting over.** Uninstalling removes the program. Your session logs,
backups and base maps are deliberately left in `~/.guzzionboard` (the
uninstaller says so); delete that folder yourself if you want them gone.

## What is not true yet

* **No hardware has been validated**, window or browser — the transports and
  the whole safety model are still waiting for a bench confirmation. See
  `docs/PHYSICAL_VALIDATION.md`.
* **The installer has not been run on a Windows machine by a human.** CI now
  installs it silently on a clean runner, starts the installed application,
  talks to it, uninstalls it, and checks that `~/.guzzionboard` was left alone
  — but a robot clicking *Next* is not a person reading the pages, and that is
  why the self-test shortcut exists. Nothing has verified the wizard's
  appearance, the license page, or what happens on a machine with an older
  Windows.
* **macOS and Linux get archives, not installers.** There is no `.dmg`, no
  `.deb`, no Flatpak. The Linux `install.sh` is a per-user script, not a
  package manager.
* **The Linux build has no window engine** (above): it serves the workstation
  and opens your browser. The native window on Linux works from a source
  install with PyGObject + WebKitGTK; bundling them for a frozen build is not
  done yet.
* **No auto-update.** New versions are downloaded from the releases page and
  installed over the old one; the installer keeps the same `AppId`, so it is an
  upgrade rather than a second copy.
