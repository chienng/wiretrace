#!/bin/bash
# Builds app/Wiretrace.icns from app/icon.svg, and the menu bar mark menubar/icon.pdf from
# app/menubar-icon.svg. A developer tool: it needs rsvg-convert (librsvg). Both outputs are
# committed, so setup-mac.sh and make-app.sh never run this.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
command -v rsvg-convert >/dev/null || { echo "rsvg-convert not found (brew install librsvg)" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
set="$tmp/Wiretrace.iconset"
mkdir "$set"
for size in 16 32 128 256 512; do
    rsvg-convert -w "$size" -h "$size" "$ROOT/app/icon.svg" -o "$set/icon_${size}x${size}.png"
    rsvg-convert -w $((size * 2)) -h $((size * 2)) "$ROOT/app/icon.svg" -o "$set/icon_${size}x${size}@2x.png"
done
iconutil -c icns -o "$ROOT/app/Wiretrace.icns" "$set"
echo "Built app/Wiretrace.icns"
# Vector, so the size is only nominal: menubar/__main__.py scales it to the menu bar.
rsvg-convert -f pdf -w 18 "$ROOT/app/menubar-icon.svg" -o "$ROOT/menubar/icon.pdf"
echo "Built menubar/icon.pdf"
