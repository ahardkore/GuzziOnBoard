; GuzziOnBoard — Windows installer (Inno Setup 6).
;
; Built by packaging/build.py or by .github/workflows/desktop-build.yml:
;
;     ISCC.exe /DAppVersion=0.4.0 /DAppDir=dist\GuzziOnBoard ^
;              /DOutputDir=dist /DSourceRoot=. packaging\installer\guzzionboard.iss
;
; Design decisions worth stating:
;
; * Per-user install by default. A garage laptop should not need an
;   administrator prompt to run a diagnostic tool; {autopf} resolves to the
;   per-user programs folder unless the user is already elevated.
; * The app's own data (session logs, backups, base maps, XDF additions) lives
;   in %USERPROFILE%\.guzzionboard and is NOT removed by the uninstaller.
;   Those files are evidence and backups; an uninstaller that eats backups is
;   a bug, so the uninstaller says where they are instead.
; * WebView2: Windows 10/11 ship it. If the machine somehow lacks it, the
;   installer runs Microsoft's bootstrapper when the build shipped one
;   (see packaging/README.md), and the app itself falls back to the browser
;   and says so in its log if a window cannot be created.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppDir
  #error Pass /DAppDir=<packaged application folder>
#endif
#ifndef AppIcon
  #define AppIcon ""
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif
#ifndef SourceRoot
  #define SourceRoot "."
#endif

#define AppName "GuzziOnBoard"
#define AppPublisher "GuzziOnBoard"
#define AppURL "https://github.com/ahardkore/GuzziOnBoard"
#define AppExe "GuzziOnBoard.exe"

[Setup]
AppId={{8F2B41E7-5C6D-4A93-9E10-2D7B8C4F1A66}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
LicenseFile={#SourceRoot}\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=GuzziOnBoard-{#AppVersion}-setup
SetupIconFile={#AppIcon}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Windows 10 1809 or newer: that is where WebView2 and the modern Python
; runtime floor are, and PyInstaller builds below it are untested.
MinVersion=10.0.17763
; x64 builds. Written with the 6.0-compatible identifier so older Inno
; Setup releases can still compile this; on ARM64 Windows the app runs
; under emulation.
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=no
DisableWelcomePage=no
ChangesAssociations=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The packaged application folder, exactly as PyInstaller produced it.
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; WebView2 bootstrapper, when the build shipped one (optional; see [Code]).
; Copied into {tmp} only when the runtime is missing, run from [Code] below
; and removed again when Setup finishes. skipifsourcedoesntexist is what makes
; the bootstrapper optional: builds that did not download it still compile.
Source: "{#SourceRoot}\packaging\resources\MicrosoftEdgeWebView2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall skipifsourcedoesntexist; Check: WebView2Needed

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\packaging\icons\guzzionboard.ico"; Comment: "Diagnostic workstation for Moto Guzzi motorcycles"
Name: "{group}\{#AppName} (browser mode)"; Filename: "{app}\{#AppExe}"; Parameters: "--browser"; Comment: "Open the workstation in your usual browser instead of a window"
Name: "{group}\{#AppName} self-test"; Filename: "{app}\{#AppExe}"; Parameters: "--selftest"; Comment: "Check that this installation is complete"
Name: "{group}\Exports and session logs"; Filename: "{app}\{#AppExe}"; Parameters: "--open-data"; Comment: "Open the folder holding exports and recorded sessions"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon; IconFilename: "{app}\packaging\icons\guzzionboard.ico"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppExe}"; Parameters: "--selftest"; Description: "Verify the installation now (writes a report to your data folder)"; Flags: nowait postinstall skipifsilent unchecked

[Code]
const
  WebView2Client = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function WebView2Installed(): Boolean;
var
  value: String;
begin
  Result :=
    RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2Client, 'pv', value) and (value <> '') or
    RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2Client, 'pv', value) and (value <> '') or
    RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2Client, 'pv', value) and (value <> '');
end;

function WebView2Needed(): Boolean;
begin
  Result := not WebView2Installed();
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  code: Integer;
begin
  if (CurStep = ssPostInstall) and WebView2Needed() then
  begin
    if FileExists(ExpandConstant('{tmp}\MicrosoftEdgeWebView2Setup.exe')) then
    begin
      if Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebView2Setup.exe'), '/silent /install', '',
              SW_SHOW, ewWaitUntilTerminated, code) then
        Log(Format('WebView2 bootstrapper exit code %d', [code]))
      else
        Log('WebView2 bootstrapper could not be started');
    end
    else
    begin
      Log('WebView2 runtime not detected and no bootstrapper was shipped');
      MsgBox('GuzziOnBoard could not find the Microsoft WebView2 runtime, which it uses for '
           + 'its window. Windows often installs it with a later update; until then the app '
           + 'will run in your browser instead (the installer also created a "browser mode" '
           + 'shortcut). You can install the runtime from '
           + 'https://developer.microsoft.com/microsoft-edge/webview2/', mbInformation, MB_OK);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    MsgBox('Your session logs, ECU backups and base maps were kept in:' + #13#10#13#10
         + ExpandConstant('{%USERPROFILE}\.guzzionboard') + #13#10#13#10
         + 'They are not part of the installation and were left alone. Delete that folder '
         + 'yourself if you want them gone.', mbInformation, MB_OK);
end;
