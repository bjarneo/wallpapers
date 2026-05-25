#!/usr/bin/env python3
"""Merge palette + metadata + scheme into /home/bjarneo/Wallpapers/wallpapers.json."""

import json
import sys

import os

PALETTES = os.environ.get("PALETTES", "/tmp/top16.tsv")
METADATA = os.environ.get("METADATA", "/tmp/metadata.json")
SCHEMES = os.environ.get("SCHEMES", "/tmp/schemes.tsv")
OUT = os.environ.get("OUT", "/home/bjarneo/Wallpapers/wallpapers.json")


def load_tsv_two(path):
    out = {}
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                a, b = line.split("\t", 1)
            except ValueError:
                continue
            out[a] = b
    return out


def main():
    palettes_raw = load_tsv_two(PALETTES)
    schemes_raw = load_tsv_two(SCHEMES)
    with open(METADATA) as f:
        meta = json.load(f)

    palettes = {k: json.loads(v) for k, v in palettes_raw.items()}

    merged = {}
    missing_palette = 0
    missing_scheme = 0

    for rel, m in sorted(meta.items()):
        colors = palettes.get(rel)
        scheme = schemes_raw.get(rel)
        if colors is None:
            missing_palette += 1
        if scheme is None:
            missing_scheme += 1
        merged[rel] = {
            "title": m["title"],
            "description": m["description"],
            "tags": m["tags"],
            "tone": m["tone"],
            "color": m["color"],
            "theme": m["theme"],
            "colors": colors or [],
            "scheme": scheme or "Custom",
        }

    with open(OUT, "w") as f:
        json.dump(merged, f, indent=2, sort_keys=True)

    print(f"Wrote {len(merged)} entries to {OUT}", file=sys.stderr)
    if missing_palette:
        print(f"  missing palette: {missing_palette}", file=sys.stderr)
    if missing_scheme:
        print(f"  missing scheme:  {missing_scheme}", file=sys.stderr)


if __name__ == "__main__":
    main()
