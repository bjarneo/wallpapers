#!/usr/bin/env bash
# Parallel batched scheme matching via claude -p.
set -uo pipefail

IN="${IN:-/tmp/top16.tsv}"
OUT="${OUT:-/tmp/schemes.tsv}"
BATCH="${BATCH:-50}"
PAR="${PAR:-4}"
MODEL="${MODEL:-claude-haiku-4-5}"
WORKDIR="${WORKDIR:-/tmp/scheme-batches}"

rm -rf "$WORKDIR"
mkdir -p "$WORKDIR"
: > "$OUT"

SCHEMES="Tokyo Night, Catppuccin Mocha, Catppuccin Macchiato, Catppuccin Frappe, Catppuccin Latte, Nord, Gruvbox Dark, Gruvbox Light, Solarized Dark, Solarized Light, Dracula, Rose Pine, Rose Pine Moon, Rose Pine Dawn, Everforest Dark, Everforest Light, Kanagawa, One Dark, Monokai, Ayu Dark, Ayu Light, Material Dark, Material Light"

total=$(wc -l < "$IN")
echo "Splitting $total palettes into batches of $BATCH"

# Split input into batch files
split -d -l "$BATCH" -a 4 "$IN" "$WORKDIR/batch-"

process_batch() {
    local bfile="$1"
    local body
    body=$(awk -F'\t' '{printf "%d: %s\n", NR, $2}' "$bfile")
    local prompt="For each palette below, output ONLY a JSON array (no markdown fences, no commentary) of objects {\"id\":N,\"scheme\":\"Name\"} picking the single best-matching popular color scheme from this allowed list: ${SCHEMES}. If none clearly fits, use \"Custom\".

Palettes:
${body}"

    local response
    response=$(printf '%s' "$prompt" | claude --model "$MODEL" -p 2>/dev/null || true)

    local json
    json=$(printf '%s' "$response" | sed -n '/\[/,/\]/p')

    local schemes_per_id
    schemes_per_id=$(printf '%s' "$json" | jq -r 'sort_by(.id) | .[] | .scheme' 2>/dev/null)

    if [ -z "$schemes_per_id" ]; then
        echo "  ! $(basename "$bfile"): parse failed" >&2
        schemes_per_id=$(awk '{print "Custom"}' "$bfile")
    fi

    paste <(cut -f1 "$bfile") <(printf '%s\n' "$schemes_per_id") > "${bfile}.out"
    printf 'done %s (%d rows)\n' "$(basename "$bfile")" "$(wc -l < "${bfile}.out")" >&2
}
export -f process_batch
export MODEL SCHEMES

ls "$WORKDIR"/batch-* | xargs -P "$PAR" -n1 bash -c 'process_batch "$0"'

cat "$WORKDIR"/batch-*.out > "$OUT"
echo "Wrote $(wc -l < "$OUT") rows to $OUT"
