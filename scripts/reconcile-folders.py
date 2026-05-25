#!/usr/bin/env python3
"""Move files so that each wallpaper lives under <tone>/<color>/ matching
the wallpapers.json `tone` and `color` fields (the latter is recomputed
from the dominant pixel color). Caches and JSON keys are kept in sync.

Default is dry-run. Pass --apply to perform moves.
"""

import json
import os
import shutil
import sys

ROOT = "/home/bjarneo/Wallpapers"
PATH = os.path.join(ROOT, "wallpapers.json")


def plan_move(rel, entry, taken):
    """Return a target relpath, choosing a `_N` suffix if the natural target collides."""
    tone = entry["tone"]
    color = entry["color"]
    parts = rel.split("/")
    if len(parts) < 3:
        return None
    cur_tone, cur_color = parts[0], parts[1]
    if cur_tone == tone and cur_color == color:
        return None
    basename = parts[-1]
    stem, _, ext = basename.rpartition(".")
    candidate = f"{tone}/{color}/{stem}.{ext}"
    n = 2
    while candidate in taken:
        candidate = f"{tone}/{color}/{stem}_{n}.{ext}"
        n += 1
    return candidate


def cache_path(rel, kind):
    stem, _, _ = rel.rpartition(".")
    return f"cache/{kind}/{stem}.jpg"


def main():
    apply = "--apply" in sys.argv

    with open(PATH) as f:
        data = json.load(f)

    moves = []          # (old_rel, new_rel)
    suffixed = []       # (old_rel, new_rel) where the natural target collided
    # `taken` tracks every existing path + every planned destination, so the
    # candidate-loop in plan_move() naturally avoids collisions.
    taken = set(data.keys())
    # Also account for files that exist on disk but aren't in the manifest
    for d in ("dark", "light"):
        full = os.path.join(ROOT, d)
        if not os.path.isdir(full):
            continue
        for sub in os.listdir(full):
            color_dir = os.path.join(full, sub)
            if not os.path.isdir(color_dir):
                continue
            for fn in os.listdir(color_dir):
                taken.add(f"{d}/{sub}/{fn}")

    for rel, entry in data.items():
        new_rel = plan_move(rel, entry, taken)
        if new_rel is None:
            continue
        natural = f"{entry['tone']}/{entry['color']}/{rel.split('/')[-1]}"
        if new_rel != natural:
            suffixed.append((rel, new_rel))
        taken.add(new_rel)
        moves.append((rel, new_rel))

    # Bucket-shift summary
    shifts = {}
    for old_rel, new_rel in moves:
        old_color = old_rel.split("/")[1]
        new_color = new_rel.split("/")[1]
        key = (old_color, new_color)
        shifts[key] = shifts.get(key, 0) + 1

    print(f"Planned moves: {len(moves)}")
    print(f"  of which suffixed to dodge collision: {len(suffixed)}")
    print()
    print("Top color shifts (from -> to: count):")
    for (old, new), n in sorted(shifts.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {old:>11} -> {new:<11}  {n}")

    if suffixed:
        print()
        print("Sample suffixed moves (first 5):")
        for old, new in suffixed[:5]:
            print(f"  {old}")
            print(f"    -> {new}")

    if not apply:
        print()
        print(f"(Dry-run. Rerun with --apply to execute {len(moves)} moves.)")
        return

    # Apply
    moved = 0
    failed = 0
    new_data = {}

    for rel, entry in data.items():
        new_data[rel] = entry  # placeholder; key may be rewritten below

    for old_rel, new_rel in moves:
        ok = True
        for src, dst in (
            (os.path.join(ROOT, old_rel), os.path.join(ROOT, new_rel)),
            (os.path.join(ROOT, cache_path(old_rel, "thumb")),
             os.path.join(ROOT, cache_path(new_rel, "thumb"))),
            (os.path.join(ROOT, cache_path(old_rel, "medium")),
             os.path.join(ROOT, cache_path(new_rel, "medium"))),
        ):
            if not os.path.exists(src):
                # cache may be missing; only the source is mandatory
                if src.endswith(old_rel):
                    print(f"  ! source missing, skipping: {old_rel}", file=sys.stderr)
                    ok = False
                    break
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                shutil.move(src, dst)
            except OSError as e:
                print(f"  ! move failed: {src} -> {dst}: {e}", file=sys.stderr)
                ok = False
                break
        if not ok:
            failed += 1
            continue
        # Rekey JSON and update cache paths
        entry = new_data.pop(old_rel)
        entry["thumb_path"] = cache_path(new_rel, "thumb")
        entry["medium_path"] = cache_path(new_rel, "medium")
        new_data[new_rel] = entry
        moved += 1

    with open(PATH, "w") as f:
        json.dump(new_data, f, indent=2, sort_keys=True)

    print()
    print(f"Moved:  {moved}")
    print(f"Failed: {failed}")
    print(f"wallpapers.json now has {len(new_data)} entries")


if __name__ == "__main__":
    main()
