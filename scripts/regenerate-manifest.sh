#!/usr/bin/env bash
# Regenerate cache + wallpapers.json end-to-end.
#
# The whole per-image pipeline now lives in process-image.py; this script
# just orchestrates the prefixing, dedupe, and parallel batch.
#
# Flags:
#   --skip-prefix      don't run prefix-size.sh
#   --skip-dedupe      don't run dedupe.sh (default is dry-run anyway)
#   --apply-dedupe     run dedupe.sh with --apply instead of dry-run
#   --par N            parallel workers for process-all.sh (default 8)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

SKIP_PREFIX=0
SKIP_DEDUPE=0
APPLY_DEDUPE=0
PAR="${PAR:-8}"

while [ $# -gt 0 ]; do
    case "$1" in
        --skip-prefix)  SKIP_PREFIX=1 ;;
        --skip-dedupe)  SKIP_DEDUPE=1 ;;
        --apply-dedupe) APPLY_DEDUPE=1 ;;
        --par)          shift; PAR="$1" ;;
        -h|--help)      sed -n '2,/^$/p' "$0" | sed 's/^# //;s/^#//'; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
    shift
done

step() { printf '\n=== %s ===\n' "$*"; }

if [ "$SKIP_PREFIX" = 0 ]; then
    step "prefix-size"
    "$SCRIPT_DIR/prefix-size.sh"
fi

if [ "$SKIP_DEDUPE" = 0 ]; then
    if [ "$APPLY_DEDUPE" = 1 ]; then
        step "dedupe --apply"
        "$SCRIPT_DIR/dedupe.sh" --apply
    else
        step "dedupe (dry-run; pass --apply-dedupe to actually delete)"
        "$SCRIPT_DIR/dedupe.sh"
    fi
fi

step "process-all (per-image: cache, palette, classify, scheme, move) [PAR=$PAR]"
PAR="$PAR" "$SCRIPT_DIR/process-all.sh"

echo
echo "Done. wallpapers.json has $(jq 'length' "$ROOT/wallpapers.json") entries."
