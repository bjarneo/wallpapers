#!/usr/bin/env python3
"""Generate per-wallpaper Omarchy theme variants.

For each static wallpaper we emit several colors.toml files. Each variant
uses its reference theme's LIGHTNESS RAMP (slot L*) and CHROMA ENVELOPE
(per-slot C* cap), but pulls HUES from the wallpaper's palette (the
`colors` array in wallpapers.json). Each variant also applies a signature
bias when picking which wallpaper color drives accent and bg tint, so the
outputs feel genuinely different:

    nord variant       cool-biased accent, blue-grey bg, low chroma cap
    gruvbox variant    warm-biased accent, brown-tinted bg, mid chroma cap
    material variant   chroma-maxed accent, deep bg, highest chroma cap
    mono variant       greyscale ramp + single vivid wallpaper-derived accent

ANSI color1..6 keep semantic hue identity (red, green, yellow, blue, magenta,
cyan) via weighted blending against the closest wallpaper hue: a close match
pulls the slot toward the wallpaper; a distant match falls back to the
reference theme's own hue so a blue-only wallpaper still produces a usable
"red" slot.

For light-tone wallpapers the dark reference ramp is mirrored across L*=50,
producing a light variant with dark text.

Output layout:
    themes/<tone>/<color>/<basename>/<scheme>/colors.toml

Each wallpaper sidecar and the merged wallpapers.json gain a `themes` field.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WALLPAPERS_ROOT", "/home/bjarneo/Wallpapers"))
MANIFEST_DIR = ROOT / "cache" / "manifest"
THEMES_DIR = ROOT / "themes"
OUT_JSON = ROOT / "wallpapers.json"

OMARCHY = Path(os.environ.get(
    "OMARCHY_THEMES",
    str(Path.home() / ".local/share/omarchy/themes"),
))

SCHEMES = ("mono", "gruvbox", "nord", "material", "aether")

# Reference colors.toml lookup. Most variants seed from an omarchy theme
# that lives under ~/.local/share/omarchy/themes/<name>/colors.toml.
# `material` and `mono` are project-local because Omarchy doesn't ship
# matching themes - we provide the seeds under scripts/references/.
# `aether` is special: it doesn't seed from a reference at all - we
# shell out to `aether --generate` and copy its colors.toml verbatim.
LOCAL_REFERENCES = {
    "material": Path(__file__).resolve().parent / "references" / "material" / "colors.toml",
    "mono":     Path(__file__).resolve().parent / "references" / "mono"     / "colors.toml",
}
AETHER_SCHEME = "aether"

# Each variant's signature: how to score wallpaper colors for the
# accent/selection-background slot, and the hue (deg) we use to tint
# achromatic slots toward this theme's mood when blending with the
# wallpaper's dominant direction.
#
#   accent_pref   : "warm" | "cool" | "vivid"
#   bg_tint_hue   : LCH hue in degrees (0=red, 60=orange, 90=yellow, 180=cyan,
#                   240=blue, 270=purple, 300=magenta)
#   c_cap         : max chroma allowed across slots (clamps wallpaper vividness)
#   accent_c_cap  : (optional) override c_cap for the accent / selection_background
#                   slots so the accent can stay vivid even when the rest of the
#                   ramp is held to near-grey (mono).
#   ref_blend     : weight of the reference theme's own hue when tinting bg/fg
#                   (the rest is wallpaper-dominant direction)
VARIANT_SIG = {
    # c_cap is the per-variant chroma ceiling. Spreading these apart
    # widens the Mono -> Cool -> Warm -> Material visual gap so each
    # variant feels distinct (Mono near-grey, Cool meaningfully softer,
    # Material the boldest / most saturated).
    "nord":     {"accent_pref": "cool",  "bg_tint_hue": 230.0, "c_cap": 20.0, "ref_blend": 0.55},
    "gruvbox":  {"accent_pref": "warm",  "bg_tint_hue":  40.0, "c_cap": 34.0, "ref_blend": 0.50},
    "material": {"accent_pref": "vivid", "bg_tint_hue": 210.0, "c_cap": 62.0, "ref_blend": 0.40},
    # Mono: low overall chroma keeps every ANSI slot near-grey; the
    # accent slot uses accent_c_cap so the wallpaper's most-saturated
    # color survives as a single, prominent point of color.
    "mono":     {"accent_pref": "vivid", "bg_tint_hue": 240.0, "c_cap":  5.0, "accent_c_cap": 48.0, "ref_blend": 0.55},
}

# Per-variant L* nudges applied on top of the base contrast bump in
# apply_ramp_adjustments. Material pushes toward the high-contrast end
# (darker bg, brighter fg); Cool pulls back so it stays the softest;
# Warm sits in the middle. Mono uses its own deep bg + bright fg so
# the greyscale ramp has the headroom to read crisp.
# Effective bg L per variant after the -5 base push + this nudge:
#   Mono      ref 15 - 5 - 3   = ~7     (deep neutral grey)
#   Warm      ref 16 - 5 - 0   = ~11    (mid-dark)
#   Cool      ref 22 - 5 + 4   = ~21    (lightest dark)
#   Material  ref 14 - 5 - 5   = ~4     (high-contrast, deepest)
VARIANT_BG_NUDGE = {
    "mono":     -3.0,
    "gruvbox":   0.0,
    "nord":     +4.0,
    "material": -5.0,
}
VARIANT_FG_NUDGE = {
    "mono":     +3.0,
    "gruvbox":   0.0,
    "nord":     -4.0,
    "material": +5.0,
}

# Slot families.
BG_KEY = "background"
FG_KEY = "foreground"
CURSOR_KEY = "cursor"
ACCENT_KEY = "accent"
SEL_FG_KEY = "selection_foreground"
SEL_BG_KEY = "selection_background"
COLOR0_KEY = "color0"
DIM_SLOT_KEYS = {f"color{i}" for i in range(1, 8)}
BRIGHT_SLOT_KEYS = {f"color{i}" for i in range(8, 16)}

# Lightness ramp adjustments (LAB L*, 0-100).
# Push backgrounds far from text; lift dim/bright ANSI so wallpaper-tinted
# colors stay legible against the deep background.
BG_L_CAP_DARK = 8.0
BG_L_FLOOR_DARK = 3.0
BG_L_CAP_LIGHT = 98.0
BG_L_FLOOR_LIGHT = 94.0
COLOR0_L_CAP_DARK = 14.0
COLOR0_L_FLOOR_LIGHT = 86.0
DIM_LIFT = 18.0
BRIGHT_LIFT = 22.0
L_CEIL = 92.0
L_FLOOR = 8.0

CHROMA_THRESHOLD_TARGET = 4.0   # reference slot below this is "neutral"
CHROMA_THRESHOLD_PALETTE = 4.0  # wallpaper color below this is "achromatic"
NEUTRAL_TINT_MIN = 3.0          # min chroma tint kept on neutral slots
NEUTRAL_TINT_MAX = 7.0          # max chroma allowed on neutral slots


# --------------------- color space helpers ---------------------

def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


def rgb_to_hex(r: float, g: float, b: float) -> str:
    def clamp(v: float) -> float:
        return max(0.0, min(1.0, v))
    return "#{:02x}{:02x}{:02x}".format(
        int(round(clamp(r) * 255)),
        int(round(clamp(g) * 255)),
        int(round(clamp(b) * 255)),
    )


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055


def _f_lab(t: float) -> float:
    return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0


def _f_lab_inv(t: float) -> float:
    return t ** 3 if t ** 3 > 0.008856 else (t - 16.0 / 116.0) / 7.787


_XN, _YN, _ZN = 0.95047, 1.0, 1.08883


def hex_to_lab(h: str) -> tuple[float, float, float]:
    r, g, b = hex_to_rgb(h)
    r, g, b = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    fx, fy, fz = _f_lab(x / _XN), _f_lab(y / _YN), _f_lab(z / _ZN)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def lab_to_hex(L: float, a: float, b: float) -> str:
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0
    x = _XN * _f_lab_inv(fx)
    y = _YN * _f_lab_inv(fy)
    z = _ZN * _f_lab_inv(fz)
    r = 3.2404542 * x + -1.5371385 * y + -0.4985314 * z
    g = -0.9692660 * x + 1.8760108 * y + 0.0415560 * z
    b2 = 0.0556434 * x + -0.2040259 * y + 1.0572252 * z
    return rgb_to_hex(_linear_to_srgb(r), _linear_to_srgb(g), _linear_to_srgb(b2))


def lab_to_lch(L: float, a: float, b: float) -> tuple[float, float, float]:
    C = math.hypot(a, b)
    h = math.atan2(b, a)
    if h < 0:
        h += 2.0 * math.pi
    return (L, C, h)


def lch_to_hex(L: float, C: float, h: float) -> str:
    return lab_to_hex(L, C * math.cos(h), C * math.sin(h))


# --- Color shade helpers for the expanded colors.toml format -----------
# These mirror the same math previously kept in package-themes.py
# (derive_aether). Promoting them here so the LCH variants can emit the
# full named-shade set Omarchy now expects directly into colors.toml.

def shift_L(hex_: str, delta: float) -> str:
    """Shift a color's L* by `delta`, clamped to [0, 100]."""
    L, a, b = hex_to_lab(hex_)
    return lab_to_hex(max(0.0, min(100.0, L + delta)), a, b)


def desaturate(hex_: str, factor: float) -> str:
    """Scale a color's chroma (a, b channels) by `factor`. <1 desaturates."""
    L, a, b = hex_to_lab(hex_)
    return lab_to_hex(L, a * factor, b * factor)


def blend(h1: str, h2: str, t: float) -> str:
    """Linear blend in Lab: t=0 returns h1, t=1 returns h2."""
    L1, a1, b1 = hex_to_lab(h1)
    L2, a2, b2 = hex_to_lab(h2)
    return lab_to_hex(L1 * (1 - t) + L2 * t, a1 * (1 - t) + a2 * t, b1 * (1 - t) + b2 * t)


def hue_dist(h1: float, h2: float) -> float:
    d = abs(h1 - h2)
    return min(d, 2.0 * math.pi - d)


def hue_blend(h_a: float, w_a: float, h_b: float, w_b: float) -> float:
    """Circular-mean of two hues with weights."""
    x = w_a * math.cos(h_a) + w_b * math.cos(h_b)
    y = w_a * math.sin(h_a) + w_b * math.sin(h_b)
    if x == 0.0 and y == 0.0:
        return h_a
    h = math.atan2(y, x)
    if h < 0:
        h += 2.0 * math.pi
    return h


# --------------------- variant-specific picking ---------------------

def warm_score(h: float) -> float:
    """1.0 at h=red-orange (30deg), 0 around cyan/blue."""
    return max(0.0, math.cos(h - math.radians(30.0)))


def cool_score(h: float) -> float:
    """1.0 at h=blue (240deg), 0 around red/orange."""
    return max(0.0, math.cos(h - math.radians(240.0)))


def pick_accent_palette(palette_lch, pref: str):
    """Pick the wallpaper color that drives accent for this variant."""
    chromatic = [(L, C, h) for (L, C, h) in palette_lch if C >= CHROMA_THRESHOLD_PALETTE]
    if not chromatic:
        return None
    if pref == "warm":
        scored = [(C * (warm_score(h) + 0.15), L, C, h) for (L, C, h) in chromatic]
    elif pref == "cool":
        scored = [(C * (cool_score(h) + 0.15), L, C, h) for (L, C, h) in chromatic]
    else:  # vivid
        # bias slightly toward mid-L so accent isn't a near-black or near-white pixel
        scored = [(C * (1.0 - abs(L - 60.0) / 90.0), L, C, h) for (L, C, h) in chromatic]
    scored.sort(reverse=True)
    return scored[0][1], scored[0][2], scored[0][3]


def palette_dominant_dir(palette_lch) -> tuple[float, float]:
    """Unit (cos h, sin h) of the wallpaper's chroma-weighted mean hue."""
    sa = sb = w = 0.0
    for _L, C, h in palette_lch:
        if C < CHROMA_THRESHOLD_PALETTE:
            continue
        sa += C * math.cos(h)
        sb += C * math.sin(h)
        w += C
    if w == 0.0:
        return (0.0, 0.0)
    a, b = sa / w, sb / w
    mag = math.hypot(a, b)
    if mag == 0.0:
        return (0.0, 0.0)
    return (a / mag, b / mag)


# --------------------- reference scheme parsing ---------------------

KV_RE = re.compile(r'^(?P<key>\w+)\s*=\s*"(?P<val>#[0-9a-fA-F]{6})"\s*$')


def parse_scheme_raw(path: Path) -> list[tuple[str, tuple[float, float, float]]]:
    raw: list[tuple[str, tuple[float, float, float]]] = []
    for line in path.read_text().splitlines():
        m = KV_RE.match(line.strip())
        if m:
            raw.append((m["key"], lab_to_lch(*hex_to_lab(m["val"].lower()))))
    return raw


def apply_ramp_adjustments(slots, tone: str, scheme_name: str = ""):
    """Adjust the reference ramp's L* per slot family.

    Dark mode: a base contrast push (bg darker, fg lighter) on top of
    each variant's reference L. A per-variant nudge then pushes Deep /
    Material further toward the high-contrast end and pulls Cool back,
    widening the visible gap between the variants while keeping their
    relative ordering stable.

    Light mode can't just mirror L (dark themes intentionally use high-L
    ANSI for dark-bg legibility, which mirrors to unusable ultra-dark
    ANSI on light bg). Each slot family is clamped to a band suited to
    light themes, modeled on catppuccin-latte / flexoki-light.
    """
    out: list[tuple[str, tuple[float, float, float]]] = []
    bg_nudge = VARIANT_BG_NUDGE.get(scheme_name, 0.0)
    fg_nudge = VARIANT_FG_NUDGE.get(scheme_name, 0.0)

    if tone != "light":
        # Base push: ~5 L* of contrast added on top of whatever the
        # reference scheme already does. Per-variant nudge stacks on top.
        base_bg = -5.0 + bg_nudge   # bg darker (more negative)
        base_fg = +6.0 + fg_nudge   # fg / cursor / text lighter

        for key, (L, C, h) in slots:
            if key == BG_KEY:
                L = max(0.0, L + base_bg)
            elif key == COLOR0_KEY:
                # color0 sits just above bg; keep that relationship.
                L = max(0.0, L + base_bg + 1.0)
            elif key in (FG_KEY, CURSOR_KEY, SEL_FG_KEY):
                L = min(100.0, L + base_fg)
            elif key == "color7":
                L = min(100.0, L + base_fg - 1.0)
            elif key == "color15":
                L = min(100.0, L + base_fg - 1.0)
            # ANSI 1-6 and 9-14 stay at the reference's mid-L. Pushing
            # them shifts hue appearance more than it helps contrast.
            out.append((key, (L, C, h)))
        return out

    for key, (L, C, h) in slots:
        L_mirror = 100.0 - L
        if key == BG_KEY:
            # Brighter ceiling on light bg, narrower floor: a touch more
            # contrast against dark text.
            L = min(max(L_mirror, 95.0), 99.0)
        elif key == COLOR0_KEY:
            L = min(max(L_mirror, 82.0), 90.0)
        elif key in (FG_KEY, CURSOR_KEY):
            # Push text darker on light bg.
            L = min(max(L_mirror, 14.0), 28.0)
        elif key == SEL_FG_KEY:
            # Tightened from [92, 99] -> [70, 85]: near-white selection
            # text glared against the mid-dark sel_bg (L 35-52). At L 70-85
            # the inversion still reads cleanly (~5:1 contrast min) but
            # without the flashlight effect.
            L = min(max(L_mirror, 70.0), 85.0)
        elif key == SEL_BG_KEY:
            # Tightened from [50, 68] -> [35, 52]: the old band left
            # selection blending into a near-white bg (only ~30 L* of
            # contrast). Mid-dark sel_bg + the existing near-white
            # sel_fg [92, 99] gives a clearly visible highlight band.
            L = min(max(L_mirror, 35.0), 52.0)
        elif key == ACCENT_KEY:
            L = min(max(L_mirror, 36.0), 52.0)
        elif key == "color7":
            L = min(max(L_mirror, 18.0), 34.0)
        elif key == "color15":
            L = min(max(L_mirror, 10.0), 24.0)
        elif key == "color8":
            L = min(max(L_mirror, 60.0), 74.0)
        elif key in DIM_SLOT_KEYS:
            L = min(max(L_mirror, 36.0), 52.0)
        elif key in BRIGHT_SLOT_KEYS:
            L = min(max(L_mirror, 30.0), 48.0)
        out.append((key, (L, C, h)))
    return out


# --------------------- per-slot palette picking ---------------------

def pick_chromatic_match(palette_chromatic, palette_lch, h_target: float):
    """Return the wallpaper color whose hue is closest to h_target.

    Always picks from the wallpaper palette (never falls back to a reference
    hue). If no chromatic colors exist, returns the most chromatic available
    color (so monochrome wallpapers still get a coherent low-chroma palette).
    """
    if palette_chromatic:
        return min(palette_chromatic, key=lambda p: hue_dist(p[2], h_target))
    return max(palette_lch, key=lambda p: p[1])


def pick_dark_palette(palette_lch, rank: int = 0):
    """Pick the n-th darkest palette color (0 = darkest)."""
    s = sorted(palette_lch, key=lambda p: p[0])
    return s[min(rank, len(s) - 1)]


def pick_light_palette(palette_lch, rank: int = 0):
    """Pick the n-th lightest palette color (0 = lightest)."""
    s = sorted(palette_lch, key=lambda p: p[0], reverse=True)
    return s[min(rank, len(s) - 1)]


def pick_mid_palette(palette_lch, target_L: float):
    """Pick the palette color whose L is closest to target_L."""
    return min(palette_lch, key=lambda p: abs(p[0] - target_L))


def emit_slot(L_slot: float, C_ref: float, h_ref: float,
              picked, sig, key: str = "") -> str:
    """Reshade a picked palette color to the slot's lightness, capping chroma
    by the variant's reference C and the variant's overall c_cap.

    Accent / selection_background can opt into a higher ceiling via
    sig["accent_c_cap"] so a low-chroma variant (mono) can still emit a
    vivid accent against an otherwise greyscale ramp.
    """
    L_p, C_p, h_p = picked
    is_accent = key in (ACCENT_KEY, SEL_BG_KEY)
    c_cap = sig.get("accent_c_cap", sig["c_cap"]) if is_accent else sig["c_cap"]
    if C_p < CHROMA_THRESHOLD_PALETTE and C_ref < CHROMA_THRESHOLD_TARGET:
        # both achromatic: keep slight tint via the variant's bg_tint_hue
        bg_tint_rad = math.radians(sig["bg_tint_hue"])
        h_out = h_p if C_p > 0.5 else bg_tint_rad
        C_out = max(NEUTRAL_TINT_MIN * 0.5, min(C_p, NEUTRAL_TINT_MAX * 0.4))
    elif C_ref < CHROMA_THRESHOLD_TARGET:
        # neutral slot but palette color is chromatic: tint slot toward the
        # palette hue. Accent slots use the (higher) accent_c_cap so the
        # wallpaper hue survives full-strength; non-accent neutrals stay
        # tinted within the NEUTRAL band.
        h_out = h_p
        if is_accent:
            C_out = min(C_p, c_cap)
        else:
            C_out = min(C_p, NEUTRAL_TINT_MAX)
            C_out = max(C_out, NEUTRAL_TINT_MIN)
    else:
        # chromatic slot: let palette chroma show, capped by variant's ref C
        h_out = h_p
        C_out = min(C_p, max(C_ref, c_cap * 0.5))
        # don't let it overshoot the variant's overall cap
        C_out = min(C_out, c_cap)
    return lch_to_hex(L_slot, C_out, h_out)


# --------------------- main per-wallpaper generation ---------------------

# Slot-role mapping: tells build_variant how to pick a palette color per slot.
ANSI_SEMANTIC_HUE_DEG = {
    "color1": 25.0,    # red
    "color2": 135.0,   # green
    "color3": 85.0,    # yellow
    "color4": 265.0,   # blue
    "color5": 325.0,   # magenta
    "color6": 195.0,   # cyan
    "color9": 25.0,
    "color10": 135.0,
    "color11": 85.0,
    "color12": 265.0,
    "color13": 325.0,
    "color14": 195.0,
}


def build_variant(scheme_name: str, slots_adjusted, palette_lch, tone: str) -> list[tuple[str, str]]:
    sig = VARIANT_SIG[scheme_name]

    # Variant-aware accent pick: scored against warmth/coolness/chroma so each
    # variant emphasises a different palette color even on the same wallpaper.
    accent_pick_lch = pick_accent_palette(palette_lch, sig["accent_pref"])
    if accent_pick_lch is None:
        accent_pick_lch = pick_light_palette(palette_lch, 0)

    palette_chromatic = [p for p in palette_lch if p[1] >= CHROMA_THRESHOLD_PALETTE]

    # Pre-compute reusable picks
    darkest = pick_dark_palette(palette_lch, 0)
    second_darkest = pick_dark_palette(palette_lch, 1)
    lightest = pick_light_palette(palette_lch, 0)
    second_lightest = pick_light_palette(palette_lch, 1)

    out: list[tuple[str, str]] = []
    for key, (L_slot, C_ref, h_ref) in slots_adjusted:
        if key == BG_KEY:
            picked = darkest
        elif key == COLOR0_KEY:
            picked = second_darkest if second_darkest[0] > darkest[0] + 4 else darkest
        elif key == CURSOR_KEY or key == FG_KEY:
            picked = lightest
        elif key == SEL_FG_KEY:
            picked = lightest if tone == "dark" else darkest
        elif key == "color7":
            picked = second_lightest
        elif key == "color15":
            picked = lightest
        elif key == "color8":
            # mid-dark gray-ish: pick a low-L palette color (between bg and mids)
            picked = pick_mid_palette(palette_lch, 35.0 if tone == "dark" else 70.0)
        elif key in (ACCENT_KEY, SEL_BG_KEY):
            picked = accent_pick_lch
        elif key in ANSI_SEMANTIC_HUE_DEG:
            h_target = math.radians(ANSI_SEMANTIC_HUE_DEG[key])
            picked = pick_chromatic_match(palette_chromatic, palette_lch, h_target)
        else:
            # fallback: use accent
            picked = accent_pick_lch

        hex_v = emit_slot(L_slot, C_ref, h_ref, picked, sig, key)
        out.append((key, hex_v))
    return out


def write_toml(path: Path, slots: list[tuple[str, str]], mode: str = "dark") -> None:
    """Write a colors.toml using Omarchy's expanded format.

    Beyond the basic accent/cursor/foreground/background/selection slots
    and color0-15, this also emits named semantic accents (red, green,
    blue, …, orange, brown) and shade tiers (lighter_bg, dark_bg,
    darker_bg, dark_fg, light_fg, bright_fg, muted, selection). Tools
    that consume colors.toml directly (Omarchy theme switcher, waybar,
    walker, terminal configs) can read these by name rather than
    deriving their own.

    See https://github.com/basecamp/omarchy/pull/4541 for the format spec.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    by_key = dict(slots)

    # Pull the canonical inputs. Fall back to black/white if a slot is
    # missing - shouldn't happen with our generator but keeps writes safe.
    bg  = by_key.get("background", "#000000")
    fg  = by_key.get("foreground", "#ffffff")
    sf  = by_key.get("selection_foreground", bg)
    sb  = by_key.get("selection_background", fg)
    acc = by_key.get("accent", fg)
    cur = by_key.get("cursor", fg)
    c = {f"color{i}": by_key.get(f"color{i}", "#000000") for i in range(16)}

    # Shade tiers derived from bg and fg. shift_L is hue/chroma-preserving
    # so the dark/light variants stay on the same tonal "axis" as their
    # base.
    lighter_bg = shift_L(bg, 8)
    dark_bg    = shift_L(bg, -3)
    darker_bg  = shift_L(bg, -6)
    light_fg   = shift_L(fg, 5)
    bright_fg  = shift_L(fg, 10)
    dark_fg    = shift_L(fg, -15)

    # `muted` lives between fg and bg, biased toward whichever end is
    # darker (the side with lower L*). In dark themes that's bg, so muted
    # leans dim; in light themes that's fg, so muted leans toward text.
    # Then halve chroma so it reads as "dimmed", not just shifted.
    bg_L = hex_to_lab(bg)[0]
    fg_L = hex_to_lab(fg)[0]
    muted_t = 0.65 if bg_L < fg_L else 0.35
    muted = desaturate(blend(fg, bg, muted_t), 0.5)

    # Named accent hues. The ANSI 1-6 slots are already semantic
    # (red/green/yellow/blue/magenta/cyan), so they map directly.
    # Orange and brown aren't in ANSI 8 so we derive them: orange is the
    # midpoint of red+yellow; brown is a dimmed, desaturated yellow.
    red     = c["color1"]
    green   = c["color2"]
    yellow  = c["color3"]
    blue    = c["color4"]
    # Slot was named `purple` in earlier Omarchy schemas. Renamed to
    # `magenta` to align with the ANSI 5/13 semantic and the upstream
    # Omarchy schema (basecamp/omarchy#5856).
    magenta = c["color5"]
    cyan    = c["color6"]
    orange  = blend(red, yellow, 0.5)
    brown   = desaturate(shift_L(yellow, -20), 0.7)

    sections = [
        ("# UI Colors (extended)", [
            ("accent", acc),
            ("cursor", cur),
        ]),
        ("# Primary colors", [
            ("foreground", fg),
            ("background", bg),
        ]),
        ("# Selection colors", [
            ("selection_foreground", sf),
            ("selection_background", sb),
        ]),
        ("# Background shades", [
            ("bg",         bg),
            ("lighter_bg", lighter_bg),
            ("dark_bg",    dark_bg),
            ("darker_bg",  darker_bg),
        ]),
        ("# Foreground shades", [
            ("fg",        fg),
            ("light_fg",  light_fg),
            ("bright_fg", bright_fg),
            ("dark_fg",   dark_fg),
            ("muted",     muted),
            ("selection", sb),
        ]),
        ("# Accent hues", [
            ("red",    red),
            ("green",  green),
            ("yellow", yellow),
            ("blue",   blue),
            ("magenta", magenta),
            ("cyan",   cyan),
            ("orange", orange),
            ("brown",  brown),
        ]),
        ("# Bright hues", [
            ("bright_red",    c["color9"]),
            ("bright_green",  c["color10"]),
            ("bright_yellow", c["color11"]),
            ("bright_blue",   c["color12"]),
            ("bright_magenta", c["color13"]),
            ("bright_cyan",   c["color14"]),
        ]),
        ("# Normal colors (ANSI 0-7)",
         [(f"color{i}", c[f"color{i}"]) for i in range(8)]),
        ("# Bright colors (ANSI 8-15)",
         [(f"color{i}", c[f"color{i}"]) for i in range(8, 16)]),
    ]

    lines: list[str] = [
        "# Generated by omarchy-themes. Semantic names mirror Omarchy's",
        "# theme color system; color0-15 ANSI slots are kept for tools that",
        "# still read them.",
        f'mode = "{mode}"',
    ]
    for comment, pairs in sections:
        lines.append("")
        lines.append(comment)
        for k, v in pairs:
            lines.append(f'{k} = "{v}"')
    path.write_text("\n".join(lines) + "\n")


def load_schemes():
    schemes_raw = {}
    for name in SCHEMES:
        # aether doesn't use the reference-scheme algorithm at all; we
        # invoke the aether CLI per wallpaper and pull its colors.toml
        # straight through. Skip the static reference here.
        if name == AETHER_SCHEME:
            continue
        # Project-local references (e.g. `material`) take precedence so
        # they're not silently shadowed by a same-named user-installed
        # omarchy theme.
        ref = LOCAL_REFERENCES.get(name)
        if ref is None:
            ref = OMARCHY / name / "colors.toml"
        if not ref.is_file():
            print(f"missing reference scheme: {ref}", file=sys.stderr)
            return None
        schemes_raw[name] = parse_scheme_raw(ref)
    return schemes_raw


# Aether CLI - generates a wallpaper-derived colors.toml. We invoke it
# via subprocess per wallpaper. Output goes to a unique tempdir to keep
# parallel workers from clobbering each other.
import shutil
import subprocess
import tempfile


def generate_aether_toml(src: Path, dest_toml: Path, tone: str) -> bool:
    """Run `aether --generate <src> --no-apply --output <tmp>` and copy the
    produced colors.toml to `dest_toml`. Returns True on success.
    """
    if shutil.which("aether") is None:
        return False
    dest_toml.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="aether-", dir="/tmp"))
    try:
        args = ["aether", "--generate", str(src), "--no-apply", "--output", str(tmp)]
        if tone == "light":
            args.append("--light-mode")
        try:
            subprocess.run(args, check=False, capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"aether: failed for {src}: {e}", file=sys.stderr)
            return False
        src_toml = tmp / "colors.toml"
        if not src_toml.is_file():
            return False
        text = src_toml.read_text()
        # Prepend `mode = ...` only when aether's output doesn't already
        # include it. The new aether binary emits the expanded Omarchy
        # format with `mode = "..."` after a two-line comment header, so
        # we scan the first ~20 lines instead of checking only line 0.
        has_mode = any(
            ln.strip().startswith('mode')
            for ln in text.splitlines()[:20]
        )
        if not has_mode:
            text = f'mode = "{tone}"\n\n' + text
        dest_toml.write_text(text)
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def process_entry(rel: str, entry: dict, schemes_raw: dict, aether_only: bool = False) -> int:
    """Write the 3 colors.toml files for one wallpaper entry. Updates the
    entry in-place to set a `themes` field pointing at the on-disk files.
    Returns the number of files written.
    """
    src = ROOT / rel
    if not src.is_file():
        return 0

    colors = entry.get("colors") or []
    tone = entry.get("tone") or ("light" if rel.startswith("light/") else "dark")
    if not colors:
        return 0

    palette_lch: list[tuple[float, float, float]] = []
    for c in colors:
        try:
            palette_lch.append(lab_to_lch(*hex_to_lab(c)))
        except (ValueError, IndexError):
            pass
    if not palette_lch:
        return 0

    key_path = Path(rel)
    base_dir = THEMES_DIR / key_path.parent / key_path.stem
    themes_field: dict = entry.get("themes") if isinstance(entry.get("themes"), dict) else {}

    def record(scheme_name: str, out_path: Path) -> None:
        source_rel = str(out_path.relative_to(ROOT))
        # Preserve enriched fields if package-themes.py has already run;
        # otherwise drop a plain `source` pointer that package-themes uses.
        prev = themes_field.get(scheme_name)
        if isinstance(prev, dict):
            prev["source"] = source_rel
            themes_field[scheme_name] = prev
        else:
            themes_field[scheme_name] = {"source": source_rel, "scheme": scheme_name}

    n = 0
    if not aether_only:
        for scheme_name, raw_slots in schemes_raw.items():
            adjusted = apply_ramp_adjustments(raw_slots, tone, scheme_name)
            remapped = build_variant(scheme_name, adjusted, palette_lch, tone)
            out_path = base_dir / scheme_name / "colors.toml"
            write_toml(out_path, remapped, mode=tone)
            record(scheme_name, out_path)
            n += 1

    # aether is special: shell out to the Aether CLI rather than using
    # the LCH-remap algorithm. Its output ships verbatim (just prefixed
    # with the mode line) as the 5th variant.
    aether_path = base_dir / AETHER_SCHEME / "colors.toml"
    if generate_aether_toml(src, aether_path, tone):
        record(AETHER_SCHEME, aether_path)
        n += 1

    entry["themes"] = themes_field
    return n


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Process only this wallpaper (rel path or absolute)")
    ap.add_argument("--aether-only", action="store_true",
                    help="Skip the LCH-remap variants; only regenerate the aether colors.toml")
    args = ap.parse_args()

    if not MANIFEST_DIR.is_dir():
        print(f"no manifest dir at {MANIFEST_DIR}", file=sys.stderr)
        return 1

    schemes_raw = load_schemes()
    if schemes_raw is None:
        return 1

    if args.only:
        p = Path(args.only)
        try:
            rel = str(p.resolve().relative_to(ROOT)) if p.is_absolute() else str(p)
        except ValueError:
            print(f"--only path not under {ROOT}: {args.only}", file=sys.stderr)
            return 2
        sidecar = MANIFEST_DIR / (Path(rel).with_suffix(".json"))
        if not sidecar.is_file():
            print(f"no sidecar for {rel}", file=sys.stderr)
            return 2
        try:
            obj = json.loads(sidecar.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"bad sidecar {sidecar}: {e}", file=sys.stderr)
            return 1
        if not isinstance(obj, dict) or rel not in obj:
            print(f"sidecar {sidecar} has no entry for {rel}", file=sys.stderr)
            return 2
        n = process_entry(rel, obj[rel], schemes_raw, aether_only=args.aether_only)
        sidecar.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")
        print(f"[--only {rel}] wrote {n} colors.toml files", file=sys.stderr)
        return 0

    n_files = 0
    n_entries = 0
    for sidecar in sorted(MANIFEST_DIR.rglob("*.json")):
        try:
            obj = json.loads(sidecar.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(obj, dict):
            continue
        changed = False
        for rel, entry in obj.items():
            if not isinstance(entry, dict):
                continue
            written = process_entry(rel, entry, schemes_raw, aether_only=args.aether_only)
            if written > 0:
                n_files += written
                n_entries += 1
                changed = True
        if changed:
            sidecar.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")

    print(f"wrote {n_files} colors.toml files across {n_entries} wallpapers", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
