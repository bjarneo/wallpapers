#!/usr/bin/env python3
"""Prune stale entries and add width/height/dimensions/size_bytes to wallpapers.json."""

import json
import os
import re
import sys

ROOT = "/home/bjarneo/Wallpapers"
PATH = os.path.join(ROOT, "wallpapers.json")

WH_RE = re.compile(r"(\d+)x(\d+)_")


def main():
    with open(PATH) as f:
        data = json.load(f)

    pruned = 0
    updated = 0
    for rel in list(data.keys()):
        full = os.path.join(ROOT, rel)
        if not os.path.isfile(full):
            del data[rel]
            pruned += 1
            continue
        entry = data[rel]
        # size_bytes
        try:
            entry["size_bytes"] = os.path.getsize(full)
        except OSError:
            entry["size_bytes"] = None
        # width / height / dimensions from filename prefix
        m = WH_RE.search(os.path.basename(rel))
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            entry["width"] = w
            entry["height"] = h
            entry["dimensions"] = f"{w}x{h}"
        else:
            entry["width"] = None
            entry["height"] = None
            entry["dimensions"] = None
        updated += 1

    with open(PATH, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)

    print(f"Pruned: {pruned}", file=sys.stderr)
    print(f"Updated: {updated}", file=sys.stderr)
    print(f"Total entries: {len(data)}", file=sys.stderr)


if __name__ == "__main__":
    main()
