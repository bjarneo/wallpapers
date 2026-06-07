#!/usr/bin/env python3
"""Publish wallpapers.json to the omarchy-themes site.

The Omarchy Themes site is wallpaper-keyed: one card per wallpaper, with
the variants (palette, gruvbox, nord, material, aether) surfaced inside
the lightbox. That schema is identical to the wallpaper-keyed manifest
the Wallpapers repo already produces, so we just propagate it forward.

Reads:  /home/bjarneo/Wallpapers/wallpapers.json (built by merge-sidecars.py)
Writes: ~/Code/omarchy-themes/wallpapers.json

The site doesn't need every field the Wallpapers gallery uses (e.g. raw
size_bytes, description text). Stripping a handful of large-and-unused
fields keeps the served manifest a bit smaller without changing the data
shape the site reads.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WALLPAPERS_ROOT", "/home/bjarneo/Wallpapers"))
SRC = ROOT / "wallpapers.json"
OUT = Path(os.environ.get(
    "OMARCHY_THEMES_OUT",
    str(Path.home() / "Code/omarchy-themes"),
)) / "wallpapers.json"

# Fields kept on each wallpaper entry. Everything else (description,
# size_bytes, llm_captioned, etc.) is dropped — the site doesn't render
# them and stripping shrinks the manifest the page has to download.
KEEP_FIELDS = {
    "title", "tags", "tone", "color", "theme", "scheme",
    "width", "height", "dimensions",
    "thumb_path", "medium_path",
    "colors",   # the wallpaper's own palette (array of hex strings)
    "themes",   # dict of <scheme> -> per-variant metadata (incl. parsed colors)
}


def slim(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k in KEEP_FIELDS}


def main() -> int:
    if not SRC.is_file():
        print(f"missing source manifest: {SRC}", file=sys.stderr)
        return 1
    try:
        data = json.loads(SRC.read_text())
    except json.JSONDecodeError as e:
        print(f"bad JSON in {SRC}: {e}", file=sys.stderr)
        return 1

    out: dict[str, dict] = {}
    skipped = 0
    for rel, entry in data.items():
        if not isinstance(entry, dict):
            skipped += 1
            continue
        # Only include wallpapers that actually have packaged themes.
        if not entry.get("themes"):
            skipped += 1
            continue
        out[rel] = slim(entry)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(out)} wallpaper entries -> {OUT}", file=sys.stderr)
    if skipped:
        print(f"skipped {skipped} entries with no themes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
