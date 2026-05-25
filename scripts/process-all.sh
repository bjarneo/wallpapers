#!/usr/bin/env bash
# Run process-image.py over every wallpaper under dark/ and light/, in parallel.
# After all workers exit, merge the sidecars into wallpapers.json.
#
# Env:
#   PAR=N       parallel worker count (default 8)
#   ROOT=...    repo root (default: parent of script dir)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PAR="${PAR:-8}"

cd "$ROOT"

mapfile -d '' files < <(find "$ROOT/dark" "$ROOT/light" -type f \
    \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \) \
    -print0 2>/dev/null)

n=${#files[@]}
echo "Processing $n images with $PAR workers"

printf '%s\0' "${files[@]}" | xargs -0 -P "$PAR" -n1 python3 "$SCRIPT_DIR/process-image.py"

echo
echo "Merging sidecars into wallpapers.json"
python3 "$SCRIPT_DIR/merge-sidecars.py"
