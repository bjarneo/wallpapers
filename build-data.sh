#!/usr/bin/env bash
# Wrap wallpapers.json + live.json into window.WALLPAPERS / window.LIVE
# so index.html works directly from file:// (no http server required).
# Re-run after regenerating wallpapers.json.
set -euo pipefail
cd "$(dirname "$0")"

{ printf 'window.WALLPAPERS = '; cat wallpapers.json; printf ';\n'; } > wallpapers.js
[ -f live.json ] && { printf 'window.LIVE = '; cat live.json; printf ';\n'; } > live.js

echo "wrote $(wc -c < wallpapers.js) bytes -> wallpapers.js"
[ -f live.js ] && echo "wrote $(wc -c < live.js) bytes -> live.js"
