#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
from pathlib import Path

p = Path("src/browser_harness/helpers.py")
text = p.read_text()
p.write_text(text + "\n\ndef opaque_task_title_has(text):\n    return text.lower() in page_info().get('title', '').lower()\n")
PY
