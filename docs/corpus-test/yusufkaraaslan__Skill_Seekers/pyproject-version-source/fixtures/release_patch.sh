#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
from pathlib import Path

path = Path("src/skill_seekers/_version.py")
text = path.read_text()
path.write_text(
    text.replace(
        'return "3.6.0"  # Hardcoded fallback',
        'return "3.6.1"  # Hardcoded fallback',
    )
)
PY
