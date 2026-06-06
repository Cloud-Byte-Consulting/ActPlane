#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
from pathlib import Path

p = Path("CHANGELOG.md")
marker = "### Changes\n\n"
text = p.read_text(encoding="utf-8-sig")
p.write_text(
    text.replace(marker, marker + "- UI: note config panel spacing fix for a normal PR.\n", 1),
    encoding="utf-8",
)
PY
