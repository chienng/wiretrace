#!/bin/bash
# Builds ~/Applications/Wiretrace.app, which starts a session of this Wiretrace folder without
# Terminal. Called by setup-mac.sh; safe to run again. Writes only that app and a temporary
# folder next to it. The app is made here rather than downloaded, so it has no quarantine flag
# and Gatekeeper does not check it (docs/specs/014-mac-app-install-and-launcher.md). Its icon is
# app/Wiretrace.icns, built from app/icon.svg by scripts/build-icon.sh.
#
# Never call git, python3, xcrun, cc or make here (see setup-mac.sh). osacompile, plutil and
# codesign are part of macOS.
set -euo pipefail

# Recognises our own app. A later signed app keeps it.
BUNDLE_ID="com.safemeet.wiretrace"

if [ "$(id -u)" -eq 0 ]; then
    echo "Do not run this with sudo." >&2
    exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPS="$HOME/Applications"
DEST="$APPS/Wiretrace.app"
SHOWN="~/Applications/Wiretrace.app"

not_created() {
    echo "WARN: Wiretrace app not created ($*)" >&2
    exit 1
}

bundle_id() {
    plutil -extract CFBundleIdentifier raw -o - "$1/Contents/Info.plist" 2>/dev/null || true
}

if [ -e "$DEST" ] || [ -L "$DEST" ]; then
    have="$(bundle_id "$DEST")"
    if [ "$have" != "$BUNDLE_ID" ]; then
        echo "WARN: $SHOWN is not Wiretrace's (bundle identifier: ${have:-none}); left as it is." >&2
        exit 1
    fi
fi

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$ROOT/cli/__init__.py")"
[ -n "$VERSION" ] || not_created "no __version__ in cli/__init__.py"

mkdir -p "$APPS"
tmp="$(mktemp -d "$APPS/.Wiretrace.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
app="$tmp/Wiretrace.app"
plist="$app/Contents/Info.plist"

run() {
    if ! "$@" >"$tmp/out" 2>&1; then
        not_created "$1 failed: $(tail -n 1 "$tmp/out")"
    fi
}

run osacompile -o "$app" "$ROOT/app/Wiretrace.applescript"
printf '%s\n' "$ROOT" > "$app/Contents/Resources/wiretrace-root"
# The bytes only, not a copy: a downloaded folder's quarantine flag must not come along.
cat "$ROOT/app/Wiretrace.icns" > "$app/Contents/Resources/applet.icns" || not_created "app/Wiretrace.icns unreadable"
# Without CFBundleIconName, macOS shows CFBundleIconFile (applet.icns), not the default
# script icon in Assets.car.
run plutil -remove CFBundleIconName "$plist"
run plutil -replace CFBundleIdentifier -string "$BUNDLE_ID" "$plist"
run plutil -replace CFBundleName -string Wiretrace "$plist"
run plutil -replace CFBundleShortVersionString -string "$VERSION" "$plist"
# Editing Info.plist breaks the signature osacompile made; Apple silicon does not run an app
# with a broken one. Ad-hoc: a Developer ID would replace "-" here.
run codesign --force --deep -s - "$app"

old=""
if [ -d "$DEST" ]; then
    old="$(head -n 1 "$DEST/Contents/Resources/wiretrace-root" 2>/dev/null || true)"
fi
rm -rf "$DEST"
mv "$app" "$DEST"

if [ -n "$old" ] && [ "$old" != "$ROOT" ]; then
    echo "Wiretrace.app now opens $ROOT (it opened $old)"
else
    echo "created: $SHOWN"
fi
