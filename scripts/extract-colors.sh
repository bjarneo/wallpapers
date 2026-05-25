#!/usr/bin/env bash
# Extract top-16 dominant colors from each thumb via ImageMagick histogram.
# Output: TSV "<source_relpath>\t<json array of 16 hex strings (descending count)>"
set -uo pipefail

ROOT="${ROOT:-/home/bjarneo/Wallpapers}"

extract_one() {
    local thumb="$1"
    local rel="${thumb#${ROOT}/cache/thumb/}"
    # The source relpath uses the actual source extension; we can't know it
    # from the thumb alone, so resolve it by globbing the source tree.
    local stem="${rel%.jpg}"
    local src=""
    for ext in jpg jpeg png webp; do
        if [ -f "${ROOT}/${stem}.${ext}" ]; then
            src="${stem}.${ext}"
            break
        fi
    done
    [ -z "$src" ] && return 0

    local raw
    raw=$(magick "$thumb" -dither None -colors 16 -depth 8 -format "%c" histogram:info:- 2>/dev/null) || return 0

    # Extract top 16 hex (sorted desc by count)
    local hexes
    hexes=$(printf '%s\n' "$raw" \
        | sort -t: -k1,1nr \
        | grep -oE '#[0-9A-Fa-f]{6}' \
        | head -16 \
        | paste -sd ',' -)
    [ -z "$hexes" ] && return 0

    # Wrap as JSON array of quoted strings
    local arr
    arr=$(printf '%s' "$hexes" | sed 's/#\([0-9A-Fa-f]*\)/"#\1"/g')
    printf '%s\t[%s]\n' "$src" "$arr"
}
export -f extract_one
export ROOT

find "$ROOT/cache/thumb" -type f -name '*.jpg' -print0 \
    | xargs -0 -P8 -n1 bash -c 'extract_one "$0"'
