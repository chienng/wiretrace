#!/bin/bash
# Builds app/Wiretrace.icns from app/icon.svg, and the menu bar icon menubar/icon.tiff from
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
# PNGs in a TIFF, not a PDF: AppKit draws rsvg's PDF of the cut-out W as blank.
rsvg-convert -w 16 -h 16 "$ROOT/app/menubar-icon.svg" -o "$tmp/menubar.png"
rsvg-convert -w 32 -h 32 "$ROOT/app/menubar-icon.svg" -o "$tmp/menubar@2x.png"
tiffutil -cathidpicheck "$tmp/menubar.png" "$tmp/menubar@2x.png" -out "$ROOT/menubar/icon.tiff" 2>/dev/null
echo "Built menubar/icon.tiff"
