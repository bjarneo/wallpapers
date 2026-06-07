#!/usr/bin/env python3
"""Package per-wallpaper theme variants into ~/Code/omarchy-themes.

For every wallpaper entry we emit one standalone Omarchy theme directory per
scheme:

    ~/Code/omarchy-themes/<basename>-<short>/
        colors.toml                       (verbatim from themes/.../colors.toml)
        neovim.lua                        (rendered Aether template)
        backgrounds/01-<basename>.<ext>   (symlink to source wallpaper)

`<short>` is `mono`, `warm`, `cool`, `material` or `aether`. After packaging
we update each sidecar's `themes` field to a rich metadata dict the site
(and the omarchy theme browser) can read directly:

    "themes": {
      "mono": {
        "name": "glass-sphere-mono",
        "scheme": "mono",
        "path": "omarchy-themes/glass-sphere-mono",
        "colors_toml":  "omarchy-themes/glass-sphere-mono/colors.toml",
        "neovim_lua":   "omarchy-themes/glass-sphere-mono/neovim.lua",
        "background":   "omarchy-themes/glass-sphere-mono/backgrounds/01-glass-sphere.jpg",
        "colors": { "background": "#...", ..., "color0": "#...", ... }
      },
      ...
    }

Paths are repo-relative — index.html prefixes them with WALLPAPERS_BASE_URL
so they resolve to the Hetzner-hosted files.

Modes:
    package-themes.py                 # bulk: every wallpaper in wallpapers.json
    package-themes.py --only PATH     # single wallpaper (rel path or absolute);
                                      # reads + writes only that one sidecar
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WALLPAPERS_ROOT", "/home/bjarneo/Wallpapers"))
MANIFEST_DIR = ROOT / "cache" / "manifest"
TARGET = Path(os.environ.get(
    "OMARCHY_THEMES_OUT",
    str(Path.home() / "Code/omarchy-themes"),
))
TEMPLATE = Path(os.environ.get(
    "AETHER_TEMPLATE",
    str(Path.home() / "Code/Aether/templates/neovim.lua"),
))
OMARCHY_THEMES = Path(os.environ.get(
    "OMARCHY_THEMES_DIR",
    str(Path.home() / ".config/omarchy/themes"),
))

# Variants are named after their character, not the reference scheme that
# seeded them. The output palettes are derived from each wallpaper's own
# colors, so the labels describe what the user actually sees:
#   mono     -> greyscale ramp + single vivid accent (seeded by local mono ref)
#   warm     -> warm-biased accent (seeded by gruvbox)
#   cool     -> cool-biased, muted (seeded by nord)
#   material -> highest contrast, boldest saturation (seeded by Material Design)
SHORT_NAMES = {
    "mono":     "mono",
    "gruvbox":  "warm",
    "nord":     "cool",
    "material": "material",
    "aether":   "aether",
}
SHORT_LABEL = {
    "mono":     "Mono",
    "warm":     "Warm",
    "cool":     "Cool",
    "material": "Material",
    "aether":   "Aether",
}
MAX_SLUG_LEN = 36

_SLUG_NONWORD = re.compile(r"[^a-z0-9]+")


def slugify(s: str, max_len: int = MAX_SLUG_LEN) -> str:
    s = _SLUG_NONWORD.sub("-", s.lower()).strip("-")
    if len(s) <= max_len:
        return s
    cut = s[:max_len]
    last_dash = cut.rfind("-")
    return cut[:last_dash] if last_dash > 8 else cut


# ----- Lab math (self-contained) -----

def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


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
    return "#{:02x}{:02x}{:02x}".format(
        int(round(_linear_to_srgb(r) * 255)),
        int(round(_linear_to_srgb(g) * 255)),
        int(round(_linear_to_srgb(b2) * 255)),
    )


def shift_L(hex_: str, delta: float) -> str:
    L, a, b = hex_to_lab(hex_)
    return lab_to_hex(max(0.0, min(100.0, L + delta)), a, b)


def desaturate(hex_: str, factor: float) -> str:
    L, a, b = hex_to_lab(hex_)
    return lab_to_hex(L, a * factor, b * factor)


def blend(h1: str, h2: str, t: float) -> str:
    L1, a1, b1 = hex_to_lab(h1)
    L2, a2, b2 = hex_to_lab(h2)
    return lab_to_hex(L1 * (1 - t) + L2 * t, a1 * (1 - t) + a2 * t, b1 * (1 - t) + b2 * t)


# ----- colors.toml parsing + Aether derivation -----

KV_RE = re.compile(r'^(?P<key>\w+)\s*=\s*"(?P<val>#[0-9a-fA-F]{6})"\s*$')


def parse_colors_toml(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = KV_RE.match(line.strip())
        if m:
            out[m["key"]] = m["val"].lower()
    return out


def derive_aether(c: dict[str, str]) -> dict[str, str]:
    """Build the slot map the neovim template renders against.

    Prefers values already present in colors.toml (the new Omarchy
    expanded format writes named shades + accents directly), falling
    back to deriving them when the slot is absent (legacy / minimal
    colors.toml).
    """
    bg = c["background"]
    fg = c["foreground"]

    # muted is biased toward whichever end is darker so it reads as
    # "dim" in both dark and light themes.
    bg_L = hex_to_lab(bg)[0]
    fg_L = hex_to_lab(fg)[0]
    muted_t = 0.65 if bg_L < fg_L else 0.35
    derived_muted = desaturate(blend(fg, bg, muted_t), 0.5)

    def take(key, fallback):
        """Read `key` from the parsed colors.toml; otherwise use `fallback`."""
        return c.get(key, fallback)

    return {
        "bg":          take("bg",         bg),
        "dark_bg":     take("dark_bg",    shift_L(bg, -3)),
        "darker_bg":   take("darker_bg",  shift_L(bg, -6)),
        "lighter_bg":  take("lighter_bg", shift_L(bg, 8)),
        "fg":          take("fg",         fg),
        "dark_fg":     take("dark_fg",    shift_L(fg, -15)),
        "light_fg":    take("light_fg",   shift_L(fg, 5)),
        "bright_fg":   take("bright_fg",  shift_L(fg, 10)),
        "muted":       take("muted",      derived_muted),
        "red":         take("red",    c["color1"]),
        "yellow":      take("yellow", c["color3"]),
        "orange":      take("orange", blend(c["color1"], c["color3"], 0.5)),
        "green":       take("green",  c["color2"]),
        "cyan":        take("cyan",   c["color6"]),
        "blue":        take("blue",   c["color4"]),
        # Slot renamed from `purple` -> `magenta` to align with Omarchy
        # upstream (basecamp/omarchy#5856). `take()` accepts the new name
        # but also falls back to the old `purple` key so colors.toml
        # files generated before the rename still feed the template.
        "magenta":     c.get("magenta", c.get("purple", c["color5"])),
        "brown":       take("brown",  desaturate(shift_L(c["color3"], -20), 0.7)),
        "bright_red":     take("bright_red",     c["color9"]),
        "bright_yellow":  take("bright_yellow",  c["color11"]),
        "bright_green":   take("bright_green",   c["color10"]),
        "bright_cyan":    take("bright_cyan",    c["color14"]),
        "bright_blue":    take("bright_blue",    c["color12"]),
        "bright_magenta": c.get("bright_magenta", c.get("bright_purple", c["color13"])),
        "accent":               c["accent"],
        "cursor":               c["cursor"],
        "foreground":           fg,
        "background":           bg,
        "selection_foreground": c.get("selection_foreground", fg),
        "selection_background": c.get("selection_background", shift_L(bg, 8)),
    }


PLACEHOLDER_RE = re.compile(r'\{([a-z_][a-z0-9_]*)\}')


def render_template(text: str, mapping: dict[str, str]) -> str:
    return PLACEHOLDER_RE.sub(lambda m: mapping.get(m.group(1), m.group(0)), text)


# ----- per-wallpaper packaging -----

def package_one(rel: str, entry: dict, base: str, template_text: str) -> dict | None:
    """Package the three variants for one wallpaper. Returns the enriched
    `themes` metadata dict to be merged back into the sidecar.
    """
    src_img = ROOT / rel
    if not src_img.is_file():
        return None

    themes_field = entry.get("themes") or {}
    if not themes_field:
        return None

    ext = Path(rel).suffix
    enriched: dict[str, dict] = {}

    for scheme_name in list(themes_field.keys()):
        short = SHORT_NAMES.get(scheme_name)
        if not short:
            continue

        # `themes` field may already hold either the legacy "path/to/colors.toml"
        # string OR the enriched dict. Recover the source colors.toml path.
        prev = themes_field[scheme_name]
        if isinstance(prev, dict):
            source_rel = prev.get("source")
        else:
            source_rel = prev
        if not source_rel:
            source_rel = f"themes/{Path(rel).parent}/{Path(rel).stem}/{scheme_name}/colors.toml"
        theme_src = ROOT / source_rel
        if not theme_src.is_file():
            continue

        theme_name = f"{base}-{short}"
        theme_dir = TARGET / theme_name
        bg_dir = theme_dir / "backgrounds"
        bg_dir.mkdir(parents=True, exist_ok=True)

        toml_text = theme_src.read_text()
        (theme_dir / "colors.toml").write_text(toml_text)

        colors = parse_colors_toml(toml_text)
        aether = derive_aether(colors)
        (theme_dir / "neovim.lua").write_text(render_template(template_text, aether))

        bg_link = bg_dir / f"01-{base}{ext}"
        if bg_link.is_symlink() or bg_link.exists():
            bg_link.unlink()
        bg_link.symlink_to(src_img.resolve())

        rel_path = f"omarchy-themes/{theme_name}"
        enriched[scheme_name] = {
            "name": theme_name,
            "scheme": scheme_name,
            "path": rel_path,
            "colors_toml": f"{rel_path}/colors.toml",
            "neovim_lua": f"{rel_path}/neovim.lua",
            "background": f"{rel_path}/backgrounds/01-{base}{ext}",
            "source": source_rel,
            "colors": colors,
        }

    return enriched


def ensure_symlink(theme_dir: Path) -> int:
    """Symlink theme_dir into ~/.config/omarchy/themes/. Returns 1 if created
    or already correct, 0 if collision (existing non-symlink preserved).
    """
    link = OMARCHY_THEMES / theme_dir.name
    if link.is_symlink():
        try:
            if link.resolve() == theme_dir.resolve():
                return 1
        except OSError:
            pass
        link.unlink()
    elif link.exists():
        return 0
    link.symlink_to(theme_dir.resolve())
    return 1


# ----- sidecar helpers (so per-image runs are race-safe) -----

def load_sidecar_for(rel: str) -> tuple[Path, dict]:
    sidecar = MANIFEST_DIR / (Path(rel).with_suffix(".json"))
    if not sidecar.is_file():
        return sidecar, {}
    try:
        obj = json.loads(sidecar.read_text())
    except (json.JSONDecodeError, OSError):
        return sidecar, {}
    return sidecar, obj if isinstance(obj, dict) else {}


def write_sidecar(sidecar: Path, obj: dict) -> None:
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def load_all_sidecars() -> dict[str, tuple[Path, dict]]:
    """Return rel -> (sidecar_path, sidecar_obj). Each sidecar is a dict
    keyed by rel; usually one entry but the schema permits multiple.
    """
    out: dict[str, tuple[Path, dict]] = {}
    if not MANIFEST_DIR.is_dir():
        return out
    for sc in MANIFEST_DIR.rglob("*.json"):
        try:
            obj = json.loads(sc.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(obj, dict):
            continue
        for rel, entry in obj.items():
            if isinstance(entry, dict):
                out[rel] = (sc, obj)
    return out


# ----- slug assignment -----

def assign_slugs(entries: dict[str, dict]) -> dict[str, str]:
    """Returns rel -> theme base slug. Disambiguates duplicate titles with
    a stable -NN suffix in sorted-key order so reruns are deterministic.
    """
    groups: dict[str, list[str]] = {}
    for rel, e in entries.items():
        title = (e.get("title") or "").strip()
        slug = slugify(title) if title else slugify(Path(rel).stem)
        if not slug:
            slug = "untitled"
        groups.setdefault(slug, []).append(rel)

    base_for_rel: dict[str, str] = {}
    for slug, rels in groups.items():
        if len(rels) == 1:
            base_for_rel[rels[0]] = slug
        else:
            for i, rel in enumerate(sorted(rels), start=1):
                base_for_rel[rel] = f"{slug}-{i:02d}"
    return base_for_rel


# ----- main -----

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Process only this wallpaper (rel path or absolute)")
    args = ap.parse_args()

    if not TEMPLATE.is_file():
        print(f"missing template: {TEMPLATE}", file=sys.stderr)
        return 1
    template_text = TEMPLATE.read_text()

    TARGET.mkdir(parents=True, exist_ok=True)
    OMARCHY_THEMES.mkdir(parents=True, exist_ok=True)

    # Slug assignment needs the full set of titles to disambiguate. Always
    # load sidecars (not wallpapers.json) so per-image runs see fresh data.
    all_sidecars = load_all_sidecars()
    entries_for_slug = {rel: sidecar_obj.get(rel, {}) for rel, (_, sidecar_obj) in all_sidecars.items()}
    slugs = assign_slugs(entries_for_slug)

    if args.only:
        # Resolve --only to a rel path
        p = Path(args.only)
        try:
            rel = str(p.resolve().relative_to(ROOT)) if p.is_absolute() else str(p)
        except ValueError:
            print(f"--only path not under {ROOT}: {args.only}", file=sys.stderr)
            return 2
        if rel not in all_sidecars:
            print(f"no sidecar for {rel}", file=sys.stderr)
            return 2
        targets = [rel]
    else:
        targets = sorted(all_sidecars.keys())

    n_themes = 0
    n_wallpapers = 0
    n_skipped = 0
    for rel in targets:
        sidecar_path, sidecar_obj = all_sidecars[rel]
        entry = sidecar_obj.get(rel)
        if not isinstance(entry, dict):
            continue
        base = slugs.get(rel)
        if not base:
            n_skipped += 1
            continue

        enriched = package_one(rel, entry, base, template_text)
        if enriched is None:
            n_skipped += 1
            continue
        if not enriched:
            continue

        entry["themes"] = enriched
        sidecar_obj[rel] = entry
        write_sidecar(sidecar_path, sidecar_obj)

        n_wallpapers += 1
        n_themes += len(enriched)

    # Symlinking each packaged theme into ~/.config/omarchy/themes/ is
    # opt-in via OMARCHY_LINK=1. The default is off because writing
    # thousands of symlinks into the user's omarchy theme dir on every
    # bulk run is noisy and overwhelms the theme switcher with
    # auto-generated entries. Manual users who want them can run with
    # OMARCHY_LINK=1.
    n_linked = 0
    n_collision = 0
    if os.environ.get("OMARCHY_LINK") == "1":
        if args.only:
            base = slugs.get(targets[0])
            if base:
                for short in SHORT_NAMES.values():
                    theme_dir = TARGET / f"{base}-{short}"
                    if theme_dir.is_dir():
                        r = ensure_symlink(theme_dir)
                        n_linked += r
                        if r == 0:
                            n_collision += 1
        else:
            for theme_dir in sorted(TARGET.iterdir()):
                if not theme_dir.is_dir():
                    continue
                r = ensure_symlink(theme_dir)
                n_linked += r
                if r == 0:
                    n_collision += 1

    mode = f"--only {args.only}" if args.only else "bulk"
    print(
        f"[{mode}] packaged {n_themes} themes from {n_wallpapers} wallpapers into {TARGET}",
        file=sys.stderr,
    )
    if os.environ.get("OMARCHY_LINK") == "1":
        print(f"[{mode}] symlinked {n_linked} themes into {OMARCHY_THEMES}", file=sys.stderr)
        if n_collision:
            print(f"[{mode}] skipped {n_collision} symlinks (existing non-symlink entries)", file=sys.stderr)
    if n_skipped:
        print(f"[{mode}] skipped {n_skipped} entries", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
