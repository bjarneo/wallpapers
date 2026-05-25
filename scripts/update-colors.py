#!/usr/bin/env python3
"""Replace `colors` and recompute `color` (perceived dominant) in wallpapers.json.

Algorithm: the most "salient" color across the top-N palette wins, where
salience = saturation * area_weight. Area_weight decays linearly by rank in
the palette (most-pixels color has weight 1.0, least has ~0.06). This avoids
naive "biggest-area" picking, which lets dark/desaturated backgrounds steal
the tag from the actual figure (e.g. red Naruto on a Nord slate-grey ground).

If no candidate clears MIN_SALIENCE, the image is bucketed as `monochrome`.
"""

import json
import os
import sys

ROOT = "/home/bjarneo/Wallpapers"
JSON_PATH = os.path.join(ROOT, "wallpapers.json")
TOP16_TSV = "/tmp/top16.tsv"

# Tunables
SAT_THRESHOLD = 0.18       # below this in HSL, a single color is treated as grey
MIN_SALIENCE = 0.06        # below this score across all candidates, image is monochrome
TOP_N = 8                  # consider this many of the top colors


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hsl(r, g, b):
    mx, mn = max(r, g, b), min(r, g, b)
    L = (mx + mn) / 2
    d = mx - mn
    if d == 0:
        return 0.0, 0.0, L
    S = d / (2 - mx - mn) if L > 0.5 else d / (mx + mn)
    if mx == r:
        H = (g - b) / d + (6 if g < b else 0)
    elif mx == g:
        H = (b - r) / d + 2
    else:
        H = (r - g) / d + 4
    return H * 60.0, S, L


def hue_to_bucket(H):
    if H < 15 or H >= 345:
        return "red"
    if H < 45:
        return "orange"
    if H < 70:
        return "yellow"
    if H < 160:
        return "green"
    if H < 200:
        return "cyan"
    if H < 250:
        return "blue"
    if H < 290:
        return "purple"
    return "pink"


def classify_palette(colors):
    """Return (bucket, dominant_hex). bucket may be 'monochrome'."""
    if not colors:
        return "monochrome", None

    best_score = 0.0
    best_hex = colors[0]
    best_bucket = "monochrome"

    for rank, hex_ in enumerate(colors[:TOP_N]):
        r, g, b = hex_to_rgb(hex_)
        H, S, _ = rgb_to_hsl(r, g, b)
        if S < SAT_THRESHOLD:
            continue
        # Linear area-weight decay across TOP_N
        area_weight = (TOP_N - rank) / TOP_N
        # Boost saturation a bit so a moderately saturated common color beats
        # a tiny ultra-saturated speck.
        score = (S ** 1.0) * area_weight
        if score > best_score:
            best_score = score
            best_hex = hex_
            best_bucket = hue_to_bucket(H)

    if best_score < MIN_SALIENCE:
        return "monochrome", colors[0]
    return best_bucket, best_hex


def load_top16():
    out = {}
    with open(TOP16_TSV) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                rel, arr = line.split("\t", 1)
            except ValueError:
                continue
            try:
                out[rel] = json.loads(arr)
            except json.JSONDecodeError:
                continue
    return out


def main():
    top16 = load_top16()
    with open(JSON_PATH) as f:
        data = json.load(f)

    missing = 0
    color_changes = 0
    for rel, entry in data.items():
        colors = top16.get(rel)
        if colors is None:
            missing += 1
            # If the manifest already has colors from a prior pass, fall back to those.
            colors = entry.get("colors")
        if colors:
            entry["colors"] = colors
        new_color, _ = classify_palette(colors or [])
        if entry.get("color") != new_color:
            old_color = entry.get("color")
            tags = entry.get("tags", [])
            tags = [new_color if t == old_color else t for t in tags]
            if new_color not in tags:
                tags.append(new_color)
            entry["tags"] = tags
            entry["color"] = new_color
            color_changes += 1

    with open(JSON_PATH, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)

    print(f"Entries: {len(data)}", file=sys.stderr)
    print(f"Missing top16 for: {missing} (used manifest colors as fallback)", file=sys.stderr)
    print(f"Color bucket changes: {color_changes}", file=sys.stderr)


if __name__ == "__main__":
    main()
