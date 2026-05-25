#!/usr/bin/env bash
# Reduce wallpaper file sizes without changing dimensions, aiming for visually imperceptible loss.
#
# JPEG: re-encode at quality 85, chroma subsample 4:2:0, strip metadata, progressive scan.
# PNG : lossless re-encode at max zlib level, strip metadata.
# WebP: re-encode at quality 85, strip metadata.
#
# Dimensions are preserved (no -resize). Files are overwritten in place; an
# original is kept only if the optimized version ends up larger.

set -euo pipefail

ROOT="${1:-/home/bjarneo/Wallpapers2}"
QUALITY="${QUALITY:-85}"

command -v magick >/dev/null || { echo "magick (ImageMagick 7) not found" >&2; exit 1; }

# Stats
total_before=0
total_after=0
count=0
skipped=0

# Process one file: $1 = path
optimize_one() {
    local f="$1"
    local before after tmp ext
    before=$(stat -c '%s' "$f")
    ext="${f##*.}"
    ext="${ext,,}"
    tmp="${f}.opt.tmp"

    case "$ext" in
        jpg|jpeg)
            magick "$f" \
                -strip \
                -interlace Plane \
                -sampling-factor 4:2:0 \
                -quality "$QUALITY" \
                "$tmp"
            ;;
        png)
            magick "$f" \
                -strip \
                -define png:compression-level=9 \
                -define png:compression-filter=5 \
                -define png:compression-strategy=1 \
                "$tmp"
            ;;
        webp)
            magick "$f" \
                -strip \
                -quality "$QUALITY" \
                -define webp:method=6 \
                "$tmp"
            ;;
        *)
            return 0
            ;;
    esac

    if [ ! -s "$tmp" ]; then
        rm -f "$tmp"
        echo "  ! re-encode failed: $f" >&2
        return 0
    fi

    after=$(stat -c '%s' "$tmp")

    if [ "$after" -lt "$before" ]; then
        mv "$tmp" "$f"
        total_before=$((total_before + before))
        total_after=$((total_after + after))
        count=$((count + 1))
    else
        # Keep the original if optimized is not smaller
        rm -f "$tmp"
        skipped=$((skipped + 1))
    fi
}

mapfile -d '' files < <(find "$ROOT" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \) -print0)
n=${#files[@]}
i=0
for f in "${files[@]}"; do
    i=$((i + 1))
    optimize_one "$f"
    if [ $((i % 50)) -eq 0 ]; then
        printf '  %d/%d\n' "$i" "$n"
    fi
done

if [ "$count" -gt 0 ]; then
    saved=$((total_before - total_after))
    pct=$(awk -v b="$total_before" -v a="$total_after" 'BEGIN { if (b>0) printf "%.1f", (b-a)*100.0/b; else print "0" }')
    echo
    echo "Optimized:  $count files"
    echo "Skipped:    $skipped files (already optimal)"
    echo "Before:     $(numfmt --to=iec --suffix=B "$total_before")"
    echo "After:      $(numfmt --to=iec --suffix=B "$total_after")"
    echo "Saved:      $(numfmt --to=iec --suffix=B "$saved") (${pct}%)"
else
    echo "No files optimized."
fi
