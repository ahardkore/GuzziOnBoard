#!/bin/sh
# Install the folder build the way docs/DESKTOP.md tells a Linux user to, then
# check what that produced.
#
# This is the Linux side of "it is an installed desktop application". There is
# no .deb and no root: the installer is `install.sh` inside the packaged
# folder, and until it has actually been run on a clean machine nobody knows
# whether the launcher, the .desktop entry and the icon end up in the right
# places. CI runs this after every build.
#
#     packaging/installer/linux-install-check.sh dist/GuzziOnBoard
#
# Failures print a GitHub check annotation, because the interesting part of a
# failing CI job is the reason, and logs are not always where people look.
set -eu

folder="${1:-dist/GuzziOnBoard}"

fail() {
    printf '::error title=%s::%s\n' "$1" "$2" >&2
    exit 1
}

note() { printf '  %s\n' "$1"; }

[ -d "$folder" ] || fail 'No package to install' "$folder does not exist"
folder=$(cd "$folder" && pwd)

app="$folder/GuzziOnBoard"
[ -x "$app" ] || fail 'No application in the package' "$app is missing or not executable"
[ -x "$folder/install.sh" ] || fail 'No install.sh' "$folder/install.sh is missing or not executable"

prefix="$HOME/.local"
launcher="$prefix/bin/guzzionboard"
desktop="$prefix/share/applications/guzzionboard.desktop"
icon="$prefix/share/icons/hicolor/256x256/apps/guzzionboard.png"

rm -f "$launcher" "$desktop" "$icon"          # a stale one would hide a failure
printf 'installing %s for %s\n' "$folder" "$HOME"
"$folder/install.sh" >"${TMPDIR:-/tmp}/gob-install.log" 2>&1 || {
    cat "${TMPDIR:-/tmp}/gob-install.log" >&2
    fail 'install.sh failed' 'see the output above'
}
cat "${TMPDIR:-/tmp}/gob-install.log"

# ------------------------------------------------------- what it installed

[ -L "$launcher" ] || fail 'No launcher was installed' "$launcher is not a symlink"
[ "$(readlink -f "$launcher")" = "$app" ] || \
    fail 'The launcher points somewhere else' "$launcher -> $(readlink "$launcher"), expected $app"
note "launcher: $launcher -> $app"

[ -f "$desktop" ] || fail 'No .desktop entry was installed' "$desktop is missing"
grep -q "^Exec=$app$" "$desktop" || \
    fail 'The .desktop entry runs the wrong thing' "$(grep '^Exec=' "$desktop" | head -1), expected Exec=$app"
grep -q '^Terminal=false' "$desktop" || \
    fail 'The .desktop entry would open a terminal' 'Terminal=false is missing'
note "menu entry: $(grep '^Exec=' "$desktop")"

[ -f "$icon" ] || fail 'No icon was installed' "$icon is missing"
note "icon: $icon"

# --------------------------------------------------- the installed launcher

# Run the thing a user would click, through the symlink, and read the report it
# writes: a windowed-ish app with no console has nowhere else to put it.
transcript="$folder/../linux-install-selftest.log"
rm -f "$transcript"
GOB_SELFTEST_LOG="$transcript" "$launcher" --selftest >/dev/null 2>&1 || {
    [ -f "$transcript" ] && cat "$transcript" >&2
    fail 'The installed launcher failed its self-test' 'the transcript is in the artifacts'
}
cat "$transcript"
grep -q 'All [0-9]* checks passed' "$transcript" || \
    fail 'The installed launcher reported a problem' 'the transcript does not say all checks passed'

data="$HOME/.guzzionboard"
[ -d "$data" ] || fail 'The application wrote no user data' "$data does not exist"
note "$data was created by the application, as it should be"

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
        printf '| Step | Result |\n|---|---|\n'
        printf '| Installed | `%s` |\n' "$folder"
        printf '| Launcher | `%s` -> the application |\n' "$launcher"
        printf '| Menu entry | `%s` |\n' "$desktop"
        printf '| Icon | `%s` |\n' "$icon"
        printf '| Installed launcher `--selftest` | passed |\n'
    } >>"$GITHUB_STEP_SUMMARY"
fi

printf 'installed from install.sh and launched: ok\n'
