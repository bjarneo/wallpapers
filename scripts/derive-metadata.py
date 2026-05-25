#!/usr/bin/env python3
"""Derive title/description/tags for each wallpaper from its path + filename."""

import os
import re
import sys
import json

ROOT = "/home/bjarneo/Wallpapers"

STOPWORDS = {
    "the", "a", "an", "of", "with", "and", "or", "on", "in", "at", "to",
    "from", "by", "for", "is", "was", "are", "were", "be", "as", "it",
    "its", "this", "that", "these", "those",
}

# Themes that are clearly source-folder labels, not content tags.
THEME_FOLDER_HINT = {
    "bonus", "dot", "spam", "unsorted", "home",
    "aesthetic", "mlfw",
}

# Strip trailing numeric variants like "_01", "_02", " (1)"
TRAILING_VARIANT = re.compile(r"(?:[_\- ]*\((\d+)\)|[_\-]\d{1,3})$")


def titlecase(words):
    out = []
    for i, w in enumerate(words):
        if i > 0 and w.lower() in STOPWORDS:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:].lower() if w else w)
    return " ".join(out)


def parse_path(relpath):
    """Return (tone, color, theme, raw_stem, ext)."""
    parts = relpath.split("/")
    if len(parts) < 3:
        return None
    tone, color = parts[0], parts[1]
    filename = parts[-1]
    stem, _, ext = filename.rpartition(".")
    # strip "WxH_" prefix
    m = re.match(r"^\d+x\d+_(.+)$", stem)
    if m:
        stem = m.group(1)
    # first underscore segment is theme prefix
    theme, _, rest = stem.partition("_")
    if not rest:
        rest = theme
        theme = "unknown"
    return tone, color, theme, rest, ext.lower()


def make_title(rest):
    # Drop trailing variant marker(s) iteratively (e.g. "_02", " (1)").
    s = rest
    while True:
        new = TRAILING_VARIANT.sub("", s)
        if new == s:
            break
        s = new
    s = s.strip("-_ ")
    # Replace separators
    s = re.sub(r"[_\-]+", " ", s).strip()
    if not s:
        return "Untitled"
    if re.fullmatch(r"\d+", s):
        return f"Wallpaper #{s}"
    # Sentence-ish title case
    words = re.split(r"\s+", s)
    return titlecase(words)


def make_tags(theme, tone, color, rest):
    tags = [tone, color]
    if theme and theme != "unknown":
        tags.append(theme)
    # Keyword extraction from rest
    cleaned = re.sub(r"[_\-]+", " ", rest).lower()
    cleaned = TRAILING_VARIANT.sub("", cleaned).strip()
    for w in re.split(r"\s+", cleaned):
        w = w.strip(".,;:'\"()[]")
        if not w or w in STOPWORDS:
            continue
        if len(w) < 3:
            continue
        if re.fullmatch(r"\d+", w):
            continue
        if w not in tags:
            tags.append(w)
    return tags


def make_description(title, tone, color, theme):
    theme_label = theme if theme not in THEME_FOLDER_HINT and theme != "unknown" else None
    parts = [f"{tone.capitalize()} {color} wallpaper"]
    if theme_label:
        parts[0] += f", {theme_label} theme"
    if title and not title.startswith("Wallpaper #") and title != "Untitled":
        parts.insert(0, title + ".")
    return " ".join(parts) + "."


def main():
    out = {}
    for tone in ("dark", "light"):
        tone_dir = os.path.join(ROOT, tone)
        if not os.path.isdir(tone_dir):
            continue
        for color in sorted(os.listdir(tone_dir)):
            color_dir = os.path.join(tone_dir, color)
            if not os.path.isdir(color_dir):
                continue
            for fn in sorted(os.listdir(color_dir)):
                if not fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    continue
                relpath = f"{tone}/{color}/{fn}"
                parsed = parse_path(relpath)
                if not parsed:
                    continue
                t, c, theme, rest, ext = parsed
                title = make_title(rest)
                tags = make_tags(theme, t, c, rest)
                desc = make_description(title, t, c, theme)
                out[relpath] = {
                    "title": title,
                    "description": desc,
                    "tags": tags,
                    "tone": t,
                    "color": c,
                    "theme": theme,
                }
    json.dump(out, sys.stdout, indent=None, separators=(",", ":"))


if __name__ == "__main__":
    main()
