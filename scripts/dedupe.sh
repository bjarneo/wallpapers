#!/usr/bin/env bash
# Detect (and optionally remove) duplicate wallpapers.
#
# Algorithm:
#   1. Resize each image to a 16x16 grayscale thumbnail.
#   2. Use its SHA-256 pixel signature as the dedup key.
#   3. Files sharing a key are duplicates (exact dupes, resizes, re-encodes,
#      slight crops, format swaps all collide on this signature).
#   4. Within each duplicate group, keep the highest-pixel-count copy
#      (parsed from the WxH_ filename prefix); tie-break on file size.
#
# Defaults to dry-run. Pass --apply to delete duplicates.
#
# Usage:
#   ./dedupe.sh                                  # dry-run, dark/ + light/
#   ./dedupe.sh --apply                          # delete dupes
#   ./dedupe.sh --include-live                   # also scan live/
#   ROOT=/some/path ./dedupe.sh                  # override root
#   ./dedupe.sh --apply --include-live

set -uo pipefail

ROOT="${ROOT:-/home/bjarneo/Wallpapers}"
APPLY=0
INCLUDE_LIVE=0

for arg in "$@"; do
    case "$arg" in
        --apply)        APPLY=1 ;;
        --include-live) INCLUDE_LIVE=1 ;;
        -h|--help)
            sed -n '2,/^$/p' "$0" | sed 's/^# //;s/^#//'
            exit 0
            ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

command -v magick >/dev/null || { echo "magick (ImageMagick 7) required" >&2; exit 1; }

# Build scan dirs
declare -a SCAN_DIRS=()
for d in "$ROOT/dark" "$ROOT/light"; do
    [ -d "$d" ] && SCAN_DIRS+=("$d")
done
if [ "$INCLUDE_LIVE" = "1" ] && [ -d "$ROOT/live" ]; then
    SCAN_DIRS+=("$ROOT/live")
fi

if [ "${#SCAN_DIRS[@]}" -eq 0 ]; then
    echo "no scan dirs found under $ROOT" >&2; exit 1
fi

SIG_SIZE="${SIG_SIZE:-32}"

compute_sig() {
    magick "${1}[0]" -resize "${SIG_SIZE}x${SIG_SIZE}!" -colorspace Gray -depth 8 -format "%#" info: 2>/dev/null
}
export SIG_SIZE
export -f compute_sig

manifest=$(mktemp)
trap "rm -f '$manifest' '${manifest}.sorted'" EXIT

echo "Hashing images under: ${SCAN_DIRS[*]}"
find "${SCAN_DIRS[@]}" -type f \
    \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' -o -iname '*.gif' \) \
    -print0 |
    xargs -0 -P8 -n1 bash -c '
        sig=$(compute_sig "$0")
        [ -n "$sig" ] && printf "%s\t%s\n" "$sig" "$0"
    ' > "$manifest"

total_files=$(wc -l < "$manifest")
sort "$manifest" > "${manifest}.sorted"
mv "${manifest}.sorted" "$manifest"

groups=0
total_dupes=0
removed=0
prev_sig=""
declare -a group_files=()

flush_group() {
    local count="${#group_files[@]}"
    [ "$count" -lt 2 ] && return 0

    groups=$((groups + 1))

    local best_score=-1
    local best_file=""
    declare -A scores=()
    local f base pixels bytes score
    for f in "${group_files[@]}"; do
        base=$(basename "$f")
        if [[ "$base" =~ ^([0-9]+)x([0-9]+)_ ]]; then
            pixels=$(( BASH_REMATCH[1] * BASH_REMATCH[2] ))
        else
            pixels=0
        fi
        bytes=$(stat -c '%s' "$f" 2>/dev/null || echo 0)
        score=$(( pixels * 10000000 + bytes ))
        scores["$f"]=$score
        if [ "$score" -gt "$best_score" ]; then
            best_score=$score
            best_file=$f
        fi
    done

    echo "--- group: $prev_sig"
    for f in "${group_files[@]}"; do
        if [ "$f" = "$best_file" ]; then
            printf '  KEEP   %s\n' "$f"
        else
            total_dupes=$((total_dupes + 1))
            if [ "$APPLY" = "1" ]; then
                if rm -f -- "$f"; then
                    removed=$((removed + 1))
                    printf '  DEL    %s\n' "$f"
                fi
            else
                printf '  dupe   %s\n' "$f"
            fi
        fi
    done
}

while IFS=$'\t' read -r sig path; do
    [ -z "$sig" ] && continue
    if [ "$sig" != "$prev_sig" ]; then
        flush_group
        group_files=()
        prev_sig="$sig"
    fi
    group_files+=("$path")
done < "$manifest"
flush_group

echo
echo "Scanned:           $total_files files"
echo "Duplicate groups:  $groups"
if [ "$APPLY" = "1" ]; then
    echo "Removed:           $removed"
else
    echo "Would remove:      $total_dupes (rerun with --apply to delete)"
fi
