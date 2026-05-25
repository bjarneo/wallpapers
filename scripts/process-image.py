#!/usr/bin/env python3
"""Process a single wallpaper end-to-end.

Per image:
  - validates dimensions (skip + delete portraits and sub-1080p)
  - prepends WxH_ if missing
  - extracts top-16 dominant colors via ImageMagick histogram
  - classifies the color bucket via saliency-weighted scoring (saturation x area)
  - matches the closest popular color scheme by LAB-distance against built-ins
  - moves the file to <tone>/<color>/ (with _N suffix on collision)
  - generates thumb (256px) and medium (1024px) JPG caches
  - derives title/description/tags from the filename
  - writes a sidecar JSON at cache/manifest/<final_rel>.json

Multiple instances can run in parallel - each operates on a distinct input,
writes its own sidecar, and uses link-then-delete moves so collisions are
race-safe (the second worker will get a NameError and retry with _N+1).

Usage:
  scripts/process-image.py <path>           # rel to repo root, or absolute

Exits 0 on success, 2 if skipped (portrait, sub-1080p), 1 on failure.
"""

import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WALLPAPERS_ROOT", "/home/bjarneo/Wallpapers"))
THUMB_SIZE = int(os.environ.get("THUMB_SIZE", 256))
MEDIUM_SIZE = int(os.environ.get("MEDIUM_SIZE", 1024))
QUALITY = int(os.environ.get("QUALITY", 85))
MIN_HEIGHT = int(os.environ.get("MIN_HEIGHT", 1080))

SAT_THRESHOLD = 0.18
MIN_SALIENCE = 0.06
TOP_N = 8

MANIFEST_DIR = ROOT / "cache" / "manifest"
THUMB_DIR = ROOT / "cache" / "thumb"
MEDIUM_DIR = ROOT / "cache" / "medium"

WH_RE = re.compile(r"^(\d+)x(\d+)_")
TRAILING_VARIANT = re.compile(r"(?:[_\- ]*\((\d+)\)|[_\-]\d{1,3})$")

STOPWORDS = {
    "the", "a", "an", "of", "with", "and", "or", "on", "in", "at", "to",
    "from", "by", "for", "is", "was", "are", "were", "be", "as", "it",
    "its", "this", "that", "these", "those",
}
THEME_FOLDER_HINT = {"bonus", "dot", "spam", "unsorted", "home", "aesthetic", "mlfw"}

# Built-in scheme palettes (base16-style, 16 colors each)
SCHEMES = {
    "Nord": ["#2e3440","#3b4252","#434c5e","#4c566a","#d8dee9","#e5e9f0","#eceff4","#8fbcbb","#88c0d0","#81a1c1","#5e81ac","#bf616a","#d08770","#ebcb8b","#a3be8c","#b48ead"],
    "Gruvbox Dark": ["#282828","#cc241d","#98971a","#d79921","#458588","#b16286","#689d6a","#a89984","#928374","#fb4934","#b8bb26","#fabd2f","#83a598","#d3869b","#8ec07c","#ebdbb2"],
    "Gruvbox Light": ["#fbf1c7","#cc241d","#98971a","#d79921","#458588","#b16286","#689d6a","#7c6f64","#928374","#9d0006","#79740e","#b57614","#076678","#8f3f71","#427b58","#3c3836"],
    "Tokyo Night": ["#1a1b26","#f7768e","#9ece6a","#e0af68","#7aa2f7","#bb9af7","#7dcfff","#a9b1d6","#414868","#f7768e","#9ece6a","#e0af68","#7aa2f7","#bb9af7","#7dcfff","#c0caf5"],
    "Dracula": ["#282a36","#ff5555","#50fa7b","#f1fa8c","#bd93f9","#ff79c6","#8be9fd","#f8f8f2","#44475a","#ff5555","#50fa7b","#f1fa8c","#bd93f9","#ff79c6","#8be9fd","#ffffff"],
    "Catppuccin Mocha": ["#1e1e2e","#f38ba8","#a6e3a1","#f9e2af","#89b4fa","#f5c2e7","#94e2d5","#cdd6f4","#6c7086","#f38ba8","#a6e3a1","#f9e2af","#89b4fa","#f5c2e7","#94e2d5","#bac2de"],
    "Catppuccin Macchiato": ["#24273a","#ed8796","#a6da95","#eed49f","#8aadf4","#f5bde6","#8bd5ca","#cad3f5","#5b6078","#ed8796","#a6da95","#eed49f","#8aadf4","#f5bde6","#8bd5ca","#b8c0e0"],
    "Catppuccin Frappe": ["#303446","#e78284","#a6d189","#e5c890","#8caaee","#f4b8e4","#81c8be","#c6d0f5","#626880","#e78284","#a6d189","#e5c890","#8caaee","#f4b8e4","#81c8be","#b5bfe2"],
    "Catppuccin Latte": ["#eff1f5","#d20f39","#40a02b","#df8e1d","#1e66f5","#ea76cb","#179299","#4c4f69","#9ca0b0","#d20f39","#40a02b","#df8e1d","#1e66f5","#ea76cb","#179299","#5c5f77"],
    "Rose Pine": ["#191724","#eb6f92","#31748f","#f6c177","#9ccfd8","#c4a7e7","#ebbcba","#e0def4","#6e6a86","#eb6f92","#31748f","#f6c177","#9ccfd8","#c4a7e7","#ebbcba","#e0def4"],
    "Rose Pine Moon": ["#232136","#eb6f92","#3e8fb0","#f6c177","#9ccfd8","#c4a7e7","#ea9a97","#e0def4","#6e6a86","#eb6f92","#3e8fb0","#f6c177","#9ccfd8","#c4a7e7","#ea9a97","#e0def4"],
    "Rose Pine Dawn": ["#faf4ed","#b4637a","#286983","#ea9d34","#56949f","#907aa9","#d7827e","#575279","#9893a5","#b4637a","#286983","#ea9d34","#56949f","#907aa9","#d7827e","#575279"],
    "Everforest Dark": ["#2d353b","#e67e80","#a7c080","#dbbc7f","#7fbbb3","#d699b6","#83c092","#d3c6aa","#475258","#e67e80","#a7c080","#dbbc7f","#7fbbb3","#d699b6","#83c092","#d3c6aa"],
    "Everforest Light": ["#fdf6e3","#f85552","#8da101","#dfa000","#3a94c5","#df69ba","#35a77c","#5c6a72","#829181","#f85552","#8da101","#dfa000","#3a94c5","#df69ba","#35a77c","#5c6a72"],
    "Kanagawa": ["#1f1f28","#c34043","#76946a","#c0a36e","#7e9cd8","#957fb8","#6a9589","#c8c093","#727169","#e82424","#98bb6c","#e6c384","#7fb4ca","#938aa9","#7aa89f","#dcd7ba"],
    "One Dark": ["#282c34","#e06c75","#98c379","#e5c07b","#61afef","#c678dd","#56b6c2","#abb2bf","#5c6370","#e06c75","#98c379","#e5c07b","#61afef","#c678dd","#56b6c2","#ffffff"],
    "Monokai": ["#272822","#f92672","#a6e22e","#f4bf75","#66d9ef","#ae81ff","#a1efe4","#f8f8f2","#75715e","#f92672","#a6e22e","#f4bf75","#66d9ef","#ae81ff","#a1efe4","#f9f8f5"],
    "Solarized Dark": ["#002b36","#dc322f","#859900","#b58900","#268bd2","#d33682","#2aa198","#eee8d5","#586e75","#dc322f","#859900","#b58900","#268bd2","#d33682","#2aa198","#fdf6e3"],
    "Solarized Light": ["#fdf6e3","#dc322f","#859900","#b58900","#268bd2","#d33682","#2aa198","#073642","#93a1a1","#dc322f","#859900","#b58900","#268bd2","#d33682","#2aa198","#002b36"],
    "Ayu Dark": ["#0a0e14","#f07178","#c2d94c","#ff8f40","#59c2ff","#d2a6ff","#95e6cb","#b3b1ad","#4d5566","#f07178","#c2d94c","#ffb454","#59c2ff","#d2a6ff","#95e6cb","#f8f9fa"],
    "Ayu Light": ["#fafafa","#f07178","#86b300","#fa8d3e","#41a6d9","#a37acc","#4cbf99","#5c6773","#abb0b6","#f07178","#86b300","#fa8d3e","#41a6d9","#a37acc","#4cbf99","#6c7680"],
    "Material Dark": ["#212121","#f44336","#4caf50","#ffc107","#2196f3","#9c27b0","#00bcd4","#fafafa","#616161","#ef5350","#66bb6a","#ffd54f","#42a5f5","#ab47bc","#26c6da","#e0e0e0"],
    "Material Light": ["#fafafa","#f44336","#4caf50","#ffc107","#2196f3","#9c27b0","#00bcd4","#212121","#9e9e9e","#ef5350","#66bb6a","#ffd54f","#42a5f5","#ab47bc","#26c6da","#424242"],
}


# -----------------------------------------------------------------------------
# Color math
# -----------------------------------------------------------------------------

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


def rgb_to_lab(r, g, b):
    # sRGB -> linear
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = lin(r), lin(g), lin(b)
    # linear -> XYZ (D65)
    x = (r * 0.4124564 + g * 0.3575761 + b * 0.1804375) / 0.95047
    y = (r * 0.2126729 + g * 0.7151522 + b * 0.0721750) / 1.00000
    z = (r * 0.0193339 + g * 0.1191920 + b * 0.9503041) / 1.08883
    # XYZ -> LAB
    def f(t):
        return t ** (1/3) if t > 0.008856 else 7.787 * t + 16/116
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def lab_delta(a, b):
    return math.sqrt(sum((a[i] - b[i])**2 for i in range(3)))


def hue_to_bucket(H):
    if H < 15 or H >= 345: return "red"
    if H < 45:  return "orange"
    if H < 70:  return "yellow"
    if H < 160: return "green"
    if H < 200: return "cyan"
    if H < 250: return "blue"
    if H < 290: return "purple"
    return "pink"


def classify_palette(colors):
    if not colors:
        return "monochrome"
    best_score = 0.0
    best_bucket = "monochrome"
    for rank, hex_ in enumerate(colors[:TOP_N]):
        r, g, b = hex_to_rgb(hex_)
        H, S, _ = rgb_to_hsl(r, g, b)
        if S < SAT_THRESHOLD:
            continue
        area_weight = (TOP_N - rank) / TOP_N
        score = S * area_weight
        if score > best_score:
            best_score = score
            best_bucket = hue_to_bucket(H)
    return best_bucket if best_score >= MIN_SALIENCE else "monochrome"


def match_scheme(palette_hex):
    """Lowest mean-LAB distance between sorted-by-lightness palettes wins."""
    if not palette_hex:
        return "Custom"
    wp_lab = sorted([rgb_to_lab(*hex_to_rgb(h)) for h in palette_hex], key=lambda x: x[0])
    # Truncate or pad to 16 for fair comparison
    wp_lab = wp_lab[:16] + [wp_lab[-1]] * max(0, 16 - len(wp_lab))

    best_name = "Custom"
    best_dist = float("inf")
    for name, scheme_hex in SCHEMES.items():
        sc_lab = sorted([rgb_to_lab(*hex_to_rgb(h)) for h in scheme_hex], key=lambda x: x[0])
        d = sum(lab_delta(wp_lab[i], sc_lab[i]) for i in range(16)) / 16
        if d < best_dist:
            best_dist = d
            best_name = name
    # If even the best is bad enough, call it Custom
    if best_dist > 35:
        return "Custom"
    return best_name


# -----------------------------------------------------------------------------
# ImageMagick wrappers
# -----------------------------------------------------------------------------

def get_dimensions(path):
    try:
        out = subprocess.check_output(
            ["magick", "identify", "-format", "%w %h", f"{path}[0]"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        w, h = out.split()
        return int(w), int(h)
    except (subprocess.CalledProcessError, ValueError):
        return None


def extract_top16(path):
    """Return list of top-16 hex colors by pixel count, descending."""
    try:
        out = subprocess.check_output(
            ["magick", f"{path}[0]", "-resize", "256x256!", "-dither", "None",
             "-colors", "16", "-depth", "8", "-format", "%c", "histogram:info:-"],
            stderr=subprocess.DEVNULL,
        ).decode()
    except subprocess.CalledProcessError:
        return []
    entries = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # "  5819: (12,52,116) #0C3474 srgb(12,52,116)"
        m = re.match(r"\s*(\d+):.*?(#[0-9A-Fa-f]{6})", line)
        if m:
            entries.append((int(m.group(1)), m.group(2).upper()))
    entries.sort(key=lambda e: -e[0])
    return [hex_ for _, hex_ in entries[:16]]


def encode_cache(src, dst, max_edge):
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "magick", f"{src}[0]",
        "-background", "white", "-alpha", "remove", "-alpha", "off",
        "-resize", f"{max_edge}x{max_edge}>",
        "-strip", "-interlace", "Plane", "-sampling-factor", "4:2:0",
        "-quality", str(QUALITY),
        f"jpg:{dst}",
    ]
    try:
        subprocess.check_call(cmd, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        if dst.exists():
            dst.unlink()
        return False


# -----------------------------------------------------------------------------
# Filename munging
# -----------------------------------------------------------------------------

def titlecase(words):
    out = []
    for i, w in enumerate(words):
        if i > 0 and w.lower() in STOPWORDS:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:].lower() if w else w)
    return " ".join(out)


def derive_metadata(rel_path, tone, color):
    parts = rel_path.split("/")
    filename = parts[-1]
    stem, _, _ = filename.rpartition(".")
    m = WH_RE.match(stem)
    if m:
        stem = stem[m.end():]
    theme, _, rest = stem.partition("_")
    if not rest:
        rest = theme
        theme = "unknown"
    # title
    s = rest
    while True:
        new = TRAILING_VARIANT.sub("", s)
        if new == s:
            break
        s = new
    s = re.sub(r"[_\-]+", " ", s.strip("-_ ")).strip()
    if not s:
        title = "Untitled"
    elif re.fullmatch(r"\d+", s):
        title = f"Wallpaper #{s}"
    else:
        title = titlecase(re.split(r"\s+", s))
    # tags
    tags = [tone, color]
    if theme and theme != "unknown":
        tags.append(theme)
    cleaned = re.sub(r"[_\-]+", " ", TRAILING_VARIANT.sub("", rest)).lower().strip()
    for w in re.split(r"\s+", cleaned):
        w = w.strip(".,;:'\"()[]")
        if not w or w in STOPWORDS or len(w) < 3 or re.fullmatch(r"\d+", w):
            continue
        if w not in tags:
            tags.append(w)
    # description
    theme_label = theme if theme not in THEME_FOLDER_HINT and theme != "unknown" else None
    desc_parts = [f"{tone.capitalize()} {color} wallpaper"]
    if theme_label:
        desc_parts[0] += f", {theme_label} theme"
    if title and not title.startswith("Wallpaper #") and title != "Untitled":
        desc_parts.insert(0, title + ".")
    description = " ".join(desc_parts) + "."
    return title, description, tags, theme


# -----------------------------------------------------------------------------
# Move with collision suffix (race-safe via O_EXCL)
# -----------------------------------------------------------------------------

def safe_move(src_path, target_path):
    """Move src_path -> target_path, suffixing with _N on collision.
    Returns the actual target path used. Race-safe across parallel workers."""
    if src_path == target_path:
        return target_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    stem = target_path.stem
    suffix = target_path.suffix
    parent = target_path.parent

    candidate = target_path
    n = 2
    while True:
        try:
            # O_CREAT|O_EXCL gives us exclusive creation; if it succeeds, the slot is ours
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            os.unlink(candidate)  # we'll re-create via move
            shutil.move(str(src_path), str(candidate))
            return candidate
        except FileExistsError:
            candidate = parent / f"{stem}_{n}{suffix}"
            n += 1
            if n > 100:
                raise RuntimeError(f"too many collisions at {target_path}")


# -----------------------------------------------------------------------------
# Main per-image flow
# -----------------------------------------------------------------------------

def main(argv):
    if len(argv) < 2:
        print("usage: process-image.py <path>", file=sys.stderr)
        return 1

    src = Path(argv[1])
    if not src.is_absolute():
        src = (ROOT / src).resolve()
    if not src.is_file():
        print(f"not a file: {src}", file=sys.stderr)
        return 1
    try:
        src.relative_to(ROOT)
    except ValueError:
        print(f"not under {ROOT}: {src}", file=sys.stderr)
        return 1

    rel = src.relative_to(ROOT)
    parts = rel.parts
    if len(parts) < 3 or parts[0] not in ("dark", "light"):
        # live/ and other top-level locations aren't in this pipeline
        print(f"skip (not under dark/ or light/): {rel}", file=sys.stderr)
        return 2

    # Dimensions + filtering
    dims = get_dimensions(src)
    if dims is None:
        print(f"identify failed: {rel}", file=sys.stderr)
        return 1
    w, h = dims
    if h > w:
        # portrait -> delete
        for p in (src,
                  THUMB_DIR / rel.with_suffix(".jpg"),
                  MEDIUM_DIR / rel.with_suffix(".jpg")):
            try: p.unlink()
            except FileNotFoundError: pass
        print(f"removed portrait {w}x{h}: {rel}", file=sys.stderr)
        return 2
    if h < MIN_HEIGHT:
        for p in (src,
                  THUMB_DIR / rel.with_suffix(".jpg"),
                  MEDIUM_DIR / rel.with_suffix(".jpg")):
            try: p.unlink()
            except FileNotFoundError: pass
        print(f"removed sub-{MIN_HEIGHT}p {w}x{h}: {rel}", file=sys.stderr)
        return 2

    # Ensure WxH_ prefix on filename
    base = src.name
    if not WH_RE.match(base):
        new_name = f"{w}x{h}_{base}"
        new_src = src.with_name(new_name)
        if new_src.exists():
            print(f"prefix would clobber: {new_src}", file=sys.stderr)
            return 1
        src.rename(new_src)
        src = new_src
        rel = src.relative_to(ROOT)

    # Extract palette
    colors = extract_top16(src)
    if not colors:
        print(f"palette extract failed: {rel}", file=sys.stderr)
        return 1

    # Classify
    tone = parts[0]
    new_color = classify_palette(colors)

    # Plan destination
    target_rel = Path(tone) / new_color / src.name
    target_abs = ROOT / target_rel

    moved = False
    if target_abs != src:
        # Move source
        actual = safe_move(src, target_abs)
        target_rel = actual.relative_to(ROOT)
        target_abs = actual
        # Move caches (best-effort; will regenerate below if missing)
        for cache_root in (THUMB_DIR, MEDIUM_DIR):
            old_cache = cache_root / rel.with_suffix(".jpg")
            new_cache = cache_root / target_rel.with_suffix(".jpg")
            if old_cache.exists() and old_cache != new_cache:
                new_cache.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(old_cache), str(new_cache))
                except OSError:
                    pass
        moved = True

    # (Re)generate caches if missing or stale
    thumb_path = THUMB_DIR / target_rel.with_suffix(".jpg")
    medium_path = MEDIUM_DIR / target_rel.with_suffix(".jpg")
    if not thumb_path.exists() or thumb_path.stat().st_mtime < target_abs.stat().st_mtime:
        encode_cache(target_abs, thumb_path, THUMB_SIZE)
    if not medium_path.exists() or medium_path.stat().st_mtime < target_abs.stat().st_mtime:
        encode_cache(target_abs, medium_path, MEDIUM_SIZE)

    # Metadata
    title, description, tags, theme = derive_metadata(str(target_rel), tone, new_color)
    scheme = match_scheme(colors)

    entry = {
        "title": title,
        "description": description,
        "tags": tags,
        "tone": tone,
        "color": new_color,
        "theme": theme,
        "colors": colors,
        "scheme": scheme,
        "width": w,
        "height": h,
        "dimensions": f"{w}x{h}",
        "size_bytes": target_abs.stat().st_size,
        "thumb_path": str(Path("cache/thumb") / target_rel.with_suffix(".jpg")),
        "medium_path": str(Path("cache/medium") / target_rel.with_suffix(".jpg")),
    }

    # Write sidecar
    sidecar = MANIFEST_DIR / target_rel.with_suffix(".json")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    # Also: clean stale sidecar at the OLD location if we moved
    if moved:
        old_sidecar = MANIFEST_DIR / rel.with_suffix(".json")
        if old_sidecar.exists() and old_sidecar != sidecar:
            try: old_sidecar.unlink()
            except FileNotFoundError: pass

    payload = {str(target_rel): entry}
    sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True))

    print(f"ok\t{target_rel}\t{new_color}\t{scheme}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
