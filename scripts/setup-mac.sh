#!/bin/bash
# Sets up Wiretrace for a standard (non-admin) macOS user. Writes only under $HOME
# and this folder; see docs/install-without-admin.md. Safe to run again.
#
# Never call git, python3, xcrun, cc or make here: without the Xcode Command
# Line Tools they are stubs that open an install dialog.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/setup-mac.sh [--skip-android]

Installs uv, Python 3.12 and the Wiretrace Python packages (into .venv), plus
Android platform-tools (into ~/tools) unless --skip-android is given, and
creates ~/Applications/Wiretrace.app. Needs no admin rights. Ends by running
./wiretrace doctor.
EOF
}

skip_android=0
for arg in "$@"; do
    case "$arg" in
        --skip-android) skip_android=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
    esac
done

if [ "$(id -u)" -eq 0 ]; then
    echo "Do not run this with sudo: files in your home folder would end up owned by root." >&2
    echo "Run it as yourself: scripts/setup-mac.sh" >&2
    exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UV_BIN="$HOME/.local/bin"
PLATFORM_TOOLS="$HOME/tools/platform-tools"
ZSHRC="$HOME/.zshrc"

# Pinned downloads. To upgrade, change the version and the SHA-256 together, after
# checking the new file against the vendor's published checksum.
UV_VERSION="0.13.0"
UV_SHA256_X86_64="5f44dcbde809b632f47c36fadb241cb4d6f9af71d0c8f172b5d2026d3dde742c"
UV_SHA256_ARM64="a9c1b29002cf3c83f07fa9cd8a887a3be0107d90e23189721221e7257db8e3d6"
PLATFORM_TOOLS_VERSION="37.0.1"
PLATFORM_TOOLS_SHA256="ee39ad5967e95c2a07f04dbcbde96b1a0c916ba376096db5d2f498b7727a5d1d"

host_cpu() {
    # A Terminal running under Rosetta reports x86_64. Its Intel builds would run
    # translated and get the Intel cryptography pin (overrides.txt).
    if [ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" = "1" ]; then
        echo arm64
    else
        uname -m
    fi
}

cpu="$(host_cpu)"
case "$cpu" in
    x86_64) uv_target="x86_64-apple-darwin"; uv_sha256="$UV_SHA256_X86_64"; python_arch="x86_64" ;;
    arm64) uv_target="aarch64-apple-darwin"; uv_sha256="$UV_SHA256_ARM64"; python_arch="aarch64" ;;
    *) echo "Unsupported CPU: $cpu" >&2; exit 1 ;;
esac
PYTHON_REQUEST="cpython-3.12-macos-$python_arch-none"

tmp="$(mktemp -d "$ROOT/.download.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

step() { printf '\n==> %s\n' "$*"; }

download_verified() {
    local url="$1" sha256="$2" dest="$3"
    curl -fL --progress-bar -o "$dest" "$url"
    if ! echo "$sha256  $dest" | shasum -a 256 -c - >/dev/null 2>&1; then
        echo "Checksum mismatch for $url; nothing was installed from it." >&2
        exit 1
    fi
}

add_path_line() {
    # $1 is written literally, e.g. '$HOME/.local/bin'.
    local line="export PATH=\"$1:\$PATH\""
    if [ -f "$ZSHRC" ] && grep -qxF "$line" "$ZSHRC"; then
        echo "already in ~/.zshrc: $line"
        return
    fi
    if [ -s "$ZSHRC" ] && [ -n "$(tail -c1 "$ZSHRC")" ]; then
        echo >> "$ZSHRC"
    fi
    printf '%s\n' "$line" >> "$ZSHRC"
    echo "added to ~/.zshrc: $line"
}

step "uv $UV_VERSION"
UV="$UV_BIN/uv"
uv_have="$("$UV" --version 2>/dev/null | awk '{print $2}')" || true
if [ "$uv_have" = "$UV_VERSION" ]; then
    echo "already installed: $UV"
else
    if [ -n "$uv_have" ]; then
        echo "replacing uv $uv_have in $UV_BIN with the pinned $UV_VERSION"
    fi
    download_verified \
        "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$uv_target.tar.gz" \
        "$uv_sha256" "$tmp/uv.tar.gz"
    tar -xzf "$tmp/uv.tar.gz" -C "$tmp"
    mkdir -p "$UV_BIN"
    cp "$tmp/uv-$uv_target/uv" "$tmp/uv-$uv_target/uvx" "$UV_BIN/"
    echo "installed: $UV"
fi
export PATH="$UV_BIN:$PATH"

step "Python 3.12"
"$UV" python install "$PYTHON_REQUEST"

step "Python packages (.venv)"
cd "$ROOT"
if [ -x .venv/bin/python ]; then
    # A .venv copied from another Mac, or made under Rosetta, can be for the other CPU.
    venv_cpu="$(.venv/bin/python -c 'import platform; print(platform.machine())' 2>/dev/null)" || venv_cpu=""
    if [ "$venv_cpu" != "$cpu" ]; then
        echo "replacing .venv: it was made for ${venv_cpu:-another CPU}, this Mac is $cpu"
        rm -rf .venv
    fi
fi
if [ ! -x .venv/bin/python ]; then
    "$UV" venv --python "$PYTHON_REQUEST" .venv
fi
# Wheels only: building from source needs a compiler, i.e. the Command Line Tools.
# Bytecode up front, so the first doctor / mitmweb start is not slowed by it.
"$UV" pip install --python .venv/bin/python --only-binary :all: --compile-bytecode \
    --overrides overrides.txt -r requirements.txt

if [ "$skip_android" -eq 1 ]; then
    step "Android platform-tools: skipped (--skip-android)"
elif [ -x "$PLATFORM_TOOLS/adb" ] && \
     [ "$(sed -n 's/^Pkg.Revision=//p' "$PLATFORM_TOOLS/source.properties" 2>/dev/null)" = "$PLATFORM_TOOLS_VERSION" ]; then
    step "Android platform-tools $PLATFORM_TOOLS_VERSION"
    echo "already installed: $PLATFORM_TOOLS"
else
    step "Android platform-tools $PLATFORM_TOOLS_VERSION"
    download_verified \
        "https://dl.google.com/android/repository/platform-tools_r$PLATFORM_TOOLS_VERSION-darwin.zip" \
        "$PLATFORM_TOOLS_SHA256" "$tmp/platform-tools.zip"
    mkdir -p "$HOME/tools"
    rm -rf "$PLATFORM_TOOLS"
    unzip -q "$tmp/platform-tools.zip" -d "$HOME/tools"
    echo "installed: $PLATFORM_TOOLS"
fi

step "PATH"
add_path_line '$HOME/.local/bin'
if [ -x "$PLATFORM_TOOLS/adb" ]; then
    add_path_line '$HOME/tools/platform-tools'
    export PATH="$PLATFORM_TOOLS:$PATH"
fi
case "${SHELL:-}" in
    */zsh) ;;
    *) echo "Your shell is ${SHELL:-unknown}, not zsh: add the lines above to its startup file yourself." ;;
esac

step "First start of the iOS tools (can take a minute)"
# The first start after install takes ~20 s on Intel (mostly waiting, not CPU),
# longer than doctor's per-check timeout.
"$ROOT/.venv/bin/pymobiledevice3" usbmux list >/dev/null 2>&1 || true
echo "done"

step "Wiretrace app (~/Applications)"
# Not needed to use Wiretrace from Terminal: a failure is a warning, and doctor still decides.
app_made=0
if "$ROOT/scripts/make-app.sh"; then
    app_made=1
fi

step "Checking the setup (./wiretrace doctor)"
set +e
"$ROOT/wiretrace" doctor
status=$?
set -e

echo
echo "Open a new Terminal window (or run: exec zsh) so the PATH changes apply."
if [ "$app_made" -eq 1 ]; then
    echo "Next time, open Wiretrace from Launchpad or Spotlight; no Terminal needed."
    echo "To keep it in the Dock: right-click its Dock icon > Options > Keep in Dock."
fi
exit "$status"
