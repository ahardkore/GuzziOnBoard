<#
.SYNOPSIS
Install the built setup, launch the application it installed, uninstall it,
and check that the user's own files survived.

.DESCRIPTION
This is the Windows half of "it is a desktop application": the installer is
what a person actually runs, so something has to run it. On a clean machine
this script

  1. installs dist\GuzziOnBoard-*-setup.exe silently,
  2. finds where it went (from the registry, not from a guess),
  3. checks the installed copy is complete - the worker, the icons, the web
     UI, the catalog, the XDF library,
  4. checks a Start-menu shortcut exists, because not needing to know where
     the .exe lives is the point of an installer,
  5. runs the *installed* application's own --selftest,
  6. checks the application wrote its state to %USERPROFILE%\.guzzionboard,
  7. uninstalls it, and
  8. checks the application and its shortcuts are gone and that
     %USERPROFILE%\.guzzionboard is untouched.

It is deliberately not part of packaging/build.py: that runs on the build
machine, and this one installs things.

.PARAMETER Dist
Directory holding the setup, relative to the current directory. Default: dist.

.PARAMETER InstallTimeoutSeconds
A silent installer that never returns is worse than one that fails, and much
harder to read afterwards: it looks like the job is busy. How long to give it
before stopping it and saying so. Default: 300.

.PARAMETER StartupTimeoutSeconds
How long to wait for the application to write down what it is doing and start
serving. Default: 60.

.PARAMETER UninstallTimeoutSeconds
Inno's uninstaller relaunches itself from a temporary copy, so waiting for the
process is not the same as waiting for the work. How long to keep looking.
Default: 90.

.EXAMPLE
pwsh -File packaging/installer/windows-install-check.ps1
#>
[CmdletBinding()]
param(
    [string] $Dist = 'dist',
    [int] $InstallTimeoutSeconds = 300,
    [int] $StartupTimeoutSeconds = 60,
    [int] $UninstallTimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'

function Show-Log {
    param([string] $Path, [int] $Tail = 30)
    if (Test-Path $Path) { Get-Content $Path -Tail $Tail | Write-Host }
}

function LogTail {
    <# The last thing a log said, on one line, for a check annotation: a hang
       is only diagnosable if the reason travels with the complaint. #>
    param([string] $Path, [int] $Tail = 10)
    if (-not (Test-Path $Path)) { return '(no log)' }
    return (((Get-Content $Path -Tail $Tail) -join ' | ') -replace '\s+', ' ')
}

function Fail {
    param([string] $Title, [string] $Message)
    # A check annotation, not just a line in a log: this is the part of CI
    # nobody can reproduce on a laptop, so the reason has to be visible from
    # the pull request.
    Write-Host "::error title=$Title::$Message"
    exit 1
}

function Find-UninstallEntry {
    <# The installer registers itself; this is what Windows itself would show
       in "Add or remove programs". #>
    $roots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    foreach ($root in $roots) {
        Get-ChildItem $root -ErrorAction SilentlyContinue | ForEach-Object {
            $entry = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
            if ($entry.DisplayName -like 'GuzziOnBoard*') { $entry }
        }
    }
}

# ------------------------------------------------------------------ install

$setup = Get-ChildItem (Join-Path $Dist 'GuzziOnBoard-*-setup.exe') -ErrorAction SilentlyContinue |
         Select-Object -First 1
if (-not $setup) { Fail 'No installer to test' "$Dist has no GuzziOnBoard-*-setup.exe" }

$installLog = Join-Path $env:RUNNER_TEMP 'install.log'
Write-Host "installing $($setup.Name) - $([math]::Round($setup.Length / 1MB, 1)) MB, silently"
$setupRun = Start-Process -FilePath $setup.FullName -PassThru -ArgumentList @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$installLog"
)
if (-not $setupRun.WaitForExit($InstallTimeoutSeconds * 1000)) {
    Stop-Process -Id $setupRun.Id -Force -ErrorAction SilentlyContinue
    Show-Log $installLog 60
    Fail 'The installer did not finish' "still running after $InstallTimeoutSeconds seconds. Last log lines: $(LogTail $installLog 12)"
}
if ($setupRun.ExitCode -ne 0) {
    Show-Log $installLog 40
    Fail 'The installer failed' "exit code $($setupRun.ExitCode); the install log is in the artifacts"
}
Show-Log $installLog 5

$entry = Find-UninstallEntry | Select-Object -First 1
if (-not $entry) {
    Fail 'The installer registered nothing' 'no uninstall entry named GuzziOnBoard was created'
}

$candidates = @(
    $entry.InstallLocation
    (Join-Path $env:LOCALAPPDATA 'Programs\GuzziOnBoard')
    (Join-Path $env:ProgramFiles 'GuzziOnBoard')
) | Where-Object { $_ } | Where-Object { Test-Path (Join-Path $_ 'GuzziOnBoard.exe') }
$dir = $candidates | Select-Object -First 1
if (-not $dir) {
    Fail 'The installer installed no application' "no GuzziOnBoard.exe found for $($entry.DisplayName)"
}
$app = Join-Path $dir 'GuzziOnBoard.exe'
$menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\GuzziOnBoard'
$data = Join-Path $env:USERPROFILE '.guzzionboard'
Write-Host "installed $($entry.DisplayName) $($entry.DisplayVersion) into $dir"

# --------------------------------------------------------- the payload

# The app resolves web/, the catalog and the XDF library relative to itself
# (guzzionboard/resources.py), from wherever it was installed.
$root = if (Test-Path (Join-Path $dir '_internal')) { Join-Path $dir '_internal' } else { $dir }
foreach ($relative in @('web\index.html',
                        'web\desktop-bridge.js',
                        'guzzionboard\catalog\ecus\5am.json',
                        'guzzionboard\xdfs\catalog.json',
                        'packaging\icons\guzzionboard.ico')) {
    if (-not (Test-Path (Join-Path $root $relative))) {
        Fail 'The installed application is incomplete' "$relative is missing from $root"
    }
}
if (-not (Test-Path (Join-Path $dir 'GuzziOnBoard-worker.exe'))) {
    Fail 'The installed application is incomplete' "GuzziOnBoard-worker.exe is missing from $dir"
}

$shortcuts = @(Get-ChildItem $menu -Filter *.lnk -ErrorAction SilentlyContinue)
if (-not ($shortcuts.Name -contains 'GuzziOnBoard.lnk')) {
    Fail 'No Start-menu shortcut' "expected GuzziOnBoard.lnk in $menu"
}
Write-Host "Start menu: $($shortcuts.Name -join ', ')"

# ------------------------------------------------------- the installed app

$transcript = Join-Path $env:RUNNER_TEMP 'installed-selftest.log'
$env:GOB_SELFTEST_LOG = $transcript
Write-Host "running $app --selftest"
$selftest = Start-Process -FilePath $app -Wait -PassThru -ArgumentList '--selftest'
$report = if (Test-Path $transcript) { Get-Content $transcript -Raw } else { '(no transcript)' }
Write-Host $report
if ($selftest.ExitCode -ne 0) {
    Fail 'The installed application failed its self-test' `
         "exit code $($selftest.ExitCode); the transcript is in the artifacts"
}
if ($report -notmatch 'All \d+ checks passed') {
    Fail 'The installed application reported a problem' `
         'the transcript does not say all checks passed'
}

# --selftest verifies the installation in a temporary directory on purpose:
# it must not write anything into someone's data folder just to check itself.
# So the launch - and the proof that the thing installed is a program, not a
# pile of files - comes from starting it and talking to it.
$instanceFile = Join-Path $data 'desktop-instance.json'
Remove-Item $instanceFile -ErrorAction SilentlyContinue
Write-Host "starting $app --no-window"
$running = Start-Process -FilePath $app -PassThru -ArgumentList '--no-window'
try {
    $log = Join-Path $data 'logs\desktop.log'
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    while (-not (Test-Path $instanceFile) -and (Get-Date) -lt $deadline -and -not $running.HasExited) {
        Start-Sleep -Milliseconds 500
    }
    if ($running.HasExited) {
        Show-Log $log 40
        Fail 'The application exited instead of running' "exit code $($running.ExitCode); see $log"
    }
    if (-not (Test-Path $instanceFile)) {
        Show-Log $log 40
        Fail 'The application recorded nothing' "$instanceFile did not appear within $StartupTimeoutSeconds seconds. Last log lines: $(LogTail $log)"
    }
    Write-Host "it recorded itself as pid $($instance.pid) on port $($instance.port)"

    # The record it wrote about itself: the same one a second launch uses to
    # find the window that is already open.
    $instance = Get-Content $instanceFile -Raw | ConvertFrom-Json
    if (-not $instance.port -or -not $instance.token) {
        Fail 'The instance record is unusable' (Get-Content $instanceFile -Raw)
    }
    if ($instance.version -ne $entry.DisplayVersion) {
        Fail 'The running application is a different version' "it reported $($instance.version), the installer says $($entry.DisplayVersion)"
    }
    $url = "http://127.0.0.1:$($instance.port)/"
    Write-Host "it is serving $url"

    try {
        $page = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 30
    } catch {
        Show-Log $log 40
        Fail 'The application did not serve its UI' "$url could not be fetched: $($_.Exception.Message)"
    }
    if ($page.StatusCode -ne 200) { Fail 'The application did not serve its UI' "$url answered HTTP $($page.StatusCode)" }
    if ($page.Content -notmatch 'GuzziOnBoard') { Fail 'The served page is not the workstation UI' "$url answered 200 but nothing in it names the application" }

    # Its own authenticated ping - the check a second copy of the app makes
    # before it decides an instance is really running.
    try {
        $ping = Invoke-RestMethod -Uri "$url/api/desktop/ping" -TimeoutSec 30 `
                                  -Headers @{ 'X-GuzziOnBoard-Token' = $instance.token }
    } catch {
        Show-Log $log 40
        Fail 'The application did not answer its own ping' "$url/api/desktop/ping: $($_.Exception.Message)"
    }
    if (-not $ping.ok -or $ping.app -ne 'GuzziOnBoard' -or -not $ping.desktop) {
        Fail 'The application did not answer its own ping' "got: $($ping | ConvertTo-Json -Compress)"
    }
    Write-Host "answered its own ping as $($ping.app) $($ping.version), desktop=$($ping.desktop)"
} finally {
    if (-not $running.HasExited) {
        Stop-Process -Id $running.Id -Force -ErrorAction SilentlyContinue
        $running.WaitForExit(15000) | Out-Null
    }
}
if (-not $running.HasExited) { Fail 'The application would not stop' "pid $($running.Id) is still running" }

if (-not (Test-Path $data)) {
    Fail 'The application wrote no user data' "$data does not exist after running"
}
$kept = @(Get-ChildItem $data -Recurse -File).Count
if ($kept -eq 0) { Fail 'The application wrote no user data' "$data is empty" }
Write-Host "$data holds $kept file(s) after running the application"

# ------------------------------------------------------------- the window
#
# --selftest and --no-window prove everything except the one thing a
# double-click actually gets: a window on a desktop. The window is created
# by pywebview on a private GUI thread, and a failure there is a silent
# process death - no exception, no log line, nothing on screen - which is
# exactly how 0.4.0 shipped to the first real user. This phase launches the
# installed application the way a person does and holds it to one of two
# honest outcomes: a window appears, or the app says why not and stays up
# serving. A silent death is the only unacceptable result.

Remove-Item $instanceFile -ErrorAction SilentlyContinue
$windowLog = Join-Path $data 'logs\desktop.log'
Remove-Item $windowLog -ErrorAction SilentlyContinue
Write-Host "starting $app (windowed, the way a double-click launches it)"
$gui = Start-Process -FilePath $app -PassThru
$windowHandle = [IntPtr]::Zero
try {
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline -and -not $gui.HasExited) {
        $gui.Refresh()
        if ($gui.MainWindowHandle -ne 0) { $windowHandle = $gui.MainWindowHandle; break }
        Start-Sleep -Milliseconds 500
    }
    if ($gui.HasExited) {
        Show-Log $windowLog 60
        Fail 'The windowed application died' `
             "exit code $($gui.ExitCode) instead of showing a window. This is the 0.4.0 failure: the GUI thread died and took the process with it. Last log lines: $(LogTail $windowLog 14)"
    }
    if ($windowHandle -ne [IntPtr]::Zero) {
        Write-Host "a window appeared (handle $windowHandle)"
    } else {
        # No window - only acceptable if the application *said so* and is
        # still alive to serve the workstation in its browser fallback.
        $explained = (Test-Path $windowLog) -and (
            (Get-Content $windowLog -Raw) -match 'could not start|did not appear|WebView2'
        )
        if (-not $explained) {
            Show-Log $windowLog 60
            Fail 'The window never appeared and never said why' `
                 "no window handle within 90 seconds and no fallback message in the log. Last log lines: $(LogTail $windowLog 14)"
        }
        Write-Host "::warning title=No window on this runner::the application fell back to the browser and explained itself; this runner may have no interactive desktop for a window"
    }

    # Whatever is on screen, the workstation behind it must be the real one:
    # the record it wrote plus its own authenticated ping, the same evidence
    # a second launch would demand.
    if (-not (Test-Path $instanceFile)) {
        Show-Log $windowLog 40
        Fail 'The windowed application recorded nothing' "$instanceFile did not appear"
    }
    $instance = Get-Content $instanceFile -Raw | ConvertFrom-Json
    $windowUrl = "http://127.0.0.1:$($instance.port)/"
    try {
        $ping = Invoke-RestMethod -Uri "$windowUrl/api/desktop/ping" -TimeoutSec 30 `
                                  -Headers @{ 'X-GuzziOnBoard-Token' = $instance.token }
    } catch {
        Show-Log $windowLog 40
        Fail 'The windowed application did not answer its own ping' "$windowUrl/api/desktop/ping: $($_.Exception.Message)"
    }
    if (-not $ping.ok -or $ping.app -ne 'GuzziOnBoard') {
        Fail 'The windowed application did not answer its own ping' "got: $($ping | ConvertTo-Json -Compress)"
    }
    Write-Host "behind the window it is serving $windowUrl and answering its own ping"

    # Close it the way a person would and expect an orderly exit.
    if ($windowHandle -ne [IntPtr]::Zero) {
        [void]$gui.CloseMainWindow()
        if (-not $gui.WaitForExit(30000)) {
            Show-Log $windowLog 40
            Fail 'The window would not close' "CloseMainWindow was ignored for 30 seconds"
        }
        Write-Host 'the window closed and the process left with it'
    }
} finally {
    Copy-Item $windowLog (Join-Path $env:RUNNER_TEMP 'windowed-desktop.log') -ErrorAction SilentlyContinue
    if (-not $gui.HasExited) {
        Stop-Process -Id $gui.Id -Force -ErrorAction SilentlyContinue
        $gui.WaitForExit(15000) | Out-Null
    }
}

# -------------------------------------------------------------- uninstall

$uninstaller = Get-ChildItem $dir -Filter 'unins*.exe' | Select-Object -First 1
if (-not $uninstaller) { Fail 'No uninstaller was installed' "expected unins*.exe in $dir" }
Write-Host "uninstalling with $($uninstaller.Name)"
$uninstalling = Start-Process -FilePath $uninstaller.FullName -PassThru -ArgumentList @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
)
if (-not $uninstalling.WaitForExit($UninstallTimeoutSeconds * 1000)) {
    Stop-Process -Id $uninstalling.Id -Force -ErrorAction SilentlyContinue
    Fail 'The uninstaller did not finish' "still running after $UninstallTimeoutSeconds seconds"
}
$deadline = (Get-Date).AddSeconds($UninstallTimeoutSeconds)
while ((Test-Path $app) -and ((Get-Date) -lt $deadline)) { Start-Sleep -Seconds 2 }
if (Test-Path $app) {
    Fail 'The uninstaller left the application behind' "$app still exists after $UninstallTimeoutSeconds seconds"
}
if (Test-Path $menu) {
    $left = @(Get-ChildItem $menu -ErrorAction SilentlyContinue).Count
    if ($left -gt 0) {
        Fail 'The uninstaller left its shortcuts behind' "$menu still holds $left item(s)"
    }
}

# Session logs, ECU backups and base maps are evidence, and the uninstaller
# says where they are instead of deleting them.
if (-not (Test-Path $data)) {
    Fail 'The uninstaller removed the user data folder' `
         "$data is gone; session logs and backups are not the installer's to delete"
}
$survived = @(Get-ChildItem $data -Recurse -File).Count
if ($survived -eq 0) { Fail 'The uninstaller emptied the user data folder' "$data holds no files any more" }
Write-Host "$data still holds $survived file(s) after the uninstall"

# ---------------------------------------------------------------- summary

if ($env:GITHUB_STEP_SUMMARY) {
    @(
        '| Step | Result |'
        '|---|---|'
        "| Installed | ``$($entry.DisplayName) $($entry.DisplayVersion)`` into ``$dir`` |"
        "| Start menu | $($shortcuts.Count) shortcut(s) |"
        "| Installed application ``--selftest`` | passed, exit 0 |"
        "| Installed application launched | served ``$url``, answered its own ping |"
        "| User data written | $kept file(s) under ``$data`` |"
        "| Uninstaller | removed the application, kept those $survived file(s) |"
    ) -join "`n" | Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
}

Write-Host 'installed, launched, uninstalled, and the user data survived.'
