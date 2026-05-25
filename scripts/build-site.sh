#!/usr/bin/env bash
# Build dist/ for GitHub Pages.
#
# Produces:
#   dist/index.html   (copied as-is)
#   dist/sw.js        (copied as-is)
#   dist/wallpapers.js  (window.WALLPAPERS = {...};  with base URL injected)
#   dist/live.js        (window.LIVE = {...};        with base URL injected)
#
# index.html reads window.WALLPAPERS_BASE_URL at load time and prefixes
# every relative thumb_path / medium_path / path with it. The base URL
# is sourced from $WALLPAPERS_BASE_URL or .env's $HETZNER_PUBLIC_BASE.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
BASE="${WALLPAPERS_BASE_URL:-${HETZNER_PUBLIC_BASE:-}}"
if [ -z "$BASE" ]; then
  echo "warn: no WALLPAPERS_BASE_URL / HETZNER_PUBLIC_BASE set. Building with relative paths." >&2
fi

OUT=dist
rm -rf "$OUT"
mkdir -p "$OUT"

cp index.html "$OUT/"
cp sw.js "$OUT/"

# Inject base URL as a prelude so it's defined BEFORE wallpapers.js / live.js run.
{
  printf 'window.WALLPAPERS_BASE_URL = %s;\n' "$(printf %s "$BASE" | jq -Rs .)"
  printf 'window.WALLPAPERS = '; cat wallpapers.json; printf ';\n'
} > "$OUT/wallpapers.js"

if [ -f live.json ]; then
  { printf 'window.LIVE = '; cat live.json; printf ';\n'; } > "$OUT/live.js"
fi

# .nojekyll so GitHub Pages serves files with leading underscores etc. verbatim.
touch "$OUT/.nojekyll"

echo "built -> $OUT/"
echo "  base url: ${BASE:-<none, relative>}"
du -sh "$OUT"/* 2>/dev/null || true
