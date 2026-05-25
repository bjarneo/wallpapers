# Wallpaper repo — instructions for Claude

This directory holds curated wallpapers, sorted by tone and dominant color. When the user adds new images, or you are asked to ingest a new wallpaper source, follow the pipeline below. Every script in `scripts/` is idempotent and safe to re-run.

## Layout

```
dark/<color>/    WxH_<theme>_<rest>.jpg   (rare: .jpeg, .png if dharmx had only that)
light/<color>/   WxH_<theme>_<rest>.jpg
live/            animated wallpapers (gif, mp4, webm, mov) — no color buckets, not in manifest
cache/thumb/     mirrored 256px JPEG thumbnails (q85)
cache/medium/    mirrored 1024px JPEG previews (q85)
cache/manifest/  per-image sidecar JSONs (one per wallpaper, auto-merged into wallpapers.json)
wallpapers.json  merged manifest, one entry per static wallpaper (see schema below)
scripts/         all pipeline scripts
```

Color buckets: `red orange yellow green cyan blue purple pink monochrome`.
Tone is mean luminance below/above 0.5 (set at ingest). Color is the *saliency-weighted* dominant in the top-8 palette colors — picks the figure, not the background. Folder placement always matches the `color` field after `process-image.py` runs.

## Per-image pipeline

The whole per-image lifecycle is in `scripts/process-image.py`. One invocation per image, fully parallel-safe:

```
scripts/process-image.py dark/blue/foo.jpg
```

Steps (all in one process):
1. Reads dimensions; deletes file + cache if portrait or `height < 1080`.
2. Adds `WxH_` filename prefix if missing.
3. Extracts top-16 dominant hex codes via ImageMagick histogram on a 256x256 scratch resize.
4. Classifies color bucket via saliency = saturation x rank-decayed area, over top 8 colors. Falls back to `monochrome` if no candidate clears `MIN_SALIENCE` (0.06).
5. Matches the closest popular color scheme by mean LAB distance between lightness-sorted palettes against built-in scheme palettes. Returns `Custom` if mean ΔE > 35.
6. Moves the source file (and cache mirrors) to `<tone>/<color>/<filename>`, suffixing `_N` on collision (race-safe via `O_EXCL`).
7. (Re)generates 256px thumb and 1024px medium JPGs at q85 if missing or stale.
8. Derives `title`, `description`, `tags`, `theme` from filename.
9. Writes a sidecar at `cache/manifest/<dest_rel>.json` containing this image's entry.

Exit codes: `0` success, `2` skipped (portrait or sub-1080p), `1` failure.

Run many in parallel: `scripts/process-all.sh` does `xargs -P 8` across every image under `dark/` and `light/`, then merges sidecars into `wallpapers.json`.

## Scripts (all in `scripts/`)

| Script | Purpose |
| --- | --- |
| `regenerate-manifest.sh` | Top-level orchestrator: prefix-size, dedupe, process-all. Run after any ingest. |
| `process-image.py` | The per-image pipeline. Self-contained, parallel-safe. |
| `process-all.sh` | xargs -P parallel runner over every image; merges sidecars at end. |
| `merge-sidecars.py` | Concatenates `cache/manifest/*.json` into `wallpapers.json` and prunes stale sidecars. |
| `categorize.sh` | Bulk ingest a new source repo: `SRC=` `DST=` `THEME_PREFIX=`. Handles portrait skip, gif/video routing to `live/`, JPEG re-encode at q92. |
| `prefix-size.sh` | Add `WxH_` filename prefix. Idempotent. (process-image.py also does this; this is the bulk drop-in version.) |
| `dedupe.sh` | Detect (dry-run) and optionally delete (`--apply`) duplicates via 32x32 grayscale perceptual hash. Cross-file, can't be per-image. |
| `cache-thumbnails.sh` | Bulk cache generator (process-image.py does this per-image; this is the standalone version). |
| `optimize.sh` | Shrink source files in place at q85 (keeps original if smaller). |
| `extract-colors.sh`, `derive-metadata.py`, `assemble-manifest.py`, `add-size.py`, `add-cache-paths.py`, `update-colors.py`, `reconcile-folders.py`, `match-schemes.sh` | Pre-refactor scripts. Still functional but superseded by `process-image.py`. Kept for reference / piecewise re-runs. |

## wallpapers.json schema

Each entry (keyed by `<tone>/<color>/<filename>`) contains:

| Field | Source |
| --- | --- |
| `title` | filename-derived; `_NN` variant suffixes stripped, title-cased. |
| `description` | filename + tone + color + theme (best-effort). |
| `tags` | `[tone, color, theme, keywords...]` from filename tokens. |
| `tone` | `dark` or `light` (the folder). |
| `color` | dominant color bucket via saliency-weighted scoring (matches folder). |
| `theme` | first underscore segment after `WxH_` in the filename. |
| `colors` | top 16 hex codes by pixel count from the source image (descending). `colors[0]` is most pixels; the perceived dominant is recovered by the saliency-weighted scoring. |
| `scheme` | closest popular palette via LAB distance against built-in palettes (or `Custom`). Built-in schemes: Nord, Gruvbox Dark/Light, Tokyo Night, Dracula, Catppuccin Mocha/Macchiato/Frappe/Latte, Rose Pine/Moon/Dawn, Everforest Dark/Light, Kanagawa, One Dark, Monokai, Solarized Dark/Light, Ayu Dark/Light, Material Dark/Light. |
| `width`, `height` | integers parsed from `WxH_` prefix. |
| `dimensions` | `"<width>x<height>"` string (e.g. `"1920x1080"`). |
| `size_bytes` | byte size of the source wallpaper. |
| `thumb_path`, `medium_path` | relative paths under `cache/thumb/` and `cache/medium/`. Always `.jpg`. |

Notes:
- `live/` is NOT in this manifest.
- The manifest is always rebuilt from sidecars by `merge-sidecars.py`. To keep it up to date, ensure every image has a fresh sidecar (i.e. run `process-image.py` whenever a file changes) and re-merge.

## Adding new images

### Single drop-in (already in dark/light/)

```
scripts/process-image.py dark/blue/foo.jpg
scripts/merge-sidecars.py
```

Or for a batch of new files: `scripts/process-all.sh` (regenerates everything; idempotent so cheap).

### Bulk source ingest (cloned repo or external dir)

```
SRC=/path/to/repo \
DST=/home/bjarneo/Wallpapers \
THEME_PREFIX=shortname \
  scripts/categorize.sh
scripts/regenerate-manifest.sh
```

`categorize.sh` does the *first-pass* classification at ingest (mean-RGB hue bucketing, JPEG re-encode, portrait skip, gif routing). `process-image.py` then reclassifies via the better saliency-weighted scoring and moves to the correct bucket.

## Edge cases & gotchas

- **Mislabeled extensions.** A file may have `.jpg` but be a WebP container (`file <name>` to sniff). Re-encode with `magick "$f" ... "jpg:${f}.real" && mv "${f}.real" "$f"` — the `jpg:` prefix forces a real JPEG encode.
- **Mobile/portrait.** `process-image.py` deletes any image where `height > width`.
- **Sub-1080p.** `process-image.py` deletes any image where `height < 1080`.
- **`.png` / `.jpg` twins.** Two source files with same stem but different extension produce colliding sidecar paths (`foo.json` for both). Resolve by removing one (typically the `.png`, keeping `.jpg`).
- **Live wallpapers.** `live/` is intentionally flat and never re-encoded. Not in the per-image pipeline.
- **Dedupe.** Cross-file, must run separately. `dedupe.sh` uses 32x32 grayscale perceptual hash; `SIG_SIZE=N` env knob to tune.
- **Theme prefix collisions.** Two source repos can share the same `<theme>` token. Pick distinct `THEME_PREFIX` values per ingest.
- **Scheme matching is deterministic.** No LLM. If you want LLM-based reclassification, `scripts/match-schemes.sh` is still around (reads `/tmp/top16.tsv`, writes `/tmp/schemes.tsv`); merge results manually.

## Tunables (env vars on process-image.py)

| Var | Default | Effect |
| --- | --- | --- |
| `THUMB_SIZE` | 256 | Long edge of `cache/thumb/`. |
| `MEDIUM_SIZE` | 1024 | Long edge of `cache/medium/`. |
| `QUALITY` | 85 | JPEG quality for both cache variants. |
| `MIN_HEIGHT` | 1080 | Images with `height` below this are deleted. |
| `WALLPAPERS_ROOT` | `/home/bjarneo/Wallpapers` | Repo root override. |

Color/scheme thresholds live as constants near the top of `process-image.py`: `SAT_THRESHOLD`, `MIN_SALIENCE`, `TOP_N`.

## What not to do

- Do not edit `wallpapers.json` directly. It's a derived artifact. Edit sidecars or rerun `process-image.py` then `merge-sidecars.py`.
- Do not run `optimize.sh` against `live/` (would lose animation quality).
- Do not add files outside `dark/<color>/`, `light/<color>/`, or `live/`. The pipeline parses paths positionally.
- Do not introduce a new color bucket without updating both `categorize.sh` (ingest classifier) and the `hue_to_bucket` function in `process-image.py`.
