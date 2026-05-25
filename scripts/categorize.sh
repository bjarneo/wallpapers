#!/usr/bin/env bash
# v2: portrait/mobile skip + live-wallpaper routing.
#
# Required env:
#   SRC=/path/to/repo            source root
#   DST=/home/bjarneo/Wallpapers destination root (must have dark/ light/ live/)
#   THEME_PREFIX=somename        prefix prepended to every output filename
#
# Optional:
#   QUALITY=92
#   SAT_THRESHOLD=0.15
#   LIVE_EXTS="gif mp4 webm mov"  formats routed to live/
set -uo pipefail

SRC="${SRC:?SRC required}"
DST="${DST:?DST required}"
THEME_PREFIX="${THEME_PREFIX:?THEME_PREFIX required}"
QUALITY="${QUALITY:-92}"
SAT_THRESHOLD="${SAT_THRESHOLD:-0.15}"
LIVE_EXTS="${LIVE_EXTS:-gif mp4 webm mov}"

process_one() {
    local f="$1"
    [ -f "$f" ] || return 0

    local ext="${f##*.}"
    ext="${ext,,}"
    case "$ext" in
        jpg|jpeg|png|webp|gif|mp4|webm|mov) ;;
        *) return 0 ;;
    esac

    local base outdir out theme
    base=$(basename "$f")
    base="${base%.*}"

    # Live route: just copy through, no re-encode.
    local is_live=0
    for le in $LIVE_EXTS; do
        if [ "$ext" = "$le" ]; then is_live=1; break; fi
    done

    if [ "$is_live" = "1" ]; then
        outdir="$DST/live"
        mkdir -p "$outdir"
        out="$outdir/${THEME_PREFIX}_${base}.${ext}"
        if [ -f "$out" ]; then
            printf 'skip-exists\t%s\n' "$out"
            return 0
        fi
        if cp -n -- "$f" "$out"; then
            printf 'live\t%s\n' "$out"
        else
            printf 'copy-failed\t%s\n' "$f" >&2
        fi
        return 0
    fi

    # Static image: read dimensions and skip portrait
    local dims w h
    dims=$(magick identify -format "%w %h" "${f}[0]" 2>/dev/null) || {
        printf 'identify-failed\t%s\n' "$f" >&2
        return 0
    }
    read -r w h <<<"$dims"
    if [ -z "${w:-}" ] || [ -z "${h:-}" ]; then
        printf 'bad-dims\t%s\n' "$f" >&2
        return 0
    fi
    if [ "$h" -gt "$w" ]; then
        printf 'skip-portrait\t%dx%d\t%s\n' "$w" "$h" "$f"
        return 0
    fi

    # Classify
    local rgb
    rgb=$(magick "${f}[0]" -resize 64x64! -colorspace sRGB \
        -format "%[fx:mean.r] %[fx:mean.g] %[fx:mean.b]" info: 2>/dev/null) || {
        printf 'classify-failed\t%s\n' "$f" >&2
        return 0
    }

    local target
    target=$(awk -v rgb="$rgb" -v sat="$SAT_THRESHOLD" 'BEGIN {
        n = split(rgb, a, " ")
        if (n < 3) { print ""; exit }
        r = a[1]+0; g = a[2]+0; b = a[3]+0
        max = (r > g) ? ((r > b) ? r : b) : ((g > b) ? g : b)
        min = (r < g) ? ((r < b) ? r : b) : ((g < b) ? g : b)
        L = (max + min) / 2
        d = max - min
        if (d == 0) { H = 0; S = 0 }
        else {
            S = (L > 0.5) ? d / (2 - max - min) : d / (max + min)
            if (max == r) H = (g - b) / d + (g < b ? 6 : 0)
            else if (max == g) H = (b - r) / d + 2
            else H = (r - g) / d + 4
            H *= 60
        }
        tone = (L < 0.5) ? "dark" : "light"
        if (S < sat) color = "monochrome"
        else if (H < 15 || H >= 345) color = "red"
        else if (H < 45)  color = "orange"
        else if (H < 70)  color = "yellow"
        else if (H < 160) color = "green"
        else if (H < 200) color = "cyan"
        else if (H < 250) color = "blue"
        else if (H < 290) color = "purple"
        else              color = "pink"
        print tone "/" color
    }')

    [ -z "$target" ] && { printf 'awk-failed\t%s\n' "$f" >&2; return 0; }

    outdir="$DST/$target"
    mkdir -p "$outdir"
    out="$outdir/${THEME_PREFIX}_${base}.jpg"

    if [ -f "$out" ]; then
        printf 'skip-exists\t%s\n' "$out"
        return 0
    fi

    if magick "${f}[0]" \
        -background white -alpha remove -alpha off \
        -strip -interlace Plane -sampling-factor 4:2:0 \
        -quality "$QUALITY" \
        "$out" 2>/dev/null; then
        printf 'ok\t%s\t%s\n' "$target" "$out"
    else
        rm -f "$out"
        printf 'convert-failed\t%s\n' "$f" >&2
    fi
}

export -f process_one
export DST QUALITY SAT_THRESHOLD THEME_PREFIX LIVE_EXTS

find "$SRC" -type f \
    \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \
       -o -iname '*.gif' -o -iname '*.mp4' -o -iname '*.webm' -o -iname '*.mov' \) \
    -not -path '*/.git/*' \
    -print0 |
    xargs -0 -n1 -P8 bash -c 'process_one "$0"'
