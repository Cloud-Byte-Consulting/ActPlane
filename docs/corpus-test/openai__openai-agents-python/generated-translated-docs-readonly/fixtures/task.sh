#!/usr/bin/env bash
set -euo pipefail
python - <<'PY'
from pathlib import Path

path = Path("docs/zh/index.md")
text = path.read_text()
path.write_text(text.replace("search:\n  exclude: true", "search:\n  exclude: false", 1))
PY
