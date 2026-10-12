# Optional build resources

Files dropped here are picked up by the Windows installer, and nothing else
reads this directory.

## `MicrosoftEdgeWebView2Setup.exe`

Windows 10 (1809+) and Windows 11 ship the Microsoft Edge WebView2 runtime,
which is what the app's window uses. A machine can still be missing it (a
stripped LTSC image, or Windows Server), and in that case the window cannot be
created — the app then runs the workstation in the user's browser and says so
in `%USERPROFILE%\.guzzionboard\logs\desktop.log`.

If this bootstrapper is present when the installer is compiled, the installer
offers to run it silently on machines where the runtime is missing. It is not
committed to the repository (it is a third-party binary that Microsoft updates
on its own schedule); the release workflow downloads it before building:

    curl -L -o packaging/resources/MicrosoftEdgeWebView2Setup.exe \
      https://go.microsoft.com/fwlink/p/?LinkId=2124703

The installer compiles fine without it — the `[Files]` entry is marked
`skipifsourcedoesntexist`, and the installer simply explains where to get the
runtime if it is needed.
