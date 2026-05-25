#!/usr/bin/env python3
"""Caption a single wallpaper via `claude -p` (Haiku 4.5) and merge the result
into its existing sidecar at cache/manifest/<rel>.json.

The LLM sees only the 256px thumb. The model is asked for a 3-5 word title,
a one-sentence description, and 5-8 lowercase subject-matter tags. Output is
merged into the existing entry; tone/color/theme tags are preserved.

Idempotent via the `llm_captioned: true` flag on the entry. Multiple instances
may run in parallel - each operates on a distinct sidecar.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WALLPAPERS_ROOT", "/home/bjarneo/Wallpapers"))
MODEL = os.environ.get("CAPTION_MODEL", "claude-haiku-4-5")
TIMEOUT = int(os.environ.get("CAPTION_TIMEOUT", 60))

PROMPT_TEMPLATE = (
    'Look at @{thumb} and output ONLY a JSON object with fields '
    '{{"title": "<3-5 word descriptive title>", '
    '"description": "<single concise sentence describing what is in the image>", '
    '"tags": ["<5-8 lowercase single-word tags about subject matter>"]}}. '
    'No markdown fences, no commentary, no explanation. Just the JSON object.'
)

JSON_RE = re.compile(r'\{[^{}]*"title".*?\}', re.DOTALL)


def main(argv):
    if len(argv) < 2:
        print("usage: caption-image.py <relpath>", file=sys.stderr)
        return 1

    rel = argv[1]
    if rel.startswith(str(ROOT)):
        rel = str(Path(rel).relative_to(ROOT))

    stem = Path(rel).with_suffix("")
    thumb = ROOT / "cache" / "thumb" / f"{stem}.jpg"
    sidecar = ROOT / "cache" / "manifest" / f"{stem}.json"

    if not thumb.is_file():
        print(f"no-thumb\t{rel}", file=sys.stderr)
        return 1
    if not sidecar.is_file():
        print(f"no-sidecar\t{rel}", file=sys.stderr)
        return 1

    data = json.loads(sidecar.read_text())
    key = next(iter(data.keys()))
    entry = data[key]
    if entry.get("llm_captioned"):
        print(f"skip\t{rel}")
        return 0

    prompt = PROMPT_TEMPLATE.format(thumb=thumb)
    try:
        result = subprocess.run(
            ["claude", "--model", MODEL, "-p", prompt],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print(f"timeout\t{rel}", file=sys.stderr)
        return 1

    response = result.stdout
    m = JSON_RE.search(response)
    if not m:
        # Fallback: any {...} block
        m = re.search(r'\{.*\}', response, re.DOTALL)
    if not m:
        print(f"no-json\t{rel}", file=sys.stderr)
        return 1
    try:
        cap = json.loads(m.group(0))
    except json.JSONDecodeError:
        print(f"bad-json\t{rel}", file=sys.stderr)
        return 1

    # Merge into entry, preserving structural tags
    title = (cap.get("title") or "").strip()
    description = (cap.get("description") or "").strip()
    new_tags = [str(t).strip().lower() for t in (cap.get("tags") or []) if t]

    if title:
        entry["title"] = title
    if description:
        entry["description"] = description

    structural = []
    for t in entry.get("tags", []):
        if t in ("dark", "light") or t == entry.get("color") or t == entry.get("theme"):
            if t not in structural:
                structural.append(t)
    entry["tags"] = list(dict.fromkeys(structural + new_tags))
    entry["llm_captioned"] = True

    sidecar.write_text(json.dumps(data, indent=2, sort_keys=True))
    print(f"ok\t{rel}\t{title}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
