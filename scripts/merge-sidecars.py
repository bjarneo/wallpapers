#!/usr/bin/env python3
"""Concatenate every cache/manifest/<path>.json sidecar into wallpapers.json.

Also prunes sidecars whose source file no longer exists. Run after a parallel
batch of process-image.py invocations - or any time you want wallpapers.json
to fully reflect the on-disk state of sidecars.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WALLPAPERS_ROOT", "/home/bjarneo/Wallpapers"))
MANIFEST_DIR = ROOT / "cache" / "manifest"
OUT = ROOT / "wallpapers.json"


def main():
    if not MANIFEST_DIR.is_dir():
        print(f"no manifest dir at {MANIFEST_DIR}", file=sys.stderr)
        return 1
    merged = {}
    pruned = 0
    bad = 0
    for sidecar in MANIFEST_DIR.rglob("*.json"):
        try:
            obj = json.loads(sidecar.read_text())
        except (json.JSONDecodeError, OSError):
            bad += 1
            continue
        if not isinstance(obj, dict):
            bad += 1
            continue
        for rel, entry in obj.items():
            src = ROOT / rel
            if not src.is_file():
                try: sidecar.unlink()
                except FileNotFoundError: pass
                pruned += 1
                continue
            merged[rel] = entry

    OUT.write_text(json.dumps(merged, indent=2, sort_keys=True))
    print(f"wrote {len(merged)} entries to {OUT}", file=sys.stderr)
    if pruned:
        print(f"pruned {pruned} stale sidecars", file=sys.stderr)
    if bad:
        print(f"skipped {bad} unreadable sidecars", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
