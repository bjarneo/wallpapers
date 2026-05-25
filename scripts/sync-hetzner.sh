#!/usr/bin/env bash
# Sync cache/, dark/, light/, live/ to Hetzner Object Storage.
# Idempotent: only uploads new/changed files. Pass --dry-run to preview.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
: "${HETZNER_BUCKET:?HETZNER_BUCKET not set (source .env or export it)}"

REMOTE="hetzner:${HETZNER_BUCKET}"
ARGS=(--fast-list --transfers 16 --checkers 16 --s3-acl public-read --progress)
[ "${1:-}" = "--dry-run" ] && ARGS+=(--dry-run)

for dir in cache dark light live; do
  [ -d "$dir" ] || { echo "skip $dir (missing)"; continue; }
  echo ">>> syncing $dir/ -> ${REMOTE}/${dir}/"
  rclone sync "$dir" "${REMOTE}/${dir}" "${ARGS[@]}"
done

echo "done. public base: ${HETZNER_PUBLIC_BASE:-https://${HETZNER_BUCKET}.${HETZNER_ENDPOINT#https://}}"
