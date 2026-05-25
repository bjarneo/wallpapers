#!/usr/bin/env bash
# Prepend image dimensions (e.g. 1920x1080_) to every wallpaper filename.
#
# Idempotent: files whose basename already starts with "<digits>x<digits>_" are
# left alone. Reads only the image header to get dimensions, so it is fast.
#
# Usage:
#   ./scripts/prefix-size.sh             # default root: parent of script directory
#   ./scripts/prefix-size.sh /some/path  # explicit root
#   DRY_RUN=1 ./scripts/prefix-size.sh   # show what would happen, don't rename

set -uo pipefail

ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
DRY_RUN="${DRY_RUN:-0}"

command -v magick >/dev/null || { echo "magick (ImageMagick 7) not found" >&2; exit 1; }

renamed=0
skipped=0
failed=0

while IFS= read -r -d '' f; do
    base=$(basename "$f")
    dir=$(dirname "$f")

    if [[ "$base" =~ ^[0-9]+x[0-9]+_ ]]; then
        skipped=$((skipped + 1))
        continue
    fi

    dims=$(magick identify -format "%wx%h" "${f}[0]" 2>/dev/null) || {
        echo "  ! identify failed: $f" >&2
        failed=$((failed + 1))
        continue
    }

    new="$dir/${dims}_${base}"

    if [ -e "$new" ]; then
        echo "  ! target exists, skipping: $new" >&2
        failed=$((failed + 1))
        continue
    fi

    if [ "$DRY_RUN" = "1" ]; then
        echo "would: $f -> $new"
    else
        mv -n -- "$f" "$new"
    fi
    renamed=$((renamed + 1))
done < <(find "$ROOT" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' -o -iname '*.gif' \) -print0)

echo
echo "Renamed: $renamed"
echo "Skipped: $skipped (already prefixed)"
echo "Failed:  $failed"
