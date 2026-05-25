#!/usr/bin/env python3
"""Add thumb_path and medium_path to each wallpapers.json entry."""

import json
import os
import sys

ROOT = "/home/bjarneo/Wallpapers"
PATH = os.path.join(ROOT, "wallpapers.json")


def cache_path(rel, kind):
    stem, _, _ = rel.rpartition(".")
    return f"cache/{kind}/{stem}.jpg"


def main():
    with open(PATH) as f:
        data = json.load(f)

    for rel, entry in data.items():
        entry["thumb_path"] = cache_path(rel, "thumb")
        entry["medium_path"] = cache_path(rel, "medium")

    with open(PATH, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)

    print(f"Updated {len(data)} entries", file=sys.stderr)


if __name__ == "__main__":
    main()
