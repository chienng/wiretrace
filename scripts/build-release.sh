#!/bin/bash
# Builds the QA release files from one git commit into dist/:
#   wiretrace-<version>-macos.tar.gz and wiretrace-<version>-macos.dmg, each with a .sha256.
#
# A developer tool: it needs git and hdiutil. setup-mac.sh, which runs on QA Macs,
# must not call git.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/build-release.sh [<commit>]

Builds dist/wiretrace-<version>-macos.tar.gz and .dmg from <commit> (default: HEAD).
Uncommitted changes are never included.
EOF
}

case "${1:-}" in
    -h|--help) usage; exit 0 ;;
esac
[ "$#" -le 1 ] || { usage >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
REF="${1:-HEAD}"
COMMIT="$(git rev-parse --short "$REF^{commit}")"
VERSION="$(git show "$COMMIT:cli/__init__.py" | sed -n 's/^__version__ = "\(.*\)"$/\1/p')"
if [ -z "$VERSION" ]; then
    echo "No __version__ in cli/__init__.py at $COMMIT" >&2
    exit 1
fi
if git cat-file -e "$COMMIT:addons/wiretrace_ui.py" 2>/dev/null && \
   ! git cat-file -e "$COMMIT:ui/dist/index.html" 2>/dev/null; then
    echo "ui/dist/ is not in $COMMIT, so --ui wiretrace would not work: run" >&2
    echo "npm --prefix ui run build and commit ui/dist/ first" >&2
    exit 1
fi
if [ "$REF" = HEAD ] && [ -n "$(git status --porcelain)" ]; then
    echo "warning: the working tree has uncommitted changes; they are not in this build" >&2
fi

NAME="wiretrace-$VERSION-macos"
mkdir -p dist
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# git archive stores owner 0:0, the commit time and no extended attributes. Its
# default umask leaves files group-writable.
git -c tar.umask=022 archive --format=tar.gz --prefix=wiretrace/ -o "dist/$NAME.tar.gz" "$COMMIT"

# macOS tags the staged files with com.apple.provenance, which cannot be removed and
# ends up in the image. It holds no user or host name.
mkdir "$tmp/stage"
tar -xzf "dist/$NAME.tar.gz" -C "$tmp/stage"
rm -f "dist/$NAME.dmg"
hdiutil create -quiet -volname "Wiretrace $VERSION" -srcfolder "$tmp/stage" \
    -fs HFS+ -format UDZO "dist/$NAME.dmg"

cd dist
for file in "$NAME.tar.gz" "$NAME.dmg"; do
    shasum -a 256 "$file" > "$file.sha256"
done
cat "$NAME.tar.gz.sha256" "$NAME.dmg.sha256"
echo "Built from $COMMIT: dist/$NAME.tar.gz and dist/$NAME.dmg"
