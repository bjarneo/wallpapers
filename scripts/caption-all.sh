#!/usr/bin/env bash
# Parallel batch captioning of every wallpaper via claude -p (Haiku 4.5).
# Idempotent: skips entries that already have llm_captioned=true.
#
# Env:
#   PAR=N   parallel workers (default 12; claude -p is mostly I/O-bound)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PAR="${PAR:-12}"

cd "$ROOT"

mapfile -d '' files < <(find "$ROOT/dark" "$ROOT/light" -type f \
    \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \) \
    -print0 2>/dev/null)

n=${#files[@]}
echo "Captioning $n images with $PAR workers"
start=$(date +%s)

# Strip the ROOT prefix from each path so we pass relpaths.
printf '%s\0' "${files[@]}" \
    | sed -z "s|^${ROOT}/||" \
    | xargs -0 -P "$PAR" -n1 python3 "$SCRIPT_DIR/caption-image.py"

end=$(date +%s)
echo
echo "Captioning finished in $((end - start))s"
echo
echo "Merging sidecars into wallpapers.json"
python3 "$SCRIPT_DIR/merge-sidecars.py"
