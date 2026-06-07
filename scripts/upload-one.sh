#!/usr/bin/env bash
# Upload a single wallpaper's artifacts to Hetzner Object Storage.
#
# Used by process-image.py to publish newly-processed wallpapers as they
# come in. Idempotent (rclone copy is a no-op when remote is up to date).
#
# Args:
#   $1  rel path of the wallpaper inside the repo
#         (e.g. dark/blue/1920x1080_foo.jpg)
#   $2  base slug for the omarchy theme dir
#         (e.g. luminous-glass-sphere); each of <base>-tokyo|nord|gruv is uploaded
#
# Required env (loaded from .env if present):
#   HETZNER_BUCKET
#
# Exits 0 silently if HETZNER_BUCKET isn't set (so local-only runs don't fail).
set -uo pipefail

REL="${1:?usage: upload-one.sh <rel-path> <base-slug>}"
BASE="${2:?usage: upload-one.sh <rel-path> <base-slug>}"

cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
if [ -z "${HETZNER_BUCKET:-}" ]; then
  exit 0  # no creds; quietly skip
fi
if ! command -v rclone >/dev/null 2>&1; then
  echo "upload-one: rclone not installed; skipping" >&2
  exit 0
fi

REMOTE="hetzner:${HETZNER_BUCKET}"
ARGS=(--transfers 4 --s3-acl public-read --copy-links --no-traverse)

# 1) the source wallpaper itself
if [ -f "$REL" ]; then
  rclone copyto "$REL" "${REMOTE}/${REL}" "${ARGS[@]}" 2>&1 \
    | grep -v 'Transferred:.*ETA' || true
fi

# 2) thumb + medium cache mirrors (stem stays the same; ext becomes .jpg)
stem="${REL%.*}"
for kind in thumb medium; do
  src="cache/${kind}/${stem}.jpg"
  [ -f "$src" ] || continue
  rclone copyto "$src" "${REMOTE}/${src}" "${ARGS[@]}" 2>&1 \
    | grep -v 'Transferred:.*ETA' || true
done

# 3) the three packaged omarchy theme dirs (colors.toml + neovim.lua + bg symlink)
OMARCHY_OUT="${OMARCHY_THEMES_OUT:-$HOME/Code/omarchy-themes}"
for short in mono warm cool material aether; do
  td="${OMARCHY_OUT}/${BASE}-${short}"
  [ -d "$td" ] || continue
  rclone copy "$td" "${REMOTE}/omarchy-themes/${BASE}-${short}" "${ARGS[@]}" 2>&1 \
    | grep -v 'Transferred:.*ETA' || true
done

exit 0
