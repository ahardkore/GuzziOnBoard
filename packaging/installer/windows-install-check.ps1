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
    [int] $UninstallTimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'

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
$setupRun = Start-Process -FilePath $setup.FullName -Wait -PassThru -ArgumentList @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$installLog"
)
if ($setupRun.ExitCode -ne 0) {
    Get-Content $installLog -Tail 40 | Write-Host
    Fail 'The installer failed' "exit code $($setupRun.ExitCode); the install log is in the artifacts"
}

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

if (-not (Test-Path $data)) {
    Fail 'The application wrote no user data' "$data does not exist after running --selftest"
}
$kept = @(Get-ChildItem $data -Recurse -File).Count
if ($kept -eq 0) { Fail 'The application wrote no user data' "$data is empty" }
Write-Host "$data holds $kept file(s) after the self-test"

# -------------------------------------------------------------- uninstall

$uninstaller = Get-ChildItem $dir -Filter 'unins*.exe' | Select-Object -First 1
if (-not $uninstaller) { Fail 'No uninstaller was installed' "expected unins*.exe in $dir" }
Write-Host "uninstalling with $($uninstaller.Name)"
$null = Start-Process -FilePath $uninstaller.FullName -Wait -PassThru -ArgumentList @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
)
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
        "| User data written | $kept file(s) under ``$data`` |"
        "| Uninstaller | removed the application, kept those $survived file(s) |"
    ) -join "`n" | Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
}

Write-Host 'installed, launched, uninstalled, and the user data survived.'
