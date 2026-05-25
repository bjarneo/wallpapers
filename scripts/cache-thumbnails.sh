#!/usr/bin/env bash
# Generate cached thumbnail + medium-size JPGs for every wallpaper.
#
# Output layout (mirrors the source tree):
#   cache/thumb/dark/<color>/...  (long edge 256 by default, jpg q85)
#   cache/medium/dark/<color>/... (long edge 1024 by default, jpg q85)
#   cache/thumb/live/...
#   cache/medium/live/...
#
# Idempotent: skips a target if it already exists *and* is newer than the source.
# Run again after adding new wallpapers; only the new files do work.
#
# Env knobs:
#   THUMB_SIZE=256
#   MEDIUM_SIZE=1024
#   QUALITY=85
#   PAR=8
#   ROOT=/home/bjarneo/Wallpapers

set -uo pipefail

ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
THUMB_SIZE="${THUMB_SIZE:-256}"
MEDIUM_SIZE="${MEDIUM_SIZE:-1024}"
QUALITY="${QUALITY:-85}"
PAR="${PAR:-8}"

command -v magick >/dev/null || { echo "magick required" >&2; exit 1; }

THUMB_ROOT="$ROOT/cache/thumb"
MEDIUM_ROOT="$ROOT/cache/medium"

process_one() {
    local src="$1"
    local rel="${src#${ROOT}/}"
    local stem="${rel%.*}"
    local thumb="$THUMB_ROOT/${stem}.jpg"
    local medium="$MEDIUM_ROOT/${stem}.jpg"

    local need_thumb=1 need_medium=1
    if [ -f "$thumb" ] && [ "$thumb" -nt "$src" ]; then need_thumb=0; fi
    if [ -f "$medium" ] && [ "$medium" -nt "$src" ]; then need_medium=0; fi
    if [ "$need_thumb" = 0 ] && [ "$need_medium" = 0 ]; then
        return 0
    fi

    if [ "$need_thumb" = 1 ]; then
        mkdir -p "$(dirname "$thumb")"
        magick "${src}[0]" \
            -background white -alpha remove -alpha off \
            -resize "${THUMB_SIZE}x${THUMB_SIZE}>" \
            -strip -interlace Plane -sampling-factor 4:2:0 \
            -quality "$QUALITY" \
            "jpg:${thumb}" 2>/dev/null || {
                echo "  ! thumb failed: $src" >&2
                rm -f "$thumb"
            }
    fi

    if [ "$need_medium" = 1 ]; then
        mkdir -p "$(dirname "$medium")"
        magick "${src}[0]" \
            -background white -alpha remove -alpha off \
            -resize "${MEDIUM_SIZE}x${MEDIUM_SIZE}>" \
            -strip -interlace Plane -sampling-factor 4:2:0 \
            -quality "$QUALITY" \
            "jpg:${medium}" 2>/dev/null || {
                echo "  ! medium failed: $src" >&2
                rm -f "$medium"
            }
    fi

    printf '.'
}

export -f process_one
export ROOT THUMB_ROOT MEDIUM_ROOT THUMB_SIZE MEDIUM_SIZE QUALITY

# Find all source wallpapers (skip the cache itself)
mapfile -d '' files < <(find "$ROOT/dark" "$ROOT/light" "$ROOT/live" \
    -type f \
    \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' -o -iname '*.gif' \) \
    -not -path "$ROOT/cache/*" \
    -print0 2>/dev/null)

n=${#files[@]}
echo "Caching $n wallpapers"
echo "  thumb: ${THUMB_SIZE}px long edge -> $THUMB_ROOT"
echo "  medium: ${MEDIUM_SIZE}px long edge -> $MEDIUM_ROOT"
echo

printf '%s\0' "${files[@]}" | xargs -0 -P "$PAR" -n1 bash -c 'process_one "$0"'
echo
echo "Done."

# Tiny summary
thumb_count=$(find "$THUMB_ROOT" -type f 2>/dev/null | wc -l)
medium_count=$(find "$MEDIUM_ROOT" -type f 2>/dev/null | wc -l)
thumb_size=$(du -sh "$THUMB_ROOT" 2>/dev/null | cut -f1)
medium_size=$(du -sh "$MEDIUM_ROOT" 2>/dev/null | cut -f1)
echo
echo "Thumbs:  $thumb_count files ($thumb_size)"
echo "Mediums: $medium_count files ($medium_size)"
